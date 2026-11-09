"""tool_audit.py — 从子 Agent _debug 日志里抽真实 tool_use 统计。

🆕 2026-08-01 改造:proposal-agent 自报 mods 数 vs Edit/Write 实际调用数不一致时,framework 端
需要用真实 tool_use 统计来校验。LLM 可能用 `python3 -c "open('f','w').write(...)"` 绕 Edit/Write
工具统计(虽然产物文件真存在),所以单看文件存在不够,必须看 raw_jsonl 里的 tool_use 事件。

输入:
  - _summary_path: optimization_summary.md 路径(查同目录的 _read_audit.json)
  - debug_dir_str: _debug 目录路径(从 SKILLX_CURRENT_TASK_DIR 环境变量读)

输出: dict[tool_name, count],如:
  {
    "ReadTool": 5,
    "EditTool": 2,
    "WriteTool": 1,
    "BashTool": 8,
    "GrepTool": 0,
    "GlobTool": 0,
  }

策略优先级:
  1. 读 _read_audit.json(LLM 自报,但可被反幻觉校验用)
  2. 从 _debug/agent_*.txt 抽 ## TOOL USE SUMMARY 段(framework 解析过)
  3. 从 _debug/agent_*.txt 抽 raw_jsonl 段(stream-json 模式,自 2026-08-01 默认开启)
  4. 退路:从 STDOUT 段 grep `\\[Tool\\] call` 计数(text 模式)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


def extract_tool_use_from_log(
    summary_path: Path,
    debug_dir_str: Optional[str] = None,
) -> dict[str, int]:
    """从子 Agent _debug 日志抽真实 tool_use 统计。

    Returns: dict[tool_name, count],例如 {"ReadTool": 5, "EditTool": 2, ...}
    """
    counts: dict[str, int] = {
        "ReadTool": 0,
        "EditTool": 0,
        "WriteTool": 0,
        "BashTool": 0,
        "GrepTool": 0,
        "GlobTool": 0,
    }

    # 1) 找 _debug 目录
    debug_dir = None
    if debug_dir_str:
        debug_dir = Path(debug_dir_str)
    if debug_dir is None or not debug_dir.exists():
        # fallback: 从 summary_path 反推
        # summary_path 通常是 {taskid}/round_N/candidate_K/optimization_summary.md
        cand_dir = summary_path.parent
        for _ in range(5):
            cand_dir = cand_dir.parent
            candidate = cand_dir / "_debug"
            if candidate.is_dir():
                debug_dir = candidate
                break

    if debug_dir is None or not debug_dir.exists():
        return counts

    # 2) 找最近的 sub-agent 日志(优先 proposal-agent,因为 proposal 是关键)
    #    如果有多个 Agent,挑 mtime 最大的
    agent_logs = sorted(debug_dir.glob("agent_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not agent_logs:
        return counts

    # 优先 proposal-agent 日志,其他 Agent 次之
    proposal_log = None
    for log in agent_logs:
        if "proposal-agent" in log.name:
            proposal_log = log
            break
    if proposal_log is None:
        proposal_log = agent_logs[0]

    text = proposal_log.read_text(encoding="utf-8", errors="replace")

    # 3) 策略 A:从 ## TOOL USE SUMMARY 段读(framework 解析过)
    # 🆕 2026-08-01 修复:原 regex `\b{tool.lower()}\s*=\s*(\d+)` 只匹配 `ReadTool`/`EditTool` 等全名,
    # 但 LLM Counter 段用 `read=18`/`write=2` 短名,导致 counts 全 0 → 3.2 校验失败
    # 修复:抓所有 `(\w+)\s*=\s*(\d+)` 模式,映射到 counts dict
    m = re.search(r"^## TOOL USE SUMMARY \(begin\)(.*?)^## TOOL USE SUMMARY \(end\)", text, re.MULTILINE | re.DOTALL)
    if m:
        seg = m.group(1)
        # LLM Counter 段用 read/write/bash/grep/glob 短名,映射到 counts dict 全名
        name_map = {
            "read": "ReadTool",
            "write": "WriteTool",
            "edit": "EditTool",
            "bash": "BashTool",
            "grep": "GrepTool",
            "glob": "GlobTool",
            # framework 跑批用 ReadTool/EditTool/WriteTool 全名时也直接匹配
            "readtool": "ReadTool",
            "writetool": "WriteTool",
            "edittool": "EditTool",
            "bashtool": "BashTool",
            "greptool": "GrepTool",
            "globtool": "GlobTool",
        }
        for short, full in name_map.items():
            mm = re.search(rf"\b{short}\s*=\s*(\d+)", seg, re.IGNORECASE)
            if mm:
                counts[full] = max(counts[full], int(mm.group(1)))
        # 如果 TOOL USE SUMMARY 段有数据,直接返回(这是 framework 解析过的)
        if any(v > 0 for v in counts.values()):
            return counts

    # 4) 策略 B:从 raw_jsonl 段读(stream-json 模式落盘)
    m = re.search(r"^## raw_jsonl \(begin\)(.*?)^## raw_jsonl \(end\)", text, re.MULTILINE | re.DOTALL)
    if m:
        seg = m.group(1)
        for line in seg.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Anthropic content_block 事件:tool_use 块
            cb = obj.get("content_block")
            if isinstance(cb, dict) and cb.get("type") == "tool_use":
                tool_name = cb.get("name", "")
                if tool_name in counts:
                    counts[tool_name] += 1
                continue
            # message.content 列表里包含 tool_use 块
            msg = obj.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_name = block.get("name", "")
                            if tool_name in counts:
                                counts[tool_name] += 1
            # assistant.content 列表里包含 tool_use 块
            if obj.get("type") == "assistant":
                content = obj.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_name = block.get("name", "")
                            if tool_name in counts:
                                counts[tool_name] += 1
        return counts

    # 5) 策略 C(退路):从 STDOUT 段 grep `\\[[A-Z]\\w+\\] call` 计数
    m = re.search(r"^## STDOUT \(begin\)(.*?)^## STDOUT \(end\)", text, re.MULTILINE | re.DOTALL)
    if m:
        seg = m.group(1)
        # cosight CLI 输出格式:[BashTool] call() invoked, [ReadTool] call() invoked 等
        for tool in counts:
            mm = re.findall(rf"\[{tool}\] call\(\) invoked", seg)
            counts[tool] = len(mm)

    return counts


def extract_read_file_paths(
    summary_path: Path,
    debug_dir_str: Optional[str] = None,
) -> list[str]:
    """从 proposal 的 _debug 日志(raw_jsonl 段)提取真实 Read 工具的 file_path 列表。

    与 extract_tool_use_from_log 共用日志定位逻辑,但返回 file_path 而非次数,
    供 framework 强校验验证 proposal 是否**真 Read** 过 trace 文件——
    不依赖 `_read_audit.json`(proposal 可伪填"相对路径+备注"),杜绝谎报。
    """
    debug_dir = None
    if debug_dir_str:
        debug_dir = Path(debug_dir_str)
    if debug_dir is None or not debug_dir.exists():
        cand_dir = summary_path.parent
        for _ in range(5):
            cand_dir = cand_dir.parent
            candidate = cand_dir / "_debug"
            if candidate.is_dir():
                debug_dir = candidate
                break
    if debug_dir is None or not debug_dir.exists():
        return []
    agent_logs = sorted(debug_dir.glob("agent_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not agent_logs:
        return []
    proposal_log = None
    for log in agent_logs:
        if "proposal-agent" in log.name:
            proposal_log = log
            break
    if proposal_log is None:
        proposal_log = agent_logs[0]
    text = proposal_log.read_text(encoding="utf-8", errors="replace")

    paths: list[str] = []
    # 遍历日志所有 JSON 行(纯 JSONL 区,stream-json 落盘),跳过 ## 分段与 # 注释
    # 兼容旧格式(## raw_jsonl 分段)与新格式(纯 JSONL 直接落盘)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        candidates: list[dict] = []
        cb = obj.get("content_block")
        if isinstance(cb, dict) and cb.get("type") == "tool_use":
            candidates.append(cb)
        msg = obj.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, list):
                candidates += [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        if obj.get("type") == "assistant":
            content = obj.get("content")
            if isinstance(content, list):
                candidates += [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
        for block in candidates:
            if block.get("name") == "Read":
                inp = block.get("input") or {}
                fp = inp.get("file_path", "")
                if fp:
                    paths.append(fp)
    return paths


def extract_mods_count_from_summary(summary_path: Path) -> int:
    """从 optimization_summary.md 抽 LLM 声明的 mods 数(只统计,不看是否真做了)。

    Returns: mods 数,如果 LLM 没声明或解析失败返回 0。
    """
    if not summary_path.exists():
        return 0
    text = summary_path.read_text(encoding="utf-8", errors="replace")

    # 尝试解析 self_check.modifications 列表
    m = re.search(r'"self_check"\s*:\s*\{', text)
    if not m:
        return 0
    # 找 modifications 数组
    m_mods = re.search(r'"modifications"\s*:\s*\[(.*?)\](?=\s*[,\}\]])', text, re.DOTALL)
    if not m_mods:
        return 0
    # 粗略计数:用花括号匹配外层 {}
    content = m_mods.group(1)
    depth = 0
    count = 0
    in_str = False
    esc = False
    for ch in content:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                count += 1
    return count
