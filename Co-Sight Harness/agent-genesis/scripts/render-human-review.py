#!/usr/bin/env python3
"""render-human-review — runner.review.assemble（步 1.6③）: human-review 机械段纯机械组装

用法:
  python3 scripts/render-human-review.py \
    --fragment <work>/agent-creation/human-review-fragment.md \
    --build-plan <work>/agent-creation/build-plan.md \
    --decision <work>/agent-creation/phase1-matching-decision.md \
    --requirements <work>/agent-creation/clarified-agent-requirements.yaml \
    --review <work>/agent-creation/phase2-review.md \
    --out <work>/agent-creation/human-review.md

退出码: 0 = 组装完成（stdout 单行 JSON 摘要）; 2 = input_error（畸形输入, JSON failures）。
职责边界: 纯机械组装。物化对账（matching 表 vs build-plan 增量表）归
validate-plan-v2.py validate_build_plan（step-3 校验接线, main agent 先跑）, 本件不重复。

机械段清单（D3 黄金对拍盘点锁定; 基线 = tests/fixtures/pr-security-reviewer/human-review.md,
仓内唯一 LLM 转写版样本）:
  §4  文件清单 —— build-plan per-file 块机械转写（路径/角色/生成方式）
  §5  已知风险 —— fragment 判断条目透传（前缀逐条机检）+ phase2-review findings 机械透传
  §7  验收标准 —— acceptance_criteria 转写 + build-plan invariants derived_from 映射机检锚点
  §11 拓扑图   —— matching-decision「结构决策」build_type_decision 渲染 Mermaid
判断段（§1/2/3/5 判断条目/6/8/9/10）自 fragment 逐字透传; fragment 未知/缺失槽位即 input_error。
C9-6: 本脚本渲染的机械段不输出内部编号（gate/pattern ID）、置信度、内部流程术语。
"""
import argparse
import json
import re
import sys

import yaml

RISK_PREFIX = re.compile(r"^\s*-\s*\[(临界|重大|轻微|critical|major|minor)\]")
FINDINGS_KEY = re.compile(r"^findings:[ \t]*(.*)$", re.MULTILINE)
TOPO_LABEL = {"W1_stage_parallel": "阶段并行", "W3_mapreduce": "归约汇总",
              "W4_leader_worker": "主从分发", "W5_wrap": "包装扩展"}
TYPE_ROLE = {"claude_md": "CLAUDE.md 主调度文件", "workflow_md": "运行时工作流文档",
             "rule": "通用规则", "schema": "结构契约（schema）", "subagent": "SubAgent 定义",
             "skill": "Skill 定义", "script": "脚本", "fixture": "测试夹具",
             "test": "验收标准", "settings": "项目设置", "gates_yaml": "门禁配置",
             "meta": "元数据记录", "other": "支撑文件"}
GEN_MODE = {"generate": "LLM 生成", "copy": "直拷", "template": "模板物化"}
JUDGMENT_SLOTS = ("概述", "核心能力", "交付计划", "已知风险（判断条目）", "spot-check 锚点",
                  "架构决策摘要", "决策物化摘要", "判断题清单")


def emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)


def input_error(detail, **extra):
    emit({"runner": "review.assemble", "verdict": "FAIL",
          "failures": [dict({"type": "input_error", "detail": detail}, **extra)]}, 2)


def read_text(path: str, label: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        input_error(f"{label} 不存在或不可读: {exc}", path=path)


def parse_frontmatter(text: str, label: str) -> dict:
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        input_error(f"{label} 缺 frontmatter（须以 --- 对开始）")
    try:
        loaded = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        input_error(f"{label} frontmatter yaml 解析失败: {exc}")
    if not isinstance(loaded, dict):
        input_error(f"{label} frontmatter 非映射")
    return loaded


def yaml_blocks(text: str, label: str) -> list:
    blocks = []
    for bm in re.finditer(r"```yaml\n(.*?)```", text, re.DOTALL):
        try:
            blocks.append(yaml.safe_load(bm.group(1)))
        except yaml.YAMLError as exc:
            input_error(f"{label} yaml 块解析失败: {exc}")
    return blocks


def split_fragment(text: str) -> tuple:
    """fragment → (agent_name, {slot: 正文})。槽位集合精确匹配，未知/缺失即 input_error。"""
    title = re.search(r"^# (.+)$", text, re.MULTILINE)
    if not title or "—" not in title.group(1):
        input_error("fragment 缺一级标题或标题缺「— <agent 名>」后缀",
                    contract="# human-review 判断段 fragment — <name>")
    name = title.group(1).split("—")[-1].strip()
    h1_end = text.index("\n", title.start()) + 1
    slots: dict = {}
    current = None
    body: list = []
    for line in text[h1_end:].splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            if current is not None:
                slots[current] = "\n".join(body).strip("\n")
            current = m.group(1).strip()
            if current not in JUDGMENT_SLOTS:
                input_error(f"fragment 含未知槽位「{current}」（判断段只允许 8 个固定槽位）",
                            known_slots=list(JUDGMENT_SLOTS))
            body = []
        elif current is not None:
            body.append(line)
    if current is not None:
        slots[current] = "\n".join(body).strip("\n")
    missing = [s for s in JUDGMENT_SLOTS if s not in slots]
    if missing:
        input_error(f"fragment 缺判断段槽位: {missing}", known_slots=list(JUDGMENT_SLOTS))
    return name, slots


def parse_build_plan(text: str) -> tuple:
    fm = parse_frontmatter(text, "build-plan")
    # 双形态归一: 平铺 path: 为权威形态（schemas/build-plan.schema.yaml），嵌套 file: 包裹取内层
    files = [b["file"] if isinstance(b.get("file"), dict) else b
             for b in yaml_blocks(text, "build-plan") if isinstance(b, dict)]
    files = [f for f in files if "path" in f]
    if not files:
        input_error("build-plan 无 per-file 块（每文件一个 ```yaml 块, 平铺 path: 或顶层 file: 键包裹）")
    for f in files:
        if not str(f.get("path") or "").strip():
            input_error("build-plan 存在 path 为空的 file 块")
    return fm, files


def parse_decision(text: str) -> dict:
    """结构决策: 优先正文「结构决策」yaml 块（subagents 键）, 回退 frontmatter build_type。"""
    fm = parse_frontmatter(text, "matching-decision")
    bt = fm.get("build_type") or {}
    if isinstance(bt, str):
        bt = {"type": bt}
    struct = {"type": bt.get("type") or "single", "topology": bt.get("topology") or "",
              "subagents": [], "skills": []}
    for b in yaml_blocks(text, "matching-decision"):
        if isinstance(b, dict) and isinstance(b.get("subagents"), list):
            struct = {"type": b.get("type") or struct["type"],
                      "topology": b.get("topology") or "",
                      "subagents": b["subagents"], "skills": b.get("skills") or []}
            break
    for sa in struct["subagents"]:
        if not isinstance(sa, dict) or not str(sa.get("role") or "").strip():
            input_error("结构决策 subagents 条目缺 role", subagent=sa)
    return struct


def parse_requirements(text: str) -> list:
    try:
        req = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        input_error(f"clarified-requirements yaml 解析失败: {exc}")
    if not isinstance(req, dict):
        input_error("clarified-requirements 顶层非映射")
    criteria = req.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria:
        input_error("clarified-requirements 缺非空 acceptance_criteria 列表")
    for i, c in enumerate(criteria):
        if not isinstance(c, dict) or not any(str(c.get(k) or "").strip() for k in ("given", "when", "then")):
            input_error(f"acceptance_criteria[{i}] 非 given/when/then 映射", entry=c)
    return criteria


def parse_review(text: str) -> list:
    m = FINDINGS_KEY.search(text)
    if not m:
        input_error("phase2-review 缺 findings 行（允许 findings: []）")
    inline = m.group(1).strip()
    if inline:
        try:
            findings = yaml.safe_load(inline)
        except yaml.YAMLError as exc:
            input_error(f"phase2-review findings 行内 yaml 解析失败: {exc}")
    else:
        collected: list = []
        for ln in text[m.end():].splitlines():
            if re.match(r"^\s+-\s", ln):
                collected.append(ln)
            elif not collected and ln.strip() == "":
                continue
            else:
                break
        try:
            findings = yaml.safe_load("\n".join(collected)) or []
        except yaml.YAMLError as exc:
            input_error(f"phase2-review findings 块解析失败: {exc}")
    if findings is None:
        findings = []
    if not isinstance(findings, list):
        input_error("phase2-review findings 非列表")
    return findings


def render_files(files: list) -> list:
    lines = ["| # | 路径 | 角色 | 生成方式 |", "|---|------|------|---------|"]
    for i, f in enumerate(files, start=1):
        gen = f.get("generation") or "generate"
        if gen not in GEN_MODE:
            input_error(f"file 块 generation 非法: {gen}", path=f.get("path"))
        lines.append(f"| {i} | {f['path']} | {TYPE_ROLE.get(f.get('type'), '支撑文件')} "
                     f"| {GEN_MODE[gen]} |")
    return lines


def render_risks(judgment_slot: str, findings: list) -> list:
    items = [ln.rstrip() for ln in judgment_slot.splitlines() if ln.strip()]
    for ln in items:
        if not RISK_PREFIX.match(ln):
            input_error(f"判断风险条目缺等级前缀（须以 - [临界|重大|轻微] 开头）: {ln[:60]}",
                        contract="dc001-channel.sh 第四项机械 grep 判定")
    for fd in findings:
        if isinstance(fd, dict):
            dim = fd.get("dimension") or fd.get("check") or "方案"
            desc = fd.get("description") or fd.get("detail") or str(fd)
            reason = fd.get("reason") or fd.get("evidence") or ""
            tail = f"（复核依据: {reason}）" if reason else ""
            items.append(f"- [重大] 匹配方案审查提示（{dim}）：{desc}{tail}")
        else:
            items.append(f"- [重大] 匹配方案审查提示：{fd}")
    if len(items) < 2:
        input_error(f"已知风险合计 {len(items)} 条, 低于 2 条下限（DC-001 审批要求）")
    return items


def render_acceptance(criteria: list, files: list) -> list:
    anchors: dict = {}
    for f in files:
        for inv in f.get("invariants") or []:
            ref = (inv or {}).get("derived_from")
            if ref:
                anchors.setdefault(ref, []).append(f"{(inv).get('type')}@{f['path']}")
    lines = ["| AC | 判据 | 验证落点 |", "|----|------|---------|"]
    for i, c in enumerate(criteria):
        parts = [f"{label} {c[k]}" for label, k in
                 (("给定", "given"), ("当", "when"), ("则", "then")) if str(c.get(k) or "").strip()]
        spots = anchors.get(f"acceptance_criteria[{i}]")
        landing = "机检 " + "、".join(sorted(spots)) if spots else "人工验收（无机检锚定, 见判断题清单）"
        lines.append(f"| AC{i + 1} | {'；'.join(parts)} | {landing} |")
    return lines


def sanitize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).replace('"', "'").replace("|", "/")
                  .replace("[", "（").replace("]", "）")).strip()


def render_topology(struct: dict) -> list:
    topo = str(struct.get("topology") or "")
    tail = re.match(r"^[A-Z]+[0-9]+_(.+)$", topo)
    label = TOPO_LABEL.get(topo) or (tail.group(1) if tail else "")
    lines = ["```mermaid", "flowchart TD"]
    if struct.get("type") == "multi_agent":
        lines.append("    U[用户输入] --> M[主 Agent 调度]")
        for i, sa in enumerate(struct["subagents"]):
            node = f"S{i}[{sanitize(sa['role'])}]"
            iso = sanitize(sa.get("isolation_point") or "")
            edge = f'-- "{iso}"' if iso else ""
            lines.append(f"    M {edge} --> {node}")
        for j, sk in enumerate(struct.get("skills") or []):
            sname = sk.get("name") if isinstance(sk, dict) else str(sk)
            lines.append(f"    M --> K{j}[Skill: {sanitize(sname)}]")
        if label:
            lines.append(f"    M -. {label} .-> M")
    else:
        lines += ["    U[用户输入] --> M[Agent 主流程]", "    M --> R[结果输出]"]
    lines.append("```")
    return lines


def assemble(name: str, slots: dict, files: list, risks: list,
             acceptance: list, topology: list) -> str:
    sec = lambda n, title, body: "\n".join([f"## {n}. {title}", "", *body, ""])  # noqa: E731
    parts = [
        f"# DC-001 人审展示面 — {name}",
        "",
        "> 本文件是 DC-001 go/no-go 审批的完整展示材料。判断段（§1/2/3/5 判断条目/6/8/9/10）"
        "由 build-planner 撰写并逐字透传；机械段（§4 文件清单 / §5 风险透传 / §7 验收转写 / "
        "§11 拓扑图）由 runner.review.assemble 自 build-plan / matching-decision / "
        "clarified-requirements / phase2-review 机械组装。",
        "",
        sec(1, "概述", slots["概述"].splitlines()),
        sec(2, "核心能力", slots["核心能力"].splitlines()),
        sec(3, "交付计划", slots["交付计划"].splitlines()),
        sec(4, "文件清单（含角色/生成方式）", render_files(files)),
        sec(5, "已知风险（≥2）", risks),
        sec(6, "Spot-check 锚点（≥3，可执行）", slots["spot-check 锚点"].splitlines()),
        sec(7, "验收标准（acceptance_criteria 映射）", acceptance),
        sec(8, "架构决策摘要", slots["架构决策摘要"].splitlines()),
        sec(9, "决策物化摘要（≤20 行）", slots["决策物化摘要"].splitlines()),
        sec(10, "判断题清单（≤7，机检标注）", slots["判断题清单"].splitlines()),
        sec(11, "拓扑图", topology),
    ]
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fragment", required=True)
    ap.add_argument("--build-plan", required=True)
    ap.add_argument("--decision", required=True)
    ap.add_argument("--requirements", required=True)
    ap.add_argument("--review", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    name, slots = split_fragment(read_text(args.fragment, "fragment"))
    _, files = parse_build_plan(read_text(args.build_plan, "build-plan"))
    struct = parse_decision(read_text(args.decision, "matching-decision"))
    criteria = parse_requirements(read_text(args.requirements, "clarified-requirements"))
    findings = parse_review(read_text(args.review, "phase2-review"))

    risks = render_risks(slots["已知风险（判断条目）"], findings)
    doc = assemble(name, slots, files, risks,
                   render_acceptance(criteria, files), render_topology(struct))
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(doc)
    except OSError as exc:
        input_error(f"--out 写入失败: {exc}", path=args.out)
    emit({"runner": "review.assemble", "status": "assembled", "out": args.out,
          "files_n": len(files), "risks_n": len(risks),
          "passthrough_findings_n": len(findings), "acceptance_n": len(criteria),
          "subagents_n": len(struct["subagents"])}, 0)


if __name__ == "__main__":
    main()
