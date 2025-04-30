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
import datetime
from pathlib import Path

file_timestamp = datetime.datetime.today().strftime('%Y%m%d')

PROJECT_ROOT_PATH = Path(__file__).parent.parent.parent.parent.parent
API_KEY_FILE = (PROJECT_ROOT_PATH / "google_api_key.json")
API_KEY_COUNT = (PROJECT_ROOT_PATH / f"google_api_key_count_{file_timestamp}.json")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")

def load_josn(file_path: str):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        print(f"load {file_path} error: {e}")
        return {}

def load_key_count(api_key_file: str , api_key_count_file: str):
    api_key_count = {}
    limit = 0
    account = {}
    if Path(api_key_file).is_file():
        api_key_dict = load_josn(api_key_file)

        if api_key_dict:
            limit = api_key_dict['limit']
            account = api_key_dict['account']
            api_key_count = load_josn(api_key_count_file)
            if not api_key_count:
                for name in account.keys():
                    api_key_count[name] = 0
                save_key_count(API_KEY_COUNT.as_posix(), api_key_count)

    return limit, account, api_key_count

def save_key_count(file_path: str, api_key_count: dict):
    try:
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(api_key_count, file, ensure_ascii=False, indent=2)
        print(f"save {API_KEY_COUNT.as_posix()}")
    except Exception as e:
        print(f"save {API_KEY_COUNT.as_posix()} error: {e}")

class APIKEYS:
    def __init__(self, api_key_file, api_key_count_file):
        self.api_key_count_file = api_key_count_file
        self.limit, self.account, self.api_key_count = load_key_count(api_key_file, api_key_count_file)
        names = list(self.api_key_count.keys())
        self.names = [name for name in names if self.api_key_count[name] < self.limit]
        self.current = self.names[0] if self.names else None

    def next(self):
        if self.current:
            index = self.names.index(self.current)
            index = (index + 1) % len(self.names)
            self.current = self.names[index]
        return self.current

    def get(self):
        if self.current:
            length = len(self.names)
            index = self.names.index(self.current)
            for i in range(length):
                name = self.names[(index + i) % length]
                count = self.api_key_count[name]
                if count < self.limit:
                    self.api_key_count[name] = count + 1
                    save_key_count(self.api_key_count_file, self.api_key_count)
                    print(f'GOOGLE_API_KEY use {name} {count + 1}')
                    return self.account[name]['GOOGLE_API_KEY'], self.account[name]['SEARCH_ENGINE_ID']
        return GOOGLE_API_KEY, SEARCH_ENGINE_ID


apikeys = APIKEYS(API_KEY_FILE.as_posix(), API_KEY_COUNT.as_posix())