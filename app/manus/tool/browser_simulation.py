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

# -*- coding: utf-8 -*-
from dotenv import load_dotenv
import asyncio

load_dotenv()

import os

from camel.models import ModelFactory
from camel.toolkits import (
    WebToolkit
)
from camel.types import ModelPlatformType, ModelType
from camel.configs import ChatGPTConfig
from camel.configs import DeepSeekConfig
from camel.configs import QwenConfig
from camel.configs import AnthropicConfig
import os


def browser_simulation(task_prompt: str, start_url: str, round_limit: int = 20):
    web_model = ModelFactory.create(
        model_platform=ModelPlatformType.QWEN,
        model_type=ModelType.QWEN_VL_MAX,
        api_key="",
        model_config_dict=QwenConfig(temperature=0, top_p=1).as_dict(),
    )
    planning_model = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=ModelType.GPT_4O_MINI,
        api_key="",
        model_config_dict=ChatGPTConfig(temperature=0, top_p=1).as_dict(),
    )
    webToolkit = WebToolkit(
        history_window=10,
        headless=True,  # Set to True for headless mode (e.g., on remote servers)
        web_agent_model=web_model,
        planning_agent_model=planning_model,
    )
    try:
        result = webToolkit.browser_simulation(task_prompt, start_url, round_limit)
        print(f'browser_simulation execute result = {result}')
        return result
    except Exception as ex:
        print(f'browser_simulation execute error {str(ex)}')
    return ""


def brower_use_cal(task_prompt: str, start_url: str):
    print(f"Using Tool: {browser_simulation}")
    try:
        return browser_simulation(task_prompt, start_url)
    except Exception as ex:
        print(f'brower_use_cal execute error {str(ex)}')


if __name__ == '__main__':
    import os

    # 代理服务器地址
    proxy = "http://proxyhk.zte.com.cn:80"

    # 设置 HTTP 和 HTTPS 代理
    os.environ['ALL_PROXY'] = ''
    os.environ['all_proxy'] = ''
    os.environ['SOCKS_PROXY'] = ''
    os.environ['socks_proxy'] = ''
    os.environ['HTTPS_PROXY'] = proxy
    os.environ['https_proxy'] = proxy
    os.environ['HTTP_PROXY'] = proxy
    os.environ['http_proxy'] = proxy
    os.environ['URL_CONTEXT_PATH'] = 'proxy'
    # __import__('pysqlite3')
    # import sys
    #
    # sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
    result = brower_use_cal("搜索并输出关于哪吒的信息", "https://www.bing.com/")
    print(result)
