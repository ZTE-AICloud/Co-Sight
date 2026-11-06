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

from pydantic import BaseModel


class Conversation(BaseModel):
    speaker: str
    content: str
    listener: str

    def __init__(self, speaker: str, content: str, listener: str, **data):
        local = locals()
        fields = self.model_fields
        args_data = dict((k, fields.get(k).default if v is None else v) for k, v in local.items() if k in fields)
        data.update(args_data)
        super().__init__(**data)


class ConversationHistory(BaseModel):
    history: list[Conversation] = []

    def __init__(self, history: list[Conversation] = None, **data):
        local = locals()
        fields = self.model_fields
        args_data = dict((k, fields.get(k).default if v is None else v) for k, v in local.items() if k in fields)
        data.update(args_data)
        super().__init__(**data)

    def append(self, conversation: Conversation):
        self.history.append(conversation)
