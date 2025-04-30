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

#!/usr/bin/env python
# coding=utf-8
# Started by AICoder, pid:d9c93845dd3e476bbbbfb7fdef881c4a
import json
import re
from typing import List, Optional


def contains_str_regex(input_string: str, substring_list: List[str]) -> bool:
    pattern = '|'.join(map(re.escape, substring_list))
    return bool(re.search(pattern, input_string))
# Ended by AICoder, pid:d9c93845dd3e476bbbbfb7fdef881c4a


# Started by AICoder, pid:z819dw2b136c580143f90a424084d31d66743ab8
def transform_with_valid_json(text) -> Optional[dict]:
    # 使用非贪婪匹配，只获取第一个匹配的json字符串
    match = re.search(r"```json(.*?)```", text, flags=re.DOTALL)
    if match:
        json_str = match.group(1)
        try:
            json_obj = json.loads(json_str)
            return json_obj
        except json.JSONDecodeError:
            pass
    return None
    # Ended by AICoder, pid:z819dw2b136c580143f90a424084d31d66743ab8


def transform_string_to_json(text) -> dict:
    if not text:
        return {}
    try:
        if isinstance(text, str):
            return json.loads(text)
        if isinstance(text, dict):
            return text
    except Exception as e:
        print(str(e))
    return {}


def transform_json_to_string(text) -> str:
    if not text:
        return '{}'
    try:
        if isinstance(text, str):
            return text
        if isinstance(text, dict):
            return json.dumps(text)
    except Exception as e:
        print(str(e))
    return '{}'
