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

"""Build all_functions dict for TaskActorAgent. question_ref is a mutable ref (e.g. list) so create_html_report lambda can read current question."""

from typing import Dict, Any

from app.cosight.tool.act_toolkit import ActToolkit
from app.cosight.tool.code_toolkit import CodeToolkit
from app.cosight.tool.file_toolkit import FileToolkit
from app.cosight.tool.terminate_toolkit import TerminateToolkit
from app.cosight.tool.web_util import WebToolkit
from app.cosight.tool.image_analysis_toolkit import VisionTool
from app.cosight.tool.document_processing_toolkit import DocumentProcessingToolkit
from app.cosight.tool.search_toolkit import SearchToolkit
from app.cosight.tool.deep_search.deep_search import DeepSearchToolkit
from app.cosight.tool.scrape_website_toolkit import (
    fetch_website_content,
    fetch_website_content_with_images,
    fetch_website_images_only,
)
from app.cosight.tool.deep_search.searchers.tavily_search import TavilySearch
from app.cosight.tool.audio_toolkit import AudioTool
from app.cosight.tool.video_analysis_toolkit import VideoTool
from app.cosight.tool.html_visualization_toolkit import HtmlVisualizationToolkit
from config.config import get_tavily_config


def build_general_actor_functions(
    plan,
    work_space_path: str,
) -> Dict[str, Any]:
    act_toolkit = ActToolkit(plan)
    file_toolkit = FileToolkit(work_space_path)
    code_toolkit = CodeToolkit(sandbox="subprocess")

    all_functions = {
        "mark_step": act_toolkit.mark_step,
        "execute_code": code_toolkit.execute_code,
        "file_saver": file_toolkit.file_saver,
        "file_read": file_toolkit.file_read,
        "file_str_replace": file_toolkit.file_str_replace,
        "file_find_in_content": file_toolkit.file_find_in_content
    }
    return all_functions
