"""转发 state-machine 的 audit_append.py。"""
from __future__ import annotations

from tests.script_loader import load

_m = load("state-machine", "audit_append")
globals().update({k: v for k, v in vars(_m).items() if not k.startswith("_")})


def __getattr__(name: str):
    return getattr(_m, name)
