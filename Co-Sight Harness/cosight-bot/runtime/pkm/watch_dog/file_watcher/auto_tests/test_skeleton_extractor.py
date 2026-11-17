#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skeleton_extractor 单测：章节/表格/加粗键/代码围栏/行号切分。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from watch_dog.file_watcher.skeleton_extractor import (  # noqa: E402
    _first_sentence,
    chunk_sections,
    contextual_chunk_embedding_text,
    extract_skeleton,
    section_embedding_text,
    structure_embedding_text,
)

SAMPLE = """# 总标题

这是引言第一句。引言第二句。

## 1. 概述

概述第一句，介绍背景。

- **根因分析**：这里的值
- **遗留风险**：还有风险

## 2. 表格

| 错误码 | 现象 | 根因 |
|---|---|---|
| ERR_401_01 | 掉线 | A |
| ERR_401_02 | 退回登录页 | B |

## 3. 代码围栏

```python
# 这不是标题
| 这不是表格 |
```

围栏后的正文。
"""


class SkeletonExtractorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "doc.md"
        self.path.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_sections_and_header_path(self) -> None:
        sk = extract_skeleton(self.path)
        titles = [s["title"] for s in sk["sections"]]
        self.assertIn("1. 概述", titles)
        self.assertIn("2. 表格", titles)
        self.assertIn("3. 代码围栏", titles)
        self.assertNotIn("这不是标题", titles)
        sec = next(s for s in sk["sections"] if s["title"] == "1. 概述")
        self.assertEqual(sec["header_path"], "总标题/1. 概述")
        self.assertTrue(sec["first_sentence"].startswith("概述第一句"))
        self.assertGreater(sec["char_count"], 0)
        # 行号是 1-based 且 start <= end
        self.assertLessEqual(sec["start_line"], sec["end_line"])

    def test_table_signature(self) -> None:
        sk = extract_skeleton(self.path)
        self.assertEqual(len(sk["tables"]), 1)
        table = sk["tables"][0]
        self.assertEqual(table["columns"], ["错误码", "现象", "根因"])
        self.assertEqual(table["row_count"], 2)
        self.assertIn("ERR_401_02", table["first_col_keys"])
        self.assertTrue(table["header_line"] <= table["end_line"])

    def test_bold_keys(self) -> None:
        sk = extract_skeleton(self.path)
        keys = {item["key"] for item in sk["bold_keys"]}
        self.assertIn("根因分析", keys)
        self.assertIn("遗留风险", keys)

    def test_chunk_line_ranges_and_table_header_line(self) -> None:
        sk = extract_skeleton(self.path)
        chunks = chunk_sections(sk, chunk_max=500, chunk_min=350)
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertLessEqual(chunk["start_line"], chunk["end_line"])
            self.assertGreaterEqual(chunk["start_line"], 1)
        # 表格至少产生一个 chunk，且 header_line 指向表头行
        table_chunks = [c for c in chunks if c["header_line"] > 0 or "|" in c["text"]]
        self.assertTrue(table_chunks)
        header_line = sk["tables"][0]["header_line"]
        first_table_chunk = next(c for c in chunks if "ERR_401" in c["text"])
        self.assertIn(first_table_chunk["header_line"], (0, header_line))

    def test_section_embedding_text(self) -> None:
        sk = extract_skeleton(self.path)
        sec = next(s for s in sk["sections"] if s["title"] == "1. 概述")
        text = section_embedding_text(sec)
        self.assertIn("1. 概述", text)
        self.assertIn("概述第一句", text)


class StructureEmbeddingTextTest(unittest.TestCase):
    def test_first_sentence_limit_120(self) -> None:
        long_sentence = "字" * 200
        text = _first_sentence([(1, long_sentence)])
        self.assertEqual(len(text), 120)

    def test_first_col_keys_limit_100(self) -> None:
        lines = ["| 键 | 值 |", "|---|---|"]
        for i in range(1, 121):
            lines.append(f"| VND-{i:03d} | x |")
        tables = extract_skeleton_from_lines(lines)
        self.assertEqual(len(tables), 1)
        self.assertEqual(len(tables[0]["first_col_keys"]), 100)
        self.assertIn("VND-100", tables[0]["first_col_keys"])
        self.assertNotIn("VND-101", tables[0]["first_col_keys"])

    def test_structure_embedding_text_components(self) -> None:
        section = {
            "header_path": "1. P0 Escalation Thresholds",
            "first_sentence": "Effective 2026-11-27, mandatory failover steps."[:200],
            # 混入长正文，断言结构向量输入零正文污染
            "lines": [(i, f"第 {i} 行正文填充内容") for i in range(1, 200)],
        }
        tables = [{
            "start_line": 10, "end_line": 60,
            "columns": ["Vendor ID", "Vendor Name", "Status"],
            "first_col_keys": [f"VND-{i:03d}" for i in range(1, 31)],
        }]
        bold_keys = [{"line": 12, "key": "强制切换步骤"}, {"line": 14, "key": "回滚护栏"}]
        text = structure_embedding_text(
            section, rel_path="ops/handoffs/2026-11-27-mariner-health.md",
            tables=tables, bold_keys=bold_keys,
        )
        # 路径语义词（/、_、- 替换为空格，去 .md）
        self.assertIn("ops handoffs 2026 11 27 mariner health", text)
        # 标题链与首句
        self.assertIn("1. P0 Escalation Thresholds", text)
        self.assertIn("mandatory failover steps", text)
        # 表格列名与前 10 个首列键
        self.assertIn("Vendor ID", text)
        self.assertIn("VND-001", text)
        self.assertIn("VND-010", text)
        self.assertNotIn("VND-011", text)
        # 加粗键
        self.assertIn("强制切换步骤", text)
        # 零长正文混入：lines 里的填充正文不得出现
        self.assertNotIn("第 100 行正文填充内容", text)
        self.assertNotIn("第 150 行正文填充内容", text)
        # 黄金窗口上限
        self.assertLessEqual(len(text), 500)

    def test_structure_embedding_text_empty_section(self) -> None:
        text = structure_embedding_text({"header_path": "", "first_sentence": ""})
        self.assertEqual(text, "")

    def test_compat_wrapper_forwards(self) -> None:
        section = {"header_path": "A/B", "first_sentence": "首句内容"}
        self.assertEqual(
            section_embedding_text(section), structure_embedding_text(section)
        )


class ContextualChunkEmbeddingTextTest(unittest.TestCase):
    LINES = [
        "# Doc", "",
        "| Code | Meaning |",
        "|---|---|",
        "| ERR_1 | a |",
        "", "正文段落。",
    ]

    def test_contextual_prefix_and_table_header(self) -> None:
        chunk = {
            "header_path": "1. 表格",
            "header_line": 3,
            "start_line": 5,
            "end_line": 5,
            "text": "| ERR_1 | a |",
        }
        text = contextual_chunk_embedding_text(
            chunk, rel_path="clients/mariner_health/ops.md", lines=self.LINES
        )
        self.assertTrue(text.startswith("[ops | 1. 表格]"))
        self.assertIn("| Code | Meaning |", text)
        self.assertIn("| ERR_1 | a |", text)
        self.assertLessEqual(len(text), 800)

    def test_no_table_header_when_header_line_zero(self) -> None:
        chunk = {"header_path": "1. 表格", "header_line": 0, "start_line": 5, "text": "正文"}
        text = contextual_chunk_embedding_text(chunk, rel_path="a/b.md", lines=self.LINES)
        self.assertTrue(text.startswith("[b | 1. 表格]"))
        self.assertNotIn("| Code | Meaning |", text)
        self.assertIn("正文", text)

    def test_no_table_header_when_header_after_start(self) -> None:
        chunk = {"header_path": "", "header_line": 8, "start_line": 5, "text": "正文"}
        text = contextual_chunk_embedding_text(chunk, rel_path="a.md", lines=self.LINES)
        self.assertNotIn("| Code | Meaning |", text)
        self.assertTrue(text.startswith("[a | ]"))
        self.assertIn("正文", text)


def extract_skeleton_from_lines(lines: list[str]) -> list[dict]:
    from watch_dog.file_watcher import skeleton_extractor as se

    return se.extract_table_signatures(lines)


if __name__ == "__main__":
    unittest.main()
