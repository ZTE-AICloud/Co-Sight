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
from typing import Optional, List, Union

from lagent import tool_api
from lagent.actions.bing_browser import ContentFetcher

# TavilySearch 不能删，作为eval创建searcher
from app.cosight.tool.deep_search.searchers.tavily_search import TavilySearch
from app.cosight.tool.deep_search.actions.web_page_reader import ContentFetcher
from app.cosight.tool.deep_search.actions.base_action import ManusBaseAction
from app.cosight.tool.deep_search.common.entity import SearchSource
from app.common.logger_util import logger


class ManusWebSearch(ManusBaseAction):
    """Wrapper around the Web Browser Tool.
    """
    def __init__(self,
                 timeout: int = 5,
                 black_list: Optional[List[str]] = [
                     'enoN',
                     'youtube.com',
                     'bilibili.com',
                     'researchgate.net',
                 ],
                 topk: int = 20,
                 searcher_type: str = 'DuckDuckGoSearch',
                 web_source: Optional[SearchSource] = None,
                 api_key: str = None,
                 proxy: str = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.searcher_type = searcher_type
        self.black_list = black_list
        self.topk = topk
        self.api_key = api_key
        self.proxy = proxy
        kwargs['timeout'] = timeout
        self.kwargs = kwargs
        logger.info(f'ManusWebSearch timeout====> {timeout}')
        self.searcher = eval(searcher_type)(black_list=black_list, topk=topk, web_source=web_source, api_key=api_key, proxy=proxy, **kwargs)
        self.fetcher = ContentFetcher(proxy=proxy, timeout=timeout)

    @tool_api
    def search(self, query: Union[str, List[str]]) -> dict:
        """Web browser search API
        Args:
            query (List[str]): list of search query strings
        """
        return super().search(query)

    @tool_api
    def search_by_source(self, query: Union[str, List[str]], source: SearchSource) -> dict:
        self.searcher = eval(self.searcher_type)(black_list=self.black_list, topk=self.topk, web_source=source, api_key=self.api_key, proxy=self.proxy, **self.kwargs)
        logger.info(f"开始执行搜索，查询内容：{query}")
        queries = query if isinstance(query, list) else [query]

        search_results = self._search_by_searcher(queries, self.searcher)        
        self.search_results = {
            idx: result
            for idx, result in enumerate(search_results.values())
        }
        logger.debug(f"索引化后的搜索结果：{json.dumps(self.search_results, ensure_ascii=False)}")
        # return self.search_results
        return {
            'content': self.search_results,
            'images': self.images
        }

    @tool_api
    def select(self, select_ids: List[int]) -> dict:
        """get the detailed content on the selected pages.

        Args:
            select_ids (List[int]): list of index to select. Max number of index to be selected is no more than 4.
        """
        return super().select(select_ids)
