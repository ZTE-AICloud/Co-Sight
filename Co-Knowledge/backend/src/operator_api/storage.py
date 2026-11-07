"""Local-file helpers for custom operators.

The sandbox materializes object-storage references into local files before an
operator runs, so operators only ever need plain filesystem access.
"""

from __future__ import annotations

from pathlib import Path


def read_bytes(path: str | Path) -> bytes:
    return Path(path).read_bytes()


def read_text(path: str | Path, encoding: str = 'utf-8') -> str:
    return Path(path).read_text(encoding=encoding)


def write_bytes(path: str | Path, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def write_text(path: str | Path, text: str, encoding: str = 'utf-8') -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding=encoding)
    return target
