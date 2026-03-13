# Copyright 2025 ZTE Corporation. All Rights Reserved.
# Licensed under the Apache License, Version 2.0

"""
Agent Registry — 从 agents.json 读取智能体配置，提供查询接口。
所有运行时代码通过此模块获取 agent 配置，禁止直接读取 agents.json。
"""

import json
import os
from typing import List, Optional, Dict
from app.common.logger_util import logger


def _find_agents_path() -> str:
    """定位 agents.json 文件路径（与 .env 同目录）"""
    from dotenv import find_dotenv
    env_path = find_dotenv(usecwd=True)
    if not env_path:
        env_path = os.path.join(os.getcwd(), ".env")
    return os.path.join(os.path.dirname(env_path), "agents.json")


def load_agents() -> List[dict]:
    """读取 agents.json，返回所有 agent 配置列表（含自动迁移）"""
    path = _find_agents_path()
    if not os.path.exists(path):
        logger.info(f"agents.json not found at {path}, returning empty list")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        agents = data if isinstance(data, list) else []
        # 自动迁移旧数据
        migrated = False
        for a in agents:
            if "agent_type" not in a:
                # 旧数据兼容：builtin planner -> planner，其余 -> actor
                if a.get("builtin") and "规划" in a.get("name", ""):
                    a["agent_type"] = "planner"
                else:
                    a["agent_type"] = "actor"
                migrated = True
            if "skills" not in a:
                a["skills"] = []
                migrated = True
            if "thinking_mode" not in a:
                a["thinking_mode"] = None
                migrated = True
        if migrated:
            _write_agents(agents, path)
            logger.info("agents.json 已自动迁移：补充了 agent_type、skills 和 thinking_mode 字段")
        return agents
    except Exception as e:
        logger.warning(f"读取 agents.json 失败: {e}")
        return []


def _write_agents(agents: List[dict], path: str = None):
    """写入 agents.json"""
    if path is None:
        path = _find_agents_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(agents, f, ensure_ascii=False, indent=2)


def get_planner_agents() -> List[dict]:
    """返回所有 planner 类型且 enabled 的 agent"""
    return [a for a in load_agents() if a.get("agent_type") == "planner" and a.get("enabled", True)]


def get_actor_agents() -> List[dict]:
    """返回所有 actor 类型且 enabled 的 agent"""
    return [a for a in load_agents() if a.get("agent_type") == "actor" and a.get("enabled", True)]


def get_all_enabled_agents() -> List[dict]:
    """返回所有 enabled 的 agent"""
    return [a for a in load_agents() if a.get("enabled", True)]


def get_default_planner() -> Optional[dict]:
    """返回默认 planner（is_default=True 或第一个 planner）"""
    planners = get_planner_agents()
    if not planners:
        return None
    default = next((a for a in planners if a.get("is_default")), None)
    return default or planners[0]


def get_default_actor() -> Optional[dict]:
    """返回默认 actor（is_default=True 或第一个 actor）"""
    actors = get_actor_agents()
    if not actors:
        return None
    default = next((a for a in actors if a.get("is_default")), None)
    return default or actors[0]


def get_agent_by_id(agent_id: str) -> Optional[dict]:
    """根据 id 查找 agent 配置"""
    agents = load_agents()
    return next((a for a in agents if a.get("id") == agent_id), None)


def validate_agent_data(agent_data: dict) -> List[str]:
    """
    校验 agent 数据的合法性，返回错误列表（空列表表示合法）。
    """
    errors = []
    agent_type = agent_data.get("agent_type", "")
    if agent_type not in ("planner", "actor"):
        errors.append("agent_type 必须是 'planner' 或 'actor'")

    if not agent_data.get("name", "").strip():
        errors.append("name 不能为空")

    if agent_type == "planner" and agent_data.get("skills"):
        # planner v1 不允许自定义 skills，自动清空
        agent_data["skills"] = []

    if agent_type == "actor":
        skills = agent_data.get("skills", [])
        if not skills:
            errors.append("actor 类型必须至少有 1 个 skill")

    return errors
