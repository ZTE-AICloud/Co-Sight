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

from typing import Any, Dict, List, Optional, TypedDict, Union

class SearchSourceType:
    ICENTER = "ZTEICenterDocument"
    RAG = "RAGKnowledgeLibrary"
    WEB = "ManusWebSearch"

class SearchSource(TypedDict):
    id: Union[int, str]
    type: SearchSourceType
    name: str
    sub_name: Optional[str]
    description: str
    owner: Optional[str]
    source_from: Optional[str]
    config: Optional[Dict]

class ContentItem(TypedDict):
    type: str
    value: str
    
class SearchParams(TypedDict):
    content: List[ContentItem]
    history: List[ContentItem]
    sessionInfo: Any
    stream: bool
    contentProperties: str

class SearchResult(TypedDict):
    analysis: str
    summary: str

class ModelInfo(TypedDict):
    base_url: Optional[str]
    api_url: str
    api_key: str
    model_name: str
    proxy: str
    
class WebSearchInfo(TypedDict):
    proxy: str
    api_key: str

