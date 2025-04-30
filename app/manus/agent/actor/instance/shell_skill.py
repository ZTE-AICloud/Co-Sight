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

from app.agent_dispatcher.infrastructure.entity.SkillFunction import SkillFunction

def execute_shell_command_skill():
    return {
        'skill_name': 'execute_shell_command',
        'skill_type': "function",
        'display_name_zh': '执行Shell命令',
        'display_name_en': 'Execute Shell Command',
        'description_zh': '在本地系统上执行Shell命令并返回结果',
        'description_en': 'Execute shell commands on the local system and return the results',
        'semantic_apis': ["api_system"],
        'function': SkillFunction(
            id='9c44f9ad-be5c-4e6c-a9d8-1426b23828a8',
            name='zagents_framework.app.manus.tool.shell_toolkit.ShellTool.execute',
            description_zh='在本地系统上执行Shell命令',
            description_en='Execute shell commands on the local system',
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description_zh": "要执行的Shell命令",
                        "description_en": "Shell command to execute"
                    }
                },
                "required": ["command"]
            }
        )
    } 