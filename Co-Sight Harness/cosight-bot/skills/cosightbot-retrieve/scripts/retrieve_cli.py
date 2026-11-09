#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cosightbot-retrieve CLI —— 知识检索入口（纯只读）。

对 runtime/common/overview_resolver.py 的薄封装：
  1. 加载 data/.env；
  2. preflight 环境自检（未安装时 exit 3 + {"hint": "please_run_install"}）；
  3. 透传全部命令行参数给 overview_resolver.main()。

用法（与 overview_resolver 完全一致）：

  # 主命令：拿 merged_overview 章节树（检索三步法第一步）
  python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-retrieve/scripts/retrieve_cli.py --agent-id main

  # 状态检查（不读内容）
  python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-retrieve/scripts/retrieve_cli.py --agent-id main --check-only

  # 按节点读全文
  python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-retrieve/scripts/retrieve_cli.py --agent-id main read-doc --node-id f001 [--line-range 100:200]

  # pre-processed 层全文扫描（多词 and 共现）
  python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-retrieve/scripts/retrieve_cli.py --agent-id main scan --terms "甲,乙"

  # 大库动态概览（Tier 1/2）
  python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-retrieve/scripts/retrieve_cli.py --agent-id main \
    resolve --question "自包含问题" [--force-dynamic]

只读红线（S-01）：本入口绝不触发索引构建/写入；需要构建时引导用户
使用 cosightbot-material 技能。
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---- sys.path 引导：本脚本位于 <插件根>/skills/cosightbot-retrieve/scripts/ ----
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME = _PLUGIN_ROOT / "runtime" / "pkm"
for _p in (str(_RUNTIME), str(_RUNTIME / "watch_dog")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common.bootstrap import bootstrap  # noqa: E402

bootstrap()  # .env 加载 + preflight（失败 exit 3，输出 please_run_install 引导）

from common.overview_resolver import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
