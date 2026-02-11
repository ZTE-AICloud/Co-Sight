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
#    License for the specific language governing limitations under the License.

"""意图分类器：根据步骤描述与各 actor 描述选出执行该步骤的 agent_id。"""

import json
from math import log
from typing import Optional

from app.cosight.agent.actor.prompt.intent_prompt import (
    intent_classifier_system_prompt,
    intent_classifier_user_prompt,
)
from app.cosight.agent.actor.registry import (
    get_registered_actors,
    get_actor_class,
    get_default_agent_id,
)
from app.cosight.llm.chat_llm import ChatLLM
from app.common.logger_util import logger


def _parse_agent_id(raw: Optional[str]) -> Optional[str]:
    """
    从 LLM 返回文本解析出 agent_id。
    支持：纯 agent_id、JSON {"agent_id": "xxx"}、带前后空白的 id。
    """
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    # 尝试 JSON
    if text.startswith("{"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and "agent_id" in obj:
                return str(obj["agent_id"]).strip()
        except (json.JSONDecodeError, TypeError):
            pass
    # 取第一行或第一个“词”（避免模型多输出了解释）
    first_line = text.split("\n")[0].strip()
    first_word = first_line.split()[0].strip() if first_line else ""
    candidate = first_word or first_line
    if candidate:
        return candidate
    return None


class IntentClassifier:
    """根据用户问题、计划标题与当前步骤描述，调用 LLM 选出执行该步骤的 agent_id。"""

    def __init__(self, llm: ChatLLM):
        self.llm = llm

    def classify(
        self,
        question: str,
        step_text: str,
        plan_title: str = "",
        openclaw_available: bool = True,
    ) -> str:
        """
        返回应执行该步骤的 agent_id。
        若解析失败或返回未知 id，则回退到默认 agent_id（task_actor），并写日志。
        """
        # 先拿到当前默认 agent_id（由注册表/配置决定）
        default_agent_id = get_default_agent_id()
        actors = get_registered_actors(openclaw_available=openclaw_available)
        if not actors:
            logger.warning("No registered actors for intent classification, using default.")
            return default_agent_id

        system = intent_classifier_system_prompt(default_agent_id=default_agent_id)
        user = intent_classifier_user_prompt(
            question=question or "",
            step_text=step_text or "",
            plan_title=plan_title or "",
            actors=actors,
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        try:
            logger.info(f"IntentClassifier messages: {messages}")
            raw = self.llm.chat_to_llm(messages)
            logger.info(f"IntentClassifier raw: {raw}")
            agent_id = _parse_agent_id(raw)
            if agent_id and get_actor_class(agent_id) is not None:
                logger.info(f"IntentClassifier selected agent_id={agent_id} for step.")
                return agent_id
            logger.warning(
                f"IntentClassifier got invalid or unknown agent_id: {raw!r}, falling back to default {default_agent_id!r}."
            )
        except Exception as e:
            logger.warning(
                f"IntentClassifier LLM call failed: {e}, falling back to default {default_agent_id!r}."
            )

        return default_agent_id
