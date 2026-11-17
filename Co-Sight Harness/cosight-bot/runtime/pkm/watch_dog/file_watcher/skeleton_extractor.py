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


def _first_sentence(lines: list[tuple[int, str]], limit: int = 120) -> str:
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
            "first_col_keys": first_col_keys[:100],
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


def _path_semantic_words(rel_path: str) -> str:
    """把 rel_path 转成路径语义词：去 .md 后缀，/、\\、_、- 替换为空格。"""
    if not rel_path:
        return ""
    lowered = rel_path.lower()
    if lowered.endswith(".md"):
        rel_path = rel_path[:-3]
    return re.sub(r"[/\\_\-]+", " ", rel_path).strip()


def structure_embedding_text(
    section: dict,
    *,
    rel_path: str = "",
    tables: list[dict] | None = None,
    bold_keys: list[dict] | None = None,
    max_chars: int = 500,
) -> str:
    """路 1 纯结构语义向量输入：路径词 + 标题链 + 首句 + 表格签名 + 加粗键。

    零长正文混入，总长控制在 80~500 字黄金窗口（max_chars 截断）。
    """
    parts: list[str] = []
    path_words = _path_semantic_words(rel_path)
    if path_words:
        parts.append(path_words)
    header_path = str(section.get("header_path") or "")
    if header_path and header_path != "[Para-Group]":
        parts.append(header_path)
    first_sentence = str(section.get("first_sentence") or "")[:120]
    if first_sentence:
        parts.append(first_sentence)
    for table in (tables or [])[:6]:
        columns = [str(c) for c in (table.get("columns") or []) if str(c).strip()]
        keys = [str(k) for k in (table.get("first_col_keys") or [])[:10] if str(k).strip()]
        if not columns and not keys:
            continue
        chunk = f"Tables: {' | '.join(columns)}" if columns else "Tables:"
        if keys:
            chunk = f"{chunk}; Keys: {', '.join(keys)}"
        parts.append(chunk)
    bold = [str(b.get("key") or "").strip() for b in (bold_keys or [])[:15]]
    bold = [k for k in bold if k]
    if bold:
        parts.append(f"Bold: {', '.join(bold)}")
    return " ".join(parts)[:max_chars]


def contextual_chunk_embedding_text(
    chunk: dict,
    *,
    rel_path: str = "",
    lines: list[str] | None = None,
    max_chars: int = 800,
) -> str:
    """路 3 上下文前缀锚定 Chunk 向量输入：[doc | 标题链] + 表头行 + 正文。

    计算完向量即丢弃该临时拼装文本，nodes_pointer 不存 text 原文列。
    """
    doc_title = Path(rel_path).stem if rel_path else ""
    doc_title = doc_title or rel_path
    header_path = str(chunk.get("header_path") or "")
    table_header = ""
    header_line = int(chunk.get("header_line") or 0)
    start_line = int(chunk.get("start_line") or 0)
    if header_line > 0 and lines and header_line < start_line:
        if 1 <= header_line <= len(lines):
            table_header = lines[header_line - 1]
    prefix = f"[{doc_title or ''} | {header_path}]"
    parts = [prefix]
    if table_header:
        parts.append(table_header)
    parts.append(str(chunk.get("text") or ""))
    return "\n".join(p for p in parts if p)[:max_chars]


def section_embedding_text(section: dict, max_chars: int = 4000) -> str:
    """向后兼容薄包装：转发至 structure_embedding_text（不再混入长正文）。"""
    return structure_embedding_text(section, max_chars=max_chars)


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
                    "lines": list(buf),
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
            # 逐行累积切块：piece 行号精确到单行（block 级行号会让长 block
            # 的所有 chunk 共享同一起止行，破坏路 3 精确行号指针）。
            for line_no, line in block.get("lines", []):
                for piece in _split_long_text(line, chunk_max):
                    text_buf.append({
                        "start_line": line_no,
                        "end_line": line_no,
                        "text": piece,
                    })
                    text_chars += len(piece)
                    if text_chars >= chunk_min or len(piece) >= chunk_max:
                        flush_text()
        flush_text()
        flush_table()
    return chunks
