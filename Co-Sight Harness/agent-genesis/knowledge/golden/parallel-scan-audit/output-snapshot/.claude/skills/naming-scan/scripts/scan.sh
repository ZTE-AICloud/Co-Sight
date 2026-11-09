#!/bin/bash
# naming-scan: 标识符风格混用 + 超长标识符（通用文本规则, 只读; findings 经临时文件收集规避子 shell 状态）
set -euo pipefail
DIR="${1:?目标目录}"; OUT="${2:?输出路径}"
[ -d "$DIR" ] || { echo "错误: 目标目录不存在: $DIR" >&2; exit 2; }
TMPD=$(mktemp -d); trap 'rm -rf "$TMPD"' EXIT
SNAKE_RE='[a-z][a-z0-9]*_[a-z0-9_]*'; CAMEL_RE='[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*'
while IFS= read -r -d '' f; do
  snake=$(grep -cE "\\b${SNAKE_RE}\\b" "$f" || true)
  camel=$(grep -cE "\\b${CAMEL_RE}\\b" "$f" || true)
  rel="${f#"$DIR"/}"
  if [ "$snake" -gt 0 ] && [ "$camel" -gt 0 ]; then
    line=$(grep -nE "\\b${CAMEL_RE}\\b" "$f" | head -1 | cut -d: -f1)
    ex=$(grep -m1 -oE "\\b${CAMEL_RE}\\b" "$f" || true)
    printf '%s\t%s\tmixed_style\t%s\n' "$rel" "$line" "$ex" >> "$TMPD/items.txt"
  fi
  { grep -nE "\\b[A-Za-z_][A-Za-z0-9_]{71,}\\b" "$f" 2>/dev/null || true; } | while IFS=: read -r ln _; do
    ex=$(sed -n "${ln}p" "$f" | grep -oE "\\b[A-Za-z_][A-Za-z0-9_]{71,}\\b" | head -1)
    printf '%s\t%s\toversize_identifier\t%s\n' "$rel" "$ln" "$ex" >> "$TMPD/items.txt"
  done
done < <(find "$DIR" -type f \( -name '*.py' -o -name '*.sh' -o -name '*.ts' -o -name '*.js' -o -name '*.go' -o -name '*.md' \) -print0)
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
