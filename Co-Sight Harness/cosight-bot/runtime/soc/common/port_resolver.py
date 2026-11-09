#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CoSightBot 数据目录解析（CC 插件版）。

数据根目录解析链（与 cosightbot-pkm 侧保持一致）：
  1. 环境变量 ``COSIGHTBOT_HOME``（测试 / 多实例场景，显式覆盖最高优先）；
  2. 环境变量 ``CLAUDE_PLUGIN_DATA``（CC 为插件提供的运行数据目录）；
  3. ``~/.claude/plugins/data/cosightbot``（CC 官方插件数据目录的默认位置兜底，
     保证用户在 shell 里手动运行技能脚本时无需注入任何环境变量）。
"""
import os
from pathlib import Path

# CC 官方插件数据目录的默认位置（plugin.json 的 name 为 cosightbot 时 <id>=cosightbot）
_PLUGIN_DATA_DEFAULT = Path.home() / ".claude" / "plugins" / "data" / "cosightbot"


def cosight_state_root() -> Path:
    """数据根目录：COSIGHTBOT_HOME > CLAUDE_PLUGIN_DATA > 官方默认位置。"""
    for env_key in ("COSIGHTBOT_HOME", "CLAUDE_PLUGIN_DATA"):
        value = (os.environ.get(env_key) or "").strip()
        if value:
            return Path(value).expanduser()
    return _PLUGIN_DATA_DEFAULT
