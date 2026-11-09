"""
State Engine - 状态机引擎
=========================
职责：状态转换 + 状态恢复 + 状态持久化

用法：
    from state_engine import StateEngine

    engine = StateEngine(workspace, args)
    engine.run()
"""

# 目标分数硬编码为 100。CLI 层已彻底删除 --target-score 参数。
DEFAULT_TARGET_SCORE = 100.0

from .engine import StateEngine
from .diagnosis import DiagnosticAnalyzer, DiagnosticFinding, generate_diagnosis_section
from .sandbox import SandboxManager
from .overfit_monitor import OverfitMonitor, OverfitSignal
from .phase_tracker import PhaseTracker, PhaseRecord, PHASE_ORDER, PHASE_DESCRIPTIONS

__all__ = [
    "StateEngine",
    "DiagnosticAnalyzer",
    "DiagnosticFinding",
    "generate_diagnosis_section",
    "SandboxManager",
    "OverfitMonitor",
    "OverfitSignal",
    "PhaseTracker",
    "PhaseRecord",
    "PHASE_ORDER",
    "PHASE_DESCRIPTIONS",
    "DEFAULT_TARGET_SCORE",
]