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
import re
import socket
import ssl
from datetime import datetime
from typing import Optional, Any

import aiohttp
from aiohttp import ClientConnectorError
import requests

from cosight_server.sdk.common.cache import Cache
from app.common.logger_util import logger
from cosight_server.sdk.entities.config_info import ConfigSetInfo


def get_timestamp():
    current_time = datetime.utcnow()

    # 转换为从1970年1月1日00:00:00 UTC到未来时间的毫秒数
    epoch = datetime(1970, 1, 1)
    future_timestamp = int((current_time - epoch).total_seconds() * 1000)

    return future_timestamp


def get_local_ip():
    try:
        # 获取主机名称
        hostname = socket.gethostname()
        # 通过主机名称获取本地IP地址
        local_ip = socket.gethostbyname(hostname)
        return local_ip
    except Exception as e:
        # 如果出现异常，返回一个默认的回环地址
        logger.error(f"get server ip error: {e}", exc_info=True)
        return '127.0.0.1'


# Started by AICoder, pid:24fcb48185z7302142d60a2d103686057e584021
def set_cache_config_info(session_id: str, infos: list[ConfigSetInfo]):
    cache_info = Cache.get("lui-" + session_id)
    if cache_info is None:
        return
    config_info = cache_info.get("config_info") if cache_info.get("config_info") is not None else {}
    for info in infos:
        config_info[info.key] = info.value
    cache_info['config_info'] = config_info
    return config_info
# Ended by AICoder, pid:24fcb48185z7302142d60a2d103686057e584021


# Started by AICoder, pid:50434g9ca69a02e144db0966503967068912a49e
def get_cache_config_info(session_id: str, key: str, default_value: Optional[Any] = None):
    cache_info = Cache.get("lui-" + session_id)
    return cache_info.get("config_info").get(key) \
        if cache_info is not None and cache_info.get("config_info") is not None else default_value
# Ended by AICoder, pid:50434g9ca69a02e144db0966503967068912a49e

# Started by AICoder, pid:r7d71529bcjb1df14d8e0b81d0423b0840781262
def filter_histories(histories):
    filtered = []
    for item in histories:
        content = item.get("content")
        # 判断 content 是否是一个列表，并且列表中的元素是否包含 'type' 和 'value'
        if isinstance(content, list) and all(isinstance(i, dict) and 'type' in i and 'value' in i for i in content):
            filtered.append(item)
    return filtered
# Ended by AICoder, pid:r7d71529bcjb1df14d8e0b81d0423b0840781262


async def stream_data(url, params, headers):
    timeout = aiohttp.ClientTimeout(sock_read=300)
    logger.info(f"=========stream_data:  url, params {url} {params}")
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url=url, json=params, headers=headers) as response1:
                if response1.status != 200:
                    logger.error(f"========stream_data: Error: Received response with status code {response1.status}")
                    return

                async for line in response1.content:
                    decoded_line = line.decode('utf-8')
                    yield decoded_line
    except ClientConnectorError as e:
        logger.info(f"========stream_data: Connection failed: {e}")
        yield None
    except Exception as e:
        logger.info(f"=========stream_data: An error occurred: {e}")
        yield None


def get_cookie_param_value(cookie: str, param: str):
    if not cookie:
        return None

    cookies = cookie.split('; ')
    cookie_dict = {}

    for cookie_item in cookies:
        if '=' in cookie_item:
            key, value = cookie_item.split('=', 1)  # 最多分割一次
            cookie_dict[key] = value

    return cookie_dict.get(param)

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

async def async_request(url, params, headers=None, method='post'):
    try:
        async with aiohttp.ClientSession() as session:
            http_method = getattr(session, method.lower(), None)

            if not http_method:
                raise ValueError(f"Unsupported HTTP method: {method}")

            async with http_method(url=url, json=params, headers=headers, ssl=ssl_context) as response:
                if response.status != 200:
                    logger.error(f"async_request: Async request failed, status code: {response.status}")
                    return None

                try:
                    return await response.json()
                except json.JSONDecodeError:
                    error_message = response.text
                    logger.error(f"async_request: Async request failed, {error_message}")
                    return None
    except ClientConnectorError as e:
        logger.info(f"async_request: Connection failed: {e}")
        return None
    except Exception as e:
        logger.exception(f"async_request: An unexpected error occurred {e}")
        return None


def sync_request(url, params, headers, method='post'):
    try:
        request_method = getattr(requests, method.lower(), None)
        response = request_method(url=url, json=params, headers=headers)

        if response.status_code != 200:
            logger.error(f"sync_request: 请求数据失败，状态码: {response.status_code}")
            return {}

        try:
            return response.json()
        except json.JSONDecodeError:
            error_message = response.text
            logger.error(f"sync_request: 请求数据失败，{error_message}")
            return {}
    except requests.ConnectionError as e:
        logger.info(f"sync_request: Connection failed: {e}")
        return {}
    except Exception as e:
        logger.info(f"sync_request: An error occurred: {e}")
        return {}


def create_background_task(coro):
    """
    创建并执行后台任务
    
    Args:
        coro: 要执行的协程对象
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        loop.create_task(coro)
    else:
        try:
            loop.run_until_complete(coro)
        except Exception as e:
            logger.exception(f"Error in background task: {e}")
            # 如果发生错误，确保关闭事件循环
            try:
                loop.close()
            except:
                pass

def parse_content_properties(params: dict) -> dict:
    """
    解析并返回 content_properties
    
    Args:
        params: 包含 contentProperties 的参数字典
    
    Returns:
        解析后的 content_properties 字典，如果解析失败则返回空字典
    """
    content_properties = params.get('contentProperties')
    if isinstance(content_properties, str):
        try:
            return json.loads(content_properties)
        except json.JSONDecodeError:
            logger.error("contentProperties 不是有效的 JSON 字符串")
            return {}
    return content_properties if isinstance(content_properties, dict) else {}

def extract_and_clean_tags(query: str) -> tuple[list[str], str]:
    """
    从查询字符串中提取所有 #xxx 格式的标签，并返回清理后的查询字符串。

    Args:
        query (str): 用户查询字符串。

    Returns:
        tuple: 包含提取的标签列表和清理后的查询字符串。
    """
    # 提取所有 #xxx 格式的标签
    source_tags = re.findall(r'#([^#\s]+(?::[^#\s]+)?)', query)
    
    if not source_tags:
        return [], query
    
    # 移除query中的所有搜索源标签
    cleaned_query = query
    for tag in source_tags:
        cleaned_query = cleaned_query.replace(f'#{tag}', '').strip()
    
    return source_tags, cleaned_query