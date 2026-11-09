"""
StateEngine - 状态机引擎
=========================
职责：
1. 管理状态转换：INIT → EVALUATE → DECIDE → OPTIMIZE → (NEXT_ROUND | FINISH)
2. 状态恢复逻辑修复：从 config 恢复时 round_num = current_round + 1
3. 状态持久化：每个状态转换后自动保存 config.json
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 添加 scripts 目录到路径
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from . import DEFAULT_TARGET_SCORE
from .persistence import ArtifactStore, ConfigStore
from .phase_tracker import PhaseTracker


class StateEngine:
    """
    状态机引擎

    状态流转：
    - init_complete: 初始化完成
    - round_{N}_ready: 准备执行第 N 轮
    - achieved: 达到目标分数
    - max_rounds: 达到最大轮次
    - manual_stop: 手动停止
    """

    # 终止状态
    TERMINAL_STATES = {"achieved", "max_rounds", "manual_stop"}

    def __init__(self, workspace: Path, args):
        self.workspace = Path(workspace).resolve()
        self.args = args
        # Agent 模式：优先使用原始 skill 路径（非 workspace 副本）
        self._original_skill_path = Path(getattr(args, 'original_skill_path', args.skill_path)).resolve()
        self.skill_path = Path(args.skill_path)  # 运行时指向 workspace 副本
        # 统一目录：skill/{name}/，所有模式一致
        self.skill_name = self.skill_path.parent.name  # skill 目录名

        # 持久化层
        self.config_store = ConfigStore(self.workspace)
        self.artifact_store = ArtifactStore(self.workspace)

        # 当前状态
        self.current_round: int = 1
        self.status: str = "init_complete"
        self.config: Optional[Dict] = None

        # 评测历史（in-memory,权威;不再写 self.config["history"]）
        self.history: List[Dict] = []
        # 实时分数（in-memory,权威;不再写 self.config["current_score" / "best_score"]）
        self.current_score: float = 0.0
        self.best_score: float = 0.0
        self.best_round: int = -1
        self.best_candidate_id: int = -1  # 产生 best_score 的候选 ID，供跨轮继承
        # baseline_score（in-memory,权威;不再写 self.config["baseline_score"]）
        self.baseline_score: float = 0.0

        # 最后一轮评测的 metadata（含量化数据），供 generate_summary 使用
        self._last_eval_metadata: Dict = {}

        # 各轮缺口详情，供诊断分析使用
        self.gaps_by_round: List[List[Dict]] = []

        # 广度优先：候选池 {round_num: [candidate_info, ...]}（in-memory,权威）
        self.candidate_pool: Dict[str, List[Dict]] = {}

        # 细粒度阶段追踪
        self.phase_tracker = PhaseTracker(self.workspace)

    def initialize(self) -> bool:
        """
        初始化或恢复状态

        修复 Bug：正确处理状态恢复
        - 新任务：从 round 0 开始
        - 恢复任务：从 current_round + 1 开始（跳过已完成的轮次）
        """
        # 确保必要目录存在
        self.artifact_store.ensure_dirs(self.workspace)

        # 尝试自动迁移旧版平铺产物结构
        try:
            self.artifact_store.migrate_from_flat(self.workspace)
        except Exception:
            pass  # 迁移失败不影响启动

        # 尝试加载已有配置
        self.config = self.config_store.load()

        # 拷贝原始 skill 到 workspace，后续所有操作基于 workspace 副本
        is_new_task = self.config is None
        self._init_workspace_skill(is_new_task)

        if self.config is None:
            # 新任务：初始化
            self.current_round = 1
            self.status = "init_complete"
            self.history = []

            # 广度优先参数
            candidates_per_round = getattr(self.args, 'candidates_per_round', 1)
            sub_rounds_per_candidate = getattr(self.args, 'sub_rounds_per_candidate', 1)
            eval_runs_per_candidate = getattr(self.args, 'eval_runs_per_candidate', 3)

            # 从 CLI args 构建 target_skills 列表（统一单/多 Skill 模式）
            if hasattr(self.args, 'skill_paths') and self.args.skill_paths:
                orig_paths = [str(Path(p).resolve()) for p in self.args.skill_paths]
            elif hasattr(self.args, 'skill_path') and self.args.skill_path:
                orig_paths = [str(self._original_skill_path)]
            else:
                orig_paths = [str(self._original_skill_path)]

            target_skills = []
            for orig_path in orig_paths:
                name = Path(orig_path).parent.name
                ws_path = str((self.workspace / "skill" / name / "SKILL.md").resolve())
                target_skills.append({
                    "name": name,
                    "original_path": orig_path,
                    "workspace_path": ws_path,
                })
            self.target_skills = target_skills

            self.config = {
                "target_skills": target_skills,
                "max_rounds": self.args.max_rounds,
                "project_root": str(self.workspace),
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                # 🆕 2026-08:专家指引(CLI --expert-guidance 传入)。任务中可在 config.json 编辑此字段,
                # 下一轮 ProposalAgent(run_optimize_agent)读到新值作为重要建议引导优化方向。
                "expert_guidance": (getattr(self.args, "expert_guidance", "") or "").strip(),
            }
            self.config_store.save(self.config)

            # 同步初始状态到 task_state.json（仅状态字段）
            self.record_current_progress(
                status=self.status,
                detail=f"初始化完成,目标 {len(target_skills)} 个 Skill",
                round_num=self.current_round,
                phase="init",
            )

            print("✅ 初始化完成")
            print(f"   目标 Skill 数: {len(target_skills)}")
            for i, ts in enumerate(target_skills, 1):
                print(f"     [{i}] {ts['name']}")
            print(f"   目标分数: >= {DEFAULT_TARGET_SCORE}")
            print(f"   最大轮次: {self.args.max_rounds}")
            return True
        else:
            # 恢复任务：current 段只读状态字段; history/分数全从 config 读
            cur = self.phase_tracker.get_current_progress() or {}
            self.current_round = self._resolve_start_round(self.config, self.args)
            self.status = cur.get("status") or self.config.get("status", "round_ready")
            self.history = self.config.get("history", [])
            self.gaps_by_round = self.config.get("gaps_summary", [])
            # 实时分/状态从 config 恢复（task_state.json 极简版不存结果数据）
            self.current_score = self.config.get("current_score", 0) or 0
            self.best_score = self.config.get("best_score", 0) or 0
            self.best_round = self.config.get("best_round", -1)
            if self.best_round is None:
                self.best_round = -1
            self.best_candidate_id = self.config.get("best_candidate_id", -1) or -1
            self.baseline_score = self.config.get("baseline_score", 0) or 0

            # 检查是否已终止
            if self.status in self.TERMINAL_STATES:
                print(f"从已有 task_state 恢复: round={self.current_round}, score={self.current_score}")
                print(f"状态: {self.status}，任务已结束。")
                return False

            print(f"从已有 task_state 恢复: round={self.current_round}, score={self.current_score}")
            print(f"   继续执行第 {self.current_round} 轮...")
            return True

    def _resolve_start_round(self, config: Dict, args) -> int:
        """
        状态恢复：正确计算起始轮次

        语义约定：
        - init_complete / round_N_ready: 尚未执行，current_round 即为待执行轮次
        - round_N_evaluated: 已完成评测，下一轮是 current_round + 1
        - 终止状态: 不再执行
        """
        current_round = config.get("current_round", 1)
        status = config.get("status", "")

        if status in self.TERMINAL_STATES:
            return current_round  # 不会再进主循环

        # 向后兼容：旧 config 的 current_round=0 视为已完成初始化，从 1 开始
        if current_round == 0 and status == "init_complete":
            return 1

        # 尚未执行或已就绪的状态：current_round 即待执行轮次，不需要 +1
        if status in ("init_complete",) or status.endswith("_ready"):
            return current_round

        # 已完成的状态：current_round 是刚完成的轮次，下一轮是 +1
        return current_round + 1

    def _init_workspace_skill(self, is_new_task: bool = False):
        """
        将原始 skill 拷贝到 workspace，后续所有操作基于 workspace 副本。

        统一目录结构：skill/{name}/SKILL.md（单/多 Skill 一致）

        这样做的目的：
        1. 保护原始 skill 不被优化过程修改
        2. 快照和优化操作基于 workspace 副本，保证一致性
        3. 多轮迭代中 skill 的演进只影响 workspace
        """
        import shutil

        skill_name = self._original_skill_path.parent.name
        workspace_skill_dir = self.workspace / "skill" / skill_name
        original_skill_dir = self._original_skill_path.parent

        if not is_new_task:
            # 恢复场景：从 config 获取 workspace skill 路径
            stored_ws_skill = (self.config or {}).get("skill_registry", {}).get(self.skill_name, "")
            if stored_ws_skill and Path(stored_ws_skill).exists():
                self.skill_path = Path(stored_ws_skill)
                return

        # 新任务：拷贝原始 skill 到 workspace/skill/{name}/
        if workspace_skill_dir.exists():
            # 保护：当原始目录和 workspace 目录重合时，先搬到临时位置
            if original_skill_dir.resolve() == workspace_skill_dir.resolve():
                import tempfile
                tmp_dir = tempfile.mkdtemp(prefix="skillx-skill-backup-")
                try:
                    shutil.copytree(str(workspace_skill_dir), tmp_dir, dirs_exist_ok=True)
                    shutil.rmtree(str(workspace_skill_dir))
                    shutil.copytree(tmp_dir, str(workspace_skill_dir))
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
            else:
                shutil.rmtree(str(workspace_skill_dir))
                shutil.copytree(str(original_skill_dir), str(workspace_skill_dir))
        else:
            shutil.copytree(str(original_skill_dir), str(workspace_skill_dir))
        self.skill_path = workspace_skill_dir / "SKILL.md"

        # 🆕 origin_skill:不可变基线(从原始路径拷贝,永远不再修改)
        # 用户设定:基线 = 任务传参的原始 skill,存到 origin_skill/ 后任何逻辑都不得改写它。
        # skill/(workspace 工作副本)可被每轮 inherit 改写;origin_skill 只读,供参照/回滚。
        origin_skill_dir = self.workspace / "origin_skill" / skill_name
        if not origin_skill_dir.exists():
            shutil.copytree(str(original_skill_dir), str(origin_skill_dir))

    def update_after_evaluation(self, eval_result: Dict, round_num: int):
        """
        评测后更新状态

        Args:
            eval_result: 评测结果 dict，包含 score, rating, total_gaps, skill_snapshot, metadata
            round_num: 当前轮次
        """
        # 存储最后一轮的量化数据，供 generate_summary 使用
        self._last_eval_metadata = eval_result.get("metadata", {})

        # 累积本轮缺口详情，供诊断分析使用
        gaps = eval_result.get("gaps", [])
        self.gaps_by_round.append(gaps)

        score = eval_result["score"]
        rating = eval_result["rating"]
        total_gaps = eval_result["total_gaps"]
        snapshot = eval_result.get("skill_snapshot", "")

        # 记录历史
        record = {
            "round": round_num,
            "score": score,
            "rating": rating,
            "total_gaps": total_gaps,
            "skill_snapshot": snapshot,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.history.append(record)

        # 更新 in-memory 状态（权威）
        self.current_round = round_num
        self.current_score = score
        if score > self.best_score:
            self.best_score = score
            self.best_round = round_num

        # 判断状态
        if score >= DEFAULT_TARGET_SCORE:
            self.status = "achieved"
        else:
            self.status = f"round_{round_num}_evaluated"

        # 同步到 task_state.json（仅状态字段；结果数据存 config.history，不写 task_state）
        self.record_current_progress(
            status=self.status,
            detail=f"round {round_num} 评测完成 score={score:.2f}",
            round_num=round_num,
            phase="evaluate",
        )

    def should_stop(self) -> bool:
        """判断是否应该停止

        注意：current_round 是「即将执行的轮次」，不是「已执行的轮次」。
        should_stop() 返回 True 仅表示已达终止状态（达标/手动停止）。
        轮次上限由主循环的 current_round > max_rounds 控制。
        """
        if self.status in self.TERMINAL_STATES:
            return True
        return False

    def should_optimize(self, eval_result: Dict) -> bool:
        """判断是否应该优化"""
        if self.status in self.TERMINAL_STATES:
            return False
        total_gaps = eval_result.get("total_gaps", 0)
        return total_gaps > 0

    def next_round(self):
        """进入下一轮（仅在非终止状态下推进）"""
        if self.status in self.TERMINAL_STATES:
            return  # 不覆盖终止状态
        self.current_round += 1
        self.status = f"round_{self.current_round}_ready"

        # 同步到 task_state.json
        self.record_current_progress(
            status=self.status,
            detail=f"进入 round {self.current_round}",
            round_num=self.current_round,
            phase="init",
        )

    def begin_round(self, round_num: int):
        """标记新一轮开始，更新 current_round 和 status"""
        self.current_round = round_num
        self.status = f"round_{round_num}_ready"

        # 同步到 task_state.json（仅状态字段）
        self.record_current_progress(
            status=self.status,
            detail=f"开始 round {round_num}",
            round_num=round_num,
            phase="init",
        )

    def end_round(self, round_num: int, score: float, gaps: list, metadata: Optional[Dict] = None):
        """记录轮次完成，更新分数、最佳、历史"""
        record = {
            "round": round_num,
            "score": score,
            "total_gaps": len(gaps),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if metadata:
            record.update(metadata)
        self.history.append(record)

        # 更新 in-memory 状态（权威）
        self.current_round = round_num
        self.current_score = score
        if score > self.best_score:
            self.best_score = score
            self.best_round = round_num

        # 同步到 task_state.json（仅状态字段；结果数据已写入 self.history/config）
        self.record_current_progress(
            status=f"round_{round_num}_completed",
            detail=f"round {round_num} 完成 score={score:.2f}",
            round_num=round_num,
            phase="proposal",
        )

    def merge_config(self, updates: Dict[str, Any]):
        """合并额外字段到 config 并持久化"""
        self.config.update(updates)
        self.config_store.save(self.config)

    def apply_proposal(self, proposal_path: str):
        """应用提案"""
        if os.path.exists(proposal_path):
            with open(proposal_path, "r", encoding="utf-8") as f:
                improved = f.read()
            from .persistence import atomic_write
            atomic_write(str(self.skill_path), improved)
            print("  ✅ 提案已应用")

    def _clean_artifacts(self):
        """清理旧产物（config.json、baseline/、round_N/）"""
        import shutil as _shutil
        items = [
            self.workspace / "config.json",
            self.workspace / "baseline",
            self.workspace / "round_0",
            self.workspace / "round_1",
            self.workspace / "round_2",
            self.workspace / "round_3",
            self.workspace / "round_4",
            self.workspace / "round_5",
        ]
        for item in items:
            if item.exists():
                try:
                    if item.is_dir():
                        _shutil.rmtree(str(item), ignore_errors=True)
                    else:
                        item.unlink()
                    print(f"  🧹 已清理: {item}")
                except Exception as e:
                    print(f"  ⚠️ 清理失败 {item}: {e}")

    @property
    def is_terminal(self) -> bool:
        """是否处于终止状态"""
        return self.status in self.TERMINAL_STATES

    @property
    def score(self) -> float:
        """当前分数(in-memory 权威)"""
        return self.current_score

    @property
    def skill_dir(self) -> Path:
        """Skill 目录"""
        return self.skill_path.parent

    # ── 广度优先候选管理 ──────────────────────────────

    def is_breadth_first(self) -> bool:
        """是否启用广度优先模式（>=1 即启用，1 也是候选生成）"""
        return getattr(self.args, 'candidates_per_round', 0) >= 1

    def candidates_per_round(self) -> int:
        """每轮候选数"""
        return getattr(self.args, 'candidates_per_round', 1)

    def sub_rounds_per_candidate(self) -> int:
        """每个候选的子优化轮次"""
        return getattr(self.args, 'sub_rounds_per_candidate', 1)

    def eval_runs_per_candidate(self) -> int:
        """每个候选的独立评测次数"""
        return getattr(self.args, 'eval_runs_per_candidate', 3)

    def record_candidate(self, candidate_id: int, score: float, strategy: str,
                         rating: str, total_gaps: int, round_num: int,
                         run_scores: Optional[List[float]] = None,
                         stddev: Optional[float] = None):
        """
        记录候选分数到 config

        Args:
            candidate_id: 候选 ID
            score: 评测分数（多次评测的平均分）
            strategy: 优化策略（如 tier1, tier2_v2）
            rating: 评级
            total_gaps: 缺口数
            round_num: 轮次编号
            run_scores: 各次独立评测的分数列表
            stddev: 分数标准差
        """
        round_key = str(round_num)
        if round_key not in self.candidate_pool:
            self.candidate_pool[round_key] = []

        entry = {
            "id": candidate_id,
            "score": score,
            "strategy": strategy,
            "rating": rating,
            "total_gaps": total_gaps,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if run_scores is not None:
            entry["run_scores"] = run_scores
        if stddev is not None:
            entry["stddev"] = stddev

        self.candidate_pool[round_key].append(entry)

        # candidate_pool 仅 in-memory 维护 + 落 config.json,task_state.json 极简版不存结果数据

    def select_best_candidate(self, round_num: int) -> Optional[Dict]:
        """
        选择当前轮次最佳候选

        Returns:
            最佳候选信息 dict，或 None（如果候选池为空）
        """
        round_key = str(round_num)
        pool = self.candidate_pool.get(round_key, [])
        if not pool:
            return None
        return max(pool, key=lambda c: c["score"])

    def get_baseline_score(self) -> float:
        """获取当前基线分数（best_score,in-memory 权威）"""
        return self.best_score

    def save_baseline_score(self, bl_avg, bl_runs=None, bl_std=None):
        """
        保存 baseline 分数到 task_state.json(权威源)

        合并 baseline_score + aggregate_baseline 为单字段 current.baseline_score。
        """
        baseline_score = bl_avg if bl_avg is not None else 0.0
        # 更新 in-memory 状态
        self.baseline_score = baseline_score
        self.current_score = baseline_score
        if baseline_score > self.best_score:
            self.best_score = baseline_score
            self.best_round = -1

        # 同步到 task_state.json（仅状态字段；结果数据存 config.baseline_score）
        self.record_current_progress(
            status="baseline_done",
            detail=f"baseline 评测完成,平均分 {baseline_score:.2f}",
            round_num=0,
            phase="baseline_done",
        )

    # ── Phase 追踪委托方法 ──

    def record_phase_start(self, round_num: int, phase_name: str):
        """记录阶段开始"""
        self.phase_tracker.start_phase(round_num, phase_name)

    def record_phase_complete(self, round_num: int, phase_name: str):
        """记录阶段完成"""
        self.phase_tracker.complete_phase(round_num, phase_name)

    def record_phase_fail(self, round_num: int, phase_name: str, error: str = ""):
        """记录阶段失败"""
        self.phase_tracker.fail_phase(round_num, phase_name, error)

    def record_phase_skip(self, round_num: int, phase_name: str, reason: str = ""):
        """记录阶段跳过"""
        self.phase_tracker.skip_phase(round_num, phase_name, reason)

    def record_current_progress(self, status: str, detail: str = "",
                                round_num: int = -1, phase: str = "") -> None:
        """记录 current 段进度（替代原 _write_progress）。

        写入 task_state.json 的 current 字段，供外部监控读取。
        与 rounds 段共享同一文件，原子写保证 current/rounds 一致性。
        """
        self.phase_tracker.update_current(status, detail, round_num, phase)

    def get_current_progress(self) -> Optional[Dict[str, Any]]:
        """获取 current 段（外部消费者读取入口）"""
        return self.phase_tracker.get_current_progress()

    def get_round_phase_summary(self, round_num: int) -> Dict[str, str]:
        """获取某轮的阶段状态摘要 {phase_name: status}"""
        records = self.phase_tracker.get_round_phases(round_num)
        return {name: rec.status for name, rec in records.items()}