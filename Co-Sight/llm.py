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
import os
import httpx

from app.common.logger_util import logger
from app.cosight.llm.chat_llm import ChatLLM
from config.config import *

# Langfuse可观测性集成（可选）
# 如果启用Langfuse，使用包装的OpenAI客户端；否则使用原生OpenAI
langfuse_enabled = os.environ.get("LANGFUSE_ENABLED", "false").lower() in ("true", "1", "yes")

if langfuse_enabled:
    try:
        from langfuse.openai import OpenAI
        logger.info("✅ Langfuse tracing enabled")
    except ImportError:
        from openai import OpenAI
        logger.warning("❌ Langfuse not installed, using standard OpenAI client. Install: pip install langfuse")
else:
    from openai import OpenAI
    logger.info("Langfuse tracing disabled")


def set_model(model_config: dict[str, Optional[str | int | float]]):
    # 从环境变量读取超时配置（秒），默认180秒（3分钟）
    timeout_seconds = float(os.environ.get("LLM_TIMEOUT", "180"))
    
    http_client_kwargs = {
        "headers": {
            'Content-Type': 'application/json',
            'Authorization': model_config['api_key']
        },
        "verify": False,
        "trust_env": False,
        "timeout": httpx.Timeout(
            connect=30.0,        # 连接超时：30秒
            read=timeout_seconds,    # 读取超时：可配置，默认180秒
            write=30.0,          # 写入超时：30秒
            pool=10.0            # 连接池超时：10秒
        )
    }

    if model_config['proxy']:
        http_client_kwargs["proxy"] = model_config['proxy']

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
    if model_config.get('thinking_mode') is not None:
        chat_llm_kwargs['thinking_mode'] = model_config['thinking_mode']

    return ChatLLM(**chat_llm_kwargs)


plan_model_config = get_plan_model_config()
logger.info(f"plan_model_config:{plan_model_config}\n")
llm_for_plan = set_model(plan_model_config)

act_model_config = get_act_model_config()
logger.info(f"act_model_config:{act_model_config}\n")
llm_for_act = set_model(act_model_config)

tool_model_config = get_tool_model_config()
logger.info(f"tool_model_config:{tool_model_config}\n")
llm_for_tool = set_model(tool_model_config)

vision_model_config = get_vision_model_config()
logger.info(f"vision_model_config:{vision_model_config}\n")
llm_for_vision = set_model(vision_model_config)

credibility_model_config = get_credibility_model_config()
logger.info(f"credibility_model_config:{credibility_model_config}\n")
llm_for_credibility = set_model(credibility_model_config)
