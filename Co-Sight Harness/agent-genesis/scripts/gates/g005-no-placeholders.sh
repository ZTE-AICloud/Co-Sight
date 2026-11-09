#!/bin/bash
# G005: 产物目录无残留占位符（模板 {{...}} / TODO|TBD|FIXME|XXX / 待补充|待定|待填写）
# 协议: --target <dir> 为 canonical；stdin JSON {"output_dir": ...} 为 fallback
# stdout JSON → exit 0(PASS)/2(FAIL)
# 语义与 scripts/phase1-blocker-check.sh B3 对齐（三类模式同源），扫描扩展为整目录；
# 与 B3 的唯一差异：「待确认」不在此列（真实产物将其作合法状态名，见文件内注）。
set -euo pipefail

TARGET=""
EXCLUDES=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)  TARGET="${2:-}"; shift 2 ;;
    # --exclude <相对路径>: 可重复；预置资产（Step 1b 注入）等非 LLM 产物目录豁免
    --exclude) [[ -n "${2:-}" ]] && EXCLUDES+=("$2"); shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  INPUT=$(cat)
  TARGET=$(echo "$INPUT" | jq -r '.output_dir // .target // ""' 2>/dev/null || echo "")
  while IFS= read -r p; do
    if [[ -n "$p" && "$p" != "null" ]]; then EXCLUDES+=("$p"); fi
  done <<< "$(echo "$INPUT" | jq -r '(.excluded_paths // .exclude_paths // [])[]' 2>/dev/null || true)"
fi

if [[ -z "$TARGET" ]] || [[ "$TARGET" == "null" ]] || [[ ! -d "$TARGET" ]]; then
  echo "{\"gate_id\":\"G005\",\"verdict\":\"FAIL\",\"failures\":[{\"type\":\"missing_target_dir\",\"path\":\"$TARGET\"}]}"
  exit 2
fi

python3 - "$TARGET" ${EXCLUDES[@]+"${EXCLUDES[@]}"} <<'PY'
import json, os, re, sys

target = sys.argv[1]


def norm_rel(p):
    return p.replace("\\", "/").strip().rstrip("/")


EXCLUDED = [x for x in (norm_rel(a) for a in sys.argv[2:]) if x]


def is_excluded(rel):
    rel = norm_rel(rel)
    return any(rel == x or rel.startswith(x + "/") for x in EXCLUDED)

# 与 B3 同源的三类模式
PATTERNS = [
    ("template_placeholder", re.compile(r"\{\{[^}]+\}\}")),
    # 大小写不敏感（补 todo: 小写漏检，gate 治理阶段 3）
    ("todo_marker", re.compile(r"(^|[^A-Za-z])(TODO|TBD|FIXME|XXX)([^A-Za-z]|$)", re.I)),
    # 注: 「待确认」刻意排除——真实产物常将其作合法工作流状态名（demo/test11
    # 重放实证 37 处全为领域词汇），属占位符语义的是 待补充/待定/待填写。
    # 「待定」加前向词边界: 排除 等待定义/期待定制 等正常中文语流误报（阶段 3）
    ("cn_placeholder", re.compile(r"待补充|待填写|(?<![等期])待定")),
]

# 二进制扩展名与目录排除（扫描文本产物，跳过非文本资产）
BINARY_EXT = {
    ".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pptx", ".ppt", ".docx", ".doc", ".xlsx", ".xls", ".pdf", ".zip", ".gz",
    ".bz2", ".xz", ".7z", ".tar", ".jar", ".class", ".so", ".dll", ".exe",
    ".bin", ".dat", ".db", ".sqlite", ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4",
}
EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}

MAX_REPORT = 20
failures = []

for root, dirs, files in os.walk(target):
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS
               and not is_excluded(os.path.relpath(os.path.join(root, d), target))]
    for fname in sorted(files):
        ext = os.path.splitext(fname)[1].lower()
        if ext in BINARY_EXT:
            continue
        fpath = os.path.join(root, fname)
        rel = os.path.relpath(fpath, target)
        if is_excluded(rel):
            continue
        try:
            with open(fpath, encoding="utf-8", errors="strict") as f:
                lines = f.readlines()
        except (UnicodeDecodeError, OSError):
            continue  # 非 UTF-8 文本（二进制 disguised），跳过
        for lineno, line in enumerate(lines, 1):
            for ptype, pat in PATTERNS:
                if pat.search(line):
                    snippet = line.strip()[:120]
                    failures.append({"type": ptype, "file": rel,
                                     "line": lineno, "snippet": snippet})
                    break  # 每行只报首个命中类型，避免单行刷屏

if failures:
    print(json.dumps({"gate_id": "gate.deliver.placeholder", "verdict": "FAIL",
                      "total": len(failures),
                      "failures": failures[:MAX_REPORT]}, ensure_ascii=False))
    sys.exit(2)

print(json.dumps({"gate_id": "gate.deliver.placeholder", "verdict": "PASS",
                  "summary": "no placeholders in output tree"}, ensure_ascii=False))
sys.exit(0)
PY
