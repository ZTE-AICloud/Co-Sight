"""转发 startup 内 discover_inputs.py。

phase 3 后原本 drive-analyze 已被删除, discover_inputs 迁到 skills/startup/scripts/。
"""
from __future__ import annotations

from tests.script_loader import load

_m = load("startup", "discover_inputs")
globals().update({k: v for k, v in vars(_m).items() if not k.startswith("_")})


def __getattr__(name: str):
    return getattr(_m, name)
