"""
提案/优化模块
=============

负责提案生成、gap 提取、基线评分保存等优化相关操作。

职责边界：
- 基于 history 重新生成提案（Solution C：避免重复失败方向）
- 从评测详情中提取 gaps
- 解析 proposal.md 中的 modifications 摘要
- 保存 baseline 分数到 task_state.json
- Agent 模式基线评测
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

# ── 内部辅助函数 ──────────────────────────────────────────

def _extract_pipeline_commands_inline(args) -> list:
    """从 pipeline 配置中提取评测命令列表（无缓存版本）。

    优先级：
    1. args.pipeline_eval_cmd（用户直接传入的命令字符串）
    2. args.pipeline_config_dict（config.json["pipeline"] 字段，dict 形态）
    3. args.pipeline_config（显式指定的 YAML 文件，仅作历史兼容兜底）
    """
    # 1. 优先：直接传入的命令字符串
    pipeline_eval_cmd = getattr(args, 'pipeline_eval_cmd', '') or ''
    if pipeline_eval_cmd:
        return [pipeline_eval_cmd]

    # 2. 从 args.pipeline_config_dict 提取（主路径，由 eval_pipeline 注入）
    pipeline_dict = getattr(args, 'pipeline_config_dict', None) or {}
    if pipeline_dict:
        steps = pipeline_dict.get("steps", []) or []
        cmds = [s.get("command", "") for s in steps if s.get("command")]
        return [c for c in cmds if c]

    # 3. 历史兼容：仅当显式传入 YAML 路径时才尝试加载（不自动发现）
    pipeline_config = getattr(args, 'pipeline_config', '') or ''
    if not pipeline_config:
        return []

    p = Path(pipeline_config)
    if not p.exists():
        return []
    try:
        import yaml
        text = p.read_text(encoding="utf-8")
        cfg = yaml.safe_load(text) or {}
        pipeline = cfg.get("pipeline", cfg)
        steps = pipeline.get("steps", [])
        return [s.get("command", "") for s in steps if s.get("command")]
    except Exception:
        return []


# ── Gap 提取 ──────────────────────────────────────────────

def extract_gaps_from_details(bl_details, score_baseline_path: str = None) -> list:
    """从评测详情中提取最后一次有 gaps 的评测结果。

    优先级：
    1. bl_details 中 run 字典的 gaps 字段（来自 eval_result.gaps）
    2. score_baseline.json 顶层 gaps 字段（来自 ProposalAgent）
    """
    if bl_details:
        for rd in reversed(bl_details):
            if isinstance(rd, dict) and rd.get("gaps"):
                return rd["gaps"]
    # 兜底：从 score_baseline.json 顶层读 gaps（由 analyze_baseline 写入）
    if score_baseline_path:
        p = Path(score_baseline_path)
        if p.exists():
            try:
                sd = json.loads(p.read_text(encoding="utf-8"))
                gaps_top = sd.get("gaps", [])
                if gaps_top:
                    return gaps_top
            except Exception:
                pass
    return []


# ── Proposal 解析 ─────────────────────────────────────────

def parse_proposal_modifications_summary(proposal_path) -> list:
    """从 baseline/proposal.md 解析 modifications 摘要列表。

    返回: [{"index": 1, "action": "MODIFY", "file": "X.md", "section": "Y", "reason": "..."}, ...]

    设计:仅作历史回顾用,不在 apply 阶段被改写。失败 → 返回 []。
    """
    import re
    p = Path(proposal_path) if not isinstance(proposal_path, Path) else proposal_path
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        return []

    out = []
    # 匹配 `### N. [ACTION] file → section`
    pattern = re.compile(r"^###\s+(\d+)\.\s*\[(\w+)\]\s*(.+?)\s*→\s*(.+?)\s*$", re.MULTILINE)
    for m in pattern.finditer(text):
        idx, action, file_path, section = m.group(1), m.group(2), m.group(3), m.group(4)
        # 在该 header 之后,定位 **理由**: 描述,直到下一空行 / 下个 ### / EOF
        tail = text[m.end():]
        reason = ""
        rm = re.search(r"\*\*理由\*\*[::]\s*(.+?)(?=\n\s*\n|\n###|\Z)", tail, re.DOTALL)
        if rm:
            reason = " ".join(rm.group(1).split())[:200]  # 截前 200 字符,去多余空白
        out.append({
            "index": int(idx),
            "action": action,
            "file": file_path,
            "section": section,
            "reason": reason,
        })
    return out


# ── 基线评分保存 ──────────────────────────────────────────

def save_baseline_score(state_engine, bl_avg, bl_runs, bl_std):
    """保存 baseline 分数到 task_state.json(权威源)。

    旧版会同步写到 state_engine.config["baseline_score"/"current_score"/"best_score"],
    现已全部迁移到 task_state.json(通过 state_engine.save_baseline_score)。
    """
    # 记录评测命令（配置项,仍走 config）
    # 内联提取逻辑，避免循环依赖 orchestrator.py
    _cmds = _extract_pipeline_commands_inline(state_engine.args)
    if _cmds and "eval_command" not in state_engine.config:
        state_engine.config["eval_command"] = _cmds[0]
        state_engine.config["eval_commands"] = _cmds
        state_engine.config_store.save(state_engine.config)

    # 实时分/状态走 task_state.json
    state_engine.save_baseline_score(bl_avg, bl_runs, bl_std)

    # 注：score_baseline.json 由后续 analyzer.analyze_baseline 统一写（包含 per_ran、rule_scores 等详细字段）。
    # 此处不再调 save_baseline_score，避免与 analyze_baseline 写同一文件导致互相覆盖。


def evaluate_baseline_agent(state_engine, args) -> tuple:
    """
    Agent 模式基线评测（端到端：一次执行，所有 Skill 一起）

    流程:
    1. 对每个 baseline run:
       a) run_evaluation 跑业务方评测命令(归档 data/ 到 run_X/data/)
       b) analyze_run 由 LLM 探查 data/,生成 score_analysis.md + score.json
       c) 从 score.json 读 result_score 作为该 run 的真实分数
    2. 全部 run 完成后,调 analyze_baseline 汇总写 score_baseline.json + proposal.md

    Returns:
        (bl_avg, bl_runs, bl_std, bl_gaps) — 与 orchestrator.py 调用方解包顺序一致
    """
    from orchestrators.eval_pipeline import run_evaluation

    # workspace 下建 baseline 目录（直接位于 taskid 根）
    workspace = Path(args.workspace)
    baseline_dir = workspace / "baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    # Skill 已提前拷贝到 baseline/skill/{name}/（由调用方负责）
    # 评测参数：skill_path 传第一个 skill（pipeline 不关心具体路径，仅用于日志）
    skill_paths = getattr(args, 'skill_paths_original', None) or []
    eval_skill_path = skill_paths[0] if skill_paths else getattr(args, 'skill_path', '')

    # 复用 orchestrator 上下文里同一份 ScoreAnalyzerAgent 配置(避免重复初始化)
    # MetricsConfig.default_eval_config() 与候选路径 (orchestrator.py:664-667) 完全对称
    from metrics.config import MetricsConfig
    from scorer import ScoreAnalyzerAgent
    _metrics_config = MetricsConfig.load()
    bl_analyzer = ScoreAnalyzerAgent(_metrics_config)

    bl_runs = []
    bl_details = []
    # 字段名兜底链:baseline_runs(显式) → eval_runs_per_candidate(CLI 传的) → 1
    # 历史 bug:run_agent_loop 之前只传 eval_runs_per_candidate,没复制到 baseline_runs,
    # 导致 Agent 模式 baseline 永远只跑 1 次,与 --eval-runs-per-candidate N 不一致。
    num_runs = (getattr(args, 'baseline_runs', 0) or 0) \
               or (getattr(args, 'eval_runs_per_candidate', 0) or 0) \
               or 1

    # baseline 在 Agent 模式下需要为 analyze_run 透传 case_ids(与候选路径对称)
    _case_ids = state_engine.config.get("case_ids") or None

    for run_idx in range(1, num_runs + 1):
        run_dir = baseline_dir / f"run_{run_idx}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Skill 快照到 run 目录
        bl_skill_dir = baseline_dir / "skill"
        if bl_skill_dir.exists():
            run_skill_dir = run_dir / "skill"
            if run_skill_dir.exists():
                import shutil
                shutil.rmtree(str(run_skill_dir))
            import shutil
            shutil.copytree(str(bl_skill_dir), str(run_skill_dir))

        # 关键修复:为 baseline run 设置 eval_mode/eval_run_index,
        # 与候选路径 (eval_mode="candidate", eval_run_index=N) 对称
        # 否则 workflow_pipeline._get_archive_dir 会走 else 分支落到 round_0/data
        args.eval_mode = "baseline"
        args.eval_run_index = run_idx
        args.candidate_id = -1

        result = run_evaluation(
            state_engine,
            args,
            round_num=0,
            is_baseline=True,
        )

        # 关键修复:run_evaluation 仅归档 data/,不写 score.json(返回 score=0 占位)。
        # 必须立即调 analyze_run 让 LLM 探查 data/,生成 score_analysis.md + score.json,
        # 否则下方从 result 取 "score" 永远是 0,bl_avg 也永远是 0。
        # (与 orchestrator.py 候选路径完全对称,见 run_agent_loop 中 candidate_analyzer.analyze_run)
        run_score = 0.0
        if run_dir.exists() and (run_dir / "data").exists():
            try:
                from orchestrators.workspace import _analyze_run_with_evidence_retry as _analyze_retry
                rs = _analyze_retry(
                    bl_analyzer, run_dir, 0, -1, run_idx,
                    case_ids=_case_ids,
                )
                # 优先读 score.json 的 result_score(LLM 探查后写入)
                score_json = run_dir / "score.json"
                if score_json.exists():
                    try:
                        sd = json.loads(score_json.read_text(encoding="utf-8"))
                        _rs = sd.get("result_score")
                        if _rs is not None:
                            run_score = float(_rs)
                    except Exception:
                        pass
                # 兜底:从 RunScore 对象读
                if run_score == 0.0 and rs is not None:
                    raw = getattr(rs, "raw", None)
                    if raw is not None and getattr(raw, "result_score", None) is not None:
                        run_score = float(raw.result_score) or 0.0
            except Exception as _e:
                print(f"  ⚠️ baseline run {run_idx} analyze_run 失败: {_e}")

        bl_runs.append(run_score)
        bl_details.append(result if isinstance(result, dict) else {})
        print(f"  📊 baseline run {run_idx}: {run_score:.2f}")

    if bl_runs:
        bl_avg = sum(bl_runs) / len(bl_runs)
        if len(bl_runs) > 1:
            import statistics
            bl_std = statistics.stdev(bl_runs)
        else:
            bl_std = 0.0
    else:
        bl_avg = 0
        bl_std = 0

    # 兜底：bl_runs 为空时 std 需为 0.0（不是 0），避免下游 .is None 检查混淆
    bl_std = bl_std if bl_std is not None else 0.0
    bl_runs = bl_runs if bl_runs else [float(bl_avg)]

    # 关键修复:必须保存 baseline 分数到 task_state.json(权威源)。
    # 旧版 evaluate_baseline_agent 仅返回 bl_avg,但没有调用 save_baseline_score,
    # 导致 eng.baseline_score 保持 0.0,current.baseline_score 字段缺失。
    save_baseline_score(state_engine, bl_avg, bl_runs, bl_std)

    # 所有 run 完成后,汇总写 score_baseline.json + proposal.md(LLM 基于全部 run 生成提案)
    try:
        bl_analyzer.analyze_baseline(baseline_dir, 0, case_ids=_case_ids)
    except Exception as _e:
        print(f"  ⚠️ baseline analyze_baseline 汇总失败(不影响主流程): {_e}")

    # 提取 gaps（来自 bl_details 中最后一次有 gaps 的评测结果）
    bl_gaps = extract_gaps_from_details(
        bl_details,
        score_baseline_path=str(baseline_dir / "score_baseline.json"),
    )

    return bl_avg, bl_runs, bl_std, bl_gaps


# ── Proposal 重生（Solution C） ───────────────────────────

def regenerate_proposal_with_history(
    eng: "StateEngine",
    args,
    round_num: int,
    candidate_analyzer: "ScoreAnalyzerAgent",
) -> bool:
    """
    Solution C:round > 1 且 history 非空时,基于 history 重新生成 baseline/proposal.md。

    触发条件:
    - round_num > 1
    - eng.history 非空(说明上轮已记录)
    - 上轮 decision=not_adopted(分数下降,采纳基线没意义,必须换方向)
    - 上轮 modifications_summary 非空

    行为:
    - 读 eng.history[-1] 构造 prev_failure_block(同 Solution B 的注入逻辑)
    - 构造 round_score(只含 baseline_score,无需新跑 eval)
    - 调 candidate_analyzer._generate_proposal_via_agent() 重新生成 baseline/proposal.md
    - ProposalAgent 的 Stage 3 收到 prev_failure_block,主动避开上轮的 file+section 组合

    Returns:
        True 成功重新生成, False 跳过(条件不满足或失败)
    """
    if round_num <= 1:
        return False
    if not eng.history:
        return False

    _hist = eng.history if hasattr(eng, "history") else eng.config.get("history", [])
    if not _hist:
        return False
    _prev = _hist[-1]
    _prev_decision = _prev.get("decision", "adopted")
    # 即使上轮 adopted,基线状态已变(上轮 mods 已应用到 skill 副本),旧 proposal 的
    # modifications file+section 组合已被应用,本轮 ApplyAgent 必触发"铁律禁止重复" → applied=0
    # 因此 prev_decision=adopted 也要重生 proposal,用 prev_failure_block 强制换方向
    _prev_mods = _prev.get("modifications_summary", [])
    if not _prev_mods:
        print("  [Solution C] 上轮 modifications_summary 为空,无需重生 proposal")
        return False

    # 构造 prev_failure_block(同 Solution B 的注入逻辑)
    _prev_round = _prev.get("round", round_num - 1)
    _prev_score = _prev.get("score", 0)
    _prev_baseline = _prev.get("baseline_score", 0)
    _prev_delta = _prev.get("vs_baseline_delta", 0)
    _mods_text = ""
    for _m in _prev_mods[:8]:
        _mods_text += (
            f"  - M{_m.get('index', '?')} [{_m.get('action', '?')}] "
            f"{_m.get('file', '?')} → {_m.get('section', '?')}\n"
            f"    reason: {(_m.get('reason') or '')[:120]}\n"
        )
    if not _mods_text:
        _mods_text = "  - (上轮无 modifications 记录)\n"
    prev_failure_block = (
        f"\n## ⚠️ 上轮失败回顾(round {_prev_round}, Solution C 必须避免重复)\n"
        f"- 上轮决策: **{_prev_decision}** "
        f"({('分数提升, 已采纳' if _prev_decision == 'adopted' else '分数未提升, 保留旧基线')})\n"
        f"- 上轮最佳候选分数: **{_prev_score}** "
        f"(基线 {_prev_baseline}, 增量 {_prev_delta:+.2f})\n"
        f"- 上轮执行的 modifications 摘要(前 {min(8, len(_prev_mods))} 条):\n"
        f"{_mods_text}"
        f"- **本轮铁律(ProposalAgent Stage 3 必须遵守)**:\n"
        f"  1. **禁止**重复上轮已尝试的 modifications(file + section 组合相同 → 必须跳过)\n"
        f"  2. 必须**分析上轮失败根因**,针对性调整方向(file/section/action 至少 1 项不同)\n"
        f"  3. 调整方向示例:\n"
        f"     - 上轮加 '执行步骤' → 本轮改 '加载上下文' 或 '前置要求'\n"
        f"     - 上轮加 '执行步骤' → 本轮改 '产物格式' 或 '早退规则'\n"
        f"     - 上轮加 '边界清单' → 本轮改 '必填字段校验' 或 '异常处理'\n"
        f"  4. 调整方向必须**有可验证的根因**支撑(不能凭感觉换)\n\n"
    )

    # 构造 round_score(只含 baseline_score,不需要新跑 eval)
    from dataclasses import dataclass, field
    from typing import Optional as _Opt

    @dataclass
    class _StubCandidate:
        result_score: float = 0.0
        case_run_matrix: dict = field(default_factory=dict)
        composite: float = 0.0
        num_runs: int = 0
        strategy: str = "stub"
        candidate_id: int = -1
        # 镜像 CandidateScore.runs:List[RunScore],供 _fallback_stage_2 访问
        # stub 没有真实 run 详情,留空即可——gap_extractor 会自然返回 [],
        # proposal 仅靠 prev_failure_block 即可重生
        runs: List = field(default_factory=list)
        # 补 CandidateScore 的全部字段,避免后续代码访问 .per_case_stddev 等属性时 AttributeError
        avg_result_score: float = 0.0
        normalized: dict = field(default_factory=dict)
        stddev: float = 0.0
        cv: float = 0.0
        per_case_stddev: dict = field(default_factory=dict)
        per_case_cv: dict = field(default_factory=dict)

    @dataclass
    class _StubRoundScore:
        round_num: int = 0
        timestamp: str = ""
        baseline_score: _Opt[_StubCandidate] = None
        candidates: List = field(default_factory=list)
        best_candidate_id: _Opt[int] = None

    baseline_dir = eng.artifact_store.workspace / "baseline"
    sb_path = baseline_dir / "score_baseline.json"
    if not sb_path.exists():
        print("  [Solution C] ⚠️ baseline/score_baseline.json 不存在,无法构造 round_score")
        return False
    try:
        sb = json.loads(sb_path.read_text(encoding="utf-8"))
        bs_dict = sb.get("baseline_score") or {}
        if isinstance(bs_dict, dict):
            avg = bs_dict.get("avg_result_score") or bs_dict.get("result_score") or 0.0
            matrix = bs_dict.get("case_run_matrix") or {}
            composite = bs_dict.get("composite") or (avg * 100.0)
            num_runs = bs_dict.get("num_runs") or 1
            _stub_baseline = _StubCandidate(
                result_score=avg, case_run_matrix=matrix,
                composite=composite, num_runs=num_runs,
                strategy="baseline", candidate_id=-1,
            )
        else:
            print("  [Solution C] ⚠️ baseline_score 字段格式异常,跳过重生")
            return False
        stub_round_score = _StubRoundScore(
            round_num=round_num,
            timestamp=eng.config.get("created_at", ""),
            baseline_score=_stub_baseline,
            candidates=[],
            best_candidate_id=None,
        )
    except Exception as _e:
        print(f"  [Solution C] ⚠️ 构造 stub round_score 失败: {_e}")
        return False

    # 清空 baseline/_proposal/stage_*.json 强制 LLM 重新跑 Stage 1/2/3
    # (否则断点续跑会复用上轮老的 stage 产物,prev_failure_block 注入无效)
    # 注意:proposal.md 写在 baseline/proposal.md,不在 _proposal/ 下,不需要清
    stages_dir = baseline_dir / "_proposal"
    if stages_dir.exists():
        for _stage_file in [
            "stage_1_context.json",
            "stage_2_gaps.json",
            "stage_3_modifications.json",
            "stage_4_self_check.json",
        ]:
            _sf = stages_dir / _stage_file
            if _sf.exists():
                _sf.unlink()
        print("  [Solution C] 已清空 stages_dir 下历史 stage 产物(强制 LLM 重新跑)")

    # 调用 _generate_proposal_via_agent 重新生成 baseline/proposal.md
    print(f"\n{'='*60}")
    print("  🔄 Solution C: 重生 baseline/proposal.md (注入 prev_failure_block)")
    print(f"  上轮 mods: {len(_prev_mods)} 条")
    print(f"  prev_failure_block 长度: {len(prev_failure_block)} chars")
    print(f"{'='*60}\n")
    try:
        proposal = candidate_analyzer._generate_proposal_via_agent(
            baseline_dir, stub_round_score, candidate_ids=[],
            prev_failure_block=prev_failure_block,
        )
        if proposal:
            # 关键:把拼装好的 proposal 落盘到 baseline/proposal.md
            # (与 analyze_baseline 流程保持一致,见 score_analyzer._write_proposal_md 调用点)
            # 否则 stage_*.json 写好了但 proposal.md 还是上轮旧的,ApplyAgent 仍按旧 mods 走
            candidate_analyzer._write_proposal_md(
                baseline_dir, round_num, proposal, scope="baseline"
            )
            print(f"  [Solution C] ✅ proposal 已重生并落盘"
                  f": {len(proposal.get('modifications', []) or [])} 条 mods"
                  f" → {baseline_dir / 'proposal.md'}")
            return True
        else:
            print("  [Solution C] ⚠️ proposal 重生失败(LLM 阶段失败)")
            return False
    except Exception as _e:
        print(f"  [Solution C] ❌ proposal 重生异常: {_e}")
        return False
