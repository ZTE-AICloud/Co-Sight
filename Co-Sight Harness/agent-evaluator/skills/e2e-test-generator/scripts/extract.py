#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract.py — S1 画像抽取（识别矩阵扫描）。

按识别矩阵扫描 Agent 根，产出：
  <work>/10-profile-input.json   结构化抽取结果（供 LLM 归并能力点）
  <work>/11-merge.prompt.md      能力点归并提示词（交主 agent 填写）

用法：
    python3 extract.py --work <中间态目录>
"""

import argparse
import json
import re
import sys
from pathlib import Path

import config
import engine_probe
from common import (
    GoldevalError,
    fail,
    name_from_path,
    read_json,
    read_text,
    work_path,
    write_json,
    write_text,
)

try:
    import yaml
except ImportError:  # pragma: no cover - 降级路径
    yaml = None


# ============================== Markdown 解析辅助 ==============================

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<yaml>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL
)


def split_sections(markdown):
    """把 Markdown 拆成 {二级标题: 正文}。返回 (title, sections, order)。"""
    title = ""
    sections = {}
    order = []
    current = None
    buffer = []

    for line in markdown.splitlines():
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) <= 2:
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = match.group(2).strip()
            if not title and len(match.group(1)) == 1:
                title = current
            if current not in sections:
                order.append(current)
            buffer = []
        else:
            buffer.append(line)

    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return title, sections, order


def find_section(sections, keyword):
    """按关键词模糊命中章节正文（如 '能力边界'）。

    跳过 None 键：当文档没有一级标题时，split_sections 会把正文挂到 None 下。
    """
    for name, body in sections.items():
        if name and keyword in name:
            return body
    return ""


def parse_key_value_table(markdown):
    """解析 | 变量 | 值 | 形态的两列表格，返回 dict。"""
    result = {}
    for line in markdown.splitlines():
        match = TABLE_ROW_RE.match(line)
        if not match:
            continue
        cells = [c.strip() for c in match.group(1).split("|")]
        if len(cells) < 2:
            continue
        key, value = cells[0], cells[1]
        if not key or set(key) <= set("-: "):
            continue
        if key in ("变量", "路径", "字段", "项目"):
            continue
        result[key] = value
    return result


def merge_anchor_meta(table_meta, frontmatter):
    """合并锚点元数据的两个来源：正文表格 + YAML frontmatter。

    COSIGHT.md 习惯把元数据写成 `| 变量 | 值 |` 表格，CLAUDE.md 则写 YAML
    frontmatter，两类锚点都得认。同一键冲突时以 frontmatter 为准——它是
    显式声明的机器可读元数据，正文表格更接近散文。

    只收标量：frontmatter 里的 list/dict（如 `skills:`、`tags:`）不是元数据，
    混进来会让下游在 `meta.get("project_id")` 之外多出一堆无关结构。下划线
    开头的键同理跳过——那是 YAML 惯例里的私有/内部字段，不是工程声明。
    """
    merged = dict(table_meta or {})
    for key, value in (frontmatter or {}).items():
        if not isinstance(key, str) or key.startswith("_"):
            continue
        if isinstance(value, (str, int, float, bool)):
            merged[key] = value
    return merged


def parse_structure_index(markdown):
    """解析工程结构索引表，返回 {路径: 作用}。"""
    index = {}
    for line in markdown.splitlines():
        match = TABLE_ROW_RE.match(line)
        if not match:
            continue
        cells = [c.strip() for c in match.group(1).split("|")]
        if len(cells) < 2:
            continue
        path_cell = cells[0].strip("` ")
        if not path_cell or path_cell in ("路径",) or set(path_cell) <= set("-: "):
            continue
        if "/" in path_cell or "." in path_cell:
            index[path_cell] = cells[1]
    return index


def parse_frontmatter(markdown):
    """解析 YAML frontmatter，返回 (frontmatter dict, 正文)。

    只有「开头就是 `---` 且块内确实是 YAML 映射」才算 frontmatter，否则**原样
    返回整篇**。这条判据不是洁癖：Markdown 里的水平分隔线也是 `---`，若照切不误，
    一篇以分隔线开头的文档会被吞掉直到下一个 `---`（一级标题一起没了），
    锚点扫描就会凭空丢标题、丢章节。

    YAML 不可用或解析失败时同样不剥离——宁可少认元数据，也不能误伤正文。
    """
    match = FRONTMATTER_RE.match(markdown)
    if not match or yaml is None:
        return {}, markdown
    try:
        loaded = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError:
        return {}, markdown
    if not isinstance(loaded, dict):
        return {}, markdown
    return loaded, markdown[match.end():]


# ============================== 验收基线抽取 ==============================

# 非功能验收项：YAML 里没有独立章节，取 quality 下的这三项拼成一条文本
QUALITY_KEYS = ("performance", "security", "availability")


def _as_text(value):
    """把 YAML 标量归一成去空白的字符串；缺失/None 得到空串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def find_requirements_file(scan_root, agent_root):
    """在 <scan_root>/.agent-genesis 下定位 clarified-agent-requirements.yaml。

    返回 (path, warnings)；没有 .agent-genesis 或里面没有该文件时返回 (None, [])。
    同一 .agent-genesis 下有多份时按工程名（agent 根目录名，版本号目录取父目录名）
    匹配 work/<name>/agent-creation/；匹配不上或多于一份都报错，避免用错别人的契约。
    """
    genesis = Path(scan_root) / config.REQUIREMENTS_DIRNAME
    if not genesis.is_dir():
        return None, []

    candidates = sorted(
        p for p in genesis.rglob(config.REQUIREMENTS_FILENAME) if p.is_file()
    )
    if not candidates:
        return None, []
    if len(candidates) == 1:
        return candidates[0], []

    name = name_from_path(agent_root)
    matched = [
        p for p in candidates if name in p.relative_to(genesis).parts
    ]
    if len(matched) == 1:
        return matched[0], []
    if not matched:
        raise GoldevalError(
            f"{genesis} 下有多份 {config.REQUIREMENTS_FILENAME}，"
            f"没有一份能按工程名 {name!r} 匹配；请把 --agent 指向具体工程"
        )
    raise GoldevalError(
        f"{genesis} 下有多份 {config.REQUIREMENTS_FILENAME} 匹配工程名 "
        f"{name!r}：{'、'.join(str(p) for p in matched)}；请把 --agent 指向具体工程"
    )


def build_nonfunctional(quality):
    """把 quality.{performance,security,availability} 拼成非功能验收文本。"""
    if not isinstance(quality, dict):
        return ""
    parts = []
    for key in QUALITY_KEYS:
        text = _as_text(quality.get(key))
        if text:
            parts.append(f"{key}: {text}")
    return "；".join(parts)


def parse_acceptance_criteria(payload):
    """从验收契约映射里抽 acceptance_criteria，返回 (entries, nonfunctional, warnings)。

    缺字段的条目**跳过而非补齐**：没有 Given/When/Then 的条目无法物化成可评测用例，
    填空串只会把脏数据传给下游。index 保留它在原列表中的位置，便于回查 YAML。
    """
    warnings = []
    raw = payload.get(config.ACCEPTANCE_FIELD)
    if raw is None:
        return [], "", warnings
    if not isinstance(raw, list):
        warnings.append(
            f"验收契约的 {config.ACCEPTANCE_FIELD} 不是数组，已按无验收基线处理"
        )
        return [], "", warnings

    entries = []
    for position, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            warnings.append(
                f"{config.ACCEPTANCE_FIELD} 第 {position} 条不是映射，已跳过"
            )
            continue
        missing = [
            key for key in ("given", "when", "then") if not _as_text(item.get(key))
        ]
        if missing:
            warnings.append(
                f"{config.ACCEPTANCE_FIELD} 第 {position} 条缺少 "
                f"{'/'.join(missing)}，已跳过"
            )
            continue
        entries.append({
            "index": position,
            "title": f"AC{position}",
            "given": _as_text(item["given"]),
            "when": _as_text(item["when"]),
            "then": _as_text(item["then"]),
        })

    return entries, build_nonfunctional(payload.get("quality")), warnings


def _relative_to(path, base):
    """尽量给出相对 base 的路径；不在 base 之下时退回绝对路径。"""
    try:
        return Path(path).relative_to(base).as_posix()
    except ValueError:
        return Path(path).as_posix()


# ============================== 识别矩阵各定位 ==============================

def scan_manifest(root, flavor):
    """P0 工程清单：锚点文件（COSIGHT.md / CLAUDE.md）。

    两类锚点的章节名不同（COSIGHT 有「定位/能力边界/快速开始/工程结构索引」，
    CLAUDE.md 是自由散文），因此章节缺失是常态，不是错误——能力点主要由
    归并那一步从全文与 skills/rules 中提炼。
    """
    anchor = flavor["anchor"]
    text = read_text(root / anchor)
    if not text:
        return None
    # 元数据有两个来源：COSIGHT.md 用正文表格，CLAUDE.md 用 YAML frontmatter。
    # 先摘掉 frontmatter 再切章节，免得 `---` 分隔线与 project_id 行混进正文。
    frontmatter, body = parse_frontmatter(text)
    title, sections, order = split_sections(body)
    return {
        "file": anchor,
        "exists": True,
        "title": title,
        "meta": merge_anchor_meta(parse_key_value_table(body), frontmatter),
        "sections": {name: sections[name] for name in order if name},
        "structure_index": parse_structure_index(find_section(sections, "工程结构索引")),
        "capability_boundary": find_section(sections, "能力边界"),
        "quickstart": find_section(sections, "快速开始"),
        "positioning": find_section(sections, "定位"),
    }


def scan_settings(root, flavor):
    """P0 工具面声明：<flavor>/settings.json。"""
    relpath = flavor["settings"]
    payload = read_json(root / relpath)
    if not isinstance(payload, dict):
        return None
    permissions = payload.get("permissions") or {}
    return {
        "file": relpath,
        "exists": True,
        "allow": permissions.get("allow") or [],
        "deny": permissions.get("deny") or [],
        "model_tier": (payload.get("model") or {}).get("tier"),
        "constraints": payload.get("constraints") or {},
        "comment": payload.get("comment", ""),
    }


def scan_skills(root, flavor):
    """P0 交互入口 / 提示词主体：<flavor>/skills/*/SKILL.md。"""
    results = []
    for path in sorted(root.glob(flavor["skills_glob"])):
        text = read_text(path)
        if not text:
            continue
        frontmatter, body = parse_frontmatter(text)
        _, sections, order = split_sections(body)
        results.append({
            "file": path.relative_to(root).as_posix(),
            "frontmatter": frontmatter,
            "sections": {name: sections[name] for name in order if name},
            "constraints": find_section(sections, "三约束") or find_section(sections, "约束"),
            "flow": find_section(sections, "流程"),
            "anchoring": find_section(sections, "判定锚定"),
            "exits": find_section(sections, "异常出口"),
            "not_for": find_section(sections, "Not for"),
        })
    return results


def scan_pass_criteria(scan_root, agent_root):
    """P0 验收基线：<--agent>/.agent-genesis 下的 clarified-agent-requirements.yaml。

    返回 (criteria, warnings)。文件缺失、不可读、YAML 解析失败或
    acceptance_criteria 为空/缺失时，criteria 为 None，由调用方降级为档 C。
    """
    path, warnings = find_requirements_file(scan_root, agent_root)
    if path is None:
        warnings.append(
            f"未找到验收契约（{Path(scan_root) / config.REQUIREMENTS_DIRNAME} 下无 "
            f"{config.REQUIREMENTS_FILENAME}），已按无验收基线处理"
        )
        return None, warnings

    relpath = _relative_to(path, scan_root)
    text = read_text(path)
    if not text:
        warnings.append(f"验收契约不可读，已按无验收基线处理：{relpath}")
        return None, warnings
    if yaml is None:
        warnings.append(
            f"PyYAML 不可用，无法解析验收契约，已按无验收基线处理：{relpath}"
        )
        return None, warnings
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        warnings.append(f"验收契约 YAML 解析失败，已按无验收基线处理：{relpath}（{exc}）")
        return None, warnings
    if not isinstance(payload, dict):
        warnings.append(f"验收契约内容不是映射，已按无验收基线处理：{relpath}")
        return None, warnings

    entries, nonfunctional, parse_warnings = parse_acceptance_criteria(payload)
    warnings.extend(parse_warnings)
    return {
        "file": relpath,
        "exists": True,
        "gwt_count": len(entries),
        "gwt_entries": entries,
        "nonfunctional": nonfunctional,
    }, warnings


def scan_rules(root, flavor):
    """P2 通用规则：只取各文件首个一级标题。"""
    results = []
    for path in sorted(root.glob(flavor["rules_glob"])):
        text = read_text(path)
        if not text:
            continue
        heading = ""
        for line in text.splitlines():
            match = HEADING_RE.match(line)
            if match and len(match.group(1)) == 1:
                heading = match.group(2).strip()
                break
        results.append({
            "file": path.relative_to(root).as_posix(),
            "title": heading,
        })
    return results


def scan_demo_code(root):
    """源②上下文素材：demo_code/ 文件清单与摘要（不直接产出用例）。"""
    demo_root = root / config.DEMO_CODE_DIRNAME
    if not demo_root.is_dir():
        return None
    files = []
    for path in sorted(demo_root.rglob("*")):
        if not path.is_file():
            continue
        text = read_text(path, limit=4096)
        files.append({
            "file": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "head": "\n".join(text.splitlines()[:20]),
        })
    return {"dir": config.DEMO_CODE_DIRNAME, "file_count": len(files), "files": files}


def scan_excluded(root, flavor):
    """列出被排除表命中的文件，供 report.md 说明。"""
    excluded = []
    for rel in flavor["excluded_relpaths"]:
        path = root / rel
        if path.is_file():
            excluded.append({"path": rel, "bytes": path.stat().st_size,
                             "reason": "框架样板，对能力抽取近乎零信号"})
    for pattern in config.EXCLUDED_DIR_GLOBS:
        path = root / pattern
        if path.is_dir():
            count = sum(1 for p in path.rglob("*") if p.is_file())
            excluded.append({"path": pattern + "/**", "bytes": 0,
                             "reason": f"构建过程工作区（{count} 文件）；"
                                       f"验收基线单独经 {config.REQUIREMENTS_FILENAME} 读取"})
    return excluded


# ============================== 归并提示词 ==============================

MERGE_PROMPT_TEMPLATE = """\
# 任务：能力点归并

你是测试设计专家。下面是自动扫描得到的**被测 Agent 画像原始素材**。
请把它归并成一组**可被单条用例验证的行为单元**（能力点），供后续生成测试用例引用。

## 硬性要求

1. 粒度：**按可验证的行为单元切分，不按文件切分**。一个能力点 = 一条用例能验证清楚的一件事。
2. 数量：控制在 {cap_min}~{cap_max} 个之间。宁精勿滥。
3. 每个能力点必须能追溯到素材中的依据（引用 `evidence` 字段写出来源）。
4. 只输出 JSON，无解释、无 markdown 围栏。

## 输出 schema

```json
{{
  "capabilities": [
    {{
      "id": "C01",
      "name": "简短名称（8 字以内最佳）",
      "desc": "一句话说明这个能力点验证什么",
      "evidence": "素材中的出处，如 CLAUDE.md#能力边界 / 引擎规则表 R01"
    }}
  ]
}}
```

## 判定档位（请一并输出）

- `A`：素材中含非空的 `acceptance_criteria`（验收基线，来自 `.agent-genesis` 下的 `clarified-agent-requirements.yaml`）
- `B`：无验收基线，但含 `demo_code/` 或引擎实现文件
- `C`：只有锚点文件（CLAUDE.md / COSIGHT.md）/ SKILL.md 等文本

输出里附加 `"tier": "A|B|C"` 与 `"tier_reason": "一句话依据"`。

## 画像原始素材

```json
{payload}
```
"""


def build_merge_prompt(profile_input):
    payload = json.dumps(profile_input, ensure_ascii=False, indent=2)
    return MERGE_PROMPT_TEMPLATE.format(
        cap_min=8, cap_max=15, payload=payload
    )


# ============================== 主流程 ==============================

def build_profile_input(root, flavor_id=None, anchor_found=True, agent_slug="",
                        scan_root=None):
    """按识别矩阵扫描，返回 profile-input 结构。

    flavor_id 由 S0 的锚点判定给出；缺省时回退 FALLBACK_FLAVOR。
    anchor_found=False 表示类型没真正识别出来（flavor 只是回退的扫描布局），
    此时标签记「未识别」。
    scan_root 是 `--agent` 对应的扫描起点（目录输入即目录本身，归档输入为解包根），
    验收契约从它下面的 `.agent-genesis` 里找；缺省时退化为 root。
    """
    root = Path(root)
    scan_root = Path(scan_root) if scan_root else root
    flavor = config.flavor_of(flavor_id or config.FALLBACK_FLAVOR)

    manifest = scan_manifest(root, flavor)
    settings = scan_settings(root, flavor)
    skills = scan_skills(root, flavor)
    criteria, criteria_warnings = scan_pass_criteria(scan_root, root)
    rules = scan_rules(root, flavor)
    demo = scan_demo_code(root)

    structure_index = (manifest or {}).get("structure_index") or {}
    engine = engine_probe.probe_engine(root, list(structure_index))

    gwts = (criteria or {}).get("gwt_entries") or []
    if gwts:
        tier = config.TIER_A
    elif demo or engine:
        tier = config.TIER_B
    else:
        tier = config.TIER_C

    return {
        "root": str(root),
        "agent_slug": agent_slug,
        "flavor": flavor["id"],
        "flavor_label": flavor["label"] if anchor_found else config.DEFAULT_LABEL,
        "anchor_file": flavor["anchor"],
        "tier_hint": tier,
        "manifest": manifest,
        "settings": settings,
        "skills": skills,
        "pass_criteria": criteria,
        "engine": engine,
        "demo_code": demo,
        "rules": rules,
        "excluded": scan_excluded(root, flavor),
        # 验收基线相关的告警（契约缺失/坏条目）由 S1 收尾并入画像
        "warnings": criteria_warnings,
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="extract.py", description="S1 画像抽取：识别矩阵扫描 + 归并提示词"
    )
    parser.add_argument("--work", required=True, help="中间态目录")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    asset = read_json(work_path(args.work, "asset"))
    if not asset:
        fail("未找到 S0 产物，请先运行 parse.py")

    try:
        profile_input = build_profile_input(
            asset["root"], asset.get("flavor"), asset.get("anchor_found", True),
            asset.get("agent_slug") or "",   # S0 未记录时由 freeze 回退推导
            # 验收契约从 --agent 对应的扫描起点找，而非深挖后的工程根
            scan_root=asset.get("scan_root") or asset["root"],
        )
    except GoldevalError as exc:
        fail(str(exc))

    write_json(work_path(args.work, "profile_input"), profile_input)
    write_text(work_path(args.work, "merge_prompt"), build_merge_prompt(profile_input))

    gwts = (profile_input["pass_criteria"] or {}).get("gwt_count", 0)
    caps_of = {
        "manifest": bool(profile_input["manifest"]),
        "settings": bool(profile_input["settings"]),
        "skills": len(profile_input["skills"]),
        "gwt": gwts,
        "engine": bool(profile_input["engine"]),
        "demo_code": bool(profile_input["demo_code"]),
        "rules": len(profile_input["rules"]),
    }
    print(f"S1 扫描完成：flavor={profile_input['flavor']}  "
          f"tier_hint={profile_input['tier_hint']}")
    for key, value in caps_of.items():
        print(f"    {key}: {value}")
    for item in profile_input["excluded"]:
        print(f"    已排除: {item['path']}（{item['reason']}）")
    print(f"\n下一步：读取 {work_path(args.work, 'merge_prompt')}")
    print(f"        并写出 {work_path(args.work, 'merge_answer')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
