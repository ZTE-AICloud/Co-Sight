#!/usr/bin/env bash
# AgentGenesis 版本号自动更新脚本
# 用法: ./scripts/bump-version.sh <major|minor|patch>
# 更新目标: .claude-plugin/plugin.json + work/progress-state.yaml
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
PLUGIN_JSON="$ROOT_DIR/.claude-plugin/plugin.json"
PROGRESS_YAML="$ROOT_DIR/work/progress-state.yaml"

log()  { echo "[bump-version] $*"; }
err()  { echo "[bump-version] ERROR: $*" >&2; exit 1; }

usage() {
    cat <<EOF
用法: bump-version.sh <major|minor|patch>

  更新 .claude-plugin/plugin.json 和 work/progress-state.yaml 中的版本号。
  plugin.json 为唯一版本源，progress-state.yaml 同步更新。

示例:
  ./scripts/bump-version.sh patch   # 0.4.0 → 0.4.1
  ./scripts/bump-version.sh minor   # 0.4.0 → 0.5.0
  ./scripts/bump-version.sh major   # 0.4.0 → 1.0.0
EOF
    exit 0
}

# 解析版本号 "X.Y.Z" → 数组
parse_version() {
    local v="$1"
    local major minor patch
    IFS='.' read -r major minor patch <<< "$v"
    echo "$major $minor $patch"
}

bump() {
    local current="$1"
    local level="$2"
    read -r major minor patch <<< "$(parse_version "$current")"

    case "$level" in
        major)
            major=$((major + 1))
            minor=0
            patch=0
            ;;
        minor)
            minor=$((minor + 1))
            patch=0
            ;;
        patch)
            patch=$((patch + 1))
            ;;
        *)
            err "未知版本级别: $level (必须是 major|minor|patch)"
            ;;
    esac
    echo "$major.$minor.$patch"
}

# === Main ===
LEVEL="${1:-}"
if [[ -z "$LEVEL" || "$LEVEL" == "-h" || "$LEVEL" == "--help" ]]; then
    usage
fi
if [[ "$LEVEL" != "major" && "$LEVEL" != "minor" && "$LEVEL" != "patch" ]]; then
    err "无效版本级别: '$LEVEL' (必须是 major|minor|patch)"
fi

# 1. 从 plugin.json 读取当前版本
if [[ ! -f "$PLUGIN_JSON" ]]; then
    err "plugin.json 不存在: $PLUGIN_JSON"
fi

CURRENT_VERSION=$(python3 -c "
import json, sys
with open('$PLUGIN_JSON') as f:
    print(json.load(f)['version'])
" 2>/dev/null || true)
if [[ -z "$CURRENT_VERSION" ]]; then
    err "无法从 plugin.json 提取 version 字段"
fi

NEW_VERSION=$(bump "$CURRENT_VERSION" "$LEVEL")
log "$CURRENT_VERSION → $NEW_VERSION ($LEVEL)"

# 2. 更新 plugin.json
python3 -c "
import json
with open('$PLUGIN_JSON') as f:
    data = json.load(f)
data['version'] = '$NEW_VERSION'
with open('$PLUGIN_JSON', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write('\n')
"
log "已更新 plugin.json: version → $NEW_VERSION"

# 3. 更新 work/progress-state.yaml (如果存在)
if [[ -f "$PROGRESS_YAML" ]]; then
    sed -i "s/last_updated: \".*\"/last_updated: \"$(date -Iseconds)\"/" "$PROGRESS_YAML"
    log "已更新 progress-state.yaml: last_updated"
else
    log "跳过 progress-state.yaml (文件不存在)"
fi

log "版本更新完成: $CURRENT_VERSION → $NEW_VERSION"
