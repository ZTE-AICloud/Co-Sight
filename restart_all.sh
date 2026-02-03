#!/bin/bash
# 重启所有服务

echo "========================================="
echo "重启 Co-Sight + OpenClaw"
echo "========================================="

cd "$(dirname "$0")"

# 停止服务
echo "停止 Co-Sight..."
pkill -f "cosight_server/deep_research/main.py"

# 若存在 clawdbot-gateway，先停掉以免与 openclaw 抢 18789
if systemctl --user is-active --quiet clawdbot-gateway 2>/dev/null; then
    echo "停用 clawdbot-gateway（避免端口冲突）..."
    systemctl --user stop clawdbot-gateway 2>/dev/null || true
    sleep 2
fi

echo "重启 OpenClaw Gateway..."
openclaw gateway restart

sleep 3

# 同步最新的 Token
echo "同步 OpenClaw Token..."
OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null)

if [ -n "$OPENCLAW_TOKEN" ]; then
    echo "✓ 获取到 Token: ${OPENCLAW_TOKEN:0:20}..."
    
    if [ -f ".env" ]; then
        # 备份并更新
        BACKUP_NAME=".env.backup.$(date +%Y%m%d_%H%M%S)"
        cp .env "$BACKUP_NAME"
        
        if grep -q "^OPENCLAW_AUTH_TOKEN=" .env; then
            sed -i "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env
            echo "✓ Token 已自动更新"
        else
            echo "OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN" >> .env
            echo "✓ Token 已自动添加"
        fi
    fi
else
    echo "⚠ 无法获取 Token，使用现有配置"
fi

sleep 2

# 启动 Co-Sight
echo "启动 Co-Sight..."
nohup ./start_cosight.sh > logs/cosight_startup.log 2>&1 &

sleep 3

# 验证服务
echo ""
echo "验证服务状态..."
openclaw gateway status
echo ""

if pgrep -f "cosight_server/deep_research/main.py" > /dev/null; then
    echo "✓ Co-Sight 运行中"
    curl -s http://localhost:7788/cosight/ > /dev/null && echo "✓ Web 服务可访问" || echo "⚠ Web 服务暂未就绪"
else
    echo "✗ Co-Sight 未启动"
fi

echo ""
echo "========================================="
echo "重启完成！"
echo "访问: http://localhost:7788/cosight/"
echo ""
echo "查看日志:"
echo "  OpenClaw 连接: tail -f logs/openclaw_client.log"
echo "  WebSocket: tail -f logs/websocket.log"
echo "========================================="
