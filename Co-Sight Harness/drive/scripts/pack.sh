#!/usr/bin/env bash
# 打包插件为可分发的 tar.gz。
#
# 用法:
#   ./scripts/pack.sh                 # 产物: dist/drive-v<version>-<utc-ts>.tar.gz
#   ./scripts/pack.sh --out-dir DIR   # 换输出目录
#
# 版本号取自 .claude-plugin/plugin.json，单一真相源。

set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$PLUGIN_DIR/dist"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out-dir) OUT_DIR="$2"; shift 2 ;;
        -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

MANIFEST="$PLUGIN_DIR/.claude-plugin/plugin.json"
if [[ ! -f "$MANIFEST" ]]; then
    echo "缺少 $MANIFEST —— 版本号无处可取" >&2
    exit 1
fi

# 官方校验器优先：它认识 manifest schema 的全部字段与组件约定，能抓到
# 手写检查看不出的问题（如 agents/ 下混入非 agent 的 .md）。
#
# 两个 manifest 都要显式校验。marketplace.json 与 plugin.json 同在
# .claude-plugin/ 时，把目录传给校验器只会校验 marketplace，plugin 层的组件
# 检查被跳过且不提示 —— 那样等于白校验。
if command -v claude >/dev/null 2>&1; then
    for manifest in \
        "$PLUGIN_DIR/.claude-plugin/plugin.json" \
        "$PLUGIN_DIR/.claude-plugin/marketplace.json"
    do
        [[ -f "$manifest" ]] || continue
        if ! claude plugin validate "$manifest" --strict; then
            echo "$(basename "$manifest") 校验未通过，不打包" >&2
            exit 1
        fi
    done
else
    echo "警告: 未找到 claude CLI，跳过 plugin validate" >&2
fi

VERSION="$(python3 -c "
import json, sys
v = json.load(open('$MANIFEST'))['version']
print(v[1:] if v.startswith('v') else v)
")"

# version 含路径分隔符会让 tar 误当子目录，直接拒绝
if [[ "$VERSION" =~ [/\\:*?\"\<\>\|] || -z "$VERSION" ]]; then
    echo "非法 version: '$VERSION'" >&2
    exit 1
fi

TIMESTAMP="$(date -u +%y%m%d%H%M)"
ARCHIVE_NAME="drive-v${VERSION}-${TIMESTAMP}.tar.gz"
ARCHIVE_PATH="$OUT_DIR/$ARCHIVE_NAME"

mkdir -p "$OUT_DIR"

# 运行时需要的：skills / agents / hooks / plugin 清单。
# tests 与 dist 不进包 —— 用户装的是插件，不是开发环境。
EXCLUDES=(
    --exclude='.git'
    --exclude='__pycache__'
    --exclude='.pytest_cache'
    --exclude='.ruff_cache'
    --exclude='dist'
    --exclude='tests'
    --exclude='legacy'
    --exclude='*.pyc'
    --exclude='*.pyo'
    --exclude='.coverage'
    --exclude='.DS_Store'
)

tar -czf "$ARCHIVE_PATH" -C "$PLUGIN_DIR" "${EXCLUDES[@]}" \
    .claude-plugin skills agents hooks README.md

echo "$ARCHIVE_PATH"
