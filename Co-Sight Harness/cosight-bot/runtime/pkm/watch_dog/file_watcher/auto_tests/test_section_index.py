#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SectionIndex 单测：LanceDB 表、f16 向量、FTS、增量更新/删除。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from watch_dog.file_watcher.section_index import DIM, SectionIndex  # noqa: E402


class FakeEmbedding:
    def _get_text_embeddings(self, texts):
        return [[0.01 * (i + 1)] * DIM for i in range(len(texts))]


DOC_A = """# Alpha

Retention policy control plane.

## 1. Overview

Alpha overview first sentence.

| Code | Meaning |
|---|---|
| ERR_401_02 | token mutex |
"""

DOC_B = """# Beta

Incident rollback and audit log.

## 1. Detail

Beta detail with rollback steps.
"""


class SectionIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pre = root / "pre"
        self.lan = root / "lan"
        self.pre.mkdir()
        (self.pre / "a.md").write_text(DOC_A, encoding="utf-8")
        (self.pre / "b.md").write_text(DOC_B, encoding="utf-8")
        self.si = SectionIndex(self.lan, embedding=FakeEmbedding(), enable_ann=False)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_tables_and_fts(self) -> None:
        summary = self.si.build_from_pre_dir(self.pre)
        final = self.si.finalize()
        self.assertEqual(summary["docs"], 2)
        self.assertGreater(summary["sections"], 0)
        self.assertGreater(summary["chunks"], 0)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(final["docs"], 2)
        stats = self.si.stats()
        self.assertEqual(stats["docs"], 2)
        self.assertGreater(stats["sections"], 0)
        self.assertGreater(stats["pointers"], 0)
        self.assertGreater(stats["body_fts_rows"], 0)
        self.assertGreater(stats["skeleton_fts_rows"], 0)

        # f16 向量列
        field = self.si.section_table.to_arrow().schema.field("vector")
        self.assertTrue(str(field.type).startswith("fixed_size_list"))

        # FTS 命中
        hits = self.si.fts_body.search(["retention"], top_k=10)
        self.assertIn("a.md", {h["doc_id"] for h in hits})
        # section 向量检索
        rows = self.si.search_sections([0.1] * DIM, top_k=5)
        self.assertGreater(len(rows), 0)
        self.assertIn("doc_key", rows[0])

    def test_incremental_upsert_does_not_duplicate(self) -> None:
        self.si.build_from_pre_dir(self.pre)
        self.si.finalize()
        before = self.si.stats()["docs"]
        self.si.upsert_document(self.pre / "a.md", "a.md")
        self.si.commit()
        self.si.finalize()
        self.assertEqual(self.si.stats()["docs"], before)

    def test_delete_document(self) -> None:
        self.si.build_from_pre_dir(self.pre)
        self.si.finalize()
        self.si.delete_document("a.md")
        self.si.commit()
        self.si.finalize()
        stats = self.si.stats()
        self.assertEqual(stats["docs"], 1)
        self.assertEqual(self.si.fts_body.search(["retention"], top_k=10), [])
        self.assertIn("b.md", {h["doc_id"] for h in self.si.fts_body.search(["rollback"], top_k=10)})

    def test_stable_doc_id_from_node_index(self) -> None:
        # overview_builder 先写 node_index.json，SectionIndex 构建期读取稳定 ID
        (self.lan / "node_index.json").write_text(
            json.dumps({
                "_next_id": 9,
                "F004": "a.md",
                "F005": "b.md",
            }),
            encoding="utf-8",
        )
        self.si.build_from_pre_dir(self.pre)
        self.si.finalize()
        rows = self.si.doc_table.to_arrow().to_pylist()
        keys = {r["rel_path"]: r["doc_key"] for r in rows}
        self.assertEqual(keys, {"a.md": "F004", "b.md": "F005"})

        hits = self.si.fts_body.search(["retention"], top_k=10)
        self.assertEqual({h["doc_id"] for h in hits}, {"F004"})
        section_rows = self.si.section_table.to_arrow().to_pylist()
        self.assertEqual({r["doc_key"] for r in section_rows}, {"F004", "F005"})

        # 增量删除用 rel_path 也能反查到稳定 key
        self.si.delete_document("a.md")
        self.si.commit()
        self.si.finalize()
        self.assertEqual(self.si.stats()["docs"], 1)
        self.assertEqual(self.si.fts_body.search(["retention"], top_k=10), [])

    def test_promoted_chapter_indexed_only_when_in_overview(self) -> None:
        (self.pre / "main.md").write_text("# Main\n", encoding="utf-8")
        (self.pre / "main_chapters").mkdir()
        (self.pre / "main_chapters" / "part.md").write_text(
            "# Part\n\npromoted chapter body\n", encoding="utf-8"
        )
        (self.pre / "other_chapters").mkdir()
        (self.pre / "other_chapters" / "hidden.md").write_text(
            "# Hidden\n\nhidden chapter body\n", encoding="utf-8"
        )
        (self.lan / "node_index.json").write_text(
            json.dumps({
                "_next_id": 5,
                "F001": "main.md",
                "F002": "main_chapters/part.md",
                "F003": "other_chapters/hidden.md",
            }),
            encoding="utf-8",
        )
        (self.lan / "overview.md").write_text(
            "# overview-format: v2-compressed\n---\n\n"
            "[F001] main\n[F002] part\n",
            encoding="utf-8",
        )
        self.si.build_from_pre_dir(self.pre)
        self.si.finalize()

        rows = self.si.doc_table.to_arrow().to_pylist()
        keys = {r["rel_path"]: r["doc_key"] for r in rows}
        self.assertEqual(keys["main_chapters/part.md"], "F002")
        self.assertNotIn("other_chapters/hidden.md", keys)
        hits = self.si.fts_body.search(["promoted"], top_k=10)
        self.assertEqual({h["doc_id"] for h in hits}, {"F002"})


if __name__ == "__main__":
    unittest.main()
