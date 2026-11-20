#!/usr/bin/env bash
# scripts/env-probe.sh
# P1: Step 0 归并入口（非节点）。从 workflow.md Step 0 抽出。
# - 输出 .agent-genesis/work/{name}/env-readiness.yaml
# - 失败：escalate always（缺工具/权限）
# - 协议: stdout JSON {env_readiness_path, status: PASS|FAIL, failures: [...]}
#
# 用法: bash scripts/env-probe.sh <name> [--host claude-code|dsh]
# 宿主判定优先级: --host > 环境变量 AG_HOST > DSH_HOME/~/.dsh 存在 > claude-code

set -uo pipefail

NAME="${1:?name required}"
shift || true

HOST_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST_OVERRIDE="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

WORK_DIR=".agent-genesis/work/${NAME}"
OUT="${WORK_DIR}/env-readiness.yaml"

mkdir -p "$WORK_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/python-bin.sh
source "${SCRIPT_DIR}/lib/python-bin.sh"

failures=()
recommended_missing=()

# 必需工具：bash / git 由流水线各处直接调用；python 由注入器与技能脚本调用。
for cmd in bash git; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    failures+=("{\"type\":\"missing_tool\",\"tool\":\"$cmd\"}")
  fi
done

if [ -z "${PYTHON_BIN:-}" ]; then
  failures+=("{\"type\":\"missing_tool\",\"tool\":\"python\",\"detail\":\"需要 Python >= 3.8；可用 AG_PYTHON 指定解释器\"}")
fi

# jq 被部分门禁脚本使用；缺失不阻断 Step 0，但记录为建议修复项。
if ! command -v jq >/dev/null 2>&1; then
  recommended_missing+=("{\"type\":\"missing_recommended_tool\",\"tool\":\"jq\",\"detail\":\"部分门禁脚本使用 jq；缺失时相关检查会失败\"}")
fi

# 宿主判定
if [ -n "$HOST_OVERRIDE" ]; then
  HOST="$HOST_OVERRIDE"
elif [ -n "${AG_HOST:-}" ]; then
  HOST="${AG_HOST}"
elif [ -n "${DSH_HOME:-}" ] || [ -d "${HOME}/.dsh" ]; then
  HOST="dsh"
else
  HOST="claude-code"
fi

# 插件形态感知只读检查（C8-2: 插件根从脚本位置推导, 不写死全局路径）
# - cache 安装态（~/.claude/plugins/cache 内）: 运行期插件根可写 = 已安装副本可能被
#   自改 → failure（修复应走 marketplace 更新）
# - directory 源/skills 态（就地加载的开发仓/用户 skills 目录）: 可写合法, 不检查
PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
case "$PLUGIN_ROOT" in
  "$HOME/.claude/plugins/cache"/*)
    if [[ -w "$PLUGIN_ROOT" ]]; then
      failures+=("{\"type\":\"plugin_writable\",\"detail\":\"cache 安装态插件根应只读; 修改插件请走 marketplace 更新后重装\"}")
    fi ;;
  *) : ;;
esac

# 路径落地检查
mkdir -p "$WORK_DIR/gate-results"
touch "$OUT" || failures+=("{\"type\":\"output_unwritable\",\"path\":\"$OUT\"}")

TOOLS_YAML=""
for cmd in bash python git jq; do
  if [ "$cmd" = "python" ]; then
    if [ -n "${PYTHON_BIN:-}" ]; then TOOLS_YAML+="    python: true"$'\n'; else TOOLS_YAML+="    python: false"$'\n'; fi
  elif command -v "$cmd" >/dev/null 2>&1; then
    TOOLS_YAML+="    ${cmd}: true"$'\n'
  else
    TOOLS_YAML+="    ${cmd}: false"$'\n'
  fi
done

PYTHON_DESC="missing"
if [ -n "${PYTHON_BIN:-}" ]; then
  PYTHON_DESC="$("$PYTHON_BIN" -c 'import sys; print("%s %d.%d.%d" % (sys.executable, *sys.version_info[:3]))' 2>/dev/null || echo "$PYTHON_BIN")"
fi

# ── 宿主项目语境探测（host-context 方案 §3.1; 纯机械枚举, 语义判定归澄清器）──
# 判定收窄（方案 R-4）: 只有 claude/dsh 项目才算项目语境; 普通代码仓/空目录 = none
#   claude_code: CLAUDE.md 或 .claude/ 任一存在
#   dsh:         .dsh/ 或 AGENTS.md 或 cordis.patch.yml
#                （特征锚定 knowledge/agent-creation/platforms/dsh.yaml host_constraints
#                 ——该文件是 DSH 事实唯一权威, 特征变更时同步本处）
# fail-open: 本段任何异常不阻断探针主流程, kind 回落 none（与 lane 判定
#   criteria.yaml 缺失静默 full 同款兜底）
# 抑制开关: AG_SUPPRESS_HOST_CONTEXT=1 → 强制 none + suppressed 标记
#   （selftest/e2e 注入抑制的确定性入口, 方案 §3.7; 非交互判定的运行时
#    语义判定仍归编排层, 此环境变量只服务确定性测试环境）
HOST_PROJECT_KIND="none"
HOST_CTX_SECTION_FILE="${WORK_DIR}/host-project-section.yaml"
rm -f "$HOST_CTX_SECTION_FILE"
if [ -n "${PYTHON_BIN:-}" ]; then
  HOST_SUPPRESSED="${AG_SUPPRESS_HOST_CONTEXT:+true}" \
  HOST_CTX_OUT="$HOST_CTX_SECTION_FILE" \
  "$PYTHON_BIN" - > /dev/null 2>&1 <<'PY' && HOST_PROJECT_KIND="$(grep -m1 'project_kind' "$HOST_CTX_SECTION_FILE" 2>/dev/null | sed 's/.*"\(.*\)"/\1/')"
import os

def detect_kind():
    # 判定收窄（方案 R-4）; dsh 特征锚定 platforms/dsh.yaml host_constraints
    if os.path.isfile("CLAUDE.md") or os.path.isdir(".claude"):
        return "claude_code"
    if os.path.isdir(".dsh") or os.path.isfile("AGENTS.md") or os.path.isfile("cordis.patch.yml"):
        return "dsh"
    return "none"

def describe(path):
    # 机械截取 frontmatter description, 失败留空（fail-open）
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            in_fm = False
            for raw in f:
                line = raw.strip()
                if line == "---":
                    if in_fm:
                        break
                    in_fm = True
                    continue
                if in_fm and line.startswith("description:"):
                    return line.split(":", 1)[1].strip().strip('"')[:120]
        return ""
    except OSError:
        return ""

def yaml_list(entries, indent):
    lines = []
    for e in entries:
        lines.append(f"{indent}- name: \"{e['name']}\"")
        lines.append(f"{indent}  path: \"{e['path']}\"")
        lines.append(f"{indent}  description: \"{e['description']}\"")
    return lines

def scan_agents(base):
    out = []
    try:
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name)
            if os.path.isdir(p):
                out.append({"name": name, "path": p, "description": describe(os.path.join(p, "CLAUDE.md"))})
            elif name.endswith(".md"):
                out.append({"name": name[:-3], "path": p, "description": describe(p)})
    except OSError:
        pass
    return out

def scan_skills(base):
    out = []
    try:
        for name in sorted(os.listdir(base)):
            p = os.path.join(base, name)
            if os.path.isdir(p):
                out.append({"name": name, "path": p, "description": describe(os.path.join(p, "SKILL.md"))})
    except OSError:
        pass
    return out

suppressed = os.environ.get("HOST_SUPPRESSED") == "true"
kind = "none" if suppressed else detect_kind()
agents, skills = [], []
if kind != "none":
    seen = set()
    for base in ("output/agents", ".claude/agents"):
        for e in scan_agents(base):
            if e["path"] not in seen:
                seen.add(e["path"])
                agents.append(e)
    seen = set()
    for base in ("output/skills", ".claude/skills"):
        for e in scan_skills(base):
            if e["path"] not in seen:
                seen.add(e["path"])
                skills.append(e)

out_path = os.environ.get("HOST_CTX_OUT", "host-project-section.yaml")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("host_project:\n")
    f.write("  in_project: %s\n" % ("true" if kind != "none" else "false"))
    f.write("  project_kind: \"%s\"\n" % kind)
    f.write("  suppressed: \"%s\"\n" % ("true" if suppressed else "false"))
    if agents:
        f.write("  existing_agents:\n")
        f.write("\n".join(yaml_list(agents, "    ")) + "\n")
    else:
        f.write("  existing_agents: []\n")
    if skills:
        f.write("  existing_skills:\n")
        f.write("\n".join(yaml_list(skills, "    ")) + "\n")
    else:
        f.write("  existing_skills: []\n")
PY
fi

# 写 env-readiness.yaml（host_project 段独立生成后拼入, 段失败不影响主体——fail-open）
{
  printf 'env_readiness:\n'
  printf '  generated_at: "%s"\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '  name: "%s"\n' "$NAME"
  printf '  host: "%s"\n' "$HOST"
  printf '  plugin_root: "%s"\n' "$PLUGIN_ROOT"
  printf '  python: "%s"\n' "$PYTHON_DESC"
  printf '  tools:\n%s' "$TOOLS_YAML"
  printf '  issues_count: %d\n' "${#failures[@]}"
  printf '  failures: [%s]\n' "$(IFS=,; echo "${failures[*]}")"
  printf '  recommended_missing: [%s]\n' "$(IFS=,; echo "${recommended_missing[*]}")"
} > "$OUT"
if [ -f "$HOST_CTX_SECTION_FILE" ]; then
  cat "$HOST_CTX_SECTION_FILE" >> "$OUT"
fi

if [[ ${#failures[@]} -gt 0 ]]; then
  printf '{"env_readiness_path": "%s", "status": "FAIL", "host": "%s", "host_project_kind": "%s", "failures": [%s]}\n' \
    "$OUT" "$HOST" "$HOST_PROJECT_KIND" "$(IFS=,; echo "${failures[*]}")"
  exit 2
fi

printf '{"env_readiness_path": "%s", "status": "PASS", "host": "%s", "host_project_kind": "%s", "failures": []}\n' "$OUT" "$HOST" "$HOST_PROJECT_KIND"
