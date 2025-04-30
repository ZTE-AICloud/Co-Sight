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

from app.agent_dispatcher.domain.plan.action.skill.mcp.const import LOCAL_MCP
from app.agent_dispatcher.domain.plan.action.skill.mcp.engine import MCPEngine
import asyncio
from contextlib import contextmanager


@contextmanager
def async_event_loop():
    """线程安全的事件循环上下文管理器"""
    try:
        # 创建新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        yield loop
    finally:
        # 清理事件循环
        loop.close()
        asyncio.set_event_loop(None)

def convert_skill_to_tool(skill, lang='en') -> dict:
    """Convert skill to tool format for llm.create_with_tools

    Args:
        skill: The skill dictionary returned by skill functions
        lang: Language code ('en' or 'zh')

    Returns:
        dict: Tool format for llm.create_with_tools
    """
    tools=[]
    if skill['skill_type'] not in [LOCAL_MCP]:
        parameters = skill['function'].get("parameters").copy()

        if 'properties' in parameters:
            for prop_name, prop_value in parameters['properties'].items():
                if lang in prop_value:
                    prop_value['description'] = prop_value[lang]
                    for key in ['zh', 'en']:
                        if key in prop_value:
                            del prop_value[key]

        result = {
            "type": "function",
            "function": {
                "name": skill['skill_name'],
                "description": skill[f'description_{lang}'],
                "parameters": parameters
            }
        }
        tools.append(result)
    return tools


def get_mcp_tools(skills):
    tools = []
    for skill in skills:
        if skill.skill_type in [LOCAL_MCP]:
            mcp_tools = asyncio.run(MCPEngine.get_mcp_tools(skill.skill_name, skill.mcp_server_config))
            result = {
                "mcp_name": skill.skill_name,
                "mcp_config": skill.mcp_server_config,
                "mcp_tools": mcp_tools
            }
            tools.append(result)
    return tools


def convert_mcp_tools(mcp_configs):
    tools = []
    for mcp_config in mcp_configs:
        for mcp_tool in mcp_config['mcp_tools']:
            if mcp_tool.inputSchema and 'properties' in mcp_tool.inputSchema:
                parameters = mcp_tool.inputSchema.get("parameters")
            else:
                parameters = {}
            result = {
                "type": "function",
                "function": {
                    "name": mcp_tool.name,
                    "description": mcp_tool.description,
                    "parameters": parameters
                }
            }
            tools.append(result)
    return tools
