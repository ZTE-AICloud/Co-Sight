"""可访问知识库的解析（只读）。

v1 只开放**文档知识库**（``kb_kbase.category = 1``）：图谱库（``category = 10``）
用的是 ``graph_<id>`` 表与另一套检索路径，不在本次 Agent 能力范围内。
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from knowledge_base.service import kbase_service as kbase_store

from agent import config
from agent.auth import AgentPrincipal
from agent.errors import (
    invalid_request,
    knowledge_base_forbidden,
    knowledge_base_not_found,
    no_accessible_knowledge_bases,
)

DOCUMENT_CATEGORY = 1


def _category(row: dict) -> int:
    try:
        return int(row.get('category'))
    except (TypeError, ValueError):
        return -1


def _is_document(row: dict) -> bool:
    return _category(row) == DOCUMENT_CATEGORY


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        # timestamptz → 保持旧契约的无偏移本地时间串（``YYYY-MM-DDTHH:MM:SS``）
        if value.tzinfo is not None:
            value = value.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
        return value.isoformat(timespec='seconds')
    return str(value)


def all_active_rows() -> list[dict]:
    """全部知识库（含图谱库，用于区分 403/404）。"""
    return kbase_store.list_all_kbases()


def to_info(row: dict) -> dict:
    """对外只暴露安全字段，不带内部表名 / ES 索引名 / props。"""
    return {
        'id': row.get('kbase_id') or '',
        'name': row.get('name') or '',
        'description': row.get('description'),
        'type': row.get('type'),
        'embedding_model': row.get('embedding_model'),
        'status': None if row.get('status') is None else str(row.get('status')),
        'created_date': _iso(row.get('created_at')),
    }


def list_knowledge_bases(principal: AgentPrincipal) -> list[dict]:
    rows = [row for row in all_active_rows()
            if _is_document(row) and principal.can_access(row.get('kbase_id') or '')]
    return [to_info(row) for row in rows]


def resolve_kbases(principal: AgentPrincipal,
                   requested_ids: Optional[Iterable[str]]) -> tuple[list[dict], bool]:
    """返回 ``(rows, explicit)``。

    * 显式 ID：不存在 / 图谱库 → 404；不在 Key 白名单 → 403；任一失败即 fail-fast。
    * 隐式全部：只取可访问的文档库；为空 → 400；超过 ``RKB_AGENT_MAX_KBS`` → 400
      （防止一个 Key 无意中扫全站）。
    """
    rows = all_active_rows()
    by_id = {row.get('kbase_id'): row for row in rows}

    requested = [item for item in (requested_ids or []) if item]
    if requested:
        resolved: list[dict] = []
        seen: set[str] = set()
        for kb_id in requested:
            if kb_id in seen:
                continue
            seen.add(kb_id)
            row = by_id.get(kb_id)
            if row is None or not _is_document(row):
                raise knowledge_base_not_found(kb_id)
            if not principal.can_access(kb_id):
                raise knowledge_base_forbidden(kb_id)
            resolved.append(row)
        return resolved, True

    visible = [row for row in rows
               if _is_document(row) and principal.can_access(row.get('kbase_id') or '')]
    if not visible:
        raise no_accessible_knowledge_bases()
    limit = config.max_kbs()
    if len(visible) > limit:
        raise invalid_request(
            f'too many accessible knowledge bases ({len(visible)} > {limit}); '
            'pass knowledge_base_ids explicitly')
    return visible, False


def name_map(rows: Iterable[dict]) -> dict[str, str]:
    return {row.get('kbase_id'): row.get('name') or '' for row in rows}
