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

from typing import Tuple, Optional, Union, Any
from pydantic import BaseModel

from app.agent_dispatcher.infrastructure.entity.Skill import Skill



class AgentTemplate(BaseModel):
    template_name: str
    template_version: str
    agent_type: str
    display_name_zh: str
    display_name_en: str
    description_zh: str
    description_en: str
    profile: list[Any] | None = None
    service_name: str
    service_version: str
    default_replay_zh: str
    default_replay_en: str
    icon: str | None = None
    icon_name: str | None = None
    skills: list[str | Skill] = []
    organizations: list[str | Any] = []
    knowledge: list[Any] = []
    rag_workflow: list[Any] = []
    max_iteration: int = 20
    business_type: dict | None = None
    reserved_map: dict | None = None
    skills_orchestration: Optional[Union[Any, str]] = None

    def __init__(self, template_name: str, template_version: str, agent_type: str, display_name_zh: str,
                 display_name_en: str, description_zh: str, description_en: str, service_name: str,
                 service_version: str, default_replay_zh: str, default_replay_en: str,profile: list[Any] | None = None,
                 icon: str | None = None, icon_name: str | None = None, skills: list[str | Skill] = None,
                 organizations: list[str | Any] = None, knowledge: list[Any] = None,
                 rag_workflow: list[Any] = None, max_iteration: int = 20, business_type: dict | None = None,
                 reserved_map: dict | None = None, skills_orchestration: str | Any | None = None, **data):
        local = locals()
        fields = self.model_fields
        args_data = dict((k, fields.get(k).default if v is None else v) for k, v in local.items() if k in fields)
        data.update(args_data)
        super().__init__(**data)

    def get_skill_by_skill_name(self, skill_name):
        for skill in self.skills:
            if skill.skill_name == skill_name:
                return skill

    def unique_key(self) -> Tuple[str, str]:
        return (self.template_name, self.template_version)

