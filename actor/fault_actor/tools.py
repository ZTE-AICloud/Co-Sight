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

"""Build all_functions for FaultActorAgent (file, doc, search, report only)."""

from typing import Dict, Any

from app.cosight.tool.act_toolkit import ActToolkit
from app.cosight.tool.agent_skills.run_terminal_cmd import run_terminal_cmd
from app.cosight.tool.agent_skills.skill_skill import skill_skill
from app.cosight.tool.file_toolkit import FileToolkit
from app.cosight.tool.document_processing_toolkit import DocumentProcessingToolkit
from app.cosight.tool.search_toolkit import SearchToolkit
from app.cosight.tool.html_visualization_toolkit import HtmlVisualizationToolkit


def build_fault_actor_functions(
    plan,
    work_space_path: str,
) -> Dict[str, Any]:
    act_toolkit = ActToolkit(plan)
    file_toolkit = FileToolkit(work_space_path)
    all_functions = {
        "mark_step": act_toolkit.mark_step,
        "file_read": file_toolkit.file_read,
        "file_saver": file_toolkit.file_saver,
        "skill": skill_skill,
        "run_terminal_cmd": run_terminal_cmd,
    }
    return all_functions

