#!/bin/sh
# Co-Sight Harness 卸载脚本（Linux / macOS）
#
# 用法：
#   ./uninstall.sh                     只把五个插件从 Claude Code 里摘掉
#   ./uninstall.sh --dry-run           只打印将执行什么，什么都不改
#   ./uninstall.sh --purge-data --yes  连数据目录一起删（会话、工作区与密钥都会没）
#
# 与 install.sh 一样的边界：这个脚本只做 Node 做不到的事——**找到 node**。
# 真正的工作（按顺序卸插件、摘市场、清载荷副本、按需删数据目录）全在
# `start.mjs --uninstall` 里。写两遍的话，sh 与 cmd 两份一定会在某次改动后分叉，
# 而且只在另一个平台上暴露。
#
# 为什么这件事不能靠"删解压目录"完成：安装会往 `~/.claude` 写五个市场（各一份
# 载荷副本）与五条插件注册，它们都不在产物目录里。目录删了，这些还在。
#
# 不做的事（刻意的）：不 sudo、不写系统目录、不改 PATH、不联网。数据目录默认
# **不动**——那是用户的会话与密钥，只有显式 --purge-data 才会删。

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if ! command -v node >/dev/null 2>&1; then
    cat >&2 <<'EOF'
找不到 node。

卸载逻辑写在 start.mjs 里，需要 Node.js ^22.19.0 || >=24.0.0（只用 Node 内置能力，
不需要 npm/pnpm，也不需要联网）。若 node 已装但不在 PATH 上，可直接用绝对路径：
/path/to/node start.mjs --uninstall
EOF
    exit 1
fi

cd "$SCRIPT_DIR"

# 收尾提示（"最后一步：删除这个解压目录" / 数据目录默认保留 / --dry-run 下什么都没改）
# 也由 start.mjs 打印：它知道自己在产物里还是仓库里，也知道这次是不是 dry-run。
# 在这里再写一份，两份就会在下次改动时对不上——比如 dry-run 时还在叫人删目录。
node start.mjs --uninstall "$@"
