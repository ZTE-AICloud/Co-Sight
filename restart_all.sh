#!/bin/bash
cd "$(dirname "$0")"
pkill -f "cosight_server/deep_research/main.py" 2>/dev/null || true
openclaw gateway restart 2>/dev/null || true
sleep 2
OPENCLAW_TOKEN=$(openclaw config get gateway.auth.token 2>/dev/null)
[ -n "$OPENCLAW_TOKEN" ] && [ -f ".env" ] && (grep -q "^OPENCLAW_AUTH_TOKEN=" .env && sed -i "s|^OPENCLAW_AUTH_TOKEN=.*|OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN|" .env || echo "OPENCLAW_AUTH_TOKEN=$OPENCLAW_TOKEN" >> .env)
mkdir -p logs
nohup ./start_cosight.sh > logs/cosight_startup.log 2>&1 &
echo "重启完成。访问: http://localhost:7788/cosight/"
