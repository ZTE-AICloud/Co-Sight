#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T5 / JEV-A1：枚举与收集题 ``scan`` 候选批量 Noul 口径预筛（``filter-hits``）。

只读子命令：把主 Agent ``scan`` 捞出的数十至上百条关键词命中回溯扩展为所在
Markdown 小节整段上下文（含自动补齐表格表头，上限 1,200 字），按 55,000 字符
预算拆批并发调用内网 JEV 执行双路原子 ``Noul``（``in_scope`` +
``is_draft_or_template``），按内网二值极化阈值三桶分流：``confirmed_docs`` /
``grey_docs`` / ``dropped_noise``。

严守红线：
- "JEV 判归属，代码做加法"：本命令只做候选预筛，绝不输出枚举总数答案；
  ``confirmed_docs + grey_docs`` 必须交主 Agent ``read-doc`` 实读（S-03）确认
  后由 Python 脚本精确求和，严禁直接把 ``confirmed_count`` 当答案数字。
- 内网二值极化阈值：``p_in < 0.005`` 才丢弃、``>= 0.90`` 才确认，中间带一律
  归 ``grey_docs`` 保守保留；草稿/模板判为真的高相关候选绝不静默丢弃。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from common import jev_client
from common.jev_questions import (
    A1_QUESTION_SET_VERSION as QUESTION_SET_VERSION,
    A1_THRESHOLDS,
)
from common.logging_setup import log_event

logger = logging.getLogger("jev_filter_hits")

PAYLOAD_CHAR_BUDGET = 55_000
MAX_ITEMS_PER_BATCH = 25
# 默认单批 1 条（2 个原子 Noul），彻底消除服务端 state × question_count 跨条目交叉乘积放大，
# 单请求耗时 < 800ms，60 条候选 ~7s 完成；可通过 COSIGHTBOT_JEV_A1_BATCH_ITEMS 调整（<= 25）。
DEFAULT_ITEMS_PER_BATCH = 1
SECTION_CHAR_CAP = 1_200
JEV_MAX_WORKERS = 6
_PER_ITEM_QUESTION_CHARS = 720

SCAN_TRUNCATED_WARNING = (
    "警告：输入的 scan 结果仍处于 truncated=true 未翻完页状态！"
    "严禁据此得出全库枚举总数，请先用 --offset 拉取剩余页后再合并预筛。"
)

ALL_DROPPED_WARNING = (
    "警告：全部候选被 JEV 判为噪声（all_dropped），已按 p_in_scope 降序抽回前 5 篇至 "
    "grey_docs；请抽查这几篇确认 --include-rule 是否写得过窄，"
    "绝不允许据此直接得出零命中结论！"
)

NEXT_STEP_HINT = (
    "请对 confirmed_docs 与 grey_docs 逐篇执行 read-doc 实读核实归属（S-03），"
    "最终枚举条目与总数必须由 Python 脚本精确统计输出，"
    "严禁直接使用 confirmed_count 作为答案数字！"
)


# ---------------------------------------------------------------------------
# 多形态 --scan-json 兼容解析与去重
# ---------------------------------------------------------------------------


def _is_scan_page(obj: object) -> bool:
    """是否为单页 cmd_scan 标准输出对象（含 hits 数组）。"""
    return isinstance(obj, dict) and isinstance(obj.get("hits"), list)


def _dedupe_hits(hits: list) -> list[dict]:
    """按 (node_id, route_label, rel_path) 顺序去重，合并同一文档多页 snippets。"""
    merged: dict[tuple, dict] = {}
    order: list[tuple] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        key = (
            str(hit.get("node_id") or ""),
            str(hit.get("route_label") or ""),
            str(hit.get("rel_path") or ""),
        )
        if key not in merged:
            entry = dict(hit)
            entry["snippets"] = [
                dict(s) for s in (hit.get("snippets") or []) if isinstance(s, dict)
            ]
            entry["term_hits"] = dict(hit.get("term_hits") or {})
            merged[key] = entry
            order.append(key)
            continue
        entry = merged[key]
        seen = {
            (s.get("line_no"), s.get("term"), s.get("text"))
            for s in entry["snippets"]
        }
        for s in hit.get("snippets") or []:
            if not isinstance(s, dict):
                continue
            sig = (s.get("line_no"), s.get("term"), s.get("text"))
            if sig not in seen:
                seen.add(sig)
                entry["snippets"].append(dict(s))
        for term, count in (hit.get("term_hits") or {}).items():
            entry["term_hits"][term] = int(entry["term_hits"].get(term) or 0) + int(count or 0)
    result: list[dict] = []
    for key in order:
        entry = merged[key]
        entry["snippets"].sort(
            key=lambda s: (s.get("line_no") if isinstance(s.get("line_no"), int) else 0,
                           str(s.get("term") or ""))
        )
        result.append(entry)
    return result


def load_scan_hits(scan_json_path: Path) -> tuple[list[dict], bool]:
    """解析多形态 --scan-json 输入，返回 (去重后的 hits, scan_truncated_warning)。

    兼容 4 种合法输入：
    1. 单页 cmd_scan 标准 JSON 对象：``{"ok": true, "truncated": false, "hits": [...]}``；
    2. 多页 cmd_scan 对象组成的 JSON 数组；
    3. JSON Lines（每行一个 cmd_scan JSON 对象，如多次 ``scan >> scan_all.jsonl`` 追加）；
    4. 纯 hits 数组。

    截断告警：最后一个 cmd_scan 分页对象 ``truncated == True`` 或
    ``hits_remaining > 0`` 时返回 ``scan_truncated_warning = True``（防漏数护栏）。
    非法输入抛 ValueError。
    """
    raw = Path(scan_json_path).read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError("文件内容为空")

    pages: list[dict] = []
    plain_hits: list[dict] = []
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        if _is_scan_page(parsed):
            pages = [parsed]
        else:
            raise ValueError("顶层 JSON 对象缺少 hits 数组，不是合法的 scan 输出")
    elif isinstance(parsed, list):
        if any(_is_scan_page(x) for x in parsed):
            pages = [x for x in parsed if _is_scan_page(x)]
        else:
            plain_hits = [x for x in parsed if isinstance(x, dict)]
            if not plain_hits:
                raise ValueError("JSON 数组中没有任何合法的 hit 或 scan 分页对象")
    else:
        # JSON Lines：整体解析失败时逐行解析（每行一个 cmd_scan JSON 对象）
        for line_no, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"第 {line_no} 行不是合法 JSON: {exc}") from exc
            if _is_scan_page(obj):
                pages.append(obj)
            elif isinstance(obj, dict):
                plain_hits.append(obj)
            else:
                raise ValueError(f"第 {line_no} 行不是 JSON 对象")
        if not pages and not plain_hits:
            raise ValueError("JSON Lines 中没有任何合法对象")

    truncated_warning = False
    hits: list = []
    if pages:
        for page in pages:
            hits.extend(h for h in (page.get("hits") or []) if isinstance(h, dict))
        last = pages[-1]
        if bool(last.get("truncated")) or int(last.get("hits_remaining") or 0) > 0:
            truncated_warning = True
    else:
        hits = plain_hits
    return _dedupe_hits(hits), truncated_warning


# ---------------------------------------------------------------------------
# 命中行回溯扩展：所在小节整段上下文 + 表格表头自动补齐（上限 1,200 字）
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+")


def _clip_by_lines(lines: list[str], cap: int) -> str:
    """按整行对齐截断到 cap 字符以内（不在单词或单元格中间硬劈）。"""
    out: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + 1
        if out and used + cost > cap:
            break
        out.append(line)
        used += cost
    return "\n".join(out)


def _build_section_table(lines: list[str]) -> list[dict]:
    """扫描标题行建立章节区间表（1-based，与 cmd_scan snippet line_no 一致）。

    每项：{level, title, start, end, header_path}；首个标题前的导言区（或
    无标题全文）作为一个 header_path 为空的虚拟小节。
    """
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []
    first_heading = None
    for i, line in enumerate(lines):
        if _HEADING_RE.match(line):
            first_heading = i
            break
    if first_heading is None:
        if lines:
            sections.append({"level": 0, "title": "", "start": 1, "end": len(lines), "header_path": ""})
        return sections
    if first_heading > 0:
        sections.append({"level": 0, "title": "", "start": 1, "end": first_heading, "header_path": ""})
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        title = line[m.end():].strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        if sections:
            sections[-1]["end"] = i  # 上一小节结束于本标题前一行的 1-based 行号
        sections.append({
            "level": level,
            "title": title,
            "start": i + 1,
            "end": len(lines),
            "header_path": " > ".join(t for _lv, t in stack),
        })
    return sections


def _section_for_line(sections: list[dict], line_no: int) -> dict | None:
    for sec in sections:
        if sec["start"] <= line_no <= sec["end"]:
            return sec
    return None


def _is_table_separator(line: str) -> bool:
    s = line.strip()
    return bool(s) and "|" in s and "-" in s and set(s) <= set("|-: ")


def _table_header_block(lines: list[str], hit_line_nos: list[int]) -> tuple[str, int]:
    """命中行处于 Markdown 表格数据行时，回溯表格顶部 2 行（表头 + 分隔行）。

    返回 (前置表头文本, 表头顶部行号 1-based)；非表格命中返回 ("", 0)。
    让 JEV 面对第 180 行的 ``| VND-108 | Cobalt | Tier-1 | Active |`` 时仍能
    100% 看到列名语义。
    """
    for line_no in sorted(set(hit_line_nos)):
        idx = line_no - 1
        if idx < 0 or idx >= len(lines):
            continue
        if not lines[idx].lstrip().startswith("|"):
            continue
        top = idx
        while top > 0 and lines[top - 1].lstrip().startswith("|"):
            top -= 1
        rows = [lines[top]]
        if top + 1 < len(lines) and _is_table_separator(lines[top + 1]):
            rows.append(lines[top + 1])
        return ("\n".join(rows) + "\n", top + 1)
    return ("", 0)


def _window_around_hits(
    sec_lines: list[str],
    sec_hit_lines: list[int],
    sec_start: int,
    budget: int,
) -> dict[int, str]:
    """围绕命中行展开连续正文窗口（按整行对齐），返回 {绝对行号: 行文本}。

    命中行按间距 <=2 合并成簇，每簇以中间命中行为中心向上下交替扩展，
    各簇均分字符预算；全部命中行强制保留。
    """
    if budget <= 0 or not sec_lines:
        return {}
    hits = sorted(set(sec_hit_lines))
    clusters: list[list[int]] = []
    for ln in hits:
        if clusters and ln - clusters[-1][-1] <= 2:
            clusters[-1].append(ln)
        else:
            clusters.append([ln])
    per = max(40, budget // len(clusters))
    chosen: dict[int, str] = {}
    for cluster in clusters:
        center = cluster[len(cluster) // 2]
        ci = min(max(center - sec_start, 0), len(sec_lines) - 1)
        lo = hi = ci
        used = len(sec_lines[ci]) + 1
        while True:
            grown = False
            if lo > 0 and used + len(sec_lines[lo - 1]) + 1 <= per:
                lo -= 1
                used += len(sec_lines[lo]) + 1
                grown = True
            if hi < len(sec_lines) - 1 and used + len(sec_lines[hi + 1]) + 1 <= per:
                hi += 1
                used += len(sec_lines[hi]) + 1
                grown = True
            if not grown:
                break
        for j in range(lo, hi + 1):
            chosen[sec_start + j] = sec_lines[j]
        # 全部命中行强制保留（即便该行自身超预算）
        for ln in cluster:
            j = ln - sec_start
            if 0 <= j < len(sec_lines):
                chosen[ln] = sec_lines[j]
    return chosen


def expand_hit_section_context(
    hit: dict,
    checked_routes: list[dict],
    global_node_index: dict,
) -> dict:
    """把单条 scan 命中回溯扩展为所在小节整段上下文（含表头补齐，<= 1,200 字）。

    绝对禁止直接拿 scan JSON 里仅含前后 1 行的 snippets 送 JEV。

    Returns:
        dict: {node_id, rel_path, route_label, header_path, section_line_range,
               section_text, context_source}（context_source: section | snippet_fallback）
    """
    from common import overview_resolver as _ovr

    node_id = str(hit.get("node_id") or "")
    rel_path = str(hit.get("rel_path") or "")
    route_label = str(hit.get("route_label") or "")
    snippets = [s for s in (hit.get("snippets") or []) if isinstance(s, dict)]

    abs_path: Path | None = None
    resolved_node_id = node_id
    if node_id:
        gid = _ovr._lookup_global_id(global_node_index, node_id)
        if gid:
            entry = global_node_index[gid]
            abs_path = Path(entry["pre_dir"]) / entry["rel_path"]
            rel_path = entry["rel_path"]
            route_label = str(entry.get("route_label") or route_label)
            resolved_node_id = gid
    if abs_path is None and route_label:
        route = next(
            (r for r in checked_routes if str(r.get("label") or "") == route_label),
            None,
        )
        if route is not None and rel_path:
            abs_path = Path(route["pre_dir"]) / rel_path

    hit_line_nos: list[int] = []
    for s in snippets:
        ln = s.get("line_no") if s.get("line_no") is not None else s.get("line")
        try:
            ln_i = int(ln)
        except (TypeError, ValueError):
            continue
        if ln_i >= 1:
            hit_line_nos.append(ln_i)
    if not hit_line_nos:
        hit_line_nos = [1]

    lines: list[str] = []
    if abs_path is not None:
        try:
            lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []

    if not lines:
        # 源文件不存在/不可读：回退拼接 snippets，绝不静默丢弃候选
        fallback_text = "\n".join(str(s.get("text") or "") for s in snippets).strip("\n")
        if not fallback_text:
            fallback_text = f"(源文件不可读: {rel_path})"
        fallback_text = _clip_by_lines(fallback_text.splitlines(), SECTION_CHAR_CAP)
        return {
            "node_id": resolved_node_id,
            "rel_path": rel_path,
            "route_label": route_label,
            "header_path": "",
            "section_line_range": f"{min(hit_line_nos)}:{max(hit_line_nos)}",
            "section_text": fallback_text,
            "context_source": "snippet_fallback",
        }

    hit_line_nos = [min(max(ln, 1), len(lines)) for ln in hit_line_nos]
    sections = _build_section_table(lines)
    owned: list[dict] = []
    for ln in hit_line_nos:
        sec = _section_for_line(sections, ln)
        if sec is not None and sec not in owned:
            owned.append(sec)
    if not owned:
        owned = [{"level": 0, "title": "", "start": 1, "end": len(lines), "header_path": ""}]
    owned = owned[:2]  # 最多取 2 个不重叠小节

    base = {
        "node_id": resolved_node_id,
        "rel_path": rel_path,
        "route_label": route_label,
    }

    # 单小节且全文（含定位前缀）不超预算：100% 完整保留整节文本
    if len(owned) == 1:
        sec = owned[0]
        prefix = f"[章节路径: {sec['header_path']}]\n" if sec["header_path"] else ""
        text = "\n".join(lines[sec["start"] - 1: sec["end"]])
        if len(prefix) + len(text) <= SECTION_CHAR_CAP:
            return {
                **base,
                "header_path": sec["header_path"],
                "section_line_range": f"{sec['start']}:{sec['end']}",
                "section_text": prefix + text,
                "context_source": "section",
            }

    # 超长小节：拼 [章节路径] + 表格表头(若有) + 围绕命中行的连续正文窗口
    header_block, header_top = _table_header_block(lines, hit_line_nos)
    per_budget = max(200, (SECTION_CHAR_CAP - len(header_block)) // len(owned))
    blocks: list[str] = []
    all_window_lines: set[int] = set()
    for sec in owned:
        sec_hit = [ln for ln in hit_line_nos if sec["start"] <= ln <= sec["end"]]
        if not sec_hit:
            sec_hit = [sec["start"]]
        prefix = f"[章节路径: {sec['header_path']}]\n" if sec["header_path"] else ""
        chosen = _window_around_hits(
            lines[sec["start"] - 1: sec["end"]], sec_hit, sec["start"], per_budget - len(prefix)
        )
        if not chosen:
            fallback_lines = lines[sec["start"] - 1: sec["start"] - 1 + max(1, per_budget // 40)]
            chosen = {sec["start"] + j: t for j, t in enumerate(fallback_lines)}
        all_window_lines.update(chosen)
        window_text = "\n".join(text for _ln, text in sorted(chosen.items()))
        blocks.append((prefix + window_text).strip("\n"))

    text = "\n...\n".join(blocks)
    # 表格被窗口截断时把表头两行前置固定在摘录块顶部
    if header_block and header_top and header_top not in all_window_lines:
        text = header_block + text
    text = _clip_by_lines(text.splitlines(), SECTION_CHAR_CAP)
    win_start = min(all_window_lines) if all_window_lines else 1
    win_end = max(all_window_lines) if all_window_lines else len(lines)
    header_path = owned[0]["header_path"]
    return {
        **base,
        "header_path": header_path,
        "section_line_range": f"{win_start}:{win_end}",
        "section_text": text,
        "context_source": "section",
    }


# ---------------------------------------------------------------------------
# 分批内网 JEV 双路 Noul 判别与三桶分流
# ---------------------------------------------------------------------------


def _item_payload_chars(item: dict) -> int:
    return len(json.dumps(item, ensure_ascii=False))


def _split_by_count(batches: list[list], max_items: int) -> list[list]:
    """在 plan_batches 字符预算结果之上再施加单批条数上限（保持顺序）。"""
    final: list[list] = []
    for batch in batches:
        for start in range(0, len(batch), max_items):
            final.append(batch[start:start + max_items])
    return final


def _items_per_batch() -> int:
    """单批最大条目数（默认 1，受硬上限 MAX_ITEMS_PER_BATCH=25 约束）。"""
    raw = (os.environ.get("COSIGHTBOT_JEV_A1_BATCH_ITEMS") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_ITEMS_PER_BATCH
    except ValueError:
        value = DEFAULT_ITEMS_PER_BATCH
    return max(1, min(value, MAX_ITEMS_PER_BATCH))


def _plan_item_batches(items: list[dict], base_state: dict) -> list[list[dict]]:
    """按 55,000 字符预算（含 base_state + 双 Noul 问题开销）与单批条数上限自动切批。"""
    base_chars = len(json.dumps(base_state, ensure_ascii=False))
    effective_budget = max(2_000, PAYLOAD_CHAR_BUDGET - base_chars)
    return _split_by_count(
        jev_client.plan_batches(
            items,
            budget_chars=effective_budget,
            per_item_chars=_item_payload_chars,
            per_item_question_chars=_PER_ITEM_QUESTION_CHARS,
        ),
        _items_per_batch(),
    )


def _build_batch_pair(items_in_batch: list[dict], base_state: dict) -> tuple[dict, dict]:
    """构造单批 (state, questions)：每条候选并行 2 个原子 Noul。

    问题字典键使用全局唯一 ``idx``（跨批合并零碰撞），
    而 ``instructions`` 严格引用本批局部数组位置 ``items[{pos}]``（防第 2+ 批越界）。
    """
    state = dict(base_state)
    state["items"] = [
        {
            "idx": it["idx"],
            "node_id": it["node_id"],
            "rel_path": it["rel_path"],
            "header_path": it["header_path"],
            "section_line_range": it["section_line_range"],
            "section_text": it["section_text"],
        }
        for it in items_in_batch
    ]
    questions: dict = {}
    for pos, it in enumerate(items_in_batch):
        i = it["idx"]
        nid = it["node_id"]
        questions[f"in_scope_{i}"] = {
            "type": "noul",
            "instructions": (
                f"`items[{pos}]`（node_id={nid}, idx={i}）的章节正文是否包含"
                "符合 `include_rule` 纳入标准的候选记录或直接事实依据"
                "（而非属于 `exclude_rule` 排除范围或仅关键词表面重名擦边）？"
            ),
            "criteria": {
                "true": "包含符合 include_rule 的有效候选记录或直接依据",
                "false": "明确属于 exclude_rule 排除情形，或仅出现检索词但内容与目标统计对象无关",
            },
        }
        questions[f"is_draft_or_template_{i}"] = {
            "type": "noul",
            "instructions": (
                f"`items[{pos}]`（node_id={nid}, idx={i}）所在段落是否属于"
                "尚未批准生效的草案（Draft/RFC/Proposal）、空白模板示例占位符"
                "（Template/Sample/Illustrative），或已被正文显式声明作废"
                "（Deprecated/Superseded/Expired）的历史旧记录？"
            ),
            "criteria": {
                "true": "是未生效草案、空白模板示例或已显式作废记录",
                "false": "是正式有效记录或状态未声明作废",
            },
        }
    return state, questions


def _candidate_record(item: dict, p_in: float | None, p_draft: float | None) -> dict:
    return {
        "node_id": item["node_id"],
        "rel_path": item["rel_path"],
        "header_path": item["header_path"],
        "section_line_range": item["section_line_range"],
        "p_in_scope": p_in,
        "p_is_draft": p_draft,
    }


def route_buckets(
    items: list[dict],
    answers: dict,
) -> tuple[list[dict], list[dict], list[dict]]:
    """按内网二值极化阈值做确定性三桶分流。

    - confirmed: p_in >= 0.90 且（p_draft 缺失或 < 0.92）
    - dropped:   p_in < 0.005
    - grey:      其余全部情况（含 p_in 缺失态 None、中间带、疑似草稿）
      草稿混合保护：p_in >= 0.90 但 p_draft >= 0.92 的疑似草稿/作废项进 grey
      （标 suspected_draft_or_superseded）而非静默丢进 dropped——防误杀
      "题面恰好问历史提案"或"大表里既有 Expired 行又有 Active 行"的真金标。
    """
    confirmed: list[dict] = []
    grey: list[dict] = []
    dropped: list[dict] = []
    for item in items:
        i = item["idx"]
        p_in = jev_client.probability(answers.get(f"in_scope_{i}"))
        p_draft = jev_client.probability(answers.get(f"is_draft_or_template_{i}"))
        rec = _candidate_record(item, p_in, p_draft)
        if (
            p_in is not None
            and p_in >= A1_THRESHOLDS["keep_in_scope_min"]
            and (p_draft is None or p_draft < A1_THRESHOLDS["draft_flag_min"])
        ):
            confirmed.append(rec)
        elif p_in is not None and p_in < A1_THRESHOLDS["drop_in_scope_max"]:
            dropped.append(rec)
        else:
            rec["grey_reason"] = (
                "suspected_draft_or_superseded"
                if (
                    p_in is not None
                    and p_in >= A1_THRESHOLDS["keep_in_scope_min"]
                    and p_draft is not None
                    and p_draft >= A1_THRESHOLDS["draft_flag_min"]
                )
                else "uncertain_band"
            )
            grey.append(rec)
    return confirmed, grey, dropped


def apply_all_dropped_safety_valve(
    confirmed: list[dict],
    grey: list[dict],
    dropped: list[dict],
) -> tuple[list[dict], list[dict], list[dict], bool]:
    """全灭异常安全阀：绝不允许 JEV 单独制造静默零命中结论。

    全部落入 dropped_noise 时按 p_in 降序抽回前 min(5, N) 篇至 grey_docs。
    """
    if not dropped or confirmed or grey:
        return confirmed, grey, dropped, False
    rescued = sorted(
        dropped,
        key=lambda r: (r["p_in_scope"] if r["p_in_scope"] is not None else 0.0),
        reverse=True,
    )[: min(5, len(dropped))]
    rescued_ids = {id(r) for r in rescued}
    grey = [dict(r, grey_reason="all_dropped_safety_guard") for r in rescued]
    dropped = [r for r in dropped if id(r) not in rescued_ids]
    return confirmed, grey, dropped, True


def _degraded_result(
    items: list[dict],
    scan_truncated_warning: bool,
    diag: dict,
    started_ms: float,
) -> dict:
    """有痕软降级：全部候选原样放入 grey_docs，退回标准手工核查不报错卡死。"""
    grey = [dict(_candidate_record(it, None, None), grey_reason="jev_degraded") for it in items]
    hint = (SCAN_TRUNCATED_WARNING + " " if scan_truncated_warning else "") + NEXT_STEP_HINT
    return {
        "ok": True,
        "total_input_docs": len(items),
        "confirmed_count": 0,
        "grey_count": len(grey),
        "dropped_noise_count": 0,
        "scan_truncated_warning": scan_truncated_warning,
        "all_dropped_warning": False,
        "jev_degraded": True,
        "confirmed_docs": [],
        "grey_docs": grey,
        "dropped_noise_ids": [],
        "audit": {
            "stage": "A1",
            "question_set_version": QUESTION_SET_VERSION,
            "thresholds": dict(A1_THRESHOLDS),
            "jev": diag,
            "duration_ms": round((time.monotonic() - started_ms) * 1000.0, 1),
        },
        "next_step_hint": hint,
    }


def cmd_filter_hits(args, checked: list[dict]) -> int:
    """filter-hits 子命令入口。checked 为 collect_routes + check_route_ready 结果。"""
    started = time.monotonic()
    question = (getattr(args, "question", "") or "").strip()
    include_rule = (getattr(args, "include_rule", "") or "").strip()
    exclude_rule = (getattr(args, "exclude_rule", "") or "").strip()
    scan_json = (getattr(args, "scan_json", "") or "").strip()

    missing = [
        name
        for name, val in (
            ("--question", question),
            ("--include-rule", include_rule),
            ("--scan-json", scan_json),
        )
        if not val
    ]
    if missing:
        print(json.dumps(
            {"ok": False, "error": f"缺少必填参数: {', '.join(missing)}"},
            ensure_ascii=False,
        ))
        return 1
    scan_path = Path(scan_json)
    if not scan_path.is_file():
        print(json.dumps(
            {"ok": False, "error": f"--scan-json 文件不存在: {scan_json}"},
            ensure_ascii=False,
        ))
        return 1
    try:
        hits, scan_truncated_warning = load_scan_hits(scan_path)
    except (OSError, ValueError) as exc:
        print(json.dumps(
            {"ok": False, "error": f"--scan-json 解析失败: {exc}"},
            ensure_ascii=False,
        ))
        return 1

    from common import overview_resolver as _ovr
    global_node_index, _ = _ovr._build_global_node_index(checked)

    items: list[dict] = []
    for i, hit in enumerate(hits):
        ctx = expand_hit_section_context(hit, checked, global_node_index)
        items.append({
            "idx": i,
            "node_id": str(ctx.get("node_id") or ""),
            "rel_path": str(ctx.get("rel_path") or ""),
            "header_path": str(ctx.get("header_path") or ""),
            "section_line_range": str(ctx.get("section_line_range") or ""),
            "section_text": str(ctx.get("section_text") or ""),
            "context_source": str(ctx.get("context_source") or ""),
        })

    base_state = {
        "question": question,
        "include_rule": include_rule,
        "exclude_rule": exclude_rule or "与目标问题无关、仅词面擦边或不属于目标统计口径的记录",
    }

    # 有痕软降级：A1 阶段开关关闭时不发起 JEV 请求
    if not jev_client.is_stage_enabled("A1"):
        result = _degraded_result(
            items, scan_truncated_warning,
            {"degraded": True, "stage": "A1", "error": "stage A1 disabled by COSIGHTBOT_JEV_STAGES"},
            started,
        )
        log_event(
            logger, "filter_hits:done",
            total_input=len(items), confirmed=0, grey=len(items), dropped=0,
            jev_degraded=True, truncated_warning=scan_truncated_warning,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if not items:
        result = {
            "ok": True,
            "total_input_docs": 0,
            "confirmed_count": 0,
            "grey_count": 0,
            "dropped_noise_count": 0,
            "scan_truncated_warning": scan_truncated_warning,
            "all_dropped_warning": False,
            "jev_degraded": False,
            "confirmed_docs": [],
            "grey_docs": [],
            "dropped_noise_ids": [],
            "audit": {
                "stage": "A1",
                "question_set_version": QUESTION_SET_VERSION,
                "thresholds": dict(A1_THRESHOLDS),
                "duration_ms": round((time.monotonic() - started) * 1000.0, 1),
            },
            "next_step_hint": NEXT_STEP_HINT,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    batches = _plan_item_batches(items, base_state)
    batch_pairs = [_build_batch_pair(batch, base_state) for batch in batches]
    try:
        jev = jev_client.ask_batches_concurrent(
            batch_pairs,
            stage="A1",
            question_set_version=QUESTION_SET_VERSION,
            max_workers=JEV_MAX_WORKERS,
        )
    except jev_client.JevUnavailable as exc:
        result = _degraded_result(
            items, scan_truncated_warning, jev_client.build_degraded_diag("A1", exc), started
        )
        log_event(
            logger, "filter_hits:done", level=logging.WARNING,
            total_input=len(items), confirmed=0, grey=len(items), dropped=0,
            jev_degraded=True, error=str(exc),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    confirmed, grey, dropped = route_buckets(items, jev.answers)
    confirmed, grey, dropped, all_dropped_warning = apply_all_dropped_safety_valve(
        confirmed, grey, dropped
    )

    hint = NEXT_STEP_HINT
    if all_dropped_warning:
        hint = ALL_DROPPED_WARNING + " " + hint
    if scan_truncated_warning:
        hint = SCAN_TRUNCATED_WARNING + " " + hint

    result = {
        "ok": True,
        "total_input_docs": len(items),
        "confirmed_count": len(confirmed),
        "grey_count": len(grey),
        "dropped_noise_count": len(dropped),
        "scan_truncated_warning": scan_truncated_warning,
        "all_dropped_warning": all_dropped_warning,
        "jev_degraded": False,
        "confirmed_docs": confirmed,
        "grey_docs": grey,
        "dropped_noise_ids": [
            {"node_id": r["node_id"], "rel_path": r["rel_path"], "p_in_scope": r["p_in_scope"]}
            for r in dropped
        ],
        "audit": {
            "stage": "A1",
            "question_set_version": QUESTION_SET_VERSION,
            "thresholds": dict(A1_THRESHOLDS),
            "batch_count": len(batches),
            "section_char_cap": SECTION_CHAR_CAP,
            "jev": jev.audit,
            "duration_ms": round((time.monotonic() - started) * 1000.0, 1),
        },
        "next_step_hint": hint,
    }
    log_event(
        logger, "filter_hits:done",
        total_input=len(items), confirmed=len(confirmed),
        grey=len(grey), dropped=len(dropped),
        batch_count=len(batches), jev_degraded=False,
        truncated_warning=scan_truncated_warning,
        all_dropped_warning=all_dropped_warning,
        duration_ms=result["audit"]["duration_ms"],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
