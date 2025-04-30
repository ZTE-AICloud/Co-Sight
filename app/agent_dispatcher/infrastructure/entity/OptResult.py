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

# -*- coding: UTF-8 -*-
from typing import Optional, Any

from pydantic import BaseModel
from app.agent_dispatcher.infrastructure.entity.Message import Message

SUCCESS_CODE = 0
SUCCESS_MESSAGE = 'Success'


class OptResult(BaseModel):
    code: int
    message: str
    result: Optional[Any] = None

    def __init__(self, code: int, message: str, result: Optional[Any] = None, **data: Any):
        local = locals()
        fields = self.model_fields
        args_data = dict((k, fields.get(k).default if v is None else v) for k, v in local.items() if k in fields)
        data.update(args_data)
        super().__init__(**data)
        self.reset_code_and_message()

    def is_success(self):
        return self.code == 0

    def is_fail(self):
        return not self.is_success()

    def is_exec_fail(self):
        return not self.is_success() or (
                    self.result and isinstance(self.result, list) and isinstance(self.result[0], Message) and
                    self.result[0].data and self.result[0].data.get("zae_framework_error"))

    def exec_message(self):
        if self.is_fail():
            return self.message
        else:
            if self.result and isinstance(self.result, list) and isinstance(self.result[0], Message):
                return self.result[0].content
        return ""

    def reset_code_and_message(self):
        if self.result and isinstance(self.result, list):
            for result_item in self.result:
                if isinstance(result_item, Message) and result_item.data:
                    zae_framework_error_code = result_item.data.get("zae_framework_error_code", 0)
                    if zae_framework_error_code != 0:
                        self.code = zae_framework_error_code
                        self.message = result_item.content


    @staticmethod
    def success(result: Optional[Any] = None):
        return OptResult(SUCCESS_CODE, SUCCESS_MESSAGE, result)

