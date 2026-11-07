"""画布「知识库下拉」的数据源接口。

数据源是 RKB 原生实现（``knowledge_base.kbase_options.KbaseTableOptionProvider``，
直接读 ``rag_studio.kb_kbase``）。本模块只保留协议、分组常量与空实现，供测试注入。
"""

from __future__ import annotations

from typing import Optional, Protocol

GROUP_RUNNING = 'running'
GROUP_DEV = 'dev'
GROUPS = (GROUP_RUNNING, GROUP_DEV)


class KbaseOptionProvider(Protocol):
    """知识库下拉的数据源。返回的**已经是分组**。"""

    def list_options(self, embedding_model: Optional[str] = None) -> dict[str, list[dict]]:
        ...


class EmptyKbaseOptionProvider:
    """空实现：显式装配「没有知识库来源」时用（测试、或该部署不接任何库）。"""

    def list_options(self, embedding_model: Optional[str] = None) -> dict[str, list[dict]]:
        return {group: [] for group in GROUPS}
