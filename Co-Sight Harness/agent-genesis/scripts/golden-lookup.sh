#!/usr/bin/env bash
# scripts/golden-lookup.sh — golden 池检索脚本（方案 §4 G1; 检索规则权威 = INDEX.yaml）
# 键域 = INDEX.yaml lookup.key_domain（11 核心全 id, 含 W2-Router; 拓扑模式非检索键）
# 多命中 → INDEX.yaml lookup.multi_hit_rule = acceptance_items_max（manifest.acceptance 条数多者优先）
# 未命中/异常 → "NONE"（miss_behavior: NONE_fail_closed, 不阻塞构建, R2）
# 消费方: fast 车道 few-shot 注入（workflow-fast.md 步骤 2; agents/fast-lane-builder.md 输入④）
# 协议: 输入 mode_id（argv[1] 或 stdin JSON {"mode_id": "..."}）→ stdout 包相对路径或 NONE → exit 0
# 包相对路径 = 相对插件根（main agent 拼 {PLUGIN_ROOT}/ 前缀）, 未命中 = 字面 NONE
# fail-closed: INDEX.yaml 缺失/解析失败/键域校验失败 → NONE（禁静默 fallback 到 fixtures）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INDEX="$PLUGIN_ROOT/knowledge/golden/INDEX.yaml"

# 输入: argv[1] 优先, 否则 stdin JSON（{"mode_id": "..."} 或裸字符串全 id）
MODE_ID="${1:-}"
if [[ -z "$MODE_ID" ]]; then
  if [[ ! -t 0 ]]; then
    INPUT=$(cat 2>/dev/null || true)
    MODE_ID=$(echo "$INPUT" | jq -r '.mode_id // empty' 2>/dev/null || true)
    [[ -z "$MODE_ID" ]] && MODE_ID=$(echo "$INPUT" | tr -d '[:space:]' | head -c 200)
  fi
fi
MODE_ID=$(echo "$MODE_ID" | tr -d '[:space:]')

# fail-closed: INDEX.yaml 不存在 → NONE
if [[ ! -f "$INDEX" ]]; then
  echo "NONE"
  exit 0
fi

# 包根 = INDEX 所在目录（manifest 同侧解析, 单源; 禁再拼 PLUGIN_ROOT 双路径）
GOLDEN_DIR="$(cd "$(dirname "$INDEX")" && pwd)"

python3 - "$GOLDEN_DIR" "$INDEX" "$MODE_ID" <<'PY'
import os, re, sys

golden_dir, index_path, mode_id = sys.argv[1], sys.argv[2], sys.argv[3]

def none():
    print("NONE")
    sys.exit(0)

try:
    index = open(index_path, encoding="utf-8").read()
except OSError:
    none()

# key_domain 显式名单段
m = re.search(r"key_domain:(.*?)(?=\n  \w|\n\n|\Z)", index, re.S)
if not m:
    none()
key_domain = re.findall(r'-\s+([A-Za-z0-9_-]+)', m.group(1))
if not key_domain:
    none()

# mode_id 不在键域 → NONE（fail-closed, 键外不做部分匹配）
if not mode_id or mode_id not in key_domain:
    none()

# pool 段: task_tag: {mode_id: X, line: Y}
m = re.search(r"^pool:\s*\n(.*?)(?=^\S|\Z)", index, re.S | re.M)
if not m:
    none()
entries = {}
for line in m.group(1).splitlines():
    line = line.split("#", 1)[0].rstrip()
    if not line.strip():
        continue
    tag_mm = re.match(r"^\s+([A-Za-z0-9_-]+):\s*\{(.*)\}\s*$", line)
    if not tag_mm:
        continue
    tag, body = tag_mm.group(1), tag_mm.group(2)
    mid = re.search(r"mode_id:\s*([A-Za-z0-9_-]+)", body)
    if mid:
        entries[tag] = mid.group(1)

hits = [tag for tag, mid in entries.items() if mid == mode_id]
if not hits:
    none()

if len(hits) == 1:
    print(f"knowledge/golden/{hits[0]}")
    sys.exit(0)

# multi_hit_rule = acceptance_items_max: manifest.acceptance 条数多者优先
def acceptance_count(tag):
    mf = os.path.join(golden_dir, "golden", tag, "manifest.yaml")
    try:
        txt = open(mf, encoding="utf-8").read()
    except OSError:
        return -1  # manifest 缺失视为零条, 让位给可计数的包
    m2 = re.search(r"^acceptance:\s*\n((?:\s*-\s+.*\n?)+)", txt, re.M)
    if not m2:
        return 0
    return len(re.findall(r"^\s*-\s+\S", m2.group(1), re.M))

counts = {tag: acceptance_count(tag) for tag in hits}
best = max(counts.values())
winners = [t for t, c in counts.items() if c == best]
# 再平 → 词典序首个（确定性, 禁随机）
print(f"knowledge/golden/{sorted(winners)[0]}")
PY
