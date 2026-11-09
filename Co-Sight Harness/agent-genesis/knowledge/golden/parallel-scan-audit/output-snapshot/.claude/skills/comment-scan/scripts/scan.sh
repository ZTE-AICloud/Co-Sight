#!/bin/bash
# comment-scan: 待办类标记 + 空注释块（只读; 模式变量相邻字符串拼接; findings 临时文件收集）
set -euo pipefail
DIR="${1:?目标目录}"; OUT="${2:?输出路径}"
[ -d "$DIR" ] || { echo "错误: 目标目录不存在: $DIR" >&2; exit 2; }
TMPD=$(mktemp -d); trap 'rm -rf "$TMPD"' EXIT
TO_DO_PATTERN='TO''DO'; FIX_ME_PATTERN='FIX''ME'; TO_BE_PATTERN='TB''D'
while IFS= read -r -d '' f; do
  rel="${f#"$DIR"/}"
  { grep -nE "\\b(${TO_DO_PATTERN}|${FIX_ME_PATTERN}|${TO_BE_PATTERN})\\b" "$f" 2>/dev/null || true; } | while IFS=: read -r ln txt; do
    printf '%s\t%s\tbacklog_marker\t%s\n' "$rel" "$ln" "$(echo "$txt" | cut -c1-50)" >> "$TMPD/items.txt"
  done
  awk 'BEGIN{c=0;s=0} /^#[[:space:]]*$/{if(c==0)s=NR;c++;next} {if(c>=2)print s, c; c=0} END{if(c>=2)print s, c}' "$f" 2>/dev/null | while read -r s c; do
    printf '%s\t%s\tempty_comment_block\t连续 %s 行空注释\n' "$rel" "$s" "$c" >> "$TMPD/items.txt"
  done
done < <(find "$DIR" -type f -print0)
python3 - "$TMPD/items.txt" "$OUT" <<'PY'
import json, sys, os
items = []
if os.path.exists(sys.argv[1]):
    for l in open(sys.argv[1]):
        parts = l.rstrip("\n").split("\t", 3)
        if len(parts) == 4:
            items.append({"path": parts[0], "line": parts[1], "rule": parts[2],
                          "excerpt": parts[3].replace("\t", " ")})
json.dump(items, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
PY
