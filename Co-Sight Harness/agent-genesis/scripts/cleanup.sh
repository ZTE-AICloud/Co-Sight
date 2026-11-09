#!/usr/bin/env bash
# AgentGenesis 产物清理脚本
# 用法:
#   ./scripts/cleanup.sh --dry-run          预览将清理的文件
#   ./scripts/cleanup.sh --stale            移动 STALE 文件到 archive/
#   ./scripts/cleanup.sh --archive          删除超期 archive 文件
#   ./scripts/cleanup.sh --full             stale + archive 全流程
#   ./scripts/cleanup.sh --agent=<name>     只清理特定 Agent
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ARCHIVE_DIR="$ROOT_DIR/archive"
WORK_DIR="$ROOT_DIR/work"
STALE_DAYS=30
ARCHIVE_MAX_DAYS=90
DRY_RUN=false

log()  { echo "[cleanup] $*"; }
warn() { echo "[cleanup] WARN: $*" >&2; }
err()  { echo "[cleanup] ERROR: $*" >&2; exit 1; }

usage() {
    cat <<EOF
用法: cleanup.sh [选项]

选项:
  --dry-run          预览模式，不执行实际操作
  --stale            将 STALE 文件移动到 archive/
  --archive          删除超过 ${ARCHIVE_MAX_DAYS} 天的归档文件
  --full             stale + archive 全流程
  --agent=<name>     仅处理指定 Agent（默认处理全部）
  -h, --help         显示帮助

示例:
  ./scripts/cleanup.sh --dry-run
  ./scripts/cleanup.sh --stale
  ./scripts/cleanup.sh --full --agent=code-review-agent
EOF
    exit 0
}

now_ts() { date +%s; }

is_stale() {
    local file="$1"
    local mtime
    mtime=$(stat -c %Y "$file" 2>/dev/null || stat -f %m "$file" 2>/dev/null)
    local age=$(( $(now_ts) - mtime ))
    local stale_sec=$(( STALE_DAYS * 86400 ))
    [[ $age -gt $stale_sec ]]
}

move_to_archive() {
    local src="$1"
    local agent_name="$2"
    local date_str
    date_str=$(date -d "@$(stat -c %Y "$src" 2>/dev/null || stat -f %m "$src")" +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d)
    local dest="$ARCHIVE_DIR/$agent_name/$date_str/$(echo "$src" | sed 's|^\./||')"
    local dest_dir
    dest_dir=$(dirname "$dest")
    if $DRY_RUN; then
        log "DRY-RUN: mv $src → $dest"
    else
        mkdir -p "$dest_dir"
        mv "$src" "$dest"
        log "mv $src → $dest"
    fi
}

delete_old_archives() {
    local cutoff_ts=$(( $(now_ts) - ARCHIVE_MAX_DAYS * 86400 ))
    while IFS= read -r -d '' dir; do
        local dir_date
        dir_date=$(basename "$dir")
        if [[ "$dir_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
            local dir_ts
            dir_ts=$(date -d "$dir_date" +%s 2>/dev/null || echo 0)
            if [[ $dir_ts -lt $cutoff_ts && $dir_ts -ne 0 ]]; then
                if $DRY_RUN; then
                    log "DRY-RUN: rm -rf $dir (归档日期 $dir_date > ${ARCHIVE_MAX_DAYS}天前)"
                else
                    log "rm -rf $dir (归档日期 $dir_date > ${ARCHIVE_MAX_DAYS}天前)"
                    rm -rf "$dir"
                fi
            fi
        fi
    done < <(find "$ARCHIVE_DIR" -mindepth 2 -maxdepth 2 -type d -print0 2>/dev/null)
}

process_agent() {
    local agent_name="$1"
    log "处理 Agent: $agent_name"

    # 处理 work/ 目录
    local agent_work="$WORK_DIR/$agent_name"
    if [[ -d "$agent_work" ]]; then
        while IFS= read -r -d '' file; do
            if is_stale "$file"; then
                log "STALE: $file"
                move_to_archive "$file" "$agent_name"
            fi
        done < <(find "$agent_work" -type f -print0 2>/dev/null)
    fi

    # 处理 test-results/ 目录
    local agent_test="$ROOT_DIR/test-results/$agent_name"
    if [[ -d "$agent_test" ]]; then
        while IFS= read -r -d '' file; do
            if is_stale "$file"; then
                log "STALE: $file"
                move_to_archive "$file" "$agent_name"
            fi
        done < <(find "$agent_test" -type f -print0 2>/dev/null)
    fi
}

# === Main ===
STALE_MODE=false
ARCHIVE_MODE=false
TARGET_AGENT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --stale) STALE_MODE=true; shift ;;
        --archive) ARCHIVE_MODE=true; shift ;;
        --full) STALE_MODE=true; ARCHIVE_MODE=true; shift ;;
        --agent=*) TARGET_AGENT="${1#*=}"; shift ;;
        --agent) TARGET_AGENT="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) err "未知选项: $1 (使用 -h 查看帮助)" ;;
    esac
done

if ! $STALE_MODE && ! $ARCHIVE_MODE; then
    usage
fi

log "AgentGenesis 清理脚本"
log "STALE 阈值: ${STALE_DAYS}天 | ARCHIVE 保留: ${ARCHIVE_MAX_DAYS}天"
$DRY_RUN && log ">>> 预览模式 — 不执行实际操作 <<<"

if $STALE_MODE; then
    log "--- STALE 文件处理 ---"
    if [[ -n "$TARGET_AGENT" ]]; then
        process_agent "$TARGET_AGENT"
    else
        for agent_dir in "$WORK_DIR"/*/; do
            agent_name=$(basename "$agent_dir")
            [[ "$agent_name" == "_self" || "$agent_name" == "_archive" ]] && continue
            process_agent "$agent_name"
        done
    fi
fi

if $ARCHIVE_MODE; then
    log "--- 归档清理 ($ARCHIVE_MAX_DAYS天) ---"
    delete_old_archives
fi

log "完成"
