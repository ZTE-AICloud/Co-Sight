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

from typing import Optional

from app.cosight.task.todolist import Plan
from app.common.logger_util import logger


class ActToolkit:
    r"""A class representing a toolkit for executing steps in a plan and marking their status."""

    def __init__(self, plan: Optional[Plan] = None):
        self.plan = plan

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

        self.plan.mark_step(step_index, step_status, step_notes)
        result = f"Step {step_index}: step_status is {step_status}, step_notes is {step_notes} "
        logger.info(f"ActToolkit mark_step result: {result}")
        logger.info(f"ActToolkit plan: {self.plan.format(True)}")
        return result
