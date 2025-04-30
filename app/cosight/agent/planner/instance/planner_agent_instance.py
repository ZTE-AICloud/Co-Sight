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
from app.cosight.agent.base.common_skill import terminate_skill
from app.cosight.agent.planner.instance.planner_agent_skill import create_plan_skill, update_plan_skill


def create_planner_instance(agent_instance_name):
    agent_params = {
        'instance_id': f"planner_{agent_instance_name}",
        'instance_name': f"Planner {agent_instance_name}",
        "template_name": "planner_agent_template",
        'template_version': 'v1',
        'display_name_zh': '任务规划专家',
        'display_name_en': 'Task Planning Expert',
        'description_zh': '专注于任务分解和规划的专业助手',
        'description_en': 'Specialized assistant for task decomposition and planning',
        "service_name": 'planning_service',
        "service_version": 'v1',
        "template": create_planner_template("planner_agent_template")
    }
    return AgentInstance(**agent_params)


def create_planner_template(template_name):
    template_content = {
        'template_name': template_name,
        'template_version': 'v1',
        "agent_type": "planner_agent",
        'display_name_zh': '任务规划专家',
        'display_name_en': 'Task Planning Expert',
        'description_zh': '负责任务分解和规划',
        'description_en': 'Responsible for task decomposition and planning',
        "profile": [],
        'service_name': 'planning_service',
        'service_version': 'v1',
        'default_replay_zh': '任务规划专家',
        'default_replay_en': 'Task Planning Expert',
        "icon": "",
        'skills': [create_plan_skill(), update_plan_skill(), terminate_skill()],
        "organizations": [],
        'knowledge': [],
        'max_iteration': 20,
        'business_type': {}
    }
    return AgentTemplate(**template_content)
