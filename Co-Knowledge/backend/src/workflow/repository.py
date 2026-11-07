"""存储接口与内存实现。

``FlowStore`` 是 service 与持久化之间**唯一**的边界 —— 换存储（内存 ↔ PG ↔ 将来别的）
只动这一层。两个实现：

* :class:`InMemoryFlowStore` —— 测试与本地联调用（不碰 DB，进程内）。
* :class:`workflow.repository_pg.PgFlowStore` —— 生产实现，读写 ``flow_*`` 三表。

``create_default_store()`` 默认返回 PG 实现：表还没建时读写会**显式报错**，
不会静默降级成「空画布」（读失败被当成「没有草稿」会让用户以为自己的画布丢了）。
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional, Protocol

from workflow.errors import FlowStoreError
from workflow.models import FlowDraft, FlowPublished, WorkflowRecord

TIMESTAMP_FORMAT = '%Y-%m-%d %H:%M:%S'

#: 全栈统一 CST（与 compose 的 `TZ=Asia/Shanghai`、PostgreSQL 的 timezone 对齐）。
#:
#: 为什么**显式指定**而不是用 `datetime.now()` 跟随容器 TZ：容器 TZ 漏配时
#: 会静默写进错误的时间，事后无从分辨（本表的列是 `timestamp without time zone`，
#: 值本身不带时区信息，写错了看不出来）。宁可在这里写死。
#: tzdata 缺失时回落到固定 +08:00 —— 中国自 1991 年起无夏令时，两者等价。
try:
    from zoneinfo import ZoneInfo

    SERVICE_TIMEZONE = ZoneInfo('Asia/Shanghai')
except Exception:  # pragma: no cover - 仅在基础镜像无 tzdata 时触发
    from datetime import timedelta, timezone

    SERVICE_TIMEZONE = timezone(timedelta(hours=8), 'CST')


def now_timestamp() -> str:
    """当前时间字符串。格式为 ``YYYY-MM-DD HH:MM:SS``，时区固定 CST。"""
    return datetime.now(SERVICE_TIMEZONE).strftime(TIMESTAMP_FORMAT)


class FlowStore(Protocol):
    """存储层接口。所有方法在出错时抛 :class:`FlowStoreError`，不返回 None 兜底。"""

    # ---- 工作流元数据 ----
    def get_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        ...

    def list_workflows(self, name: Optional[str], page: int, size: int,
                       publish_type: Optional[int] = None) -> tuple[list[WorkflowRecord], int]:
        ...

    def list_workflows_by_creator(self, created_by: str) -> list[WorkflowRecord]:
        ...

    def create_workflow_with_draft(self, record: WorkflowRecord, draft: FlowDraft) -> None:
        """建流 + 播种默认画布，同一事务（**没有**「只建流不播种」的入口）。"""
        ...

    def update_workflow(self, workflow_id: str, name: str, template: Optional[str],
                        knowledge_type: Optional[str], description: Optional[str]) -> None:
        ...

    def update_publish_type(self, workflow_id: str, publish_type: int) -> None:
        ...

    def delete_workflow(self, workflow_id: str) -> None:
        ...

    # ---- 画布草稿 ----
    def get_draft(self, workflow_id: str) -> Optional[FlowDraft]:
        ...

    def insert_draft(self, draft: FlowDraft) -> None:
        ...

    def update_draft(self, workflow_id: str, flow_type: str, node_config: list,
                     other_node_config: list) -> None:
        ...

    def update_draft_version(self, workflow_id: str, version: int) -> None:
        ...

    def list_drafts(self, workflow_ids: list[str]) -> list[FlowDraft]:
        ...

    # ---- 发布快照 ----
    def get_latest_published(self, workflow_id: str) -> Optional[FlowPublished]:
        ...

    def get_max_published_version(self, workflow_id: str) -> int:
        ...

    def insert_published(self, published: FlowPublished) -> None:
        ...


class InMemoryFlowStore:
    """进程内实现：测试、本地联调、以及「表还没建」时的显式替代品。

    **不是**生产存储：多实例部署各存各的、重启即丢。生产走 :class:`PgFlowStore`。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._workflows: dict[str, WorkflowRecord] = {}
        self._drafts: dict[str, FlowDraft] = {}
        self._published: dict[str, dict[int, FlowPublished]] = {}

    # ---- 工作流元数据 ----

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        return self._workflows.get(workflow_id)

    def list_workflows(self, name: Optional[str], page: int, size: int,
                       publish_type: Optional[int] = None) -> tuple[list[WorkflowRecord], int]:
        records = list(self._workflows.values())
        if name:
            # 与 PgFlowStore 同口径：名称 / 工作流 ID / 创建人 三选一命中即可。
            needle = name.lower()
            records = [
                record for record in records
                if needle in (record.name or '').lower()
                or needle in (record.workflow_id or '').lower()
                or needle in (record.created_by or '').lower()
            ]
        if publish_type is not None:
            records = [record for record in records if record.publish_type == publish_type]
        # 按最后修改时间倒序；同一时间按 workflow_id 倒序
        records.sort(key=lambda r: (r.updated_at or '', r.workflow_id), reverse=True)
        total = len(records)
        start = (page - 1) * size
        return records[start:start + size], total

    def list_workflows_by_creator(self, created_by: str) -> list[WorkflowRecord]:
        return [record for record in self._workflows.values() if record.created_by == created_by]

    def create_workflow_with_draft(self, record: WorkflowRecord, draft: FlowDraft) -> None:
        """建流 + 播种默认画布，**要么都在、要么都不在**（与 PgFlowStore 同一语义）。

        分成两次写会让「工作流建出来了、画布没播下去」成为一个可能的中间态 ——
        表现出来就是刚建的工作流画布上空无一物，且没有任何错误可查。
        """
        with self._lock:
            if record.workflow_id in self._workflows:
                raise FlowStoreError(FlowStoreError.DUPLICATE, f'workflow {record.workflow_id} already exists')
            if draft.workflow_id in self._drafts:
                raise FlowStoreError(FlowStoreError.DUPLICATE, f'draft of {draft.workflow_id} already exists')
            self._workflows[record.workflow_id] = record
            self._drafts[draft.workflow_id] = draft

    def update_workflow(self, workflow_id: str, name: str, template: Optional[str],
                        knowledge_type: Optional[str], description: Optional[str]) -> None:
        with self._lock:
            existing = self._workflows.get(workflow_id)
            if existing is None:
                raise FlowStoreError(FlowStoreError.NOT_FOUND, f'workflow {workflow_id} does not exist')
            self._workflows[workflow_id] = WorkflowRecord(
                workflow_id=workflow_id,
                name=name,
                template=template,
                knowledge_type=knowledge_type,
                description=description,
                publish_type=existing.publish_type,
                status=existing.status,
                bound_info=existing.bound_info,
                created_by=existing.created_by,
                created_at=existing.created_at,
                updated_at=now_timestamp(),
            )

    def update_publish_type(self, workflow_id: str, publish_type: int) -> None:
        with self._lock:
            existing = self._workflows.get(workflow_id)
            if existing is None:
                raise FlowStoreError(FlowStoreError.NOT_FOUND, f'workflow {workflow_id} does not exist')
            self._workflows[workflow_id] = WorkflowRecord(
                workflow_id=existing.workflow_id,
                name=existing.name,
                template=existing.template,
                knowledge_type=existing.knowledge_type,
                description=existing.description,
                publish_type=publish_type,
                status=existing.status,
                bound_info=existing.bound_info,
                created_by=existing.created_by,
                created_at=existing.created_at,
                updated_at=existing.updated_at,
            )

    def delete_workflow(self, workflow_id: str) -> None:
        """显式按序删三张表（草稿 → 快照 → 元数据），与 PgFlowStore 同一语义。

        不依赖数据库级联：连接池没有声明式外键配套，
        删一半静默成功会留下孤儿数据，所以这里逐层删、失败即抛。
        """
        with self._lock:
            self._drafts.pop(workflow_id, None)
            self._published.pop(workflow_id, None)
            self._workflows.pop(workflow_id, None)

    # ---- 画布草稿 ----

    def get_draft(self, workflow_id: str) -> Optional[FlowDraft]:
        return self._drafts.get(workflow_id)

    def insert_draft(self, draft: FlowDraft) -> None:
        with self._lock:
            if draft.workflow_id in self._drafts:
                raise FlowStoreError(FlowStoreError.DUPLICATE, f'draft of {draft.workflow_id} already exists')
            self._drafts[draft.workflow_id] = draft

    def update_draft(self, workflow_id: str, flow_type: str, node_config: list,
                     other_node_config: list) -> None:
        with self._lock:
            existing = self._drafts.get(workflow_id)
            if existing is None:
                raise FlowStoreError(FlowStoreError.NOT_FOUND, f'draft of {workflow_id} does not exist')
            self._drafts[workflow_id] = FlowDraft(
                workflow_id=workflow_id,
                node_config=node_config,
                other_node_config=other_node_config,
                version=existing.version,  # 保存草稿不推进版本号
                flow_type=flow_type,
                created_by=existing.created_by,
                created_at=existing.created_at,
                updated_at=now_timestamp(),
            )

    def update_draft_version(self, workflow_id: str, version: int) -> None:
        with self._lock:
            existing = self._drafts.get(workflow_id)
            if existing is None:
                raise FlowStoreError(FlowStoreError.NOT_FOUND, f'draft of {workflow_id} does not exist')
            self._drafts[workflow_id] = FlowDraft(
                workflow_id=workflow_id,
                node_config=existing.node_config,
                other_node_config=existing.other_node_config,
                version=version,
                flow_type=existing.flow_type,
                created_by=existing.created_by,
                created_at=existing.created_at,
                updated_at=existing.updated_at,
            )

    def list_drafts(self, workflow_ids: list[str]) -> list[FlowDraft]:
        wanted = set(workflow_ids)
        return [draft for workflow_id, draft in self._drafts.items() if workflow_id in wanted]

    # ---- 发布快照 ----

    def get_latest_published(self, workflow_id: str) -> Optional[FlowPublished]:
        versions = self._published.get(workflow_id)
        if not versions:
            return None
        return versions[max(versions)]

    def get_max_published_version(self, workflow_id: str) -> int:
        versions = self._published.get(workflow_id)
        return max(versions) if versions else 0

    def insert_published(self, published: FlowPublished) -> None:
        with self._lock:
            versions = self._published.setdefault(published.workflow_id, {})
            if published.version in versions:
                raise FlowStoreError(
                    FlowStoreError.DUPLICATE,
                    f'published snapshot of {published.workflow_id} version {published.version} exists',
                )
            versions[published.version] = published


def create_default_store() -> FlowStore:
    """生产默认存储：``PgFlowStore``（``flow_*`` 三表）。

    延迟 import：``store_pg`` 会 import psycopg2（RKB 运行期有、单测环境不需要）。
    表没建时它抛 FlowStoreError（显式报错），**不**静默降级 —— 见模块文档。
    """
    from workflow.repository_pg import PgFlowStore

    return PgFlowStore()
