#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""overview_builder 稳定节点 ID / 主文档去重单测。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from watch_dog.file_watcher.overview_builder import (  # noqa: E402
    NEXT_ID_KEY,
    write_overview_md,
)


class StableNodeIdTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pre = root / "pre"
        self.lan = root / "lan"
        self.pre.mkdir()
        self.lan.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, rel: str, text: str = "# T\n\nbody\n") -> None:
        path = self.pre / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _index(self) -> dict:
        return json.loads((self.lan / "node_index.json").read_text(encoding="utf-8"))

    @staticmethod
    def _paths(index: dict) -> dict[str, str]:
        return {
            rel: node_id
            for node_id, rel in index.items()
            if node_id != NEXT_ID_KEY and isinstance(rel, str)
        }

    def test_ids_stable_on_insert_and_delete(self) -> None:
        self._write("a.md")
        self._write("b.md")
        write_overview_md(self.lan, self.pre)
        first = self._index()
        paths = self._paths(first)
        self.assertEqual(paths["a.md"], "F001")
        self.assertEqual(paths["b.md"], "F002")
        self.assertEqual(first[NEXT_ID_KEY], 3)

        # 字典序更靠前的新文件不能挤动已有编号
        self._write("0-new.md")
        write_overview_md(self.lan, self.pre)
        second = self._index()
        paths2 = self._paths(second)
        self.assertEqual(paths2["a.md"], "F001")
        self.assertEqual(paths2["b.md"], "F002")
        self.assertEqual(paths2["0-new.md"], "F003")
        self.assertEqual(second[NEXT_ID_KEY], 4)
        # 显示序按编号而非名称：F001 仍在 F003 之前
        overview = (self.lan / "overview.md").read_text(encoding="utf-8")
        self.assertLess(overview.index("F001"), overview.index("F003"))

        # 删除中间文件：其余编号不变，水位线不回退
        (self.pre / "a.md").unlink()
        write_overview_md(self.lan, self.pre)
        third = self._index()
        paths3 = self._paths(third)
        self.assertNotIn("a.md", paths3)
        self.assertEqual(paths3["b.md"], "F002")
        self.assertEqual(paths3["0-new.md"], "F003")
        self.assertGreaterEqual(third[NEXT_ID_KEY], 4)

    def test_chapters_excluded_from_tree_but_alias_kept(self) -> None:
        self._write("main.md", "# Main\n\n## Part 1\n\ncontent\n")
        self._write("main_chapters/part1.md", "# Part 1\n\nchapter content\n")
        write_overview_md(self.lan, self.pre)

        overview = (self.lan / "overview.md").read_text(encoding="utf-8")
        # 主文档为准：章节文件不进入 overview 树
        self.assertIn("main", overview)
        self.assertNotIn("part1", overview)

        index = self._index()
        paths = self._paths(index)
        self.assertIn("main.md", paths)
        self.assertIn("main_chapters/part1.md", paths)
        # 章节 alias 与主文档使用不同 ID，旧 read-doc 仍可解析
        self.assertNotEqual(paths["main.md"], paths["main_chapters/part1.md"])

    def test_chapters_promoted_when_main_doc_empty(self) -> None:
        self._write("main.md", "# Main\n\n## Part 1\n")
        self._write("main_chapters/part1.md", "# Part 1\n\nchapter content\n")
        write_overview_md(self.lan, self.pre)

        overview = (self.lan / "overview.md").read_text(encoding="utf-8")
        self.assertIn("main_chapters", overview)
        self.assertIn("part1", overview)
        paths = self._paths(self._index())
        self.assertIn("main.md", paths)
        self.assertIn("main_chapters/part1.md", paths)

    def test_chapters_promoted_for_preprocessed_md_name(self) -> None:
        # 预处理后的 markdown 主文档是 main_md.md，章节目录仍是 main_chapters/
        self._write("main_md.md", "# Main\n")
        self._write("main_chapters/part1.md", "# Part 1\n\nchapter content\n")
        write_overview_md(self.lan, self.pre)

        overview = (self.lan / "overview.md").read_text(encoding="utf-8")
        self.assertIn("main_chapters", overview)
        self.assertIn("part1", overview)

    def test_chapters_promoted_when_main_doc_only_toc(self) -> None:
        self._write(
            "main.md",
            "# Main\n\n## 目录\n\n- [Part 1](#part-1)\n\n1. Overview .... 1\n",
        )
        self._write("main_chapters/part1.md", "# Part 1\n\nchapter content\n")
        write_overview_md(self.lan, self.pre)

        overview = (self.lan / "overview.md").read_text(encoding="utf-8")
        self.assertIn("main_chapters", overview)
        self.assertIn("part1", overview)

    def test_orphan_chapters_promoted_when_main_missing(self) -> None:
        self._write("other.md", "# Other\n\nbody\n")
        self._write("main_chapters/part1.md", "# Part 1\n\nchapter content\n")
        write_overview_md(self.lan, self.pre)

        overview = (self.lan / "overview.md").read_text(encoding="utf-8")
        self.assertIn("main_chapters", overview)
        self.assertIn("part1", overview)

    def test_chapters_not_promoted_when_pages_sibling_exists(self) -> None:
        self._write("scan_pdf.md", "# Scan\n\n## 第 1 页\n")
        self._write("scan_pdf_pages/Page_001.md", "# Page 1\n\ninvoice\n")
        self._write("scan_pdf_chapters/part1.md", "# Part 1\n\nchapter content\n")
        write_overview_md(self.lan, self.pre)

        overview = (self.lan / "overview.md").read_text(encoding="utf-8")
        self.assertIn("Page_001", overview)
        self.assertNotIn("part1", overview)


if __name__ == "__main__":
    unittest.main()
