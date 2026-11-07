"""Logging helpers for custom operators."""

from __future__ import annotations

import logging as _logging

from typing import Optional


def build_prefix(tx_id: Optional[str]) -> str:
    """Prefix every message with the transaction id, when present."""
    return f'[{tx_id}] >>> ' if tx_id else ''


class TxPrefixedLogger:
    """Logger that prefixes messages with the operator transaction id."""

    def __init__(self, tx_id: Optional[str]):
        self._prefix = build_prefix(tx_id)

    def debug(self, message: str) -> None:
        _logging.debug(self._prefix + message)

    def info(self, message: str) -> None:
        _logging.info(self._prefix + message)

    def warning(self, message: str) -> None:
        _logging.warning(self._prefix + message)

    def error(self, message: str) -> None:
        _logging.error(self._prefix + message)

    def exception(self, message: str | Exception) -> None:
        if isinstance(message, Exception):
            _logging.exception(self._prefix + str(message))
        else:
            _logging.exception(self._prefix + message)
