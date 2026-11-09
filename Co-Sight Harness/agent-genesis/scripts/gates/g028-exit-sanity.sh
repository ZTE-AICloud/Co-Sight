#!/usr/bin/env bash
# G028: exit-sanity — 收尾校验薄编排（提速方案 OPT-8b）
# 合并集合（按时序划定，原 G005/G014/G021 顶层注册移除，规则脚本保留为内部模块）:
#   agent-exit 档:  g005 + g014 + g021 + g023(--mode batch, 全量声明文件——清单契约
#                     全量首查, executor v2) + g023(--mode cross)
#                   + CLAUDE.md 地板（出口校验减负, 2026-10-16: 原 required_files
#                     全清单复检撤出, 标准回归设计期输入——方案编制时消费;
#                     依据 docs/plan/exit-check-slimming-plan.md, 地板只此一条）
#                   + workflow 引用闭合扫描
#                   + module.agent.static（scripts 可执行位 + frontmatter 必需字段）
#   execution-report 不再机检（executor v2 有意简化——报告为事后审计材料）
#   skill-build 档: g005 + g014（条件启用: skills_dir 提供才跑） + module.skill.static
#                     （确定性收敛重构 2.1: SK-S1/S2 移植; SK-S3 归并 g005——g005 模式集
#                     是其超集, 不双轨）
#   skill-verify 档: g005 + module.skill.static（step-s5 采信链同源, 只读幂等）
#   原 gate.report.valid（g022）随 progress 协议废除一并裁撤（executor v2）
#
# 协议: stdin JSON（g026 原样透传 INPUT）→ stdout 合并 JSON
#   {"gates":["runner.exit"],"profile":"agent-exit|skill-build|skill-verify", ...各规则消费键}  // sunset 后 gates[] 写语义键
# 退出码: 0=PASS / 1=CONCERNS / 2=FAIL（含输入错误，C8-1: type=input_error + 人读 detail）
# 位置无关: SCRIPT_DIR 锚定内部调用与 knowledge 路径（C8-2），不写死 PWD
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export G028_SCRIPT_DIR="$SCRIPT_DIR"
export G028_INPUT="$(cat)"
exec python3 - <<'PYEOF'
import glob
import json
import os
import re
import subprocess
import sys

try:
    import yaml
except ImportError:
    print(json.dumps({"gate_id": "runner.exit", "verdict": "FAIL",
                      "failures": [{"type": "input_error", "detail": "pyyaml 不可用"}]}))
    sys.exit(2)

SCRIPT_DIR = os.environ["G028_SCRIPT_DIR"]
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))


def emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)


def input_error(detail, extra=None):
    f = {"type": "input_error", "detail": detail}
    if extra:
        f.update(extra)
    emit({"gate_id": "runner.exit", "verdict": "FAIL", "failures": [f]}, 2)


try:
    data = json.loads(os.environ.get("G028_INPUT", ""))
except Exception as e:
    input_error(f"输入非合法 JSON: {e}")
if not isinstance(data, dict):
    input_error("输入须为 JSON 对象")

PROFILE = data.get("profile")
PROFILES = ("agent-exit", "skill-build", "skill-verify")
if not PROFILE or PROFILE not in PROFILES:
    input_error(f"profile 缺失或非法（须为 {'|'.join(PROFILES)} 之一）", {"got": PROFILE})

# ── profile 条件必填键（schema 格式不支持条件必填，脚本内 fail-closed 补位）──
# skill-build: skills_dir/rules_dir 为可选——纯 skill 交付物（SKILL.md + templates/）
#   无 .claude/ 子目录（g014 条件启用, 同阶段一裁定"无 skill 的精简交付物不误拦"）;
#   键提供但目录不存在时 g014 自身 missing_input fail-closed 不变
PROFILE_REQUIRE = {
    "agent-exit": ["output_dir", "work_dir", "skills_dir", "rules_dir", "build_plan"],
    "skill-build": [],
    "skill-verify": [],
}
missing = [k for k in PROFILE_REQUIRE[PROFILE] if not data.get(k)]
if not (data.get("target") or data.get("output_dir")):
    missing.append("target|output_dir（任一）")
if missing:
    input_error(f"profile={PROFILE} 必需输入键缺失", {"missing_keys": missing})

OUTPUT_DIR = data.get("output_dir") or data.get("target")

# 内部模块（既有规则脚本，不重写已测试逻辑）
def _modules(profile):
    if profile == "agent-exit":
        # g023 两形态均从 argv 读 --build-plan/--output-dir（stdin INPUT 不覆盖该形态）
        # batch(全量声明文件) = 逐文件 invariants 清单契约首查; cross = 跨文件一致性
        return [("g005", []), ("g014", []), ("g021", []),
                ("g023", ["--mode", "batch", "--build-plan", data["build_plan"],
                          "--output-dir", data["output_dir"]]),
                ("g023", ["--mode", "cross", "--build-plan", data["build_plan"],
                          "--output-dir", data["output_dir"]])]
    if profile == "skill-build":
        # g014 条件启用: 仅当 skills_dir 提供时（纯 skill 交付物无 .claude/ 子目录, 见 PROFILE_REQUIRE 注）
        mods = [("g005", [])]
        if data.get("skills_dir"):
            mods.append(("g014", []))
        return mods
    return [("g005", [])]  # skill-verify

failures = []
concerns = []
passed = 0

# ── 1. 既有规则模块串行执行（INPUT 原样透传 stdin，各模块自取所需键）──
for prefix, extra_argv in _modules(PROFILE):
    matches = sorted(glob.glob(os.path.join(SCRIPT_DIR, f"{prefix}-*.sh")))
    if not matches:
        failures.append({"module": prefix, "type": "unknown_module_script"})
        continue
    try:
        proc = subprocess.run(["bash", matches[0]] + extra_argv, input=json.dumps(data, ensure_ascii=False),
                              capture_output=True, text=True, timeout=600)
        rc, out = proc.returncode, proc.stdout
    except subprocess.TimeoutExpired:
        failures.append({"module": prefix, "type": "module_timeout"})
        continue
    try:
        d = json.loads(out)
        failures.extend({"module": prefix, **f} for f in d.get("failures", []))
        concerns.extend({"module": prefix, **c} for c in d.get("concerns", []))
        verdict = d.get("verdict", "UNKNOWN")
    except Exception:
        verdict = "UNKNOWN"
        failures.append({"module": prefix, "type": "non_json_output"})
    if (rc == 0 and verdict in ("PASS", "CONCERNS")) or (rc == 1 and verdict == "CONCERNS"):
        passed += 1
    else:
        failures.append({"module": prefix, "type": "module_fail", "rc": rc, "verdict": verdict})

# ── 2. CLAUDE.md 地板（出口校验减负, 2026-10-16）──
# 原 required_files 全清单存在性检查已撤出：它与 g023 batch 的方案保真重复裁决
# （方案声明什么产什么，未声明的标准件不要求），且跨场景误伤（如 fast lane 无
# DC-001 却被要求 proposal-spec.md）。标准（agent-output-standard.yaml）回归纯
# 设计期输入，由 planner/builder 编制方案时消费，人审（DC-001/T2）把关方案质量。
# 地板白名单只此一条（agent 线运行时入口，plan-independent）；再扩须过方案评审。
if PROFILE == "agent-exit" and os.path.isdir(OUTPUT_DIR):
    entry = os.path.join(OUTPUT_DIR, "CLAUDE.md")
    if not os.path.isfile(entry):
        failures.append({"module": "file_list", "type": "missing_entry_file",
                         "path": "CLAUDE.md"})
    elif os.path.getsize(entry) == 0:
        failures.append({"module": "file_list", "type": "empty_entry_file",
                         "path": "CLAUDE.md"})

# ── 3. 新增规则: workflow 引用闭合扫描（承接 readiness Step 3 中 g014/g025 未覆盖形态）──
# 扫描产物 phase/ 与 CLAUDE.md 中的路径式引用，核对目标存在:
#   .claude/skills/<n> → <output_dir>/.claude/skills/<n>/SKILL.md
#   .claude/rules/<n>  → <output_dir>/.claude/rules/<n>
#   gate id G[0-9]{3}  → <output_dir>/phase/gates/G###-*（仅当该目录存在时核对）
if PROFILE == "agent-exit" and os.path.isdir(OUTPUT_DIR):
    scan_roots = [os.path.join(OUTPUT_DIR, "phase"), os.path.join(OUTPUT_DIR, "CLAUDE.md")]
    texts = []
    for root in scan_roots:
        if os.path.isfile(root):
            texts.append(root)
        elif os.path.isdir(root):
            for dp, _, fns in os.walk(root):
                for fn in fns:
                    if fn.endswith((".md", ".yaml", ".yml", ".json")):
                        texts.append(os.path.join(dp, fn))
    skills_base = os.path.join(OUTPUT_DIR, ".claude", "skills")
    rules_base = os.path.join(OUTPUT_DIR, ".claude", "rules")
    gates_base = os.path.join(OUTPUT_DIR, "phase", "gates")
    for path in texts:
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for m in re.finditer(r"\.claude/skills/([A-Za-z0-9_-]+)", text):
            if not os.path.isfile(os.path.join(skills_base, m.group(1), "SKILL.md")):
                failures.append({"module": "ref_closure", "type": "broken_skill_ref",
                                 "ref": m.group(0), "in": os.path.relpath(path, OUTPUT_DIR)})
        for m in re.finditer(r"\.claude/rules/([A-Za-z0-9_-]+)", text):
            # 引用可带可不带扩展名（.md 等），存在任一形态即闭合
            base = os.path.join(rules_base, m.group(1))
            if not (os.path.exists(base) or glob.glob(base + ".*")):
                failures.append({"module": "ref_closure", "type": "broken_rule_ref",
                                 "ref": m.group(0), "in": os.path.relpath(path, OUTPUT_DIR)})
        if os.path.isdir(gates_base):
            gate_files = os.listdir(gates_base)
            for m in re.finditer(r"\bG[0-9]{3}\b", text):
                if not any(gf.startswith(m.group(0)) for gf in gate_files):
                    failures.append({"module": "ref_closure", "type": "broken_gate_ref",
                                     "ref": m.group(0), "in": os.path.relpath(path, OUTPUT_DIR)})

# ── 4. module.agent.static: 剩余静态信号（可执行位 + frontmatter 必需字段）──
# C8-3 数据驱动: 文件类别/必需字段/可执行扩展名全在下表, 加类别或字段不改主逻辑
AGENT_STATIC_SPEC = {
    # 相对 OUTPUT_DIR 的 glob → frontmatter 必需字段（存在且非空才闭合）
    "frontmatter": [
        (".claude/agents/*.md", ("name", "description", "tools", "forbidden_inputs")),
        (".claude/skills/*/SKILL.md", ("name", "description")),
    ],
    "executable_extensions": (".sh",),  # 命中文件须有可执行位（hooks 以解释器调用的
                                        # .js/.py 不在内——存在性归 g025 hooks.json 检查）
}

if PROFILE == "agent-exit" and os.path.isdir(OUTPUT_DIR):
    fm = AGENT_STATIC_SPEC["frontmatter"]
    for pattern, fields in fm:
        for path in sorted(glob.glob(os.path.join(OUTPUT_DIR, pattern))):
            try:
                text = open(path, encoding="utf-8").read()
            except OSError as e:
                failures.append({"module": "agent_static", "type": "frontmatter_unreadable",
                                 "path": os.path.relpath(path, OUTPUT_DIR), "detail": str(e)[:200]})
                continue
            if not text.startswith("---"):
                failures.append({"module": "agent_static", "type": "frontmatter_missing",
                                 "path": os.path.relpath(path, OUTPUT_DIR)})
                continue
            block = text.split("\n---", 1)[0][3:]
            try:
                meta = yaml.safe_load(block) or {}
            except Exception as e:
                failures.append({"module": "agent_static", "type": "frontmatter_unparseable",
                                 "path": os.path.relpath(path, OUTPUT_DIR),
                                 "detail": str(e)[:200]})
                continue
            if not isinstance(meta, dict):
                failures.append({"module": "agent_static", "type": "frontmatter_unparseable",
                                 "path": os.path.relpath(path, OUTPUT_DIR),
                                 "detail": "frontmatter 非 key:value 映射"})
                continue
            rel = os.path.relpath(path, OUTPUT_DIR)
            for field in fields:
                if field not in meta:
                    failures.append({"module": "agent_static", "type": "frontmatter_field_missing",
                                     "path": rel, "field": field})
                elif meta[field] in (None, "", [], {}):
                    failures.append({"module": "agent_static", "type": "frontmatter_field_empty",
                                     "path": rel, "field": field})
    for root, _, files in os.walk(OUTPUT_DIR):
        for fn in files:
            if fn.endswith(AGENT_STATIC_SPEC["executable_extensions"]):
                p = os.path.join(root, fn)
                if not os.access(p, os.X_OK):
                    failures.append({"module": "agent_static", "type": "script_not_executable",
                                     "path": os.path.relpath(p, OUTPUT_DIR)})

# ── 5. module.skill.static: SK-S1/S2 移植（skill 线主交付 SKILL.md 静态检查）──
# 确定性收敛重构 2.1（agents/skill-verifier.md 原 Step 1/2 的脚本化, 行为等价基线=内联版;
# SK-S3 占位符不在本模块——g005 模式集为其超集且 skill 两档均运行 g005, 红线 6 禁双轨;
# 语义四项 SK-S4/S8/S9/S10 留在 skill-verifier, 红线 2）
# C8-3 数据驱动: 字段集/行数下限/引用形态/路径黑名单全在下表, 加类别或字段不改主逻辑
SKILL_STATIC_SPEC = {
    "skill_md": "SKILL.md",
    # SK-S1 frontmatter 必需字段（含 version——用户裁定 2026-10-14, 与 SK-S1 行为等价;
    # agent 线附属 skill 的 name/description 口径不变, 见 AGENT_STATIC_SPEC）
    "frontmatter_fields": ("name", "description", "version"),
    "min_lines": 50,
    # SK-S2 引用闭合（内联版口径）: SKILL.md 中提及的 references/*.md 须存在;
    # scripts/*.sh 须过 bash -n——仅当交付物存在 scripts/ 目录时启用（有本地脚本目录
    # → 提及即内部引用须闭合; 无 → scripts/ 提及按外部仓库路径处理, 如资产表引用
    # 仓库机检脚本。references/ 无此歧义, 保持无条件检查）。绝对路径黑名单同内联版
    "ref_checks": (
        (r"references/[A-Za-z0-9_./-]+\.md", "file_exists", None),
        (r"scripts/[A-Za-z0-9_./-]+\.sh", "bash_n", "scripts"),
    ),
    "absolute_path_bans": ("/home/", "/Users/", "/tmp/", "/root/"),
}

if PROFILE in ("skill-build", "skill-verify"):
    skill_md = os.path.join(OUTPUT_DIR, SKILL_STATIC_SPEC["skill_md"])
    if not os.path.isfile(skill_md):
        failures.append({"module": "skill_static", "type": "skill_md_missing",
                         "path": SKILL_STATIC_SPEC["skill_md"]})
    else:
        try:
            text = open(skill_md, encoding="utf-8").read()
        except OSError as e:
            text = None
            failures.append({"module": "skill_static", "type": "skill_md_unreadable",
                             "detail": str(e)[:200]})
        if text is not None:
            # SK-S1: 行数下限
            n_lines = text.count("\n") + (0 if text.endswith("\n") else 1) if text else 0
            if n_lines < SKILL_STATIC_SPEC["min_lines"]:
                failures.append({"module": "skill_static", "type": "skill_md_too_short",
                                 "lines": n_lines, "min": SKILL_STATIC_SPEC["min_lines"]})
            # SK-S1: frontmatter 必需字段
            if not text.startswith("---"):
                failures.append({"module": "skill_static", "type": "frontmatter_missing"})
            else:
                block = text.split("\n---", 1)[0][3:]
                try:
                    meta = yaml.safe_load(block) or {}
                except Exception as e:
                    meta = None
                    failures.append({"module": "skill_static", "type": "frontmatter_unparseable",
                                     "detail": str(e)[:200]})
                if meta is not None and not isinstance(meta, dict):
                    failures.append({"module": "skill_static", "type": "frontmatter_unparseable",
                                     "detail": "frontmatter 非 key:value 映射"})
                    meta = {}
                elif meta is None:
                    meta = {}
                for field in SKILL_STATIC_SPEC["frontmatter_fields"]:
                    if field not in meta:
                        failures.append({"module": "skill_static", "type": "frontmatter_field_missing",
                                         "field": field})
                    elif meta[field] in (None, "", [], {}):
                        failures.append({"module": "skill_static", "type": "frontmatter_field_empty",
                                         "field": field})
            # SK-S2: 引用闭合
            for pattern, kind, context_dir in SKILL_STATIC_SPEC["ref_checks"]:
                if context_dir and not os.path.isdir(os.path.join(OUTPUT_DIR, context_dir)):
                    continue  # 上下文目录不存在 → 该类提及按外部仓库路径处理, 不检
                for m in re.finditer(pattern, text):
                    ref = m.group(0)
                    target = os.path.join(OUTPUT_DIR, ref)
                    if kind == "file_exists":
                        if not os.path.isfile(target):
                            failures.append({"module": "skill_static", "type": "broken_reference",
                                             "ref": ref})
                    else:  # bash_n
                        if not os.path.isfile(target):
                            # scripts/*.sh 提及即要求存在（内联版 SKILL.md 引用闭合语义）
                            failures.append({"module": "skill_static", "type": "broken_reference",
                                             "ref": ref})
                            continue
                        try:
                            proc = subprocess.run(["bash", "-n", target], capture_output=True,
                                                  text=True, timeout=60)
                        except subprocess.TimeoutExpired:
                            failures.append({"module": "skill_static", "type": "script_syntax_timeout",
                                             "ref": ref})
                            continue
                        if proc.returncode != 0:
                            failures.append({"module": "skill_static", "type": "script_syntax_error",
                                             "ref": ref,
                                             "detail": (proc.stderr or "").strip()[:200]})
            # SK-S2: 绝对路径黑名单
            for ban in SKILL_STATIC_SPEC["absolute_path_bans"]:
                if ban in text:
                    line_no = text[:text.index(ban)].count("\n") + 1
                    failures.append({"module": "skill_static", "type": "absolute_path_found",
                                     "path_prefix": ban, "line": line_no})

# ── 6. 合并 verdict ──
result = {"gate_id": "runner.exit", "profile": PROFILE, "passed": passed,
          "failures": failures, "concerns": concerns}
if not failures and not concerns:
    result["verdict"] = "PASS"
    emit(result, 0)
if not failures:
    result["verdict"] = "CONCERNS"
    emit(result, 1)
result["verdict"] = "FAIL"
emit(result, 2)
PYEOF
