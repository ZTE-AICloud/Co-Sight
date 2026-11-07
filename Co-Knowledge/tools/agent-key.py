#!/usr/bin/env python3
"""宿主侧 Agent Key CLI 包装。

真正的实现在 ``backend/src/agent/cli.py``（容器内推荐
``python3 -m agent.cli``，因为 ``tools/`` 不进运行镜像）。本包装只用于
在宿主机上临时建 Key/排查，需要：

* ``backend`` 的 Python 依赖（psycopg2 等）；
* 与容器**同一份** ``RKB_DB_*`` 与 ``RKB_AGENT_KEY_PEPPER``。

宿主连库时通常还要把 ``RKB_DB_HOST`` 指到 ``127.0.0.1``（PG 只发布在
宿主回环），并设置 ``DB_PASSWORD``（ES 客户端等模块的默认口令回落）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'backend' / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.cli import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
