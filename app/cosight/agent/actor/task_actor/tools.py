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
from config.config import get_tavily_config


def build_task_actor_functions(
    plan,
    work_space_path: str,
    tool_llm,
    vision_llm,
    question_ref: list,
) -> Dict[str, Any]:
    act_toolkit = ActToolkit(plan)
    file_toolkit = FileToolkit(work_space_path)
    image_toolkit = VisionTool({
        "base_url": vision_llm.base_url,
        "model": vision_llm.model,
        "api_key": vision_llm.api_key,
    })
    audio_toolkit = AudioTool({
        "base_url": vision_llm.base_url,
        "model": vision_llm.model,
        "api_key": vision_llm.api_key,
    })
    video_toolkit = VideoTool({
        "base_url": vision_llm.base_url,
        "model": vision_llm.model,
        "api_key": vision_llm.api_key,
    })
    doc_toolkit = DocumentProcessingToolkit()
    search_toolkit = SearchToolkit()
    deep_search_toolkit = DeepSearchToolkit(
        {
            "base_url": tool_llm.base_url,
            "api_key": tool_llm.api_key,
            "model_name": tool_llm.model,
        },
        {"api_key": get_tavily_config()},
    )
    code_toolkit = CodeToolkit(sandbox="subprocess")


    all_functions = {
        "mark_step": act_toolkit.mark_step,
        "search_google": search_toolkit.search_google,
        "search_wiki": search_toolkit.search_wiki,
        "tavily_search": search_toolkit.tavily_search,
        "audio_recognition": audio_toolkit.speech_to_text,
        "execute_code": code_toolkit.execute_code,
        "file_saver": file_toolkit.file_saver,
        "file_read": file_toolkit.file_read,
        "file_str_replace": file_toolkit.file_str_replace,
        "file_find_in_content": file_toolkit.file_find_in_content,
        "ask_question_about_image": image_toolkit.ask_question_about_image,
        "ask_question_about_video": video_toolkit.ask_question_about_video,
        "fetch_website_content": fetch_website_content,
        "fetch_website_content_with_images": fetch_website_content_with_images,
        "fetch_website_images_only": fetch_website_images_only,
        "extract_document_content": doc_toolkit.extract_document_content,
    }
    return all_functions
