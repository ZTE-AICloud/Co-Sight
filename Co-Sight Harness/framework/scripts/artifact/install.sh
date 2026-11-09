#!/bin/sh
# Co-Sight Harness 安装脚本（Linux / macOS）
#
# 用法：
#   ./install.sh                 用默认数据目录（~/.cosight-harness）
#   ./install.sh --home /srv/ch  指定数据目录
#
# ── 这个脚本故意很短，而且故意用 POSIX sh ──────────────────────────────
#
# **短**：真正的活（Node 版本校验、建数据目录、生成配置、装五个 Claude Code 插件）
# 全在 `start.mjs --install` 里。
# 在这个脚本里再写一遍，就等于同一件事有两份实现：一份跑在 Linux、一份跑在
# install.cmd（还有它的 `%VAR%` 方言），而两份一定会在某次改动后开始不一致。
# 这个脚本只做 Node 自己做不到的事——**找到 node**。
#
# **POSIX sh**：仓库里那几个 install.sh（如 drive/scripts/install.sh）是装在开发机上的，
# 用 bash 没问题；这一份跑在**用户的机器**上，可能是 Alpine 之类只有 busybox 的最小系统，
# 所以不用 `[[ ]]`、不用数组、不用 `BASH_SOURCE`。
#
# 不做的事（刻意的）：不 sudo、不写系统目录、不改 PATH、不联网、不后台常驻。
# 产物自带依赖树、没有编译步骤，拷到哪都能跑，"安装"实际只剩三件事：
# 确认 Node、定数据目录、留一份配置。

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if ! command -v node >/dev/null 2>&1; then
    cat >&2 <<'EOF'
找不到 node。

本程序需要 Node.js ^22.19.0 || >=24.0.0（只用到 Node 内置能力，不需要 npm/pnpm，
也不需要联网装依赖）。下载地址：https://nodejs.org/zh-cn/download

装好 Node 后重新运行本脚本。若 node 已装但不在 PATH 上，请把它的 bin 目录加进 PATH，
或直接用绝对路径调用：/path/to/node start.mjs --install
EOF
    exit 1
fi

cd "$SCRIPT_DIR"

# 预检 + 建数据目录 + 生成 cosight.env + 把五个插件装进 Claude Code。
# 幂等：重复运行不会覆盖已有配置；插件按版本与内容哈希判断，已最新就跳过。
node start.mjs --install "$@"

cat <<'EOF'

下一步：./start.sh            （或 node start.mjs）
        ./start.sh --help    查看所有参数
EOF
