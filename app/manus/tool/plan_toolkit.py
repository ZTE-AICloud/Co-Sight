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

import ast
from typing import List, Optional, Dict

from app.manus.task.plan_report_manager import plan_report_event_manager
from app.manus.task.todolist import Plan


class PlanToolkit:
    r"""A class representing a toolkit for creating and managing a single plan."""

    def __init__(self, plan: Optional[Plan] = None):
        self.plan = plan

    def create_plan(self, title: str, steps: List[str], dependencies: Optional[Dict[int, List[int]]] = None) -> str:
        r"""Create a new plan with the given title, steps, and dependencies.

        Args:
            title (str): Title for the plan
            steps (List[str]): List of steps for the plan
            dependencies (Optional[Dict[int, List[int]]]): Dictionary of step dependencies
                e.g., {1: [0]} means step 1 depends on step 0. If None, steps will be sequential.

        Returns:
            str: Success message with plan details
        """
        print(f"create plan, title is {title}, steps is {steps}, dependencies({type(dependencies)}) is {dependencies}")

        if dependencies and isinstance(dependencies, str):
            try:
                dependencies = ast.literal_eval(dependencies)
            except Exception as e:
                print(f"Plan Warning: not literal_eval('{dependencies}') to dict")
                dependencies = None

        # Generate sequential dependencies if None
        if dependencies is None and len(steps) > 1:
            dependencies = {i: [i-1] for i in range(1, len(steps))}
            
        self.plan.update(title,steps,dependencies)
        result = f"Plan created successfully\n\n{self.plan.format()}"
        plan_report_event_manager.publish("plan_created", self.plan)
        print(result)
        return result

    def update_plan(self, title: Optional[str] = None, steps: Optional[List[str]] = None,
                    dependencies: Optional[Dict[int, List[int]]] = None) -> str:
        r"""Update the existing plan with new title, steps, or dependencies while preserving completed steps.

        Args:
            title (Optional[str]): New title for the plan
            steps (Optional[List[str]]): New list of steps for the plan
            dependencies (Optional[Dict[int, List[int]]]): New dependencies between steps

        Returns:
            str: Success message with updated plan details
        """
        if self.plan is None:
            return "No plan exists. Create a plan with the 'create' command."

        print(f"update plan, title is {title}, steps is {steps}, dependencies({type(dependencies)}) is {dependencies}")

        if dependencies and isinstance(dependencies, str):
            try:
                dependencies = ast.literal_eval(dependencies)
            except Exception as e:
                print(f"Plan Warning: not literal_eval('{dependencies}') to dict")
                dependencies = None

        self.plan.update(title, steps, dependencies)
        result = f"Plan updated successfully\n\n{self.plan.format()}"
        plan_report_event_manager.publish("plan_updated", self.plan)
        print(f"update result is {result}")
        return result
