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

"""Actor 注册表：供意图分类与派发使用。

支持通过环境变量配置哪些 actor 可参与意图选择：

- COSIGHT_ENABLED_ACTORS：逗号分隔的 agent_id 列表，例如 "task_actor,openclaw"。
  未配置时，默认启用所有已注册的 actor。
"""

import os
from typing import List, Tuple, Type, Optional

from app.cosight.agent.actor.task_actor import TaskActorAgent
from app.cosight.agent.actor.netopt_actor import NetoptActorAgent
from app.cosight.agent.actor.openclaw import OpenclawAgent
from app.common.logger_util import logger

# (agent_id, description, actor_class); Openclaw 的 id 用于过滤
_REGISTRY: List[Tuple[str, str, Type]] = [
    (TaskActorAgent.AGENT_ID, TaskActorAgent.DESCRIPTION, TaskActorAgent),
    (NetoptActorAgent.AGENT_ID, NetoptActorAgent.DESCRIPTION, NetoptActorAgent),
    (OpenclawAgent.AGENT_ID, OpenclawAgent.DESCRIPTION, OpenclawAgent),
]

# 默认执行器：也可以将其包含/排除在 COSIGHT_ENABLED_ACTORS 中
_DEFAULT_AGENT_ID = TaskActorAgent.AGENT_ID


def _get_enabled_actor_ids_from_env() -> Optional[set]:
    """从环境变量 COSIGHT_ENABLED_ACTORS 读取允许参与意图分类的 actor 列表。

    返回值：
        - set([...])：启用的 agent_id 集合
        - None：未配置环境变量，表示“全部启用”
    """
    raw = os.environ.get("COSIGHT_ENABLED_ACTORS") or os.environ.get("cosight_enabled_actors")
    if not raw:
        return None
    # 允许形如 "task_actor, openclaw"
    enabled = {item.strip() for item in raw.split(",") if item.strip()}
    return enabled or None


def get_registered_actors(openclaw_available: bool = True) -> List[Tuple[str, str]]:
    """
    返回可供意图分类使用的 (agent_id, description) 列表。
    当 openclaw_available 为 False 时，不包含 OpenclawAgent，避免分类选中不可用 agent。
    """
    enabled_ids = _get_enabled_actor_ids_from_env()

    result = []
    for agent_id, description, cls in _REGISTRY:
        # 若配置了启用列表，则只保留在列表中的 actor
        if enabled_ids is not None and agent_id not in enabled_ids:
            continue

        if agent_id == OpenclawAgent.AGENT_ID and not openclaw_available:
            continue
        result.append((agent_id, description))
    return result


def get_actor_class(agent_id: str) -> Optional[Type]:
    """根据 agent_id 返回对应的 Actor 类，未找到时返回 None。"""
    for aid, _, cls in _REGISTRY:
        if aid == agent_id:
            return cls
    logger.warning(f"Unknown agent_id in registry: {agent_id}")
    return None


def get_default_agent_id() -> str:
    """返回默认 agent_id（用于 fallback）。"""
    return _DEFAULT_AGENT_ID
