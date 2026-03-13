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

from app.cosight.task.plan_report_manager import plan_report_event_manager
from app.cosight.task.todolist import Plan
from app.common.logger_util import logger


class PlanToolkit:
    r"""A class representing a toolkit for creating and managing a single plan."""

    def __init__(self, plan: Optional[Plan] = None):
        self.plan = plan

    def _parse_step_agents(self, step_agents: Optional[Dict]) -> Optional[Dict[int, str]]:
        if step_agents is None:
            return None
        if isinstance(step_agents, str):
            try:
                step_agents = ast.literal_eval(step_agents)
            except Exception as exc:
                logger.warning(f"Invalid step_agents payload: {exc}")
                return None
        if not isinstance(step_agents, dict):
            return None

        parsed: Dict[int, str] = {}
        allowed_actor_ids = set(getattr(self.plan, "allowed_actor_ids", []) or [])
        for raw_index, agent_id in step_agents.items():
            try:
                step_index = int(raw_index)
            except (TypeError, ValueError):
                logger.warning(f"Ignore invalid step index in step_agents: {raw_index}")
                continue
            if not agent_id:
                continue
            if allowed_actor_ids and agent_id not in allowed_actor_ids:
                logger.warning(f"Ignore unallowed actor assignment: step={step_index}, agent={agent_id}")
                continue
            parsed[step_index] = agent_id
        return parsed

    def create_plan(self, title: str, steps: List[str], dependencies: Optional[Dict[int, List[int]]] = None,
                     step_agents: Optional[Dict] = None) -> str:
        r"""Create a new plan with the given title, steps, and dependencies.

        Args:
            title (str): Title for the plan
            steps (List[str]): List of steps for the plan
            dependencies (Optional[Dict[int, List[int]]]): Dictionary of step dependencies
                e.g., {1: [0]} means step 1 depends on step 0. If None, steps will be sequential.
            step_agents (Optional[Dict]): Dictionary mapping step index to actor_id
                e.g., {"0": "builtin-actor", "1": "actor_code_review"}

        Returns:
            str: Success message with plan details
        """
        logger.info(
            f"create plan, title is {title}, steps is {steps}, dependencies({type(dependencies)}) is {dependencies}")

        if dependencies and isinstance(dependencies, str):
            try:
                dependencies = ast.literal_eval(dependencies)
            except Exception as e:
                logger.error(f"Plan Warning: not literal_eval('{dependencies}') to dict, raise error: {str(e)}",
                             exc_info=True)
                dependencies = None

        # Generate sequential dependencies if None
        if dependencies is None and len(steps) > 1:
            dependencies = {i: [i - 1] for i in range(1, len(steps))}

        self.plan.update(title, steps, dependencies)

        parsed_step_agents = self._parse_step_agents(step_agents)
        if parsed_step_agents is not None:
            self.plan.replace_step_agents_batch(parsed_step_agents)
            logger.info(f"Step agents assigned: {parsed_step_agents}")

        result = f"Plan created successfully\n\n{self.plan.format()}"
        plan_report_event_manager.publish("plan_created", self.plan)
        logger.info(result)
        return result

    def update_plan(self, title: Optional[str] = None, steps: Optional[List[str]] = None,
                    dependencies: Optional[Dict[int, List[int]]] = None,
                    step_agents: Optional[Dict] = None) -> str:
        r"""Update the existing plan with new title, steps, or dependencies while preserving completed steps.

        Args:
            title (Optional[str]): New title for the plan
            steps (Optional[List[str]]): New list of steps for the plan
            dependencies (Optional[Dict[int, List[int]]]): New dependencies between steps
            step_agents (Optional[Dict]): Dictionary mapping step index to actor_id

        Returns:
            str: Success message with updated plan details
        """
        if self.plan is None:
            return "No plan exists. Create a plan with the 'create' command."

        logger.info(
            f"update plan, title is {title}, steps is {steps}, dependencies({type(dependencies)}) is {dependencies}")

        if dependencies and isinstance(dependencies, str):
            try:
                dependencies = ast.literal_eval(dependencies)
            except Exception as e:
                logger.error(f"Plan Warning: not literal_eval('{dependencies}') to dict, raise error: {str(e)}",
                             exc_info=True)
                dependencies = None

        self.plan.update(title, steps, dependencies)

        parsed_step_agents = self._parse_step_agents(step_agents)
        if parsed_step_agents is not None:
            self.plan.replace_step_agents_batch(parsed_step_agents)
            logger.info(f"Step agents updated: {parsed_step_agents}")

        result = f"Plan updated successfully\n\n{self.plan.format()}"
        plan_report_event_manager.publish("plan_updated", self.plan)
        logger.info(f"update result is {result}")
        return result
