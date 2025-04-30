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

from typing import Any, TypedDict, Optional, List, Union, Dict
from enum import Enum

from pydantic import BaseModel

from cosight_server.deep_research.services.i18n_service import i18n
from cosight_server.sdk.common.config import custom_config


class AiSearchPlugin:
    @staticmethod
    def plugin_info():
        return {
            "name": i18n.t('ai_search_plugin_name'),
            "role": "copilot",
            "portrait": "assets/portrait_ai_search.png",
            "allow_file_types": [],
            "stream": True,
            "running_router": f"{custom_config.get('base_api_url')}/deep-research/search"
        }


class IcenterToken(TypedDict):
    auth_value: str
    emp_no: Union[int, str]
    username: Optional[Union[int, str]]
    space_ids: Optional[list[str]]


class SearchSourceType:
    ICENTER = "ZTEICenterDocument"
    RAG = "RAGKnowledgeLibrary"
    WEB = "WebSearch"


class RAGEnv:
    AIMNAE = "aim_nae"
    DNSTUDIO = "dn_studio"


class SearchSource(TypedDict):
    id: Union[int, str]
    type: SearchSourceType
    name: str
    sub_name: Optional[str]
    description: str
    owner: Optional[str]
    source_from: Optional[str]
    config: Optional[Dict]

class SearchParams(BaseModel):
    content: List[dict]
    sessionInfo: Dict[str, Any]
    headers: Optional[Dict[str, Any]] = {}
    systemPrompts: Optional[List[str]] = []
    history: Optional[List[dict]] = []
    from_script: Optional[bool] = None
    contentProperties: Optional[str] = ""
    
class ModelAdapterModelInfo(TypedDict):
    model: str
    interface: str
    service_name: str
    userName: Optional[str]
    tenantId: Optional[str]
    chat_url: Optional[str]
    complete_url: Optional[str]
    tag: Optional[Dict]
    safe_mode: Optional[str]
    scene: Optional[str]
    create_time: Optional[str]
    update_time: Optional[str]


class ApiKeyModel(BaseModel):
    user_id: Optional[str] = None
    key_name: Optional[str] = None
    key_value: Optional[str] = None
    create_time: Optional[str] = None
    observe1: Optional[str] = None
    observe2: Optional[str] = None


class ApiKey(TypedDict):
    id: Union[int, str]
    user_id: str
    key_name: str
    key_value: str
    create_time: str
    observe1: Optional[str]
    observe2: Optional[str]