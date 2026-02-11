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

import os
import re
from typing import Dict

from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
from app.cosight.agent.actor.task_actor.prompt import (
    actor_system_prompt,
    actor_system_prompt_zh,
    actor_execute_task_prompt,
    actor_execute_task_prompt_zh,
)
from app.cosight.agent.base.base_agent import BaseAgent
from app.cosight.llm.chat_llm import ChatLLM
from app.cosight.task.plan_report_manager import plan_report_event_manager
from app.cosight.task.task_manager import TaskManager
from app.cosight.task.time_record_util import time_record
from app.cosight.agent.actor.task_actor.tools import build_task_actor_functions
from app.common.logger_util import logger


class TaskActorAgent(BaseAgent):
    """本地执行器：使用代码/文件/搜索/网页/文档/图像等多工具完成步骤。"""

    AGENT_ID = "task_actor"
    DESCRIPTION = (
        "通用报告生成执行器（非网优专用）。主要负责收集已有资料并生成 HTML 报告，"
        "如汇总信息、整合内容、生成可视化报告等，使用 CoSight 内置工具链。"
        "当步骤主要是对本地文件系统做遍历/批量收集等操作时，通常应优先选择 openclaw 执行器，"
        "而本执行器更适合在已有资料基础上做内容整理和报告输出。"
    )
    ICON_FILENAME = "report-document-file-svgrepo-com.svg"

    def __init__(
        self,
        agent_instance: AgentInstance,
        llm: ChatLLM,
        vision_llm: ChatLLM,
        tool_llm: ChatLLM,
        plan_id,
        functions: Dict = None,
        work_space_path: str = None,
    ):
        self.work_space_path = (
            work_space_path if work_space_path else os.environ.get("WORKSPACE_PATH") or os.getcwd()
        )
        self.question = None
        self._question_ref = [None]

        logger.info(f"TaskActorAgent: Looking for plan_id: {plan_id}")
        logger.info(f"TaskActorAgent: Available plans in TaskManager: {list(TaskManager.plans.keys())}")

        try:
            self.plan = TaskManager.get_plan(plan_id)
            logger.info(f"TaskActorAgent: Successfully retrieved plan for plan_id: {plan_id}")
        except KeyError as e:
            logger.error(f"TaskActorAgent: Plan not found for plan_id: {plan_id}, error: {e}")
            raise ValueError(
                f"Plan with id '{plan_id}' not found in TaskManager. "
                f"Available plans: {list(TaskManager.plans.keys())}"
            )

        all_functions = build_task_actor_functions(
            self.plan,
            self.work_space_path,
            tool_llm,
            vision_llm,
            self._question_ref,
        )
        if functions:
            all_functions.update(functions)

        super().__init__(agent_instance, llm, all_functions, plan_id=plan_id)

        is_chinese = (
            bool(re.search(r"[\u4e00-\u9fff]", self.plan.title))
            if self.plan and self.plan.title
            else True
        )
        if is_chinese:
            sys_prompt = actor_system_prompt_zh(self.work_space_path)
        else:
            sys_prompt = actor_system_prompt(self.work_space_path)
        self.history.append({"role": "system", "content": sys_prompt})

    @time_record
    def act(self, question, step_index):
        self.question = question
        self._question_ref[0] = question

        if self.plan is None:
            logger.error(f"TaskActorAgent.act: self.plan is None for step_index {step_index}")
            raise ValueError(f"Plan is None. Cannot execute step {step_index}.")

        self.plan.mark_step(step_index, step_status="in_progress")
        plan_report_event_manager.publish("plan_process", self.plan)

        is_chinese = bool(re.search(r"[\u4e00-\u9fff]", self.question)) if self.question else True
        if is_chinese:
            task_prompt = actor_execute_task_prompt_zh(
                question, step_index, self.plan, self.work_space_path
            )
        else:
            task_prompt = actor_execute_task_prompt(
                question, step_index, self.plan, self.work_space_path
            )

        self.history.append({"role": "user", "content": task_prompt})
        try:
            result = self.execute(self.history, step_index=step_index)
            if self.plan.step_statuses.get(self.plan.steps[step_index], "") == "in_progress":
                self.plan.mark_step(step_index, step_status="completed", step_notes=str(result))
                plan_report_event_manager.publish("plan_process", self.plan)
            return result
        except Exception as e:
            logger.error(f"act agent execute error: {str(e)}", exc_info=True)
            self.plan.mark_step(step_index, step_status="blocked", step_notes=str(e))
            plan_report_event_manager.publish("plan_process", self.plan)
            return str(e)
