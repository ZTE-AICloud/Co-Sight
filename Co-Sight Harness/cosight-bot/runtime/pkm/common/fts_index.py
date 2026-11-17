#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tantivy contentless FTS 封装。

- body：每个正文 chunk 一条文档；`content` 只索引、不存原文（stored=False）；
- skeleton：每个 section 一条文档；标题/首句/表头只索引、不存原文；
- 查询返回 stored 指针（doc_id / section_id / 行号），由调用方回 pre_dir 读原文；
- 删除按 `doc_id`（raw tokenizer）精确匹配，支持增量重建。

索引/查询分词统一走 common.text_tokenize.tokenize_text()。
"""
from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path
from typing import Iterable

import tantivy

from common.logging_setup import log_event
from common.text_tokenize import tokenize, tokenize_text

logger = logging.getLogger("fts_index")

BODY_KIND = "body"
SKELETON_KIND = "skeleton"

# skeleton 分词检索域权重（目录/文件名最强，首句兜底）。
SKELETON_FIELD_BOOSTS = {
    "path_tokens": 2.0,
    "title": 1.8,
    "header_path": 1.5,
    "table_headers": 1.3,
    "first_col_keys": 1.2,
    "bold_keys": 1.2,
    "first_sentence": 1.0,
}


def path_tokens_text(rel_path: str) -> str:
    """目录名/文件名分词域：分隔符替换为空格后再走统一分词。"""
    if not rel_path:
        return ""
    flattened = re.sub(r"[/\\._\-]+", " ", str(rel_path))
    return tokenize_text(flattened)


class FtsIndex:
    # v2（历史 Phase 0）骨架索引域集合：title/header_path/first_sentence/table_headers。
    # v3 新增 path_tokens/first_col_keys/bold_keys 三个检索域；v2 目录只能按 v2 schema 打开。
    _LEGACY_SKELETON_FIELDS = ("doc_id", "section_id", "rel_path", "title",
                               "header_path", "first_sentence", "table_headers")
    _LEGACY_BODY_FIELDS = ("doc_id", "section_id", "chunk_id", "start_line",
                           "end_line", "content")

    def __init__(self, path: str | Path, kind: str = BODY_KIND):
        if kind not in (BODY_KIND, SKELETON_KIND):
            raise ValueError(f"unknown fts kind: {kind}")
        self.path = Path(path)
        self.kind = kind
        self.schema_mismatch = False
        self.recreated_on_schema_change = False
        # v2 兼容：旧 Schema 目录按其自有 Schema 只读打开（检索侧零写入）。
        self.legacy_schema = False
        self.available_fields: set[str] | None = None
        self.path.mkdir(parents=True, exist_ok=True)
        try:
            self.index = tantivy.Index(self._schema(), path=str(self.path))
        except ValueError as exc:
            if "schema does not match" not in str(exc).lower():
                raise
            # S-01 检索只读：先尝试按旧版 Schema 只读打开（保住路 2 可用性）；
            # 打不开才退回"只打标记不改磁盘"，待构建侧写入（writer/recreate）时再安全重建目录。
            legacy = self._try_open_legacy()
            if legacy is not None:
                self.index, self.available_fields = legacy
                self.legacy_schema = True
                log_event(
                    logger, "fts:legacy:opened", level=logging.WARNING,
                    kind=self.kind, path=str(self.path),
                    fields=sorted(f for f in self.available_fields
                                  if f not in ("doc_id", "section_id", "rel_path", "chunk_id",
                                               "start_line", "end_line", "content")),
                )
                return
            self.index = None
            self.schema_mismatch = True
            log_event(
                logger, "fts:schema:mismatch", level=logging.WARNING,
                kind=self.kind, path=str(self.path), error=str(exc),
            )

    def _try_open_legacy(self):
        """按 v2 历史 Schema 只读打开旧索引目录；失败返回 None 保持原降级行为。"""
        try:
            builder = tantivy.SchemaBuilder()
            if self.kind == BODY_KIND:
                builder.add_text_field("doc_id", stored=True, tokenizer_name="raw")
                builder.add_text_field("section_id", stored=True, tokenizer_name="raw")
                builder.add_text_field("chunk_id", stored=True, tokenizer_name="raw")
                builder.add_integer_field("start_line", stored=True, fast=True)
                builder.add_integer_field("end_line", stored=True, fast=True)
                builder.add_text_field("content", stored=False, tokenizer_name="whitespace")
                legacy_fields = set(self._LEGACY_BODY_FIELDS)
            else:
                for name in self._LEGACY_SKELETON_FIELDS:
                    if name in ("title", "header_path", "first_sentence", "table_headers"):
                        builder.add_text_field(name, stored=False, tokenizer_name="whitespace")
                    else:
                        builder.add_text_field(name, stored=True, tokenizer_name="raw")
                legacy_fields = set(self._LEGACY_SKELETON_FIELDS)
            index = tantivy.Index(builder.build(), path=str(self.path))
            return index, legacy_fields
        except Exception as exc:
            log_event(
                logger, "fts:legacy:open_failed", level=logging.DEBUG,
                kind=self.kind, path=str(self.path), error=str(exc),
            )
            return None

    def recreate(self) -> None:
        """构建期将旧版 Schema 索引目录安全重建为当前 Schema。"""
        shutil.rmtree(self.path, ignore_errors=True)
        self.path.mkdir(parents=True, exist_ok=True)
        self.index = tantivy.Index(self._schema(), path=str(self.path))
        self.schema_mismatch = False
        self.legacy_schema = False
        self.available_fields = None
        self.recreated_on_schema_change = True
        log_event(
            logger, "fts:upgrade:recreated", level=logging.WARNING,
            kind=self.kind, path=str(self.path),
        )

    # ------------------------------------------------------------------
    # schema / writer
    # ------------------------------------------------------------------
    def _schema(self):
        builder = tantivy.SchemaBuilder()
        if self.kind == BODY_KIND:
            builder.add_text_field("doc_id", stored=True, tokenizer_name="raw")
            builder.add_text_field("section_id", stored=True, tokenizer_name="raw")
            builder.add_text_field("chunk_id", stored=True, tokenizer_name="raw")
            # 用 signed integer，避免 tantivy 对 Python int 的 U64 类型断言
            builder.add_integer_field("start_line", stored=True, fast=True)
            builder.add_integer_field("end_line", stored=True, fast=True)
            # 内容已由 tokenize_text 预分词；whitespace 保证 ERR_401_02 不被再次拆开
            builder.add_text_field("content", stored=False, tokenizer_name="whitespace")
        else:
            builder.add_text_field("doc_id", stored=True, tokenizer_name="raw")
            builder.add_text_field("section_id", stored=True, tokenizer_name="raw")
            builder.add_text_field("rel_path", stored=True, tokenizer_name="raw")
            # 7 个分词检索域（全部 stored=False，入库前统一经 tokenize_text 预分词）
            builder.add_text_field("path_tokens", stored=False, tokenizer_name="whitespace")
            builder.add_text_field("title", stored=False, tokenizer_name="whitespace")
            builder.add_text_field("header_path", stored=False, tokenizer_name="whitespace")
            builder.add_text_field("first_sentence", stored=False, tokenizer_name="whitespace")
            builder.add_text_field("table_headers", stored=False, tokenizer_name="whitespace")
            builder.add_text_field("first_col_keys", stored=False, tokenizer_name="whitespace")
            builder.add_text_field("bold_keys", stored=False, tokenizer_name="whitespace")
        return builder.build()

    def writer(self):
        if self.schema_mismatch or self.index is None:
            self.recreate()
        elif self.legacy_schema:
            # v2 兼容：旧 Schema 索引只读可检索；一旦需要写入，先安全重建为
            # 当前 Schema（recreate 内部处理目录替换与标记复位）。
            self.recreate()
        return self.index.writer()

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------
    def add_body(self, rows: Iterable[dict], writer=None, commit: bool = True) -> int:
        """rows: doc_id/section_id/chunk_id/start_line/end_line/text。"""
        own = writer is None
        writer = writer or self.writer()
        added = 0
        for row in rows:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            writer.add_document(tantivy.Document.from_dict({
                "doc_id": str(row["doc_id"]),
                "section_id": str(row["section_id"]),
                "chunk_id": str(row["chunk_id"]),
                "start_line": int(row["start_line"]),
                "end_line": int(row["end_line"]),
                "content": tokenize_text(text),
            }))
            added += 1
        if own or commit:
            writer.commit()
            writer.wait_merging_threads()
        log_event(
            logger, "fts:add", level=logging.DEBUG,
            kind=self.kind, path=str(self.path.name), rows=added, committed=own or commit,
        )
        return added

    def add_skeleton(self, rows: Iterable[dict], writer=None, commit: bool = True) -> int:
        """rows: doc_id/section_id/rel_path/title/header_path/first_sentence/table_headers
        /first_col_keys/bold_keys（缺省键安全兜底为空串）。"""
        own = writer is None
        writer = writer or self.writer()
        added = 0
        for row in rows:
            writer.add_document(tantivy.Document.from_dict({
                "doc_id": str(row["doc_id"]),
                "section_id": str(row["section_id"]),
                "rel_path": str(row.get("rel_path", "")),
                "path_tokens": path_tokens_text(row.get("rel_path", "")),
                "title": tokenize_text(row.get("title", "")),
                "header_path": tokenize_text(row.get("header_path", "")),
                "first_sentence": tokenize_text(row.get("first_sentence", "")),
                "table_headers": tokenize_text(row.get("table_headers", "")),
                "first_col_keys": tokenize_text(row.get("first_col_keys", "")),
                "bold_keys": tokenize_text(row.get("bold_keys", "")),
            }))
            added += 1
        if own or commit:
            writer.commit()
            writer.wait_merging_threads()
        log_event(
            logger, "fts:add", level=logging.DEBUG,
            kind=self.kind, path=str(self.path.name), rows=added, committed=own or commit,
        )
        return added

    def delete_all(self, writer=None, commit: bool = True) -> None:
        own = writer is None
        writer = writer or self.writer()
        writer.delete_all_documents()
        if own or commit:
            writer.commit()
            writer.wait_merging_threads()
        log_event(logger, "fts:delete-all", level=logging.DEBUG, kind=self.kind)

    def delete_doc(self, doc_id: str, writer=None, commit: bool = True) -> None:
        own = writer is None
        writer = writer or self.writer()
        writer.delete_documents_by_term("doc_id", str(doc_id))
        if own or commit:
            writer.commit()
            writer.wait_merging_threads()
        log_event(logger, "fts:delete", level=logging.DEBUG, kind=self.kind, doc_id=doc_id)

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------
    def search(self, terms: list[str], top_k: int = 100, conjunction: bool = True) -> list[dict]:
        if self.schema_mismatch or self.index is None:
            raise RuntimeError(f"fts {self.kind} schema upgrade required")
        # 索引/查询共用同一分词；这里把调用方传入的原始 terms 归一化
        tokens: list[str] = []
        for term in terms or []:
            if term:
                tokens.extend(tokenize(term))
        if not tokens:
            return []
        t0 = time.perf_counter()
        self.index.reload()
        searcher = self.index.searcher()
        query_str = " ".join(tokens)
        if self.kind == BODY_KIND:
            query = self.index.parse_query(
                query_str, ["content"], conjunction_by_default=conjunction
            )
        else:
            # v2 兼容：旧骨架索引缺 v3 新增检索域（path_tokens/first_col_keys/bold_keys），
            # 查询域按实际可打开的 Schema 过滤，boost 沿用原表，绝不写盘。
            fields = list(SKELETON_FIELD_BOOSTS.keys())
            if self.available_fields is not None:
                fields = [f for f in fields if f in self.available_fields] or ["title"]
            query = self.index.parse_query(
                query_str,
                fields,
                field_boosts={k: v for k, v in SKELETON_FIELD_BOOSTS.items() if k in fields},
                conjunction_by_default=conjunction,
            )
        result = searcher.search(query, top_k)
        out = []
        for score, addr in result.hits:
            doc = searcher.doc(addr)
            row = {"score": float(score)}
            for name in ("doc_id", "section_id", "chunk_id", "rel_path"):
                value = doc.get_first(name)
                if value is not None:
                    row[name] = value
            for name in ("start_line", "end_line"):
                value = doc.get_first(name)
                if value is not None:
                    row[name] = int(value)
            out.append(row)
        log_event(
            logger, "fts:search", level=logging.DEBUG,
            kind=self.kind, terms=tokens, top_k=top_k, hits=len(out),
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
        )
        return out

    def count(self) -> int:
        if self.schema_mismatch or self.index is None:
            return 0
        self.index.reload()
        return self.index.searcher().num_docs

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.path.rglob("*") if p.is_file())
