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
import tempfile



class JsonUtil:

    @staticmethod
    def write_data(data, data_path):
        if not os.path.isfile(data_path):
            # Create new file and write content
            print(f'not find, create new file {data_path}')
            dst_dir = os.path.dirname(data_path)
            if not os.path.exists(dst_dir):
                os.makedirs(dst_dir)
        with open(data_path, 'w') as json_file:
            json.dump(data, json_file, indent=4)

    @staticmethod
    def read_data(data_path):
        if not os.path.isfile(data_path):
            print(f'not find: {data_path}')
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

    # Started by AICoder, pid:h97031bd1495b521424e0b69b0d3f52ded687c6f
    @staticmethod
    def create_tmp_json(data_dict, json_path):
        # 创建一个临时文件用于存储修改后的 JSON 数据
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.json',
                                         dir=tempfile.mkdtemp()) as tmp_file:
            # 将修改后的数据写入临时文件
            json.dump(data_dict, tmp_file, indent=4)
            temp_json_path = tmp_file.name
        # 提取出临时文件所在的目录
        temp_dir = os.path.dirname(temp_json_path)
        # 获取文件名
        filename = os.path.basename(json_path)
        new_file_path = os.path.join(temp_dir, filename)
        # 重命名临时文件
        os.rename(temp_json_path, new_file_path)
        return temp_dir, new_file_path

    @staticmethod
    def rewrite_template_json(jsonpath, extend_arges: dict[str, list] = None, **kwargs):
        json_path = fetch_abs_path_from_target(
            jsonpath)
        with open(json_path, 'r', encoding="utf-8") as file:
            data = file.read()
            for k, v in kwargs.items():
                data = data.replace(f"{{{k}}}", v)
        # 将替换后的数据解析成字典
        data_dict = json.loads(data)
        if extend_arges and isinstance(extend_arges, dict):
            for k, v in extend_arges.items():
                if k in data_dict:
                    v1 = data_dict.get(k, [])
                    if isinstance(v1, list):
                        v1 += v
                    data_dict[k] = v1
        return JsonUtil.create_tmp_json(data_dict, json_path)

    # Ended by AICoder, pid:h97031bd1495b521424e0b69b0d3f52ded687c6f
