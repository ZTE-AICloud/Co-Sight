#!/usr/bin/env bash
# 批次 3 验证门（提速方案批次 4: OPT-2b + OPT-8b）——合成用例，全部通过输出 ALL PASS
# 覆盖: G028 三 profile 通过/拒绝态、profile 条件必填 fail-closed、引用闭合正反例、
#        C8-4 畸形输入负例、C8-2 仓外对拍、OPT-2b 三态
# 用法: bash tests/speedup/batch3-verify.sh   （在仓库根执行）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { if [ "$2" -eq "$3" ]; then ok "$1 (rc=$3)"; else bad "$1 (期望 rc=$2, 实际 rc=$3)"; fi; }
check_json() {
  if echo "$3" | python3 -I -c "import json,sys; d=json.load(sys.stdin); assert ($2), d" 2>/dev/null; then
    ok "$1"
  else
    bad "$1 —— got: $(echo "$3" | head -c 300)"
  fi
}
G028="scripts/gates/g028-exit-sanity.sh"

# ── 搭建合成产物目录（满足 agent-exit 全链）──
PROD="$TMP/prod"
mkdir -p "$PROD/.claude/skills/my-skill" "$PROD/.claude/rules" "$PROD/phase/gates" "$PROD/phase/02-workflows" "$PROD/scripts"
printf -- '# CLAUDE.md 总览\n\n本文件为运行时主交付轻量总览（合成用例, 满足 g021 ≥100 字节阈值）。\n版本 v1, 自动化级别 L2, 预算与标签从略。\n' > "$PROD/CLAUDE.md"
printf -- '---\nname: my-skill\ndescription: x\n---\nbody\n' > "$PROD/.claude/skills/my-skill/SKILL.md"
# skill-build/skill-verify 档以 target 根 SKILL.md 为主交付（module.skill.static 契约:
# frontmatter 三字段 + ≥50 行 + references 闭合）——合成件补齐, 修 skill_static 落地时
# 本套件漏更新的存量缺口
mkdir -p "$PROD/references"
{ printf -- '---\nname: my-skill-root\ndescription: "合成用例根 skill（skill 两档主交付）。"\nversion: "1.0.0"\n---\n# My Skill Root\n'
  printf '正文行。\n%.0s' $(seq 1 55)
  printf '详见 references/guide.md。\n'; } > "$PROD/SKILL.md"
printf '# Guide\n\n内容。\n' > "$PROD/references/guide.md"
printf -- '> This file extends common/x.md\n' > "$PROD/.claude/rules/r1.md"
printf -- '# G028 stub\n' > "$PROD/phase/gates/G028-exit-sanity.md"
printf -- '步骤引用 .claude/skills/my-skill 与 .claude/rules/r1.md\n' > "$PROD/phase/02-workflows/main.md"
mkdir -p "$TMP/work"
printf -- '{"name":"x","done":[],"failed":[]}\n' > "$TMP/work/progress.json"
printf -- '# execution-report\n\n## overall\nPASS\n\n## per_file_status\nall done\n\n## blockers\nnone\n' > "$TMP/work/phase4-execution-report.md"
cat > "$TMP/bp.md" <<'EOF'
# build-plan（合成）
files:

```yaml
path: CLAUDE.md
type: generate
invariants: []
```
EOF
# 全形态超集落一份（合法超集——过地板 + 方案保真两层即可; required_files 清单复检
# 已于 2026-10-16 从 g028 撤出, 全形态仍保留以覆盖引用闭合等扫描面; 文件写非空内容,
# 目录型建目录）
python3 - "$PROD" <<'PY'
import os, sys, yaml
std = yaml.safe_load(open(os.path.join(os.getcwd(), "knowledge/agent-creation/agent-output-standard.yaml")))
prod = sys.argv[1]
for e in std.get("required_files") or []:
    t = (e or {}).get("target", "")
    if not t or "{" in t:
        continue
    p = os.path.join(prod, t.rstrip("/"))
    if t.endswith("/"):
        os.makedirs(p, exist_ok=True)
    else:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        if not os.path.exists(p):  # 不覆盖已写入的非空内容（如 ≥100B 的 CLAUDE.md）
            open(p, "w").write("# stub\n")
PY

echo "══ G028 三 profile ══"
out=$(echo "{\"gates\":[\"G028\"],\"profile\":\"agent-exit\",\"build_plan\":\"$TMP/bp.md\",\"output_dir\":\"$PROD\",\"target\":\"$PROD\",\"work_dir\":\"$TMP/work\",\"skills_dir\":\"$PROD/.claude/skills\",\"rules_dir\":\"$PROD/.claude/rules\"}" | bash "$G028"); rc=$?
check "agent-exit 全链 PASS" 0 "$rc"
check_json "verdict=PASS 且 profile 回显" "d['verdict']=='PASS' and d['profile']=='agent-exit'" "$out"
out=$(echo "{\"gates\":[\"G028\"],\"profile\":\"skill-build\",\"skills_dir\":\"$PROD/.claude/skills\",\"rules_dir\":\"$PROD/.claude/rules\",\"target\":\"$PROD\"}" | bash "$G028"); rc=$?
check "skill-build 档 PASS" 0 "$rc"
out=$(echo '{"gates":["G028"],"profile":"skill-verify","target":"'"$PROD"'"}' | bash "$G028"); rc=$?
check "skill-verify 档 PASS" 0 "$rc"

echo "══ G028 profile 条件必填 fail-closed ══"
out=$(echo "{\"gates\":[\"G028\"],\"profile\":\"agent-exit\",\"output_dir\":\"$PROD\",\"target\":\"$PROD\"}" | bash "$G028"); rc=$?
check "agent-exit 缺 work_dir/skills_dir/rules_dir/build_plan → FAIL" 2 "$rc"
check_json "type=input_error + missing_keys 列明" "d['failures'][0]['type']=='input_error' and 'work_dir' in d['failures'][0]['missing_keys']" "$out"
out=$(echo '{"gates":["G028"],"profile":"nope","output_dir":"x"}' | bash "$G028"); rc=$?
check "非法 profile → FAIL" 2 "$rc"
out=$(echo '{"gates":["G028"],"profile":"skill-build"}' | bash "$G028"); rc=$?
check "缺 target/output_dir any_of → FAIL" 2 "$rc"

echo "══ 引用闭合正反例 ══"
printf -- '引用不存在的 .claude/skills/ghost-skill 与 gate G999\n' > "$PROD/phase/02-workflows/main.md"
out=$(echo "{\"gates\":[\"G028\"],\"profile\":\"agent-exit\",\"build_plan\":\"$TMP/bp.md\",\"output_dir\":\"$PROD\",\"target\":\"$PROD\",\"work_dir\":\"$TMP/work\",\"skills_dir\":\"$PROD/.claude/skills\",\"rules_dir\":\"$PROD/.claude/rules\"}" | bash "$G028"); rc=$?
check "幽灵 skill/gate 引用 → FAIL" 2 "$rc"
check_json "broken_skill_ref/broken_gate_ref 点名" "any(f['type']=='broken_skill_ref' for f in d['failures']) and any(f['type']=='broken_gate_ref' for f in d['failures'])" "$out"
printf -- '步骤引用 .claude/skills/my-skill 与 .claude/rules/r1.md\n' > "$PROD/phase/02-workflows/main.md"

echo "══ C8-4 畸形输入负例（≥3）══"
out=$(printf 'not json' | bash "$G028"); rc=$?
check "非 JSON → FAIL" 2 "$rc"
check_json "input_error 类型" "d['failures'][0]['type']=='input_error'" "$out"
out=$(echo '{"gates":["G028"],"profile":"","output_dir":"x"}' | bash "$G028"); rc=$?
check "空 profile → FAIL" 2 "$rc"
out=$(python3 -c "print('{\"gates\":[\"G028\"],\"profile\":\"agent-exit\",\"build_plan\":\"'+('a'*5000)+'\",\"output_dir\":\"y\"}')" | bash "$G028"); rc=$?
check "超长路径 → FAIL 不崩溃" 2 "$rc"

echo "══ C8-2 仓外对拍 ══"
out=$(cd "$TMP" && echo "{\"gates\":[\"G028\"],\"profile\":\"skill-verify\",\"target\":\"$PROD\"}" | bash "$REPO_ROOT/$G028"); rc=$?
check "仓外目录跑 G028 → PASS（路径 SCRIPT_DIR 锚定）" 0 "$rc"

echo "══ registry / 语法全链 ══"
bash scripts/check-gate-registry.sh >/dev/null 2>&1 && ok "check-gate-registry PASS（含 G028）" || { bad "check-gate-registry"; bash scripts/check-gate-registry.sh; }
syn=0
for f in scripts/gates/*.sh scripts/gates/g028-exit-sanity.sh tests/speedup/batch3-verify.sh; do
  if ! bash -n "$f" 2>/dev/null; then bad "bash -n: $f"; syn=1; fi
done
[ "$syn" -eq 0 ] && ok "全部脚本 bash -n 通过"

echo
echo "════════ PASS=$PASS FAIL=$FAIL ════════"
[ "$FAIL" -eq 0 ] && echo "ALL PASS" || exit 1
