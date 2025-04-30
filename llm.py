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
import httpx
from openai import OpenAI, AzureOpenAI
from openai import OpenAI, AzureOpenAI

from app.cosight.llm.chat_llm import ChatLLM
from config.config import *


def set_model(model_config: dict[str, Optional[str | int | float]]):
    openai_llm = None
    http_client_kwargs = {
        "headers": {
            'Content-Type': 'application/json',
            'Authorization': model_config['api_key']
        },
        "verify": False,
        "trust_env": False
    }

    if model_config['proxy']:
        http_client_kwargs["proxy"] = model_config['proxy']
    if model_config['api_type'] == "azure" and model_config['api_version'] is not None:
        openai_llm = AzureOpenAI(
            base_url=model_config['base_url'],
            api_key=model_config['api_key'],
            api_version=model_config['api_version'],
            http_client=httpx.Client(**http_client_kwargs)
        )
    if model_config['api_type'] != "azure":
        openai_llm = OpenAI(
            base_url=model_config['base_url'],
            api_key=model_config['api_key'],
            http_client=httpx.Client(**http_client_kwargs)
        )
        

    chat_llm_kwargs = {
        "model": model_config['model'],
        "base_url": model_config['base_url'],
        "api_key": model_config['api_key'],
        "client": openai_llm
    }

    if model_config.get('max_tokens') is not None:
        chat_llm_kwargs['max_tokens'] = model_config['max_tokens']
    if model_config.get('temperature') is not None:
        chat_llm_kwargs['temperature'] = model_config['temperature']

    return ChatLLM(**chat_llm_kwargs)


plan_model_config = get_plan_model_config()
print(f"plan_model_config:{plan_model_config}\n")
llm_for_plan = set_model(plan_model_config)

act_model_config = get_act_model_config()
print(f"act_model_config:{act_model_config}\n")
llm_for_act = set_model(act_model_config)

tool_model_config = get_tool_model_config()
print(f"tool_model_config:{tool_model_config}\n")
llm_for_tool = set_model(tool_model_config)

vision_model_config = get_vision_model_config()
print(f"vision_model_config:{vision_model_config}\n")
llm_for_vision = set_model(vision_model_config)
