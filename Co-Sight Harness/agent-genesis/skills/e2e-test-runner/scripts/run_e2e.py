#!/usr/bin/env python3
"""E2E Test Runner — spawns claude -p per test case, collects session data + artifacts, generates report.

Evaluation is phase-gated: checks which pipeline phase was reached, what files were produced,
and whether the behavior matches expectations. No keyword-matching on stdout.

All detection signals and behavior rules are loaded from YAML configs in scripts/:
  - phase-detection.yaml  — phase keyword signals and ordering
  - behavior-rules.yaml   — per-case behavior checks + assessment templates

Output follows AgentGenesis work/{target-name}/ convention:
  work/e2e-test-ci/
  ├── run-{timestamp}/           # one directory per run, history traceable
  │   ├── suite.yaml             # run config snapshot
  │   ├── report.json
  │   ├── report.md
  │   └── sessions/{case_id}/
  │       ├── stdout.txt
  │       ├── stderr.txt
  │       ├── result.json
  │       ├── timing.json
  │       ├── artifacts.json
  │       └── phase.json
  └── latest -> run-{timestamp}/  # symlink to latest run
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import yaml

# Script is at skills/e2e-test-runner/scripts/run_e2e.py
# SKILL_DIR = skills/e2e-test-runner; REPO_ROOT = 仓库根（相对 target_path/sources 的解析基准）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.dirname(os.path.dirname(SKILL_DIR))

# 被测会话的产物扫描根（v0.17 过程产物在 .agent-genesis/work/，旧版在 work/）
WORK_ROOTS = ["work", os.path.join(".agent-genesis", "work")]
# V6c 副作用快照根 = 产物扫描根 + 最终产物 output/
SIDE_EFFECT_ROOTS = WORK_ROOTS + ["output"]

# ── Config Loading ──────────────────────────────────────────────


def _load_yaml_config(name):
    """Load a YAML config from the scripts/ directory."""
    path = os.path.join(SCRIPT_DIR, name)
    with open(path) as f:
        return yaml.safe_load(f)


def load_phase_patterns():
    """Load phase detection patterns from phase-detection.yaml."""
    cfg = _load_yaml_config("phase-detection.yaml")
    return cfg.get("phase_patterns", {})


def load_behavior_rules():
    """Load behavior rules and assessment templates from behavior-rules.yaml."""
    cfg = _load_yaml_config("behavior-rules.yaml")
    return {
        "behavior_rules": cfg.get("behavior_rules", {}),
        "domain_templates": cfg.get("domain_assessment_templates", {}),
        "global_templates": cfg.get("global_assessment_templates", {}),
    }


# ── Test Case Loading ───────────────────────────────────────────


def load_cases_from_suite(suite_path, cli_args=None):
    """从 suite.yaml 的 sources 列表加载所有 test_cases，合并返回。

    Args:
        suite_path: suite.yaml 文件路径
        cli_args: argparse.Namespace，支持 --ids 和 --domain 过滤

    Returns:
        list[dict]: 测试用例列表
    """
    suite_dir = os.path.dirname(os.path.abspath(suite_path))
    with open(suite_path) as f:
        config = yaml.safe_load(f)

    # target_path in suite.yaml is relative to REPO_ROOT (not suite.yaml dir)
    config_target = config.get("target_path", ".")
    if os.path.isabs(config_target):
        target_dir = config_target
    else:
        target_dir = os.path.normpath(os.path.join(REPO_ROOT, config_target))

    cases = []
    for source_path in config.get("sources", []):
        if os.path.isabs(source_path):
            source_full = source_path
        else:
            source_full = os.path.normpath(os.path.join(target_dir, source_path))
        with open(source_full) as f:
            source = yaml.safe_load(f)
        domain = source.get("domain", "")
        for tc in source.get("test_cases", []):
            if "domain" not in tc:
                tc["domain"] = domain
            cases.append(tc)

    # Apply CLI filters
    if cli_args:
        if cli_args.ids:
            id_set = set(i.strip() for i in cli_args.ids.split(","))
            cases = [c for c in cases if c["id"] in id_set]
        if cli_args.domain:
            domain_prefix = cli_args.domain.upper()
            cases = [c for c in cases
                     if c.get("domain", "").startswith(domain_prefix + "-")
                     or c.get("domain", "").startswith(domain_prefix + " ")]

    return cases, target_dir


# ── Session Collection ─────────────────────────────────────────────────

class SessionCollector:
    """Saves all CLI output and metadata for a single test case."""

    def __init__(self, sessions_dir, case_id):
        self.dir = os.path.join(sessions_dir, case_id)
        os.makedirs(self.dir, exist_ok=True)

    def save_stdout(self, text):
        with open(os.path.join(self.dir, "stdout.txt"), "w") as f:
            f.write(text if text else "(empty)")

    def save_stderr(self, text):
        with open(os.path.join(self.dir, "stderr.txt"), "w") as f:
            f.write(text if text else "(empty)")

    def save_result_json(self, data):
        with open(os.path.join(self.dir, "result.json"), "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def save_timing(self, elapsed, exit_code, timed_out):
        with open(os.path.join(self.dir, "timing.json"), "w") as f:
            json.dump({"elapsed_seconds": elapsed, "exit_code": exit_code, "timed_out": timed_out}, f)

    def save_artifacts(self, artifacts):
        with open(os.path.join(self.dir, "artifacts.json"), "w") as f:
            json.dump(artifacts, f, indent=2, ensure_ascii=False)

    def save_phase(self, phase_info):
        with open(os.path.join(self.dir, "phase.json"), "w") as f:
            json.dump(phase_info, f, indent=2, ensure_ascii=False)


# ── Artifact Scanning ──────────────────────────────────────────────────

def _extract_partial_result(text):
    """Extract the 'result' field from partially-written JSON (timeout case)."""
    if not text or len(text) < 50:
        return ""
    marker = '"result":"'
    idx = text.find(marker)
    if idx >= 0:
        start = idx + len(marker)
        end = start
        while end < len(text):
            if text[end] == '"' and (end + 1 >= len(text) or text[end-1] != '\\'):
                return text[start:end][:1000]
            end += 1
        return text[start:][:1000]
    return ""


def _iter_root_files(root_dir):
    """Walk a root dir, yield (full_path, rel_path, mtime)."""
    if not os.path.isdir(root_dir):
        return
    for root, _dirs, files in os.walk(root_dir):
        for f in files:
            fpath = os.path.join(root, f)
            try:
                st = os.stat(fpath)
            except OSError:
                continue
            yield fpath, os.path.relpath(fpath, root_dir), st.st_mtime


def take_work_snapshot(target_path):
    """Record all file paths + mtimes under every WORK_ROOTS entry before a test run."""
    snapshot = {}
    for work_root in WORK_ROOTS:
        for fpath, _rel, mtime in _iter_root_files(os.path.join(target_path, work_root)) or []:
            snapshot[fpath] = mtime
    return snapshot


# orchestrator-state.yaml (v0.17) current_step → 旧版相位键
# 映射依据 phase/gates/gates.yaml steps[].step_id；相位键保持旧语义不变
_STEP_PHASE_MAP = {
    "step-1-requirement-clarification": "IH2_CLARIFY",
    "step-2-pattern-matching": "PHASE_1",
    "step-3-build-planning": "PLAN_MODE",
    "step-3c-plan-approval": "PLAN_MODE",
    "step-4-implementation": "CODE_GENERATED",
    "step-5-readiness-verification": "PHASE_4",
    "step-5-5-runtime-eval-choice": "PHASE_4",
    "step-6-product-validation": "PHASE_5",
    "step-6c-runtime-evaluation": "PHASE_5",
    # skill-foundry 线（step-s*）
    "step-s0-clarify": "IH2_CLARIFY",
    "step-s1-skill-plan-create": "PHASE_1",
    "step-s1-skill-plan-optimize": "PHASE_1",
    "step-s2-plan-sanity": "PHASE_1",
    "step-s3-dc002-approval": "PLAN_MODE",
    "step-s4-skill-build-create": "CODE_GENERATED",
    "step-s4-skill-build-optimize": "CODE_GENERATED",
    "step-s5-skill-verify": "PHASE_4",
    "step-s5-5-eval-choice": "PHASE_4",
    "step-s6-product-validation": "PHASE_5",
    "step-s6c-runtime-evaluation": "PHASE_5",
}


def _map_orchestrator_state(state):
    """orchestrator-state.yaml → 旧版相位键（DONE/PLAN_MODE/PHASE_*/IH2_CLARIFY/CODE_GENERATED）。"""
    if state.get("pipeline_status") in ("DONE", "COMPLETED"):
        return "DONE"
    current_step = state.get("current_step")
    if not current_step:
        steps = state.get("steps") or []
        if steps:
            current_step = steps[-1].get("step_id", "")
    return _STEP_PHASE_MAP.get(current_step, "UNKNOWN")


def _read_pipeline_state(target_root):
    """读目标目录的流水线状态。

    优先 orchestrator-state.yaml (v0.17)，回退 progress-state.yaml (旧版)。
    返回归一化 dict（消费方接口与旧 progress_state 一致）；无状态文件返回 None。
    """
    orch = os.path.join(target_root, "orchestrator-state.yaml")
    if os.path.isfile(orch):
        try:
            with open(orch) as fh:
                st = yaml.safe_load(fh) or {}
            return {
                "current_state": _map_orchestrator_state(st),
                "pipeline": st.get("pipeline", ""),
                "phase_count": len(st.get("steps", []) or []),
                "source": "orchestrator-state.yaml",
            }
        except Exception:
            return {"current_state": "parse_error", "source": "orchestrator-state.yaml"}

    legacy = os.path.join(target_root, "progress-state.yaml")
    if os.path.isfile(legacy):
        try:
            with open(legacy) as fh:
                ps = yaml.safe_load(fh) or {}
            return {
                "current_state": ps.get("current_state", "unknown"),
                "pipeline": ps.get("pipeline", ""),
                "phase_count": len(ps.get("phase_history", []) or []),
                "source": "progress-state.yaml",
            }
        except Exception:
            return {"current_state": "parse_error", "source": "progress-state.yaml"}

    return None


def scan_work_artifacts(target_path, before_snapshot=None):
    """Scan WORK_ROOTS directories for pipeline artifacts.

    If before_snapshot is provided, only reports files NEW or MODIFIED since snapshot.
    """
    any_exists = False
    targets_map = {}  # target_name → list of artifact dicts

    for work_root in WORK_ROOTS:
        root_dir = os.path.join(target_path, work_root)
        for fpath, rel, mtime in _iter_root_files(root_dir) or []:
            any_exists = True

            if before_snapshot is not None:
                prev_mtime = before_snapshot.get(fpath)
                if prev_mtime is not None and abs(mtime - prev_mtime) < 1.0:
                    continue  # unchanged

            parts = rel.split(os.sep)
            target_name = parts[0] if parts else "_root"
            file_rel = os.sep.join(parts[1:]) if len(parts) > 1 else parts[0]
            size = os.path.getsize(fpath)

            if target_name not in targets_map:
                targets_map[target_name] = []
            targets_map[target_name].append({"path": file_rel, "size_bytes": size})

    if not any_exists:
        return {"work_exists": False, "targets": []}

    targets = []
    for name in sorted(targets_map.keys()):
        if name.startswith("_") or name.startswith("."):
            continue
        key_files = targets_map[name]
        target_info = {"name": name, "key_files": key_files, "file_count": len(key_files)}

        for work_root in WORK_ROOTS:
            state = _read_pipeline_state(os.path.join(target_path, work_root, name))
            if state:
                target_info["has_progress_state"] = True
                target_info["progress_state"] = state
                break

        targets.append(target_info)

    return {"work_exists": True, "target_count": len(targets), "targets": targets}


# ── Side-Effect Manifest (V6c) ─────────────────────────────────────────

def take_side_snapshot(target_path):
    """V6c: snapshot SIDE_EFFECT_ROOTS (work/ + .agent-genesis/work/ + output/) at run start."""
    snapshot = {}
    for root in SIDE_EFFECT_ROOTS:
        for fpath, _rel, mtime in _iter_root_files(os.path.join(target_path, root)) or []:
            snapshot[fpath] = mtime
    return snapshot


def diff_side_effects(target_path, before_snapshot, exclude_dir):
    """V6c: diff SIDE_EFFECT_ROOTS after run → new/modified files (excluding the report dir itself)."""
    exclude_prefix = os.path.abspath(exclude_dir) + os.sep
    new_files, modified_files = [], []
    for root in SIDE_EFFECT_ROOTS:
        root_dir = os.path.join(target_path, root)
        for fpath, rel, mtime in _iter_root_files(root_dir) or []:
            if os.path.abspath(fpath).startswith(exclude_prefix):
                continue  # 报告自身不算副作用
            prev = before_snapshot.get(fpath)
            if prev is None:
                new_files.append(os.path.join(root, rel))
            elif abs(mtime - prev) >= 1.0:
                modified_files.append(os.path.join(root, rel))
    return {"new": sorted(new_files), "modified": sorted(modified_files)}


# ── Phase Analysis (config-driven) ─────────────────────────────────────

def _phase_base(phase_str):
    """Extract the base phase key from a display string."""
    for key in ["DONE", "PLAN_MODE", "PHASE_5", "PHASE_4", "PHASE_3",
                 "PHASE_2", "PHASE_1", "IH2_CLARIFY", "EXECUTING", "NO_WORK_DIR", "UNKNOWN"]:
        if key in phase_str:
            return key
    return "UNKNOWN"


def _build_phase_order(patterns):
    """Build PHASE_ORDER mapping from loaded patterns."""
    order = {"NO_WORK_DIR": 0, "UNKNOWN": 1}
    for phase_key, phase_cfg in patterns.items():
        order[phase_key] = phase_cfg.get("order", 5)
    return order


def _detect_phase_from_output(output_text, patterns):
    """Detect pipeline phase from output text patterns (config-driven)."""
    if not output_text:
        return None, 0

    best_match = None
    best_order = 0

    # Check compound conditions first (signal + also_requires)
    for phase_key, phase_cfg in patterns.items():
        for compound in phase_cfg.get("compound", []):
            main_signal = compound.get("signal", "")
            if main_signal not in output_text:
                continue
            required = compound.get("also_requires", [])
            if any(r in output_text for r in required):
                order = phase_cfg.get("order", 5)
                if order > best_order:
                    best_order = order
                    best_match = phase_cfg.get("display_name", phase_key)

    # Check simple signal matching
    for phase_key, phase_cfg in patterns.items():
        for signal in phase_cfg.get("signals", []):
            if signal in output_text:
                order = phase_cfg.get("order", 5)
                if order > best_order:
                    best_order = order
                    best_match = phase_cfg.get("display_name", phase_key)
                break  # one match per phase is enough

    return best_match, best_order


# ── Behavioral Analysis (config-driven) ────────────────────────────────

def _check_condition(condition, output_text, phase_reached, artifacts):
    """Evaluate a single condition against the test output."""
    cond_type = condition.get("type", "")

    if cond_type == "text_contains":
        return condition.get("value", "") in output_text

    if cond_type == "text_regex":
        import re
        try:
            return bool(re.search(condition.get("pattern", ""), output_text))
        except re.error:
            return False

    if cond_type == "artifact_exists":
        return artifacts.get("target_count", 0) >= condition.get("min_targets", 0)

    if cond_type == "phase_contains":
        return condition.get("value", "") in phase_reached

    return False


def analyze_behavior(case_id, domain, output_text, phase_reached, artifacts, behavior_rules):
    """Generate a behavioral assessment based on config-defined rules."""
    behaviors = []

    # Look up case-specific rules
    case_rules = behavior_rules.get(case_id)
    if case_rules:
        for behavior_def in case_rules.get("behaviors", []):
            conditions = behavior_def.get("conditions", [])
            pass_when = behavior_def.get("pass_when", "any")
            name = behavior_def.get("name", "")
            detail = behavior_def.get("detail", "")

            results = [_check_condition(c, output_text, phase_reached, artifacts) for c in conditions]

            matched = any(results) if pass_when == "any" else all(results)
            if conditions and matched:
                behaviors.append((name, "PASS", detail))
            elif not conditions:
                # No conditions = always report (phase-driven)
                behaviors.append((name, "INFO", detail))

    # Fallback: if no behaviors matched but we have output, report generically
    if not behaviors:
        if "IH2" in phase_reached or "CLARIFY" in phase_reached:
            behaviors.append(("追问澄清", "PASS", "对模糊输入正确追问，未猜测用户意图"))

    # Timeout behavior: check for partial progress
    if "TIMEOUT" in phase_reached or (not output_text and not behaviors):
        if artifacts.get("work_exists") and artifacts.get("target_count", 0) > 0:
            for t in artifacts.get("targets", []):
                if t.get("has_progress_state"):
                    state = t.get("progress_state", {}).get("current_state", "")
                    if state and state != "unknown":
                        behaviors.append(("进度已保存", "PARTIAL",
                                         f"超时前已写入progress-state.yaml (状态={state})"))
                        break
            if not behaviors:
                behaviors.append(("产物已生成", "PARTIAL",
                                  f"超时前已生成{artifacts.get('target_count', 0)}个目标目录的产物"))

    # Generic output-based fallback
    if not behaviors:
        if len(output_text) > 500:
            behaviors.append(("有响应", "PASS", f"CLI正常响应，输出{len(output_text)}字符"))
        elif len(output_text) > 50:
            behaviors.append(("有响应", "PARTIAL", f"CLI有输出但较短({len(output_text)}字符)，可能仍在处理中"))
        else:
            behaviors.append(("短响应", "WARN", "CLI输出异常短或为空，可能上下文窗口过大导致处理缓慢"))

    return behaviors


def generate_assessment(case_id, domain, phase_reached, behaviors, assessment_templates):
    """Generate a one-sentence assessment based on domain templates + phase."""
    all_pass = all(b[1] == "PASS" for b in behaviors)
    has_partial = any(b[1] == "PARTIAL" for b in behaviors)
    has_warn = any(b[1] == "WARN" for b in behaviors)

    # Check for special cases that override templates
    if "DONE" in phase_reached:
        return "满分通过 — 完整流水线执行成功"

    # Look up domain template
    domain_tpl = assessment_templates.get("domain_templates", {}).get(domain, {})
    global_tpl = assessment_templates.get("global_templates", {})

    # Try domain template with phase base key
    phase_base = _phase_base(phase_reached)
    for tpl_key in (phase_base,):
        if tpl_key in domain_tpl:
            return domain_tpl[tpl_key]

    # Try global template
    if phase_base in global_tpl:
        result = global_tpl[phase_base]
        if has_partial and "进行中" not in result and "部分" not in result:
            return result + "，超时截断"
        return result

    # Default fallbacks
    if all_pass:
        return "通过"
    if has_partial:
        return "部分通过 — 功能正常但超时截断"
    if has_warn:
        return "需进一步分析 — 响应异常或上下文问题"
    return domain_tpl.get("default", global_tpl.get("default", "需进一步分析"))


def analyze_phase_reached(artifacts, output_text, patterns):
    """Determine what pipeline phase the test reached.

    Uses progress-state.yaml as primary source, output text analysis can UPGRADE.
    """
    phase_order = _build_phase_order(patterns)

    ps_phase = None
    ps_order = -1

    if artifacts.get("work_exists"):
        targets = artifacts.get("targets", [])
        for t in targets:
            ps = t.get("progress_state", {})
            state = ps.get("current_state", "")

            if state == "DONE":
                ps_phase = "DONE (完整流水线完成)"
                ps_order = phase_order.get("DONE", 11)
                break
            if state == "PLAN_MODE":
                phases = ps.get("phase_count", 0)
                ps_phase = f"PLAN_MODE (完成Phase1+Phase2={phases}阶段, 等待审批)"
                ps_order = phase_order.get("PLAN_MODE", 7)
                break
            if state in ("PHASE_3", "PHASE_4", "PHASE_5"):
                ps_phase = f"{state} (构建/验证/评估阶段)"
                ps_order = phase_order.get(state, 5)
                break
            if state == "PHASE_2":
                ps_phase = "PHASE_2 (审查阶段)"
                ps_order = phase_order.get("PHASE_2", 6)
            if state == "PHASE_1":
                ps_phase = "PHASE_1 (需求分析/设计阶段)"
                ps_order = phase_order.get("PHASE_1", 5)

        if not ps_phase:
            for t in targets:
                if any("phase1" in f.get("path", "").lower() or "matching-decision" in f.get("path", "").lower()
                       for f in t.get("key_files", [])):
                    ps_phase = "PHASE_1 (检测到 phase1 产物)"
                    ps_order = phase_order.get("PHASE_1", 5)
                    break

    text_phase, text_order = _detect_phase_from_output(output_text, patterns)

    if text_phase and text_order > ps_order:
        return text_phase

    if ps_phase:
        return ps_phase

    if text_phase:
        return text_phase

    if artifacts.get("work_exists") and artifacts.get("target_count", 0) == 0:
        return "NO_ARTIFACTS (work/存在但无新产物)"

    return "UNKNOWN"


# ── Report Generation ──────────────────────────────────────────────────

def generate_report(results, timing_start, report_dir, side_effects=None):
    """Generate JSON + Markdown reports from structured results."""
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "passed")
    partial = sum(1 for r in results if r["status"] == "partial")
    failed = sum(1 for r in results if r["status"] == "failed")
    timed_out = sum(1 for r in results if r["status"] == "timeout")

    if failed == 0 and timed_out == 0 and partial == 0:
        verdict = "PASS"
    elif passed > 0 or partial > 0:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    findings = set()
    for r in results:
        for b in r.get("behaviors", []):
            if b[1] == "PASS":
                findings.add(b[2])

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "execution_mode": "claude -p --permission-mode bypassPermissions --output-format json",
        "summary": {
            "total": total, "passed": passed, "partial": partial, "failed": failed, "timed_out": timed_out,
            "total_duration_seconds": round(time.time() - timing_start, 1),
        },
        "results": results,
    }
    if side_effects is not None:
        report["side_effects"] = side_effects

    # JSON report
    json_path = os.path.join(report_dir, "report.json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Markdown report
    md = []
    md.append("# AgentGenesis E2E Test Report")
    md.append("")
    md.append(f"**Timestamp**: {report['timestamp']}")
    md.append(f"**Verdict**: **{verdict}**")
    md.append(f"**Mode**: `claude -p --permission-mode bypassPermissions --output-format json`")
    md.append(f"**Total Duration**: {report['summary']['total_duration_seconds']:.0f}s")
    md.append("")
    md.append("## 评测逻辑")
    md.append("")
    md.append("每次测试 spawn 独立 `claude -p` 会话，从三个维度评测：")
    md.append("")
    md.append("| 维度 | 说明 |")
    md.append("|------|------|")
    md.append("| **阶段到达** | 是否到达了该用例预期的 Pipeline 阶段（读取 progress-state.yaml） |")
    md.append("| **产物质量** | 是否生成了预期文件（扫描 work/ 目录） |")
    md.append("| **行为正确性** | 输出内容是否与 behavior-rules.yaml 定义的行为规则匹配 |")
    md.append("")
    md.append("## 总览")
    md.append("")
    md.append("| 指标 | 数值 |")
    md.append("|------|:--:|")
    md.append(f"| 总用例 | {total} |")
    md.append(f"| 通过 | {passed} |")
    md.append(f"| 部分 | {partial} |")
    md.append(f"| 超时 | {timed_out} |")
    md.append(f"| 失败 | {failed} |")
    md.append(f"| 总耗时 | {report['summary']['total_duration_seconds']:.0f}s |")
    md.append("")
    md.append("## 逐用例详情")
    md.append("")

    for r in results:
        cid = r["case_id"]
        domain = r.get("domain", "")
        expected = r.get("expected", "")

        if r["status"] == "passed":
            icon = "PASS"
        elif r["status"] == "partial":
            icon = "PART"
        elif r["status"] == "timeout":
            icon = "TIME"
        else:
            icon = "FAIL"

        md.append(f"### {cid} — {domain} — {icon} ({r['duration_seconds']:.0f}s)")
        md.append("")
        md.append("| 项目 | 内容 |")
        md.append("|------|------|")
        md.append(f"| 输入 | {r['input'][:100]} |")
        md.append(f"| 预期 | {expected} |")
        md.append(f"| 到达阶段 | **{r['phase_reached']}** |")

        if r.get("artifacts") and r["artifacts"]["work_exists"]:
            target_count = r["artifacts"].get("target_count", 0)
            if target_count > 0:
                target_names = [t["name"] for t in r["artifacts"].get("targets", [])]
                md.append(f"| 产物目标 | {', '.join(target_names)} (共{target_count}个) |")
                for t in r["artifacts"].get("targets", [])[:3]:
                    for kf in t.get("key_files", [])[:5]:
                        md.append(f"| 产物文件 | `work/{t['name']}/{kf['path']}` ({kf['size_bytes']}B) |")
            else:
                md.append("| 产物 | 无 |")
        else:
            md.append("| 产物 | 无持久化产物 |")

        md.append(f"| 判定 | **{r['assessment']}** |")
        md.append("")

        if r.get("behaviors"):
            md.append("**行为分析**:")
            md.append("")
            for name, result, detail in r["behaviors"]:
                b_icon = {"PASS": "✓", "PARTIAL": "△", "INFO": "ℹ", "WARN": "⚠"}.get(result, "?")
                md.append(f"- {b_icon} **{name}**: {detail}")
            md.append("")

        preview = r.get("result_preview", "")
        if preview:
            md.append(f"**输出摘要**: {preview[:400]}...")
            md.append("")

        md.append(f"**会话数据**: `sessions/{cid}/` (stdout.txt, stderr.txt, result.json, timing.json, artifacts.json, phase.json)")
        md.append("")

    md.append("## 发现汇总")
    md.append("")
    for i, finding in enumerate(sorted(findings), 1):
        md.append(f"| {i} | {finding} |")
    md.append("")

    if side_effects is not None:
        md.append("## 副作用清单（V6c）")
        md.append("")
        md.append("自检会话在被测目录产生的非报告文件（不自动删除，如需清理可手动执行 "
                  "`git clean -nfd .agent-genesis output` 先 dry-run 确认）:")
        md.append("")
        md.append(f"| 类型 | 数量 |")
        md.append(f"|------|:--:|")
        md.append(f"| 新增 | {len(side_effects.get('new', []))} |")
        md.append(f"| 修改 | {len(side_effects.get('modified', []))} |")
        md.append("")
        for f in side_effects.get("new", [])[:50]:
            md.append(f"- 新增: `{f}`")
        for f in side_effects.get("modified", [])[:50]:
            md.append(f"- 修改: `{f}`")
        if len(side_effects.get("new", [])) > 50 or len(side_effects.get("modified", [])) > 50:
            md.append(f"- …(共 {len(side_effects.get('new', [])) + len(side_effects.get('modified', []))} 项，详见 report.json side_effects)")
        md.append("")
    md.append("## 改进方向")
    md.append("")
    md.append("- 创建类用例超时设为 600-900s 以跑完完整流水线")
    md.append("- TC-DP-02 输入措辞需更抽象（避免触发实际命令路由）")
    md.append("- Plan Mode 阶段的用例可通过注入审批消息自动推进到构建阶段")
    md.append("")

    md_path = os.path.join(report_dir, "report.md")
    with open(md_path, "w") as f:
        f.write("\n".join(md))

    # Update latest symlink: work/e2e-test-ci/latest -> run-{ts}/
    latest_link = os.path.join(os.path.dirname(report_dir), "latest")
    if os.path.exists(latest_link) or os.path.islink(latest_link):
        os.unlink(latest_link)
    os.symlink(os.path.basename(report_dir), latest_link)

    return json_path, md_path


# ── Main Runner ────────────────────────────────────────────────────────

def run_test(case_info, target_path, sessions_dir, before_snapshot=None, patterns=None, behavior_rules=None, assessment_templates=None):
    """Run a single test case. Saves all session data. Returns structured result."""
    timeout = case_info.get("timeout", 600)
    collector = SessionCollector(sessions_dir, case_info["id"])

    cmd = [
        "claude", "-p",
        "--permission-mode", "bypassPermissions",
        "--output-format", "json",
        "--no-session-persistence",
    ]

    t0 = time.time()
    timed_out = False
    exit_code = None
    stdout_text = ""
    stderr_text = ""

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=target_path,
            env={**os.environ, "CLAUDE_CODE_DISABLE_NONWHITELISTED_MCP": "1"},
        )
        try:
            stdout_text, stderr_text = proc.communicate(
                input=case_info["input"],
                timeout=timeout,
            )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                _stdout, _stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                _stdout, _stderr = proc.communicate()
            stdout_text = _stdout or ""
            stderr_text = _stderr or ""
    except FileNotFoundError:
        stderr_text = "claude CLI not found"
        exit_code = 127

    elapsed = round(time.time() - t0, 1)

    collector.save_stdout(stdout_text)
    collector.save_stderr(stderr_text)
    collector.save_timing(elapsed, exit_code, timed_out)

    result_text = ""
    if stdout_text:
        try:
            result_json = json.loads(stdout_text)
            result_text = result_json.get("result", "") or ""
            collector.save_result_json(result_json)
        except json.JSONDecodeError:
            partial_result = _extract_partial_result(stdout_text)
            if partial_result:
                result_text = partial_result
                collector.save_result_json({"partial_result": True, "extracted_text": result_text})
            else:
                collector.save_result_json({"parse_error": True, "raw": stdout_text[:2000]})
                result_text = stdout_text

    artifacts = scan_work_artifacts(target_path, before_snapshot=before_snapshot)
    full_artifacts = scan_work_artifacts(target_path)
    collector.save_artifacts(full_artifacts)

    # Config-driven phase analysis
    phase_reached = analyze_phase_reached(artifacts, result_text, patterns)
    phase_info = {
        "phase_reached": phase_reached,
        "artifacts_summary": f"{artifacts.get('target_count', 0)} targets in work/",
    }
    collector.save_phase(phase_info)

    # Config-driven behavior analysis
    domain = case_info.get("domain", "")
    behaviors = analyze_behavior(case_info["id"], domain, result_text, phase_reached, artifacts, behavior_rules)
    assessment = generate_assessment(case_info["id"], domain, phase_reached, behaviors, assessment_templates)

    if timed_out:
        pipeline_phases = ("PLAN_MODE", "PHASE_5", "PHASE_4", "PHASE_3", "PHASE_2", "PHASE_1")
        code_gen = "CODE_GENERATED" in phase_reached
        has_output = len(result_text) > 100
        has_artifacts = artifacts.get("target_count", 0) > 0
        has_progress = artifacts.get("work_exists") and any(
            t.get("has_progress_state") for t in artifacts.get("targets", [])
        )
        if code_gen or any(p in phase_reached for p in pipeline_phases):
            status = "partial"
        elif has_progress or has_artifacts:
            status = "partial"
        elif has_output:
            status = "partial"
        else:
            status = "timeout"
    elif exit_code == 0:
        status = "passed"
    elif exit_code is None and not timed_out:
        status = "passed"
    else:
        status = "failed"

    error_msg = ""
    if timed_out:
        error_msg = f"Timeout after {timeout}s"
        if "PLAN_MODE" in phase_reached:
            error_msg += " (到达Plan Mode)"
        elif any(p in phase_reached for p in pipeline_phases):
            error_msg += f" (到达{phase_reached})"
        elif has_artifacts:
            error_msg += f" (已生成{artifacts.get('target_count', 0)}个目标的产物)"
        elif has_output:
            error_msg += " (有部分输出)"
    elif exit_code and exit_code != 0:
        error_msg = stderr_text[:500] if stderr_text else f"exit_code={exit_code}"

    return {
        "case_id": case_info["id"],
        "domain": domain,
        "input": case_info["input"],
        "expected": case_info.get("expected", ""),
        "status": status,
        "duration_seconds": elapsed,
        "exit_code": exit_code,
        "error_message": error_msg,
        "phase_reached": phase_reached,
        "result_preview": result_text[:400].replace("\n", " "),
        "artifacts": artifacts,
        "behaviors": behaviors,
        "assessment": assessment,
        "session_dir": os.path.join("sessions", case_info["id"]),
    }


def main():
    parser = argparse.ArgumentParser(description="E2E Test Runner for AgentGenesis")
    parser.add_argument("--config", default=None,
                        help="suite.yaml 配置文件路径（播放列表），不指定则从 skills/e2e-test-runner/task/suite.yaml 加载")
    parser.add_argument("--ids", default=None,
                        help="只跑指定用例ID，逗号分隔 (如 TC-DP-01,TC-SM-01)")
    parser.add_argument("--domain", default=None,
                        help="只跑指定域 (A-K)")
    parser.add_argument("--task-file", default=None,
                        help=argparse.SUPPRESS)  # 兼容旧 run-e2e.sh 的 --task-file
    parser.add_argument("--keep-runs", type=int, default=5,
                        help="work/e2e-test-ci/ 下保留的 run-* 报告目录数（默认 5，超出自动删除最旧的）")
    args = parser.parse_args()

    # 兼容旧 --task-file：映射到 --config
    config_path = args.config or args.task_file

    # Load config-driven evaluation rules
    patterns = load_phase_patterns()
    rules = load_behavior_rules()
    behavior_rules = rules["behavior_rules"]
    assessment_templates = {"domain_templates": rules["domain_templates"], "global_templates": rules["global_templates"]}

    target_path = os.environ.get("AGENTGENESIS_TARGET") or None

    # Default to suite.yaml if no config specified
    default_suite = os.path.join(SKILL_DIR, "task", "suite.yaml")
    if not config_path:
        config_path = default_suite

    # Load test cases
    test_cases, suite_target = load_cases_from_suite(config_path, args)
    # spawn cwd: 显式 env 优先，其次 suite 的 target_path（pipeline 形态指向被测产物），最后 REPO_ROOT
    if not target_path:
        target_path = suite_target or REPO_ROOT
    print(f"Loaded {len(test_cases)} cases from {config_path}")

    if not test_cases:
        print("ERROR: No test cases matched. Check --ids / --domain filters.")
        return 1

    run_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    work_root = os.path.join(target_path, "work", "e2e-test-ci")
    report_dir = os.path.join(work_root, f"run-{run_ts}")
    sessions_dir = os.path.join(report_dir, "sessions")
    results_file = os.path.join(report_dir, "results-partial.json")
    suite_snapshot = os.path.join(report_dir, "suite.yaml")

    print(f"AgentGenesis E2E Test Runner v3 (config-driven)")
    print(f"Target: {target_path}")
    print(f"Run:    run-{run_ts}")
    print(f"Cases:  {len(test_cases)}")
    print(f"Phase patterns: {len(patterns)} phases loaded")
    print(f"Behavior rules: {len(behavior_rules)} cases loaded")
    print()

    os.makedirs(sessions_dir, exist_ok=True)

    suite_config = {
        "run_id": f"run-{run_ts}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "target_path": target_path,
        "cli": "claude -p --permission-mode bypassPermissions --output-format json",
        "total_cases": len(test_cases),
        "cases": [{"id": tc["id"], "domain": tc.get("domain",""), "input": tc["input"],
                    "timeout": tc.get("timeout", 600)} for tc in test_cases],
    }
    with open(suite_snapshot, "w") as f:
        yaml.dump(suite_config, f, allow_unicode=True, default_flow_style=False)

    timing_start = time.time()
    results = []
    done_ids = set()

    # V6c: run-start side-effect snapshot across work/ + .agent-genesis/work/ + output/
    side_snapshot = take_side_snapshot(target_path)

    if os.path.exists(results_file):
        try:
            with open(results_file) as f:
                results = json.load(f)
            done_ids = {r["case_id"] for r in results}
            print(f"Resuming: {len(results)} done, {len(test_cases) - len(results)} remaining\n")
        except (json.JSONDecodeError, KeyError):
            results = []
            done_ids = set()

    for i, case in enumerate(test_cases, 1):
        cid = case["id"]
        if cid in done_ids:
            continue

        print(f"[{i}/{len(test_cases)}] {cid} ({case.get('domain','')}) ... ", end="", flush=True)
        before = take_work_snapshot(target_path)
        result = run_test(case, target_path, sessions_dir, before,
                         patterns=patterns, behavior_rules=behavior_rules,
                         assessment_templates=assessment_templates)
        results.append(result)

        status = result["status"]
        icon = "PASS" if status == "passed" else ("PART" if status == "partial" else ("TIME" if status == "timeout" else "FAIL"))
        print(f"{icon} ({result['duration_seconds']:.0f}s) → {result['phase_reached']}")

        with open(results_file, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    side_effects = diff_side_effects(target_path, side_snapshot, report_dir)
    json_path, md_path = generate_report(results, timing_start, report_dir,
                                         side_effects=side_effects)

    if os.path.exists(results_file):
        os.remove(results_file)

    # V6b: 报告轮转 — 保留最近 --keep-runs 个 run-* 目录
    run_dirs = sorted(d for d in os.listdir(work_root)
                      if d.startswith("run-") and os.path.isdir(os.path.join(work_root, d)))
    for old in run_dirs[:-args.keep_runs] if args.keep_runs > 0 else run_dirs:
        shutil.rmtree(os.path.join(work_root, old), ignore_errors=True)
        print(f"Pruned old run: {old}")

    passed = sum(1 for r in results if r["status"] == "passed")
    partial = sum(1 for r in results if r["status"] == "partial")
    failed = sum(1 for r in results if r["status"] == "failed")
    timed_out = sum(1 for r in results if r["status"] == "timeout")

    print(f"\n{'='*60}")
    print(f"Report Summary")
    print(f"{'='*60}")
    print(f"  Passed:      {passed}")
    print(f"  Partial:     {partial}")
    print(f"  Timed Out:   {timed_out}")
    print(f"  Failed:      {failed}")
    print(f"")
    print(f"  Run dir:     {report_dir}")
    print(f"  Latest:      {os.path.join(work_root, 'latest')} -> run-{run_ts}")
    print(f"  JSON:        {json_path}")
    print(f"  MD:          {md_path}")
    print(f"  Sessions:    {sessions_dir}")
    print(f"  Side FX:     {len(side_effects['new'])} new / {len(side_effects['modified'])} modified "
          f"(详见 report.md 副作用清单; 清理建议: git clean -nfd .agent-genesis output)")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
