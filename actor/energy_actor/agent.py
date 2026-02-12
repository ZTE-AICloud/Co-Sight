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
from actor.energy_actor.prompt import (
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
from actor.energy_actor.tools import build_energy_actor_functions
from app.common.logger_util import logger


class EnergyActorAgent(BaseAgent):
    """
    能效分析执行器：

    - 专注于“能耗 / 能效 / 节能方案”等相关内容；
    - 以“评估能效水平、识别节能空间、对比节能方案效果”为主；
    - 典型能力：
      * 读取能耗报表、节能改造记录、设备运行参数等；
      * 分析不同区域/设备的能效差异与趋势；
      * 结合行业经验与配置策略，给出节能优化建议；
      * 生成面向能效优化的分析报告。
    """

    AGENT_ID = "energy_actor"
    DESCRIPTION = (
        "能效分析执行器。专门用于分析能耗与能效相关数据，评估当前能效水平并识别节能潜力，"
        "帮助形成节能优化方案与评估报告，适用于日常能耗分析、节能项目论证与复盘等场景。"
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
                f"EnergyActorAgent: Successfully retrieved plan for plan_id: {plan_id}"
            )
        except KeyError as e:
            logger.error(
                f"EnergyActorAgent: Plan not found for plan_id: {plan_id}, error: {e}"
            )
            raise ValueError(
                f"Plan with id '{plan_id}' not found in TaskManager. "
                f"Available plans: {list(TaskManager.plans.keys())}"
            )

        all_functions = build_energy_actor_functions(
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
                f"EnergyActorAgent.act: self.plan is None for step_index {step_index}"
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
            logger.error(f"EnergyActorAgent execute error: {str(e)}", exc_info=True)
            self.plan.mark_step(
                step_index, step_status="blocked", step_notes=str(e)
            )
            plan_report_event_manager.publish("plan_process", self.plan)
            return str(e)

