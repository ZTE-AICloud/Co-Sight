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
import time
from pathlib import Path
from typing import Iterable

import tantivy

from common.logging_setup import log_event
from common.text_tokenize import tokenize, tokenize_text

logger = logging.getLogger("fts_index")

BODY_KIND = "body"
SKELETON_KIND = "skeleton"


class FtsIndex:
    def __init__(self, path: str | Path, kind: str = BODY_KIND):
        if kind not in (BODY_KIND, SKELETON_KIND):
            raise ValueError(f"unknown fts kind: {kind}")
        self.path = Path(path)
        self.kind = kind
        self.path.mkdir(parents=True, exist_ok=True)
        self.index = tantivy.Index(self._schema(), path=str(self.path))

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
            builder.add_text_field("title", stored=False, tokenizer_name="whitespace")
            builder.add_text_field("header_path", stored=False, tokenizer_name="whitespace")
            builder.add_text_field("first_sentence", stored=False, tokenizer_name="whitespace")
            builder.add_text_field("table_headers", stored=False, tokenizer_name="whitespace")
        return builder.build()

    def writer(self):
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
        """rows: doc_id/section_id/rel_path/title/header_path/first_sentence/table_headers。"""
        own = writer is None
        writer = writer or self.writer()
        added = 0
        for row in rows:
            writer.add_document(tantivy.Document.from_dict({
                "doc_id": str(row["doc_id"]),
                "section_id": str(row["section_id"]),
                "rel_path": str(row.get("rel_path", "")),
                "title": tokenize_text(row.get("title", "")),
                "header_path": tokenize_text(row.get("header_path", "")),
                "first_sentence": tokenize_text(row.get("first_sentence", "")),
                "table_headers": tokenize_text(row.get("table_headers", "")),
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
            query = self.index.parse_query(
                query_str,
                ["title", "header_path", "first_sentence", "table_headers"],
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
        self.index.reload()
        return self.index.searcher().num_docs

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.path.rglob("*") if p.is_file())
