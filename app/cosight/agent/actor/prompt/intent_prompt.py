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
#    License for the specific language governing limitations and permissions
#    under the License.

"""意图分类 prompt：根据步骤描述与各 actor 描述选出唯一 agent_id。"""

from typing import List, Tuple


def intent_classifier_system_prompt(default_agent_id: str) -> str:
    """意图分类系统提示：说明任务与输出格式。

    不再写死具体 agent_id，而是使用传入的默认执行器 ID。
    具体有哪些执行器、各自描述，会在「用户消息」部分给出。
    """
    return (
        "你是一个步骤执行器选择器。根据「用户问题」「计划标题」和「当前步骤描述」，"
        "从给定的执行器列表中选出唯一最适合执行该步骤的执行器。\n\n"
        "规则：\n"
        "1. 严格根据各执行器的职责描述与当前步骤内容的匹配程度进行选择，不要自行臆造新执行器。\n"
        "2. 必须只输出一个执行器 ID，不要输出解释、标点或换行。\n"
        f"3. 如果多个执行器看起来都合适，优先选择系统配置的默认执行器 {default_agent_id}。\n"
        "4. 如果仍然无法判断，也请选择默认执行器，不要返回空值或列表。"
    )


def intent_classifier_user_prompt(
    question: str,
    step_text: str,
    plan_title: str,
    actors: List[Tuple[str, str]],
) -> str:
    """意图分类用户提示：包含各 agent 的 id+description 以及当前 question、step、plan title。"""
    lines = [
        "可选执行器（id 与描述）：",
    ]
    for agent_id, description in actors:
        lines.append(f"- {agent_id}: {description}")
    lines.append("")
    lines.append(f"计划标题: {plan_title or '(无)'}")
    lines.append(f"用户问题: {question}")
    lines.append(f"当前步骤: {step_text}")
    lines.append("")
    lines.append("请只输出上述执行器列表中的一个 id，不要输出其他内容。")
    return "\n".join(lines)
