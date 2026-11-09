"""
Step Tracker — 步骤级别的状态追踪
===================================
弥补当前只有轮次级别追踪的不足，提供步骤级别的进度、错误和产物追踪。

用法：
    tracker = StepTracker()
    tracker.begin_step(round_num=1, step_name="eval")
    try:
        ... execute step ...
        tracker.complete_step(round_num=1, step_name="eval", artifacts=["data/eval/..."])
    except Exception as e:
        tracker.fail_step(round_num=1, step_name="eval", error=str(e))
"""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class StepStatus:
    """单个步骤的执行状态。"""
    step_name: str
    status: str  # "pending" | "running" | "done" | "failed" | "skipped"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 0

    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None and v != [] and v != 0}


class StepTracker:
    """
    步骤级别的状态追踪器。

    特性：
    - 每个轮次内的多个步骤独立追踪
    - 支持原地重试计数
    - 产物路径记录
    - 状态持久化到 JSON 文件
    """

    def __init__(self, state_file: Optional[str] = None):
        self._state_file = Path(state_file) if state_file else None
        self._steps: Dict[int, Dict[str, StepStatus]] = {}  # {round_num: {step_name: status}}
        self._load()

    def _now(self) -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def begin_step(self, round_num: int, step_name: str, max_retries: int = 0):
        """标记步骤开始执行。"""
        if round_num not in self._steps:
            self._steps[round_num] = {}
        self._steps[round_num][step_name] = StepStatus(
            step_name=step_name,
            status="running",
            start_time=self._now(),
            max_retries=max_retries,
        )
        self._save()

    def complete_step(self, round_num: int, step_name: str, artifacts: Optional[List[str]] = None):
        """标记步骤成功完成。"""
        step = self._get_step(round_num, step_name)
        if step is None:
            return
        step.status = "done"
        step.end_time = self._now()
        step.artifacts = artifacts or []
        if step.start_time:
            from datetime import datetime
            try:
                start = datetime.strptime(step.start_time, "%Y-%m-%d %H:%M:%S")
                end = datetime.strptime(step.end_time, "%Y-%m-%d %H:%M:%S")
                step.duration_seconds = (end - start).total_seconds()
            except ValueError:
                pass
        self._save()

    def fail_step(self, round_num: int, step_name: str, error: str):
        """标记步骤执行失败。"""
        step = self._get_step(round_num, step_name)
        if step is None:
            return
        step.status = "failed"
        step.error = error
        step.end_time = self._now()
        step.retry_count += 1
        self._save()

    def skip_step(self, round_num: int, step_name: str, reason: str = ""):
        """标记步骤跳过。"""
        if round_num not in self._steps:
            self._steps[round_num] = {}
        self._steps[round_num][step_name] = StepStatus(
            step_name=step_name,
            status="skipped",
            end_time=self._now(),
            error=reason if reason else None,
        )
        self._save()

    def should_retry_step(self, round_num: int, step_name: str, max_retries: int = 0) -> bool:
        """判断步骤是否应该重试。"""
        step = self._get_step(round_num, step_name)
        if step is None:
            return False
        effective_max = max_retries if max_retries > 0 else step.max_retries
        return step.status == "failed" and step.retry_count <= effective_max

    def get_step(self, round_num: int, step_name: str) -> Optional[StepStatus]:
        """获取单个步骤的状态。"""
        return self._get_step(round_num, step_name)

    def get_round_steps(self, round_num: int) -> List[StepStatus]:
        """获取某轮次内所有步骤的状态列表。"""
        return list(self._steps.get(round_num, {}).values())

    def all_steps_done(self, round_num: int) -> bool:
        """判断某轮次内所有步骤是否都已完成（done 或 skipped）。"""
        steps = self._steps.get(round_num, {})
        if not steps:
            return False
        return all(s.status in ("done", "skipped") for s in steps.values())

    def any_step_failed(self, round_num: int) -> bool:
        """判断某轮次内是否有任何步骤失败且不可重试。"""
        steps = self._steps.get(round_num, {})
        for s in steps.values():
            if s.status == "failed" and not self.should_retry_step(round_num, s.step_name):
                return True
        return False

    def summary(self, round_num: int) -> Dict:
        """生成某轮次的步骤执行摘要。"""
        steps = self._steps.get(round_num, {})
        return {
            "total": len(steps),
            "done": sum(1 for s in steps.values() if s.status == "done"),
            "failed": sum(1 for s in steps.values() if s.status == "failed"),
            "skipped": sum(1 for s in steps.values() if s.status == "skipped"),
            "running": sum(1 for s in steps.values() if s.status == "running"),
        }

    def _get_step(self, round_num: int, step_name: str) -> Optional[StepStatus]:
        return self._steps.get(round_num, {}).get(step_name)

    def save(self, path: str):
        """持久化到 JSON 文件。"""
        data = {}
        for rn, steps_dict in self._steps.items():
            data[str(rn)] = {sn: s.to_dict() for sn, s in steps_dict.items()}
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> "StepTracker":
        """从 JSON 文件加载状态。"""
        tracker = cls(state_file=str(Path(path)))
        return tracker

    def _load(self):
        if self._state_file and self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                for rn, steps_dict in data.items():
                    round_num = int(rn)
                    self._steps[round_num] = {}
                    for sn, sdata in steps_dict.items():
                        self._steps[round_num][sn] = StepStatus(**sdata)
            except Exception:
                pass

    def _save(self):
        """内部保存（每次状态变更后自动调用）。"""
        if not self._state_file:
            return
        self.save(str(self._state_file))
