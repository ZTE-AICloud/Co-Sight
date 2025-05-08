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

import json
import os
from pathlib import Path
import re
import uuid

from app.common.logger_util import logger


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

def get_upload_path(cookie: str):
    upload_dir = os.getenv("TRAFFIC_OPS_UPLOAD_DIR")
    logger.info(f"get_upload_path >>>>>>>>>>>>>>>>> upload_dir_env: {upload_dir}")
    if not upload_dir:
        upload_dir = str(Path(__file__).parent.parent.parent.resolve())
        logger.info(f"get_upload_path >>>>>>>>>>>>>>>>> use current project dir: {upload_dir}")

    # user_id = session_manager.get_user_id(session_manager.get_req_session_id(cookie))
    # logger.info(f"get_upload_path >>>>>>>>>>>>>>>>> user_id: {user_id}")
    user_id = "admin"
    upload_dir = upload_dir + "/upload_files/" + user_id
    logger.info(f"get_upload_path >>>>>>>>>>>>>>>>> upload_dir: {upload_dir}")

    upload_id = str(uuid.uuid4())
    upload_path = Path(upload_dir) / upload_id
    logger.info(f"get_upload_path >>>>>>>>>>>>>>>>> upload_path: {upload_path}")
    os.makedirs(upload_path, exist_ok=True)

    return upload_path, user_id, upload_id
