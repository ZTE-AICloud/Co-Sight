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

from __future__ import annotations

import os
import re
from typing import Dict

from app.agent_dispatcher.infrastructure.entity.AgentInstance import AgentInstance
from actor.experience_actor.prompt import (
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
from actor.experience_actor.tools import build_experience_actor_functions
from app.common.logger_util import logger


class ExperienceActorAgent(BaseAgent):
    """
    体验分析执行器：

    - 专注于“用户体验 / QoE / 客户投诉”等体验相关内容；
    - 以“从多源数据中提炼体验问题、评价体验质量、输出体验优化建议”为主；
    - 典型能力：
      * 读取客户投诉、体验问卷、探针/测速数据等；
      * 整理用户体验问题的分布、类型与严重度；
      * 结合指标与业务场景，分析体验劣化原因；
      * 生成面向体验优化的分析报告与改进建议。
    """

    AGENT_ID = "experience_actor"
    DESCRIPTION = (
        "体验分析执行器。专门用于处理客户投诉、体验测量、QoE 指标等资料，归纳主要体验问题并分析原因，"
        "帮助产出用户体验评估报告与体验优化建议，适用于客服反馈梳理、体验专项分析等场景。"
    )
    ICON_FILENAME = "report-document-file-svgrepo-com.svg"

    def __init__(
        self,
        agent_instance: AgentInstance,
        llm: ChatLLM,
        vision_llm: ChatLLM,
        tool_llm: ChatLLM,
        plan_id: str,
        functions: Dict | None = None,
        work_space_path: str | None = None,
    ):
        self.work_space_path = (
            work_space_path or os.environ.get("WORKSPACE_PATH") or os.getcwd()
        )
        self.question = None
        self._question_ref = [None]

        try:
            self.plan = TaskManager.get_plan(plan_id)
            logger.info(
                f"ExperienceActorAgent: Successfully retrieved plan for plan_id: {plan_id}"
            )
        except KeyError as e:
            logger.error(
                f"ExperienceActorAgent: Plan not found for plan_id: {plan_id}, error: {e}"
            )
            raise ValueError(
                f"Plan with id '{plan_id}' not found in TaskManager. "
                f"Available plans: {list(TaskManager.plans.keys())}"
            )

        all_functions = build_experience_actor_functions(
            self.plan,
            self.work_space_path,
        )
        if functions:
            all_functions.update(functions)

        super().__init__(agent_instance, llm, all_functions, plan_id=plan_id)

        is_chinese_title = (
            bool(re.search(r"[\u4e00-\u9fff]", self.plan.title))
            if self.plan and getattr(self.plan, "title", None)
            else True
        )
        if is_chinese_title:
            sys_prompt = actor_system_prompt_zh(self.work_space_path)
        else:
            sys_prompt = actor_system_prompt(self.work_space_path)
        self.history.append({"role": "system", "content": sys_prompt})

    @time_record
    def act(self, question: str, step_index: int):
        self.question = question
        self._question_ref[0] = question

        if self.plan is None:
            logger.error(
                f"ExperienceActorAgent.act: self.plan is None for step_index {step_index}"
            )
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
            if (
                self.plan.step_statuses.get(self.plan.steps[step_index], "")
                == "in_progress"
            ):
                self.plan.mark_step(
                    step_index, step_status="completed", step_notes=str(result)
                )
                plan_report_event_manager.publish("plan_process", self.plan)
            return result
        except Exception as e:
            logger.error(f"ExperienceActorAgent execute error: {str(e)}", exc_info=True)
            self.plan.mark_step(
                step_index, step_status="blocked", step_notes=str(e)
            )
            plan_report_event_manager.publish("plan_process", self.plan)
            return str(e)

