"""
PhaseTracker - 阶段状态追踪（极简版）
=====================================

管理每个轮次的 4 个子阶段状态，写入 task_state.json。

**极简原则**：task_state.json 只记录状态（status + 时间戳），不记录结果数据
（分数、提案、候选池、decision 等）。所有结果数据统一存到 config.json
（`history` / `candidate_pool` / `best_score` 等）。task_state.json 的唯一职责
是让外部监控 / 断点续跑知道"现在卡在哪一步"。

阶段列表（基线无 apply，最后一轮无 proposal）：
1. apply     - 应用上轮优化提案（基线无）
2. evaluate  - 候选产物生成 + Gold 对比评测（N 个 run 一起算一个阶段）
3. score     - 分数聚合和评级 + 缺口分析
4. proposal  - 优化提案生成
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .persistence import atomic_write, ensure_dir

# 每轮的标准阶段顺序
PHASE_ORDER = ["apply", "evaluate", "score", "proposal"]

PHASE_DESCRIPTIONS = {
    "apply": "应用上轮优化提案",
    "evaluate": "候选产物生成 + Gold 对比评测（N 个 run 一起算）",
    "score": "分数聚合和评级 + 缺口分析",
    "proposal": "优化提案生成",
}

# current 段允许的字段（白名单）：除 timestamp/status/detail/round/phase 外，
# 不再透传任何结果字段（分数/decision/gaps 等）。结果数据走 config.json。
_CURRENT_ALLOWED_KEYS = {"timestamp", "status", "detail", "round", "phase"}


@dataclass
class PhaseRecord:
    """单个阶段的执行记录（仅状态 + 时间戳，无 metadata）"""
    name: str
    status: str  # pending | running | completed | failed | skipped
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
        }
        if self.error:
            d["error"] = self.error
        return d

    @staticmethod
    def from_dict(name: str, d: Dict[str, Any]) -> "PhaseRecord":
        return PhaseRecord(
            name=name,
            status=d.get("status", "pending"),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
            error=d.get("error"),
            retry_count=d.get("retry_count", 0),
        )

    def duration_seconds(self) -> Optional[float]:
        """计算阶段耗时（秒）"""
        if not self.started_at or not self.completed_at:
            return None
        try:
            t1 = datetime.fromisoformat(self.started_at)
            t2 = datetime.fromisoformat(self.completed_at)
            return (t2 - t1).total_seconds()
        except (ValueError, TypeError):
            return None


class PhaseTracker:
    """
    阶段状态追踪器（极简版）

    为每轮维护 4 个子阶段的状态，写入 workspace/task_state.json。
    文件含双 section：
    - rounds   : {round_num: {apply: ..., evaluate: ..., score: ..., proposal: ...}}  阶段状态
    - current  : {timestamp, status, detail, round, phase}  最近进度（替代原 progress.json）

    兼容旧格式：启动时检测 task_state.json（新）> progress_state.json（旧）>
    phase_state.json（中间态）> progress.json（最旧），自动迁移并备份为 .bak。
    旧 9-phase 数据 → 加载时自动折叠到 4 phase, 落盘覆盖。
    当文件不存在或损坏时自动初始化，不影响主流程。

    **结果数据迁移**：所有 results（分数/gaps/decision/candidate_pool/summary 等）
    加载时丢弃，外部消费者应从 config.json 读取。
    """

    # 状态机扩展:终止态枚举(orchestrator 决定是否进入)
    TERMINAL_STATUSES = {"achieved", "max_rounds", "manual_stop"}

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self._state_path = self.workspace / "task_state.json"
        self._data: Dict[str, Any] = {"rounds": {}, "current": None}
        self._load()

    def _load(self):
        """加载已有状态（静默失败，不阻断主流程），旧格式自动迁移并备份为 .bak。

        优先级：task_state.json（新）> progress_state.json（旧）> phase_state.json（中间态）> progress.json（最旧）。
        各文件可贡献不同段：rounds 来自 task_state.json / progress_state.json / phase_state.json；
        current 来自 progress.json / 新文件（白名单过滤，丢弃结果字段）。
        新文件存在时其他旧文件不备份（避免破坏性操作）。
        """
        candidate_files = [
            (self._state_path, "new"),
            (self.workspace / "progress_state.json", "progress_state"),
            (self.workspace / "phase_state.json", "phase_state_only"),
            (self.workspace / "progress.json", "progress_only"),
        ]
        loaded_sources: list = []  # 实际加载过的源文件路径
        for path, kind in candidate_files:
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            if "rounds" in raw and isinstance(raw["rounds"], dict) and not self._data["rounds"]:
                self._data["rounds"] = self._sanitize_rounds(raw["rounds"])
            if "current" in raw and isinstance(raw["current"], dict) and not self._data["current"]:
                self._data["current"] = self._sanitize_current(raw["current"])
            elif kind == "progress_only" and not self._data["current"]:
                # 旧 progress.json 顶层就是单 record
                self._data["current"] = self._sanitize_current({
                    "timestamp": raw.get("timestamp", ""),
                    "status": raw.get("status"),
                    "detail": raw.get("detail", ""),
                    "round": raw.get("round", -1),
                    "phase": raw.get("phase", ""),
                })
            loaded_sources.append((path, kind))
        # 备份策略：新文件存在 → 旧文件不备份；否则备份所有非新文件源
        new_loaded = any(k == "new" for _, k in loaded_sources)
        if not new_loaded:
            for path, kind in loaded_sources:
                if kind == "new":
                    continue
                bak_path = path.with_suffix(path.suffix + ".bak")
                try:
                    path.rename(bak_path)
                except OSError:
                    pass

        # 旧 9-phase 数据 → 新 4-phase 自动迁移
        self._migrate_old_schema()

    def _sanitize_rounds(self, rounds: Dict[str, Any]) -> Dict[str, Any]:
        """加载时过滤 rounds 段：剥离 summary 等结果字段，只保留 phase records"""
        out: Dict[str, Any] = {}
        for key, round_data in rounds.items():
            if not isinstance(round_data, dict):
                continue
            # 只保留 4 phase 字段，其它（summary 等）丢弃
            out[key] = {
                name: round_data.get(name, {"status": "pending"})
                for name in PHASE_ORDER
            }
        return out

    def _sanitize_current(self, cur: Dict[str, Any]) -> Dict[str, Any]:
        """加载时过滤 current 段：白名单字段，丢弃所有结果字段（score/rating/aggregate_score/gaps 等）"""
        return {k: v for k, v in cur.items() if k in _CURRENT_ALLOWED_KEYS}

    def _save(self):
        """原子写入状态文件"""
        ensure_dir(str(self.workspace))
        atomic_write(str(self._state_path), json.dumps(self._data, ensure_ascii=False, indent=2))

    def _migrate_old_schema(self) -> None:
        """旧 9-phase → 新 4-phase, 一次性迁移, 幂等。

        触发条件：某个 round 顶层包含 9-phase 旧 phase 字段
        （sandbox_setup/sandbox_cleanup/round_complete/gap_analysis/proposal_review）。
        这些 phase 信息密度近零（pending 空壳或 4ms 时间戳），折叠到 4 phase 无损。
        迁移时保留 summary 等非 phase 顶层字段。
        """
        legacy_phases = {"sandbox_setup", "sandbox_cleanup", "round_complete", "gap_analysis", "proposal_review"}
        migrated = False
        for round_data in self._data.get("rounds", {}).values():
            if not isinstance(round_data, dict):
                continue
            # 旧 phase 字段在 round 顶层 → 需要迁移
            legacy_keys_in_round = legacy_phases & set(round_data.keys())
            if not legacy_keys_in_round:
                continue
            # 重建 round: 保留 4 phase，其它（summary 等）丢弃（极简版不需要）
            new_round = {name: round_data.get(name, {"status": "pending"}) for name in PHASE_ORDER}
            round_data.clear()
            round_data.update(new_round)
            migrated = True
        if migrated:
            self._save()

    def _ensure_round(self, round_num: int) -> Dict[str, PhaseRecord]:
        """确保某轮的阶段记录存在，返回 {phase_name: PhaseRecord}"""
        key = str(round_num)
        if key not in self._data["rounds"]:
            self._data["rounds"][key] = {
                name: PhaseRecord(name=name, status="pending").to_dict()
                for name in PHASE_ORDER
            }
        raw = self._data["rounds"][key]
        return {name: PhaseRecord.from_dict(name, raw.get(name, {"status": "pending"})) for name in PHASE_ORDER}

    def _serialize_round(self, round_num: int, records: Dict[str, PhaseRecord]):
        """将 PhaseRecord dict 序列化回原始 dict 格式（只覆盖 phase 字段，其它键不写）"""
        key = str(round_num)
        existing = self._data["rounds"].get(key, {})
        phase_dict = {name: rec.to_dict() for name, rec in records.items()}
        merged = dict(existing)
        merged.update(phase_dict)
        self._data["rounds"][key] = merged

    # ── 核心操作 ──

    def update_current(self, status: str, detail: str = "",
                       round_num: int = -1, phase: str = "") -> None:
        """写入 current 段（last-write-wins 单 record）。

        只存状态字段（status/detail/round/phase），不存任何结果数据。
        任何额外参数（score/rating/gaps 等）都会被忽略。
        """
        self._data["current"] = {
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "detail": detail,
            "round": round_num,
            "phase": phase,
        }
        self._save()

    def get_current_progress(self) -> Optional[Dict[str, Any]]:
        """获取 current 段（外部消费者读取入口）。"""
        return self._data.get("current")

    def start_phase(self, round_num: int, phase_name: str):
        """标记阶段开始（running）"""
        records = self._ensure_round(round_num)
        if phase_name not in records:
            return
        rec = records[phase_name]
        rec.status = "running"
        rec.started_at = datetime.now().isoformat()
        self._serialize_round(round_num, records)
        self._save()

    def complete_phase(self, round_num: int, phase_name: str):
        """标记阶段完成（completed）"""
        records = self._ensure_round(round_num)
        if phase_name not in records:
            return
        rec = records[phase_name]
        rec.status = "completed"
        rec.completed_at = datetime.now().isoformat()
        self._serialize_round(round_num, records)
        self._save()

    def fail_phase(self, round_num: int, phase_name: str, error: str = ""):
        """标记阶段失败（failed），retry_count +1"""
        records = self._ensure_round(round_num)
        if phase_name not in records:
            return
        rec = records[phase_name]
        rec.status = "failed"
        rec.completed_at = datetime.now().isoformat()
        rec.error = error
        rec.retry_count += 1
        self._serialize_round(round_num, records)
        self._save()

    def skip_phase(self, round_num: int, phase_name: str, reason: str = ""):
        """标记阶段跳过（skipped）"""
        records = self._ensure_round(round_num)
        if phase_name not in records:
            return
        rec = records[phase_name]
        rec.status = "skipped"
        rec.completed_at = datetime.now().isoformat()
        if reason:
            rec.error = reason
        self._serialize_round(round_num, records)
        self._save()

    def retry_phase(self, round_num: int, phase_name: str):
        """标记阶段重试：将 failed 状态重置为 pending，retry_count 已递增"""
        records = self._ensure_round(round_num)
        if phase_name not in records:
            return
        rec = records[phase_name]
        if rec.status == "failed":
            rec.status = "pending"
            rec.started_at = None
            rec.completed_at = None
            rec.error = None
        self._serialize_round(round_num, records)
        self._save()

    # ── 查询 ──

    def get_round_phases(self, round_num: int) -> Dict[str, PhaseRecord]:
        """获取某轮的所有阶段记录"""
        return self._ensure_round(round_num)

    def get_phase(self, round_num: int, phase_name: str) -> Optional[PhaseRecord]:
        """获取某轮的指定阶段记录"""
        records = self._ensure_round(round_num)
        return records.get(phase_name)

    def get_current_phase(self, round_num: int) -> Optional[str]:
        """获取当前正在执行的阶段名称"""
        records = self._ensure_round(round_num)
        for name in PHASE_ORDER:
            if records[name].status == "running":
                return name
        return None

    def get_round_status_summary(self, round_num: int) -> str:
        """
        从子阶段推导轮次总体状态
        - 全部 completed → completed
        - 有 failed → failed
        - 有 running → running
        - 其他 → pending
        """
        records = self._ensure_round(round_num)
        statuses = {rec.status for rec in records.values()}
        if all(s == "completed" for s in statuses):
            return "completed"
        if "failed" in statuses:
            return "failed"
        if "running" in statuses:
            return "running"
        return "pending"

    def get_completed_phases(self, round_num: int) -> List[str]:
        """获取已完成阶段列表"""
        records = self._ensure_round(round_num)
        return [name for name in PHASE_ORDER if records[name].status == "completed"]

    def get_all_rounds(self) -> Dict[str, Dict[str, PhaseRecord]]:
        """获取所有轮次的阶段记录"""
        result = {}
        for key, raw_round in self._data.get("rounds", {}).items():
            result[key] = {
                name: PhaseRecord.from_dict(name, raw_round.get(name, {"status": "pending"}))
                for name in PHASE_ORDER
            }
        return result

    def infer_past_round_phases(self, round_num: int, config_status: str):
        """
        对已有但无 phase 记录的轮次，从 config status 推断 phase 完成状态。
        用于迁移旧 workspace。
        """
        records = self._ensure_round(round_num)
        # 检查是否已有详细记录
        has_details = any(rec.status != "pending" for rec in records.values())
        if has_details:
            return  # 已有记录，跳过

        # 根据 config status 推断
        if config_status in ("achieved", "manual_stop", "max_rounds"):
            # 终止轮次：假设前 3 个 phase 完成（apply/evaluate/score），proposal 可能未完成
            for name in PHASE_ORDER[:3]:
                records[name].status = "completed"
                records[name].completed_at = datetime.now().isoformat()
        elif "evaluated" in config_status:
            for name in PHASE_ORDER[:3]:
                records[name].status = "completed"
                records[name].completed_at = datetime.now().isoformat()

        self._serialize_round(round_num, records)
        self._save()
