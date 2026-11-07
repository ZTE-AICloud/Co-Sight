#!/usr/bin/env python3
"""宿主侧账号管理 CLI 包装。

真正的实现是 ``backend/src/auth/cli.py``（容器内推荐
``python3 -m auth.cli ...``，因为 ``tools/`` 不进运行镜像）。本包装只用于
在宿主机上临时建号/排查，需要：

* ``backend`` 的 Python 依赖（psycopg2 等）；
* 与容器**同一份** ``RKB_DB_*`` 环境变量。

宿主连库时通常还要把 ``RKB_DB_HOST`` 指到 ``127.0.0.1``（PG 只发布在
宿主回环），并设置 ``DB_PASSWORD``（与 ``tools/agent-key.py`` 同一套约定）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'backend' / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from auth.cli import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
