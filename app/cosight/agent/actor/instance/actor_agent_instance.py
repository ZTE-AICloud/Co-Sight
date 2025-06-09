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
from app.cosight.agent.actor.instance.actor_agent_skill import *


def create_actor_instance(agent_instance_name, work_space_path):
    agent_params = {
        'instance_id': f"actor_{agent_instance_name}",
        'instance_name': f"Actor {agent_instance_name}",
        "template_name": "actor_agent_template",
        'template_version': 'v1',
        'display_name_zh': '任务执行专家',
        'display_name_en': 'Task Execution Expert',
        'description_zh': '专注于任务执行和操作的专业助手',
        'description_en': 'Specialized assistant for task execution and operations',
        "service_name": 'execution_service',
        "service_version": 'v1',
        "template": create_actor_template("actor_agent_template", work_space_path)
    }
    return AgentInstance(**agent_params)


def create_actor_template(template_name, work_space_path):
    template_content = {
        'template_name': template_name,
        'template_version': 'v1',
        "agent_type": "actor_agent",
        'display_name_zh': '任务执行专家',
        'display_name_en': 'Task Execution Expert',
        'description_zh': '负责具体任务执行',
        'description_en': 'Responsible for task execution',
        "profile": [],
        'service_name': 'execution_service',
        'service_version': 'v1',
        'default_replay_zh': '任务执行专家',
        'default_replay_en': 'Task Execution Expert',
        "icon": "",
        'skills': [execute_code_skill(work_space_path),
                   search_baidu_skill(),
                   mark_step_skill(),
                   browser_use_skill(),
                   file_saver_skill(),
                   file_read_skill(),
                   file_str_replace_skill(),
                   file_find_in_content_skill(),
                   ask_question_about_image_skill(),
                   extract_document_content_skill(),
                   create_html_report_skill(),
                   fetch_website_content_skill(),
                   # search_duckgo_skill(),
                   search_wiki_skill(),
                   audio_recognition_skill(),
                   ask_question_about_video_skill()],
        # , terminate_skill(), browser_use_skill()
        "organizations": [],
        'knowledge': [],
        'max_iteration': 20,
        'business_type': {}
    }
    template_content['skills'].extend(register_mcp_tools())
    load_search_skill(template_content)
    return AgentTemplate(**template_content)


def load_search_skill(template_content):
    import os
    if os.environ.get("GOOGLE_API_KEY", "") and os.environ.get("SEARCH_ENGINE_ID", ""):
        template_content['skills'].extend([search_google_skill()])
    if os.environ.get("TAVILY_API_KEY", ""):
        template_content['skills'].extend([tavily_search_skill(), search_image_skill()])
