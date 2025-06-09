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
from typing import Tuple, Optional, Union
from pydantic import BaseModel, model_validator

from app.agent_dispatcher.infrastructure.entity.KnowledgeInfo import KnowledgeInfo
from app.agent_dispatcher.infrastructure.entity.Organization import Organization
from app.agent_dispatcher.infrastructure.entity.Profile import Profile
from app.agent_dispatcher.infrastructure.entity.RagWorkFlow import RagWorkFlow
from app.agent_dispatcher.infrastructure.entity.Skill import Skill
from app.agent_dispatcher.infrastructure.entity.SkillsOrchestration import SkillsOrchestration
from app.common.logger_util import logger


class AgentTemplate(BaseModel):
    template_name: str
    template_version: str
    agent_type: str
    display_name_zh: str
    display_name_en: str
    description_zh: str
    description_en: str
    profile: list[Profile] | None = None
    service_name: str
    service_version: str
    default_replay_zh: str
    default_replay_en: str
    icon: str | None = None
    icon_name: str | None = None
    skills: list[str | Skill] = []
    organizations: list[str | Organization] = []
    knowledge: list[KnowledgeInfo] = []
    rag_workflow: list[RagWorkFlow] = []
    max_iteration: int = 20
    business_type: dict | None = None
    reserved_map: dict | None = None
    skills_orchestration: Optional[Union[SkillsOrchestration, str]] = None

    def __init__(self, template_name: str, template_version: str, agent_type: str, display_name_zh: str,
                 display_name_en: str, description_zh: str, description_en: str, service_name: str,
                 service_version: str, default_replay_zh: str, default_replay_en: str,
                 profile: list[Profile] | None = None,
                 icon: str | None = None, icon_name: str | None = None, skills: list[str | Skill] = None,
                 organizations: list[str | Organization] = None, knowledge: list[KnowledgeInfo] = None,
                 rag_workflow: list[RagWorkFlow] = None, max_iteration: int = 20, business_type: dict | None = None,
                 reserved_map: dict | None = None, skills_orchestration: str | SkillsOrchestration | None = None,
                 **data):
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

    @model_validator(mode='before')
    @classmethod
    def validate_skills_orchestration(cls, values):
        """验证并转换skills_orchestration字段"""
        if not isinstance(values, dict):
            return values

        if 'skills_orchestration' not in values:
            return values

        skills_orchestration = values.get('skills_orchestration')
        if skills_orchestration is None:
            return values

        if isinstance(skills_orchestration, dict):
            try:
                if skills_orchestration.get('schema') and isinstance(skills_orchestration.get('schema'), str):
                    skills_orchestration['schema'] = json.loads(skills_orchestration.get('schema'))
                values['skills_orchestration'] = SkillsOrchestration(**skills_orchestration)
            except Exception as e:
                values['skills_orchestration'] = None
                logger.error(f"Failed to parse skills_orchestration: {e}", exc_info=True)
        return values

    def model_dump(self, **kwargs):
        data = super().model_dump(**kwargs)
        if self.skills_orchestration and isinstance(self.skills_orchestration, SkillsOrchestration):
            data['skills_orchestration'] = self.skills_orchestration.model_dump()
        return data
