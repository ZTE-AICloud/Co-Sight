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

import os

from app.agent_dispatcher.infrastructure.entity.SkillFunction import SkillFunction
from config import mcp_server_config_dir
from app.common.domain.util.json_util import JsonUtil


def execute_code_skill():
    return {
        'skill_name': 'execute_code',
        'skill_type': "function",
        'display_name_zh': '执行代码',
        'display_name_en': 'Execute Code',
        'description_zh': f'执行给定的代码片段并返回结果,若要处理本地文件，必须在工作区: {os.getenv("WORKSPACE_PATH") or os.getcwd()}',
        'description_en': f'Execute a given code snippet and return the result. To process the local file, it must be in the working area: {os.getenv("WORKSPACE_PATH") or os.getcwd()}',
        'semantic_apis': ["api_code_execution"],
        'function': SkillFunction(
            id='4c44f9ad-be5c-4e6c-a9d8-1426b23828a9',
            name='zagents_framework.app.manus.code_interpreter.execute_code',
            description_zh='执行Python代码片段并返回输出结果',
            description_en='Execute Python code snippet and return the output',
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description_zh": "要执行的Python代码",
                        "description_en": "Python code to execute"
                    }
                },
                "required": ["code"]
            }
        )
    }


def search_google_skill():
    return {
        'skill_name': 'search_google',
        'skill_type': "function",
        'display_name_zh': '谷歌搜索',
        'display_name_en': 'Google Search',
        'description_zh': '使用谷歌搜索引擎搜索给定查询的信息',
        'description_en': 'Use Google search engine to search information for the given query',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='3c44f9ad-be5c-4e6c-a9d8-1426b23828a0',
            name='zagents_framework.app.manus.search_toolkit.search_google',
            description_zh='通过谷歌搜索引擎获取查询结果',
            description_en='Get search results using Google search engine',
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description_zh": "要搜索的查询内容",
                        "description_en": "Query to be searched"
                    }
                },
                "required": ["query"]
            }
        )
    }


def tavily_search_skill():
    return {
        'skill_name': 'tavily_search',
        'skill_type': "function",
        'display_name_zh': 'Tavily搜索',
        'display_name_en': 'Tavily Search',
        'description_zh': '使用Tavily搜索引擎搜索给定查询的信息',
        'description_en': 'Use Tavily search engine to search information for the given query',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='3c44f9ad-be5c-4e6c-a9d8-1426b23828a0',
            name='zagents_framework.app.manus.search_toolkit.search_google',
            description_zh='通过谷歌搜索引擎获取查询结果',
            description_en='Get search results using Tavily search engine',
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description_zh": "要搜索的查询内容",
                        "description_en": "Query to be searched"
                    }
                },
                "required": ["query"]
            }
        )
    }


def search_duckgo_skill():
    return {
        'skill_name': 'search_duckgo',
        'skill_type': "function",
        'display_name_zh': 'DuckDuckGo搜索',
        'display_name_en': 'Google Search',
        'description_zh': '使用DuckDuckGo搜索引擎搜索给定查询的信息',
        'description_en': 'Use DuckDuckGo search engine to search information for the given query',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='3c44f9ad-be5c-4e6c-a9d8-1426b23828a0',
            name='zagents_framework.app.manus.search_toolkit.search_google',
            description_zh='使用DuckDuckGo搜索引擎搜索给定查询的信息',
            description_en='Get search results using DuckDuckGo search engine',
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description_zh": "要搜索的查询内容",
                        "description_en": "Query to be searched"
                    },
                    "source": {
                        "type": "string",
                        "description_zh": "要搜索的查询内容类型，例如：text，images，videos",
                        "description_en": "Query to be searched"
                    }
                },
                "required": ["query"]
            }
        )
    }


def search_wiki_skill():
    return {
        'skill_name': 'search_wiki',
        'skill_type': "function",
        'display_name_zh': '维基百科搜索',
        'display_name_en': 'Google Search',
        'description_zh': '使用维基百科搜索工具搜索给定查询的信息',
        'description_en': 'Use wiki search engine to search information for the given query',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='3c44f9ad-be5c-4e6c-a9d8-1426b23828a0',
            name='zagents_framework.app.manus.search_toolkit.search_google',
            description_zh='使用维基百科搜索工具搜索给定查询的信息',
            description_en='Get search results using wiki search engine',
            parameters={
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description_zh": "要搜索的查询内容",
                        "description_en": "Query to be searched"
                    }
                },
                "required": ["entity"]
            }
        )
    }


def browser_use_skill():
    return {
        'skill_name': 'browser_use',
        'skill_type': "function",
        'display_name_zh': '浏览器交互模拟',
        'display_name_en': 'Browser Interaction Simulation',
        'description_zh': '模拟浏览器交互以解决需要多步操作的任务',
        'description_en': 'Simulate browser interaction to solve tasks requiring multi-step actions',
        'semantic_apis': ["api_browser_simulation"],
        'function': SkillFunction(
            id='2c44f9ad-be5c-4e6c-a9d8-1426b23828a1',
            name='zagents_framework.app.manus.browser_toolkit.browser_use',
            description_zh='通过模拟浏览器交互解决复杂任务',
            description_en='Solve complex tasks by simulating browser interactions',
            parameters={
                "type": "object",
                "properties": {
                    "task_prompt": {
                        "type": "string",
                        "description_zh": "需要解决的任务描述",
                        "description_en": "Task description to be solved"
                    },
                    "start_url": {
                        "type": "string",
                        "description_zh": "要访问的起始 URL",
                        "description_en": "The start URL to visit"
                    }
                },
                "required": ["task_prompt", "start_url"]
            }
        )
    }


def fetch_website_content_skill():
    return {
        'skill_name': 'fetch_website_content',
        'skill_type': "function",
        'display_name_zh': '网页内容爬取',
        'display_name_en': 'Fetch Website Content',
        'description_zh': '网页内容爬取',
        'description_en': 'Fetch Website Content',
        'semantic_apis': ["api_browser_simulation"],
        'function': SkillFunction(
            id='2c44f9ad-be5c-4e6c-a9d8-1426b23828a1',
            name='zagents_framework.app.manus.browser_toolkit.browser_use',
            description_zh='网页内容爬取',
            description_en='Fetch Website Content',
            parameters={
                "type": "object",
                "properties": {
                    "website_url": {
                        "type": "string",
                        "description_zh": "页面链接",
                        "description_en": "Website Url"
                    }
                },
                "required": ["website_url"]
            }
        )
    }


def mark_step_skill():
    return {
        'skill_name': 'mark_step',
        'skill_type': "function",
        'display_name_zh': '标记步骤',
        'display_name_en': 'Mark Step',
        'description_zh': '标记计划中的步骤状态，包括执行结果、遇到的问题、下一步建议等信息',
        'description_en': 'Mark the status of a step in the plan, including execution results, problems encountered, and suggestions for next steps',
        'semantic_apis': ["api_planning"],
        'function': SkillFunction(
            id='6d7f9a2b-c6e3-4f8d-b1a2-3e4f5d6c7b8c',
            name='zagents_framework.app.manus.tool.act_toolkit.ActToolkit.mark_step',
            description_zh='更新步骤的状态和备注，状态包括：已完成、受阻',
            description_en='Update the status and notes of a step, with status options: completed, blocked',
            parameters={
                "type": "object",
                "properties": {
                    'step_index': {
                        'type': 'integer',
                        'description_zh': '要更新的步骤索引（从0开始）',
                        'description_en': 'Index of the step to update (starting from 0)'
                    },
                    'step_status': {
                        'type': 'string',
                        'enum': ['completed', 'blocked'],
                        'description_zh': '步骤的新状态：\n'
                                          '- "completed": 步骤已完全执行且正确解决问题\n'
                                          '- "blocked": 步骤无法完成或未正确解决问题',
                        'description_en': 'New status for the step:\n'
                                          '- "completed": Step is fully executed AND correctly solved the problem\n'
                                          '- "blocked": Step cannot be completed OR did not correctly solve the problem'
                    },
                    'step_notes': {
                        'type': 'string',
                        'description_zh': '步骤的备注信息，包括：\n'
                                          '- 详细执行结果\n'
                                          '- 遇到的问题\n'
                                          '- 下一步建议\n'
                                          '- 对其他步骤的依赖\n'
                                          '- 生成的任何文件的绝对路径',
                        'description_en': 'Additional notes for the step, including:\n'
                                          '- Detailed execution results\n'
                                          '- Problems encountered\n'
                                          '- Suggestions for next steps\n'
                                          '- Dependencies on other steps\n'
                                          '- Absolute file paths of any generated files'
                    }
                },
                'required': ['step_index', 'step_status', 'step_notes']
            }
        )
    }


def file_saver_skill():
    return {
        'skill_name': 'file_saver',
        'skill_type': "function",
        'display_name_zh': '文件保存',
        'display_name_en': 'File Saver',
        'description_zh': '将内容保存到指定路径的本地文件中，支持文本和二进制文件（如图片、音频、视频）。默认模式为追加，以保留文件原有内容',
        'description_en': 'Save content to a local file at a specified path. Supports both text and binary files (e.g., images, audio, video). Default mode is append to preserve existing file content',
        'semantic_apis': ["api_file_management"],
        'function': SkillFunction(
            id='5c44f9ad-be5c-4e6c-a9d8-1426b23828a2',
            name='zagents_framework.app.manus.tool.file_toolkit.FileToolkit.file_saver',
            description_zh='将内容保存到指定路径的文件中，支持文本和二进制文件。默认模式为追加',
            description_en='Save content to a file at the specified path. Supports both text and binary files. Default mode is append',
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description_zh": "要保存的内容（文本或base64编码的二进制数据）",
                        "description_en": "Content to be saved (text or base64 encoded binary data)"
                    },
                    "file_path": {
                        "type": "string",
                        "description_zh": "要保存文件的绝对路径（需在工作区内，WORKSPACE_PATH环境变量指定）",
                        "description_en": "Absolute path of the file to save (must be within workspace specified by WORKSPACE_PATH environment variable)"
                    },
                    "mode": {
                        "type": "string",
                        "description_zh": "文件打开模式：'a' 追加（默认），'w' 写入",
                        "description_en": "File opening mode: 'a' for append (default), 'w' for write",
                        "enum": ["a", "w"],
                        "default": "a"
                    },
                    "binary": {
                        "type": "boolean",
                        "description_zh": "是否为二进制文件模式",
                        "description_en": "Whether to use binary mode",
                        "default": False
                    }
                },
                "required": ["content", "file_path"]
            }
        )
    }


def file_download_skill():
    return {
        'skill_name': 'download_file',
        'skill_type': "function",
        'display_name_zh': '远程文件下载工具',
        'display_name_en': 'Remote File Download',
        'description_zh': '下载远程文件并保存到指定路径（如果文件已存在，将自动覆盖）。',
        'description_en': 'Download a remote file and save it to the specified path.If the file already exists, it will be overwritten.',
        'semantic_apis': ["api_file_management"],
        'function': SkillFunction(
            id='5c44f9ad-be5c-4e6c-a9d8-1426b23828a2',
            name='zagents_framework.app.manus.tool.file_toolkit.FileToolkit.file_saver',
            description_zh='下载远程文件并保存到指定路径（如果文件已存在，将自动覆盖）。',
            description_en='Download a remote file and save it to the specified path.If the file already exists, it will be overwritten.',
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description_zh": "文件的 URL 地址",
                        "description_en": "The URL of the file to download."
                    },
                    "dest_path": {
                        "type": "string",
                        "description_zh": "要保存文件的绝对路径（需在工作区内，WORKSPACE_PATH环境变量指定）",
                        "description_en": "Absolute path of the file to save (must be within workspace specified by WORKSPACE_PATH environment variable)"
                    }
                },
                "required": ["url", "dest_path"]
            }
        )
    }


def file_read_skill():
    return {
        'skill_name': 'file_read',
        'skill_type': "function",
        'display_name_zh': '文件读取',
        'display_name_en': 'File Read',
        'description_zh': '读取指定路径的本地文件内容，支持文本和二进制文件（如图片、音频、视频）',
        'description_en': 'Read content from a local file at a specified path. Supports both text and binary files (e.g., images, audio, video)',
        'semantic_apis': ["api_file_management"],
        'function': SkillFunction(
            id='6c44f9ad-be5c-4e6c-a9d8-1426b23828a3',
            name='zagents_framework.app.manus.tool.file_toolkit.FileToolkit.file_read',
            description_zh='读取指定路径的文件内容，支持文本和二进制文件',
            description_en='Read content from a file at the specified path. Supports both text and binary files',
            parameters={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description_zh": "要读取的文件的绝对路径（需在工作区内，WORKSPACE_PATH环境变量指定）",
                        "description_en": "Absolute path of the file to read (must be within workspace specified by WORKSPACE_PATH environment variable)"
                    },
                    "start_line": {
                        "type": "integer",
                        "description_zh": "起始行号（从0开始，仅文本文件）",
                        "description_en": "Starting line number (0-based, text files only)",
                        "minimum": 0
                    },
                    "end_line": {
                        "type": "integer",
                        "description_zh": "结束行号（不包括该行，仅文本文件）",
                        "description_en": "Ending line number (exclusive, text files only)",
                        "minimum": 0
                    },
                    "sudo": {
                        "type": "boolean",
                        "description_zh": "是否使用sudo权限",
                        "description_en": "Whether to use sudo privileges",
                        "default": False
                    },
                    "binary": {
                        "type": "boolean",
                        "description_zh": "是否为二进制文件模式",
                        "description_en": "Whether to use binary mode",
                        "default": False
                    }
                },
                "required": ["file"]
            }
        )
    }


def file_str_replace_skill():
    return {
        'skill_name': 'file_str_replace',
        'skill_type': "function",
        'display_name_zh': '文件字符串替换',
        'display_name_en': 'File String Replacement',
        'description_zh': '替换文件中的指定字符串，用于更新文件内容或修复代码错误',
        'description_en': 'Replace specified string in a file. Use for updating specific content in files or fixing errors in code',
        'semantic_apis': ["api_file_management"],
        'function': SkillFunction(
            id='7c44f9ad-be5c-4e6c-a9d8-1426b23828a4',
            name='zagents_framework.app.manus.tool.file_toolkit.FileToolkit.file_str_replace',
            description_zh='替换文件中的指定字符串',
            description_en='Replace specified string in a file',
            parameters={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description_zh": "要执行替换操作的文件路径",
                        "description_en": "Absolute path of the file to perform replacement on"
                    },
                    "old_str": {
                        "type": "string",
                        "description_zh": "要被替换的原始字符串",
                        "description_en": "Original string to be replaced"
                    },
                    "new_str": {
                        "type": "string",
                        "description_zh": "用于替换的新字符串",
                        "description_en": "New string to replace wiEth"
                    },
                    "sudo": {
                        "type": "boolean",
                        "description_zh": "是否使用sudo权限",
                        "description_en": "Whether to use sudo privileges",
                        "default": False
                    }
                },
                "required": ["file", "old_str", "new_str"]
            }
        )
    }


def file_find_in_content_skill():
    return {
        'skill_name': 'file_find_in_content',
        'skill_type': "function",
        'display_name_zh': '文件内容查找',
        'display_name_en': 'Find in File Content',
        'description_zh': '在文件内容中搜索匹配的文本，用于查找特定内容或模式',
        'description_en': 'Search for matching text within file content. Use for finding specific content or patterns in files',
        'semantic_apis': ["api_file_management"],
        'function': SkillFunction(
            id='8c44f9ad-be5c-4e6c-a9d8-1426b23828a5',
            name='zagents_framework.app.manus.tool.file_toolkit.FileToolkit.file_find_in_content',
            description_zh='在文件内容中搜索匹配的文本',
            description_en='Search for matching text within file content',
            parameters={
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "description_zh": "要搜索的文件路径",
                        "description_en": "Absolute path of the file to search within"
                    },
                    "regex": {
                        "type": "string",
                        "description_zh": "要匹配的正则表达式模式",
                        "description_en": "Regular expression pattern to match"
                    },
                    "sudo": {
                        "type": "boolean",
                        "description_zh": "是否使用sudo权限",
                        "description_en": "Whether to use sudo privileges",
                        "default": False
                    }
                },
                "required": ["file", "regex"]
            }
        )
    }


def register_mcp_tools():
    # 解析mcp工具
    skills = JsonUtil.read_all_data(mcp_server_config_dir)
    return skills


def deep_search_skill():
    return {
        'skill_name': 'deep_search',
        'skill_type': "function",
        'display_name_zh': '深度搜索',
        'display_name_en': 'Deep Search',
        'description_zh': '使用深度搜索引擎进行信息检索和分析',
        'description_en': 'Use deep-search engine for multi-source information retrieval and analysis',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='8d5e7f3b-a4c2-4d1b-9f6e-2c8b9d7e1234',
            name='zagents_framework.app.manus.tool.deep_search_toolkit.deep_search',
            description_zh='通过深度搜索引擎获取搜索结果并进行分析总结',
            description_en='Get and analyze search results using deep-search engine with multiple sources',
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description_zh": "要搜索的查询内容",
                        "description_en": "Query to be searched"
                    }
                },
                "required": ["query"]
            }
        )
    }


def search_content_skill():
    return {
        'skill_name': 'search_content',
        'skill_type': "function",
        'display_name_zh': '内容搜索',
        'display_name_en': 'Content Search',
        'description_zh': '使用搜索引擎进行信息检索和分析',
        'description_en': 'Use search engine for multi-source information retrieval and analysis',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='8d5e7f3b-a4c2-4d1b-9f6e-2c8b9d7e1234',
            name='zagents_framework.app.manus.tool.deep_search_toolkit.deep_search',
            description_zh='通过内容搜索引擎获取搜索结果并进行分析总结',
            description_en='Get and analyze search results using search engine with multiple sources',
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description_zh": "要搜索的查询内容",
                        "description_en": "Query to be searched"
                    }
                },
                "required": ["query"]
            }
        )
    }


def ask_question_about_video_skill():
    return {
        'skill_name': 'ask_question_about_video',
        'skill_type': "function",
        'display_name_zh': '解析任一视频，获取视频内容',
        'display_name_en': 'Parse any video to get the video content',
        'description_zh': '解析任一视频，获取视频内容',
        'description_en': 'Parse any video to get the video content',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='8d5e7f3b-a4c2-4d1b-9f6e-2c8b9d7e1234',
            name='zagents_framework.app.manus.tool.deep_search_toolkit.deep_search',
            description_zh='解析任一视频，获取视频内容',
            description_en='Parse any video to get the video content',
            parameters={
                "type": "object",
                "properties": {
                    "video_path": {
                        "type": "string",
                        "description_zh": "视频路径",
                        "description_en": "Video path"
                    },
                    "question": {
                        "type": "string",
                        "description_zh": "要提问的问题",
                        "description_en": "question"
                    }
                },

                "required": ["video_path", "question"]
            }
        )
    }


def audio_recognition_skill():
    return {
        'skill_name': 'audio_recognition',
        'skill_type': "function",
        'display_name_zh': '根据任务描述和输入音频文件（支持mp3，wav格式文件）识别输出音频内容',
        'display_name_en': 'Identify the output audio content based on the task description and input audio file(support mp3、wav file)',
        'description_zh': '根据任务描述和输入音频文件（支持mp3，wav格式文件）识别输出音频内容',
        'description_en': 'Identify the output audio content based on the task description and input audio file(support mp3、wav file)',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='8d5e7f3b-a4c2-4d1b-9f6e-2c8b9d7e1234',
            name='zagents_framework.app.manus.tool.deep_search_toolkit.deep_search',
            description_zh='根据任务描述和输入音频文件（支持mp3，wav格式文件）识别输出音频内容',
            description_en='Identify the output audio content based on the task description and input audio file(support mp3、wav file)',
            parameters={
                "type": "object",
                "properties": {
                    "audio_path": {
                        "type": "string",
                        "description_zh": "音频路径",
                        "description_en": "Audio path"
                    },
                    "task_prompt": {
                        "type": "string",
                        "description_zh": "任务内容描述",
                        "description_en": "task description"
                    }
                },

                "required": ["audio_path", "task_prompt"]
            }
        )
    }


def ask_question_about_image_skill():
    return {
        'skill_name': 'ask_question_about_image',
        'skill_type': "function",
        'display_name_zh': '根据任务描述解析图片内容',
        'display_name_en': 'Image Content analyse',
        'description_zh': '根据任务描述解析图片内容',
        'description_en': 'Ask a question about the image.',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='8d5e7f3b-a4c2-4d1b-9f6e-2c8b9d7e1234',
            name='zagents_framework.app.manus.tool.deep_search_toolkit.deep_search',
            description_zh='图片内容解析',
            description_en='Ask a question about the image.',
            parameters={
                "type": "object",
                "properties": {
                    "image_path_url": {
                        "type": "string",
                        "description_zh": "图片路径",
                        "description_en": "Image path"
                    },
                    "task_prompt": {
                        "type": "string",
                        "description_zh": "任务内容描述",
                        "description_en": "task description"
                    }
                },

                "required": ["image_path_url", "task_prompt"]
            }
        )
    }


def extract_document_content_skill():
    return {
        'skill_name': 'extract_document_content',
        'skill_type': "function",
        'display_name_zh': '读取jsonl，json，jsonld，zip，md，py，xml，docx，pptx，pdf等类型文件内容',
        'display_name_en': 'Read contents from files of types such as .jsonl, .json, .jsonld, .zip, .md, .py, .xml, .docx, .pptx, .pdf, and others.',
        'description_zh': '读取jsonl，json，jsonld，zip，md，py，xml，docx，pptx，pdf等类型文件内容',
        'description_en': 'Read contents from files of types such as .jsonl, .json, .jsonld, .zip, .md, .py, .xml, .docx, .pptx, .pdf, and others.',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='8d5e7f3b-a4c2-4d1b-9f6e-2c8b9d7e1234',
            name='zagents_framework.app.manus.tool.deep_search_toolkit.deep_search',
            description_zh='读取jsonl，json，jsonld，zip，md，py，xml，docx，pptx，pdf等类型文件内容',
            description_en='Read contents from files of types such as .jsonl, .json, .jsonld, .zip, .md, .py, .xml, .docx, .pptx, .pdf, and others.',
            parameters={
                "type": "object",
                "properties": {
                    "document_path": {
                        "type": "string",
                        "description_zh": "文件路径",
                        "description_en": "File path"
                    }
                },

                "required": ["document_path"]
            }
        )
    }


def html_visualization_skill():
    return {
        'skill_name': 'create_visualization',
        'skill_type': "function",
        'display_name_zh': 'HTML可视化图表',
        'display_name_en': 'HTML Visualization Chart',
        'description_zh': '创建基于HTML的数据可视化图表，可以保存为HTML文件或返回HTML内容',
        'description_en': 'Create HTML-based data visualizations that can be saved to an HTML file or returned as HTML content',
        'semantic_apis': ["api_data_visualization"],
        'function': SkillFunction(
            id='9c44f9ad-be5c-4e6c-a9d8-1426b23828a9',
            name='zagents_framework.app.manus.tool.html_visualization_toolkit.HTMLVisualizationToolkit.create_visualization',
            description_zh='创建交互式数据可视化图表，支持多种图表类型',
            description_en='Create interactive data visualizations with support for various chart types',
            parameters={
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "line", "pie", "scatter", "heatmap", "table", "histogram", "boxplot", "treemap",
                                 "sankey"],
                        "description_zh": "图表类型：条形图、折线图、饼图、散点图、热力图、表格、直方图、箱线图、树图或桑基图",
                        "description_en": "Type of chart: bar, line, pie, scatter, heatmap, table, histogram, boxplot, treemap, or sankey"
                    },
                    "data": {
                        "type": "string",
                        "description_zh": "图表数据的JSON字符串。格式取决于图表类型",
                        "description_en": "JSON string containing data for the visualization. Format depends on chart type"
                    },
                    "title": {
                        "type": "string",
                        "description_zh": "图表标题",
                        "description_en": "Chart title",
                        "default": "Visualization"
                    },
                    "width": {
                        "type": "integer",
                        "description_zh": "图表宽度（像素）",
                        "description_en": "Width of the chart in pixels",
                        "default": 800
                    },
                    "height": {
                        "type": "integer",
                        "description_zh": "图表高度（像素）",
                        "description_en": "Height of the chart in pixels",
                        "default": 500
                    },
                    "options": {
                        "type": "string",
                        "description_zh": "图表特定配置选项的JSON字符串",
                        "description_en": "JSON string with chart-specific configuration options",
                        "default": "{}"
                    },
                    "file_path": {
                        "type": "string",
                        "description_zh": "保存生成的HTML的绝对路径（使用WORKSPACE_PATH环境变量）。如果为空，则直接返回HTML内容",
                        "description_en": "Absolute path (using the WORKSPACE_PATH environment variable) to save the generated HTML. If None, HTML is returned as string."
                    }
                },
                "required": ["chart_type", "data"]
            }
        )
    }


def create_report_skill():
    return {
        'skill_name': 'create_report',
        'skill_type': "function",
        'display_name_zh': 'HTML交互式报告生成',
        'display_name_en': 'HTML Interactive Report Creation',
        'description_zh': '创建包含多个可视化图表和格式化文本的完整HTML报告，自动检测和生成可视化内容',
        'description_en': 'Create complete HTML reports with multiple visualizations, formatted text, and automatic chart detection',
        'semantic_apis': ["api_report_generation"],
        'function': SkillFunction(
            id='ac44f9ad-be5c-4e6c-a9d8-1426b23828b9',
            name='zagents_framework.app.manus.tool.html_visualization_toolkit.HTMLVisualizationToolkit.create_report',
            description_zh='生成包含多个可视化图表和文本内容的交互式HTML报告，支持自动检测和整合图表数据',
            description_en='Generate interactive HTML reports with multiple visualizations and text content, with automatic chart detection and integration',
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description_zh": "报告标题",
                        "description_en": "Report title",
                        "default": "Interactive Report"
                    },
                    "content": {
                        "type": "string",
                        "description_zh": "报告正文内容（支持Markdown或HTML格式，可包含图表数据）",
                        "description_en": "Report body content (supports Markdown or HTML formatting, can include chart data)",
                        "default": ""
                    },
                    "visualizations": {
                        "type": "string",
                        "description_zh": "可视化图表配置的JSON字符串数组，格式为：[{\"chart_type\": \"bar\", \"data\": [{...}], \"title\": \"图表标题\", \"options\": {...}}]",
                        "description_en": "JSON string array of visualization configurations with format: [{\"chart_type\": \"bar\", \"data\": [{...}], \"title\": \"Chart Title\", \"options\": {...}}]",
                        "default": "[]"
                    },
                    "html_files": {
                        "type": "string",
                        "description_zh": "HTML文件路径JSON字符串数组，用于从现有可视化文件中提取图表",
                        "description_en": "JSON string array of HTML file paths to extract visualizations from existing files",
                        "default": "[]"
                    },
                    "css_theme": {
                        "type": "string",
                        "enum": ["default", "light", "dark", "professional"],
                        "description_zh": "报告样式主题：默认、浅色、深色或专业",
                        "description_en": "Report styling theme: default, light, dark, or professional",
                        "default": "default"
                    },
                    "file_path": {
                        "type": "string",
                        "description_zh": "保存生成的HTML的绝对路径（使用WORKSPACE_PATH环境变量）。如果为空，则直接返回HTML内容",
                        "description_en": "Absolute path (using the WORKSPACE_PATH environment variable) to save the generated HTML. If None, HTML is returned as string."
                    }
                },
                "required": ["title", "file_path"]
            }
        )
    }


def search_bocha_skill():
    return {
        'skill_name': 'search_bocha',
        'skill_type': "function",
        'display_name_zh': '博查web搜索',
        'display_name_en': 'BoCha Search',
        'description_zh': '从全网搜索任何网页信息和网页链接，结果准确、摘要完整。包括网页、图片、视频。',
        'description_en': 'Search for any web page information and web links from the whole web, and the results are accurate and complete. This includes web pages, images, and videos.',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='3c44f9ad-be5c-4e6c-a9d8-1426b23828a0',
            name='zagents_framework.app.manus.search_toolkit.search_google',
            description_zh='从全网搜索任何网页信息和网页链接，结果准确、摘要完整。包括网页、图片、视频。',
            description_en='Search for any web page information and web links from the whole web, and the results are accurate and complete. This includes web pages, images, and videos.',
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description_zh": "要搜索的查询内容",
                        "description_en": "Query to be searched"
                    },
                    "freshness": {
                        "type": "string",
                        "description_zh": "搜索指定时间范围内的网页.oneDay，一天内; oneWeek，一周内;oneMonth，一个月内;oneYear，一年内;noLimit，不限（默认）;YYYY-MM-DD..YYYY-MM-DD，搜索日期范围，例如：\"2025-01-01..2025-04-06\";YYYY-MM-DD，搜索指定日期，例如：\"2025-04-06\"",
                        "description_en": "Search for web pages within a specified time range.oneDay, within one day; oneWeek, within a week; oneMonth, within one month; oneYear, within one year; noLimit, unlimited (default); YYYY-MM-DD.. YYYY-MM-DD, search for a date range, for example: \"2025-01-01..2025-04-06\"; YYYY-MM-DD, search for a specified date, for example: \"2025-04-06\""
                    },
                    "summary": {
                        "type": "string",
                        "description_zh": "是否显示文本摘要",
                        "description_en": "Whether to display a text summary"
                    },
                    "count": {
                        "type": "string",
                        "description_zh": "返回结果的条数（实际返回结果数量可能会小于count指定的数量）",
                        "description_en": "The number of returned results (the actual number of returned results may be less than the number specified in count)"
                    },
                    "page": {
                        "type": "string",
                        "description_zh": "页码，默认值为 1",
                        "description_en": "Page number, default is 1"
                    }
                },
                "required": ["query"]
            }
        )
    }
