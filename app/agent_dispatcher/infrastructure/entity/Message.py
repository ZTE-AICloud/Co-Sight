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

import time

from pydantic import BaseModel

from app.agent_dispatcher.infrastructure.util.constants import TYPE_REQUEST


class Message(BaseModel):
    content: str
    role: str | None = None
    data: dict | None = None
    create_time: int = int(time.time() * 1000)  # 时间戳,单位毫秒
    type: str = TYPE_REQUEST  # 通知、请求、应答

    def __init__(self, content: str, role: str | None = None, data: dict | None = None, create_time: int = None,
                 type: str = TYPE_REQUEST, **kdata):
        local = locals()
        fields = self.model_fields
        args_data = dict((k, fields.get(k).default if v is None else v) for k, v in local.items() if k in fields)
        kdata.update(args_data)
        super().__init__(**kdata)

    def __iter__(self):
        self._current_index = 0
        return self

    def __next__(self):
        if self._current_index == 0:
            self._current_index += 1
            return self
        else:
            raise StopIteration

    def to_text(self) -> str:
        return self.content