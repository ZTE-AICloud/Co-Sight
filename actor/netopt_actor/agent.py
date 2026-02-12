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
from actor.netopt_actor.prompt import (
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
from actor.netopt_actor.tools import build_netopt_actor_functions
from app.common.logger_util import logger


class NetoptActorAgent(BaseAgent):
    """
    网优资料整理执行器：

    - 专注于「无线网络优化 / 参数配置 / 指标分析」等网优相关内容；
    - 以“整理现有资料、形成结构化结论”为主，而不是执行代码或多模态分析；
    - 典型能力：
      * 读取本地文档/日志/报表；
      * 对网优相关内容进行筛选、归类、对比与总结；
      * 结合搜索结果补充背景与业界常见做法；
      * 生成面向网优场景的 HTML 报告（可选）。
    """

    AGENT_ID = "netopt_actor"
    DESCRIPTION = (
        "网优资料整理执行器。专门用于处理无线网络优化相关资料，例如参数配置说明、KPI 指标分析、"
        "小区/小区簇指标对比、网优方案评估、网优周报/进展报告等，偏重阅读/归纳/写报告，不负责执行代码或多模态分析。"
        "当计划标题或步骤描述中出现“网优”“网络优化”“KPI”“小区参数”“无线指标”等字样时，应优先选择本执行器。"
    )
    ICON_FILENAME = "wifi-wireless-svgrepo-com.svg"

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
                f"NetoptActorAgent: Successfully retrieved plan for plan_id: {plan_id}"
            )
        except KeyError as e:
            logger.error(
                f"NetoptActorAgent: Plan not found for plan_id: {plan_id}, error: {e}"
            )
            raise ValueError(
                f"Plan with id '{plan_id}' not found in TaskManager. "
                f"Available plans: {list(TaskManager.plans.keys())}"
            )

        all_functions = build_netopt_actor_functions(
            self.plan,
            self.work_space_path,
            tool_llm,
            self._question_ref,
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
                f"NetoptActorAgent.act: self.plan is None for step_index {step_index}"
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
            logger.error(f"NetoptActorAgent execute error: {str(e)}", exc_info=True)
            self.plan.mark_step(
                step_index, step_status="blocked", step_notes=str(e)
            )
            plan_report_event_manager.publish("plan_process", self.plan)
            return str(e)

