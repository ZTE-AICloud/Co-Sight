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
import requests
from tqdm import tqdm


def download_file(url, dest_path):
    chunk_size = 1024
    # 获取已下载文件大小（断点续传）
    resume_byte_pos = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    headers = {"Range": f"bytes={resume_byte_pos}-"}
    # 如果文件存在，直接覆盖（删除再下）
    if os.path.exists(dest_path):
        print(f"⚠️ 文件已存在，正在覆盖: {dest_path}")
        os.remove(dest_path)
        # 发起请求，获取文件大小
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        total_size = int(response.headers.get('Content-Length', 0))

        with open(dest_path, 'wb') as f, tqdm(
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                desc=os.path.basename(dest_path)
        ) as bar:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    bar.update(len(chunk))

    print(f"\n✅ 下载完成: {dest_path}")
    return f"\n✅ 下载完成: {dest_path}"
