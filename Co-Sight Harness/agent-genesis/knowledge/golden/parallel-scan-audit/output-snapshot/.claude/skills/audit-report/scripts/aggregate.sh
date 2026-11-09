#!/bin/bash
# audit-report: 合并三路 findings JSON → audit-report.md（确定性合并, 无 LLM 判断）
set -euo pipefail
NAMING="${1:?naming findings}"; COMMENT="${2:?comment findings}"; DUP="${3:?dup findings}"; REPORT="${4:?报告路径}"
count() { python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$1"; }
section() { # section <标题> <findings文件> <规则译文>
  local n; n=$(count "$2")
  echo "## $1（${n} 项）"; echo
  if [ "$n" -gt 0 ]; then
    python3 -c '
import json,sys
for x in json.load(open(sys.argv[1])):
    print("- %s:%s [%s] %s" % (x["path"], x["line"], x["rule"], x.get("excerpt","")))' "$2"
  else
    echo "无命中。"
  fi
  echo
}
{
  echo "# 代码规范审查报告 — audit-report"
  echo
  section "命名维度" "$NAMING"
  section "注释维度" "$COMMENT"
  section "重复维度" "$DUP"
  echo "## 总结"
  echo
  echo "命名 $(count "$NAMING") / 注释 $(count "$COMMENT") / 重复 $(count "$DUP") — 共 $(( $(count "$NAMING") + $(count "$COMMENT") + $(count "$DUP") )) 项发现。"
} > "$REPORT"
