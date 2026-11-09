#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""6 类静态骨架提取 + 行号游标切分。

输入是预处理后的 pre_dir/*.md 主文档；输出：
- sections：章节树 + 起止行号 + 首句 + 字符数；
- tables：Markdown 表格签名（列名/行数/起止行/首列键）；
- bold_keys：段首/列表加粗键；
- chunks：按自然段/350~500 字切分，保留 (start_line, end_line, header_line)。

设计约束：
- 纯规则、零 LLM；
- 不修改原文、不重排字符串，保证行号可还原；
- 代码围栏内的 # / | / ** 不做结构解析；
- 表格行豁免软折行（由 preprocessor 负责落盘净化）。
"""
from __future__ import annotations

import re
from pathlib import Path

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
_BOLD_KEY_RE = re.compile(r"^\s*(?:[-*+]\s+)?\*\*([^*]{2,25})\*\*\s*[：:]")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s+")


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _is_code_fence(line: str) -> bool:
    return line.strip().startswith("```")


def extract_sections(lines: list[str]) -> list[dict]:
    """按 #~###### 标题切章节；无标题文档生成一个虚拟章节。"""
    sections: list[dict] = []
    stack: list[str] = []
    current: dict | None = None
    in_code = False

    for line_no, line in enumerate(lines, 1):
        if _is_code_fence(line):
            in_code = not in_code
        match = None if in_code else _HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            stack = stack[: level - 1] + [title]
            if current is not None:
                current["end_line"] = max(current["start_line"], line_no - 1)
                sections.append(current)
            current = {
                "level": level,
                "title": title,
                "header_path": "/".join(stack),
                "start_line": line_no,
                "lines": [(line_no, line)],
            }
        else:
            if current is None:
                current = {
                    "level": 0,
                    "title": "[Para-Group]",
                    "header_path": "[Para-Group]",
                    "start_line": line_no,
                    "lines": [],
                }
            current["lines"].append((line_no, line))

    if current is not None:
        current["end_line"] = max(current["start_line"], len(lines))
        sections.append(current)
    if not sections:
        sections.append({
            "level": 0,
            "title": "[Para-Group]",
            "header_path": "[Para-Group]",
            "start_line": 1,
            "end_line": max(1, len(lines)),
            "lines": [(i, line) for i, line in enumerate(lines, 1)],
        })

    for section in sections:
        section["char_count"] = sum(len(text) for _, text in section["lines"])
        section["first_sentence"] = _first_sentence(section["lines"])
    return sections


def _first_sentence(lines: list[tuple[int, str]], limit: int = 60) -> str:
    for idx, (_, text) in enumerate(lines):
        stripped = text.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # 跳过标题行后的空行/列表符号，取第一句正文
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        return stripped[:limit]
    return ""


def extract_table_signatures(lines: list[str]) -> list[dict]:
    """提取连续 Markdown 表格块的签名。"""
    tables: list[dict] = []
    i = 0
    n = len(lines)
    while i < n:
        if not _TABLE_ROW_RE.match(lines[i]):
            i += 1
            continue
        start = i
        block: list[str] = []
        while i < n and _TABLE_ROW_RE.match(lines[i]):
            block.append(lines[i])
            i += 1
        if len(block) < 2:
            continue
        header = block[0]
        if not _TABLE_SEP_RE.match(block[1]):
            continue
        columns = [c.strip() for c in header.strip().strip("|").split("|")]
        rows = block[2:]
        first_col_keys = []
        for row in rows:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if cells and cells[0]:
                first_col_keys.append(cells[0])
        tables.append({
            "start_line": start + 1,
            "end_line": i,
            "header_line": start + 1,
            "columns": columns,
            "row_count": len(rows),
            "first_col_keys": first_col_keys[:20],
        })
    return tables


def extract_bold_keys(lines: list[str]) -> list[dict]:
    keys: list[dict] = []
    in_code = False
    for line_no, line in enumerate(lines, 1):
        if _is_code_fence(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = _BOLD_KEY_RE.match(line)
        if match:
            keys.append({"line": line_no, "key": match.group(1).strip()})
    return keys


def extract_skeleton(path: Path) -> dict:
    lines = read_lines(path)
    return {
        "path": str(path),
        "line_count": len(lines),
        "char_count": sum(len(line) for line in lines),
        "sections": extract_sections(lines),
        "tables": extract_table_signatures(lines),
        "bold_keys": extract_bold_keys(lines),
        "page_anchors": [],  # PPT/扫描页锚点由 ppt_slide_extractor/doc_image_extractor 填充
    }


def section_embedding_text(section: dict, max_chars: int = 4000) -> str:
    """section 向量输入：标题链 + 首句 + 正文（截断）。"""
    body = "\n".join(text for _, text in section.get("lines", []))
    return f'{section.get("header_path", "")}\n{section.get("first_sentence", "")}\n{body[:max_chars]}'


def _split_long_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts = _SENTENCE_SPLIT_RE.split(text)
    out: list[str] = []
    buf = ""
    for part in parts:
        if not part:
            continue
        if len(buf) + len(part) + 1 <= limit:
            buf = f"{buf} {part}".strip()
        else:
            if buf:
                out.append(buf)
            while len(part) > limit:
                out.append(part[:limit])
                part = part[limit:]
            buf = part
    if buf:
        out.append(buf)
    return out or [text[:limit]]


def _blocks_from_section(section: dict) -> list[dict]:
    blocks: list[dict] = []
    buf: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal buf
        if buf:
            text = "\n".join(t for _, t in buf).strip()
            if text:
                blocks.append({
                    "kind": "text",
                    "start_line": buf[0][0],
                    "end_line": buf[-1][0],
                    "text": text,
                })
            buf = []

    for line_no, line in section["lines"]:
        if not line.strip():
            flush()
            continue
        if _TABLE_ROW_RE.match(line):
            flush()
            blocks.append({
                "kind": "table",
                "start_line": line_no,
                "end_line": line_no,
                "text": line,
            })
            continue
        buf.append((line_no, line))
    flush()
    return blocks


def chunk_sections(
    skeleton: dict,
    chunk_max: int = 500,
    chunk_min: int = 350,
    table_max_chars: int = 7000,
    table_max_rows: int = 50,
) -> list[dict]:
    """按 section 切 chunk；行号与表格表头指针可直接回读原文。"""
    chunks: list[dict] = []
    for section_index, section in enumerate(skeleton.get("sections", [])):
        blocks = _blocks_from_section(section)
        text_buf: list[dict] = []
        text_chars = 0
        table_buf: list[dict] = []

        def flush_text() -> None:
            nonlocal text_buf, text_chars
            if not text_buf:
                return
            merged = "\n\n".join(b["text"] for b in text_buf).strip()
            if merged:
                chunks.append({
                    "section_index": section_index,
                    "section_title": section["title"],
                    "header_path": section["header_path"],
                    "start_line": text_buf[0]["start_line"],
                    "end_line": text_buf[-1]["end_line"],
                    "header_line": 0,
                    "text": merged,
                })
            text_buf = []
            text_chars = 0

        def flush_table() -> None:
            nonlocal table_buf
            if not table_buf:
                return
            header_line = table_buf[0]["start_line"]
            for idx in range(0, len(table_buf), table_max_rows):
                part = table_buf[idx: idx + table_max_rows]
                merged = "\n".join(b["text"] for b in part).strip()
                if len(merged) > table_max_chars:
                    merged = merged[:table_max_chars]
                chunks.append({
                    "section_index": section_index,
                    "section_title": section["title"],
                    "header_path": section["header_path"],
                    "start_line": part[0]["start_line"],
                    "end_line": part[-1]["end_line"],
                    "header_line": 0 if idx == 0 else header_line,
                    "text": merged,
                })
            table_buf = []

        for block in blocks:
            if block["kind"] == "table":
                flush_text()
                table_buf.append(block)
                continue
            flush_table()
            for piece in _split_long_text(block["text"], chunk_max):
                text_buf.append({
                    "start_line": block["start_line"],
                    "end_line": block["end_line"],
                    "text": piece,
                })
                text_chars += len(piece)
                if text_chars >= chunk_min or len(piece) >= chunk_max:
                    flush_text()
        flush_text()
        flush_table()
    return chunks
