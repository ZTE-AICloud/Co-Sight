#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JEV 五节点问题集版本与模型感知分侧阈值注册表（对应主方案第 5.2 节）。

职责：
  1. 统一纳管 E1 / E2 / A1 / A2 / A3 五个介入节点的 ``QUESTION_SET_VERSION``，
     杜绝魔数散落在各业务模块中；
  2. 同时维护内网 ``Ntele-decision-V1`` 强二值极化刻度（生产默认）与外网
     ``typesafe/jev-1.14`` 平滑参考刻度（供离线对标与跨模型迁移参考），严禁混用；
  3. 零第三方依赖，可被构建期（watch_dog）与在线检索期（common / dynamic_overview）
     任意模块无环导入。
"""
from __future__ import annotations

import os

__all__ = [
    "QUESTION_SET_VERSIONS",
    "E1_QUESTION_SET_VERSION",
    "E2_QUESTION_SET_VERSION",
    "A1_QUESTION_SET_VERSION",
    "A2_QUESTION_SET_VERSION",
    "A3_QUESTION_SET_VERSION",
    "E1_THRESHOLDS",
    "E2_THRESHOLDS",
    "A1_THRESHOLDS",
    "A2_THRESHOLDS",
    "A3_THRESHOLDS",
    "INTERNAL_THRESHOLDS",
    "EXTERNAL_REFERENCE_THRESHOLDS",
    "is_internal_polarized_model",
    "get_stage_thresholds",
]

# ---------------------------------------------------------------------------
# 各节点冻结问题集版本号
# ---------------------------------------------------------------------------
E1_QUESTION_SET_VERSION = "office-e1-a0-v1"
E2_QUESTION_SET_VERSION = "office-e2-nav-v1"
A1_QUESTION_SET_VERSION = "office-a1-filter-hits-v1"
A2_QUESTION_SET_VERSION = "office-a2-conflict-v1"
A3_QUESTION_SET_VERSION = "office-a3-verify-v1"

QUESTION_SET_VERSIONS: dict[str, str] = {
    "E1": E1_QUESTION_SET_VERSION,
    "E2": E2_QUESTION_SET_VERSION,
    "A1": A1_QUESTION_SET_VERSION,
    "A2": A2_QUESTION_SET_VERSION,
    "A3": A3_QUESTION_SET_VERSION,
}

# ---------------------------------------------------------------------------
# 内网 Ntele-decision-V1 强二值极化初始刻度（主方案第 5.2 节生产生效表）
# 负例集中在 1e-6 ~ 1e-3，正例集中在 0.98 ~ 1.0；中间带一律走保守不伤召回分支。
# ---------------------------------------------------------------------------
E1_THRESHOLDS: dict[str, float] = {
    "choice_full_hit_min": 0.70,    # hit_quality == "FULL_HIT" 最低胜出概率
    "direct_ready_min": 0.95,       # 快速停跳确认门槛（<0.95 一律走二跳，严控假停率 <=3%）
    "clue_covered_min": 0.90,       # 单个关键要素已覆盖门槛
}

E2_THRESHOLDS: dict[str, float] = {
    "promote_target_min": 0.90,     # 池外灰区穿透晋升 Tier1 的 target_match 门槛
    "promote_constraint_min": 1.30,  # 池外灰区穿透晋升 Tier1 的 E[constraint_fit] 门槛（满分 2.0）
    "recommend_target_min": 0.90,   # 进入顶部「★ 优先精读建议」的 target_match 门槛
    "recommend_score_min": 0.72,    # 进入顶部「★ 优先精读建议」的优先分 J(d) 门槛
    "tier1_demote_max": 0.02,       # 原 Tier1 尾部允许顺移至 Tier2 的最大 target_match 概率
    "m1_prior_conf_min": 0.90,      # 复用构建期 M1（小模型）先验免问在线 doc_role 的最低置信度
    "role_choice_min": 0.55,        # 在线 doc_role choice 采信门槛
}

A1_THRESHOLDS: dict[str, float] = {
    "keep_in_scope_min": 0.90,      # >= 0.90 且非草稿 -> confirmed_docs
    "drop_in_scope_max": 0.005,     # < 0.005 -> dropped_noise；[0.005, 0.90) 归入 grey_docs
    "draft_flag_min": 0.92,         # >= 0.92 视为疑似未生效草稿/模板，移入 grey_docs
}

A2_THRESHOLDS: dict[str, float] = {
    "dim_covered_min": 0.90,        # 单个冲突维度显式覆盖确认门槛
    "authority_choice_min": 0.55,   # authority_tier choice 最高项门槛
    "authority_clear_min": 0.85,    # Companion Noul 权威状态明确门槛
    "supersedes_min": 0.92,         # 显式替代/废止旧版声明门槛
    "detail_complete_min": 0.90,    # 具备完整参数表/可执行示例/明确边界门槛
}

A3_THRESHOLDS: dict[str, float] = {
    "source_has_min": 0.95,         # 原文极高置信确有该要求（与 draft_covers_max 联立报漏点）
    "draft_covers_max": 0.02,       # 草稿极高置信未覆盖该要求
    "contradicts_neg_min": 0.95,    # 原文极高置信直接反驳草稿"未找到"否定断言
    "literal_supported_max": 0.02,  # 原文极高置信不支持该字面拼写或数值绑定
}

INTERNAL_THRESHOLDS: dict[str, dict[str, float]] = {
    "E1": E1_THRESHOLDS,
    "E2": E2_THRESHOLDS,
    "A1": A1_THRESHOLDS,
    "A2": A2_THRESHOLDS,
    "A3": A3_THRESHOLDS,
}

# ---------------------------------------------------------------------------
# 外网 typesafe/jev-1.14 平滑概率参考刻度（仅作离线标定对标，办公资料严禁出域）
# ---------------------------------------------------------------------------
EXTERNAL_REFERENCE_THRESHOLDS: dict[str, dict[str, float]] = {
    "E1": {
        "choice_full_hit_min": 0.65,
        "direct_ready_min": 0.80,
        "clue_covered_min": 0.70,
    },
    "E2": {
        "promote_target_min": 0.70,
        "promote_constraint_min": 1.30,
        "recommend_target_min": 0.70,
        "recommend_score_min": 0.65,
        "tier1_demote_max": 0.10,
        "m1_prior_conf_min": 0.75,
        "role_choice_min": 0.50,
    },
    "A1": {
        "keep_in_scope_min": 0.75,
        "drop_in_scope_max": 0.08,
        "draft_flag_min": 0.75,
    },
    "A2": {
        "dim_covered_min": 0.70,
        "authority_choice_min": 0.50,
        "authority_clear_min": 0.70,
        "supersedes_min": 0.75,
        "detail_complete_min": 0.70,
    },
    "A3": {
        "source_has_min": 0.78,
        "draft_covers_max": 0.20,
        "contradicts_neg_min": 0.78,
        "literal_supported_max": 0.20,
    },
}


def _current_configured_model() -> str:
    channel = (os.environ.get("COSIGHTBOT_JEV_CHANNEL") or "").strip().lower()
    if channel == "external":
        return (
            os.environ.get("COSIGHTBOT_JEV_EXTERNAL_MODEL")
            or os.environ.get("JEV_EXTERNAL_MODEL")
            or ""
        ).strip()
    return (os.environ.get("COSIGHTBOT_JEV_INTERNAL_MODEL") or "").strip()


def is_internal_polarized_model(model: str | None = None) -> bool:
    """判定模型是否采用内网 Ntele-decision 二值极化刻度（缺省按内网刻度处理）。"""
    effective = (model if model is not None else _current_configured_model()).strip().lower()
    if not effective:
        return True
    if "typesafe" in effective or effective.startswith("jev-1."):
        return False
    return True


def get_stage_thresholds(stage: str, model: str | None = None) -> dict[str, float]:
    """按阶段名与模型名返回分侧阈值字典副本（防止调用方原地修改全局注册表）。"""
    key = (stage or "").strip().upper()
    registry = (
        INTERNAL_THRESHOLDS
        if is_internal_polarized_model(model)
        else EXTERNAL_REFERENCE_THRESHOLDS
    )
    if key not in registry:
        raise KeyError(f"unknown JEV stage: {stage!r}")
    return dict(registry[key])
