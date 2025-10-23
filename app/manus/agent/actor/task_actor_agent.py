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

import traceback
from typing import Dict

from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
from app.manus.agent.actor.prompt.actor_prompt import actor_system_prompt, actor_execute_task_prompt, \
    update_facts_prompt
from app.manus.agent.base.base_agent import BaseAgent
from app.manus.llm.chat_llm import ChatLLM
from app.manus.task.plan_report_manager import plan_report_event_manager
from app.manus.task.task_manager import TaskManager
from app.manus.task.time_record_util import time_record
from app.manus.tool.act_toolkit import ActToolkit
from app.manus.tool.arxiv_toolkit import ArxivToolkit
from app.manus.tool.audio_toolkit import AudioTool
# from app.manus.tool.browser_simulation import brower_use_cal
from app.manus.tool.code_toolkit import CodeToolkit
from app.manus.tool.document_processing_toolkit import DocumentProcessingToolkit
from app.manus.tool.file_download_toolkit import download_file
from app.manus.tool.file_toolkit import FileToolkit
# from app.manus.tool.google_search_util import search_google
from app.manus.tool.image_analysis_toolkit import VisionTool
from app.manus.tool.scrape_website_toolkit import fetch_website_content
from app.manus.tool.search_toolkit import SearchToolkit
from app.manus.tool.terminate_toolkit import TerminateToolkit
from app.manus.tool.video_analysis_toolkit import VideoTool
from app.manus.tool.web_util import sync_browser_use
from app.manus.tool.excel_toolkit import read_excel_color


class TaskActorAgent(BaseAgent):
    def __init__(self, agent_instance: AgentInstance, llm: ChatLLM,
                 vision_llm: ChatLLM,
                 tool_llm: ChatLLM,
                 plan_id,
                 functions: Dict = None):
        self.plan = TaskManager.get_plan(plan_id)
        act_toolkit = ActToolkit(self.plan)
        terminate_toolkit = TerminateToolkit()
        file_toolkit = FileToolkit()

        image_toolkit = VisionTool({"base_url": vision_llm.base_url,
                                    "model": vision_llm.model,
                                    "temperature": vision_llm.temperature,
                                    "api_key": vision_llm.api_key})
        audio_toolkit = AudioTool({"base_url": vision_llm.base_url,
                                   "model": vision_llm.model,
                                   "temperature": vision_llm.temperature,
                                   "api_key": vision_llm.api_key})
        video_toolkit = VideoTool({"base_url": vision_llm.base_url,
                                   "model": vision_llm.model,
                                   "temperature": vision_llm.temperature,
                                   "api_key": vision_llm.api_key})
        doc_toolkit = DocumentProcessingToolkit({"base_url": tool_llm.base_url,
                                                 "model": tool_llm.model,
                                                 "temperature": tool_llm.temperature,
                                                 "api_key": tool_llm.api_key})
        # search_toolkit = SearchToolkit()
        search_toolkit = SearchToolkit({"base_url": tool_llm.base_url,
                                                 "model": tool_llm.model,
                                                 "temperature": tool_llm.temperature,
                                                 "api_key": tool_llm.api_key})
        arxiv_toolkit = ArxivToolkit()
        code_toolkit = CodeToolkit(sandbox="subprocess")
        all_functions = {
            # "read_excel_color": read_excel_color,
            # "download_wiki_main_image": search_toolkit.download_wiki_main_image,
            # "download_youtube_channel_thumbnails": search_toolkit.download_youtube_channel_thumbnails,
            # "download_wiki_commons_image": search_toolkit.download_wiki_commons_image,
            # "get_wikipedia_revision_record": search_toolkit.get_wikipedia_revision_record,
            # "count_youtube_videos_number": search_toolkit.count_youtube_videos_number,

            "search_wiki_history_url": search_toolkit.search_wiki_history_url,
            "search_wiki": search_toolkit.search_wiki,
            "search_google": search_toolkit.search_google,
            # "browser_use": sync_browser_use,

            "mark_step": act_toolkit.mark_step,
            "file_saver": file_toolkit.write_to_file,
            "file_read": file_toolkit.file_read,
            "execute_code": code_toolkit.execute_code,
            "file_str_replace": file_toolkit.file_str_replace,
            "file_find_in_content": file_toolkit.file_find_in_content,
            "audio_recognition": audio_toolkit.speech_to_text,
            "ask_question_about_image": image_toolkit.ask_question_about_image,
            "ask_question_about_video": video_toolkit.ask_question_about_video,
            "fetch_website_content": fetch_website_content,
            # "extract_document_content": doc_toolkit.extract_document_content,
            "ask_question_by_extract_document_content": doc_toolkit.ask_question_about_document,

            "search_papers": arxiv_toolkit.search_papers,
            "download_papers": arxiv_toolkit.download_papers,
            "download_file": download_file,
            # "execute_shell_command": shell_tool.execute,
        }
        if functions:
            all_functions = functions.update(functions)
        super().__init__(agent_instance, llm, all_functions)
        self.history.append({"role": "system", "content": actor_system_prompt()})

    @time_record
    def act(self, question, step_index):
        self.plan.mark_step(step_index, step_status="in_progress")
        plan_report_event_manager.publish("plan_process", self.plan)
        self.history.append(
            {"role": "user", "content": actor_execute_task_prompt(question, step_index, self.plan)})
        try:
            result = self.execute(self.history, step_index=step_index, plan=self.plan)
            if self.plan.step_statuses.get(self.plan.steps[step_index], "") == "in_progress":
                self.plan.mark_step(step_index, step_status="completed", step_notes=str(result))
            self.update_fact(question)
            pass

            return result
        except Exception as e:
            self.plan.mark_step(step_index, step_status="blocked", step_notes=str(e))
            print(traceback.format_exc())
            return str(e)

    def update_fact(self, question):
        self.history.append({"role": "user", "content": update_facts_prompt(question, self.plan.facts)})
        result = self.llm.chat_to_llm(self.history)
        self.history.append({"role": "assistant", "content": result})
        self.plan.update_facts(result)
        pass
        return result

    def single_act(self, question):
        execute_task_prompt = f"""
Here are auxiliary information about the overall task, which may help you understand the intent of the current task: {question}
Think carefully step by step to execute the current task. If there are available tools and you want to call them, never say 'I will ...', but first call the tool and reply based on tool call's result, and tell me which tool you have called.         
"""
        self.history.append({"role": "user", "content": execute_task_prompt})
        try:
            result = self.execute(self.history, plan=self.plan)
            pass
            return result
        except Exception as e:
            print(traceback.format_exc())
            return str(e)
