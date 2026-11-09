#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC KB 构建器配置模型。

只支持本地源构建：
  - builtin: 通用 KB，从本地源目录构建（01_Specs_PD/ + 02_Historical_Responses/，
    布局见 docs/soc-kb-format.md）
  - team:    枚举值仅为注册表兼容保留；无远程下载能力，读到 team
             配置直接报错（零兜底）

配置 JSON 示例：
  {
    "kb_id":      "acme_products",
    "kb_type":    "builtin",
    "kb_name":    "Acme 产品知识库",
    "source_dir": "/path/to/my-kb",
    "build_dir":  "<workdir>/data/workspace-soc/builder/builds/acme_products"
  }

构建产物直落本地 data/workspace-soc/kbs/<kb_id>/，无上传步骤。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class KBType(str, Enum):
    """KB 类型枚举（TEAM 仅为注册表兼容保留，不可构建）。"""

    BUILT = "builtin"
    TEAM = "team"


# 已移除的配置节：读到即报错（零兜底，不静默忽略）
_REMOVED_SECTIONS = (
    "upload", "cloud_drive", "tsm_drive",
    "support_download", "tsm_download", "local_source",
)


@dataclass(frozen=True)
class BuildConfig:
    """单个 KB 的完整构建配置（本地源）。"""

    kb_id: str
    kb_type: KBType
    kb_name: str
    source_dir: Path
    build_dir: Path
    # dry-run 模式：跳过向量构建，仅生成最小可用的 status.json，方便开发调试
    dry_run: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BuildConfig":
        if not isinstance(payload, dict):
            raise ValueError("KB 配置必须是字典")

        for removed_key in _REMOVED_SECTIONS:
            if removed_key in payload:
                raise ValueError(
                    f"配置节 {removed_key!r} 已移除（仅支持本地源目录构建），"
                    f"请删除该配置节后重试")

        kb_id = str(payload.get("kb_id", "")).strip()
        if not kb_id:
            raise ValueError("kb_id 不能为空")

        kb_type_str = str(payload.get("kb_type", payload.get("type", "builtin"))).strip()
        if kb_type_str not in {t.value for t in KBType}:
            raise ValueError(f"非法 kb_type: {kb_type_str!r}")
        kb_type = KBType(kb_type_str)
        if kb_type == KBType.TEAM:
            raise ValueError(
                "team 类型 KB 需要远程下载能力，当前不支持——"
                "请改用本地源目录注册 builtin 类型（cosightbot-soc-kb-build add-builtin）")

        kb_name = str(payload.get("kb_name", payload.get("name", kb_id))).strip()

        source_dir_str = str(payload.get("source_dir", "")).strip()
        if not source_dir_str:
            raise ValueError("source_dir 不能为空")
        source_dir = Path(os.path.expanduser(source_dir_str))

        build_dir_str = str(payload.get("build_dir", "")).strip()
        if not build_dir_str:
            # 默认 build_dir = source_dir.parent.parent / "builds" / kb_id
            build_dir = source_dir.parent.parent / "builds" / kb_id
        else:
            build_dir = Path(os.path.expanduser(build_dir_str))

        return cls(
            kb_id=kb_id,
            kb_type=kb_type,
            kb_name=kb_name,
            source_dir=source_dir,
            build_dir=build_dir,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "kb_id": self.kb_id,
            "kb_type": self.kb_type.value,
            "kb_name": self.kb_name,
            "source_dir": str(self.source_dir),
            "build_dir": str(self.build_dir),
        }


# 兼容旧名：BuildConfig 在某些上下文里被叫 BuilderConfig（历史 alias）
BuilderConfig = BuildConfig


def load_config_from_file(config_path: str | Path) -> BuildConfig:
    """从 JSON 文件加载单个 KB 配置。"""
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"KB 配置文件不存在: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"KB 配置文件 {path} 解析失败: {exc}") from exc
    return BuildConfig.from_payload(payload)


__all__ = [
    "BuildConfig",
    "BuilderConfig",
    "KBType",
    "load_config_from_file",
]
