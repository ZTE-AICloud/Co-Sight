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

import lancedb
import numpy as np
import pyarrow as pa

from watch_dog.file_watcher.section_index import (  # noqa: E402
    DIM,
    SCHEMA_VERSION,
    SectionIndex,
)


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


class SchemaV3Test(unittest.TestCase):
    """底座-B1：SCHEMA_VERSION=3 双向量表 + JEV 角色列预留 + 平滑升级。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pre = root / "pre"
        self.lan = root / "lan"
        self.pre.mkdir()
        (self.pre / "a.md").write_text(DOC_A, encoding="utf-8")
        (self.pre / "b.md").write_text(DOC_B, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _new_index(self) -> SectionIndex:
        return SectionIndex(self.lan, embedding=FakeEmbedding(), enable_ann=False)

    def test_schema_version_is_3(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 3)

    def test_v3_columns_and_dual_vectors(self) -> None:
        si = self._new_index()
        si.build_from_pre_dir(self.pre)
        si.finalize()
        # doc_skeleton：JEV 三列 + 默认值
        doc_fields = set(si.doc_table.to_arrow().schema.names)
        self.assertIn("jev_doc_type", doc_fields)
        self.assertIn("jev_doc_type_conf", doc_fields)
        self.assertIn("jev_is_registry", doc_fields)
        row = si.doc_table.to_arrow().to_pylist()[0]
        self.assertEqual(row["jev_doc_type"], "")
        self.assertEqual(row["jev_doc_type_conf"], 0.0)
        self.assertFalse(row["jev_is_registry"])
        # doc_meta JSON 镜像
        meta = json.loads(row["doc_meta"])
        self.assertEqual(meta["jev_doc_type"], "")
        self.assertEqual(meta["jev_doc_type_conf"], 0.0)
        self.assertFalse(meta["jev_is_registry"])
        # nodes_pointer：float16[1024] 向量列，严禁 text 原文列
        ptr_schema = si.pointer_table.to_arrow().schema
        self.assertIn("vector", ptr_schema.names)
        self.assertNotIn("text", ptr_schema.names)
        vec_type = str(ptr_schema.field("vector").type)
        self.assertIn("fixed_size_list", vec_type)
        self.assertIn("1024", vec_type)
        # build_meta 记录 v3 与双 ANN 开关
        meta = {
            r["key"]: r["value"] for r in si.meta_table.to_arrow().to_pylist()
        }
        self.assertEqual(meta["schema_version"], "3")
        self.assertIn("section_ann_enabled", meta)
        self.assertIn("pointer_ann_enabled", meta)
        self.assertIn("ann_enabled", meta)

    def test_role_info_written_into_payload(self) -> None:
        si = self._new_index()
        si.upsert_document(
            self.pre / "a.md", "a.md",
            role_info={"jev_doc_type": "runbook_sop", "jev_doc_type_conf": 1.0,
                       "jev_is_registry": False},
        )
        si.commit()
        si.finalize()
        row = next(
            r for r in si.doc_table.to_arrow().to_pylist() if r["rel_path"] == "a.md"
        )
        self.assertEqual(row["jev_doc_type"], "runbook_sop")
        self.assertAlmostEqual(row["jev_doc_type_conf"], 1.0, places=3)
        self.assertFalse(row["jev_is_registry"])
        meta = json.loads(row["doc_meta"])
        self.assertEqual(meta["jev_doc_type"], "runbook_sop")

    def _seed_legacy_v2_index(self) -> None:
        """构造完整存量 v2 磁盘索引：缺列 LanceDB 表 + 旧 4 域 Tantivy fts/skeleton。"""
        import tantivy

        db = lancedb.connect(str(self.lan))
        db.create_table("doc_skeleton", schema=pa.schema([
            pa.field("doc_key", pa.string()), pa.field("rel_path", pa.string()),
            pa.field("title", pa.string()), pa.field("doc_meta", pa.string()),
            pa.field("skeleton_json", pa.string()), pa.field("fingerprint", pa.string()),
            pa.field("line_count", pa.int64()), pa.field("char_count", pa.int64()),
            pa.field("updated_at", pa.int64()),
        ]))
        db.create_table("nodes_pointer", schema=pa.schema([
            pa.field("doc_key", pa.string()), pa.field("section_id", pa.string()),
            pa.field("chunk_id", pa.string()), pa.field("start_line", pa.int64()),
            pa.field("end_line", pa.int64()), pa.field("header_line", pa.int64()),
        ]))
        db.create_table("build_meta", schema=pa.schema([
            pa.field("key", pa.string()), pa.field("value", pa.string()),
        ]))
        db.open_table("doc_skeleton").add([{
            "doc_key": "F001", "rel_path": "a.md", "title": "a.md",
            "doc_meta": "{}", "skeleton_json": "{}", "fingerprint": "",
            "line_count": 1, "char_count": 1, "updated_at": 0,
        }])
        db.open_table("build_meta").add([{"key": "schema_version", "value": "2"}])

        skel_dir = self.lan / "fts" / "skeleton"
        skel_dir.mkdir(parents=True, exist_ok=True)
        builder = tantivy.SchemaBuilder()
        builder.add_text_field("doc_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("section_id", stored=True, tokenizer_name="raw")
        builder.add_text_field("rel_path", stored=True, tokenizer_name="raw")
        builder.add_text_field("title", stored=False, tokenizer_name="whitespace")
        builder.add_text_field("header_path", stored=False, tokenizer_name="whitespace")
        builder.add_text_field("first_sentence", stored=False, tokenizer_name="whitespace")
        builder.add_text_field("table_headers", stored=False, tokenizer_name="whitespace")
        old_fts = tantivy.Index(builder.build(), path=str(skel_dir))
        old_w = old_fts.writer()
        old_w.add_document(tantivy.Document.from_dict({
            "doc_id": "F001", "section_id": "F001#1", "rel_path": "a.md", "title": "legacy",
        }))
        old_w.commit()
        del old_w, old_fts

    def test_v2_tables_upgrade_smoothly_on_full_build(self) -> None:
        self._seed_legacy_v2_index()

        # full_build 路径同时平滑重建旧 LanceDB 表与旧 4 域 Tantivy fts/skeleton
        si = self._new_index()
        self.assertTrue(si.needs_schema_upgrade)
        summary = si.build_from_pre_dir(self.pre, full_build=True)
        self.assertEqual(summary["failed"], 0)
        final = si.finalize()
        self.assertEqual(final["docs"], 2)
        self.assertFalse(si.needs_schema_upgrade)
        doc_fields = set(si.doc_table.to_arrow().schema.names)
        self.assertIn("jev_doc_type", doc_fields)
        self.assertIn("vector", set(si.pointer_table.to_arrow().schema.names))
        meta = {r["key"]: r["value"] for r in si.meta_table.to_arrow().to_pylist()}
        self.assertEqual(meta["schema_version"], "3")
        self.assertGreater(si.fts_skeleton.count(), 0)

    def test_v2_pointer_probe_skips_gracefully_and_recovers_after_rebuild(self) -> None:
        """v2 兼容：无向量列的 nodes_pointer 上路 3 优雅返回空，重建后自动恢复。"""
        import numpy as np

        self._seed_legacy_v2_index()
        si = self._new_index()
        self.assertTrue(si.needs_schema_upgrade)
        self.assertFalse(si.pointer_vector_ready)
        # 路 3 探针：不抛错、返回空（日志只记一次）
        self.assertEqual(si.search_pointers(np.zeros(1024, dtype=np.float32)), [])
        self.assertEqual(si.search_pointers(np.ones(1024, dtype=np.float32)), [])
        # full_build 重建后路 3 恢复：可正常召回（检索只读红线不受影响）
        summary = si.build_from_pre_dir(self.pre, full_build=True)
        self.assertEqual(summary["failed"], 0)
        si.finalize()
        self.assertTrue(si.pointer_vector_ready)
        pointer_rows = si.pointer_table.to_arrow().to_pylist()
        self.assertTrue(pointer_rows)
        phits = si.search_pointers(
            np.asarray(pointer_rows[0]["vector"], dtype=np.float32), top_k=3,
        )
        self.assertTrue(phits)

    def test_v2_incremental_trigger_auto_promotes_to_full_build(self) -> None:
        self._seed_legacy_v2_index()

        # 存量 v2 库首次遇到单文件增量触发（rel_paths={"a.md"}, full_build=False）时，
        # 自动提升为 full_build=True 全量升级全部 2 篇文档，零 Schema mismatch
        si = self._new_index()
        self.assertTrue(si.needs_schema_upgrade)
        summary = si.build_from_pre_dir(self.pre, rel_paths={"a.md"}, full_build=False)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["docs"], 2)
        final = si.finalize()
        self.assertEqual(final["docs"], 2)
        self.assertFalse(si.needs_schema_upgrade)
        meta = {r["key"]: r["value"] for r in si.meta_table.to_arrow().to_pylist()}
        self.assertEqual(meta["schema_version"], "3")

    def test_search_sections_and_pointers_recall(self) -> None:
        si = self._new_index()
        si.build_from_pre_dir(self.pre)
        si.finalize()
        # section 向量：直接回读某行的向量做余弦查询，应召回该行自身
        section_rows = si.section_table.to_arrow().to_pylist()
        target = section_rows[0]
        hits = si.search_sections(np.asarray(target["vector"], dtype=np.float32), top_k=3)
        self.assertTrue(hits)
        self.assertEqual(str(hits[0]["section_id"]), str(target["section_id"]))
        # pointer 向量：同理验证路 3 召回通路
        pointer_rows = si.pointer_table.to_arrow().to_pylist()
        ptr = pointer_rows[0]
        phits = si.search_pointers(np.asarray(ptr["vector"], dtype=np.float32), top_k=3)
        self.assertTrue(phits)
        self.assertEqual(str(phits[0]["chunk_id"]), str(ptr["chunk_id"]))
        self.assertIn("start_line", phits[0])
        self.assertIn("header_line", phits[0])

    def test_ann_ready_flags_from_meta(self) -> None:
        si = self._new_index()
        si.build_from_pre_dir(self.pre)
        si.finalize()
        # 小库未达阈值：双 ANN 均未启用，但兼容别名 ann_ready 可用
        self.assertFalse(si.section_ann_ready)
        self.assertFalse(si.pointer_ann_ready)
        self.assertFalse(si.ann_ready)


if __name__ == "__main__":
    unittest.main()
