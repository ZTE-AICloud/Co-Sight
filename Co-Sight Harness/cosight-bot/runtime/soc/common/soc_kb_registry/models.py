#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOC Agent 多知识库注册表数据类。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterator


class KbType(str, Enum):
    """知识库类型枚举。"""

    BUILT = "builtin"  # 通用内置 KB，本地源目录构建
    TEAM = "team"  # 团队 KB（需要远程下载能力，当前不支持，构建层拒绝）
    LOCAL = "local"  # 本地个人 KB（增量索引能力预留，本轮未实现）


@dataclass(frozen=True)
class KnowledgeBase:
    """单个知识库条目。不同类型必填字段不同：

    - builtin: kb_id, type, name, server_path, auto_sync（可选 source_dir）
    - team: 当前不支持（构建层拒绝），仅保留枚举兼容老注册表文件
    - local: kb_id, type, name, local_path, route_key（本轮延后实现）
    """

    kb_id: str
    type: KbType
    name: str
    enabled: bool = True
    server_path: str = ""  # 服务端目录（本地构建不写，恒为空）
    auto_sync: bool = True
    # local 专用（本轮延后实现）
    local_path: str = ""
    route_key: str = ""
    # 子库专用（可选，老注册表文件无此字段，兼容解析）：
    # parent_kb_id = 家族父库；sub_path = L1/L2 产品路径
    parent_kb_id: str = ""
    sub_path: str = ""

    def to_payload(self) -> dict[str, Any]:
        """序列化为 JSON 友好字典；空字段省略。"""
        data: dict[str, Any] = {
            "kb_id": self.kb_id,
            "type": self.type.value,
            "name": self.name,
            "enabled": self.enabled,
            "auto_sync": self.auto_sync,
        }
        if self.server_path:
            data["server_path"] = self.server_path
        if self.local_path:
            data["local_path"] = self.local_path
        if self.route_key:
            data["route_key"] = self.route_key
        if self.parent_kb_id:
            data["parent_kb_id"] = self.parent_kb_id
        if self.sub_path:
            data["sub_path"] = self.sub_path
        return data

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "KnowledgeBase":
        """从 JSON 字典构造；缺失字段使用默认值。

        老注册表文件里的团队库字段（space_id 等）无消费方，直接忽略。
        """
        if not isinstance(payload, dict):
            raise ValueError("知识库条目必须是字典")
        kb_id = payload.get("kb_id")
        type_str = payload.get("type")
        name = payload.get("name")
        if not (isinstance(kb_id, str) and kb_id.strip()):
            raise ValueError("kb_id 必须是非空字符串")
        if not (isinstance(name, str) and name.strip()):
            raise ValueError("name 必须是非空字符串")
        if type_str not in {t.value for t in KbType}:
            raise ValueError(f"非法 kb_type: {type_str!r}")
        return cls(
            kb_id=kb_id,
            type=KbType(type_str),
            name=name,
            enabled=bool(payload.get("enabled", True)),
            server_path=str(payload.get("server_path", "")),
            auto_sync=bool(payload.get("auto_sync", True)),
            local_path=str(payload.get("local_path", "")),
            route_key=str(payload.get("route_key", "")),
            parent_kb_id=str(payload.get("parent_kb_id", "")),
            sub_path=str(payload.get("sub_path", "")),
        )

    def with_(self, **changes: Any) -> "KnowledgeBase":
        """不可变副本（替换部分字段）。"""
        return replace(self, **changes)


@dataclass(frozen=True)
class KnowledgeBaseRegistry:
    """知识库注册表（不可变）。"""

    version: int = 1
    knowledge_bases: tuple[KnowledgeBase, ...] = ()

    def enabled_kbs(self) -> tuple[KnowledgeBase, ...]:
        """只返回 enabled=True 的知识库。"""
        return tuple(kb for kb in self.knowledge_bases if kb.enabled)

    def get(self, kb_id: str) -> KnowledgeBase | None:
        """按 kb_id 查找知识库。"""
        for kb in self.knowledge_bases:
            if kb.kb_id == kb_id:
                return kb
        return None

    def __iter__(self) -> Iterator[KnowledgeBase]:  # type: ignore[override]
        return iter(self.knowledge_bases)

    def __len__(self) -> int:
        return len(self.knowledge_bases)

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "knowledge_bases": [kb.to_payload() for kb in self.knowledge_bases],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "KnowledgeBaseRegistry":
        if not isinstance(payload, dict):
            raise ValueError("注册表必须是字典")
        version = int(payload.get("version", 1))
        # 历史字段 default_kb_id（无消费方，已移除）：老文件里的该键直接忽略
        kb_payloads = payload.get("knowledge_bases", [])
        if not isinstance(kb_payloads, list):
            raise ValueError("knowledge_bases 必须是列表")
        kbs = tuple(KnowledgeBase.from_payload(item) for item in kb_payloads)
        return cls(
            version=version,
            knowledge_bases=kbs,
        )

    def with_added(self, kb: KnowledgeBase) -> "KnowledgeBaseRegistry":
        """返回新注册表，追加一个 KB（同 kb_id 替换）。"""
        new_kbs: list[KnowledgeBase] = []
        replaced = False
        for existing in self.knowledge_bases:
            if existing.kb_id == kb.kb_id:
                new_kbs.append(kb)
                replaced = True
            else:
                new_kbs.append(existing)
        if not replaced:
            new_kbs.append(kb)
        return replace(self, knowledge_bases=tuple(new_kbs))

    def without(self, kb_id: str) -> "KnowledgeBaseRegistry":
        """返回新注册表，移除指定 kb_id（不存在则不变）。"""
        new_kbs = tuple(kb for kb in self.knowledge_bases if kb.kb_id != kb_id)
        return replace(self, knowledge_bases=new_kbs)

    def with_enabled(self, kb_id: str, enabled: bool) -> "KnowledgeBaseRegistry":
        """返回新注册表，切换指定 KB 的启用状态。"""
        new_kbs = tuple(
            kb.with_(enabled=enabled) if kb.kb_id == kb_id else kb
            for kb in self.knowledge_bases
        )
        return replace(self, knowledge_bases=new_kbs)


__all__ = ["KbType", "KnowledgeBase", "KnowledgeBaseRegistry"]