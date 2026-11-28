"""执行期的通用策略：行数、字节、超时。

这些上限与具体方言无关——SQL 算子用它裁剪结果集，未来的 Search / API 算子
同样需要「最多返回多少行、最多多少字节」。所以放在引擎里，领域只提供
「怎么把一行变成 JSON 安全的结构」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

DEFAULT_MAX_ROWS = 1000
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ExecutionPolicy:
    max_rows: int = DEFAULT_MAX_ROWS
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_bytes: int = DEFAULT_MAX_BYTES

    @classmethod
    def from_mapping(cls, value: Optional[dict[str, Any]]) -> 'ExecutionPolicy':
        value = value or {}
        return cls(
            max_rows=int(value.get('max_rows') or DEFAULT_MAX_ROWS),
            timeout_ms=int(value.get('timeout_ms') or DEFAULT_TIMEOUT_MS),
            max_bytes=int(value.get('max_bytes') or DEFAULT_MAX_BYTES),
        )


def encode_rows(raw_rows: list[Any], policy: ExecutionPolicy,
                convert: Optional[Callable[[Any], list[Any]]] = None
                ) -> tuple[list[list[Any]], bool]:
    """把结果行转成 JSON 安全结构，同时守住行数与字节上限。

    单行就超过 ``max_bytes`` 时丢弃该行并置 ``byte_truncated``：宁可返回空结果，
    也不把一个可能上百 MB 的行塞进响应。
    """
    rows: list[list[Any]] = []
    total_bytes = 0
    for raw in raw_rows[:policy.max_rows]:
        converted = convert(raw) if convert else list(raw)
        size = len(json.dumps(converted, ensure_ascii=False, default=str))
        if total_bytes + size > policy.max_bytes:
            return rows, True
        rows.append(converted)
        total_bytes += size
    return rows, False
