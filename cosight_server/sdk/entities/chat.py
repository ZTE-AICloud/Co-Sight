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

from typing import Optional

from pydantic import BaseModel


class Chat(BaseModel):
    userName: Optional[str] = None
    chatName: Optional[str] = None
    type: Optional[str] = None
    uuid: str
    participants: Optional[list] = None
    messages: Optional[list] = None
    newChatName: Optional[str] = None
    pinMessage: Optional[str] = None
    showPortrait: Optional[bool] = False
    showName: Optional[bool] = False
    showTimestamp: Optional[bool] = False


class RoleInfo(BaseModel):
    name: str
    role: str
    portrait: Optional[str] = None
