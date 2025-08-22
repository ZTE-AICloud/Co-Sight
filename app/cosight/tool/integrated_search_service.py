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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import socket
import threading
from bs4 import BeautifulSoup
from urllib.parse import quote

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
            logger.info(f"开始选择类型为 '{source_type}' 的搜索源")
            logger.info(f"当前配置的搜索源总数: {len(self.search_sources)}")
            
            for i, source in enumerate(self.search_sources):
                source_type_actual = source.get('type')
                source_name = source.get('name', 'Unknown')
                source_sub_name = source.get('sub_name', 'Unknown')
                logger.info(f"搜索源 {i+1}: type='{source_type_actual}', name='{source_name}', sub_name='{source_sub_name}'")
                
                if source_type_actual == source_type:
                    sources.append(source)
                    logger.info(f"✓ 匹配到搜索源: {source_name}:{source_sub_name}")
            
            logger.info(f"类型 '{source_type}' 的搜索源选择完成，共找到 {len(sources)} 个")
            return sources
        except Exception as e:
            logger.error(f"选择搜索源时出错: {e}")
        return []
    
    async def rag_search_concurrent(self, query: str, max_concurrent: int = 6) -> Dict:
        """RAG并发检索：在所有RAG搜索源中并发搜索，返回所有内容"""
        rag_sources = self._pick_sources_by_type(SearchSourceType.RAG)
        if not rag_sources:
            raise ValueError('RAG搜索源未配置')
        
        logger.info(f"执行RAG并发搜索，查询: {query}，搜索源数量: {len(rag_sources)}，最大并发数: {max_concurrent}")
        
        # 显示所有RAG搜索源的详细信息
        for i, source in enumerate(rag_sources):
            source_name = source.get('name', 'RAG')
            source_sub_name = source.get('sub_name', 'default')
            source_id = source.get('id', 'unknown')
            logger.info(f"RAG搜索源 {i+1}: ID={source_id}, 名称={source_name}:{source_sub_name}")
        
        # 使用信号量控制并发数
        semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(f"限制最大并发数为{max_concurrent}")
        
        # 使用共享计数器跟踪完成的任务数量
        completed_counter = 0
        total_tasks = len(rag_sources)
        counter_lock = asyncio.Lock()
        
        # 存储所有搜索结果
        all_results = []
        
        async def process_rag_source(source_info):
            nonlocal completed_counter
            source = source_info
            source_name = f"{source.get('name', 'RAG')}:{source.get('sub_name', 'default')}"
            
            async with semaphore:
                logger.info(f"开始处理RAG搜索源: {source_name}")
                try:
                    result = await self._rag_search_single_source(query, source)
                    
                    # 安全地更新计数器
                    async with counter_lock:
                        completed_counter += 1
                        current_completed = completed_counter
                    
                    logger.info(f"完成处理RAG搜索源: {source_name} (已完成: {current_completed} / {total_tasks})")
                    
                    if result:
                        logger.info(f"RAG搜索源 {source_name} 返回了 {len(result)} 条结果")
                        # 合并搜索结果
                        for key, item in result.items():
                            all_results.append({
                                'key': key,
                                'item': item,
                                'source_name': source_name,
                                'source_type': SearchSourceType.RAG
                            })
                    else:
                        logger.warning(f"RAG搜索源 {source_name} 未返回结果")
                        
                except Exception as e:
                    # 安全地更新计数器
                    async with counter_lock:
                        completed_counter += 1
                        current_completed = completed_counter
                    
                    logger.error(f"RAG搜索源 {source_name} 搜索失败: {e} (已完成: {current_completed} / {total_tasks})")
        
        # 创建所有搜索任务
        search_tasks = [process_rag_source(source) for source in rag_sources]
        
        # 并发执行所有任务
        start_time = time.time()
        await asyncio.gather(*search_tasks, return_exceptions=True)
        total_time = time.time() - start_time
        
        logger.info(f"RAG并发搜索完成，总耗时: {total_time:.2f}s")
        
        # 合并所有搜索结果
        merged_results = {}
        result_offset = 0
        
        for result_info in all_results:
            new_key = str(int(result_info['key']) + result_offset)
            merged_results[new_key] = result_info['item']
            merged_results[new_key]['source_name'] = result_info['source_name']
            merged_results[new_key]['source_type'] = result_info['source_type']
            result_offset = len(merged_results)
        
        # 直接返回所有搜索结果，不进行筛选
        logger.info(f"RAG并发搜索完成，共返回 {len(merged_results)} 条结果")
        return merged_results
    
    async def _rag_search_single_source(self, query: str, source: Dict) -> Dict:
        """在单个RAG搜索源中搜索"""
        try:
            source_name = source.get('name', 'RAG')
            source_sub_name = source.get('sub_name', 'default')
            source_id = source.get('id', 'unknown')
            logger.info(f"开始搜索RAG搜索源: ID={source_id}, 名称={source_name}:{source_sub_name}")
            
            results = await self.rag_toolkit.search_by_source_async(query, source)
            
            logger.info(f"RAG搜索源 {source_name}:{source_sub_name} 搜索完成，返回 {len(results)} 条结果")
            return results
        except Exception as e:
            source_name = source.get('name', 'RAG')
            source_sub_name = source.get('sub_name', 'default')
            logger.error(f"RAG搜索源 {source_name}:{source_sub_name} 搜索失败: {e}")
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
    
    async def custom_search_concurrent(self, query: str, max_concurrent: int = 6) -> Dict:
        """自定义并发搜索：在所有类型为custom的自定义源中并发执行搜索"""
        custom_sources = self._pick_sources_by_type(SearchSourceType.CUSTOM)
        if not custom_sources:
            raise ValueError('自定义搜索源未配置')
        
        logger.info(f"执行自定义并发搜索，查询: {query}，搜索源数量: {len(custom_sources)}，最大并发数: {max_concurrent}")
        
        # 使用信号量控制并发数
        semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(f"限制最大并发数为{max_concurrent}")
        
        # 使用共享计数器跟踪完成的任务数量
        completed_counter = 0
        total_tasks = len(custom_sources)
        counter_lock = asyncio.Lock()
        
        # 存储所有搜索结果
        all_results = []
        
        async def process_custom_source(source_info):
            nonlocal completed_counter
            source = source_info
            source_name = f"{source.get('name', 'Custom')}:{source.get('sub_name', 'default')}"
            
            async with semaphore:
                logger.info(f"开始处理自定义搜索源: {source_name}")
                try:
                    result = await self._custom_search_single_source(query, source)
                    
                    # 安全地更新计数器
                    async with counter_lock:
                        completed_counter += 1
                        current_completed = completed_counter
                    
                    logger.info(f"完成处理自定义搜索源: {source_name} (已完成: {current_completed} / {total_tasks})")
                    
                    if result:
                        logger.info(f"自定义搜索源 {source_name} 返回了 {len(result)} 条结果")
                        # 合并搜索结果
                        for key, item in result.items():
                            all_results.append({
                                'key': key,
                                'item': item,
                                'source_name': source_name,
                                'source_type': SearchSourceType.CUSTOM
                            })
                    else:
                        logger.warning(f"自定义搜索源 {source_name} 未返回结果")
                        
                except Exception as e:
                    # 安全地更新计数器
                    async with counter_lock:
                        completed_counter += 1
                        current_completed = completed_counter
                    
                    logger.error(f"自定义搜索源 {source_name} 搜索失败: {e} (已完成: {current_completed} / {total_tasks})")
        
        # 创建所有搜索任务
        search_tasks = [process_custom_source(source) for source in custom_sources]
        
        # 并发执行所有任务
        start_time = time.time()
        await asyncio.gather(*search_tasks, return_exceptions=True)
        total_time = time.time() - start_time
        
        logger.info(f"自定义并发搜索完成，总耗时: {total_time:.2f}s")
        
        # 合并所有搜索结果
        merged_results = {}
        result_offset = 0
        
        for result_info in all_results:
            new_key = str(int(result_info['key']) + result_offset)
            merged_results[new_key] = result_info['item']
            merged_results[new_key]['source_name'] = result_info['source_name']
            merged_results[new_key]['source_type'] = result_info['source_type']
            result_offset = len(merged_results)
        
        return merged_results
    
    async def _custom_search_single_source(self, query: str, source: Dict) -> Dict:
        """在单个自定义搜索源中搜索"""
        try:
            logger.info(f"在自定义搜索源 {source.get('name', 'Custom')}:{source.get('sub_name', 'default')} 中搜索")
            results = await self.custom_toolkit.search_by_source_async(query, source)
            return results
        except Exception as e:
            logger.error(f"自定义搜索源 {source.get('name', 'Custom')} 搜索失败: {e}")
            return {}
    
    async def search_all_concurrent(self, query: str, max_concurrent: int = 6) -> Dict:
        """并发执行所有可用的搜索，限制并发数量"""
        results = {}
        
        # 收集所有搜索源
        all_sources = []
        source_types = []
        
        # RAG搜索源
        rag_sources = self._pick_sources_by_type(SearchSourceType.RAG)
        for source in rag_sources:
            all_sources.append(('rag', source))
            source_types.append(SearchSourceType.RAG)
        
        # 自定义搜索源
        custom_sources = self._pick_sources_by_type(SearchSourceType.CUSTOM)
        for source in custom_sources:
            all_sources.append(('custom', source))
            source_types.append(SearchSourceType.CUSTOM)
        
        if not all_sources:
            logger.warning("没有可用的搜索源")
            return results
        
        logger.info(f"开始并发搜索，总共 {len(all_sources)} 个搜索源，最大并发数: {max_concurrent}")
        
        # 使用信号量控制并发数
        semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(f"限制最大并发数为{max_concurrent}")
        
        # 使用共享计数器跟踪完成的任务数量
        completed_counter = 0
        total_tasks = len(all_sources)
        counter_lock = asyncio.Lock()
        
        # 存储所有搜索结果
        all_results = []
        
        async def process_search_source(source_info):
            nonlocal completed_counter
            source_type, source = source_info
            source_name = f"{source.get('name', source_type.title())}:{source.get('sub_name', 'default')}"
            
            async with semaphore:
                logger.info(f"开始处理{source_type.title()}搜索源: {source_name}")
                try:
                    if source_type == 'rag':
                        result = await self._rag_search_single_source(query, source)
                    elif source_type == 'custom':
                        result = await self._custom_search_single_source(query, source)
                    else:
                        logger.error(f"未知的搜索源类型: {source_type}")
                        return
                    
                    # 安全地更新计数器
                    async with counter_lock:
                        completed_counter += 1
                        current_completed = completed_counter
                    
                    logger.info(f"完成处理{source_type.title()}搜索源: {source_name} (已完成: {current_completed} / {total_tasks})")
                    
                    if result:
                        logger.info(f"{source_type.title()}搜索源 {source_name} 返回了 {len(result)} 条结果")
                        all_results.append({
                            'type': source_type,
                            'source': source,
                            'source_name': source_name,
                            'results': result
                        })
                    else:
                        logger.warning(f"{source_type.title()}搜索源 {source_name} 未返回结果")
                        
                except Exception as e:
                    # 安全地更新计数器
                    async with counter_lock:
                        completed_counter += 1
                        current_completed = completed_counter
                    
                    logger.error(f"{source_type.title()}搜索源 {source_name} 搜索失败: {e} (已完成: {current_completed} / {total_tasks})")
        
        # 创建所有搜索任务
        search_tasks = [process_search_source(source_info) for source_info in all_sources]
        
        # 并发执行所有任务
        start_time = time.time()
        await asyncio.gather(*search_tasks, return_exceptions=True)
        total_search_time = time.time() - start_time
        
        logger.info(f"所有并发搜索完成，总耗时: {total_search_time:.2f}s")
        
        # 合并所有搜索结果
        all_rag_results = {}
        all_custom_results = {}
        rag_offset = 0
        custom_offset = 0
        
        for result_info in all_results:
            source_type = result_info['type']
            source_name = result_info['source_name']
            result = result_info['results']
            
            if source_type == 'rag':
                for key, item in result.items():
                    new_key = str(int(key) + rag_offset)
                    all_rag_results[new_key] = item
                    all_rag_results[new_key]['source_name'] = source_name
                    all_rag_results[new_key]['source_type'] = SearchSourceType.RAG
                rag_offset = len(all_rag_results)
            elif source_type == 'custom':
                for key, item in result.items():
                    new_key = str(int(key) + custom_offset)
                    all_custom_results[new_key] = item
                    all_custom_results[new_key]['source_name'] = source_name
                    all_custom_results[new_key]['source_type'] = SearchSourceType.CUSTOM
                custom_offset = len(all_custom_results)
        
        # 合并结果
        if all_rag_results:
            results['rag'] = all_rag_results
        if all_custom_results:
            results['custom'] = all_custom_results
        
        return results
    
    # 保留原有的单源搜索方法以保持向后兼容
    def rag_search(self, query: str) -> Dict:
        """RAG检索：优先使用传入的RAG搜索源，返回所有内容"""
        source = self._pick_source(SearchSourceType.RAG)
        if not source:
            raise ValueError('RAG搜索源未配置')
        
        logger.info(f"执行RAG搜索，查询: {query}")
        results = self.rag_toolkit.search_by_source(query, source)
        
        # 直接返回所有搜索结果，不进行筛选
        logger.info(f"RAG搜索完成，共返回 {len(results)} 条结果")
        return results
    
    def custom_search(self, query: str) -> Dict:
        """自定义搜索：使用类型为custom的自定义源执行搜索"""
        source = self._pick_source(SearchSourceType.CUSTOM)
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
        self.max_retries = kwargs.get('max_retries', 2)
        self.retry_delay = kwargs.get('retry_delay', 1)
        self.max_concurrent = kwargs.get('max_concurrent', 3)  # 限制并发数
        
        # 创建线程锁和信号量
        self._lock = threading.Lock()
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        
        # 创建会话并配置连接池
        self.session = self._create_session_with_pool()
        
        super().__init__(description=description,
                         parser=parser,
                         enable=enable,
                         model_format=model_format,
                         **kwargs)
    
    def _create_session_with_pool(self):
        """创建带有连接池的会话"""
        session = requests.Session()
        
        # 配置连接池
        adapter = HTTPAdapter(
            pool_connections=5,      # 连接池大小
            pool_maxsize=10,         # 最大连接数
            max_retries=0,           # 禁用urllib3的重试，我们自己处理
            pool_block=False         # 不阻塞
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def cleanup(self):
        """清理资源"""
        if hasattr(self, 'session'):
            self.session.close()
    
    def __del__(self):
        """析构函数，确保资源被清理"""
        self.cleanup()

    def _make_post_request(self, url: str, data: dict, headers: dict, cookies: dict, proxies: dict, timeout: int):
        """执行POST请求"""
        try:
            return self.session.post(
                url=url,
                json=data,
                headers=headers,
                cookies=cookies,
                proxies=proxies,
                timeout=timeout,
                verify=False
            )
        except Exception as e:
            logger.error(f"POST请求执行失败: {e}")
            raise

    def _make_get_request(self, url: str, headers: dict, cookies: dict, proxies: dict, timeout: int):
        """执行GET请求"""
        try:
            return self.session.get(
                url=url,
                headers=headers,
                cookies=cookies,
                proxies=proxies,
                timeout=timeout,
                verify=False
            )
        except Exception as e:
            logger.error(f"GET请求执行失败: {e}")
            raise

    def _is_connection_error(self, exception):
        """判断是否为连接相关错误"""
        connection_errors = (
            requests.exceptions.ConnectionError,
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ReadTimeout,
            socket.error,
            OSError
        )
        return isinstance(exception, connection_errors) or (
            hasattr(exception, '__cause__') and 
            exception.__cause__ and 
            isinstance(exception.__cause__, connection_errors)
        )

    def _check_network_connectivity(self, host: str = "8.8.8.8", port: int = 53, timeout: int = 3):
        """检查网络连接性"""
        try:
            socket.setdefaulttimeout(timeout)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
            return True
        except socket.error:
            return False
        finally:
            socket.setdefaulttimeout(None)

    @tool_api
    def search(self, query: str) -> dict:
        """Custom Search API
        Args:
            query (str): question string for search
        """
        return super().search(query)

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
        selectors = config.get('selectors')
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

                    raw_response = self._handle_post_request_with_template(url, template_str, keyword, headers, cookies, proxies, self.timeout)

                    if isinstance(raw_response, list):
                        parsed_results = raw_response
                    else:
                        parsed_results = parse_func(raw_response)
                else:
                    # 使用带解析的GET请求处理
                    parsed_results = self._handle_get_request_with_parsing(url, keyword, template_str, selectors, headers, cookies, proxies, self.timeout, parse_func)
                    logger.info(f"解析结果类型: {type(parsed_results)}")

                # 验证并添加结果
                if isinstance(parsed_results, list):
                    for result in parsed_results:
                        if isinstance(result, dict) and all(k in result for k in ['url', 'title']):
                            # 确保结果格式正确
                            formatted_result = {
                                'result_id': result_count + 1,
                                'title': result.get('title', ''),
                                'description': result.get('content', result.get('summ', ''))[:500],
                                'url': result.get('url', ''),
                                'content': result.get('content', result.get('summ', ''))
                            }
                            all_results[str(result_count)] = formatted_result
                            result_count += 1
                        else:
                            logger.warning(f"跳过格式不正确的结果: {result}")
                else:
                    logger.warning(f"解析结果不是列表: {type(parsed_results)}")
                    # 尝试使用原始解析方法
                    result_count = self._parse_and_validate_results(parsed_results, parse_func, all_results, result_count)

            except requests.exceptions.ConnectionError as e:
                logger.error(f"网络连接错误，处理关键词 '{keyword}' 时出错: {str(e)}")
                continue
            except requests.exceptions.Timeout as e:
                logger.error(f"请求超时，处理关键词 '{keyword}' 时出错: {str(e)}")
                continue
            except requests.exceptions.RequestException as e:
                logger.error(f"HTTP请求错误，处理关键词 '{keyword}' 时出错: {str(e)}")
                continue
            except Exception as e:
                logger.error(f"处理关键词 '{keyword}' 时出错: {str(e)}", exc_info=True)
                continue

        if not all_results:
            raise ValueError("未找到任何搜索结果")

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
        selectors = config.get('selectors')
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
                async with self._semaphore:  # 限制并发数
                    if method == 'POST':
                        logger.info(f"请求URL: {url}")
                        logger.info(f"关键词: {keyword}")
                        logger.info(f"请求自带的cookie为: {cookies}")

                        raw_response = await asyncio.wait_for(
                            asyncio.to_thread(
                                self._handle_post_request_with_template,
                                url, template_str, keyword, headers, cookies, proxies, self.timeout
                            ),
                            timeout=self.timeout + 5
                        )

                        if isinstance(raw_response, list):
                            parsed_results = raw_response
                        else:
                            parsed_results = parse_func(raw_response)
                    else:
                        # 使用带解析的GET请求处理
                        parsed_results = await asyncio.wait_for(
                            asyncio.to_thread(
                                self._handle_get_request_with_parsing,
                                url, keyword, template_str, selectors, headers, cookies, proxies, self.timeout, parse_func
                            ),
                            timeout=self.timeout + 5
                        )
                        logger.info(f"解析结果类型: {type(parsed_results)}")

                    # 验证并添加结果
                    if isinstance(parsed_results, list):
                        for result in parsed_results:
                            if isinstance(result, dict) and all(k in result for k in ['url', 'title']):
                                # 确保结果格式正确
                                formatted_result = {
                                    'result_id': result_count + 1,
                                    'title': result.get('title', ''),
                                    'description': result.get('content', result.get('summ', ''))[:500],
                                    'url': result.get('url', ''),
                                    'content': result.get('content', result.get('summ', ''))
                                }
                                all_results[str(result_count)] = formatted_result
                                result_count += 1
                            else:
                                logger.warning(f"跳过格式不正确的结果: {result}")
                    else:
                        logger.warning(f"解析结果不是列表: {type(parsed_results)}")
                        # 尝试使用原始解析方法
                        result_count = self._parse_and_validate_results(parsed_results, parse_func, all_results, result_count)

            except requests.exceptions.ConnectionError as e:
                logger.error(f"网络连接错误，处理关键词 '{keyword}' 时出错: {str(e)}")
                continue
            except requests.exceptions.Timeout as e:
                logger.error(f"请求超时，处理关键词 '{keyword}' 时出错: {str(e)}")
                continue
            except requests.exceptions.RequestException as e:
                logger.error(f"HTTP请求错误，处理关键词 '{keyword}' 时出错: {str(e)}")
                continue
            except Exception as e:
                logger.error(f"处理关键词 '{keyword}' 时出错: {str(e)}", exc_info=True)
                continue

        if not all_results:
            raise ValueError("未找到任何搜索结果")

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

        parse_function_str = config.get('parseFunction')
        if not parse_function_str:
            raise ValueError("解析函数不能为空")

        return config, method, url, parse_function_str

    def _parse_function_from_string(self, func_str: str) -> callable:
        """将字符串形式的解析函数转换为可执行函数，并自动注入json模块"""
        # 允许的安全 builtins
        allowed_builtins = {
            "len": len,
            "range": range,
            "min": min,
            "max": max,
            "sum": sum,
            "sorted": sorted,
            "map": map,
            "filter": filter,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "enumerate": enumerate,
            "zip": zip,
            "abs": abs,
            "print": print,
            "json": json
        }

        # 禁止 import
        def fake_import(*args, **kwargs):
            raise ImportError("import is disabled in this environment")

        safe_globals = {
            "__builtins__": allowed_builtins,
            "__import__": fake_import
        }

        local_dict = {}
        try:
            exec(func_str, safe_globals, local_dict)
            if 'parse_response' not in local_dict:
                raise ValueError("必须定义一个名为 parse_response 的函数")
            return local_dict['parse_response']
        except Exception as e:
            logger.error(f"解析函数转换失败: {str(e)}")
            raise ValueError("解析函数格式无效") from e

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
            
            response = self.session.post(
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

    def _handle_post_request_with_template(self, url: str, template_str: str, keyword: str,
                                          headers: dict, cookies: dict, proxies: dict, timeout: int) -> str:
        """处理POST请求（带模板字符串）"""
        try:
            # 先替换模板字符串中的 $keyword
            template_str = template_str.replace("$keyword", keyword)
            data = json.loads(template_str)
            logger.info(f"POST数据: {data}")
            logger.info(f"proxies数据: {proxies}")

            response = self.session.post(
                url, json=data, headers=headers, cookies=cookies, proxies=proxies, verify=False, timeout=timeout
            )

            if response.status_code != 200:
                logger.error(f"POST请求失败: {response.status_code}")
                return []
            logger.info(f"POST返回的数据: {response.text}")

            if not response.text:
                # 返回一个默认的 JSON 字符串，内容为一个包含默认字段的列表
                default_result = [{
                    "url": "",
                    "title": "未获取到内容",
                    "content": "未获取到内容"
                }]
                return json.dumps(default_result)

            return response.text

        except json.JSONDecodeError:
            raise ValueError("POST请求模板格式无效")
        except UnicodeEncodeError as e:
            logger.error(f"编码错误: {str(e)}")
            raise ValueError(f"编码处理失败: {str(e)}")

    async def _handle_post_request_async(self, url: str, template: dict, keyword: str, headers: dict, cookies: dict, proxies: dict, timeout: int) -> str:
        """异步处理POST请求"""
        try:
            # 替换模板中的占位符
            data = self._replace_template_placeholders(template, keyword)
            
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._make_post_request,
                    url=url,
                    data=data,
                    headers=headers,
                    cookies=cookies,
                    proxies=proxies,
                    timeout=timeout
                ),
                timeout=timeout + 5
            )
            response.raise_for_status()
            return response.text
            
        except asyncio.TimeoutError:
            logger.error(f"POST请求超时: {url}")
            raise
        except requests.exceptions.ConnectionError as e:
            logger.error(f"POST请求连接错误: {url}, 错误: {e}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"POST请求失败: {url}, 错误: {e}")
            raise
        except Exception as e:
            logger.error(f"POST请求未知错误: {url}, 错误: {e}")
            raise

    def _handle_get_request(self, url: str, template: dict, keyword: str, headers: dict, cookies: dict, proxies: dict, timeout: int) -> str:
        """处理GET请求"""
        try:
            # 替换URL中的占位符
            processed_url = self._replace_template_placeholders(url, keyword)
            
            response = self.session.get(
                url=processed_url,
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

    def _handle_get_request_with_parsing(self, url: str, keyword: str, params: dict,
                                        selectors: dict, headers: dict, cookies: dict, proxies: dict,
                                        timeout: int, parse_func=None) -> list:
        """处理GET请求并解析结果"""
        logger.info(f"keyword: {keyword}")
        logger.info(f"params (before replace): {params}")
        logger.info(f"请求用到的headers: {headers}")

        # 替换 params 中的 $keyword 占位符
        replaced_params = {}
        for k, v in params.items():
            if isinstance(v, str):
                replaced_params[k] = v.replace("$keyword", keyword)
            else:
                replaced_params[k] = v

        query_params = []
        for key, value in replaced_params.items():
            param_key = quote(key)
            param_value = quote(value) if isinstance(value, str) else quote(str(value))
            query_params.append(f"{param_key}={param_value}")

        search_url = f"{url}?{'&'.join(query_params)}"

        try:
            response = self.session.get(
                search_url, headers=headers, cookies=cookies, proxies=proxies, verify=False, timeout=timeout
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"GET请求失败: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        # 如果提供了解析函数，使用它来解析结果
        if parse_func:
            try:
                logger.info("使用前端提供的解析函数处理结果")
                results = parse_func(soup)
                logger.info(f"解析完成，获取到 {len(results) if results else 0} 条结果")
                return results
            except Exception as e:
                logger.error(f"解析函数执行失败: {str(e)}", exc_info=True)
                # 如果解析失败，可以尝试使用默认解析逻辑
                logger.info("尝试使用默认解析逻辑")

        # 默认解析逻辑（当没有提供解析函数或解析函数执行失败时使用）
        if not selectors:
            selectors = {
                'result': 'li.b_algo',
                'title': 'h2 a',
                'snippet': 'div.b_caption',
                'url': 'h2 a'
            }

        result_elements = soup.select(selectors['result'])
        if not result_elements:
            return []

        results = []
        for result in result_elements:
            try:
                title_elem = result.select_one(selectors['title'])
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)

                # 获取URL
                if selectors['url'] == selectors['title']:
                    url = title_elem.get('href', '')
                else:
                    url_elem = result.select_one(selectors['url'])
                    url = url_elem.get('href', '') if url_elem else ''

                if not (title and url):
                    continue

                # 获取摘要
                snippet_elem = result.select_one(selectors['snippet'])
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else "unknown"

                # 处理相对URL
                if url.startswith('/'):
                    base_url = url.split('?')[0]
                    url = f"{base_url}{url}"

                results.append({
                    "url": url,
                    "title": title,
                    "content": snippet[:1000] if snippet else "unknown"
                })
            except Exception as e:
                logger.error(f"处理搜索结果时出错: {str(e)}", exc_info=True)
                continue

        # 添加日志，查看处理后的结果
        logger.info(f"GET请求处理后的结果: {results}")
        return results

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

    def _parse_and_validate_results(self, parsed_results: list, parse_func, all_results: dict, result_count: int) -> int:
        """解析和验证搜索结果"""
        try:
            logger.info(f"parse_func: {parse_func}")
            logger.info(f"parsed_results: {parsed_results}")
            
            if isinstance(parsed_results, str):
                # 如果是字符串，尝试使用解析函数处理
                parsed_results = parse_func(parsed_results)
            
            if not isinstance(parsed_results, list):
                raise ValueError("解析函数返回值必须是列表（list）")

            for result in parsed_results:
                if isinstance(result, dict) and all(k in result for k in ['url', 'title']):
                    # 确保结果格式正确
                    formatted_result = {
                        'result_id': result_count + 1,
                        'title': result.get('title', ''),
                        'description': result.get('content', result.get('summ', ''))[:500],
                        'url': result.get('url', ''),
                        'content': result.get('content', result.get('summ', ''))
                    }
                    all_results[str(result_count)] = formatted_result
                    result_count += 1
                else:
                    logger.warning(f"跳过格式不正确的结果: {result}")
                        
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