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
    chunk_sections,
    extract_skeleton,
    section_embedding_text,
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


if __name__ == "__main__":
    unittest.main()
