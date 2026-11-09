#!/bin/sh
# Co-Sight Harness 启动（Linux / macOS）
#
#   ./start.sh                    默认 127.0.0.1:4300，数据目录 ~/.cosight-harness
#   ./start.sh --port 8080        参数与 node start.mjs 完全一致
#   ./start.sh --help
#
# 配置文件是同目录下的 `cosight.env`（`KEY=VALUE` 纯文本，模板见 cosight.env.example），
# 由 `start.mjs` 读取——**这个脚本不解析它**。理由见 lib/env-file.mjs 的文件头：
# 让 sh 与 cmd 各解析一遍，两份语义迟早会分叉，而且只在另一个平台上暴露。
#
# 用 `exec` 而不是 `node ... ; exit $?`：让 node 直接占用当前进程，Ctrl-C 送到的
# 就是它本身，退出码也是它的原样。中间多一层 shell 会让信号与退出码都多一次转手。

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

exec node start.mjs "$@"
