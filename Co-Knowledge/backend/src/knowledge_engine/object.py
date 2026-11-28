"""知识对象的公共形状。

一个知识对象就是「一段可被检索的、指向某个领域对象的文本」：

* ``object_type`` 领域自定义（``TABLE`` / ``COLUMN`` / ``NODE`` / ``FIELD`` …），
  引擎不解释它，只用它做过滤与展示；
* ``object_key`` 领域对象的稳定标识（UUID 或路径），同一版本内唯一；
* ``title`` / ``content`` 参与词法与向量检索；
* ``metadata`` 放领域专属信息，引擎不解析。

领域表（``t2s_knowledge``、未来的 ``graph_*`` / ``api_*``）仍然是权威存储；
这个类只描述「投影出来给检索用的那一份」。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class KnowledgeObject:
    object_type: str
    object_key: str
    title: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.object_type, self.object_key)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode('utf-8')).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def group_by_type(objects: Iterable[KnowledgeObject]
                  ) -> dict[str, list[KnowledgeObject]]:
    grouped: dict[str, list[KnowledgeObject]] = {}
    for item in objects:
        grouped.setdefault(item.object_type, []).append(item)
    return grouped
