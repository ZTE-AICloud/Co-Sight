#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
表格感知切分器（table-aware splitter）

背景：
  excel_to_md.py 把 Excel 每个 sheet 渲染成 markdown 表格。经 MarkdownNodeParser
  切成 chapter_node 后，原实现直接用 SentenceSplitter(chunk_size=1024) 按字符
  数再切一刀——表格行从字符中间被切断，产生"残行"（不以 | 开头/结尾的行段），
  且只有第一块带表头。后处理再补表头时，残行归属只能靠启发式猜测，猜错就把
  表格数据甩到表格外面（用户在知识库页面看到"和表格无关的裸文本"）。

  根因：按字符切表格行，行边界信息在切片那一刻就丢了，事后补不回来。

解决：换切分方式，不换修补方式——
  1. 扫描内容里的"连续表格块"（表头行 + |---| 分隔行 + 后续 | 开头的行）；
     先裁掉所有行都为空的尾部列（Excel 宽表按声明维度渲染的空 padding
     防御，真实事故：16K 列宽表表头块 ~148K 打穿字符预算）
  2. 表格块内部按"行"切：累积整行直到接近 chunk_size；每个表格切片开头
     自动拼表头 + 分隔行；单行超过 max_chars_per_chunk 时按预算切成多个
     补表头的片段（整行独占会超 embed 服务端输入上限被 400 拒绝）；表头
     自身超上限时碎片不拼表头（数据优先入库，归属降级）
  3. 表格块之外的普通文本仍走 SentenceSplitter（保持原有的句子边界/重叠行为）
  4. 表格块之前的短文本（≤200 字符，通常是章节标题）并入该表格块的首个切片，
     避免产生只有一行标题的碎片切片

输出保证：
  - 表格切片 = 完整表格行的拼接（首行是表头）；唯一例外是单行超
    max_chars_per_chunk 的巨无霸行，会被切成多个补表头的片段
  - 文本切片 = SentenceSplitter 原行为
  - 不丢数据：所有输入行都会出现在某个切片里

使用方：
  - runtime/common/soc_kb_builder/vector_build/common_processor.py
    （_build_common_index / _insert_source）
  - runtime/watch_dog/file_watcher/handler.py（_parse_md_to_chapter_nodes）

  三处都按 is_excel_md() 判断来源：**只有 Excel 转出的 md 走本切分器**，
  其他文件（PDF/Word/PPT/HTML 等）维持原有 SentenceSplitter 行为不变。
  原因：非 Excel 文档的表格通常列少、单元格短，旧的切分+补表头启发式
  已验证正确；Excel 宽表（如 46 列配置项清单、单元格含整段 license 文本）
  才是旧逻辑崩溃的场景。最小爆炸半径原则——只覆盖出问题的场景。
"""
from __future__ import annotations

import logging
import re
from typing import List

logger = logging.getLogger("common.table_aware_splitter")

# 表格前的短文本（章节标题等）并入表格首个切片的长度上限
_SHORT_PREFIX_MERGE_LIMIT = 200

# 默认单片字符上限。embed 客户端截断线是 EMBED_MAX_INPUT_CHARS（默认 7800，
# 见 watch_dog/file_watcher/embedding_model.py），而 embed 输入 = llama_index
# 拼接的 metadata preamble（file_path/chapter_title 等，~200-400 字符）
# + 切片文本；切片文本 = 表头（不计入行预算）+ 并入的前缀短文本（≤200）
# + 数据行（计入预算）。留 ~800 余量覆盖表头 + 前缀 + metadata，避免切片
# 在 embed 侧被截尾（截掉的是切片尾部的数据行）。
DEFAULT_MAX_CHARS_PER_CHUNK = 7000

# Excel 源 md 的命名后缀（preprocessor 命名规则：f"{stem}_{ext}".replace(".", "_")）
EXCEL_MD_SUFFIXES = ("_xlsx.md", "_xls.md")


def _fallback_char_chunks(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """硬切字符兜底：按 chunk_size 定长切、步长 chunk_size - chunk_overlap。

    不依赖 punkt 分句、零递归——只用于 SentenceSplitter 栈溢出的救命路径，
    放弃句子边界，保证内容进库（数据优先，边界降级）。
    """
    step = max(1, chunk_size - chunk_overlap)
    return [text[i:i + chunk_size] for i in range(0, len(text), step)]


def _safe_sentence_split(splitter, text: str) -> List[str]:
    """SentenceSplitter.split_text 的防栈溢出包装。

    真实事故：某配置指导书 docx 里有一段 Word 乱码
    （同一串 "@;\\_x0019\\_瓿酲椴騙焓藷!" 重复数千次、单行 4.3 万字符）。
    punkt 分句器对这种无标点/无空白的病态文本找不到句子边界，llama_index
    SentenceSplitter._split 逐层递归 + punkt 自身多层调用帧，打穿 CPython
    默认递归上限（1000）抛 RecursionError，整个文件插入失败。
    且 punkt 对这类文本回溯极慢（2MB md 要 51s），提递归上限治标不治本。

    策略：RecursionError 时降级为硬切字符兜底，内容不丢、检索可用。
    """
    try:
        return splitter.split_text(text)
    except RecursionError:
        chunk_size = getattr(splitter, "chunk_size", 1024) or 1024
        chunk_overlap = getattr(splitter, "chunk_overlap", 128) or 0
        logger.warning(
            "table_aware_splitter: SentenceSplitter 递归溢出（文本 %d 字符），"
            "降级为硬切字符兜底（chunk_size=%d, overlap=%d）",
            len(text), chunk_size, chunk_overlap,
        )
        return _fallback_char_chunks(text, chunk_size, chunk_overlap)


def is_excel_md(path_or_name) -> bool:
    """判断预处理产物 .md 是否来自 Excel 源文件（按文件名后缀）。"""
    return str(path_or_name).lower().endswith(EXCEL_MD_SUFFIXES)


def _is_table_row(line: str) -> bool:
    """完整表格行：以 | 开头、以 | 结尾、| 数量 ≥ 3（即至少 2 列）。"""
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 3


def _is_separator_row(line: str) -> bool:
    """markdown 表格分隔行：| --- | --- | ..."""
    return _is_table_row(line) and "---" in line


# 按未转义的 | 拆分 cell（cell 内的 \| 是转义字面值，不是列边界）
_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


def _split_cells(line: str) -> List[str]:
    """把表格行拆成 cell 列表（不含首尾边界空串）。"""
    parts = _CELL_SPLIT_RE.split(line.strip())
    # 完整表格行以 | 开头结尾，split 后首尾必为空串
    return parts[1:-1] if len(parts) >= 2 else parts


def _trim_trailing_empty_cols(run: List[str]) -> List[str]:
    """裁掉整个表格块里"所有行（含表头）都为空"的尾部列。

    背景：Excel 转 md 按声明维度渲染，宽表格式刷到最大列时单行几乎全是
    空 cell padding（真实事故：某超宽端口表 OMM/TMSP sheet 声明 16384
    列、真实列 ~18，单行渲染 ~49K 字符，表头行 + 分隔行合计 ~148K）。
    表头自身超 max_chars_per_chunk 后，巨无霸行切片段时逐片重复表头会把
    每个碎片撑到 ~149K，embed 截断只保留碎片开头（表头），行数据语义全丢。

    只裁尾部全空列：任何一行（表头/数据）在该列有内容就保留，分隔行的
    "---" 不提供内容语义、随内容列对齐裁剪。不丢数据。
    """
    parsed = [_split_cells(ln) for ln in run]
    last_col = 0
    for cells in parsed:
        for ci in range(len(cells) - 1, -1, -1):
            c = cells[ci].strip()
            if c and set(c) != {"-"}:
                last_col = max(last_col, ci + 1)
                break
    if last_col == 0 or all(len(cells) <= last_col for cells in parsed):
        return run
    return [
        "| " + " | ".join(c.strip() for c in cells[:last_col]) + " |"
        if len(cells) > last_col else ln
        for cells, ln in zip(parsed, run)
    ]


def _fragment_oversized_row(row: str, header: List[str], max_chars: int) -> List[str]:
    """把超过字符上限的单个表格行切成若干片段，每片补表头。

    整行独占一块会超出 embed 服务端输入上限（bge 路由对超长输入返回 400，
    且确定性复现），直接硬切是唯一让内容全部进库的办法：
      - 片段 1 保留行首的关键列（告警码/参数名等标识列通常在前面）
      - 每片都拼表头 + 分隔行，归属不丢
      - 预算扣除表头自身长度；表头比上限还宽时不再重复表头（见下）

    表头自身 ≥ max_chars 的守卫：逐片重复表头会让每个碎片都超限（真实事故：
    16K 列宽表表头块 ~148K，保底预算下每个碎片 ≈149K），embed 客户端截断只
    保留碎片开头（表头），行数据一个字都进不了向量。此时归属让位于尺寸约束——
    碎片不拼表头、按 max_chars 满预算切，保证行数据完整进入 embedding。
    """
    if header:
        header_len = sum(len(h) + 1 for h in header)
        if header_len >= max_chars:
            logger.warning(
                f"table_aware_splitter: 表头块 {header_len} 字符 ≥ 单片上限 {max_chars}，"
                f"巨无霸行（{len(row)} 字符）切片段时不拼表头（数据优先入库，归属降级）"
            )
            header = []
    header_len = sum(len(h) + 1 for h in header)
    budget = max(1000, max_chars - header_len)
    frags: List[str] = []
    for start in range(0, len(row), budget):
        frag = row[start:start + budget]
        frags.append("\n".join(header + [frag]) if header else frag)
    return frags


def split_table_aware(
    content: str,
    chunk_size: int = 1024,
    chunk_overlap: int = 128,
    *,
    target_rows_per_chunk: int = 50,
    max_chars_per_chunk: int = DEFAULT_MAX_CHARS_PER_CHUNK,
) -> List[str]:
    """把一段 markdown 内容切成若干切片，表格按行切、文本按 SentenceSplitter 切。

    Args:
        content: chapter_node 的正文（已去 \r 与否均可，函数内会再清一次）
        chunk_size: 文本切片的目标大小（字符数），透传给 SentenceSplitter。
            不约束表格切片大小。
        chunk_overlap: 文本切片的重叠字符数（透传给 SentenceSplitter）。
            表格切片不做重叠——重叠会在相邻切片里复制同一行数据，对检索和展示
            都是负担。
        target_rows_per_chunk: 表格切片的目标行数（不含表头）。累积到
            len(cur) >= target_rows_per_chunk 时开下一个切片。
        max_chars_per_chunk: 表格切片字符数上限（含数据行，不含表头）。
            "再加下一行就超过"时提前开切片，避免单切片过大撑爆 embed 模型。
            单行自身超过 max_chars_per_chunk 时按字符预算切成若干片段、每片
            补表头（_fragment_oversized_row）——整行独占会超出 embed 服务端
            输入上限被 400 拒绝（真实事故：告警手册单行 1.1 万字符），
            切片段后内容不丢、归属不丢，仅片段 2+ 不再是完整 markdown 行。

    Returns:
        切片文本列表，保持原始内容顺序（文本块与表格块交替出现时按出现顺序输出）。
    """
    from llama_index.core.node_parser import SentenceSplitter

    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    content = content.replace("\r", "")
    lines = content.split("\n")
    chunks: List[str] = []
    text_buf: List[str] = []

    def _flush_text() -> None:
        text = "\n".join(text_buf).strip()
        text_buf.clear()
        if text:
            chunks.extend(_safe_sentence_split(splitter, text))

    i, n = 0, len(lines)
    while i < n:
        if not _is_table_row(lines[i]):
            text_buf.append(lines[i])
            i += 1
            continue

        # 收集连续表格行 run
        j = i
        while j < n and _is_table_row(lines[j]):
            j += 1
        run = [ln.strip() for ln in lines[i:j]]
        i = j

        # 裁掉所有行都为空的尾部列（Excel 宽表空 padding 场景，见函数 docstring）
        run = _trim_trailing_empty_cols(run)

        # 表头识别：run 前两行是 表头行 + 分隔行 才算有表头
        if len(run) >= 2 and _is_separator_row(run[1]):
            header, data = run[:2], run[2:]
        else:
            header, data = [], run

        # 表格块之前的缓冲文本：短的并入首个表格切片（通常是章节标题），
        # 长的按普通文本切块
        prefix = ""
        pending = "\n".join(text_buf).strip()
        text_buf.clear()
        if pending:
            if len(pending) <= _SHORT_PREFIX_MERGE_LIMIT:
                prefix = pending
            else:
                chunks.extend(_safe_sentence_split(splitter, pending))

        # 按行切块（绝不从行中间断）
        # 双重预算：行数（target_rows_per_chunk）+ 字符数（max_chars_per_chunk）。
        # 任一达到上限即开下一个切片：
        #   - 行数到目标 → 切，避免超长表切出几百个 1 行小切片
        #   - 字符数将爆 → 切，避免单切片过大撑爆 embed 模型
        # 表头不计入预算——宽表（如 46 列配置项清单）表头自身就可能超过
        # max_chars_per_chunk，计入会导致每块只能塞 1 行数据。
        block: List[str] = []
        cur: List[str] = []
        cur_len = 0
        for row in data:
            row_len = len(row) + 1
            if row_len > max_chars_per_chunk:
                # 单行超上限：先 flush 当前累积，再把该行切成若干补表头的片段。
                # 不整行独占——超出 embed 服务端输入上限会被 400 拒绝。
                if cur:
                    block.append("\n".join(header + cur))
                    cur = []
                    cur_len = 0
                block.extend(_fragment_oversized_row(row, header, max_chars_per_chunk))
                continue
            # 行数到上限 或 再加这行就超字符上限 → 开新切片
            if cur and (
                len(cur) >= target_rows_per_chunk
                or cur_len + row_len > max_chars_per_chunk
            ):
                block.append("\n".join(header + cur))
                cur = []
                cur_len = 0
            cur.append(row)
            cur_len += row_len
        if cur:
            block.append("\n".join(header + cur))
        elif header and not data:
            # 只有表头没有数据行的表格：表头自身成一个切片。
            # 注意不能只看 cur 为空——巨无霸行走 _fragment_oversized_row 分支后
            # cur 也是空的，再补一个 header-only 切片就是纯噪音。
            block.append("\n".join(header))

        if prefix and block:
            block[0] = prefix + "\n\n" + block[0]
        chunks.extend(block)

    _flush_text()
    return [c for c in chunks if c.strip()]
