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


def search_arxiv_papers_skill():
    return {
        'skill_name': 'search_papers',
        'skill_type': "function",
        'display_name_zh': 'arXiv论文搜索',
        'display_name_en': 'arXiv Paper Search',
        'description_zh': '在arXiv上搜索学术论文，返回论文的标题、作者、摘要等信息',
        'description_en': 'Search for academic papers on arXiv, returning paper titles, authors, abstracts, etc.',
        'semantic_apis': ["api_search"],
        'function': SkillFunction(
            id='9c44f9ad-be5c-4e6c-a9d8-1426b23828a6',
            name='zagents_framework.app.manus.tool.arxiv_toolkit.ArxivToolkit.search_papers',
            description_zh='在arXiv上搜索学术论文并返回相关信息',
            description_en='Search for academic papers on arXiv and return relevant information',
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description_zh": "搜索查询字符串",
                        "description_en": "Search query string"
                    },
                    "paper_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description_zh": "要搜索的特定arXiv论文ID列表",
                        "description_en": "List of specific arXiv paper IDs to search for"
                    },
                    "max_results": {
                        "type": "integer",
                        "description_zh": "最大返回结果数量",
                        "description_en": "Maximum number of results to return",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        )
    }


def download_arxiv_papers_skill():
    return {
        'skill_name': 'download_arxiv_papers',
        'skill_type': "function",
        'display_name_zh': 'arXiv论文下载',
        'display_name_en': 'arXiv Paper Download',
        'description_zh': '从arXiv下载学术论文的PDF文件',
        'description_en': 'Download PDF files of academic papers from arXiv',
        'semantic_apis': ["api_file_management"],
        'function': SkillFunction(
            id='9c44f9ad-be5c-4e6c-a9d8-1426b23828a7',
            name='zagents_framework.app.manus.tool.arxiv_toolkit.ArxivToolkit.download_papers',
            description_zh='从arXiv下载指定论文的PDF文件',
            description_en='Download PDF files of specified papers from arXiv',
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description_zh": "搜索查询字符串",
                        "description_en": "Search query string"
                    },
                    "paper_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description_zh": "要下载的特定arXiv论文ID列表",
                        "description_en": "List of specific arXiv paper IDs to download"
                    },
                    "max_results": {
                        "type": "integer",
                        "description_zh": "最大下载数量",
                        "description_en": "Maximum number of papers to download",
                        "default": 5
                    },
                    "output_dir": {
                        "type": "string",
                        "description_zh": "保存PDF文件的目录路径",
                        "description_en": "Directory path to save PDF files",
                        "default": "./"
                    }
                },
                "required": ["query"]
            }
        )
    }
