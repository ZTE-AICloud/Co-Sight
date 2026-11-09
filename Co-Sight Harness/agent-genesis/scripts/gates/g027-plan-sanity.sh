#!/usr/bin/env bash
# G027: Skill Foundry 阶段1 产出健全性检查 (批次 2 新增)
#
# 替代原 skill-creation/skill-optimization step-2 的 LLM 独立审查
# (agents/diagnosis-reviewer.md, 已在批次 1/2 阶段裁撤)。
# 镜像 agent 线 G017 替代 readiness-verifier 的已验证先例 (C2 重写注释):
# 格式完整性由确定性 gate 兜底, 语义质量由 DC-002 人审 + Step 6c 盲评双重把关。
#
# 协议: stdin JSON → stdout JSON → exit 0(PASS) / 1(CONCERNS) / 2(FAIL)
# 输入: {"mode": "create|optimize|diagnose", "report_path": "<绝对或相对 ROOT 路径>", "root": "<用户 cwd>",
#        "source_path": "<可选, optimize/diagnose 时目标 Skill 的 SKILL.md 绝对或相对 ROOT 路径>"}
#   mode 必须 = main agent 已路由的 mode (skill-foundry §Mode 判定权威)
#   report_path:
#     - create   → work_root/phase1-skill-design.md
#     - optimize → work_root/phase1-diagnosis-report.md
#     - diagnose → work_root/phase1-diagnosis-report.md
#   source_path: 提供时校验报告中 SKILL.md:<N> 行号引用真实存在 (N ≤ 文件实际行数);
#     缺省 → 行号存在性降级为 CONCERNS (不阻断, 与 §8 R3 误杀防护一致)
#
# FAIL-CLOSED: 缺 mode / 缺 report_path / 报告文件不存在 → FAIL
# CONCERNS(非阻断): frontmatter 缺字段 / 行号格式变异 / Q/G 决策无 guide.yaml 引用 / source_path 缺失
#                   → 由 main agent 写 plan-sanity-result.yaml 时降级记录, 不阻断 phase 流转
#
# 设计约束:
#   - 容忍多种 L\d+ 行号写法 (按 §8 风险缓解 R3 落实, 误杀防护)
#   - 行号存在性仅 optimize/diagnose 模式检查 (create 阶段 1 是设计, 行号引用是产物阶段才看)
#   - 不内联 guide.yaml 决策清单 (薄封装, 防止三重拷贝)
set -uo pipefail

INPUT=$(cat)
MODE=$(echo "$INPUT" | jq -r '.mode // ""')
REPORT=$(echo "$INPUT" | jq -r '.report_path // ""')
ROOT=$(echo "$INPUT" | jq -r '.root // ""')
SOURCE=$(echo "$INPUT" | jq -r '.source_path // ""')
[[ -z "$ROOT" || "$ROOT" == "null" ]] && ROOT="$PWD"
[[ -z "$SOURCE" || "$SOURCE" == "null" ]] && SOURCE=""

if [[ -z "$MODE" || "$MODE" == "null" ]]; then
  echo '{"gate_id":"gate.plan.sanity","verdict":"FAIL","failures":[{"type":"missing_mode"}]}'
  exit 2
fi

case "$MODE" in
  create|optimize|diagnose) ;;
  *)
    echo "{\"gate_id\":\"G027\",\"verdict\":\"FAIL\",\"failures\":[{\"type\":\"invalid_mode\",\"value\":\"$MODE\"}]}"
    exit 2
    ;;
esac

if [[ -z "$REPORT" || "$REPORT" == "null" ]]; then
  echo '{"gate_id":"gate.plan.sanity","verdict":"FAIL","failures":[{"type":"missing_report_path"}]}'
  exit 2
fi

# 相对路径基于 ROOT 解析
if [[ ! "$REPORT" = /* ]]; then
  REPORT="$ROOT/$REPORT"
fi
if [[ -n "$SOURCE" && ! "$SOURCE" = /* ]]; then
  SOURCE="$ROOT/$SOURCE"
fi

if [[ ! -f "$REPORT" ]]; then
  echo "{\"gate_id\":\"G027\",\"verdict\":\"FAIL\",\"failures\":[{\"type\":\"report_missing\",\"path\":\"$REPORT\"}]}"
  exit 2
fi

# 委托 python 做内容级校验（容错 L\d+ 多种写法）
python3 - "$MODE" "$REPORT" "$SOURCE" <<'PY'
import json
import os
import re
import sys

mode, report, source = sys.argv[1], sys.argv[2], sys.argv[3]

with open(report) as f:
    content = f.read()

failures = []
concerns = []

# ── 通用: frontmatter 必填 (mode / created_at / confidence) ──
fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
if not fm_match:
    failures.append({"type": "frontmatter_missing", "detail": "阶段1 产出必须以 YAML frontmatter 开头"})
else:
    fm = fm_match.group(1)
    for field in ("mode", "created_at", "confidence"):
        if not re.search(rf'^{field}:\s*\S+', fm, re.MULTILINE):
            failures.append({"type": "frontmatter_field_missing", "field": field})

    # 校验 frontmatter.mode 与传入 mode 一致
    declared_mode = re.search(r'^mode:\s*(\S+)', fm, re.MULTILINE)
    if declared_mode and declared_mode.group(1) != mode:
        failures.append({
            "type": "frontmatter_mode_mismatch",
            "declared": declared_mode.group(1),
            "expected": mode
        })

# ── 模式分叉 ──
if mode == "create":
    # create 模式契约来自 rules/skill/skill-design-rules.md §阶段1 产出契约
    required_keys = [
        ("skill_name", r'^skill_name:\s*[a-z][a-z0-9-]+'),
        ("operation_mode", r'^operation_mode:\s*(iterates_and_judges|fetch_filter_rank|transform|record_report)'),
        ("granularity_decision", r'^granularity_decision:\s*(\S.*)?$'),
        ("frontmatter_draft", r'^frontmatter_draft:\s*(\S.*)?$'),
        ("acceptance_criteria", r'^acceptance_criteria:\s*(\S.*)?$'),
    ]
    for name, pat in required_keys:
        if not re.search(pat, content, re.MULTILINE):
            failures.append({"type": "create_field_missing", "field": name})

    # SF-6 描述四要素 (CONCERNS 而非 FAIL: 描述可能由阶段 4 builder 进一步打磨)
    fm_draft_match = re.search(r'^frontmatter_draft:\s*\n((?:[ \t].*\n|\s*\n)+)', content, re.MULTILINE)
    if fm_draft_match:
        desc_match = re.search(r'description:\s*"([^"]+)"', fm_draft_match.group(1))
        if desc_match:
            desc = desc_match.group(1)
            sf6_elements = ["输入", "输出"]  # 做什么 + 何时触发用语义启发太脆, 固定两个最关键
            for elem in sf6_elements:
                if elem not in desc:
                    concerns.append({
                        "type": "sf6_element_missing",
                        "element": elem,
                        "field": "frontmatter_draft.description"
                    })

    # knowledge_assets 引用路径合法性 (防编造)
    refs = re.findall(r'path:\s*["\']?([^\s"\'#]+)["\']?', content)
    bad_refs = [r for r in refs if r.startswith("/") or r.startswith("..") or "~" in r]
    if bad_refs:
        concerns.append({"type": "knowledge_path_may_be_unsafe", "paths": bad_refs[:5]})

elif mode in ("optimize", "diagnose"):
    # 7 维诊断契约 (来自 rules/skill/skill-diagnosis-rules.md §维度 1-7)
    required_dims = [
        ("decomposition", r'(?im)decomposition'),
        ("information", r'(?im)information'),
        ("state", r'(?im)\bstate\b'),
        ("verification", r'(?im)verification'),
        ("logic_consistency", r'(?im)logic[ _-]?consistency'),
        ("design_form", r'(?im)design[ _-]?form'),
        ("global_context", r'(?im)global[ _-]?context'),
    ]
    missing_dims = [name for name, pat in required_dims if not re.search(pat, content)]
    if missing_dims:
        failures.append({
            "type": "diagnosis_dims_missing",
            "missing": missing_dims,
            "detail": "7 维诊断必须全部显式声明 (PASS/FAIL 都行, 但不可跳过)"
        })

    # 边界判定必填 (模式内/部分超出/完全超出 三选一)
    boundary_match = re.search(
        r'(?im)边界判定[::\s]+(skill\s*内可解决|部分超出|完全超出|skill[ _-]?内|partially[ _-]?out|fully[ _-]?out)',
        content
    )
    if not boundary_match:
        failures.append({
            "type": "boundary_judgment_missing",
            "detail": "必须给出明确边界判定结论 (skill 内可解决 / 部分超出 / 完全超出)"
        })

    # 行号引用: 宽校验多种 L\d+ 写法（仅识别显式行号标记, 排除时间戳/版本号等假阳性）
    # 接受的写法:
    #   - L42 / L 42 / L:42（最常见）
    #   - line 42 / line:42
    #   - 第 42 行 / 第42行
    #   - SKILL.md:42 / SKILL.md L42 / SKILL.md:42-58（行号区间也算）
    line_refs = re.findall(
        r'(?:\bL[: ]\d+|\bline[: ]\d+|第\s*\d+\s*行|SKILL\.md[: ]\d+)',
        content,
        re.IGNORECASE
    )
    if not line_refs:
        concerns.append({
            "type": "no_line_refs",
            "detail": "optimize/diagnose 模式建议每个 FAIL 维度附行号证据 (接受 L42 / line:42 / 第 42 行 / SKILL.md:42 等写法)"
        })

    # 行号存在性: SKILL.md:<N> 引用必须指向源文件真实行 (§4.3 Step 2, v0.18 修订补实现)
    # 仅校验带文件名的引用 (SKILL.md:42 / SKILL.md L42 / SKILL.md:42-58); 裸 L42 无文件名锚点, 无法定位文件
    if source and os.path.isfile(source):
        with open(source, encoding="utf-8", errors="ignore") as sf:
            source_lines = sum(1 for _ in sf)
        named_refs = re.findall(r'SKILL\.md[: ](\d+)(?:-(\d+))?', content, re.IGNORECASE)
        for start, end in named_refs:
            max_ref = int(end) if end else int(start)
            if max_ref > source_lines:
                failures.append({
                    "type": "line_ref_out_of_range",
                    "ref": f"SKILL.md:{start}" + (f"-{end}" if end else ""),
                    "source_lines": source_lines,
                    "detail": "行号证据指向源 SKILL.md 不存在的行 (伪造行号)"
                })
    else:
        concerns.append({
            "type": "source_path_missing",
            "detail": "未提供 source_path, 行号存在性未校验 (降级记录, 不阻断)"
        })

# ── 占位符硬检查 (独立黑名单, 刻意≠g005: XXX 移除——正文合法出现 XXX 会误报, gate 治理阶段 3;
#    待定 带词边界排除"等/期待定"。勿改回"与 G005 同标准"表述——两 gate 对象不同, 黑名单各自演进) ──
placeholders = re.findall(r'\{\{[^}]+\}\}|TODO|TBD|FIXME|待补充|(?<![等期])待定', content)
if placeholders:
    failures.append({
        "type": "placeholders_present",
        "count": len(placeholders),
        "samples": list(set(placeholders))[:5]
    })

# ── 汇总 ──
if failures:
    print(json.dumps({
        "gate_id": "gate.plan.sanity",
        "verdict": "FAIL",
        "mode": mode,
        "report": report,
        "failures": failures,
        "concerns": concerns
    }, ensure_ascii=False))
    sys.exit(2)
elif concerns:
    print(json.dumps({
        "gate_id": "gate.plan.sanity",
        "verdict": "CONCERNS",
        "mode": mode,
        "report": report,
        "concerns": concerns
    }, ensure_ascii=False))
    # CONCERNS 统一 rc0（gate 治理阶段 3——原 rc1 落入 g026 非预期分支被误判 FAIL）
    sys.exit(0)
else:
    print(json.dumps({
        "gate_id": "gate.plan.sanity",
        "verdict": "PASS",
        "mode": mode,
        "report": report
    }, ensure_ascii=False))
    sys.exit(0)
PY
