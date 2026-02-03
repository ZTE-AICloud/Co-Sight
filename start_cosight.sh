#!/bin/bash
# Co-Sight 启动脚本

cd "$(dirname "$0")"

# 检查 uv 是否可用
if command -v uv >/dev/null 2>&1; then
    echo "使用 uv 启动 Co-Sight..."
    uv run cosight_server/deep_research/main.py
else
    echo "使用 python 启动 Co-Sight..."
    python3 cosight_server/deep_research/main.py
fi
