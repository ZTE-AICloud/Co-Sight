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
import json
import time
import uuid
from typing import Dict, List, Optional, Any
from fastapi import APIRouter
from fastapi.params import Body
from pydantic import BaseModel

from cosight_server.sdk.common.api_result import json_result
from app.common.logger_util import logger

settingsRouter = APIRouter()

# ---------- 配置分组定义 ----------
SETTINGS_GROUPS = [
    {
        "group": "general",
        "label_zh": "通用配置",
        "label_en": "General",
        "icon": "fa-sliders-h",
        "keys": [
            "ENVIRONMENT", "TURBO_MODE", "LLM_TIMEOUT",
        ],
    },
    {
        "group": "default_model",
        "label_zh": "默认模型",
        "label_en": "Default Model",
        "icon": "fa-brain",
        "keys": [
            "API_KEY", "API_BASE_URL", "MODEL_NAME",
            "MAX_TOKENS", "TEMPERATURE", "PROXY", "THINKING_MODE",
        ],
    },
    {
        "group": "plan_model",
        "label_zh": "规划模型",
        "label_en": "Plan Model",
        "icon": "fa-map",
        "keys": [
            "PLAN_API_KEY", "PLAN_API_BASE_URL", "PLAN_MODEL_NAME",
            "PLAN_MAX_TOKENS", "PLAN_TEMPERATURE", "PLAN_PROXY", "PLAN_THINKING_MODE",
        ],
    },
    {
        "group": "act_model",
        "label_zh": "执行模型",
        "label_en": "Act Model",
        "icon": "fa-play",
        "keys": [
            "ACT_API_KEY", "ACT_API_BASE_URL", "ACT_MODEL_NAME",
            "ACT_MAX_TOKENS", "ACT_TEMPERATURE", "ACT_PROXY", "ACT_THINKING_MODE",
        ],
    },
    {
        "group": "tool_model",
        "label_zh": "工具模型",
        "label_en": "Tool Model",
        "icon": "fa-wrench",
        "keys": [
            "TOOL_API_KEY", "TOOL_API_BASE_URL", "TOOL_MODEL_NAME",
            "TOOL_MAX_TOKENS", "TOOL_TEMPERATURE", "TOOL_PROXY", "TOOL_THINKING_MODE",
        ],
    },
    {
        "group": "vision_model",
        "label_zh": "视觉模型",
        "label_en": "Vision Model",
        "icon": "fa-eye",
        "keys": [
            "VISION_API_KEY", "VISION_API_BASE_URL", "VISION_MODEL_NAME",
            "VISION_MAX_TOKENS", "VISION_TEMPERATURE", "VISION_PROXY", "VISION_THINKING_MODE",
        ],
    },
    {
        "group": "credibility_model",
        "label_zh": "可信分析模型",
        "label_en": "Credibility Model",
        "icon": "fa-shield-alt",
        "keys": [
            "CREDIBILITY_API_KEY", "CREDIBILITY_API_BASE_URL", "CREDIBILITY_MODEL_NAME",
            "CREDIBILITY_MAX_TOKENS", "CREDIBILITY_TEMPERATURE", "CREDIBILITY_PROXY", "CREDIBILITY_THINKING_MODE",
        ],
    },
    {
        "group": "browser_model",
        "label_zh": "浏览器模型",
        "label_en": "Browser Model",
        "icon": "fa-globe",
        "keys": [
            "BROWSER_API_KEY", "BROWSER_API_BASE_URL", "BROWSER_MODEL_NAME",
            "BROWSER_MAX_TOKENS", "BROWSER_TEMPERATURE", "BROWSER_PROXY", "BROWSER_THINKING_MODE",
        ],
    },
    {
        "group": "search_engine",
        "label_zh": "搜索引擎",
        "label_en": "Search Engine",
        "icon": "fa-search",
        "keys": [
            "GOOGLE_API_KEY", "SEARCH_ENGINE_ID", "TAVILY_API_KEY",
        ],
    },
    {
        "group": "context",
        "label_zh": "上下文管理",
        "label_en": "Context Management",
        "icon": "fa-layer-group",
        "keys": [
            "ENABLE_CONTEXT_COMPRESSION", "MAX_CONTEXT_TOKENS",
            "COMPRESSION_THRESHOLD", "KEEP_INITIAL_TURNS", "KEEP_RECENT_TURNS",
            "MAX_MESSAGES", "MAX_TOOL_CONTENT_LENGTH",
        ],
    },
    {
        "group": "browser_use",
        "label_zh": "Browser Use 配置",
        "label_en": "Browser Use",
        "icon": "fa-desktop",
        "keys": [
            "HEADLESS", "DISABLE_SECURITY", "FORCE_KEEP_BROWSER_ALIVE",
            "MINIMUM_WAIT_PAGE_LOAD_TIME", "WAIT_FOR_NETWORK_IDLE_PAGE_LOAD_TIME",
            "WAIT_BETWEEN_ACTIONS", "BROWSER_PROXY_URL", "BROWSER_PROXY_USER",
            "BROWSER_PROXY_PASSWORD", "ADD_SCHEMA_TO_SYSTEM_PROMPT",
            "FLASH_MODE", "MAX_TOKENS_PER_STEP",
        ],
    },
    {
        "group": "langfuse",
        "label_zh": "Langfuse 可观测性",
        "label_en": "Langfuse Observability",
        "icon": "fa-chart-line",
        "keys": [
            "LANGFUSE_ENABLED", "LANGFUSE_SECRET_KEY",
            "LANGFUSE_PUBLIC_KEY", "LANGFUSE_BASE_URL",
        ],
    },
    {
        "group": "knowledge_base",
        "label_zh": "知识库 (LightRAG)",
        "label_en": "Knowledge Base (LightRAG)",
        "icon": "fa-book",
        "keys": [
            "LIGHTRAG_BASE_URL", "LIGHTRAG_API_KEY",
            "LIGHTRAG_STORAGE_DIR", "LIGHTRAG_DEFAULT_QUERY_MODE",
        ],
    },
    {
        "group": "embedding_rerank",
        "label_zh": "嵌入与重排序模型",
        "label_en": "Embedding & Rerank Models",
        "icon": "fa-layer-group",
        "keys": [
            "LIGHTRAG_EMBEDDING_API_KEY", "LIGHTRAG_EMBEDDING_API_BASE",
            "LIGHTRAG_EMBEDDING_MODEL", "LIGHTRAG_EMBEDDING_DIM",
            "LIGHTRAG_EMBEDDING_MAX_TOKENS",
            "LIGHTRAG_RERANK_ENABLED", "LIGHTRAG_RERANK_API_KEY",
            "LIGHTRAG_RERANK_API_BASE", "LIGHTRAG_RERANK_MODEL",
            "LIGHTRAG_RERANK_TOP_K",
        ],
    },
]

# 需要脱敏的字段关键字
SENSITIVE_KEYWORDS = ["API_KEY", "SECRET", "PASSWORD", "TOKEN"]

# 所有已知配置 key 的集合（用于快速查找）
ALL_KNOWN_KEYS = set()
for g in SETTINGS_GROUPS:
    ALL_KNOWN_KEYS.update(g["keys"])


def _find_env_path() -> str:
    """定位 .env 文件路径"""
    # 从当前工作目录向上查找 .env
    cwd = os.getcwd()
    env_path = os.path.join(cwd, ".env")
    if os.path.exists(env_path):
        return env_path
    # Fallback: 项目根目录（main.py 所在的上三级）
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    env_path = os.path.join(root, ".env")
    if os.path.exists(env_path):
        return env_path
    return os.path.join(cwd, ".env")  # 默认路径


def _mask_value(key: str, value: str) -> str:
    """对敏感字段值做脱敏"""
    if not value:
        return value
    key_upper = key.upper()
    for kw in SENSITIVE_KEYWORDS:
        if kw in key_upper:
            if len(value) > 8:
                return value[:4] + "****" + value[-4:]
            return "****"
    return value


def _is_masked(value: str) -> bool:
    """判断值是否是脱敏后的值"""
    return "****" in value if value else False


def _parse_env_file(env_path: str) -> Dict[str, str]:
    """解析 .env 文件，返回 key->value 字典（忽略注释和空行）"""
    result = {}
    if not os.path.exists(env_path):
        return result
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key:
                    result[key] = value
    return result


def _write_env_file(env_path: str, updates: Dict[str, str]):
    """将更新写回 .env 文件，保留原有注释和格式"""
    if not os.path.exists(env_path):
        # 如果文件不存在，直接写入
        with open(env_path, "w", encoding="utf-8") as f:
            for k, v in updates.items():
                f.write(f"{k}={v}\n")
        return

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # 追加新增的配置项
    for k, v in updates.items():
        if k not in updated_keys:
            new_lines.append(f"{k}={v}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


@settingsRouter.get("/deep-research/settings")
async def get_settings():
    """获取所有配置项（敏感字段脱敏）"""
    try:
        env_path = _find_env_path()
        env_values = _parse_env_file(env_path)

        groups = []
        for group_def in SETTINGS_GROUPS:
            items = []
            for key in group_def["keys"]:
                raw_value = env_values.get(key, "")
                items.append({
                    "key": key,
                    "value": _mask_value(key, raw_value),
                    "raw_exists": bool(raw_value),
                })
            groups.append({
                "group": group_def["group"],
                "label_zh": group_def["label_zh"],
                "label_en": group_def["label_en"],
                "icon": group_def["icon"],
                "items": items,
            })

        return json_result(0, "success", {"groups": groups})
    except Exception as e:
        logger.error(f"读取设置失败: {str(e)}", exc_info=True)
        return json_result(-1, f"读取设置失败: {str(e)}", None)


class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, str]


@settingsRouter.post("/deep-research/settings")
async def save_settings(body: SettingsUpdateRequest):
    """保存配置项到 .env 文件"""
    try:
        env_path = _find_env_path()
        current_values = _parse_env_file(env_path)

        updates = {}
        for key, new_value in body.settings.items():
            # 跳过脱敏未修改的字段
            if _is_masked(new_value):
                continue
            # 只更新有变化的字段
            if current_values.get(key, "") != new_value:
                updates[key] = new_value

        if updates:
            # 合并当前值和更新值
            merged = {**current_values, **updates}
            _write_env_file(env_path, merged)

            # 同步更新环境变量
            for k, v in updates.items():
                os.environ[k] = v

            logger.info(f"设置已保存，更新了 {len(updates)} 个配置项: {list(updates.keys())}")
            return json_result(0, "保存成功", {"updated_keys": list(updates.keys())})
        else:
            return json_result(0, "无需更新", {"updated_keys": []})
    except Exception as e:
        logger.error(f"保存设置失败: {str(e)}", exc_info=True)
        return json_result(-1, f"保存设置失败: {str(e)}", None)


# ==================== 供应商管理 ====================

def _find_providers_path() -> str:
    """定位 providers.json 文件路径（与 .env 同目录）"""
    env_path = _find_env_path()
    return os.path.join(os.path.dirname(env_path), "providers.json")


def _read_providers() -> List[dict]:
    """读取 providers.json"""
    path = _find_providers_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"读取 providers.json 失败: {e}")
        return []


def _write_providers(providers: List[dict]):
    """写入 providers.json"""
    path = _find_providers_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(providers, f, ensure_ascii=False, indent=2)


@settingsRouter.get("/deep-research/providers")
async def get_providers():
    """获取已配置的模型供应商列表"""
    try:
        providers = _read_providers()
        # 对 API Key 脱敏
        safe_providers = []
        for p in providers:
            sp = dict(p)
            if sp.get("api_key"):
                sp["api_key"] = _mask_value("API_KEY", sp["api_key"])
            safe_providers.append(sp)
        return json_result(0, "success", {"providers": safe_providers})
    except Exception as e:
        logger.error(f"获取供应商列表失败: {e}", exc_info=True)
        return json_result(-1, f"获取供应商列表失败: {str(e)}", None)


class ProvidersUpdateRequest(BaseModel):
    providers: List[Dict[str, Any]]


@settingsRouter.post("/deep-research/providers")
async def save_providers(body: ProvidersUpdateRequest):
    """保存供应商列表（全量覆盖）"""
    try:
        existing = _read_providers()
        existing_map = {p.get("id"): p for p in existing if p.get("id")}

        new_providers = []
        for p in body.providers:
            # 如果没有 id，自动生成
            if not p.get("id"):
                p["id"] = str(uuid.uuid4())[:8]
            # 如果 api_key 是脱敏值，用旧值还原
            if p.get("api_key") and _is_masked(p["api_key"]):
                old = existing_map.get(p["id"])
                if old:
                    p["api_key"] = old.get("api_key", "")
            new_providers.append(p)

        _write_providers(new_providers)
        logger.info(f"供应商列表已保存，共 {len(new_providers)} 个")
        return json_result(0, "保存成功", {"count": len(new_providers)})
    except Exception as e:
        logger.error(f"保存供应商列表失败: {e}", exc_info=True)
        return json_result(-1, f"保存失败: {str(e)}", None)


class ProviderTestRequest(BaseModel):
    provider_id: str
    model: str = "gpt-4o-mini"


@settingsRouter.post("/deep-research/providers/test")
async def test_provider(body: ProviderTestRequest):
    """测试供应商 API 连通性 — 从 providers.json 读取真实 API Key"""
    try:
        import httpx
        from openai import OpenAI

        # 从 providers.json 读取真实（未脱敏）的供应商信息
        providers = _read_providers()
        provider = None
        for p in providers:
            if p.get("id") == body.provider_id:
                provider = p
                break

        if not provider:
            return json_result(-1, f"未找到供应商 (id={body.provider_id})", None)

        api_key = provider["api_key"]
        base_url = provider["base_url"]
        test_model = body.model

        logger.info(f"测试供应商连接: base_url={base_url}, model={test_model}, api_key长度={len(api_key)}")

        # 与 llm.py set_model() 完全一致的 httpx 客户端配置
        http_client = httpx.Client(
            headers={
                'Content-Type': 'application/json',
                'Authorization': api_key
            },
            verify=False,
            trust_env=False,
            timeout=httpx.Timeout(
                connect=15.0,
                read=30.0,
                write=15.0,
                pool=10.0
            )
        )

        client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            http_client=http_client,
        )

        start = time.monotonic()

        import asyncio
        def _do_test():
            return client.chat.completions.create(
                model=test_model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )

        response = await asyncio.to_thread(_do_test)
        latency_ms = int((time.monotonic() - start) * 1000)

        actual_model = response.model or test_model
        logger.info(f"测试供应商成功: model={actual_model}, latency={latency_ms}ms")

        http_client.close()

        return json_result(0, "连接成功", {
            "model": actual_model,
            "latency_ms": latency_ms,
        })
    except Exception as e:
        error_msg = str(e)
        logger.error(f"测试供应商连接失败: {error_msg}")

        if "timeout" in error_msg.lower():
            return json_result(-1, "连接超时（30秒）", None)
        elif "401" in error_msg or "Unauthorized" in error_msg:
            return json_result(-1, "认证失败：API Key 无效或已过期", {"error": error_msg})
        elif "404" in error_msg:
            return json_result(-1, "接口地址错误：未找到 chat/completions 端点", {"error": error_msg})
        else:
            return json_result(-1, f"连接失败: {error_msg[:200]}", {"error": error_msg[:500]})


class ProviderApplyRequest(BaseModel):
    provider_id: str
    model_name: str
    target_group: str  # e.g. "default", "plan", "act", "tool", "vision"


# 模型分组 -> .env key 前缀映射
_GROUP_PREFIX_MAP = {
    "default": "",
    "plan": "PLAN_",
    "act": "ACT_",
    "tool": "TOOL_",
    "vision": "VISION_",
    "credibility": "CREDIBILITY_",
    "browser": "BROWSER_",
}


@settingsRouter.post("/deep-research/providers/apply")
async def apply_provider(body: ProviderApplyRequest):
    """将供应商的配置应用到指定模型分组（写入 .env）"""
    try:
        providers = _read_providers()
        provider = next((p for p in providers if p.get("id") == body.provider_id), None)
        if not provider:
            return json_result(-1, "供应商不存在", None)

        prefix = _GROUP_PREFIX_MAP.get(body.target_group)
        if prefix is None:
            return json_result(-1, f"未知的模型分组: {body.target_group}", None)

        env_path = _find_env_path()
        updates = {
            f"{prefix}API_KEY": provider.get("api_key", ""),
            f"{prefix}API_BASE_URL": provider.get("base_url", ""),
            f"{prefix}MODEL_NAME": body.model_name,
        }

        current_values = _parse_env_file(env_path)
        merged = {**current_values, **updates}
        _write_env_file(env_path, merged)

        # 同步更新环境变量
        for k, v in updates.items():
            os.environ[k] = v

        logger.info(f"已将供应商 {provider.get('name')} 应用到 {body.target_group} 分组")
        return json_result(0, "应用成功", {"updated_keys": list(updates.keys())})
    except Exception as e:
        logger.error(f"应用供应商配置失败: {e}", exc_info=True)
        return json_result(-1, f"应用失败: {str(e)}", None)


# ==================== 智能体管理 ====================

def _find_agents_path() -> str:
    """定位 agents.json 文件路径（与 .env 同目录）"""
    env_path = _find_env_path()
    return os.path.join(os.path.dirname(env_path), "agents.json")


def _read_agents() -> List[dict]:
    """读取 agents.json"""
    path = _find_agents_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"读取 agents.json 失败: {e}")
        return []


def _write_agents(agents: List[dict]):
    """写入 agents.json"""
    path = _find_agents_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(agents, f, ensure_ascii=False, indent=2)


@settingsRouter.get("/deep-research/agents")
async def get_agents():
    """获取所有智能体配置"""
    try:
        from app.cosight.agent.runtime.agent_registry import load_agents

        agents = load_agents()
        return json_result(0, "success", {"agents": agents})
    except Exception as e:
        logger.error(f"读取智能体失败: {e}", exc_info=True)
        return json_result(-1, f"读取失败: {str(e)}", None)


class AgentSaveRequest(BaseModel):
    id: str = ""
    name: str
    description: str = ""
    agent_type: str = "actor"  # "planner" or "actor"
    system_prompt: str = ""
    skills: list = []  # actor 可用 skill 名称列表
    provider_id: str = ""
    model_name: str = ""
    thinking_mode: bool | None = None
    enabled: bool = True
    is_default: bool = False


@settingsRouter.post("/deep-research/agents")
async def save_agent(body: AgentSaveRequest):
    """创建或更新智能体"""
    try:
        from app.cosight.agent.runtime.skill_catalog import validate_skill_names

        agents = _read_agents()
        agent_data = body.model_dump()
        agent_data["name"] = agent_data.get("name", "").strip()
        agent_data["description"] = agent_data.get("description", "").strip()
        agent_data["system_prompt"] = agent_data.get("system_prompt", "").strip()
        agent_data["skills"] = list(dict.fromkeys(agent_data.get("skills") or []))
        if agent_data.get("thinking_mode") is not None:
            agent_data["thinking_mode"] = bool(agent_data["thinking_mode"])
        if not agent_data["name"]:
            return json_result(-1, "name 涓嶈兘涓虹┖", None)

        # 校验 agent_type
        if agent_data.get("agent_type") not in ("planner", "actor"):
            return json_result(-1, "agent_type 必须是 'planner' 或 'actor'", None)

        # planner 不允许自定义 skills
        if agent_data.get("agent_type") == "planner":
            agent_data["skills"] = []
        else:
            if not agent_data["skills"]:
                return json_result(-1, "actor 绫诲瀷蹇呴』鑷冲皯鏈?1 涓?skill", None)
            invalid_skills = validate_skill_names(agent_data["skills"])
            if invalid_skills:
                return json_result(-1, f"鍖呭惈鏃犳晥 skill: {invalid_skills}", None)

        if not agent_data["id"]:
            import uuid
            agent_data["id"] = uuid.uuid4().hex[:8]
        existing = next((i for i, a in enumerate(agents) if a["id"] == agent_data["id"]), None)
        existing_agent = agents[existing] if existing is not None else None
        agent_data["builtin"] = bool(existing_agent.get("builtin")) if existing_agent else False

        # 如果设置为默认，只取消同类型的其他默认
        if agent_data.get("is_default"):
            for a in agents:
                if a.get("agent_type") == agent_data.get("agent_type") and a.get("id") != agent_data["id"]:
                    a["is_default"] = False
        if existing is not None:
            agents[existing] = agent_data
        else:
            agents.append(agent_data)

        _write_agents(agents)
        logger.info(f"保存智能体: {agent_data['name']} (id={agent_data['id']}, type={agent_data.get('agent_type')})")
        return json_result(0, "保存成功", {"agent": agent_data})
    except Exception as e:
        logger.error(f"保存智能体失败: {e}", exc_info=True)
        return json_result(-1, f"保存失败: {str(e)}", None)


@settingsRouter.delete("/deep-research/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """删除智能体"""
    try:
        agents = _read_agents()
        target_agent = next((a for a in agents if a.get("id") == agent_id), None)
        if target_agent and target_agent.get("builtin"):
            return json_result(-1, "内置智能体不允许删除", None)
        new_agents = [a for a in agents if a.get("id") != agent_id]
        if len(new_agents) == len(agents):
            return json_result(-1, "智能体不存在", None)
        _write_agents(new_agents)
        logger.info(f"删除智能体: id={agent_id}")
        return json_result(0, "删除成功", None)
    except Exception as e:
        logger.error(f"删除智能体失败: {e}", exc_info=True)
        return json_result(-1, f"删除失败: {str(e)}", None)


@settingsRouter.get("/deep-research/available-skills")
async def get_available_skills():
    """返回所有 actor 可选的 skill 列表"""
    try:
        from app.cosight.agent.runtime.skill_catalog import get_available_actor_skills
        skills = get_available_actor_skills()
        return json_result(0, "success", {"skills": skills})
    except Exception as e:
        logger.error(f"获取可用技能失败: {e}", exc_info=True)
        return json_result(-1, f"获取失败: {str(e)}", None)


@settingsRouter.get("/deep-research/runtime-agent-defaults")
async def get_runtime_agent_defaults():
    """返回默认的 planner 和 actor 配置，供前端初始化运行时选择器"""
    try:
        from app.cosight.agent.runtime.agent_registry import get_default_planner, get_default_actor, get_planner_agents, get_actor_agents
        return json_result(0, "success", {
            "default_planner": get_default_planner(),
            "default_actor": get_default_actor(),
            "planners": get_planner_agents(),
            "actors": get_actor_agents(),
        })
    except Exception as e:
        logger.error(f"获取运行时默认配置失败: {e}", exc_info=True)
        return json_result(-1, f"获取失败: {str(e)}", None)
