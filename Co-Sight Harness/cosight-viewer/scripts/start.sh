#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# ============================================================
# Cosight Viewer 启动脚本
# 检查依赖状态，自动完成安装和启动
#
# 用法:
#   ./scripts/start.sh           # 启动服务
#   ./scripts/start.sh --help    # 显示帮助
# ============================================================

set -e

# 颜色
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

log()   { echo -e "${GREEN}[启动]${NC} $1"; }
info()  { echo -e "${CYAN}[启动]${NC} $1"; }
err()   { echo -e "${RED}[启动]${NC} $1" >&2; }

# 参数解析
for arg in "$@"; do
  case "$arg" in
    -h|--help)
      echo "用法: $0"
      echo ""
      echo "自动检查依赖并启动服务："
      echo "  - 依赖未安装 → npm install（自动触发 postinstall 启动）"
      echo "  - 依赖已安装 → npm run start"
      echo ""
      echo "停止服务: npm run stop"
      exit 0
      ;;
    *)
      err "未知参数: $arg"
      exit 1
      ;;
  esac
done

# 进入项目目录
cd "$(dirname "$0")/.." || exit 1

# 检查依赖是否已安装
if [ ! -d "node_modules" ] || [ ! -d "client/node_modules" ]; then
    log "依赖未安装，执行 npm install..."
    log "（安装完成后会自动启动服务）"
    npm install
else
    info "依赖已安装"
    log "启动服务..."
    npm run start
fi
