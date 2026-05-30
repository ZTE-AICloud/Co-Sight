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

import json
import os
from typing import Optional

from app.cosight.task.todolist import Plan
from app.common.logger_util import logger


class ActToolkit:
    r"""A class representing a toolkit for executing steps in a plan and marking their status."""

    def __init__(self, plan: Optional[Plan] = None):
        self.plan = plan

    def _is_report_completion_step(self, step_index: int) -> bool:
        if not self.plan or step_index < 0 or step_index >= len(self.plan.steps):
            return False

        step_text = (self.plan.steps[step_index] or "").lower()
        title_text = (getattr(self.plan, "title", "") or "").lower()
        is_last_step = step_index == len(self.plan.steps) - 1
        escaped_text = f"{step_text} {title_text}".encode("unicode_escape").decode("ascii")
        escaped_report_keywords = (
            "\\u62a5\\u544a", "\\u603b\\u7ed3", "\\u6c47\\u603b",
            "\\u7efc\\u5408\\u5206\\u6790", "\\u64b0\\u5199", "\\u751f\\u6210",
        )
        if any(keyword in escaped_text for keyword in escaped_report_keywords):
            return True
        report_keywords = (
            "报告", "总结", "汇总", "综合分析", "撰写", "生成",
            "report", "summary", "summarize", "final", "write",
        )
        has_report_intent = any(keyword in step_text or keyword in title_text for keyword in report_keywords)
        return has_report_intent or (is_last_step and any(keyword in title_text for keyword in report_keywords))

    def _current_step_has_markdown_save(self, step_index: int) -> bool:
        if not self.plan or step_index < 0 or step_index >= len(self.plan.steps):
            return False

        step = self.plan.steps[step_index]
        tool_calls = getattr(self.plan, "step_tool_calls", {}).get(step, [])
        workspace = getattr(self.plan, "work_space_path", "") or os.environ.get("WORKSPACE_PATH") or os.getcwd()

        for call in tool_calls:
            if call.get("tool_name") != "file_saver":
                continue
            result = str(call.get("tool_result") or "")
            if result.strip().lower().startswith(("error:", "error saving file", "execution error")):
                continue

            file_path = ""
            try:
                args = json.loads(call.get("tool_args") or "{}")
                if isinstance(args, dict):
                    file_path = args.get("file_path") or args.get("file") or args.get("filename") or ""
            except Exception:
                file_path = ""

            if not file_path:
                marker = "Content successfully saved to "
                if marker in result:
                    file_path = result.split(marker, 1)[1].strip()

            if not str(file_path).lower().endswith(".md"):
                continue

            candidate = file_path if os.path.isabs(file_path) else os.path.join(workspace, os.path.basename(file_path))
            if os.path.exists(candidate):
                return True

        return False

    def mark_step(self, step_index: int, step_status: str=None, step_notes: str=None, **kwargs) -> str:
        r"""Mark a single step with specific status and notes.

        Args:
            step_index (int): Index of the step to update
            step_status (str): New status for the step, considering:
                - "completed": Step is fully executed AND correctly solved the problem
                - "blocked": Step cannot be completed OR did not correctly solve the problem
            step_notes (str): Additional notes for the step, including:
                - Detailed execution results
                - Problems encountered
                - Suggestions for next steps
                - Dependencies on other steps
                - Absolute file paths of any generated files

        Returns:
            dict: Success to mark step
        """
        # Infer step_status from kwargs if not provided
        if step_status is None:
            for value in kwargs.values():
                if isinstance(value, str) and ("completed" in value or "blocked" in value):
                    step_status = "completed" if "completed" in value else "blocked"
                    break

        # Infer step_notes from kwargs if not provided
        if step_notes is None:
            step_notes = " ".join(f"{k}: {v}" for k, v in kwargs.items() if k not in ["step_status", "step_notes"]) if kwargs else ""

        if (
            step_status == "completed"
            and self._is_report_completion_step(step_index)
            and not self._current_step_has_markdown_save(step_index)
        ):
            warning = (
                "Final/report step cannot be marked completed because no Markdown "
                "file was saved with file_saver in this step."
            )
            logger.warning("mark_step downgraded to blocked: %s", warning)
            step_status = "blocked"
            step_notes = f"{step_notes}\n\n{warning}".strip()

        self.plan.mark_step(step_index, step_status, step_notes)
        result = f"Step {step_index}: step_status is {step_status}, step_notes is {step_notes} "
        logger.info(f"ActToolkit mark_step result: {result}")
        logger.info(f"ActToolkit plan: {self.plan.format(True)}")
        return result
