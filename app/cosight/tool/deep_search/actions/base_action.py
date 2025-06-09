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
import warnings
import traceback
from typing import Any, List, Optional, Type, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from lagent import JsonParser, BaseAction, BaseParser, ActionReturn, ActionStatusCode
from lagent.actions.parser import ParseError

from app.cosight.tool.deep_search.common.prompts import select_example1_cn, select_example2_cn
from app.common.logger_util import logger

class ZTEActionParser(JsonParser):
    model_format: str = ''

    def parse_outputs(self, outputs: Any, name: str) -> List[dict]:
        res = super().parse_outputs(outputs)
        logger.info(f"ZTEActionParser >>>>>>>>>> name: {name}, model_format: {self.model_format}")
        if self.model_format.lower().startswith('internlm') or self.model_format.lower().startswith('model_qwen'):
            return res

        if name == 'search':
            res[0]['content'] += select_example1_cn
        if name == 'select':
            res[0]['content'] += select_example2_cn
        return res


class ManusBaseAction(BaseAction):
    def __init__(self,
                 description: Optional[dict] = None,
                 parser: Type[BaseParser] = ZTEActionParser,
                 enable: bool = True,
                 model_format: str = '',
                 **kwargs):
        self.search_results = None
        self.images = {}
        super().__init__(description, parser, enable)
        self._parser.model_format = model_format

    def __call__(self, inputs: str, name='run') -> ActionReturn:
        fallback_args = {'inputs': inputs, 'name': name}
        if not hasattr(self, name):
            return ActionReturn(
                fallback_args,
                type=self.name,
                errmsg=f'invalid API: {name}',
                state=ActionStatusCode.API_ERROR)
        try:
            inputs = self._parser.parse_inputs(inputs, name)
        except ParseError as exc:
            return ActionReturn(
                fallback_args,
                type=self.name,
                errmsg=exc.err_msg,
                state=ActionStatusCode.ARGS_ERROR)
        try:
            outputs = getattr(self, name)(**inputs)
        except Exception as exc:
            logger.error(f"ManusBaseAction call {name} error >>>>>>>>>> {exc}", exc_info=True)

            return ActionReturn(
                inputs,
                type=self.name,
                errmsg=str(exc),
                state=ActionStatusCode.API_ERROR)
        if isinstance(outputs, ActionReturn):
            action_return = outputs
            if not action_return.args:
                action_return.args = inputs
            if not action_return.type:
                action_return.type = self.name
        else:
            result = self._parser.parse_outputs(outputs, name)
            action_return = ActionReturn(inputs, type=self.name, result=result)
        return action_return

    def search(self, query: Union[str, List[str]]) -> dict:
        logger.info(f"开始执行搜索，查询内容：{query}")
        queries = query if isinstance(query, list) else [query]

        search_results = self._search_by_searcher(queries, self.searcher)        
        self.search_results = {
            idx: result
            for idx, result in enumerate(search_results.values())
        }
        logger.debug(f"索引化后的搜索结果：{json.dumps(self.search_results, ensure_ascii=False)}")
        return self.search_results

    def _search_by_searcher(self, queries: List[str], searcher) -> dict:
        logger.info(f"开始并行搜索，查询数量：{len(queries)}")
        search_results = {}
        with ThreadPoolExecutor() as executor:
            future_to_query = {
                executor.submit(searcher.search, q): q
                for q in queries
            }

            for future in as_completed(future_to_query):
                query = future_to_query[future]
                try:
                    results = future.result()
                    logger.info(f"查询 '{query}' 返回结果：{json.dumps(results, ensure_ascii=False)}")
                except Exception as exc:
                    logger.error(f"查询 '{query}' 发生异常：{str(exc)}", exc_info=True)
                    warnings.warn(f'{query} generated an exception: {exc}')
                else:
                    self.images[query] = results.get('images', [])
                    for result in results.get('content', []).values():
                        if result['url'] not in search_results:
                            search_results[result['url']] = result
                        else:
                            search_results[result['url']]['summ'] += f"\n{result['summ']}"

        logger.info(f"并行搜索完成，共获得 {len(search_results)} 条唯一结果")
        return search_results

    def select(self, select_ids: List[int]) -> dict:
        """get the detailed content on the selected pages.

        Args:
            select_ids (List[int]): list of index to select. Max number of index to be selected is no more than 4.
        """
        logger.info(f"开始获取详细内容，选择的索引：{select_ids}")
        
        if not self.search_results:
            error_msg = '没有可选择的搜索结果'
            logger.error(error_msg)
            raise ValueError('No search results to select from.')

        new_search_results = {}
        # 过滤出 URL 以 'None' 开头的条目
        for select_id in select_ids:
            if select_id in self.search_results:
                if self.search_results[select_id]['url'].startswith('None'):
                    new_search_results[select_id] = self.search_results[select_id].copy()
                    new_search_results[select_id]['content'] = new_search_results[select_id]['summ']
                    new_search_results[select_id].pop('summ')
                    new_search_results[select_id]['url'] = new_search_results[select_id]['url'].replace('None ', '')

        with ThreadPoolExecutor() as executor:
            future_to_id = {
                executor.submit(self.fetcher.fetch, self.search_results[select_id]['url']): select_id
                for select_id in select_ids
                if select_id in self.search_results and not self.search_results[select_id]['url'].startswith('None')
            }
            logger.info(f"已提交 {len(future_to_id)} 个内容获取任务")

            for future in as_completed(future_to_id):
                select_id = future_to_id[future]
                try:
                    web_success, web_content = future.result()
                    if isinstance(web_content, str):
                        try:
                            web_content = json.loads(web_content)
                        except:
                            pass
                    if isinstance(web_content, dict) and web_content.get('bo'):
                        web_content = web_content.get('bo').get('contentBody', '')
                except Exception as exc:
                    logger.error(f"获取索引 {select_id} 的内容时发生异常：{str(exc)}", exc_info=True)
                    warnings.warn(f'{select_id} generated an exception: {exc}')
                    new_search_results[select_id] = self.search_results[select_id].copy()
                    new_search_results[select_id]['content'] = new_search_results[select_id]['summ']
                    new_search_results[select_id].pop('summ')
                else:
                    if web_success:
                        # 确保 web_content 是字符串类型
                        content_str = str(web_content) if web_content is not None else ''
                        self.search_results[select_id]['content'] = content_str[:8192] if content_str else self.search_results[select_id]['summ']
                        new_search_results[select_id] = self.search_results[select_id].copy()
                        new_search_results[select_id].pop('summ')

        logger.info(f"内容获取完成，成功获取 {len(new_search_results)} 条内容")
        return new_search_results

    def open_url(self, url: str) -> dict:
        web_success, web_content = self.fetcher.fetch(url)
        if web_success:
            return {'type': 'text', 'content': web_content}
        else:
            return {'error': web_content}
