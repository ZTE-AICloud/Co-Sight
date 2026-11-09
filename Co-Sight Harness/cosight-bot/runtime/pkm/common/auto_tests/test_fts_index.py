#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FtsIndex 单测：contentless、查询、增量删除、骨架索引。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))

from common.fts_index import FtsIndex  # noqa: E402
from common.text_tokenize import tokenize, tokenize_text  # noqa: E402


class TokenizeTest(unittest.TestCase):
    def test_identifiers_kept_whole(self) -> None:
        tokens = tokenize("SSO 网关抛出 ERR_401_02，IP 192.168.1.1，版本 v2.3.1")
        # ASCII 统一小写以支持大小写不敏感检索，但标识符不被拆成 ERR/401/02
        self.assertIn("err_401_02", tokens)
        self.assertIn("192.168.1.1", tokens)
        self.assertIn("v2.3.1", tokens)
        self.assertNotIn("err", tokens)
        self.assertNotIn("401", tokens)

    def test_index_query_same_tokenization(self) -> None:
        text = "并发刷新锁 RefreshMutex 导致 ERR_401_02"
        self.assertEqual(tokenize_text(text), tokenize_text(text))
        self.assertIn("RefreshMutex", text)  # 原文不被改写

    def test_trailing_punctuation_not_in_identifier(self) -> None:
        tokens = tokenize("keyword M3PROMOTED. Done, next; value.")
        self.assertIn("m3promoted", tokens)
        self.assertNotIn("m3promoted.", tokens)
        self.assertIn("done", tokens)
        self.assertIn("next", tokens)
        # 内部点号仍保留
        self.assertIn("v2.3.1", tokenize("版本 v2.3.1。"))


class FtsIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.body = FtsIndex(self.root / "fts_body", "body")
        self.body.add_body([
            {
                "doc_id": "F001", "section_id": "F001#0", "chunk_id": "F001#0",
                "start_line": 1, "end_line": 5,
                "text": "retention policy control plane ERR_401_02 RefreshMutex",
            },
            {
                "doc_id": "F002", "section_id": "F002#0", "chunk_id": "F002#0",
                "start_line": 10, "end_line": 12,
                "text": "incident rollback audit log retention",
            },
        ])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_search_and_pointers(self) -> None:
        hits = self.body.search(["retention"], top_k=10)
        self.assertEqual({h["doc_id"] for h in hits}, {"F001", "F002"})
        hits = self.body.search(["ERR_401_02"], top_k=10)
        self.assertEqual([h["doc_id"] for h in hits], ["F001"])
        self.assertEqual(hits[0]["start_line"], 1)
        self.assertEqual(hits[0]["end_line"], 5)

    def test_and_semantics(self) -> None:
        # F002 同时含 retention 与 incident
        self.assertEqual(
            [h["doc_id"] for h in self.body.search(["retention", "incident"], top_k=10)],
            ["F002"],
        )
        # 不存在的词 → AND 失败
        self.assertEqual(self.body.search(["retention", "nonexistent"], top_k=10), [])
        self.assertEqual(
            [h["doc_id"] for h in self.body.search(["retention", "rollback"], top_k=10)],
            ["F002"],
        )

    def test_content_not_stored(self) -> None:
        self.body.index.reload()
        searcher = self.body.index.searcher()
        query = self.body.index.parse_query("retention", ["content"])
        result = searcher.search(query, 1)
        self.assertTrue(result.hits)
        doc = searcher.doc(result.hits[0][1])
        self.assertIsNone(doc.get_first("content"))
        self.assertIsNotNone(doc.get_first("doc_id"))

    def test_incremental_delete(self) -> None:
        self.assertEqual(self.body.count(), 2)
        self.body.delete_doc("F001")
        self.assertEqual(self.body.count(), 1)
        self.assertEqual(self.body.search(["ERR_401_02"], top_k=10), [])
        self.assertEqual(
            [h["doc_id"] for h in self.body.search(["retention"], top_k=10)], ["F002"]
        )

    def test_skeleton_index(self) -> None:
        skel = FtsIndex(self.root / "fts_skeleton", "skeleton")
        skel.add_skeleton([
            {
                "doc_id": "F001", "section_id": "F001#0", "rel_path": "a/doc.md",
                "title": "会话Token刷新机制",
                "header_path": "1. 概述/1.2 会话Token刷新机制",
                "first_sentence": "客户端偶发退回登录页",
                "table_headers": "错误码 现象 根因",
            },
        ])
        hits = skel.search(["登录页"], top_k=10)
        self.assertEqual([h["doc_id"] for h in hits], ["F001"])
        self.assertEqual(hits[0]["rel_path"], "a/doc.md")
        self.assertGreater(self.body.size_bytes(), 0)


if __name__ == "__main__":
    unittest.main()
