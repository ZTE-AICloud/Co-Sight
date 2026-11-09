#!/usr/bin/env bash
# G026: 批量 gate 跑器 — 一次进程运行多个 gate，输出合并 JSON verdict
# (P1/P2 基础设施，见 docs/plan/goal-mode-pipeline-acceleration.md §1.3；
#  输入契约与缺键校验见 schemas/g026-input.schema.yaml，gate 治理方案阶段 1)
#
# 协议: --input '<json>'（executor 白名单模式唯一可行方式）或 stdin JSON
#       {gates: ["gate.step.outputs",...], ...可选上下文键} → stdout merged JSON
# 退出码: 0=PASS(全部) / 1=CONCERNS(有 concerns 无硬 fail) / 3=FAIL(任一硬 fail 或 input_error)
# 行为: 按 gates 顺序串行调用所解析的实现脚本，合并 failures/concerns；
#       名称解析（legacy sunset 后, 2026-10-15——双读收敛为单读）:
#         1) 语义键直查（gate.* / runner.*, 注册表 phase/gates/gates.yaml 两段）
#         2) 编号 glob 回退仅在 G026_GATES_DIR 显式注入时启用（测试基建专用,
#            生产路径不参与; 原 legacy 反查与 internal-module glob 已随 sunset 删除）
#       子 gate stderr 捕获进 stderr_notes（不再丢弃）；未知 gate 记 unknown_gate_script
#       并入 warnings（不静默）。

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ "${1:-}" = "--input" ]; then
  [ $# -ge 2 ] || { echo '{"gate_id":"runner.gates.batch","verdict":"FAIL","failures":[{"type":"input_error","detail":"--input 需跟 JSON 参数"}]}'; exit 3; }
  export G026_INPUT="$2"
else
  # 有界 stdin 读: 开放 stdin 的后台场景不再无界挂死, 超时按空输入 fail-closed
  export G026_INPUT="$(timeout 10 cat 2>/dev/null || true)"
fi

export G026_REPO_ROOT="$REPO_ROOT"
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
    print(json.dumps({"gate_id": "runner.gates.batch", "verdict": "FAIL",
                      "failures": [{"type": "input_error", "detail": "pyyaml 不可用"}]}))
    sys.exit(3)

GATE_ID_RE = re.compile(r"^(G[0-9]{3})")


def emit(obj, code):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)


def input_error(detail, extra=None):
    failure = {"type": "input_error", "detail": detail}
    if extra:
        failure.update(extra)
    emit({"gate_id": "runner.gates.batch", "verdict": "FAIL", "failures": [failure]}, 3)


raw = os.environ.get("G026_INPUT", "")

# ── 1. JSON 解析（fail-closed，拒绝静默空转）──
try:
    data = json.loads(raw)
except Exception as e:
    input_error(f"输入非合法 JSON: {e}")
if not isinstance(data, dict):
    input_error("输入须为 JSON 对象")

gates = data.get("gates")
if not isinstance(gates, list) or not gates or not all(isinstance(g, str) and g.strip() for g in gates):
    input_error("gates 须为非空字符串数组")

# ── 2. 输入契约校验（schema 缺失即 input_error，拒绝无契约运行）──
schema_path = os.path.join(os.environ["G026_REPO_ROOT"], "schemas", "g026-input.schema.yaml")
try:
    with open(schema_path, encoding="utf-8") as f:
        schema = yaml.safe_load(f) or {}
except Exception as e:
    input_error(f"输入契约 schema 缺失或不可解析: {schema_path} ({e})")

required_map = schema.get("gate_required_keys") or {}


# ── 2.6 注册表加载（fail-closed; sunset 后仅语义键表）──
def load_registry():
    """gates.yaml 两段注册表 → 语义键→条目。缺失/不可解析即 input_error。"""
    reg_path = os.path.join(os.environ["G026_REPO_ROOT"], "phase", "gates", "gates.yaml")
    try:
        with open(reg_path, encoding="utf-8") as f:
            reg = yaml.safe_load(f) or {}
    except Exception as e:
        input_error(f"gate 注册表缺失或不可解析: {reg_path} ({e})")
    semantic = {}
    for sec in ("gates", "runners"):
        for key, entry in (reg.get(sec) or {}).items():
            semantic[key] = entry or {}
    return semantic


SEMANTIC_MAP = load_registry()

# gate 目录锚定插件根（不随 CWD 漂移——R6 跑错仓库根因之一）；G026_GATES_DIR 仅供测试注入
gates_dir = os.environ.get("G026_GATES_DIR") or os.path.join(
    os.environ["G026_REPO_ROOT"], "scripts", "gates")


def resolve_gate(name):
    """解析请求的 gate 名 → (实现脚本绝对路径或 None, schema 必需键 canon)。
    sunset 后单读: 语义键直查; 编号 glob 仅当 G026_GATES_DIR 显式注入（测试基建）。
    canon = 语义键（schema required_map 同键）; 未知 gate → (None, 原名) 走 unknown fail-closed。"""
    n = name.strip()
    entry = SEMANTIC_MAP.get(n)
    if entry is not None:
        script = entry.get("script")
        path = os.path.join(os.environ["G026_REPO_ROOT"], str(script)) if script else None
        return path, n
    if os.environ.get("G026_GATES_DIR"):
        m = GATE_ID_RE.match(n)
        canon = m.group(1) if m else n
        matches = sorted(glob.glob(os.path.join(gates_dir, f"{canon.lower()}-*.sh")))
        return (matches[0] if matches else None), canon
    return None, n


missing_report = []
resolved = {}
for g in gates:
    script_path, canon = resolve_gate(g)
    resolved[g] = (script_path, canon)
    req = required_map.get(canon) if canon else None
    if not req:
        continue
    missing = []
    for k in req.get("all_of") or []:
        if not data.get(k):
            missing.append(k)
    if req.get("any_of"):
        if not any(data.get(k) for k in req["any_of"]):
            missing.append("任一: " + "|".join(req["any_of"]))
    if missing:
        missing_report.append({"gate": g, "missing_keys": missing})
if missing_report:
    input_error("所请求 gate 的必需输入键缺失", {"missing": missing_report})

# ── 3. 逐 gate 串行执行 ──
merged_failures = []
merged_concerns = []
warnings = []
stderr_notes = []
passed = 0
failed = 0

for g in gates:
    script_path, canon = resolved[g]
    if not script_path:
        failed += 1
        merged_failures.append({"gate": g, "type": "unknown_gate_script"})
        warnings.append(f"{g}: 未解析到实现（registry 语义键未命中；"
                        f"编号 glob 回退仅 G026_GATES_DIR 测试注入时可用）")
        continue
    script = script_path
    try:
        proc = subprocess.run(["bash", script], input=raw, capture_output=True,
                              text=True, timeout=600)
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        failed += 1
        merged_failures.append({"gate": g, "type": "gate_timeout"})
        continue

    verdict = "UNKNOWN"
    try:
        d = json.loads(out)
        verdict = d.get("verdict", "UNKNOWN")
        merged_failures.extend(d.get("failures", []))
        merged_concerns.extend(d.get("concerns", []))
    except Exception:
        warnings.append(f"{g}: stdout 非合法 JSON（verdict 视为 UNKNOWN）")

    if err.strip():
        stderr_notes.append({"gate": g, "stderr": err.strip()[:2000]})

    if rc == 0 and verdict in ("PASS", "CONCERNS"):
        passed += 1
    elif rc == 1 and verdict == "CONCERNS":
        passed += 1  # rc1+CONCERNS: 有 concerns 无硬 fail（兼容 G027 旧形态）
    elif rc in (2, 3) and verdict == "FAIL":
        failed += 1
    else:
        failed += 1
        warnings.append(f"{g}: 非预期 rc={rc}/verdict={verdict}")

# ── 4. 合并 verdict ──
result = {"gate_id": "runner.gates.batch", "passed": passed, "failed": failed,
          "failures": merged_failures, "concerns": merged_concerns}
if warnings:
    result["warnings"] = warnings
if stderr_notes:
    result["stderr_notes"] = stderr_notes

if failed == 0 and not merged_concerns:
    result["verdict"] = "PASS"
    emit(result, 0)
elif failed == 0:
    result["verdict"] = "CONCERNS"
    emit(result, 1)
else:
    result["verdict"] = "FAIL"
    emit(result, 3)
PYEOF
