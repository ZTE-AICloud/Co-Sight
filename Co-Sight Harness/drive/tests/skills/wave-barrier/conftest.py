"""wave-barrier tests conftest —— 让 aggregate.py 可作为模块直接 import。
"""
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PLUGIN_ROOT / "skills" / "wave-barrier" / "scripts"))
