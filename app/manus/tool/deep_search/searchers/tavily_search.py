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
import httpx
from typing import Optional, List
from lagent.actions.bing_browser import DuckDuckGoSearch

from app.manus.tool.deep_search.common.entity import SearchSource
from manus_server.sdk.common.logger_util import get_logger

logger = get_logger("ai-search")


class TavilySearch(DuckDuckGoSearch):
    """Tavily搜索引擎实现"""

    def __init__(self,
                 api_key: str,
                 proxy: Optional[str] = None,
                 topk: int = 10,
                 black_list: Optional[List[str]] = None,
                 web_source: Optional[SearchSource] = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.proxy = proxy
        self.topk = topk
        self.black_list = black_list or []
        self.api_url = "https://api.tavily.com/search"
        self.timeout = kwargs.get('timeout', 5)
        logger.info(f'TavilySearch timeout====> {self.timeout}')
        self.include_domains = []
        if web_source:
            urls = web_source.get('config', {}).get('urls', [])
            self.include_domains = urls

    def _call_ddgs(self, query: str, **kwargs) -> dict:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response = loop.run_until_complete(
                self._async_call_ddgs(query, **kwargs))
            return response
        finally:
            loop.close()

    async def _async_call_ddgs(self, query: str, **kwargs) -> dict:
        """实现Tavily搜索接口"""
        logger.info(f"开始Tavily搜索，查询内容: {query}")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "query": query,
            "max_results": self.topk,
            "search_depth": "advanced",
            "include_images": True,
            "exclude_domains": [
                "zhihu.com"
            ]
        }
        if self.include_domains:
            data["include_domains"] = self.include_domains

        try:
            logger.debug(f"正在连接Tavily API，URL: {self.api_url}")
            async with httpx.AsyncClient(proxy=self.proxy, timeout=self.timeout) as client:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    json=data
                )
                response.raise_for_status()
                response_data = response.json()

                # 重构返回格式
                if not isinstance(response_data.get('results'), list):
                    return []

                result = [
                    {
                        'title': item.get('title', ''),
                        'href': item.get('url', ''),
                        'body': item.get('content', '')[:400],
                        'score': item.get('score', '')
                    }
                    for item in response_data.get('results', [])
                    if item.get('score', 0) >= 0.4
                ]

                logger.info(f"Tavily搜索成功，返回结果数量: {len(result)}")
                return {
                    'content': result,
                    'images': response_data.get('images', [])
                }
        except httpx.HTTPError as e:
            logger.error(f"Tavily HTTP请求失败: {str(e)}, 状态码: {getattr(e.response, 'status_code', 'N/A')}, 响应内容: {getattr(e.response, 'text', 'N/A')}")
            return []
        except Exception as e:
            logger.error(f"Tavily搜索失败，详细错误: {str(e)}")
            return []

    def _parse_response(self, response: dict) -> dict:
        raw_results = []
        for item in response.get('content', []):
            raw_results.append((item['href'], item['description'] if 'description' in item else item['body'], item['title'], item['score']))
        results = self._filter_results(raw_results)
        images = response.get('images', [])
        return {
            'content': results,
            'images': images
        }
    
    def _filter_results(self, results: List[tuple]) -> dict:
        filtered_results = {}
        count = 0
        for url, snippet, title, score in results:
            if all(domain not in url for domain in self.black_list) and not url.endswith('.pdf'):
                filtered_results[count] = {
                    'url': url,
                    'summ': json.dumps(snippet, ensure_ascii=False)[1:-1],
                    'title': title,
                    'score': score
                }
                count += 1
                if count >= self.topk:
                    break
        return filtered_results