#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC 知识库本地就绪校验。

无服务器依赖，检索前只做**本地就绪校验**——
  - 无已启用 KB → ok=False，引导先用 cosightbot-soc-kb-build 注册构建；
  - 有启用 KB 但向量库目录缺失/为空 → ok=False，引导重新构建；
  - 全部就绪 → ok=True。

返回契约：{"ok": bool, "reason": str, ...}，
应答/复核技能检索前调用，ok=False 时按 reason 如实反馈用户（不降级裸答）。
"""
from __future__ import annotations

import logging

from common.soc_kb_registry.load import load_registry
from common.soc_kb_registry.paths import SOC_AGENT_ID
from common.soc_vector_paths import (
    SOC_HISTORICAL_VECTOR_NAME,
    SOC_PD_SPEC_VECTOR_NAME,
    kbs_root,
)

logger = logging.getLogger(__name__)


def check_enabled_kbs_ready(agent_id: str = SOC_AGENT_ID) -> dict:
    """本地就绪校验。返回 {"ok", "reason", "ready", "not_ready"}。"""
    try:
        registry = load_registry(agent_id)
    except Exception as e:  # 注册表损坏等异常按未就绪处理，不抛给技能层
        logger.warning("load_registry failed: %s", e)
        return {
            "ok": False,
            "reason": f"知识库注册表读取失败: {e}",
            "ready": [],
            "not_ready": [],
        }

    enabled = [kb for kb in registry.knowledge_bases if getattr(kb, "enabled", False)]
    if not enabled:
        return {
            "ok": False,
            "reason": "没有已启用的知识库——请先用 cosightbot-soc-kb-build "
            "注册本地源目录并完成构建",
            "ready": [],
            "not_ready": [],
        }

    ready: list[str] = []
    not_ready: list[str] = []
    for kb in enabled:
        # 就绪 = 产品规范库或历史应答库至少其一已构建（docs/soc-kb-format.md：
        # 01_Specs_PD / 02_Historical_Responses 至少存在其一即可注册构建）。
        # 只建历史库的 KB 对 soc-respond（纯范式检索）完全可用。
        kb_dir = kbs_root(agent_id) / kb.kb_id
        built = False
        for table in (SOC_PD_SPEC_VECTOR_NAME, SOC_HISTORICAL_VECTOR_NAME):
            lib = kb_dir / table
            try:
                if lib.is_dir() and any(lib.iterdir()):
                    built = True
                    break
            except OSError:
                continue
        (ready if built else not_ready).append(kb.kb_id)

    if not_ready:
        return {
            "ok": False,
            "reason": f"知识库尚未构建: {', '.join(not_ready)}——"
            "请运行 cosightbot-soc-kb-build build 完成构建",
            "ready": ready,
            "not_ready": not_ready,
        }
    return {"ok": True, "reason": "", "ready": ready, "not_ready": []}


__all__ = ["check_enabled_kbs_ready"]
