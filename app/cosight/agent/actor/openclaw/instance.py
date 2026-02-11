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

"""Minimal instance factory for OpenclawAgent (no LLM/tools, no skills)."""

from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
from app.agent_dispatcher.infrastructure.entity.AgentTemplate import AgentTemplate


def create_openclaw_instance(agent_instance_name: str, work_space_path: str, extra_skills=None):
    """Create a minimal AgentInstance for OpenclawAgent. extra_skills is ignored."""
    template_content = {
        "template_name": "openclaw_agent_template",
        "template_version": "v1",
        "agent_type": "actor_agent",
        "display_name_zh": "OpenClaw 执行器",
        "display_name_en": "OpenClaw Executor",
        "description_zh": "通过 OpenClaw Gateway 执行本地文件操作",
        "description_en": "Execute local file operations via OpenClaw Gateway",
        "profile": [],
        "service_name": "execution_service",
        "service_version": "v1",
        "default_replay_zh": "OpenClaw 执行器",
        "default_replay_en": "OpenClaw Executor",
        "icon": "",
        "skills": [],
        "organizations": [],
        "knowledge": [],
        "max_iteration": 1,
        "business_type": {},
    }
    template = AgentTemplate(**template_content)
    agent_params = {
        "instance_id": f"actor_{agent_instance_name}",
        "instance_name": f"Actor {agent_instance_name}",
        "template_name": "openclaw_agent_template",
        "template_version": "v1",
        "display_name_zh": "OpenClaw 执行器",
        "display_name_en": "OpenClaw Executor",
        "description_zh": "通过 OpenClaw Gateway 执行本地文件操作",
        "description_en": "Execute local file operations via OpenClaw Gateway",
        "service_name": "execution_service",
        "service_version": "v1",
        "template": template,
    }
    return AgentInstance(**agent_params)
