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

from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
from app.agent_dispatcher.infrastructure.entity.AgentTemplate import AgentTemplate
from app.cosight.agent.actor.instance.actor_agent_skill import (
    mark_step_skill,
    file_saver_skill,
    file_read_skill,
    file_str_replace_skill,
    file_find_in_content_skill,
    register_mcp_tools,
)
from app.cosight.agent.actor.instance.actor_agent_instance import load_search_skill


def create_netopt_actor_template(template_name: str, work_space_path: str, extra_skills=None):
    if extra_skills is None:
        extra_skills = []
    skills = [
        mark_step_skill(),
        file_saver_skill(),
        file_read_skill(),
        file_str_replace_skill(),
        file_find_in_content_skill(),
    ]
    skills.extend(extra_skills)
    template_content = {
        "template_name": template_name,
        "template_version": "v1",
        "agent_type": "actor_agent",
        "display_name_zh": "网优资料整理专家",
        "display_name_en": "Netopt Data Curation Expert",
        "description_zh": "负责网优相关资料整理与报告",
        "description_en": "Responsible for netopt-related data curation and reporting",
        "profile": [],
        "service_name": "execution_service",
        "service_version": "v1",
        "default_replay_zh": "网优资料整理专家",
        "default_replay_en": "Netopt Data Curation Expert",
        "icon": "",
        "skills": skills,
        "organizations": [],
        "knowledge": [],
        "max_iteration": 20,
        "business_type": {},
    }
    template_content["skills"].extend(register_mcp_tools())
    load_search_skill(template_content)
    return AgentTemplate(**template_content)


def create_netopt_actor_instance(agent_instance_name: str, work_space_path: str, extra_skills=None):
    if extra_skills is None:
        extra_skills = []
    agent_params = {
        "instance_id": f"actor_{agent_instance_name}",
        "instance_name": f"Actor {agent_instance_name}",
        "template_name": "netopt_actor_agent_template",
        "template_version": "v1",
        "display_name_zh": "网优资料整理专家",
        "display_name_en": "Netopt Data Curation Expert",
        "description_zh": "专注于网优资料整理与报告的专业助手",
        "description_en": "Specialized assistant for netopt data curation and reporting",
        "service_name": "execution_service",
        "service_version": "v1",
        "template": create_netopt_actor_template(
            "netopt_actor_agent_template", work_space_path, extra_skills
        ),
    }
    return AgentInstance(**agent_params)
