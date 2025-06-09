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
from typing import Optional

from cosight_server.deep_research.services.i18n_service import i18n
from cosight_server.sdk.common.cache import Cache
from cosight_server.sdk.common.config import custom_config
from app.common.logger_util import logger
from cosight_server.sdk.common.utils import async_request, extract_and_clean_tags, sync_request

from cosight_server.deep_research.entity import IcenterToken, SearchSource

def loop_sync_extract_entity(task_name, content) -> dict:
    """
    同步版本的实体提取。plugin_service里的extract_entity是需要加await/async的，会改动原有的代码
    """
    try:
        return _run_loop_task(task_func=_sync_extract_entity, params={"task_name":task_name, "content":content})
    except Exception as e:
        logger.exception(str(e),exc_info=True)


def _run_loop_task(task_func, params) -> dict:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        response = loop.run_until_complete(
            _async_run_task(task_func, params))
        return response
    finally:
        loop.close()


async def _async_run_task(task_func, params) -> dict:
    try:
        # Using asyncio.to_thread to run the synchronous request in a separate thread
        response = await asyncio.wait_for(
            asyncio.to_thread(task_func, **params),  timeout=20
        )
        return response
    except asyncio.TimeoutError:
        logger.exception('Request timed out.')
        raise


def _sync_extract_entity(task_name, content) -> dict:
    url = f"http://{custom_config['entity_extraction']['ip']}:{custom_config['entity_extraction']['port']}/chat/completions"
    params = {
        "model": "NTele-72B-V2",
        "temperature": 1,
        "task_name": task_name,
        "top_k": 1,
        "messages": [{"role": "user", "content": content}],
        "stream": False
    }
    headers = {}

    data = sync_request(url, params, headers)
    try:
        content = json.loads(data["choices"][0]["message"]["content"])
        logger.info(f"extract_entity: 提取实体数据：{content}")
        return content
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"extract_entity: 提取实体数据失败，错误信息：{e}，响应数据：{data}", exc_info=True)
        return {}


def is_url(url: str) -> bool:
    # 定义一个用于匹配URL的正则表达式
    url_pattern = re.compile(
        r'^(https?|ftp)://'  # 匹配 http, https, 或 ftp 协议
        r'([a-zA-Z0-9.-]+(:[a-zA-Z0-9.&%$-]+)*@)?'  # 可选的用户名和密码
        r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'  # 域名
        r'(:\d{2,5})?'  # 可选的端口号
        r'(/[a-zA-Z0-9&%$./-~-]*)*'  # 可选的路径
        r'(\?[a-zA-Z0-9=&%$./-~-]*)?'  # 可选的查询参数
        r'(#[a-zA-Z0-9=&%$./-~-]*)?$'  # 可选的 fragment 锚点
    )

    # 使用正则表达式匹配字符串
    return re.match(url_pattern, url) is not None


async def get_icenter_space_ids(space_names: list[str], icenter_token: IcenterToken) -> list[str]:
    url = f"https://icenterapi.zte.com.cn/zte-km-icenter-space/space/searchMySpace"
    space_ids = []

    for space_name in space_names:
        params = {
            "employeeShortId": icenter_token['emp_no'],
            "keyword": space_name,
            "scCodes": []
        }
        headers = get_icenter_headers(icenter_token)
        data = await async_request(url, params, headers)
        if data is None:
            logger.error(f"get_icenter_space_ids: 未收到 {space_name} 对应的空间id")
            continue

        try:
            space_info = data['bo'][0]
            space_id = space_info['id']
            space_ch_name = space_info['chName']
            logger.info(f"查询到的icenter空间：{space_id}, {space_ch_name}")
            space_ids.append(space_id)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"get_icenter_space_ids: 查询 {space_name} 空间ID失败，错误信息：{e}", exc_info=True)
            continue

    return space_ids


def get_icenter_headers(icenter_token: IcenterToken):
    return {
        'Content-Type': 'application/json;charset=UTF-8',
        'Origin': 'https://i.zte.com.cn',
        'Referer': 'https://i.zte.com.cn/',
        'X-Auth-Value': icenter_token['auth_value'],
        'X-Emp-No': icenter_token['emp_no'],
        'X-Lang-Id': 'zh_CN'
    }


async def get_space_ids(search_sources: list[SearchSource], query: str, icenter_token: IcenterToken) -> list[str]:
    """
    从搜索源和问题中提取空间ID
    
    Args:
        search_source: 搜索源列表
        query: 用户查询字符串
        icenter_token: icenter令牌信息
    
    Returns:
        list[str]: 空间ID列表
    """
    space_ids = []
    
    # 从搜索源提取空间ID
    if isinstance(search_sources, list) and len(search_sources) > 0:
        icenter_spaces = []
        for source in search_sources:
            if source.get('type') == 'ZTEICenterDocument':
                # get方法只要有属性就不会取默认值，所以需要使用or []    
                spaces = source.get('config', {}).get('spaces') or []
                icenter_spaces.extend(spaces)
        logger.info(f"知识源中提取到搜索空间=======> icenter_spaces: {icenter_spaces}")
        source_space_ids = await get_icenter_space_ids(icenter_spaces, icenter_token)
        logger.info(f"知识源中提取到搜索空间=======> source_space_ids:{source_space_ids}")
        space_ids.extend(source_space_ids)
    
    # 从问题中提取空间ID
    entity = await extract_entity('实体提取_根据输入提取使用的搜索空间_10210844', query)
    logger.info(f"实体提取使用的搜索空间=======> entity: {entity}")
    if entity:
        entity_space_ids = await get_icenter_space_ids(entity.get('space_names', []), icenter_token)
        logger.info(f"实体提取使用的搜索空间=======> entity_space_ids:{entity_space_ids}")
        space_ids.extend(entity_space_ids)
    
    # 去重
    space_ids = list(set(space_ids))
    logger.info(f"最终使用的搜索空间=======> space_ids:{space_ids}")
    
    return space_ids


def is_message_stoped(message_id):
    if message_id is None:
        return False
    is_message_stoped = Cache.get(f"is_message_stopped_{message_id}")
    if is_message_stoped:
        Cache.delete(f"is_message_stopped_{message_id}")
    return is_message_stoped