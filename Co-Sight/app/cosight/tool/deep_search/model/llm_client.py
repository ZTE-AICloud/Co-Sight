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
import time
import aiohttp
import requests
from functools import partial
from typing import List, Dict, AsyncGenerator
from lagent.schema import ModelStatusCode
from app.common.logger_util import logger

class LLMClient:
    """LLM客户端基类"""

    def __init__(self, api_url: str, model_name: str, api_key: str = None, proxy: str = None):
        """初始化LLM客户端

        Args:
            api_url: API endpoint URL
            model_name: 模型名称
            authorization: 可选的认证令牌
        """
        self.api_url = api_url
        self.model_name = model_name
        self.proxy = proxy
        self.headers = {
            "Content-Type": "application/json"
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def _prepare_payload(self, messages: List[Dict[str, str]], stream: bool = False, **kwargs):
        return {
            "model": self.model_name,
            "messages": messages,
            "stream": stream
        }

    def _finish_handler(self, line, chunk) -> str:
        # 将结束原因输出
        logger.info(f"line ===========> {line}")
        logger.info(f"finish_reason ===> {chunk['choices'][0]['finish_reason']}")
        return chunk["choices"][0]["delta"].get("content", "")

    async def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """非流式调用大模型"""
        payload = self._prepare_payload(messages, False, **kwargs)
        logger.info(f'chat to {self.api_url}, model: {self.model_name}, payload: {payload}')

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers, proxy=self.proxy, ssl=False) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"API request failed with status {response.status}: {error_text}")
                        raise Exception(f"API request failed: {error_text}")

                    result = await response.json()
                    return result["choices"][0]["message"]["content"]

        except Exception as e:
            logger.error(f"Error in chat: {str(e)}", exc_info=True)
            raise

    async def stream_chat(self, messages: List[Dict[str, str]], **kwargs) -> AsyncGenerator[tuple, None]:
        """流式调用大模型"""
        payload = self._prepare_payload(messages, True, **kwargs)
        logger.info(f'stream chat to {self.api_url}, model: {self.model_name}, payload: {payload}')

        start_time = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, headers=self.headers, proxy=self.proxy, ssl=False) as response:
                    response_time = time.time() - start_time
                    logger.info(f'LLM API response time: {response_time:.2f}s, status: {response.status}')

                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"API request failed with status {response.status}: {error_text}")
                        yield ModelStatusCode.SERVER_ERR, f"API request failed: {error_text}", None
                        return
                    content = ''
                    async for line in response.content:
                        if line:
                            try:
                                line = line.decode('utf-8').strip()
                                # 忽略所有以冒号开头的SSE注释行
                                if line.startswith(':'):
                                    continue
                                if line.startswith('data: '):
                                    line = line[6:]
                                if line and line != '[DONE]':
                                    chunk = json.loads(line)
                                    if chunk["choices"][0].get("finish_reason", None):
                                        content += self._finish_handler(line, chunk)
                                        break
                                    if "content" in chunk["choices"][0]["delta"]:
                                        content += chunk["choices"][0]["delta"]["content"]
                                        yield ModelStatusCode.STREAM_ING, content, None
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to decode JSON: {line}, error: {str(e)}")
                                continue
                            except Exception as e:
                                logger.error(f"Error processing stream chunk: {str(e)}", exc_info=True)
                                yield ModelStatusCode.SESSION_INVALID_ARG, str(e), None
                                return

                    total_time = time.time() - start_time
                    logger.info(f'LLM API total streaming time: {total_time:.2f}s')
                    yield ModelStatusCode.END, content, None

        except Exception as e:
            logger.error(f"Error in stream_chat: {str(e)}",exc_info=True)
            yield ModelStatusCode.SERVER_ERR, str(e), None
