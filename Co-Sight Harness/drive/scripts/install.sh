#!/usr/bin/env bash
# 把打包好的插件制品安装到本地 Claude Code。
#
# 用法:
#   ./scripts/install.sh --from PKG.tar.gz     # 从 pack.sh 的制品装（分发主路径）
#   ./scripts/install.sh                       # 从当前源码目录装（拷贝快照）
#   ./scripts/install.sh --dev                 # 开发机：marketplace 直指本仓库
#   ./scripts/install.sh --scope project       # 装到项目 scope（默认 user）
#   DEST=/tmp/cache ./scripts/install.sh       # 离线 cp 到指定根（CI/测试场景）
#
# 本脚本替第三方完成 `/plugin marketplace add` + `/plugin install` 两步：
#   1. 制品解包 / 源码 cp 到 ~/.claude/plugins/marketplaces/<marketplace>/
#      —— CLI 给 git 源用的同一个规范位置。marketplace 只记路径不复制，
#      所以这个目录必须持久存在，不能是临时目录。
#   2. claude plugin marketplace add <该目录>
#   3. claude plugin install / update <plugin>@<marketplace>
#
# --dev 跳过第 1 步的拷贝，marketplace 直接指向本仓库 03-drive-core/，
# 改完源码无需重装即可被 CLI 看到。仅限本机开发，不用于分发。
#
# cache（~/.claude/plugins/cache/...）由 CLI 自己从上面这个源生成，
# 脚本不碰 —— 手工往 cache 里 cp 会混进 tests/ 之类的非运行时文件。
#
# 安装后需重启 Claude Code 会话，命令才会出现在面板里。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

FROM_TARBALL=""
SCOPE="user"
DEV_MODE=""
CUSTOM_DEST="${DEST:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --from)         FROM_TARBALL="$2"; shift 2 ;;
        --dev)          DEV_MODE="1"; shift ;;
        --scope)        SCOPE="$2"; shift 2 ;;
        --scope=*)      SCOPE="${1#--scope=}"; shift ;;
        -h|--help)      sed -n '2,24p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *)              echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

if [[ -n "$DEV_MODE" && -n "$FROM_TARBALL" ]]; then
    echo "--dev 与 --from 互斥：--dev 指向本仓库，--from 装制品" >&2
    exit 2
fi


# ============================================================================
# 辅助（必须先于主流程定义）
# ============================================================================

cp_runtime_files() {
    # 只 cp 运行时需要的（tests / scripts / dist 不进源目录）
    local src="$1"
    local target="$2"

    for item in .claude-plugin skills agents hooks README.md; do
        [[ -e "$src/$item" ]] || continue
        rm -rf "$target/$item"
        cp -r "$src/$item" "$target/$item"
    done

    find "$target" -type d -name '__pycache__'    -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type d -name '.ruff_cache'    -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type d -name '.pytest_cache'  -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type d -name 'dist'           -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type f -name '*.py[co]' -delete 2>/dev/null || true
}

json_field() {
    # json_field <file> <python 表达式，d 为已解析的 dict>
    python3 -c 'import json,sys
d = json.load(open(sys.argv[1]))
print(eval(sys.argv[2], {"d": d}))' "$1" "$2"
}

registered_marketplace_path() {
    python3 -c 'import json,os,sys
p = os.path.expanduser("~/.claude/plugins/known_marketplaces.json")
if not os.path.exists(p): sys.exit(0)
e = json.load(open(p)).get(sys.argv[1])
print(e.get("installLocation", "") if e else "")' "$1" 2>/dev/null || true
}

installed_plugin_version() {
    python3 -c 'import json,os,sys
p = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
if not os.path.exists(p): sys.exit(0)
e = json.load(open(p)).get("plugins", {}).get(sys.argv[1])
print(e[0].get("version", "") if e else "")' "$1" 2>/dev/null || true
}

content_hash() {
    # content_hash <root_dir>
    # 算 plugin runtime 关键文件 + manifest 的 sha256——同版本代码变更能检测到。
    # 注意：cache 命中的 hash 与 marketplace 源 hash 一致 → 不重装。
    python3 -c '
import hashlib, sys, os
root = sys.argv[1]
h = hashlib.sha256()
# 固定文件清单：plugin runtime + manifest
files = [
    ".claude-plugin/plugin.json",
    "skills/startup/SKILL.md",
    "skills/drive-cleanup/SKILL.md",
    "skills/state-machine/SKILL.md",
    "skills/drive/SKILL.md",
    "hooks/hooks.json",
]
for rel in files:
    p = os.path.join(root, rel)
    if os.path.isfile(p):
        h.update(rel.encode() + b"\0")
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
print(h.hexdigest()[:16])
' "$1"
}

cache_root() {
    # cache_root <plugin_name> <marketplace_name> → cache dir path（可能有，也可能没有）
    python3 -c '
import json, os, sys
p = os.path.expanduser("~/.claude/plugins/installed_plugins.json")
if not os.path.exists(p):
    sys.exit(0)
e = json.load(open(p)).get("plugins", {}).get(f"{sys.argv[1]}@{sys.argv[2]}")
if e:
    print(e[0].get("installPath", ""))
' "$1" "$2" 2>/dev/null
}


# ============================================================================
# 准备源：tarball 解包到 stage，否则直接用 repo
# ============================================================================

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

if [[ -n "$FROM_TARBALL" ]]; then
    [[ -f "$FROM_TARBALL" ]] || { echo "找不到 $FROM_TARBALL" >&2; exit 1; }
    tar -xzf "$FROM_TARBALL" -C "$STAGE"
    SRC="$STAGE"
else
    SRC="$SCRIPT_DIR"
fi

# manifest 必须从 SRC 读 —— tarball 模式下脚本所在目录没有 .claude-plugin/
MANIFEST="$SRC/.claude-plugin/plugin.json"
MARKETPLACE="$SRC/.claude-plugin/marketplace.json"
[[ -f "$MANIFEST" ]]    || { echo "制品缺少 .claude-plugin/plugin.json"    >&2; exit 1; }
[[ -f "$MARKETPLACE" ]] || { echo "制品缺少 .claude-plugin/marketplace.json" >&2; exit 1; }

PLUGIN_NAME="$(json_field "$MANIFEST" 'd["name"]')"
MARKETPLACE_NAME="$(json_field "$MARKETPLACE" 'd["name"]')"
VERSION="$(json_field "$MANIFEST" 'd["version"][1:] if d["version"].startswith("v") else d["version"]')"


# ============================================================================
# DEST 模式：只 cp 不注册（CI / 测试）
# ============================================================================

if [[ -n "$CUSTOM_DEST" ]]; then
    TARGET="$CUSTOM_DEST/$VERSION"
    mkdir -p "$TARGET"
    cp_runtime_files "$SRC" "$TARGET"
    echo "DEST 模式只 cp，未注册: $TARGET"
    echo "若要 Claude Code 索引到，调: claude plugin install ${PLUGIN_NAME}@${MARKETPLACE_NAME}"
    exit 0
fi


# ============================================================================
# 正常路径：marketplace 源就位 → add → install/update
# ============================================================================

if [[ -n "$DEV_MODE" ]]; then
    # 开发机：marketplace 直指本仓库，不拷贝。改源码即时生效。
    MARKETPLACE_HOME="$SCRIPT_DIR"
else
    MARKETPLACE_HOME="$HOME/.claude/plugins/marketplaces/$MARKETPLACE_NAME"
fi

# 已注册到别的路径时先摘掉，否则 add 不改指向。
# 必须在填充源目录之前做 —— `marketplace remove` 会删掉
# ~/.claude/plugins/marketplaces/<name>/，先拷再 remove 等于自删输入。
PREV_PATH="$(registered_marketplace_path "$MARKETPLACE_NAME")"
if [[ -n "$PREV_PATH" && "$PREV_PATH" != "$MARKETPLACE_HOME" ]]; then
    echo "marketplace '$MARKETPLACE_NAME' 原指向 $PREV_PATH，重新指向 $MARKETPLACE_HOME"
    claude plugin marketplace remove "$MARKETPLACE_NAME" >/dev/null 2>&1 || true
fi

if [[ -n "$DEV_MODE" ]]; then
    echo "dev 模式，marketplace 直指本仓库: $MARKETPLACE_HOME"
else
    mkdir -p "$MARKETPLACE_HOME"
    cp_runtime_files "$SRC" "$MARKETPLACE_HOME"
    echo "marketplace 源已就位: $MARKETPLACE_HOME"
fi

claude plugin marketplace add "$MARKETPLACE_HOME" || {
    echo "marketplace 注册失败: $MARKETPLACE_HOME" >&2
    exit 1
}

INSTALL_ID="${PLUGIN_NAME}@${MARKETPLACE_NAME}"
PREV_VERSION="$(installed_plugin_version "$INSTALL_ID")"

# 内容 hash 比对：marketplace 源与 cache 内容一致 → update 即可；
# 不一致 → 必须 uninstall + install 才能刷新 cache（update 不复制内容，
# 只在版本号变化时才复制——同版本号内容更新会跳过）。
MARKETPLACE_HASH="$(content_hash "$MARKETPLACE_HOME")"
CACHE_PATH="$(cache_root "$PLUGIN_NAME" "$MARKETPLACE_NAME")"
CACHE_HASH=""
if [[ -n "$CACHE_PATH" && -d "$CACHE_PATH" ]]; then
    CACHE_HASH="$(content_hash "$CACHE_PATH")"
fi
NEEDS_REINSTALL=""
if [[ -n "$PREV_VERSION" && -n "$MARKETPLACE_HASH" && -n "$CACHE_HASH" && "$MARKETPLACE_HASH" != "$CACHE_HASH" ]]; then
    NEEDS_REINSTALL="1"
    echo "已装 $PREV_VERSION，但 cache 与 marketplace 内容不一致："
    echo "  marketplace hash: $MARKETPLACE_HASH"
    echo "  cache hash:       $CACHE_HASH"
    echo "→ 走 uninstall + install 强制刷新 cache（update 不会复制内容）"
fi

# install 是幂等的：已装时它直接返回，不会把元数据更到新版本。要升级得走 update。
if [[ -n "$PREV_VERSION" ]]; then
    if [[ "$NEEDS_REINSTALL" == "1" ]]; then
        echo "已装 $PREV_VERSION，内容有变化"
        ACTION_CMD=(claude plugin uninstall "$INSTALL_ID")
        ACTION_CMD2=(claude plugin install "$INSTALL_ID" --scope "$SCOPE")
    else
        echo "已装 $PREV_VERSION，走 update 到 $VERSION"
        ACTION_CMD=(claude plugin update "$INSTALL_ID")
        ACTION_CMD2=()
    fi
else
    ACTION_CMD=(claude plugin install "$INSTALL_ID" --scope "$SCOPE")
    ACTION_CMD2=()
fi

if [[ -n "${ACTION_CMD2[*]}" ]]; then
    if "${ACTION_CMD[@]}" && "${ACTION_CMD2[@]}"; then
        SUCCESS=1
    else
        SUCCESS=0
    fi
else
    if "${ACTION_CMD[@]}"; then
        SUCCESS=1
    else
        SUCCESS=0
    fi
fi

if [[ "$SUCCESS" == "1" ]]; then
    echo
    echo "安装完成:"
    echo "  scope:       $SCOPE"
    echo "  marketplace: $MARKETPLACE_HOME"
    echo "  version:     $VERSION"
    echo
    echo "在 Claude Code 会话里执行 /reload-plugins 刷新插件，"
    echo "即可使用 /$PLUGIN_NAME。若组件未出现，重启会话。"
else
    echo
    echo "失败。手动排查路径："
    echo "  claude plugin marketplace list       # 看 $MARKETPLACE_NAME 是否在已知源里"
    echo "  claude plugin list                   # 看 $INSTALL_ID 是否已注册"
    echo "  claude plugin details $INSTALL_ID    # 看组件是否被加载"
    exit 1
fi
