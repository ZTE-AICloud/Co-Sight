# Copyright 2025 ZTE Corporation.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Any, Type
import requests
import hashlib
import os
from lagent.actions import tool_api
from lagent.actions.parser import BaseParser

from app.common.logger_util import logger
from app.cosight.tool.deep_search.common.entity import SearchSource, SearchSourceType
from app.cosight.tool.deep_search.actions.base_action import ZTEActionParser, ManusBaseAction

# 获取上传目录配置
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
upload_dir_env_key = os.getenv("UPLOAD_DIR_ENV")
upload_dir_home = os.getenv(upload_dir_env_key) if upload_dir_env_key else None
upload_dir_home = upload_dir_home or root_dir
upload_dir = os.path.join(upload_dir_home, "upload_files")


class IntegratedSearchService:
    """集成的搜索服务，包含RAG和自定义搜索功能，支持并发搜索多个知识源"""
    
    def __init__(self, search_sources: List[Dict] = None):
        """
        初始化集成搜索服务
        
        Args:
            search_sources: 搜索源配置列表
        """
        self.search_sources = search_sources or []
        self.rag_toolkit = RAGSearchToolkit()
        self.custom_toolkit = CustomSearchToolkit()
        
    def _pick_source(self, source_type: str) -> Optional[Dict]:
        """根据类型选择搜索源"""
        try:
            for source in self.search_sources:
                if source.get('type') == source_type:
                    return source
        except Exception as e:
            logger.error(f"选择搜索源时出错: {e}")
        return None
    
    def _pick_sources_by_type(self, source_type: str) -> List[Dict]:
        """根据类型选择多个搜索源"""
        try:
            sources = []
            for source in self.search_sources:
                if source.get('type') == source_type:
                    sources.append(source)
            return sources
        except Exception as e:
            logger.error(f"选择搜索源时出错: {e}")
        return []
    
    async def rag_search_concurrent(self, query: str) -> Dict:
        """RAG并发检索：在所有RAG搜索源中并发搜索，自动选择前3条内容输出"""
        rag_sources = self._pick_sources_by_type(SearchSourceType.RAG)
        if not rag_sources:
            raise ValueError('RAG搜索源未配置')
        
        logger.info(f"执行RAG并发搜索，查询: {query}，搜索源数量: {len(rag_sources)}")
        
        # 创建并发任务
        search_tasks = []
        for source in rag_sources:
            search_tasks.append(self._rag_search_single_source(query, source))
        
        # 并发执行所有搜索任务
        start_time = time.time()
        search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)
        total_search_time = time.time() - start_time
        logger.info(f"RAG并发搜索完成，耗时: {total_search_time:.2f}s")
        
        # 合并所有搜索结果
        all_results = {}
        result_offset = 0
        
        for i, search_result in enumerate(search_results_list):
            source = rag_sources[i]
            source_name = f"{source.get('name', 'RAG')}:{source.get('sub_name', 'default')}"
            
            # 处理异常情况
            if isinstance(search_result, Exception):
                logger.error(f"RAG搜索源 {source_name} 搜索失败: {search_result}")
                continue
                
            if not search_result:
                logger.warning(f"RAG搜索源 {source_name} 未返回结果")
                continue
            
            # 合并搜索结果
            for key, item in search_result.items():
                new_key = str(int(key) + result_offset)
                all_results[new_key] = item
                # 添加源信息
                all_results[new_key]['source_name'] = source_name
                all_results[new_key]['source_type'] = SearchSourceType.RAG
            
            result_offset = len(all_results)
        
        # 选择最多前三条
        try:
            if all_results:
                select_ids = list(all_results.keys()) if isinstance(list(all_results.keys())[0], int) else [int(k) for k in list(all_results.keys())]
                select_ids = select_ids[:3]
                detailed = await self._rag_select_concurrent(select_ids, all_results)
                return detailed or all_results
        except Exception as e:
            logger.error(f"RAG搜索结果处理失败: {e}")
            
        return all_results
    
    async def _rag_search_single_source(self, query: str, source: Dict) -> Dict:
        """在单个RAG搜索源中搜索"""
        try:
            logger.info(f"在RAG搜索源 {source.get('name', 'RAG')}:{source.get('sub_name', 'default')} 中搜索")
            results = await self.rag_toolkit.search_by_source_async(query, source)
            return results
        except Exception as e:
            logger.error(f"RAG搜索源 {source.get('name', 'RAG')} 搜索失败: {e}")
            return {}
    
    async def _rag_select_concurrent(self, select_ids: List[int], all_results: Dict) -> Dict:
        """并发选择RAG搜索结果"""
        try:
            new_search_results = {}
            for select_id in select_ids:
                if select_id in all_results:
                    new_search_results[select_id] = all_results[select_id].copy()
                    # 获取完整内容，限制长度
                    content = all_results[select_id].get('content', '')[:8192]
                    new_search_results[select_id]['content'] = content
                    
                    if self.rag_toolkit.save_reference:
                        source_id = all_results[select_id].get('source_id', 'default')
                        filepath = self.rag_toolkit._calculate_md5_and_save(content, source_id)
                        # 修复URL构建逻辑，确保使用正确的rag-reference端点
                        new_search_results[select_id]['url'] = f"rag-reference?source={filepath}"
                    else:
                        # 如果没有保存引用，使用原始URL或设置默认值
                        original_url = all_results[select_id].get('url', '')
                        if original_url and not original_url.startswith('/api/nae-deep-research/v1/work_space'):
                            new_search_results[select_id]['url'] = original_url
                        else:
                            # 如果原始URL是work_space格式，则设置为空
                            new_search_results[select_id]['url'] = ""
                    
                    # 移除不需要的字段，保持与百度搜索格式一致
                    new_search_results[select_id].pop('summ', None)
                        
            return new_search_results
        except Exception as e:
            logger.error(f"RAG选择结果失败: {e}")
            return {}
    
    async def custom_search_concurrent(self, query: str) -> Dict:
        """自定义并发搜索：在所有类型为WebSearch的自定义源中并发执行搜索"""
        web_sources = self._pick_sources_by_type(SearchSourceType.WEB)
        if not web_sources:
            raise ValueError('自定义搜索源未配置')
        
        logger.info(f"执行自定义并发搜索，查询: {query}，搜索源数量: {len(web_sources)}")
        
        # 创建并发任务
        search_tasks = []
        for source in web_sources:
            search_tasks.append(self._custom_search_single_source(query, source))
        
        # 并发执行所有搜索任务
        start_time = time.time()
        search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)
        total_search_time = time.time() - start_time
        logger.info(f"自定义并发搜索完成，耗时: {total_search_time:.2f}s")
        
        # 合并所有搜索结果
        all_results = {}
        result_offset = 0
        
        for i, search_result in enumerate(search_results_list):
            source = web_sources[i]
            source_name = f"{source.get('name', 'Web')}:{source.get('sub_name', 'default')}"
            
            # 处理异常情况
            if isinstance(search_result, Exception):
                logger.error(f"自定义搜索源 {source_name} 搜索失败: {search_result}")
                continue
                
            if not search_result:
                logger.warning(f"自定义搜索源 {source_name} 未返回结果")
                continue
            
            # 合并搜索结果
            for key, item in search_result.items():
                new_key = str(int(key) + result_offset)
                all_results[new_key] = item
                # 添加源信息
                all_results[new_key]['source_name'] = source_name
                all_results[new_key]['source_type'] = SearchSourceType.WEB
            
            result_offset = len(all_results)
        
        return all_results
    
    async def _custom_search_single_source(self, query: str, source: Dict) -> Dict:
        """在单个自定义搜索源中搜索"""
        try:
            logger.info(f"在自定义搜索源 {source.get('name', 'Web')}:{source.get('sub_name', 'default')} 中搜索")
            results = await self.custom_toolkit.search_by_source_async(query, source)
            return results
        except Exception as e:
            logger.error(f"自定义搜索源 {source.get('name', 'Web')} 搜索失败: {e}")
            return {}
    
    async def search_all_concurrent(self, query: str) -> Dict:
        """并发执行所有可用的搜索"""
        results = {}
        
        # 创建所有搜索任务
        search_tasks = []
        
        # RAG搜索任务
        rag_sources = self._pick_sources_by_type(SearchSourceType.RAG)
        if rag_sources:
            for source in rag_sources:
                search_tasks.append(self._rag_search_single_source(query, source))
        
        # 自定义搜索任务
        web_sources = self._pick_sources_by_type(SearchSourceType.WEB)
        if web_sources:
            for source in web_sources:
                search_tasks.append(self._custom_search_single_source(query, source))
        
        if not search_tasks:
            logger.warning("没有可用的搜索源")
            return results
        
        # 并发执行所有搜索任务
        logger.info(f"开始并发搜索，总共 {len(search_tasks)} 个搜索任务")
        start_time = time.time()
        search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)
        total_search_time = time.time() - start_time
        logger.info(f"所有并发搜索完成，耗时: {total_search_time:.2f}s")
        
        # 处理搜索结果
        all_rag_results = {}
        all_custom_results = {}
        rag_offset = 0
        custom_offset = 0
        
        # 处理RAG搜索结果
        for i, search_result in enumerate(rag_sources):
            if i < len(search_results_list):
                result = search_results_list[i]
                source = rag_sources[i]
                source_name = f"{source.get('name', 'RAG')}:{source.get('sub_name', 'default')}"
                
                if isinstance(result, Exception):
                    logger.error(f"RAG搜索源 {source_name} 搜索失败: {result}")
                    continue
                    
                if result:
                    for key, item in result.items():
                        new_key = str(int(key) + rag_offset)
                        all_rag_results[new_key] = item
                        all_rag_results[new_key]['source_name'] = source_name
                        all_rag_results[new_key]['source_type'] = SearchSourceType.RAG
                    rag_offset = len(all_rag_results)
        
        # 处理自定义搜索结果
        for i, search_result in enumerate(search_results_list[len(rag_sources):]):
            if i < len(web_sources):
                source = web_sources[i]
                source_name = f"{source.get('name', 'Web')}:{source.get('sub_name', 'default')}"
                
                if isinstance(search_result, Exception):
                    logger.error(f"自定义搜索源 {source_name} 搜索失败: {search_result}")
                    continue
                    
                if search_result:
                    for key, item in search_result.items():
                        new_key = str(int(key) + custom_offset)
                        all_custom_results[new_key] = item
                        all_custom_results[new_key]['source_name'] = source_name
                        all_custom_results[new_key]['source_type'] = SearchSourceType.WEB
                    custom_offset = len(all_custom_results)
        
        # 合并结果
        if all_rag_results:
            results['rag'] = all_rag_results
        if all_custom_results:
            results['custom'] = all_custom_results
        
        return results
    
    # 保留原有的单源搜索方法以保持向后兼容
    def rag_search(self, query: str) -> Dict:
        """RAG检索：优先使用传入的RAG搜索源，自动选择前3条内容输出"""
        source = self._pick_source(SearchSourceType.RAG)
        if not source:
            raise ValueError('RAG搜索源未配置')
        
        logger.info(f"执行RAG搜索，查询: {query}")
        results = self.rag_toolkit.search_by_source(query, source)
        
        try:
            if results:
                # 选择最多前三条
                select_ids = list(results.keys()) if isinstance(list(results.keys())[0], int) else [int(k) for k in list(results.keys())]
                select_ids = select_ids[:3]
                detailed = self.rag_toolkit.select(select_ids)
                return detailed or results
        except Exception as e:
            logger.error(f"RAG搜索结果处理失败: {e}")
            
        return results
    
    def custom_search(self, query: str) -> Dict:
        """自定义搜索：使用类型为WebSearch的自定义源执行搜索"""
        source = self._pick_source(SearchSourceType.WEB)
        if not source:
            raise ValueError('自定义搜索源未配置')
        
        logger.info(f"执行自定义搜索，查询: {query}")
        return self.custom_toolkit.search_by_source(query, source)
    
    def search_all(self, query: str) -> Dict:
        """执行所有可用的搜索"""
        results = {}
        
        # RAG搜索
        try:
            rag_results = self.rag_search(query)
            if rag_results:
                results['rag'] = rag_results
        except Exception as e:
            logger.error(f"RAG搜索失败: {e}")
        
        # 自定义搜索
        try:
            custom_results = self.custom_search(query)
            if custom_results:
                results['custom'] = custom_results
        except Exception as e:
            logger.error(f"自定义搜索失败: {e}")
        
        return results


class RAGSearchToolkit(ManusBaseAction):
    """RAG搜索工具包"""
    
    def __init__(self,
                 description: Optional[dict] = None,
                 parser: Type[BaseParser] = ZTEActionParser,
                 enable: bool = True,
                 model_format: str = '',
                 save_reference: bool = True,
                 **kwargs):
        self.search_results = None
        self.save_reference = save_reference
        super().__init__(description=description,
                        parser=parser, 
                        enable=enable,
                        model_format=model_format,
                        **kwargs)

    def _calculate_md5_and_save(self, text: str, source_id: str, base_dir: str = "rag_references") -> str:
        """根据文本内容计算MD5哈希值并保存文本到文件"""
        source_id = str(source_id)
        md5_hash = hashlib.md5(text.encode('utf-8'), usedforsecurity=False).hexdigest()
        
        os.makedirs(os.path.join(upload_dir, base_dir, source_id), exist_ok=True)
        
        filename = f"{md5_hash}.txt"
        filepath = os.path.join(base_dir, source_id, filename)
        full_path = os.path.join(upload_dir, filepath)
        
        if not os.path.exists(full_path):
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(text)
            logger.info(f"已保存引用文本到文件: {filepath}")
        else:
            logger.info(f"引用文本文件已存在，跳过保存: {filepath}")
            
        return filepath

    @tool_api
    def search_by_source(self, query: str, source: SearchSource) -> dict:
        """根据源执行RAG搜索"""
        result = self.search_for_answer(query, source)
        logger.info(f"RAG的问题: {query}")
        logger.info(f"RAG初始答案: {result.get('citation')}")
        search_results = {}
        if result.get('citation'):
            for idx, (title, citation_data) in enumerate(result['citation'].items()):
                if citation_data.get('type') == 'text' and citation_data.get('data'):
                    data = citation_data['data']
                    source_id = citation_data.get('source_id', 'default')
                    
                    # 修复URL设置逻辑，避免返回错误的work_space URL
                    original_url = data.get('source', '')
                    if original_url and original_url.startswith('/api/nae-deep-research/v1/work_space'):
                        # 如果是work_space格式的URL，设置为空，避免前端访问错误
                        url = ""
                    else:
                        url = original_url
                    # 修改返回格式，与百度搜索保持一致
                    search_results[idx] = {
                        "result_id": idx + 1,  # 添加result_id字段
                        "title": data.get('source', ''),  # 标题
                        "description": data.get('content_expand', '')[:500] if data.get('content_expand') else '',  # 描述（摘要）
                        "url": url,  # 使用修复后的URL
                        "content": data.get('content_expand', ''),  # 完整内容
                        "source_id": source_id  # 源ID
                    }
        logger.info(f"RAG搜索到的答案: {search_results}")
        self.search_results = search_results
        return self.search_results

    async def search_by_source_async(self, query: str, source: SearchSource) -> dict:
        """异步根据源执行RAG搜索"""
        result = await self.search_for_answer_async(query, source)
        logger.info(f"RAG的问题: {query}")
        logger.info(f"RAG初始答案: {result.get('citation')}")
        search_results = {}
        if result.get('citation'):
            for idx, (title, citation_data) in enumerate(result['citation'].items()):
                if citation_data.get('type') == 'text' and citation_data.get('data'):
                    data = citation_data['data']
                    source_id = citation_data.get('source_id', 'default')

                    # 修复URL设置逻辑，避免返回错误的work_space URL
                    original_url = data.get('source', '')
                    if original_url and original_url.startswith('/api/nae-deep-research/v1/work_space'):
                        # 如果是work_space格式的URL，设置为空，避免前端访问错误
                        url = ""
                    else:
                        url = original_url
                    # 修改返回格式，与百度搜索保持一致
                    search_results[idx] = {
                        "result_id": idx + 1,  # 添加result_id字段
                        "title": data.get('source', ''),  # 标题
                        "description": data.get('content_expand', '')[:500] if data.get('content_expand') else '',  # 描述（摘要）
                        "url": url,  # 使用修复后的URL
                        "content": data.get('content_expand', ''),  # 完整内容
                        "source_id": source_id  # 源ID
                    }
        logger.info(f"RAG搜索到的答案: {search_results}")
        self.search_results = search_results
        return self.search_results

    @tool_api
    def select(self, select_ids: List[int]) -> dict:
        """选择详细的搜索结果内容"""
        if not self.search_results:
            raise ValueError('No search results to select from.')

        new_search_results = {}
        for select_id in select_ids:
            if select_id in self.search_results:
                new_search_results[select_id] = self.search_results[select_id].copy()
                # 获取完整内容，限制长度
                content = self.search_results[select_id].get('content', '')[:8192]
                new_search_results[select_id]['content'] = content
                
                if self.save_reference:
                    source_id = self.search_results[select_id].get('source_id', 'default')
                    filepath = self._calculate_md5_and_save(content, source_id)
                    # 修复URL构建逻辑，确保使用正确的rag-reference端点
                    new_search_results[select_id]['url'] = f"rag-reference?source={filepath}"
                else:
                    # 如果没有保存引用，使用原始URL或设置默认值
                    original_url = self.search_results[select_id].get('url', '')
                    if original_url and not original_url.startswith('/api/nae-deep-research/v1/work_space'):
                        new_search_results[select_id]['url'] = original_url
                    else:
                        # 如果原始URL是work_space格式，则设置为空
                        new_search_results[select_id]['url'] = ""
                
                # 移除不需要的字段，保持与百度搜索格式一致
                new_search_results[select_id].pop('summ', None)
                    
        return new_search_results

    def search_for_answer(self, question: str, source: SearchSource = None) -> dict:
        """搜索答案"""
        try:
            with ThreadPoolExecutor() as executor:
                future = executor.submit(self._call_search, question, source)
                return future.result()
        except Exception as e:
            logger.exception(str(e))
            return {}

    async def search_for_answer_async(self, question: str, source: SearchSource = None) -> dict:
        """异步搜索答案"""
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._sync_search, question, source), timeout=50
            )
            return response
        except asyncio.TimeoutError:
            logger.exception('Request to RAG timed out.')
            return {}
        except Exception as e:
            logger.exception(str(e))
            return {}

    def _call_search(self, question: str, source: SearchSource = None) -> dict:
        """在独立线程中执行搜索"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(
                self._async_search(question, source))
            return response
        finally:
            loop.close()

    async def _async_search(self, question: str, source: SearchSource = None) -> dict:
        """异步搜索"""
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(self._sync_search, question, source), timeout=50
            )
            return response
        except asyncio.TimeoutError:
            logger.exception('Request to RAG timed out.')
            raise

    def _sync_search(self, question: str, source: SearchSource = None) -> dict:
        """同步搜索"""
        logger.info(f"========RAG question:{question}")
        logger.info(f"========RAG rag_source:{source}")

        if not source:
            logger.error("RAG source is None")
            return {}

        config = source.get('config', {})
        current_result = self._sync_aimnae_search(question, config)
        if current_result and current_result.get('citation'):
            for title, citation_data in current_result['citation'].items():
                citation_data['source_id'] = source.get('id', 'default')

        return current_result

    def _sync_aimnae_search(self, question: str, config: dict) -> dict:
        """处理AIM NAE环境下的同步搜索请求"""
        url = config.get("url")
        workflow_id = config.get("workflow_id")
        
        if not url or not workflow_id:
            logger.error(f"RAG配置不完整: url={url}, workflow_id={workflow_id}")
            return {}

        params = {
            "question": question,
            "workflow_id": workflow_id,
            "stream": False,
            "dialogue_id": "1112223334444"
        }
        headers = {}
        kwargs = config.get("kwargs")
        if kwargs:
            params["kwargs"] = kwargs
        headers["x-from-deepsearch"] = "true"

        logger.info(f"_sync_aimnae_search================>headers: {headers}")
        logger.info(f"_sync_aimnae_search================>url: {url}")
        logger.info(f"_sync_aimnae_search================>params: {params}")

        try:
            response = requests.post(url=url, json=params, headers=headers, verify=True)

            if response.status_code == 200:
                try:
                    data = response.json()
                    answer = data["data"]["answer"]
                    citation = data["data"]["citation"]
                    return dict(answer=answer, citation=citation)
                except json.JSONDecodeError:
                    error_message = response.text
                    logger.error(f"_sync_search: rag回答失败，{error_message}")
                    return {}
            else:
                logger.error(f"_sync_search: rag回答失败，状态码: {response.status_code}")
                return {}
        except requests.ConnectionError as e:
            logger.info(f"_sync_search: Connection failed: {e}")
            return {}
        except Exception as e:
            logger.info(f"_sync_search: An error occurred: {e}")
            return {}


class CustomSearchToolkit(ManusBaseAction):
    """自定义搜索工具包"""
    
    def __init__(self,
                 description: Optional[dict] = None,
                 parser: Type[BaseParser] = ZTEActionParser,
                 enable: bool = True,
                 model_format: str = '',
                 **kwargs):
        self.search_results = None
        self.timeout = kwargs.get('timeout', 30)
        super().__init__(description=description,
                         parser=parser,
                         enable=enable,
                         model_format=model_format,
                         **kwargs)

    @tool_api
    def search_by_source(self, query: str, source: SearchSource) -> dict:
        """根据源执行自定义搜索"""
        config, method, url, parse_function_str = self._validate_search_source(source, query)

        try:
            parse_func = self._parse_function_from_string(parse_function_str)
        except Exception as e:
            logger.error(f"解析函数配置错误: {str(e)}")
            raise ValueError("解析函数配置无效")

        configHeaders = config.get('headers', {})
        headers = self._prepare_headers(configHeaders)
        cookie_header = headers.pop('Cookie', None) or headers.pop('cookie', None)
        cookies = {}

        if cookie_header:
            for item in cookie_header.split(';'):
                if '=' in item:
                    key, value = item.split('=', 1)
                    cookies[key.strip()] = value.strip()
                    
        proxy = config.get('proxy')
        proxies = {'http': proxy, 'https': proxy} if proxy else None
        params = config.get('params', {})
        template_str = params.get('template') if params else None
        
        if isinstance(template_str, str) and method == 'GET':
            template_str = json.loads(template_str)
        if method == 'POST' and not template_str:
            raise ValueError("POST请求需要template参数")

        all_results = {}
        result_count = 0

        if isinstance(query, str):
            keywords = [query]
        elif isinstance(query, list):
            keywords = query
        else:
            logger.error(f"查询参数类型错误: {type(query)}")
            raise ValueError("查询参数必须是字符串或列表")

        logger.info(f"处理查询关键词: {keywords}")
        logger.info(f"合并后的headers是这样的: {headers}")
        logger.info(f"解析后的cookies是这样的: {cookies}")

        for keyword in keywords:
            try:
                if method == 'POST':
                    logger.info(f"请求URL: {url}")
                    logger.info(f"关键词: {keyword}")
                    logger.info(f"请求自带的cookie为: {cookies}")

                    raw_response = self._handle_post_request(url, template_str, keyword, headers, cookies, proxies, self.timeout)

                    if isinstance(raw_response, list):
                        parsed_results = raw_response
                    else:
                        parsed_results = parse_func(raw_response)
                else:
                    raw_response = self._handle_get_request(url, template_str, keyword, headers, cookies, proxies, self.timeout)
                    parsed_results = parse_func(raw_response)

                result_count = self._parse_and_validate_results(raw_response, parse_func, all_results, result_count)

            except Exception as e:
                logger.error(f"处理关键词 '{keyword}' 时出错: {str(e)}", exc_info=True)

        logger.info(f"自定义搜索完成，共获得 {len(all_results)} 条结果")
        self.search_results = all_results
        return all_results

    async def search_by_source_async(self, query: str, source: SearchSource) -> dict:
        """异步根据源执行自定义搜索"""
        config, method, url, parse_function_str = self._validate_search_source(source, query)

        try:
            parse_func = self._parse_function_from_string(parse_function_str)
        except Exception as e:
            logger.error(f"解析函数配置错误: {str(e)}")
            raise ValueError("解析函数配置无效")

        configHeaders = config.get('headers', {})
        headers = self._prepare_headers(configHeaders)
        cookie_header = headers.pop('Cookie', None) or headers.pop('cookie', None)
        cookies = {}

        if cookie_header:
            for item in cookie_header.split(';'):
                if '=' in item:
                    key, value = item.split('=', 1)
                    cookies[key.strip()] = value.strip()
                    
        proxy = config.get('proxy')
        proxies = {'http': proxy, 'https': proxy} if proxy else None
        params = config.get('params', {})
        template_str = params.get('template') if params else None
        
        if isinstance(template_str, str) and method == 'GET':
            template_str = json.loads(template_str)
        if method == 'POST' and not template_str:
            raise ValueError("POST请求需要template参数")

        all_results = {}
        result_count = 0

        if isinstance(query, str):
            keywords = [query]
        elif isinstance(query, list):
            keywords = query
        else:
            logger.error(f"查询参数类型错误: {type(query)}")
            raise ValueError("查询参数必须是字符串或列表")

        logger.info(f"处理查询关键词: {keywords}")
        logger.info(f"合并后的headers是这样的: {headers}")
        logger.info(f"解析后的cookies是这样的: {cookies}")

        for keyword in keywords:
            try:
                if method == 'POST':
                    logger.info(f"请求URL: {url}")
                    logger.info(f"关键词: {keyword}")
                    logger.info(f"请求自带的cookie为: {cookies}")

                    raw_response = await self._handle_post_request_async(url, template_str, keyword, headers, cookies, proxies, self.timeout)

                    if isinstance(raw_response, list):
                        parsed_results = raw_response
                    else:
                        parsed_results = parse_func(raw_response)
                else:
                    raw_response = await self._handle_get_request_async(url, template_str, keyword, headers, cookies, proxies, self.timeout)
                    parsed_results = parse_func(raw_response)

                result_count = self._parse_and_validate_results(raw_response, parse_func, all_results, result_count)

            except Exception as e:
                logger.error(f"处理关键词 '{keyword}' 时出错: {str(e)}", exc_info=True)

        logger.info(f"自定义搜索完成，共获得 {len(all_results)} 条结果")
        self.search_results = all_results
        return all_results

    def _validate_search_source(self, source: SearchSource, query: str) -> tuple:
        """验证搜索源配置"""
        if not source:
            raise ValueError("搜索源不能为空")

        config = source.get('config', {})
        if not config:
            raise ValueError("搜索源配置不能为空")

        method = config.get('method', 'GET').upper()
        if method not in ['GET', 'POST']:
            raise ValueError(f"不支持的HTTP方法: {method}")

        url = config.get('url')
        if not url:
            raise ValueError("URL不能为空")

        parse_function_str = config.get('parse_function')
        if not parse_function_str:
            raise ValueError("解析函数不能为空")

        return config, method, url, parse_function_str

    def _parse_function_from_string(self, function_str: str):
        """从字符串解析函数"""
        try:
            # 这里可以根据需要实现更复杂的函数解析逻辑
            # 目前返回一个简单的解析函数
            def parse_func(response_text):
                # 简单的解析逻辑，可以根据需要扩展
                return [{"title": "解析结果", "content": response_text[:500]}]
            return parse_func
        except Exception as e:
            logger.error(f"解析函数字符串失败: {e}")
            raise

    def _prepare_headers(self, config_headers: dict) -> dict:
        """准备请求头"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        headers.update(config_headers)
        return headers

    def _handle_post_request(self, url: str, template: dict, keyword: str, headers: dict, cookies: dict, proxies: dict, timeout: int) -> str:
        """处理POST请求"""
        try:
            # 替换模板中的占位符
            data = self._replace_template_placeholders(template, keyword)
            
            response = requests.post(
                url=url,
                json=data,
                headers=headers,
                cookies=cookies,
                proxies=proxies,
                timeout=timeout,
                verify=False
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"POST请求失败: {e}")
            raise

    async def _handle_post_request_async(self, url: str, template: dict, keyword: str, headers: dict, cookies: dict, proxies: dict, timeout: int) -> str:
        """异步处理POST请求"""
        try:
            # 替换模板中的占位符
            data = self._replace_template_placeholders(template, keyword)
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    requests.post,
                    url=url,
                    json=data,
                    headers=headers,
                    cookies=cookies,
                    proxies=proxies,
                    timeout=timeout,
                    verify=False
                ),
                timeout=timeout + 5
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"异步POST请求失败: {e}")
            raise

    def _handle_get_request(self, url: str, template: dict, keyword: str, headers: dict, cookies: dict, proxies: dict, timeout: int) -> str:
        """处理GET请求"""
        try:
            # 替换URL中的占位符
            url = self._replace_template_placeholders(url, keyword)
            
            response = requests.get(
                url=url,
                headers=headers,
                cookies=cookies,
                proxies=proxies,
                timeout=timeout,
                verify=False
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"GET请求失败: {e}")
            raise

    async def _handle_get_request_async(self, url: str, template: dict, keyword: str, headers: dict, cookies: dict, proxies: dict, timeout: int) -> str:
        """异步处理GET请求"""
        try:
            # 替换URL中的占位符
            url = self._replace_template_placeholders(url, keyword)
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    requests.get,
                    url=url,
                    headers=headers,
                    cookies=cookies,
                    proxies=proxies,
                    timeout=timeout,
                    verify=False
                ),
                timeout=timeout + 5
            )
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.error(f"异步GET请求失败: {e}")
            raise

    def _replace_template_placeholders(self, template: Any, keyword: str) -> Any:
        """替换模板中的占位符"""
        if isinstance(template, str):
            return template.replace('{query}', keyword)
        elif isinstance(template, dict):
            return {k: self._replace_template_placeholders(v, keyword) for k, v in template.items()}
        elif isinstance(template, list):
            return [self._replace_template_placeholders(item, keyword) for item in template]
        else:
            return template

    def _parse_and_validate_results(self, raw_response: str, parse_func, all_results: dict, result_count: int) -> int:
        """解析和验证搜索结果"""
        try:
            parsed_results = parse_func(raw_response)
            
            if isinstance(parsed_results, list):
                for result in parsed_results:
                    if isinstance(result, dict) and result.get('title') and result.get('content'):
                        # 修改返回格式，与百度搜索保持一致
                        all_results[result_count] = {
                            'result_id': result_count + 1,  # 添加result_id字段
                            'title': result['title'],  # 标题
                            'description': result['content'][:500] if result.get('content') else '',  # 描述（摘要）
                            'url': result.get('url', ''),  # URL
                            'content': result['content'],  # 完整内容
                            'summ': result['content'][:500]  # 保留summ字段以兼容现有代码
                        }
                        result_count += 1
                        
        except Exception as e:
            logger.error(f"解析函数执行失败: {str(e)}", exc_info=True)

        return result_count 

    @tool_api
    def select(self, select_ids: List[int]) -> dict:
        """选择详细的搜索结果内容"""
        if not self.search_results:
            raise ValueError('No search results to select from.')

        new_search_results = {}
        for select_id in select_ids:
            if select_id in self.search_results:
                new_search_results[select_id] = self.search_results[select_id].copy()
                # 获取完整内容，限制长度
                content = self.search_results[select_id].get('content', '')[:8192]
                new_search_results[select_id]['content'] = content
                
                # 移除不需要的字段，保持与百度搜索格式一致
                new_search_results[select_id].pop('summ', None)
                    
        return new_search_results 