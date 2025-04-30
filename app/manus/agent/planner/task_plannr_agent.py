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

import re
from typing import Dict

from app.manus.llm.chat_llm import ChatLLM
from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
from app.manus.agent.base.base_agent import BaseAgent
from app.manus.agent.planner.prompt.planner_prompt import planner_system_prompt, \
    planner_create_plan_prompt, planner_re_plan_prompt, planner_finalize_plan_prompt
from app.manus.task.plan_report_manager import plan_report_event_manager
from app.manus.task.task_manager import TaskManager
from app.manus.tool.plan_toolkit import PlanToolkit
from app.manus.tool.terminate_toolkit import TerminateToolkit


class TaskPlannerAgent(BaseAgent):
    def __init__(self, agent_instance: AgentInstance, llm: ChatLLM, plan_id, functions: Dict = None):
        self.plan = TaskManager.get_plan(plan_id)
        plan_toolkit = PlanToolkit(self.plan)
        terminate_toolkit = TerminateToolkit()
        all_functions = {"create_plan": plan_toolkit.create_plan, "update_plan": plan_toolkit.update_plan,
                         "terminate": terminate_toolkit.terminate}
        if functions:
            all_functions = functions.update(functions)
        super().__init__(agent_instance, llm, all_functions)

    def create_plan(self, question, output_format=""):
        self.history.append({"role": "system", "content": planner_system_prompt()})
        self.history.append({"role": "user", "content": planner_create_plan_prompt(question, output_format)})
        result = self.execute(self.history, max_iteration=1)
        return result

    def re_plan(self, question, output_format=""):
        self.history.append(
            {"role": "user", "content": planner_re_plan_prompt(question, self.plan.format(), output_format)})
        result = self.execute(self.history, max_iteration=1)
        return result

    def finalize_plan(self, question, output_format=""):
        self.history.append(
            {"role": "user", "content": planner_finalize_plan_prompt(question, self.plan.format(), output_format)})
        raw_result = self.execute(self.history, max_iteration=1)
        result = self.extract_pattern(raw_result, "final_answer")
        print(f"raw_resultesult is >>{raw_result}<<, result is {result}")
        self.plan.set_plan_result(result)
        plan_report_event_manager.publish("plan_result", self.plan)
        return result

    def extract_pattern(self, content: str, pattern: str):
        try:
            _pattern = fr"<{pattern}>(.*?)</{pattern}>"
            match = re.search(_pattern, content, re.DOTALL)
            if match:
                text = match.group(1)
                return text.strip()
            else:
                return content
        except Exception as e:
            print(f"Error extracting answer: {e}, current content: {content}")
            return content

