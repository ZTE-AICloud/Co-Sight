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

from common.fts_index import FtsIndex, path_tokens_text  # noqa: E402
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


class SkeletonSevenFieldsTest(unittest.TestCase):
    """底座-B1：fts/skeleton 全部 7 个分词检索域召回验证。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.skel = FtsIndex(Path(self.tmp.name) / "fts_skeleton", "skeleton")
        self.skel.add_skeleton([
            {
                # 业务主体名只写在目录/文件名里，正文首行直接是表格
                "doc_id": "F010", "section_id": "F010#1",
                "rel_path": "clients/mariner_health/2026-11-27.md",
                "title": "Ops Bridge",
                "header_path": "1. Escalation",
                "first_sentence": "Bridge notes for the weekly review.",
                "table_headers": "Vendor ID Status",
                "first_col_keys": " ".join(f"VND-{i:03d}" for i in range(1, 56)),
                "bold_keys": "故障切换阈值 回滚护栏",
            },
        ])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_path_tokens_recall_dir_and_filename(self) -> None:
        # 目录名与文件名中的客户名/项目代号可被检索
        for term in ("mariner", "health", "clients"):
            hits = self.skel.search([term], top_k=10)
            self.assertEqual([h["doc_id"] for h in hits], ["F010"], term)
        self.assertEqual(self.skel.search(["nonexistent"], top_k=10), [])

    def test_first_col_keys_recall_deep_row(self) -> None:
        # 表格第 55 行首列键
        hits = self.skel.search(["VND-055"], top_k=10)
        self.assertEqual([h["doc_id"] for h in hits], ["F010"])
        self.assertEqual(self.skel.search(["VND-099"], top_k=10), [])

    def test_bold_keys_recall(self) -> None:
        hits = self.skel.search(["故障切换阈值"], top_k=10)
        self.assertEqual([h["doc_id"] for h in hits], ["F010"])

    def test_path_tokens_text_flattening(self) -> None:
        # 分隔符全部压成空格后走统一分词；扩展名 md 也成为可检索 token
        self.assertEqual(path_tokens_text("dir/sub_name-x.md"), "dir sub name md")
        self.assertEqual(path_tokens_text(""), "")

    def test_field_boosts_query_runs(self) -> None:
        # 7 个分词域带 field_boosts 查询可正常执行（tantivy parse_query 接受
        # field_boosts 参数；跨域 BM25 分数受字段长度归一化影响，不做精确排序断言）
        hits = self.skel.search(["vendor", "status"], top_k=10)
        self.assertEqual([h["doc_id"] for h in hits], ["F010"])
        hits = self.skel.search(["bridge"], top_k=10)
        self.assertEqual([h["doc_id"] for h in hits], ["F010"])

    def test_v2_four_field_skeleton_lazy_upgrade_preserves_s01_readonly(self) -> None:
        # 预建旧 v2 的 4 分词域 Tantivy 索引目录
        import tantivy

        legacy_dir = Path(self.tmp.name) / "legacy_v2_skeleton"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        builder = tantivy.SchemaBuilder()
        builder.add_text_field("doc_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("section_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("rel_path", stored=True, tokenizer_name="raw")
        builder.add_text_field("title", stored=False, tokenizer_name="whitespace")
        builder.add_text_field("header_path", stored=False, tokenizer_name="whitespace")
        builder.add_text_field("first_sentence", stored=False, tokenizer_name="whitespace")
        builder.add_text_field("table_headers", stored=False, tokenizer_name="whitespace")
        old_idx = tantivy.Index(builder.build(), path=str(legacy_dir))
        old_w = old_idx.writer()
        old_w.add_document(tantivy.Document.from_dict({
            "doc_id": "F001", "section_id": "F001#1", "rel_path": "a.md", "title": "legacy",
        }))
        old_w.commit()
        del old_w, old_idx
        meta_before = (legacy_dir / "meta.json").read_text(encoding="utf-8")

        # 1) 只读实例化不抛异常、绝不修改旧 meta.json（严守 S-01 检索只读）；
        #    v2 兼容层允许按旧 Schema 只读检索（路 2 在存量库上保持可用）
        upgraded = FtsIndex(legacy_dir, "skeleton")
        self.assertTrue(upgraded.legacy_schema)
        self.assertFalse(upgraded.schema_mismatch)
        self.assertEqual(
            upgraded.available_fields,
            {"doc_id", "section_id", "rel_path", "title", "header_path",
             "first_sentence", "table_headers"},
        )
        self.assertEqual((legacy_dir / "meta.json").read_text(encoding="utf-8"), meta_before)
        self.assertEqual([h["doc_id"] for h in upgraded.search(["legacy"])], ["F001"])

        # 2) 构建期写入自动重建为 7 域 Schema 并正常支持新字段检索
        upgraded.delete_all()
        self.assertFalse(upgraded.schema_mismatch)
        self.assertTrue(upgraded.recreated_on_schema_change)
        upgraded.add_skeleton([{
            "doc_id": "F002", "section_id": "F002#1", "rel_path": "ops/cutover.md",
            "title": "Cutover", "first_col_keys": "VND_088", "bold_keys": "RTO",
        }])
        self.assertEqual([h["doc_id"] for h in upgraded.search(["VND_088"])], ["F002"])
        self.assertEqual([h["doc_id"] for h in upgraded.search(["cutover"])], ["F002"])


if __name__ == "__main__":
    unittest.main()
