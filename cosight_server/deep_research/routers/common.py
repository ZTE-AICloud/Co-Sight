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

from datetime import datetime
from typing import Dict
from urllib.parse import urlparse
from fastapi import APIRouter
from fastapi.params import Body

from cosight_server.sdk.common.api_result import json_result
from cosight_server.sdk.common.cache import Cache
from app.common.logger_util import logger
from app.cosight.tool.tool_result_processor import ToolResultProcessor

commonRouter = APIRouter()

server_start_timestamp = int(datetime.now().timestamp() * 1000)

@commonRouter.get("/deep-research/server-timestamp")
async def get_server_timestamp():
    """获取服务器启动时间戳"""
    return json_result(0, 'success', {
        'timestamp': server_start_timestamp
    })

@commonRouter.post("/deep-research/stop-message")
async def stop_message(body: Dict = Body(...)):
    messageId = body.get("messageId")
    logger.info(f"stop_message >>>>>>>>>> is called, messageId: {messageId}")
    Cache.put(f"is_message_stopped_{messageId}", True)
    return json_result(0, 'success', {
        'status': 'stopped'
    })

@commonRouter.post("/check-iframe-embedding")
async def check_iframe_embedding(body: Dict = Body(...)):
    url = body.get("url")
    if not url:
        return {"allowed": False, "reason": "No URL provided"}

    parsed_url = urlparse(url)
    if not parsed_url.scheme and url.startswith("/") and not url.startswith("//"):
        return {"allowed": True, "reason": "Same-origin relative URL"}

    try:
        allowed = ToolResultProcessor.check_embeddable(url)
        reason = "" if allowed else "Forbidden by policy, not accessible, or invalid content type"
        return {"allowed": allowed, "reason": reason}
    except Exception as e:
        logger.error(f"Error checking iframe embedding for {url}: {e}")
        return {"allowed": True, "reason": str(e)}
