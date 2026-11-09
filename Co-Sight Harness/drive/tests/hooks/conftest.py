"""hooks 测试的 import 路径 — hooks/ 是独立脚本目录，非 Python 包。

Claude Code 以独立进程执行 hook 脚本，其 cwd 即 hooks/，同目录 import 自然
解析。测试进程需显式把 hooks/ 加入 sys.path 以复现该环境。
"""
from __future__ import annotations

import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent.parent / "hooks"

if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))
