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

import tiktoken
import hashlib
import os

blobpath = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
cache_key = hashlib.sha1(blobpath.encode()).hexdigest()  # 9b5ad71b2ce5302211f9c61530b329a4922fc6a4，对应文件名
# Started by AICoder, pid:8c0e1ade8e6259b14d1a09ebf0f8140552e13c37
tiktoken_cache_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Ended by AICoder, pid:8c0e1ade8e6259b14d1a09ebf0f8140552e13c37
os.environ["TIKTOKEN_CACHE_DIR"] = f"{tiktoken_cache_dir}/resource"
encoding = tiktoken.get_encoding("cl100k_base")


def count_token(sentence: str) -> int:
    token_sentence = encoding.encode(sentence)
    return len(token_sentence)
