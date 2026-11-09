#!/usr/bin/env bash
# check-delta-scope — optimize 改动范围机检（fast lane optimize 安全三件之二, 方案 §4.0）
# 判定: 快照与目标的 diff 文件集 ⊆ 点名清单（allowlist）即 PASS; 越界 FAIL 列出越界文件。
# 消费: skill 线 step-sf2 / agent 线 step-f2（FB/FC 共用规格, 禁各自变体）
# 协议: bash check-delta-scope.sh --snapshot <快照目录> --target <目标目录> --allowlist <清单文件>
#   清单文件: 每行一个相对路径（# 注释与空行忽略）
# 退出码: 0=PASS / 2=FAIL（越界或输入错误, type=scope_violation|input_error）
# fail-closed: 参数缺失/目录不存在/清单不可读 → input_error, 禁静默跳过（C8-1）
set -euo pipefail

SNAPSHOT=""; TARGET=""; ALLOWLIST=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --snapshot)  SNAPSHOT="$2"; shift 2 ;;
    --target)    TARGET="$2"; shift 2 ;;
    --allowlist) ALLOWLIST="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

emit_json() { # emit_json <verdict> <python表达式构造failures>
  python3 - "$@" <<'PY'
import json, sys
print(json.dumps({"gate_id": "check-delta-scope", "verdict": sys.argv[1],
                  "failures": json.loads(sys.argv[2])}, ensure_ascii=False))
PY
}

fail_closed() { # fail_closed <detail>
  emit_json "FAIL" "[{\"type\": \"input_error\", \"detail\": \"$1\"}]" >&2
  exit 2
}

[[ -n "$SNAPSHOT" && -n "$TARGET" && -n "$ALLOWLIST" ]] || fail_closed "缺参数（须 --snapshot/--target/--allowlist 三全）"
[[ -d "$SNAPSHOT" ]] || fail_closed "快照目录不存在: $SNAPSHOT"
[[ -d "$TARGET" ]] || fail_closed "目标目录不存在: $TARGET"
[[ -f "$ALLOWLIST" ]] || fail_closed "清单文件不存在: $ALLOWLIST"

SNAPSHOT="$(cd "$SNAPSHOT" && pwd)"; TARGET="$(cd "$TARGET" && pwd)"

# 两遍法: walk 两树收集变更文件集（新增∪删除∪内容修改）, 对照 allowlist
python3 - "$SNAPSHOT" "$TARGET" "$ALLOWLIST" <<'PY'
import filecmp, os, sys, json

snapshot, target, allowlist = sys.argv[1], sys.argv[2], sys.argv[3]

def walk_files(root):
    out = {}
    for dp, _, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            out[os.path.relpath(p, root)] = p
    return out

allow = set()
for line in open(allowlist, encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#"):
        allow.add(line)

snap_files = walk_files(snapshot)
tgt_files = walk_files(target)
changed = set(tgt_files) - set(snap_files)          # 新增
changed |= set(snap_files) - set(tgt_files)         # 删除
for rel in set(snap_files) & set(tgt_files):        # 内容修改
    if not filecmp.cmp(snap_files[rel], tgt_files[rel], shallow=False):
        changed.add(rel)

violations = sorted(c for c in changed if c not in allow)
result = {"gate_id": "check-delta-scope",
          "changed_files": sorted(changed),
          "allowlist_size": len(allow)}
if violations:
    result["verdict"] = "FAIL"
    result["failures"] = [{"type": "scope_violation", "file": v,
                           "reason": "改动越出点名清单（allowlist）"} for v in violations]
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(2)
result["verdict"] = "PASS"
result["failures"] = []
print(json.dumps(result, ensure_ascii=False))
PY
