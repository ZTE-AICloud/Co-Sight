#!/usr/bin/env bash
# 安装 {{package_name}} 到 DSH profile（幂等：重复执行等价于一次 add）。
# 用法: ./install.sh [profile]    默认 profile 取 $DSH_PROFILE 或 web
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE="${1:-${DSH_PROFILE:-web}}"

if ! command -v dsh >/dev/null 2>&1; then
  echo "错误: 未找到 dsh 命令，请先安装 DeepSeek Harness 并确保 PATH 可见。" >&2
  exit 1
fi

if [ ! -f "$SCRIPT_DIR/package.json" ] || [ ! -f "$SCRIPT_DIR/cordis.patch.yml" ]; then
  echo "错误: $SCRIPT_DIR 不是完整的 bundle（缺 package.json 或 cordis.patch.yml）。" >&2
  exit 1
fi

dsh plugin --profile "$PROFILE" add "$SCRIPT_DIR"

cat <<'EOF'
已注册 bundle。请重启 dsh（bundle 只在启动时读取），然后：
  1) 在 UI 的 Agent 预设中选择「{{display_name}}」
  2) 需要核对时执行: dsh --dump-config | grep -A5 'preset-{{preset_id}}'
EOF
