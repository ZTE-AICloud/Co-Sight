"""转发 startup 内 init_planning.py。

phase 3 后原本 drive-start 已被删除, init_planning 迁到 skills/startup/scripts/。
"""
from __future__ import annotations

from tests.script_loader import load

_m = load("startup", "init_planning")
globals().update({k: v for k, v in vars(_m).items() if not k.startswith("_")})


def __getattr__(name: str):
    return getattr(_m, name)
