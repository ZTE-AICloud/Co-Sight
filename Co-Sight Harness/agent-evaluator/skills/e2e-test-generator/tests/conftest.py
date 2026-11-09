#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""conftest.py — 让测试能 import scripts/ 下的模块（脚本是平铺的，非包）。"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SAMPLE_AGENT = (
    Path("/tmp/eval/runtime/output/agents/"
         "plaintext-password-checker/v1")
)
