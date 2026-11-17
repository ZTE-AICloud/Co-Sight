#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""section 级知识索引：LanceDB 骨架/指针表 + 双 f16 向量表 + tantivy FTS。

Schema v3 约定（底座-B1）：
- 文档 key 优先用稳定节点 ID（`F###`，来自 `node_index.json`），无映射时回退
  `rel_path`（测试/旧索引兼容）；
- `section_skeleton`：每个 section 一个 f16 纯结构语义向量（路径词 + 标题链 +
  首句 + 表格签名 + 加粗键，零长正文混入）；
- `nodes_pointer`：每个 350~500 字正文块/表格分片一个 f16 上下文前缀锚定向量
  （`[doc | header_path] + 表头 + chunk 正文`，算完即弃文本），仍不存原文列；
- `doc_skeleton` 预留 `jev_doc_type` / `jev_doc_type_conf` / `jev_is_registry`
  三列（M1 构建期角色先验写入位，默认空值）；
- FTS 建 body（chunk 级）与 skeleton（section 级）两个 contentless 索引，
  skeleton 索引全部 7 个分词检索域；
- 打开旧 v2 目录时，full_build 路径在 `_clear_all()` 中 drop 旧表后按 v3
  Schema 重建，避免在旧表上 add v3 Arrow Table 报 Schema mismatch；
- 本模块不修改 `handler.py` 的原有 overview/status 逻辑，只新增索引产物。
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Optional

import lancedb
import numpy as np
import pyarrow as pa

from common.fts_index import FtsIndex
from common.logging_setup import log_event

from . import doc_role_classifier
from .skeleton_extractor import (
    chunk_sections,
    contextual_chunk_embedding_text,
    extract_skeleton,
    read_lines,
    structure_embedding_text,
)

logger = logging.getLogger("section_index")

DIM = 1024
# v3: 双向量表分离（纯结构向量 + 带前缀 Chunk 向量）+ doc_skeleton JEV 角色列
SCHEMA_VERSION = 3
DEFAULT_ANN_THRESHOLD = int(os.environ.get("COSIGHTBOT_SECTION_ANN_THRESHOLD", "100000"))
DEFAULT_POINTER_ANN_THRESHOLD = int(os.environ.get("COSIGHTBOT_POINTER_ANN_THRESHOLD", "200000"))


class SectionIndexError(RuntimeError):
    """section 索引构建失败（embedding 未配置/维度不符/LanceDB 写入失败等）。"""


def _vector_type() -> pa.DataType:
    return pa.list_(pa.float16(), DIM)


def _table_names(db) -> set[str]:
    tables = db.list_tables()
    names = getattr(tables, "tables", tables)
    return set(names)


def _escape(value: str) -> str:
    return value.replace("'", "''")


class SectionIndex:
    def __init__(self, lan_dir: str | Path, embedding=None, enable_ann: Optional[bool] = None):
        self.lan_dir = Path(lan_dir)
        self.lan_dir.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.lan_dir))
        self.embedding = embedding
        self._ensure_tables()
        self.fts_body = FtsIndex(self.lan_dir / "fts" / "body", "body")
        self.fts_skeleton = FtsIndex(self.lan_dir / "fts" / "skeleton", "skeleton")
        self.enable_ann = (
            enable_ann if enable_ann is not None
            else os.environ.get("COSIGHTBOT_SECTION_ANN", "1") != "0"
        )
        self._body_writer = None
        self._skel_writer = None
        # rel_path -> 稳定节点 ID（F###）；懒加载自 lan_dir/node_index.json。
        self._doc_id_map: Optional[dict[str, str]] = None
        self._docs_since_commit = 0
        self._commit_every = int(os.environ.get("COSIGHTBOT_SECTION_COMMIT_EVERY", "50"))
        self._batch_docs = int(os.environ.get("COSIGHTBOT_SECTION_BATCH_DOCS", "200"))
        self._full_build = False
        self._pending_docs: list[dict] = []
        self._pending_sections: list[dict] = []
        self._pending_vectors: list[np.ndarray] = []
        self._pending_pointers: list[dict] = []
        self._pending_pointer_vectors: list[np.ndarray] = []
        self._pending_body: list[dict] = []
        self._pending_skel: list[dict] = []

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------
    def _doc_schema(self) -> pa.Schema:
        return pa.schema([
            pa.field("doc_key", pa.string()), pa.field("rel_path", pa.string()),
            pa.field("title", pa.string()), pa.field("doc_meta", pa.string()),
            pa.field("skeleton_json", pa.string()), pa.field("fingerprint", pa.string()),
            pa.field("line_count", pa.int64()), pa.field("char_count", pa.int64()),
            pa.field("updated_at", pa.int64()),
            # v3：M1 文档角色先验预留列（T2 写入，默认空值）
            pa.field("jev_doc_type", pa.string()),
            pa.field("jev_doc_type_conf", pa.float32()),
            pa.field("jev_is_registry", pa.bool_()),
        ])

    def _pointer_schema(self) -> pa.Schema:
        # v3：恢复 vector 列（上下文前缀锚定 Chunk 向量），坚持不存 text 原文列。
        return pa.schema([
            pa.field("doc_key", pa.string()), pa.field("section_id", pa.string()),
            pa.field("chunk_id", pa.string()), pa.field("start_line", pa.int64()),
            pa.field("end_line", pa.int64()), pa.field("header_line", pa.int64()),
            pa.field("vector", _vector_type()),
        ])

    def _table_has_field(self, table, field_name: str) -> bool:
        try:
            names = table.to_arrow().schema.names
        except Exception:
            return False
        return field_name in names

    def _ensure_tables(self) -> None:
        names = _table_names(self.db)
        # 旧 v2 表缺 v3 必需列时先记住，full_build 的 _clear_all() 里 drop 后重建
        self._stale_doc_table = False
        self._stale_pointer_table = False
        if "doc_skeleton" in names:
            self._stale_doc_table = not self._table_has_field(
                self.db.open_table("doc_skeleton"), "jev_doc_type"
            )
        if "nodes_pointer" in names:
            self._stale_pointer_table = not self._table_has_field(
                self.db.open_table("nodes_pointer"), "vector"
            )
        if "doc_skeleton" not in names:
            self.db.create_table("doc_skeleton", schema=self._doc_schema())
        if "section_skeleton" not in names:
            self.db.create_table("section_skeleton", schema=pa.schema([
                pa.field("doc_key", pa.string()), pa.field("section_id", pa.string()),
                pa.field("header_path", pa.string()), pa.field("level", pa.int64()),
                pa.field("start_line", pa.int64()), pa.field("end_line", pa.int64()),
                pa.field("char_count", pa.int64()), pa.field("first_sentence", pa.string()),
                pa.field("table_sig", pa.string()), pa.field("bold_keys", pa.string()),
                pa.field("vector", _vector_type()),
            ]))
        if "nodes_pointer" not in names:
            self.db.create_table("nodes_pointer", schema=self._pointer_schema())
        # v2 兼容探测：nodes_pointer 是否真带向量列（路 3 可用性）；V2 库仅跳过
        # 路 3 探针，绝不在此改磁盘（重建仍由 full_build 的 _clear_all 负责）。
        # 必须在 create_table 之后评估，避免把首次建库（新建表必带 v3 向量列）
        # 误判为无向量列；_stale_pointer_table 对新建表恒为 False。
        self.pointer_vector_ready = not self._stale_pointer_table
        self._pointer_skip_logged = False
        if "build_meta" not in names:
            self.db.create_table("build_meta", schema=pa.schema([
                pa.field("key", pa.string()), pa.field("value", pa.string()),
            ]))
        self.doc_table = self.db.open_table("doc_skeleton")
        self.section_table = self.db.open_table("section_skeleton")
        self.pointer_table = self.db.open_table("nodes_pointer")
        self.meta_table = self.db.open_table("build_meta")
        # 只有 finalize 真正建了 IVF-PQ 才能传 nprobes/refine_factor；
        # 小库 flat scan 时传这些参数会报 "nearest neighbor index not found"。
        self.section_ann_ready = False
        self.pointer_ann_ready = False
        self._stale_schema_version = False
        try:
            meta = {
                row["key"]: row["value"]
                for row in self.meta_table.to_arrow().to_pylist()
            }
            version = meta.get("schema_version")
            if version and version != str(SCHEMA_VERSION):
                self._stale_schema_version = True
            self.section_ann_ready = meta.get("section_ann_enabled", meta.get("ann_enabled")) == "1"
            self.pointer_ann_ready = meta.get("pointer_ann_enabled") == "1"
        except Exception:
            pass
        # 兼容旧引用（evaluation/eval_ann.py 等）
        self.ann_ready = self.section_ann_ready

    @property
    def needs_schema_upgrade(self) -> bool:
        """存量旧索引是否缺少 v3 列或存在旧版 Tantivy FTS Schema。"""
        return bool(
            self._stale_doc_table
            or self._stale_pointer_table
            or self._stale_schema_version
            or getattr(self, "fts_body", None) is not None and self.fts_body.schema_mismatch
            or getattr(self, "fts_skeleton", None) is not None and self.fts_skeleton.schema_mismatch
        )

    def _rebuild_stale_tables(self) -> None:
        """把缺 v3 列的旧表 drop 后按 v3 Schema 重建（full_build 专用）。"""
        for name, stale, schema in (
            ("doc_skeleton", self._stale_doc_table, self._doc_schema()),
            ("nodes_pointer", self._stale_pointer_table, self._pointer_schema()),
        ):
            if not stale:
                continue
            try:
                self.db.drop_table(name)
            except Exception as exc:
                log_event(logger, "section_index:upgrade:drop:error", level=logging.WARNING,
                          table=name, error=f"{type(exc).__name__}: {exc}")
            self.db.create_table(name, schema=schema)
            log_event(logger, "section_index:upgrade:recreated", table=name,
                      schema_version=str(SCHEMA_VERSION))
        self._stale_doc_table = False
        self._stale_pointer_table = False
        self._stale_schema_version = False
        self.doc_table = self.db.open_table("doc_skeleton")
        self.pointer_table = self.db.open_table("nodes_pointer")
        # 重建后的 nodes_pointer 必带 v3 向量列，路 3 可用性恢复。
        self.pointer_vector_ready = True
        self._pointer_skip_logged = False

    # ------------------------------------------------------------------
    # stable doc ids
    # ------------------------------------------------------------------
    _LOCAL_NODE_ID_RE = re.compile(r"^F\d{3,}$")

    def refresh_doc_id_map(self) -> dict[str, str]:
        """从 node_index.json 读取 ``rel_path -> F###`` 映射（章节 alias 也包含）。

        overview_builder 先写 node_index.json，SectionIndex 再构建，因此构建期
        能拿到稳定 ID。文件缺失/损坏时返回空表，调用方回退用 rel_path 作 key。
        """
        path = self.lan_dir / "node_index.json"
        mapping: dict[str, str] = {}
        if not path.exists():
            self._doc_id_map = mapping
            return mapping
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log_event(logger, "section_index:node_index:error", level=logging.WARNING,
                      path=str(path), error=f"{type(exc).__name__}: {exc}")
            self._doc_id_map = mapping
            return mapping
        if isinstance(data, dict):
            for node_id, rel_path in data.items():
                if not self._LOCAL_NODE_ID_RE.match(str(node_id)):
                    continue
                if not isinstance(rel_path, str):
                    continue
                norm = "/".join(Path(rel_path).parts)
                mapping.setdefault(norm, str(node_id))
                mapping.setdefault(rel_path, str(node_id))
        self._doc_id_map = mapping
        return mapping

    def _load_doc_id_map(self) -> dict[str, str]:
        if self._doc_id_map is None:
            return self.refresh_doc_id_map()
        return self._doc_id_map

    def _resolve_doc_key(self, rel_path: str, doc_id: Optional[str] = None) -> str:
        """稳定 ID 优先；没有映射时回退 rel_path（兼容测试/旧索引）。"""
        if doc_id:
            return doc_id
        norm = "/".join(Path(rel_path).parts)
        mapping = self._load_doc_id_map()
        return mapping.get(norm) or mapping.get(rel_path) or rel_path

    # ------------------------------------------------------------------
    # writers / commit
    # ------------------------------------------------------------------
    def _ensure_writers(self) -> None:
        if self._body_writer is None:
            self._body_writer = self.fts_body.writer()
        if self._skel_writer is None:
            self._skel_writer = self.fts_skeleton.writer()

    def flush(self) -> None:
        # tantivy-py 的 IndexWriter 在 commit 后即被消费，必须丢弃并在下次写入时重建
        if self._body_writer is not None:
            self._body_writer.commit()
            self._body_writer.wait_merging_threads()
            self._body_writer = None
        if self._skel_writer is not None:
            self._skel_writer.commit()
            self._skel_writer.wait_merging_threads()
            self._skel_writer = None
        self._docs_since_commit = 0

    def _clear_all(self) -> None:
        """全量重建前清空三类表 + FTS；只产生少量版本。

        旧 v2 表缺 v3 必需列时先 drop 后按 v3 Schema 重建（平滑升级）。
        """
        self._rebuild_stale_tables()
        for name, table in (
            ("doc_skeleton", self.doc_table),
            ("section_skeleton", self.section_table),
            ("nodes_pointer", self.pointer_table),
        ):
            try:
                table.delete("true")
            except Exception as exc:
                log_event(logger, "section_index:clear:error", level=logging.WARNING,
                          table=name, error=f"{type(exc).__name__}: {exc}")
        self._ensure_writers()
        self.fts_body.delete_all(writer=self._body_writer, commit=False)
        self.fts_skeleton.delete_all(writer=self._skel_writer, commit=False)
        self.flush()
        log_event(logger, "section_index:clear:done", lan_dir=str(self.lan_dir))

    def _flush_batch(self) -> None:
        """把 pending 的 doc/section/pointer/FTS 行一次性写入，减少 LanceDB 版本数。"""
        if not any((
            self._pending_docs, self._pending_sections, self._pending_pointers,
            self._pending_body, self._pending_skel,
        )):
            return
        docs = len(self._pending_docs)
        sections = len(self._pending_sections)
        pointers = len(self._pending_pointers)
        if self._pending_docs:
            self.doc_table.add(self._pending_docs)
        if self._pending_sections:
            vectors = (
                np.stack(self._pending_vectors)
                if self._pending_vectors
                else np.zeros((sections, DIM), dtype=np.float16)
            )
            self.section_table.add(self._section_arrow(self._pending_sections, vectors))
        if self._pending_pointers:
            self.pointer_table.add(
                self._pointer_arrow(self._pending_pointers, self._pending_pointer_vectors)
            )
        self._ensure_writers()
        if self._pending_body:
            self.fts_body.add_body(self._pending_body, writer=self._body_writer, commit=False)
        if self._pending_skel:
            self.fts_skeleton.add_skeleton(self._pending_skel, writer=self._skel_writer, commit=False)
        self.flush()
        self._pending_docs.clear()
        self._pending_sections.clear()
        self._pending_vectors.clear()
        self._pending_pointers.clear()
        self._pending_pointer_vectors.clear()
        self._pending_body.clear()
        self._pending_skel.clear()
        log_event(logger, "section_index:batch:done", level=logging.DEBUG,
                  docs=docs, sections=sections, pointers=pointers)

    def commit(self) -> None:
        """把当前 pending 批写入 LanceDB + FTS（增量单文档也走这里）。"""
        self._flush_batch()
        self.flush()

    # ------------------------------------------------------------------
    # embedding
    # ------------------------------------------------------------------
    def _get_embedding(self):
        if self.embedding is None:
            from .embedding_model import OnlineBGEEmbedding, embedding_configured

            if not embedding_configured():
                raise SectionIndexError("embedding 未配置（缺少 COSIGHTBOT_EMBEDDING_API_URL）")
            self.embedding = OnlineBGEEmbedding()
        return self.embedding

    def _embed_texts(self, texts: list[str]) -> np.ndarray:
        """通用批量 embedding：输入字符串列表，返回 (N, DIM) float16。"""
        if not texts:
            return np.zeros((0, DIM), dtype=np.float16)
        batch = max(1, int(os.environ.get("COSIGHTBOT_SECTION_EMBED_BATCH", "16")))
        vectors: list[list[float]] = []
        t0 = time.perf_counter()
        for start in range(0, len(texts), batch):
            chunk = texts[start:start + batch]
            try:
                batch_vectors = self._get_embedding()._get_text_embeddings(chunk)
            except Exception as exc:
                raise SectionIndexError(
                    f"embedding failed at batch {start}-{start + len(chunk)}: {type(exc).__name__}: {exc}"
                ) from exc
            if len(batch_vectors) != len(chunk):
                raise SectionIndexError(
                    f"embedding returned {len(batch_vectors)} vectors for {len(chunk)} texts"
                )
            vectors.extend(batch_vectors)
            log_event(
                logger, "section_index:embed:batch", level=logging.DEBUG,
                start=start, count=len(chunk),
                dim=len(batch_vectors[0]) if batch_vectors else 0,
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] != DIM:
            raise SectionIndexError(f"embedding dim mismatch: expected {DIM}, got {arr.shape}")
        log_event(
            logger, "section_index:embed:done", level=logging.DEBUG,
            texts=len(arr), batch=batch,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
        return arr.astype(np.float16)

    def _embed_sections(self, sections: list[dict]) -> np.ndarray:
        """向后兼容薄包装：结构语义向量输入。"""
        return self._embed_texts([structure_embedding_text(s) for s in sections])

    # ------------------------------------------------------------------
    # table payload
    # ------------------------------------------------------------------
    def _section_arrow(self, rows: list[dict], vectors: np.ndarray) -> pa.Table:
        flat = pa.array(vectors.reshape(-1), type=pa.float16())
        vector_col = pa.FixedSizeListArray.from_arrays(flat, DIM)
        return pa.table({
            "doc_key": pa.array([r["doc_key"] for r in rows], type=pa.string()),
            "section_id": pa.array([r["section_id"] for r in rows], type=pa.string()),
            "header_path": pa.array([r["header_path"] for r in rows], type=pa.string()),
            "level": pa.array([r["level"] for r in rows], type=pa.int64()),
            "start_line": pa.array([r["start_line"] for r in rows], type=pa.int64()),
            "end_line": pa.array([r["end_line"] for r in rows], type=pa.int64()),
            "char_count": pa.array([r["char_count"] for r in rows], type=pa.int64()),
            "first_sentence": pa.array([r["first_sentence"] for r in rows], type=pa.string()),
            "table_sig": pa.array([r["table_sig"] for r in rows], type=pa.string()),
            "bold_keys": pa.array([r["bold_keys"] for r in rows], type=pa.string()),
            "vector": vector_col,
        })

    def _doc_payload(self, doc_key: str, rel_path: str, sk: dict, fingerprint: str,
                     role_info: Optional[dict] = None) -> dict:
        # skeleton_json 不存原文 lines，只存结构（行号/标题/首句/表格签名/加粗键）
        sections = [
            {
                "header_path": s["header_path"],
                "level": s["level"],
                "start_line": s["start_line"],
                "end_line": s["end_line"],
                "char_count": s["char_count"],
                "first_sentence": s["first_sentence"],
            }
            for s in sk["sections"]
        ]
        skeleton_json = json.dumps({
            "sections": sections,
            "tables": sk.get("tables", []),
            "bold_keys": sk.get("bold_keys", []),
            "page_anchors": sk.get("page_anchors", []),
        }, ensure_ascii=False)
        role = role_info or {}
        doc_type = str(role.get("jev_doc_type") or "")
        doc_type_conf = float(role.get("jev_doc_type_conf") or 0.0)
        is_registry = bool(role.get("jev_is_registry") or False)
        return {
            "doc_key": doc_key,
            "rel_path": rel_path,
            "title": Path(rel_path).name,
            "doc_meta": json.dumps({
                "line_count": sk["line_count"],
                "char_count": sk["char_count"],
                "sections": len(sections),
                "tables": len(sk.get("tables", [])),
                "bold_keys": len(sk.get("bold_keys", [])),
                # v3：doc_meta JSON 镜像 JEV 角色列，供轻量读取消费
                "jev_doc_type": doc_type,
                "jev_doc_type_conf": doc_type_conf,
                "jev_is_registry": is_registry,
            }, ensure_ascii=False),
            "skeleton_json": skeleton_json,
            "fingerprint": fingerprint,
            "line_count": int(sk["line_count"]),
            "char_count": int(sk["char_count"]),
            "updated_at": int(time.time()),
            "jev_doc_type": doc_type,
            "jev_doc_type_conf": doc_type_conf,
            "jev_is_registry": is_registry,
        }

    def _section_payloads(self, doc_key: str, sk: dict, rel_path: str = "") -> tuple[list[dict], list[str]]:
        rows: list[dict] = []
        texts: list[str] = []
        for i, section in enumerate(sk["sections"], 1):
            tables = [
                t for t in sk.get("tables", [])
                if not (t["end_line"] < section["start_line"] or t["start_line"] > section["end_line"])
            ]
            bold = [
                b for b in sk.get("bold_keys", [])
                if section["start_line"] <= b["line"] <= section["end_line"]
            ]
            rows.append({
                "doc_key": doc_key,
                "section_id": f"{doc_key}#{i}",
                "header_path": section["header_path"],
                "level": int(section["level"]),
                "start_line": int(section["start_line"]),
                "end_line": int(section["end_line"]),
                "char_count": int(section["char_count"]),
                "first_sentence": section["first_sentence"],
                "table_sig": json.dumps(tables, ensure_ascii=False),
                "bold_keys": json.dumps(bold, ensure_ascii=False),
            })
            # v3：纯结构语义向量输入（零长正文混入）
            texts.append(structure_embedding_text(
                section, rel_path=rel_path, tables=tables, bold_keys=bold,
            ))
        return rows, texts

    def _pointer_payloads(self, doc_key: str, chunks: list[dict]) -> list[dict]:
        return [
            {
                "doc_key": doc_key,
                "section_id": f"{doc_key}#{c['section_index'] + 1}",
                "chunk_id": f"{doc_key}#c{i}",
                "start_line": int(c["start_line"]),
                "end_line": int(c["end_line"]),
                "header_line": int(c["header_line"]),
            }
            for i, c in enumerate(chunks)
        ]

    def _pointer_arrow(self, rows: list[dict], vectors: list[np.ndarray]) -> pa.Table:
        """构造带 vector 列的 nodes_pointer Arrow Table（float16[1024]）。"""
        if vectors and len(vectors) != len(rows):
            raise SectionIndexError(
                f"pointer vectors mismatch: {len(vectors)} vectors for {len(rows)} rows"
            )
        if vectors:
            stacked = np.stack([
                v if v.shape == (DIM,) else np.zeros(DIM, dtype=np.float16)
                for v in vectors
            ]).astype(np.float16)
        else:
            stacked = np.zeros((len(rows), DIM), dtype=np.float16)
        flat = pa.array(stacked.reshape(-1), type=pa.float16())
        vector_col = pa.FixedSizeListArray.from_arrays(flat, DIM)
        return pa.table({
            "doc_key": pa.array([r["doc_key"] for r in rows], type=pa.string()),
            "section_id": pa.array([r["section_id"] for r in rows], type=pa.string()),
            "chunk_id": pa.array([r["chunk_id"] for r in rows], type=pa.string()),
            "start_line": pa.array([r["start_line"] for r in rows], type=pa.int64()),
            "end_line": pa.array([r["end_line"] for r in rows], type=pa.int64()),
            "header_line": pa.array([r["header_line"] for r in rows], type=pa.int64()),
            "vector": vector_col,
        })

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------
    def delete_document(self, doc_key: str) -> None:
        """按稳定 ID 或 rel_path 删除文档及其章节/指针/FTS 行。

        doc_key 可能是新格式的 F###，也可能是旧索引里的 rel_path（增量删除
        时 overview 已刷新、node_index 里可能已查不到该文件）。先按
        doc_key/rel_path 反查实际 doc_key 集合，再逐 key 删除。
        """
        self._ensure_writers()
        keys: set[str] = {doc_key}
        try:
            filt = (
                f"doc_key = '{_escape(doc_key)}' "
                f"OR rel_path = '{_escape(doc_key)}'"
            )
            rows = self.doc_table.to_lance().to_table(filter=filt).to_pylist()
            keys.update(str(r["doc_key"]) for r in rows if r.get("doc_key"))
        except Exception as exc:
            log_event(logger, "section_index:delete:lookup:error", level=logging.WARNING,
                      doc_key=doc_key, error=f"{type(exc).__name__}: {exc}")
        for key in keys:
            where = f"doc_key = '{_escape(key)}'"
            for table in (self.doc_table, self.section_table, self.pointer_table):
                try:
                    table.delete(where)
                except Exception as exc:
                    log_event(logger, "section_index:delete:error", level=logging.WARNING,
                              doc_key=key, error=f"{type(exc).__name__}: {exc}")
            self.fts_body.delete_doc(key, writer=self._body_writer, commit=False)
            self.fts_skeleton.delete_doc(key, writer=self._skel_writer, commit=False)
        log_event(logger, "section_index:delete", level=logging.DEBUG,
                  doc_key=doc_key, keys=sorted(keys))

    def _prepare_doc_inputs(self, md_path: Path, rel_path: str, doc_key: str,
                            sk: Optional[dict] = None) -> dict:
        """提取单篇骨架、分块与待向量化文本（磁盘仅读一次，供单篇与批量流水线共用）。"""
        if sk is None:
            sk = extract_skeleton(md_path)
        chunks = chunk_sections(sk, chunk_max=500, chunk_min=350)
        section_rows, section_texts = self._section_payloads(doc_key, sk, rel_path=rel_path)
        chunk_lines = read_lines(md_path)
        chunk_context_texts = [
            contextual_chunk_embedding_text(c, rel_path=rel_path, lines=chunk_lines)
            for c in chunks
        ]
        non_empty_sections = [i for i, text in enumerate(section_texts) if text.strip()]
        non_empty_chunks = [i for i, text in enumerate(chunk_context_texts) if text.strip()]
        merged_texts = [section_texts[i] for i in non_empty_sections]
        merged_texts.extend(chunk_context_texts[i] for i in non_empty_chunks)
        return {
            "sk": sk,
            "chunks": chunks,
            "section_rows": section_rows,
            "non_empty_sections": non_empty_sections,
            "non_empty_chunks": non_empty_chunks,
            "merged_texts": merged_texts,
        }

    def upsert_document(self, md_path: str | Path, rel_path: str, fingerprint: str = "",
                        doc_id: Optional[str] = None,
                        role_info: Optional[dict] = None,
                        *,
                        _prepared: Optional[dict] = None,
                        _embedded: Optional[np.ndarray] = None) -> dict:
        """构建/更新单个主文档；返回计数摘要。失败抛 SectionIndexError。

        doc_id 是稳定节点 ID（F###）；不传时从 node_index.json 自动解析，
        仍未命中则回退 rel_path（测试/旧索引兼容）。
        role_info 是 M1 文档角色先验（T2 写入）：{"jev_doc_type": ...,
        "jev_doc_type_conf": ..., "jev_is_registry": ...}，缺省写默认空值。
        """
        md_path = Path(md_path)
        doc_key = self._resolve_doc_key(rel_path, doc_id)
        t0 = time.perf_counter()
        log_event(logger, "section_index:doc:start", level=logging.DEBUG,
                  doc_key=doc_key, path=str(md_path))
        prep = _prepared or self._prepare_doc_inputs(md_path, rel_path, doc_key)
        sk = prep["sk"]
        # M1（T2）：角色先验三级兜底 —— 调用方显式传入 > 静态规则快筛（零网络，
        # 小模型未配置时也生效）> 弱标题单篇小模型分类（仅 M1 开启时）。标签只写
        # doc_skeleton 标量列与 doc_meta JSON，绝不进入任何语义向量输入文本。
        if role_info is None:
            role_info = doc_role_classifier.classify_by_static_rules(
                rel_path, Path(rel_path).name, sk
            )
            if role_info is None and doc_role_classifier.m1_stage_enabled():
                item = doc_role_classifier.build_weak_item(
                    doc_key, rel_path, Path(rel_path).name, sk, md_path=md_path
                )
                role_info = doc_role_classifier.classify_weak_docs([item]).get(
                    doc_key
                )
        chunks = prep["chunks"]
        section_rows = prep["section_rows"]
        non_empty_sections = prep["non_empty_sections"]
        non_empty_chunks = prep["non_empty_chunks"]
        merged_texts = prep["merged_texts"]
        section_vectors = np.zeros((len(section_rows), DIM), dtype=np.float16)
        chunk_vectors = [np.zeros(DIM, dtype=np.float16) for _ in chunks]
        if merged_texts:
            embedded = _embedded if _embedded is not None else self._embed_texts(merged_texts)
            section_vecs = embedded[:len(non_empty_sections)]
            chunk_vecs = embedded[len(non_empty_sections):]
            for pos, idx in enumerate(non_empty_sections):
                section_vectors[idx] = section_vecs[pos]
            for pos, idx in enumerate(non_empty_chunks):
                chunk_vectors[idx] = chunk_vecs[pos]

        # 增量模式先删旧行；全量模式由 _clear_all 一次性清空，避免每篇文档产生版本
        if not self._full_build:
            self.delete_document(doc_key)

        pointer_rows = self._pointer_payloads(doc_key, chunks)
        self._pending_docs.append(
            self._doc_payload(doc_key, rel_path, sk, fingerprint, role_info=role_info)
        )
        self._pending_sections.extend(section_rows)
        self._pending_vectors.extend(list(section_vectors))
        self._pending_pointers.extend(pointer_rows)
        self._pending_pointer_vectors.extend(chunk_vectors)
        # FTS body（chunk 级）
        self._pending_body.extend([
            {
                "doc_id": doc_key,
                "section_id": p["section_id"],
                "chunk_id": p["chunk_id"],
                "start_line": p["start_line"],
                "end_line": p["end_line"],
                "text": c["text"],
            }
            for p, c in zip(pointer_rows, chunks)
        ])
        # FTS skeleton（section 级）：补齐全部 7 个分词检索域
        self._pending_skel.extend([
            {
                "doc_id": doc_key,
                "section_id": row["section_id"],
                "rel_path": rel_path,
                "title": sk["sections"][i]["title"],
                "header_path": row["header_path"],
                "first_sentence": row["first_sentence"],
                "table_headers": " ".join(
                    " ".join(t.get("columns", []))
                    for t in json.loads(row["table_sig"] or "[]")
                ),
                "first_col_keys": " ".join(
                    " ".join(t.get("first_col_keys", []))
                    for t in json.loads(row["table_sig"] or "[]")
                ),
                "bold_keys": " ".join(
                    b.get("key", "") for b in json.loads(row["bold_keys"] or "[]")
                ),
            }
            for i, row in enumerate(section_rows)
        ])
        self._docs_since_commit += 1
        if len(self._pending_docs) >= self._batch_docs:
            self._flush_batch()
        summary = {
            "doc_key": doc_key,
            "sections": len(section_rows),
            "chunks": len(pointer_rows),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        log_event(logger, "section_index:doc:done", level=logging.DEBUG, **summary)
        return summary

    # ------------------------------------------------------------------
    # build
    # ------------------------------------------------------------------
    def _promoted_chapter_rels(self) -> set[str]:
        """overview 树中出现的章节文件（M-3 主文档为空/仅 TOC 时被提升）。

        overview_builder 只把正常主文档和"提升后的章节"写进树；node_index 里
        同时保留了未提升章节的 alias。这里解析树中的 [F###]，取其中位于
        *_chapters/ 的路径，作为需要进入 section 索引的章节白名单。
        """
        overview = self.lan_dir / "overview.md"
        index_path = self.lan_dir / "node_index.json"
        if not overview.is_file() or not index_path.is_file():
            return set()
        try:
            text = overview.read_text(encoding="utf-8", errors="replace")
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return set()
        marker = "# overview-format:"
        if marker in text:
            text = text.split(marker, 1)[1]
        # 只认树节点行（ID 后跟空白 + 名称），避开 header 里的 `[F001]` 示例。
        ids = set(re.findall(r"\[(F\d{3,})\](?=\s+\S)", text))
        out: set[str] = set()
        for node_id in ids:
            rel = index.get(node_id)
            if not isinstance(rel, str):
                continue
            parts = Path(rel).parts
            if any(p.endswith("_chapters") for p in parts):
                out.add("/".join(parts))
        return out

    def build_from_pre_dir(self, pre_dir: str | Path, rel_paths: Optional[Iterable[str]] = None,
                           fingerprint_map: Optional[dict[str, str]] = None,
                           full_build: bool = False,
                           doc_id_map: Optional[dict[str, str]] = None) -> dict:
        pre_dir = Path(pre_dir)
        if doc_id_map is not None:
            mapping: dict[str, str] = {}
            for rel, node_id in doc_id_map.items():
                if isinstance(rel, str) and isinstance(node_id, str):
                    mapping.setdefault("/".join(Path(rel).parts), node_id)
                    mapping.setdefault(rel, node_id)
            self._doc_id_map = mapping
        else:
            # overview_builder 已先写 node_index.json；构建期读一次即可。
            self.refresh_doc_id_map()
        if not full_build and self.needs_schema_upgrade:
            log_event(
                logger, "section_index:upgrade:force_full_build",
                schema_version=str(SCHEMA_VERSION),
                stale_doc=self._stale_doc_table,
                stale_pointer=self._stale_pointer_table,
                stale_fts=bool(
                    self.fts_body.schema_mismatch or self.fts_skeleton.schema_mismatch
                ),
            )
            full_build = True
        self._full_build = bool(full_build)
        if self._full_build:
            self._clear_all()
        rel_set = set(rel_paths) if (rel_paths is not None and not self._full_build) else None
        promoted_chapters = self._promoted_chapter_rels()
        files = []
        for path in sorted(pre_dir.rglob("*.md")):
            rel = path.relative_to(pre_dir).as_posix()
            parts = Path(rel).parts
            if any(p in {"references", "assets"} for p in parts):
                continue
            if any(p.endswith(("_pages", "_pptx_slides")) for p in parts):
                continue
            if any(p.endswith("_chapters") for p in parts):
                # M-3：只有 overview 树中出现的章节（主文档为空/仅 TOC
                # 或缺主文档时被提升）才进入 section 索引；未提升章节仍只做
                # read-doc 兼容 alias。
                if "/".join(parts) not in promoted_chapters:
                    continue
            if rel_set is not None and rel not in rel_set:
                continue
            files.append((path, rel))

        t0 = time.perf_counter()
        total_sections = 0
        total_chunks = 0
        failed = []
        # 100 篇缓冲窗口流水线：
        # 1) 每篇磁盘仅读一次提取骨架与待向量化文本；
        # 2) M1 弱标题并发分类（后台线程发小模型服务）与跨文档合并 BGE
        #    向量化（主线程发 Embedding 服务）并行重叠执行，避免 51 万篇构建
        #    中两台远端服务串行互等与单篇零碎 HTTP 往返。
        doc_queue: list[tuple[Path, str, str]] = []
        m1_enabled = doc_role_classifier.m1_stage_enabled()

        def _flush_doc_queue() -> tuple[int, int]:
            pending, doc_queue[:] = list(doc_queue), []
            if not pending:
                return 0, 0
            resolved: dict[str, dict] = {}
            m1_items: list[tuple[str, dict]] = []
            prepared_docs: list[tuple[Path, str, str, Optional[str], str, dict]] = []

            for path, rel, fp in pending:
                doc_id = (self._doc_id_map or {}).get(rel)
                doc_key = self._resolve_doc_key(rel, doc_id)
                try:
                    prep = self._prepare_doc_inputs(path, rel, doc_key)
                except Exception as exc:
                    failed.append({"rel": rel, "error": f"{type(exc).__name__}: {exc}"})
                    log_event(logger, "section_index:doc:error", level=logging.ERROR,
                              rel=rel, error=f"{type(exc).__name__}: {exc}",
                              exc_info=True)
                    continue
                sk = prep["sk"]
                role = doc_role_classifier.classify_by_static_rules(
                    rel, Path(rel).name, sk or None
                )
                if role is not None:
                    resolved[doc_key] = role
                elif m1_enabled:
                    m1_items.append((
                        doc_key,
                        doc_role_classifier.build_weak_item(
                            doc_key, rel, Path(rel).name, sk, md_path=path
                        ),
                    ))
                else:
                    resolved[doc_key] = doc_role_classifier.default_role_info("skipped")
                prepared_docs.append((path, rel, fp, doc_id, doc_key, prep))

            def _run_m1() -> dict[str, dict]:
                try:
                    return doc_role_classifier.classify_weak_docs(
                        [item for _, item in m1_items]
                    )
                except Exception as exc:
                    log_event(logger, "m1:llm:degraded", level=logging.WARNING,
                              items=len(m1_items),
                              error=f"{type(exc).__name__}: {exc}")
                    return {}

            doc_embeddings: dict[str, tuple[Optional[np.ndarray], Optional[Exception]]] = {}

            def _embed_prepared() -> None:
                for _path, _rel, _fp, _doc_id, doc_key, prep in prepared_docs:
                    texts = prep["merged_texts"]
                    if not texts:
                        doc_embeddings[doc_key] = (None, None)
                        continue
                    try:
                        doc_embeddings[doc_key] = (self._embed_texts(texts), None)
                    except Exception as exc:
                        doc_embeddings[doc_key] = (None, exc)

            if m1_items:
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="m1-llm") as pool:
                    m1_future = pool.submit(_run_m1)
                    _embed_prepared()
                    resolved.update(m1_future.result())
            else:
                _embed_prepared()

            flushed_sections = 0
            flushed_chunks = 0
            for path, rel, fp, doc_id, doc_key, prep in prepared_docs:
                role_info = resolved.get(doc_key) or doc_role_classifier.default_role_info()
                doc_emb, emb_err = doc_embeddings.get(doc_key, (None, None))
                if emb_err is not None:
                    failed.append({"rel": rel, "error": f"{type(emb_err).__name__}: {emb_err}"})
                    log_event(logger, "section_index:doc:error", level=logging.ERROR,
                              rel=rel, error=f"{type(emb_err).__name__}: {emb_err}")
                    continue
                try:
                    summary = self.upsert_document(
                        path, rel, fp,
                        doc_id=doc_id,
                        role_info=role_info,
                        _prepared=prep,
                        _embedded=doc_emb,
                    )
                    flushed_sections += summary["sections"]
                    flushed_chunks += summary["chunks"]
                except Exception as exc:
                    failed.append({"rel": rel, "error": f"{type(exc).__name__}: {exc}"})
                    log_event(logger, "section_index:doc:error", level=logging.ERROR,
                              rel=rel, error=f"{type(exc).__name__}: {exc}",
                              exc_info=True)
            return flushed_sections, flushed_chunks

        for idx, (path, rel) in enumerate(files, 1):
            doc_queue.append((path, rel, (fingerprint_map or {}).get(rel, "")))
            if len(doc_queue) >= doc_role_classifier.WEAK_BUFFER_DOCS or idx == len(files):
                q_sections, q_chunks = _flush_doc_queue()
                total_sections += q_sections
                total_chunks += q_chunks
            if idx % 100 == 0 or idx == len(files):
                log_event(
                    logger, "section_index:progress",
                    docs=idx, total=len(files), sections=total_sections,
                    chunks=total_chunks, failed=len(failed),
                    duration_ms=round((time.perf_counter() - t0) * 1000, 1),
                )
        q_sections, q_chunks = _flush_doc_queue()
        total_sections += q_sections
        total_chunks += q_chunks
        self._flush_batch()
        self._full_build = False
        summary = {
            "docs": len(files), "sections": total_sections, "chunks": total_chunks,
            "failed": len(failed), "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        log_event(logger, "section_index:build:done", **summary)
        if failed:
            log_event(logger, "section_index:build:failed", level=logging.WARNING,
                      failed=len(failed), sample=failed[:5])
        return summary

    # ------------------------------------------------------------------
    # finalize / ANN / meta
    # ------------------------------------------------------------------
    def finalize(self) -> dict:
        t0 = time.perf_counter()
        self._flush_batch()
        self.flush()
        for name, table in (
            ("doc_skeleton", self.doc_table),
            ("section_skeleton", self.section_table),
            ("nodes_pointer", self.pointer_table),
        ):
            try:
                # 保留 1 小时内的旧版本，避免并发读者在使用旧 snapshot 时失败
                table.optimize(cleanup_older_than=timedelta(hours=1))
            except Exception as exc:
                log_event(logger, "section_index:optimize:error", level=logging.WARNING,
                          table=name, error=f"{type(exc).__name__}: {exc}")
        rows = self.section_table.count_rows()
        p_rows = self.pointer_table.count_rows()
        section_ann_enabled = self._ensure_ann(
            self.section_table, rows, DEFAULT_ANN_THRESHOLD,
            partitions_cap=256, partitions_floor=1, ready=self.section_ann_ready,
            event="section_index:ann:done",
        )
        pointer_ann_enabled = self._ensure_ann(
            self.pointer_table, p_rows, DEFAULT_POINTER_ANN_THRESHOLD,
            partitions_cap=1024, partitions_floor=64, ready=self.pointer_ann_ready,
            event="section_index:pointer_ann:done",
        )
        self.section_ann_ready = section_ann_enabled
        self.pointer_ann_ready = pointer_ann_enabled
        # 兼容旧引用与 handler.py:528 的 ann_enabled 消费
        self.ann_ready = self.section_ann_ready
        ann_enabled = section_ann_enabled or pointer_ann_enabled
        self._write_meta({
            "schema_version": str(SCHEMA_VERSION),
            "embedding_dim": str(DIM),
            "section_rows": str(rows),
            "doc_rows": str(self.doc_table.count_rows()),
            "pointer_rows": str(p_rows),
            "section_ann_enabled": "1" if section_ann_enabled else "0",
            "pointer_ann_enabled": "1" if pointer_ann_enabled else "0",
            "ann_enabled": "1" if ann_enabled else "0",
            "built_at": str(int(time.time())),
        })
        summary = {
            "docs": self.doc_table.count_rows(),
            "sections": rows,
            "pointers": p_rows,
            "ann_enabled": ann_enabled,
            "section_ann_enabled": section_ann_enabled,
            "pointer_ann_enabled": pointer_ann_enabled,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
        log_event(logger, "section_index:finalize:done", **summary)
        return summary

    def _ensure_ann(self, table, rows: int, threshold: int, *,
                    partitions_cap: int, partitions_floor: int, ready: bool,
                    event: str) -> bool:
        """按行数阈值为单张向量表建 IVF-PQ；已有索引时不重复重建。"""
        if ready:
            return True
        index_exists = False
        try:
            indices = table.list_indices()
            index_exists = any("vector" in str(idx) for idx in indices)
        except Exception:
            index_exists = False
        if index_exists:
            return True
        if not self.enable_ann or rows < threshold:
            return False
        try:
            partitions = min(partitions_cap, max(partitions_floor, int(math.sqrt(rows))))
            at = time.perf_counter()
            table.create_index(
                metric="cosine",
                num_partitions=partitions,
                num_sub_vectors=64,
                vector_column_name="vector",
                index_type="IVF_PQ",
            )
            log_event(
                logger, event, rows=rows, partitions=partitions, sub_vectors=64,
                duration_ms=round((time.perf_counter() - at) * 1000, 1),
            )
            return True
        except Exception as exc:
            log_event(logger, event.replace(":done", ":error"), level=logging.ERROR,
                      rows=rows, error=f"{type(exc).__name__}: {exc}", exc_info=True)
            return False

    def _write_meta(self, values: dict[str, str]) -> None:
        try:
            existing = {row["key"]: row for row in self.meta_table.to_arrow().to_pylist()}
            for key, value in values.items():
                if key in existing:
                    self.meta_table.delete(f"key = '{_escape(key)}'")
                self.meta_table.add([{"key": key, "value": value}])
        except Exception as exc:
            log_event(logger, "section_index:meta:error", level=logging.WARNING,
                      error=f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # read (供动态 resolver 使用)
    # ------------------------------------------------------------------
    def search_sections(self, query_vector: list[float] | np.ndarray, top_k: int = 50,
                        nprobes: int = 50, refine_factor: int = 10,
                        bypass_index: bool = False) -> list[dict]:
        q = np.asarray(query_vector, dtype=np.float32).tolist()
        builder = self.section_table.search(q).metric("cosine").limit(top_k)
        if bypass_index:
            # 评测/排障用：强制 flat scan，避免 LanceDB 自动选择向量索引。
            builder = builder.bypass_vector_index()
        elif self.section_ann_ready:
            builder = builder.nprobes(nprobes).refine_factor(refine_factor)
        rows = builder.to_list()
        log_event(logger, "section_index:search", level=logging.DEBUG,
                  top_k=top_k, nprobes=nprobes, refine=refine_factor, hits=len(rows))
        return rows

    def search_pointers(self, query_vector: list[float] | np.ndarray, top_k: int = 800,
                        nprobes: int = 96, refine_factor: int = 20,
                        bypass_index: bool = False) -> list[dict]:
        """路 3 正文语义探针：按 Chunk 向量召回精确行号指针（零原文副本）。

        v2 兼容：nodes_pointer 无向量列时返回空列表（路 3 优雅跳过），只在
        实例生命周期内记一条 WARNING，绝不让四路并发探针抛错。
        """
        if not getattr(self, "pointer_vector_ready", True):
            if not getattr(self, "_pointer_skip_logged", True):
                self._pointer_skip_logged = True
                log_event(
                    logger, "section_index:pointer:legacy_skip", level=logging.WARNING,
                    reason="nodes_pointer has no vector column (schema v2); "
                           "body semantic probe (route 3) disabled",
                )
            return []
        q = np.asarray(query_vector, dtype=np.float32).tolist()
        builder = self.pointer_table.search(q).metric("cosine").limit(top_k)
        if bypass_index:
            builder = builder.bypass_vector_index()
        elif self.pointer_ann_ready:
            builder = builder.nprobes(nprobes).refine_factor(refine_factor)
        rows = builder.to_list()
        log_event(logger, "section_index:search_pointers", level=logging.DEBUG,
                  top_k=top_k, nprobes=nprobes, refine=refine_factor, hits=len(rows))
        return rows

    def stats(self) -> dict:
        return {
            "docs": self.doc_table.count_rows(),
            "sections": self.section_table.count_rows(),
            "pointers": self.pointer_table.count_rows(),
            "body_fts_rows": self.fts_body.count(),
            "skeleton_fts_rows": self.fts_skeleton.count(),
        }
