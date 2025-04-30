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

import json
import os

from app.common.infrastructure.utils.log import logger


class JsonUtil:

    @staticmethod
    def write_data(data, data_path):
        if not os.path.isfile(data_path):
            # Create new file and write content
            logger.info(f'not find, create new file {data_path}')
            dst_dir = os.path.dirname(data_path)
            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir)
        with open(data_path, 'w') as json_file:
            json.dump(data, json_file, indent=4)

    @staticmethod
    def read_data(data_path):
        if not os.path.isfile(data_path):
            logger.info(f'not find: {data_path}')
            return {}
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data

    @staticmethod
    def read_all_data(data_path_dir) -> list[dict]:
        datas: list[dict] = []
        for file_name in os.listdir(data_path_dir):
            file: str = os.path.join(data_path_dir, file_name)
            if os.path.isfile(file) and file.endswith('.json'):
                with open(file, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                    if isinstance(json_data, list):
                        datas.extend(json_data)
                    else:
                        datas.append(json_data)
        return datas
