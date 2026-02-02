#!/bin/bash
# Co-Sight + OpenClaw 卸载脚本

echo "========================================="
echo "卸载 Co-Sight + OpenClaw"
echo "========================================="
echo ""

echo "⚠️  警告: 此操作将："
echo "  - 停止所有服务"
echo "  - 删除 Co-Sight 配置文件"
echo "  - 卸载 OpenClaw（可选）"
echo ""

read -p "确认卸载？[y/N]: " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# 停止服务
echo "停止服务..."
pkill -f "cosight_server/deep_research/main.py" 2>/dev/null || true
openclaw gateway stop 2>/dev/null || true

# 备份配置
if [ -f ".env" ]; then
    BACKUP=".env.backup.$(date +%Y%m%d_%H%M%S)"
    cp .env "$BACKUP"
    echo "✓ 配置已备份到: $BACKUP"
fi

# 删除 Co-Sight 相关文件
echo "清理 Co-Sight 文件..."
rm -f .env
rm -f start_cosight.sh stop_cosight.sh restart_all.sh check_status.sh
echo "✓ Co-Sight 配置已清理"

# 询问是否卸载 OpenClaw
echo ""
read -p "是否同时卸载 OpenClaw？[y/N]: " UNINSTALL_OPENCLAW
if [[ "$UNINSTALL_OPENCLAW" =~ ^[Yy]$ ]]; then
    openclaw gateway uninstall
    npm uninstall -g openclaw
    echo "✓ OpenClaw 已卸载"
fi

echo ""
echo "========================================="
echo "卸载完成！"
echo "========================================="
