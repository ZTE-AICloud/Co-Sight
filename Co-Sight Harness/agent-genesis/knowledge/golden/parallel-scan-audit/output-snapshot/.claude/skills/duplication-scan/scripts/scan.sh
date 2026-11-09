#!/bin/bash
# duplication-scan: 连续重复行块 ≥3 行（只读, 通用文本规则; findings 临时文件收集）
set -euo pipefail
DIR="${1:?目标目录}"; OUT="${2:?输出路径}"
[ -d "$DIR" ] || { echo "错误: 目标目录不存在: $DIR" >&2; exit 2; }
TMPD=$(mktemp -d); trap 'rm -rf "$TMPD"' EXIT
while IFS= read -r -d '' f; do
  rel="${f#"$DIR"/}"
  awk '
    { lines[NR]=$0 }
    END {
      run=1; start=1
      for (i=2; i<=NR; i++) {
        if (lines[i]==lines[i-1] && lines[i]!~/^[[:space:]]*$/) { if(run==1) start=i-1; run++ }
        else { if (run>=3) printf "%s %d %s\n", FILENAME, start, lines[start]; run=1 }
      }
      if (run>=3) printf "%s %d %s\n", FILENAME, start, lines[start]
    }' "$f" 2>/dev/null | while read -r p s ex; do
      printf '%s\t%s\tduplicate_block\t%s\n' "$rel" "$s" "$ex" >> "$TMPD/items.txt"
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
