"""模型注册表的存储协议 + 内存实现（单测用）。

与 ``workflow/repository.py`` 同一套路：生产用 PG 实现（``repository_pg.py``），
单测注内存实现 —— 于是**端点测试不需要数据库、不需要网络**（见
``tests/test_kb_api_llm_list.py`` 的裸 TestClient 写法）。

存储层红线（与 flow_api / kb_api 一致）：**不吞异常**。重复键抛
:class:`~knowledge_base.errors.KbStoreError`（``kind='duplicate'``），
其余数据库错误抛 ``kind='db_error'``，由路由的异常阶梯翻成 0005/0001。
"""

from __future__ import annotations

from typing import Optional, Protocol

from model.models import ModelRecord


class ModelStore(Protocol):
    """注册表读写。实现方：:class:`InMemoryModelStore` / ``store_pg.PgModelStore``。"""

    def list_records(self, kind: Optional[str] = None) -> list[ModelRecord]:
        """全部记录（可按 kind 过滤）。顺序由实现定：PG 按 kind + 注册名，内存同。"""
        ...

    def get_record(self, model_id: str) -> Optional[ModelRecord]:
        ...

    def find_by_name(self, kind: str, model_name: str) -> Optional[ModelRecord]:
        ...

    def insert(self, record: ModelRecord) -> None:
        ...

    def update(self, record: ModelRecord) -> None:
        ...

    def delete(self, model_id: str) -> None:
        ...

    def clear_default(self, kind: str, keep_id: Optional[str] = None) -> None:
        """把该 kind 下（除 ``keep_id`` 外）的 ``is_default`` 全部清掉。

        与 ``insert`` / ``update`` 必须在**同一个事务**里 —— 否则并发两次「设为默认」
        会留下两个默认（解析层遇到两个默认时的行为就变成未定义）。
        """
        ...


class InMemoryModelStore:
    """内存实现（单测用）。**不保证线程安全** —— 单测是单线程的。"""

    def __init__(self, records: Optional[list[ModelRecord]] = None):
        self._records: list[ModelRecord] = list(records or [])

    def list_records(self, kind: Optional[str] = None) -> list[ModelRecord]:
        rows = [r for r in self._records if kind is None or r.model_kind == kind]
        # ⚠️ 排序必须与 PgModelStore 的 ORDER BY 逐项一致（kind, is_default DESC, model_name）：
        # 单测跑的是这一个实现，生产跑的是那一个，排序分叉 = 单测替身替你掩盖了线上行为。
        return sorted(rows, key=lambda r: (r.model_kind, not r.is_default, r.model_name))

    def get_record(self, model_id: str) -> Optional[ModelRecord]:
        for record in self._records:
            if record.model_id == model_id:
                return record
        return None

    def find_by_name(self, kind: str, model_name: str) -> Optional[ModelRecord]:
        for record in self._records:
            if record.model_kind == kind and record.model_name == model_name:
                return record
        return None

    def insert(self, record: ModelRecord) -> None:
        from shared.errors.api import KbStoreError

        if any(r.model_id == record.model_id for r in self._records):
            raise KbStoreError(KbStoreError.DUPLICATE, 'duplicate model_id')
        if self.find_by_name(record.model_kind, record.model_name):
            raise KbStoreError(KbStoreError.DUPLICATE, 'duplicate model_name')
        if record.is_default:
            self.clear_default(record.model_kind, keep_id=record.model_id)
        self._records.append(record)

    def update(self, record: ModelRecord) -> None:
        from shared.errors.api import KbStoreError

        for index, existing in enumerate(self._records):
            if existing.model_id != record.model_id:
                continue
            other = self.find_by_name(record.model_kind, record.model_name)
            if other is not None and other.model_id != record.model_id:
                raise KbStoreError(KbStoreError.DUPLICATE, 'duplicate model_name')
            if record.is_default:
                self.clear_default(record.model_kind, keep_id=record.model_id)
            self._records[index] = record
            return
        raise KbStoreError(KbStoreError.NOT_FOUND, 'model not found')

    def delete(self, model_id: str) -> None:
        from shared.errors.api import KbStoreError

        for index, existing in enumerate(self._records):
            if existing.model_id == model_id:
                del self._records[index]
                return
        raise KbStoreError(KbStoreError.NOT_FOUND, 'model not found')

    def clear_default(self, kind: str, keep_id: Optional[str] = None) -> None:
        for index, existing in enumerate(self._records):
            if existing.model_kind != kind or not existing.is_default:
                continue
            if keep_id is not None and existing.model_id == keep_id:
                continue
            self._records[index] = existing.with_changes(is_default=False)
