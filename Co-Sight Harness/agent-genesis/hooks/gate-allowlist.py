#!/usr/bin/env python3
"""fail-open 桩 — OPT-7 已删除 Bash 守卫, hooks.json 已移除本注册。
保留此文件仅为兼容本开发会话的 hook 注册快照(指向本路径, 文件缺失即阻断全部 Bash);
新会话不再加载本注册。批次收官时物理删除。"""
import sys
sys.exit(0)
