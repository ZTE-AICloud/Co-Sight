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

import time

from app.cosight.tool.deep_search.common.utils import extract_and_clean_tags, parse_content_properties
from app.cosight.tool.deep_search.common.entity import ModelInfo, SearchResult, WebSearchInfo
from app.cosight.tool.deep_search.model.model_service import ModelService
from app.cosight.tool.deep_search.services.flash_search_service import flash_search_handler
from app.cosight.tool.deep_search.common.i18n_service import i18n
from app.common.logger_util import logger

class DeepSearchToolkit:
    def __init__(self, model_info: ModelInfo, web_search_info: WebSearchInfo):
        base_url = model_info.get('base_url')
        if base_url and base_url.endswith('/'):
            base_url = base_url.rstrip('/')
        api_url = base_url + '/chat/completions' if base_url else model_info.get('api_url')
        model_info['api_url'] = api_url
        self.model_info = model_info
        self.web_search_info = web_search_info
        self.model_service = ModelService(model_info)
        i18n.set_locale("zh")

    async def deep_search(self, query: str) -> SearchResult:
        """Use deep-search to search information for the given query.

        Args:
            query (str): The query to be searched.

        Returns:
            SearchResult: A dictionary containing the search results:
                - analysis (str): Detailed analysis process for searching
                - summary (str): summary of the search results
        """
        start_time = time.time()
        
        params = {
            "content": [
                {
                    "type": "text",
                    "value": query
                }
            ],
            "history":[],
            "sessionInfo": {},
            "stream": True,
            "contentProperties": "{\"searchSourceTags\":\" #互联网:全网\",\"deepReasoningEnabled\":false}"
        }
        
        logger.info(f'deep search for ==============> {params}')
        question_with_source = params['content'][-1]['value']

        content_properties = parse_content_properties(params)
        search_source_tags = content_properties.get('searchSourceTags', '')
        logger.info(f'searchSourceTags ==============> {search_source_tags}')
        
        if search_source_tags:
            question_with_source = f"{question_with_source}\n\n{search_source_tags}"
        logger.info(f'question_with_source ==============> {question_with_source}')

        source_tags, raw_question = extract_and_clean_tags(question_with_source)
        logger.info(f'raw_question ==============> {raw_question}')
        search_sources = [
            {
                "id": 44,
                "type": "ManusWebSearch",
                "name": "互联网",
                "sub_name": "全网",
                "description": "系统默认的互联网搜索",
                "owner": "all",
                "source_from": "system_preset",
                "config": {
                    "url": "",
                    "spaces": None,
                    "workflow_id": ""
                }
            }
        ]
        
        # 准备传递给handler的参数
        search_params = {
            **params,  # 保留原有参数
            'search_engine': 'TavilySearch',
            'search_sources': search_sources,
            'rag_sources': [],
            'web_sources': search_sources
        }

        system_prompt = '\n'.join(params.get('systemPrompts', []) or [])
        history = params.get('history', []) or []
        result = await flash_search_handler(
            raw_question, 
            search_params, 
            question_with_source, 
            system_prompt, 
            history,
            self.web_search_info,
            self.model_service
        )
        
        logger.info(f"deep search cost ===============> {(time.time() - start_time):.2f} 秒")
        logger.info(f"deep search result ===============> {result}")
        return result


if __name__ == '__main__':
    import asyncio
    
    model_info = {
        "base_url": "https://api.deepseek.com/",
        "api_key": "sk-425469d1f43543cc87ab12ebf8c8e081",
        "model_name": "deepseek-chat",

    }
    web_search_info = {
        "api_key": "tvly-dev-123"
    }
    deep_search_toolkit = DeepSearchToolkit(model_info, web_search_info)
    result = asyncio.run(deep_search_toolkit.deep_search("介绍哪吒2"))
    logger.info(f"搜索结果 >>>>>>>>>>>>>>>>>>>>>>>> {result}")
