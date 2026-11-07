"""Model gateway calls available to custom operators.

The implementation lives in :mod:`model.operator_client`; this module is the
stable import surface.
"""

from __future__ import annotations

from model.operator_client import (MODEL_GATEWAY_CHAT_PATH,
                                   MODEL_GATEWAY_REASONING_EFFORT,
                                   MODEL_GATEWAY_URL, check_status_code_ok,
                                   invoke_llm)

__all__ = [
    'MODEL_GATEWAY_URL',
    'MODEL_GATEWAY_CHAT_PATH',
    'MODEL_GATEWAY_REASONING_EFFORT',
    'check_status_code_ok',
    'invoke_llm',
]
