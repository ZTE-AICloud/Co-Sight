#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handler 增量 section 索引接线：overview 刷新后使用稳定 ID。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_RUNTIME = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

import lancedb  # noqa: E402

from watch_dog.file_watcher.handler import LlamaIndexIncrementalHandler  # noqa: E402
from watch_dog.file_watcher.overview_builder import write_overview_md  # noqa: E402
from watch_dog.file_watcher.section_index import DIM, SectionIndex  # noqa: E402


class FakeEmbedding:
    def _get_text_embeddings(self, texts):
        return [[0.01 * (i + 1)] * DIM for i in range(len(texts))]


class HandlerSectionIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "src"
        self.pre = self.root / "pre"
        self.lan = self.root / "lan"
        self.src.mkdir()
        self.pre.mkdir()
        self.lan.mkdir()
        self._write("a.md", "# Alpha\n\nretention policy\n")
        self._write("b.md", "# Beta\n\nrollback steps\n")
        self.handler = LlamaIndexIncrementalHandler(self.src, agent_id="test")

    def tearDown(self) -> None:
        self.handler.shutdown()
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        (self.pre / rel).write_text(text, encoding="utf-8")

    def _doc_keys(self) -> dict[str, str]:
        db = lancedb.connect(str(self.lan))
        rows = db.open_table("doc_skeleton").to_arrow().to_pylist()
        return {r["rel_path"]: r["doc_key"] for r in rows}

    def test_legacy_doc_key_detected_for_full_rebuild(self) -> None:
        # 模拟稳定 ID 之前的索引：无 node_index，doc_key 回退为 rel_path
        builder = SectionIndex(self.lan, embedding=FakeEmbedding(), enable_ann=False)
        builder.build_from_pre_dir(self.pre, full_build=True)
        builder.finalize()
        self.assertTrue(self.handler._section_index_needs_upgrade(self.lan))

        # 新格式（doc_key=F###）不需要重建
        write_overview_md(self.lan, self.pre)
        rebuilt = SectionIndex(self.lan, embedding=FakeEmbedding(), enable_ann=False)
        rebuilt.build_from_pre_dir(self.pre, full_build=True)
        rebuilt.finalize()
        self.assertFalse(self.handler._section_index_needs_upgrade(self.lan))

    def test_incremental_uses_stable_id_and_deletes_by_rel_path(self) -> None:
        write_overview_md(self.lan, self.pre)
        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()):
            self.handler._update_section_index_for_event(
                self.lan, self.pre, "a.md", event="created"
            )
            self.handler._update_section_index_for_event(
                self.lan, self.pre, "b.md", event="created"
            )
            self.assertEqual(self._doc_keys(), {"a.md": "F001", "b.md": "F002"})

            # 新文件在 overview 刷新后获得稳定 ID，section 索引跟随
            self._write("c.md", "# Gamma\n\naudit log\n")
            write_overview_md(self.lan, self.pre)
            self.handler._update_section_index_for_event(
                self.lan, self.pre, "c.md", event="created"
            )
            self.assertEqual(self._doc_keys()["c.md"], "F003")

            # 删除事件：node_index 已移除该文件，仍能按 rel_path 反查旧 key
            (self.pre / "a.md").unlink()
            write_overview_md(self.lan, self.pre)
            self.handler._update_section_index_for_event(
                self.lan, self.pre, "a.md", event="deleted"
            )
            self.assertEqual(set(self._doc_keys()), {"b.md", "c.md"})


if __name__ == "__main__":
    unittest.main()
