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

import json
import time
import re
import asyncio
from datetime import datetime
from typing import Any, Dict, List
from lagent.schema import ModelStatusCode
from lagent.actions import ActionExecutor

from app.cosight.tool.deep_search.common.i18n_service import i18n
from app.cosight.tool.deep_search.common.utils import parse_content_properties
from app.cosight.tool.deep_search.common.entity import SearchResult, SearchSourceType, WebSearchInfo
from app.cosight.tool.deep_search.common.prompts import select_example1_cn, select_example2_cn
from app.cosight.tool.deep_search.actions.web_search import ManusWebSearch
from app.cosight.tool.deep_search.model.model_service import ModelService
from cosight_server.sdk.common.logger_util import get_logger

logger = get_logger("ai-search")

DEFAULT_SYSTEM_PROMPT = "你是一个专业的知识助手。"


class SearchContext:
    def __init__(self,
                 model_format=None,
                 search_engine=None,
                 search_sources=None,
                 models_used=None,
                 deepReasoningEnabled=False,
                 web_search_info=None):
        self.search_results = None
        self.context = ""
        self.images = {}
        self.models_used = models_used
        # 添加多种搜索工具的配置
        self.tools_config = [
            {
                'class': ManusWebSearch,
                'params': {
                    'searcher_type': search_engine,
                    'model_format': model_format,
                    'topk': 2 if deepReasoningEnabled else 5,
                    'proxy': web_search_info.get('proxy'),
                    'api_key': web_search_info.get('api_key'),
                    'timeout': 10
                }
            }
        ]

        # 初始化所有搜索工具
        tools = []
        for tool_config in self.tools_config:
            tool_class = tool_config['class']
            tool_params = tool_config['params']
            tools.append(tool_class(**tool_params))

        # 初始化 ActionExecutor
        self.action_executor = ActionExecutor(tools)
        self.search_sources = search_sources or []

    async def search(self, query: str):
        """执行搜索"""
        try:
            # 如果没有搜索源，使用默认搜索源
            if not self.search_sources or len(self.search_sources) == 0:
                logger.warning("没有指定搜索源，将使用默认搜索源")
                self.search_sources = [{"name": "iCenter", "sub_name": i18n.t('search_source_all_space'), "type": SearchSourceType.ICENTER}]

             # 对搜索源进行排序，将RAG类型的搜索源排在前面
            self.search_sources.sort(key=lambda x: 0 if x.get('type') == SearchSourceType.RAG else 1)

            # 提取关键词
            yield i18n.t('extracting_keywords')
            start_time = time.time()
            keywords = await extract_search_keywords(query, self.models_used.get('key_extractor'))
            total_time = time.time() - start_time
            if i18n.get_locale() == 'en':
                yield i18n.t('keywords_extracted_count', len(keywords), f"{total_time:.2f}")
            else:
                yield i18n.t('keywords_extracted', ', '.join([f'[{kw}]' for kw in keywords]), f"{total_time:.2f}")
            # 有多个搜索源时，并发执行搜索
            logger.info(f"将在 {len(self.search_sources)} 个搜索源中并发搜索")
            yield i18n.t('concurrent_search_start', len(self.search_sources))

            # 创建并发任务
            search_tasks = []
            for source in self.search_sources:
                search_tasks.append(self.perform_search_with_source_task(query, source, keywords))

            # 先通知用户所有搜索已启动
            for i, source in enumerate(self.search_sources):
                source_name = f"{source['name']}:{source['sub_name']}"
                yield i18n.t('source_search_start', source_name)

            # 并发执行所有搜索任务
            start_time = time.time()
            
            results = await asyncio.gather(*search_tasks)
            # 解包结果
            search_results_list, self.images = results[-1]

            total_search_time = time.time() - start_time
            yield i18n.t('all_searches_complete', total_search_time)

            # 处理所有搜索结果
            all_search_results = {}
            all_formatted_results = []
            all_results = []

            for i, search_result in enumerate(search_results_list):
                source = self.search_sources[i]
                source_name = f"{source['name']}:{source['sub_name']}"

                # 如果搜索结果为空或出错，继续下一个搜索源
                if not search_result or isinstance(search_result, dict) and search_result.get(
                        "type") == "unknown_result":
                    yield i18n.t('no_results_found_source', source_name)
                    continue

                # 处理搜索结果
                result_count = len(search_result.keys()) if isinstance(search_result, dict) else 0
                yield i18n.t('results_found', source_name, result_count)

                # 合并搜索结果
                offset = len(all_search_results)
                for key, item in search_result.items():
                    new_key = str(int(key) + offset)
                    all_search_results[new_key] = item

                    # 添加到格式化结果和结果列表
                    idx = len(all_formatted_results)
                    all_formatted_results.append(
                        f"[webpage {idx + 1} begin]\n**标题：{item['title']}**\n链接：{item['url']}\n正文：{item['content']}\n[webpage {idx + 1} end]")
                    all_results.append({
                        "title": item['title'],
                        "url": item['url'],
                        "source_name": source_name,
                        "source_type": source.get('type')
                    })

            # 如果没有找到任何结果
            if not all_results:
                logger.info("在所有搜索源中未找到任何相关结果")
                yield {"type": "unknown_result", "prefix_content": i18n.t('no_results_found_all_sources')}
                return

            # 设置搜索结果
            self.set_search_results(all_results)

            # 生成引文列表
            reference_list = self._generate_reference_list(all_results)
            yield i18n.t('references_found', len(all_results), "\n\n".join(reference_list))

            # 最后一个yield，标记为最终结果
            yield {"type": "final_result", "content": "\n".join(all_formatted_results)}

        except Exception as e:
            logger.error(f"搜索过程出错: {str(e)}", exc_info=True)
            yield {"type": "unknown_result", "prefix_content": i18n.t('search_error')}
            return

    def _generate_reference_list(self, all_results):
        """生成引文列表"""
        reference_list = []
        for i, item in enumerate(all_results, 1):
            # URL转换
            if item.get('url'):
                match = re.match(
                    r'^https://i\.zte\.com\.cn/zte-rd-icenter-contents/content/([a-zA-Z0-9]+)\?spaceId=([a-zA-Z0-9]+)$',
                    item['url'])
                if match:
                    content_id, space_id = match.groups()
                    item['url'] = f'https://i.zte.com.cn/#/shared/{space_id}/wiki/page/{content_id}/view'

            source_name = f" [{item.get('source_name', i18n.t('unknown_source'))}]" if 'source_name' in item else ""

            if item.get('source_type') == SearchSourceType.RAG:
                reference_list.append(i18n.t('reference_item_rag', i, source_name, i, item['url']))
            else:
                reference_list.append(i18n.t('reference_item', i, source_name, item['title'], item['url']))
        return reference_list

    async def perform_search_with_source_task(self, query, selected_search_source, keywords):
        """执行特定知识源的搜索任务（不产生中间状态更新）

        Args:
            query: 查询字符串
            selected_search_source: 选择的知识源

        Returns:
            搜索结果或错误信息
        """
        search_source_name = (selected_search_source['name'] + ':' + selected_search_source[
            'sub_name']) if selected_search_source else 'iCenter:全空间'
        search_type = selected_search_source.get('type') if selected_search_source else SearchSourceType.ICENTER
        logger.info(f"perform search with source task[{search_source_name}]({query}) =====> 在知识源 [{search_source_name}] 中检索相关信息")

        try:
            if search_type == SearchSourceType.RAG:
                # RAG有大模型参与，不需要提取关键词
                keywords = query

            start_time = time.time()
            logger.info(f"perform search with source task[{search_source_name}]({query}) =====> 正在搜索相关内容...")
            action_return = await self.execute_action_async(search_type + '.search_by_source',
                                                            {'query': keywords if search_type != SearchSourceType.RAG else query,
                                                             'source': selected_search_source})
            search_results = {}
            if action_return and action_return.result and len(action_return.result) >= 0:
                search_results_str = action_return.result[0]['content'].replace(select_example1_cn, "").replace(
                    select_example2_cn, "")
                search_results = json.loads(search_results_str)

            total_time = time.time() - start_time
            logger.info(f"perform search with source task[{search_source_name}]({query}) =====> 已搜索到 {len(search_results.keys())} 条相关内容 ({total_time:.2f}s)")

            images = search_results.get('images', [])
            search_results = search_results.get('content', {})
            
            # 检查搜索结果是否为空
            if list(search_results.keys()) == ['0'] and search_results['0']['summ'] == "unknown":
                return {"type": "unknown_result"}

            logger.info(f"perform search with source task[{search_source_name}]({query}) =====> 正在分析搜索结果相关性，可能需要一些时间...")
            start_time = time.time()
            relevant_indices = await analyze_search_results(query, search_results,
                                                            self.models_used.get('result_analyst'))
            total_time = time.time() - start_time
            logger.info(f"perform search with source task[{search_source_name}]({query}) =====> 已筛选到 {len(relevant_indices)} 条相关内容 ({total_time:.2f}s)")

            logger.info(f"perform search with source task[{search_source_name}]({query}) =====> 正在读取内容...")
            start_time = time.time()
            action_return = await self.execute_action_async(search_type + '.select', {'select_ids': relevant_indices})

            total_time = time.time() - start_time
            if not action_return.result or len(action_return.result) == 0:
                logger.info(f"perform search with source task[{search_source_name}]({query}) =====> 未读取到任何内容 ({total_time:.2f}s)")
                return {"type": "unknown_result"}

            search_content_results = action_return.result[0]['content'].replace(select_example1_cn, "").replace(
                select_example2_cn, "")
            search_content_results = json.loads(search_content_results)
            logger.info(
                f"perform search with source task[{search_source_name}]({query}) =====> 已读取到 {len(search_content_results.keys())} 条相关内容 ({total_time:.2f}s)")

            # 搜索到相关网页，但没有获取到实际内容的时候，将之前搜索到的网页一起发给模型进行总结输出
            if len(relevant_indices) > 0 and len(search_content_results.keys()) == 0:
                logger.info(f"perform search with source task[{search_source_name}]({query}) =====> 搜索到相关网页，但没有获取到实际内容，将之前搜索到的网页摘要作为搜索结果")
                search_content_results = {
                    str(k): {
                        "url": v["url"],
                        "content": v["summ"],
                        "title": v["title"]
                    } for k, v in search_results.items()
                }

            return search_content_results, images

        except Exception as e:
            logger.error(f"perform search with source task[{search_source_name}]({query}) =====> 在知识源 [{search_source_name}] 中搜索时出错: {str(e)}", exc_info=True)
            return {"type": "unknown_result"}

    async def execute_action_async(self, action_name, params):
        """异步执行action_executor操作

        Args:
            action_name: 操作名称
            params: 操作参数

        Returns:
            操作结果
        """
        # 使用线程池执行同步操作，避免阻塞事件循环
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.action_executor(action_name, params)
        )

    def set_search_results(self, results):
        self.search_results = results

    def add_context(self, text):
        self.context += "\n" + text


async def rewrite_question(query: str, llm, chat_history) -> list:
    """使用大模型重组和优化问题。"""
    prompt = f"""
    请根据提供的历史问答对和当前问题，重写用户问题，重写问题请参考历史对话信息将代词替换为明确表示。只输出你改写后的结果，**不要有其他任何内容**。

    # 示例1：
      - *历史问答对：
        Human：请给我一首李白的诗？ Assistant: 《静夜思》窗前明月...
      - *用户问题：
        杜甫的呢？
      - *重写问题：
        请给我一首杜甫的诗？

    # 示例2：
      - *历史问答对：
        Human：请给我一首李白的诗？ Assistant: 《静夜思》窗前明月...
      - *用户问题：
        秦始皇是如何统一天下的?
      - *重写问题：
        秦始皇是如何统一天下的?

    # 示例3：
      - *历史问答对：

      - *用户问题：
        今天天气怎么样？
      - *重写问题：
        2025-03-06天气怎么样？

    # 问题：
      - *历史问答对：
        ***历史问答对start***
        ```
        {chat_history}
        ```
        ***历史问答对end***
      - *用户问题：
        {query}
      - *重写问题：
    """

    messages = [
        {
            "role": "system",
            "content": f"""
    你是一个专业的问题重写的专家。请按以下规则处理用户输入：
    1. **当前时间**：现在是{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

    2. **识别时间关键词**：扫描句子中是否包含以下类别的时间词（不区分中英文及大小写）：
       - **精确时间**：今天、今早、今晚、此时、此刻等
       - **相对日期**：本周/这周、周末、这个月、本季度、今年、明天、下周、下个月等
       - **模糊时段**：最近、近来、这段时间、眼下、当下等
       - **过去/未来**：昨天、上周、去年、明晚、下季度等

    3. **时间转换规则**：
       - 若为**精确日期**（如今天/明天），替换为当前日期的实际值（示例：今天→2023-10-24）
       - 若为**相对日期**（如本周/下个月），计算基于当前时间的起止日期（示例：本周→2023-10-23至2023-10-29）
       - 若为**模糊时段**，保持原词不做转换（示例：最近→最近）
       - 若含**节日/季节**（如春节、圣诞节），返回节日具体日期（需接入日历API）

    4. **输出要求**：
       - 替换时间关键词时，保持原句内容不变
       - 时间格式统一为`YYYY-MM-DD`或范围`YYYY-MM-DD至YYYY-MM-DD`
       - 无法识别的时间词保留原文
    {"5. **请使用英文进行回答**" if i18n.get_locale() == 'en' else ""}
    """
        },
        {"role": "user", "content": prompt}
    ]
    logger.info(f"rewrite_question ======>messages: {messages}")
    try:
        response = await llm.chat(messages)
        logger.info(f"rewrite_question ======>response: {response}")

        # 清理响应文本,去除引号和多余空格
        return clear_model_response(response)
    except Exception as e:
        logger.error(f"提取关键词失败: {e}", exc_info=True)
        return query


async def analyze_search_results(query: str, search_results: dict, llm) -> list:
    """使用LLM分析搜索结果的相关性并返回相关索引列表"""
    prompt = f"""请分析以下搜索结果与问题"{query}"的相关性。
搜索结果格式为: {{"0": {{"title": "标题", "url": "链接", "summ": "摘要"}}, "1": {{"title": "标题", "url": "链接", "summ": "摘要"}}...}}

搜索结果如下：
{json.dumps(search_results, ensure_ascii=False, indent=2)}

请仔细分析每个搜索结果的标题(title)和内容(summ)，找出可能回答问题的结果，稍微严格一些。
只需返回索引数字(从0开始)，用逗号分隔,例如"0,2,5"，如果没有匹配的搜索结果则输出""。
不要包含任何其他解释或文字。"""

    messages = [
        {"role": "system", "content": "你是一个专业的搜索结果分析助手，请根据相关性分析搜索结果。"},
        {"role": "user", "content": prompt}
    ]
    logger.info(f"analyze_search_results messages ========> {json.dumps(messages, ensure_ascii=False, indent=2)}")
    try:
        response = await llm.chat(messages)

        # 清理响应文本,去除引号和多余空格
        cleaned_response = clear_model_response(response)

        logger.info(f"analyze_search_results response ========> {cleaned_response}")

        # 提取返回的索引列表
        indices = [int(idx.strip()) for idx in cleaned_response.split(',')] if cleaned_response else []
        return indices
    except Exception as e:
        logger.error(f"分析搜索结果失败: {e}", exc_info=True)
        return [0, 1, 2]  # 发生错误时返回默认值


async def extract_search_keywords(query: str, llm) -> list:
    """使用LLM从问题中提取搜索关键词并返回关键词列表"""
    prompt = f"""你是一个专业的关键词提取助手，任务是从用户的问题中提炼出用于网络搜索的关键词。用户的问题是用中文提出的，你需要满足以下要求：

1. 提取4组关键词：两组中文、两组英文，其中英文关键词是对应中文的准确翻译。
2. 每组关键词应能独立支持一次完整覆盖用户问题的网络搜索。
3. 两组中文关键词应从不同的维度拆解问题（例如，一个从主题维度，一个从细节维度）。
4. 输出格式严格为：`中文组1,中文组2,英文组1,英文组2`，不同组间用半角逗号','分隔，组内关键词用空格分隔。
5. 关键词应简洁、准确，避免冗余。

以下是几个示例（few-shot）供参考：

**示例1**  
用户问题：如何在中国农村地区推广新能源电动车？  
输出：新能源电动车 中国农村, 推广策略 农村市场, new energy electric vehicles rural China, promotion strategies rural market

**示例2**  
用户问题：人工智能在医疗诊断中的最新进展是什么？  
输出：人工智能 医疗诊断, 最新进展 技术应用, artificial intelligence medical diagnosis, latest advancements technology application

**示例3**  
用户问题：我想了解上海的房价趋势和政策影响  
输出：上海房价 趋势, 政策影响 房地产, Shanghai housing prices trends, policy impact real estate

现在，请根据以下用户问题提取关键词并按要求输出：  
**用户问题：{query}**
    """

    messages = [
        {"role": "system", "content": "你是一个专业搜索关键词优化器，请根据以下指导原则从给定的问题中提炼出精准的网络搜索关键词。"},
        {"role": "user", "content": prompt}
    ]
    logger.info(f"extract_search_keywords ======>messages: {messages}")
    try:
        response = await llm.chat(messages)

        # 清理响应文本,去除引号和多余空格
        cleaned_response = clear_model_response(response)
        logger.info(f"extract_search_keywords ======>response: {cleaned_response}")

        # 提取返回的关键词列表,并将原始query作为第一个关键词
        keywords = [kw.strip() for kw in cleaned_response.split(',')]
        return [query, *keywords]
    except Exception as e:
        logger.error(f"提取关键词失败: {e}", exc_info=True)
        return [query]  # 发生错误时返回原始查询词


async def select_search_source(query: str, search_sources: list, llm) -> dict:
    prompt = f"""请从以下搜索源列表中选择最适合回答问题的搜索源：
搜索源列表："{json.dumps(search_sources, ensure_ascii=False, indent=2)}"

问题："{query}"

请返回搜索源的名称，例如 "iCenter:全空间"，注意输出的冒号要用:。

注意如果不能确定选哪种搜索源，则优先选择默认搜索源"""

    messages = [
        {"role": "system", "content": "你是一个专业的搜索源选择助手，请根据问题选择最适合的搜索源。"},
        {"role": "user", "content": prompt}
    ]
    logger.info(f"select_search_source ======>messages: {messages}")
    try:
        response = await llm.chat(messages)

        # 清理响应文本,去除引号和多余空格
        selected_search_source_name = clear_model_response(response)

        logger.info(f"select_search_source ======>response: {selected_search_source_name}")

        selected_search_source = next((source for source in search_sources if
                                       source['name'] + ':' + source['sub_name'] == selected_search_source_name), None)

        return selected_search_source if selected_search_source else search_sources[0]
    except Exception as e:
        logger.error(f"选择搜索源失败: {e}", exc_info=True)
        return search_sources[0]  # 发生错误时返回默认值

def create_chat_messages(query: str, context: str = "", system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> list:
    if context:
        logger.info(f"搜索到的资料长度: {len(context)}")
    """创建聊天消息列表"""
    prompt = f'''# 以下内容是基于用户发送的消息的搜索结果:
{context[:11000]}
在我给你的搜索结果中，每个结果都是[webpage X begin]...[webpage X end]格式的，X代表每篇文章的数字索引。请在适当的情况下在句子末尾引用上下文。请按照引用编号[citation:X]的格式在答案中对应部分引用上下文。如果一句话源自多个上下文，请列出所有相关的引用编号，例如[citation:3][citation:5]，切记不要将引用集中在最后返回引用编号，而是在答案对应部分列出。
在回答时，请注意以下几点：
- 今天是{datetime.now().strftime("%Y年%m月%d日")}。
- 并非搜索结果的所有内容都与用户的问题密切相关，你需要结合问题，对搜索结果进行甄别、筛选。
- 对于列举类的问题（如列举所有航班信息），尽量将答案控制在10个要点以内，并告诉用户可以查看搜索来源、获得完整信息。优先提供信息完整、最相关的列举项；如非必要，不要主动告诉用户搜索结果未提供的内容。
- 对于创作类的问题（如写论文），请务必在正文的段落中引用对应的参考编号，例如[citation:3][citation:5]，不能只在文章末尾引用。你需要解读并概括用户的题目要求，选择合适的格式，充分利用搜索结果并抽取重要信息，生成符合用户要求、极具思想深度、富有创造力与专业性的答案。你的创作篇幅需要尽可能延长，对于每一个要点的论述要推测用户的意图，给出尽可能多角度的回答要点，且务必信息量大、论述详尽。
- 如果回答很长，请尽量结构化、分段落总结。如果需要分点作答，尽量控制在5个点以内，并合并相关的内容。
- 对于客观类的问答，如果问题的答案非常简短，可以适当补充一到两句相关信息，以丰富内容。
- 你需要根据用户要求和回答内容选择合适、美观的回答格式，确保可读性强。
- 你的回答应该综合多个相关网页来回答，不能重复引用一个网页。
- 除非用户要求，否则你回答的语言需要和用户提问的语言保持一致。

# 用户消息为：
{query}'''

    return [{"role": "user", "content": prompt}]


async def stream_llm_chat(query: str, llm, context: str = "", system_prompt: str = DEFAULT_SYSTEM_PROMPT,
                          question_with_source: str = "",
                          search_source_ids: list = [], **kwargs):
    """进行流式对话"""
    full_messages = create_chat_messages(query, context, system_prompt)
    if i18n.get_locale() == "en":
        full_messages.append({"role": "user", "content": "请使用英文进行回答"})
    async for model_state, response, _ in llm.stream_chat(
            full_messages
    ):
        if model_state.value < 0:
            logger.error(f"LLM stream chat error: {response}")
            yield i18n.t('model_error')
            break
        if not response and model_state == ModelStatusCode.END:
            yield i18n.t('model_error')
            break
        if response:
            if model_state == ModelStatusCode.END:
                logger.info(f"{query} final_response =====> {response}")
            yield response


async def flash_search_handler(
    query: str, 
    params: Any, 
    question_with_source: str, 
    system_prompt: str, 
    history: List[Dict[str, Any]],
    web_search_info: WebSearchInfo,
    model_service: ModelService) -> SearchResult:
    """处理快速搜索请求
    Args:
        query: 搜索查询
        params: 搜索参数
        question_with_source: 带源的问题
        system_prompt: 系统提示
        history: 历史记录
    """
    # 从params中获取所有必要的配置
    search_sources = params.get('search_sources', [])
    search_engine = params.get('search_engine')
    model_format = 'model_qwen2_7b_int4'

    content_properties = parse_content_properties(params)
    deepReasoningEnabled = content_properties.get('deepReasoningEnabled', False)
    # 根据参数决定本次搜过过程中，各个步骤使用的模型
    models_used = model_service.deep_reasoning_models if deepReasoningEnabled else model_service.non_deep_reasoning_models

    chat_history = format_history(history)

    # 创建SearchContext实例
    search_ctx = SearchContext(
        model_format=model_format,
        search_engine=search_engine,
        search_sources=search_sources,
        models_used=models_used,
        deepReasoningEnabled=deepReasoningEnabled,
        web_search_info=web_search_info
    )

    # 从 search_sources 中提取 id
    search_source_ids = [source.get('id') for source in search_sources] if search_sources else []

    async def collect_results():
        """收集所有结果的辅助函数"""
        analysis_messages = []
        final_result = {"analysis": "", "summary": ""}

        analysis_messages.append(i18n.t('rewrite_question_start'))
        
        start_time = time.time()
        rewrited_query = await rewrite_question(query, models_used.get('question_rewriter'), chat_history)
        total_time = time.time() - start_time
        logger.info(f"flash_search_handler ======> 改写后的问题: {rewrited_query}")
        analysis_messages.append(i18n.t('rewrite_question_result', rewrited_query, total_time))

        summary_prefix = ''
        # 执行搜索并获取状态信息
        async for result in search_ctx.search(rewrited_query):
            if isinstance(result, dict):
                if result["type"] == "final_result":
                    search_ctx.add_context(result["content"])
                    break
                elif result["type"] == "unknown_result":
                    summary_prefix = result['prefix_content']
                    break
                elif result["type"] == "error":
                    analysis_messages.append(result['content'])
                    break
            else:
                analysis_messages.append(result)

        analysis_messages.append(i18n.t('retrieved_content_length', len(search_ctx.context)))
        analysis_messages.append(i18n.t('start_summarizing'))

        final_summary = ""
        async for response in stream_llm_chat(
                query=rewrited_query,
                llm=models_used.get('summary_generator'),
                context=search_ctx.context,
                question_with_source=question_with_source,
                search_source_ids=search_source_ids,
                system_prompt=system_prompt
        ):
            if "<think>" in response and "</think>" not in response:
                analysis_messages.append(response)
            elif "</think>" in response or ("<think>" not in response and "</think>" not in response):
                response = clear_model_response(response)
                processed_response = process_citations(response, search_ctx.search_results)
                final_summary = summary_prefix + processed_response

        final_result["analysis"] = "\n\n".join(analysis_messages)
        final_result["summary"] = final_summary
        # final_result["images"] = search_ctx.images
        return final_result

    return await collect_results()


def format_history(history, max_count=20):
    # 取最近的max_count条记录
    recent_history = history[-max_count:] if len(history) > max_count else history

    # 找出最近20条消息中所有 assistant 消息的索引
    assistant_indices = [
        i for i, msg in enumerate(recent_history)
        if msg.get("role") == "assistant"
    ]

    # 获取最后两条 assistant 消息的索引
    last_two_indices = set(assistant_indices[-2:]) if len(assistant_indices) >= 2 else set(assistant_indices)

    formatted_history = []
    for i, msg in enumerate(recent_history):
        role = msg.get("role", "")

        text = ""
        for item in msg.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text += item.get("value", "")

        # Human 消息直接添加
        if role == "user":
            formatted_history.append(f"Human: \"{text}\"")
        # Assistant 消息只添加最后两条
        elif role == "assistant" and i in last_two_indices:
            formatted_history.append(f"Assistant: \"{text}\"")

    return "\n\n".join(formatted_history)


def clear_model_response(response: str):
    """清除模型响应中的引号和思考标签"""
    # 移除<think>标签及其内容
    cleaned = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
    # 清除首尾的引号和空白
    return cleaned.strip().strip('"').strip("'")


def process_citations(response: str, search_results: list) -> str:
    """处理响应中的引用并添加URL

    Args:
        response: 模型响应文本
        search_results: 搜索结果列表

    Returns:
        处理后的文本，包含URL的引用
    """
    def replace_citation(match):
        try:
            # 获取引用编号（减1因为我们的索引从0开始，但显示从1开始）
            citation_num = int(match.group(1)) - 1
            if search_results and citation_num < len(search_results):
                url = search_results[citation_num].get('url', '')
                return f" [#{match.group(1)}]({url})"
            return ""  # 找不到对应结果时删除引用标记
        except (ValueError, IndexError):
            return ""  # 出错时删除引用标记

    # 使用正则表达式查找并替换引用
    pattern = r'\[citation:(\d+)\](?!\()'  # 匹配没有跟着URL的引用
    processed_response = re.sub(pattern, replace_citation, response)
    return processed_response.strip()