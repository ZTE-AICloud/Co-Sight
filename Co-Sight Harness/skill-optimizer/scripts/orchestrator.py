#!/usr/bin/env python3
"""
skillx-alpha Orchestrator (重构版)
===================================
skillx-alpha-agents的主循环编排器。

重构说明：
- 状态管理 -> state_engine.StateEngine
- Hook 系统 -> hooks.HookRegistry
- 评测解耦 -> evaluators.EvaluatorFactory
- 优化器网关 -> optimizer.OptimizerGateway

职责边界：
  - Agent    = 理解任务意图 → 调用 orchestrator
  - Skill    = 纯工具（trace_analyzer / optimize_skill）
  - 本脚本  = 循环控制 + 流程编排 + 组件协调
"""

from __future__ import annotations  # 延迟类型注解求值,兼容 Python 3.9 的 PEP 604/585 语法

import argparse
import datetime
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

# 添加 scripts 目录到路径
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

# 加载 .env 文件（项目根目录或 scripts 目录下），使环境变量在脚本中生效
_env_candidate = None
_line = None
_key = None
_val = None
for _env_candidate in (Path(__file__).parent.parent / ".env", Path(__file__).parent / ".env"):
    if _env_candidate.exists():
        for _line in _env_candidate.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key, _val = _key.strip(), _val.strip()
                # SKILLX_* 关键配置：.env 强制覆盖已设置的环境变量
                # 其他变量：仅在未设置时才从 .env 读取
                if _key and _val and (_key not in os.environ or _key.startswith("SKILLX_")):
                    os.environ[_key] = _val
        break
del _env_candidate, _line, _key, _val

from orchestrators import _save_final_review_report
from orchestrators.breadth import (_evaluate_baseline,
                                   _re_evaluate_as_new_baseline,
                                   _run_breadth_round)
from orchestrators.cleanup_hook import \
    clear_user_source_bak_from_config as _clear_user_source_bak_from_config
from orchestrators.cleanup_hook import \
    register_cleanup_hook as _register_cleanup_hook
from orchestrators.cleanup_hook import \
    write_user_source_bak_to_config as _write_user_source_bak_to_config
from orchestrators.context_extractor import run_optimize_agent
from orchestrators.eval_pipeline import (_run_eval_subprocess_inner,
                                         _run_optimize_subprocess_inner,
                                         run_evaluation, run_optimization,
                                         run_single_round)
from orchestrators.proposal import \
    evaluate_baseline_agent as _evaluate_baseline_agent
from orchestrators.proposal import \
    parse_proposal_modifications_summary as \
    _parse_proposal_modifications_summary
from orchestrators.proposal import \
    regenerate_proposal_with_history as _regenerate_proposal_with_history
try:
    from orchestrators.reports import _generate_agent_report, _copy_newest_skill_for_test
except ImportError:
    # 兼容旧版 reports.py（无 _copy_newest_skill_for_test）：置 None，调用点防御跳过
    from orchestrators.reports import _generate_agent_report
    _copy_newest_skill_for_test = None
from orchestrators.skill_manager import \
    backup_skill_to_bak as _backup_skill_to_bak
from orchestrators.skill_manager import cleanup_skill_bak as _cleanup_skill_bak
from orchestrators.skill_manager import copy_skill_files as _copy_skill_files
from orchestrators.skill_manager import make_skill_args as _make_skill_args
from orchestrators.skill_manager import parse_skill_paths as _parse_skill_paths
from orchestrators.workspace import (_load_eval_env_from_dotenv,
                                     _revert_to_best_skill,
                                     enforce_evolution_workspace,
                                     populate_pipeline_in_config)
from orchestrators.workspace import setup_eval_env as _setup_eval_env
from orchestrators.workspace import setup_workspace as _setup_workspace
from state_engine import DEFAULT_TARGET_SCORE, SandboxManager, StateEngine

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _resolve_skill_path_list(args) -> list[str]:
    """从 CLI args 解析 skill 原路径列表（命令层统一 --skill-paths；args.skill_path 仅作 resume/config 恢复内部兼容）。"""
    _raw = getattr(args, "skill_paths", "") or getattr(args, "skill_path", "") or ""
    if not isinstance(_raw, str):
        _raw = str(_raw)
    _raw = _raw.strip()
    if not _raw:
        return []
    _list = _parse_skill_paths(_raw) if "," in _raw or getattr(args, "skill_paths", None) else [_raw]
    return [str(p) for p in _list]


def _init_skill_bak(args, state_engine) -> None:
    """init 阶段:备份 + 写 config + 注册异常钩子(走一次 backup_skill_to_bak)。

    若 .bak 已存在(force=False 默认跳过),不重复备份;但 config 仍写、hook 仍注册。
    """
    _sp_list = _resolve_skill_path_list(args)
    if not _sp_list:
        return
    _backup_result = _backup_skill_to_bak(_sp_list, {}, force=False)
    if _backup_result.get("backup_roots"):
        _cfg_path = Path(state_engine.config_store.config_path)
        _write_user_source_bak_to_config(_cfg_path, _backup_result["backup_roots"])
        _register_cleanup_hook(_cfg_path)


def _generate_diff_report(agent_dir: Path, round_num: int, *, best_round: int = 0, best_candidate_id: int = 0) -> str:
    """生成 result_diff_report.md,供 LLM 必读。

    目的:代替让 LLM 自己 Read 多文件,避免漏读 / 凭印象。
    通用性:不写死 case_id / 字段名 / 路径,全从产物读。

    **单轮对比模式**:本文件**只含当前轮 vs 上一轮**的 4 段数据,
    历史所有 rounds 的 diff 由 proposal-agent 通过 `{{history_diff_paths}}`
    路径清单**主动并发 Read**(避免 result_diff_report.md 单文件膨胀)。

    数据源(优先级,优先 score.json 字典 → phase3-eval 兜底):
    1. score.json 的 `info.result_score_per_case`(per-case f1)
    2. score.json 的 `info.{gold_per_case, llm_output_per_case, diff_notes_per_case}`(case 级证据字典)
    3. phase3-eval .../results/eval_data.json 的 diff_notes(字典缺失时兜底)
    4. phase3-eval .../inputs/{gold,agent}/*.md(gold + Skill 产出,字典缺失时兜底)

    写入路径(用户要求):与上一轮 score.json 同目录,即 `{round}/candidate_{X}/run_1/result_diff_report.md`
    返回:文件路径字符串
    """

    # ── 1. 定位 score.json 目录(仅依赖 round_num 当前轮,because 调用时机已保证 Evaluate 完成) ──
    # 修复 2026-07-30 v2:round_N/result_diff_report_round_N.md 必须基于该轮**实际**数据生成。
    # 调用时机已保证:round_N/candidate_K/run_1/score.json 已存在(Evaluate + analyze_run 完成后)。
    # 不再依赖 best_round / baseline 兜底 — 本轮数据为唯一真相源。
    # 搜索路径优先级:
    #   1. round_{round_num}/candidate_K/candidate_K_score.json(候选聚合,4 段字典已全在)
    #   2. round_{round_num}/candidate_K/run_1/score.json(单 run fallback)
    #   3. baseline/run_1/score.json(仅 round_num=0 baseline 时)
    score_dir = None
    phase3_dir = None
    if round_num > 0:
        round_dir_n = agent_dir / f"round_{round_num}"
        if round_dir_n.exists():
            # 优先 candidate_K_score.json(4 段字典完整),并取最高分候选作为锚点
            best_round_cand = None
            best_round_score = -1.0
            for cand_root in sorted(round_dir_n.glob("candidate_*")):
                cand_score_file = cand_root / f"{cand_root.name}_score.json"
                if cand_score_file.exists():
                    try:
                        from state_engine.persistence import load_json as _lj_sr
                        _csd = _lj_sr(str(cand_score_file))
                        _cs = _csd.get("avg_result_score") or _csd.get("composite") or 0.0
                        if _cs > best_round_score:
                            best_round_score = _cs
                            best_round_cand = cand_root
                    except Exception:
                        pass
            if best_round_cand is not None:
                score_dir = best_round_cand
                # phase3_dir 只用于路径标注(让 result_diff_report.md 标真实子目录路径),
                # 不用于读分(分数从 candidate_K_score.json 读)
                _p3 = best_round_cand / "run_1" / "data" / "phase3-eval"
                phase3_dir = _p3 if _p3.exists() else None
            else:
                # 没有 candidate_K_score.json 时,回退用 run_1/score.json
                for cand_root in sorted(round_dir_n.glob("candidate_*")):
                    run1_score = cand_root / "run_1" / "score.json"
                    if run1_score.exists():
                        score_dir = cand_root / "run_1"
                        _p3 = cand_root / "run_1" / "data" / "phase3-eval"
                        phase3_dir = _p3 if _p3.exists() else None
                        break
    if score_dir is None and round_num == 0:
        baseline_run1 = agent_dir / "baseline" / "run_1"
        if (baseline_run1 / "score.json").exists():
            score_dir = baseline_run1
            phase3_dir = baseline_run1 / "data" / "phase3-eval"
    # 调用时机已保证数据存在;若仍无 → return ""(不静默 fallback,避免污染)
    if not score_dir:
        return ""

    # 命名约定(2026-07-30 修复):
    # - baseline → baseline/result_diff_report_baseline.md(单一权威)
    # - round_N → round_N/result_diff_report_round_N.md(当前轮) + round_N/result_diff_report_baseline.md(参考副本)
    #   + round_N/result_diff_report_round_{N-1}.md(上一轮副本,如存在)
    # 目的:文件名携带 round 归属,LLM/人类一眼分辨;round_N 目录聚合所有历史 diff 供并发 Read
    if round_num == 0:
        out_path = agent_dir / "baseline" / "result_diff_report_baseline.md"
    else:
        out_path = agent_dir / f"round_{round_num}" / f"result_diff_report_round_{round_num}.md"
    cur_label = _infer_score_dir_label(score_dir, agent_dir)

    # ── 2. 收集当前轮 4 段数据(跨 run 聚合:保留每 run 证据,单 run 与原行为一致) ──
    # 2026-08-10 移植自 skillxalpha:拆成「收集」+「聚合」两步。
    #   - _collect_diff_run_infos: 收集全 run 的 info 条目(candidate 读 candidate_K_score.json
    #     runs[].info;baseline 遍历 baseline/run_*/score.json)
    #   - _aggregate_diff_run_infos: 跨 run 聚合(per-case F1 取平均,证据全保留标注 run 来源)
    # 单 run(N=1)时 flatten 结果与原 _load_round_4_segments 输出字节级一致。
    _run_infos, _rs0 = _collect_diff_run_infos(
        score_dir, phase3_dir=phase3_dir, agent_dir=agent_dir,
    )
    _agg_diff = _aggregate_diff_run_infos(_run_infos, rs_str=_rs0)
    _run_count = _agg_diff.get("run_count", 1)
    cur_per_case, cur_gold, cur_llm, cur_notes, cur_score_str, cur_paths = _flatten_agg_to_4_segments(_agg_diff)
    cur_case_ids = sorted((_agg_diff.get("cases") or {}).keys())
    if not cur_case_ids:
        # 无任何证据(调用时机已保证数据存在,此处为防御)
        return ""

    # ★ 2026-07-31 新增:读 baseline_score 用于判定"低分 case"(f1 < baseline)trace 必读标记
    # 数据源:baseline/score_baseline.json(优先)→ 顶层 result_score → 兜底用 cur_score_str 推
    baseline_score: float | None = None
    baseline_score_path = agent_dir / "baseline" / "score_baseline.json"
    if baseline_score_path.exists():
        try:
            import json as _json_bs
            _bs_data = _json_bs.loads(baseline_score_path.read_text())
            baseline_score = _bs_data.get("baseline_score") or _bs_data.get("result_score")
        except Exception:
            pass
    if baseline_score is None:
        # 兜底:从当前轮 score.json 顶层 result_score 推不出 baseline,跳过 ⚠️ 判定
        pass

    # ── 2.5) 读 evidence_paths.scoring_rule(从 user-config.yaml 注入到 diff 报告开头) ──
    # 目的:LLM/人类 Read diff 报告时,第一眼就看到分怎么算 → 改 SKILL.md 时知道改什么能提分
    scoring_rule_text = ""
    try:
        from orchestrators.workspace import _load_user_config as _load_ucfg_diff
        _ucfg_diff = _load_ucfg_diff() or {}
        scoring_rule_text = ((_ucfg_diff.get("evidence_paths", {}) or {}).get("scoring_rule", "") or "").strip()
    except Exception:
        scoring_rule_text = ""

    # ── 3. 渲染单轮 result_diff_report.md(只含当前轮 4 段 + 资源消耗,不展开历史内容) ──
    lines: list[str] = [
        f"# Diff Report({cur_label} → Round {round_num})",
        "",
        "> 本报告由 framework 直接从 `score.json` 的 4 段字典生成,**无需 LLM**。",
        "> **单轮对比模式**:本文件只含**当前轮 vs 上一轮**的 4 段数据。",
        "> 历史所有 rounds 的 diff 由 proposal-agent 通过 `{{history_diff_paths}}` 路径清单**主动并发 Read**",
        "> (本报告底部列出该清单)。每个 case 5 段:**F1 分数** / gold 答案 / Skill 实际产出 / diff_notes 失分描述 / 资源消耗(duration_ms + input_tokens + output_tokens)。",
        "",
    ]
    # 评分规则段(从 yaml evidence_paths.scoring_rule 读)— 写进 diff 报告文件
    if scoring_rule_text:
        lines.extend([
            "## 🎯 评分规则(business metric 怎么算 — 改 SKILL.md 时优先看这)",
            "",
            "**重要**:本任务分数 = 5 维评分法(见下)。改 SKILL.md 时,先想「改哪一维能提分」→ 直接对应下面的失分维度优化。",
            "",
            "```",
            scoring_rule_text,
            "```",
            "",
            "---",
            "",
        ])
    lines.extend([
        f"## 📌 当前轮:{cur_label}(F1 均分={cur_score_str})",
        "",
    ])
    # 读资源消耗(per-case dict,缺失则空 dict,渲染层会跳过)
    cur_resources = _load_round_resources(score_dir)
    # ★ 2026-07-31 新增:trace 路径注入 — 从 score.json.info.trace_paths_per_case 读取(ExtractionAgent 按 YAML 配置填入)
    cur_trace_paths = _load_trace_paths_per_case(score_dir)
    # 中间产物路径(渲染层 #### 4 贴内容,score-analyzer 读报告归因)
    cur_middle_products = _load_middle_products_per_case(score_dir)
    for case_id in cur_case_ids:
        # 2026-08-10 移植自 skillxalpha:多 run 走 run_evidence 标注渲染(F1 跨 run 平均 + 证据标注来源);
        # 单 run(N=1)走原渲染路径(字节级不变)。
        case_data = _agg_diff["cases"][case_id]
        if _run_count > 1:
            lines.extend(_render_case_4_segments(
                case_id, None, "", "", "", resources=None, case_dir="",
                trace_paths="", baseline_score=baseline_score, run_evidence=case_data,
            ))
            lines.append("---")
            lines.append("")
            continue
        f1 = cur_per_case.get(case_id)
        # ★ 2026-07-31 改造:gold/llm 字典 value 改为绝对路径,渲染层按路径 Read 真文件
        gold_path = cur_gold.get(case_id, "")
        llm_path = cur_llm.get(case_id, "")
        notes_text = cur_notes.get(case_id, "")
        res = cur_resources.get(case_id, {})
        # ★ 2026-07-30 修复:传真实子目录路径(精确可定位,无通配符)
        case_dir = cur_paths.get(case_id, "")
        # trace_paths 是 list(trace.log + subagents/*.jsonl),渲染层第 5 段逐个标注
        trace_paths = cur_trace_paths.get(case_id, [])
        middle_products = cur_middle_products.get(case_id, [])
        lines.extend(_render_case_4_segments(case_id, f1, gold_path, llm_path, notes_text, resources=res, case_dir=case_dir, trace_paths=trace_paths, baseline_score=baseline_score, middle_products=middle_products))
        lines.append("---")
        lines.append("")

    # ── 4. 历史 diff 路径清单(由 proposal-agent 主动并发 Read,不在本报告展开) ──
    # 修复 v2026-07-24:历史清单应该是 round_num 之前的所有 rounds(round_0..round_num-1)
    # 不包括 round_num 自身(它是当前正在生成的 result_diff_report.md)
    # 用一个虚拟 current_score_dir 指向 round_num/candidate_1/run_1 让 _build_history_diff_paths 用 round_num 过滤
    if round_num > 0:
        _virtual_current = agent_dir / f"round_{round_num}" / "candidate_1" / "run_1"
    else:
        _virtual_current = agent_dir / "baseline" / "run_1"
    history_paths = _build_history_diff_paths(agent_dir, current_score_dir=_virtual_current)
    if history_paths:
        lines.append("## 📜 历史 result_diff_report.md 路径清单(LLM 主动并发 Read)")
        lines.append("")
        lines.append(
            "> **不要在本报告展开历史内容**,而是按以下路径**并发 Read**(Step 1 探查时),"
            "吸收每轮失败模式、修复策略、效果,生成下一轮 mod 时复用有效 mod、避开失败 mod。"
        )
        lines.append("")
        for entry in history_paths:
            lines.append(
                f"- `{entry['path']}`(round_{entry['round_num']} candidate_{entry['candidate_id']}, F1={entry['f1_str']})"
            )
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # ── 4.5) 证据路径自查:渲染后校验 gold/llm/trace 存在性(gold/llm 已 glob 兜底)──
    _verify_evidence_paths(cur_gold, cur_llm, cur_trace_paths)

    # ── 5) 失分分析(score-analyzer 子 Agent) ──
    # 2026-08-05 重新启用:score-analyzer 挨个读 trace + 中间产物,做误差根因 + 责任归因到具体 skill,
    # 独立落盘 score_analyzer_report;proposal 只读该独立文件归因结论,减轻自身分析负担。
    # 传入 best_round + baseline_score,让独立报告开头标注"本轮/修改基线/分数"元信息(不跨文件)。
    _history_diff = _build_history_diff_paths(agent_dir, current_score_dir=score_dir,
                                              best_round=best_round)
    _enrich_diff_report_with_score_analyzer(out_path, score_dir, history_diff_paths=_history_diff,
                                            best_round=best_round, baseline_score=baseline_score)

    # ── 4b. 跨轮拷贝逻辑已迁移到 _populate_round_history(在 _ensure_round_dir 末尾调用) ──
    # 修复 2026-07-31:原 line 269-288 的跨轮拷贝只在 Evaluate 后才执行,
    # 导致 proposal-agent 启动时 round_N/ 目录还没历史 diff。
    # 现在 _populate_round_history 在 round_N 目录创建时立即建立历史副本。

    return str(out_path)


# ─── _generate_diff_report 的辅助函数 ─────────────────────────────

import re as _re_diff


def _infer_score_dir_label(score_dir: Path, agent_dir: Path) -> str:
    """返回 'baseline' / 'round_N candidate_K' 这种易读 label。"""
    try:
        rel = score_dir.resolve().relative_to(agent_dir.resolve())
    except ValueError:
        return score_dir.name
    return str(rel).replace("/", " / ")


def _build_history_diff_paths(agent_dir: Path, current_score_dir: Path,
                              best_round: int = 0) -> list[dict]:
    """扫描 agent_dir 下所有历史 rounds 的 result_diff_report.md + skill_diff_round.md 路径。

    返回:list[dict],每项含 path(结果) / skill_diff_path(改动,配对) / round_num / candidate_id /
    f1_str / is_baseline(是否为当前修改基线轮)。
    两个 agent 都通过历史清单**主动并发 Read**:
      - proposal-agent: 吸收历史 mod 经验(改动+结果配对才能判断"哪条 mod 救了/害了哪个 case")
      - score-analyzer: 判断该 case 失分是"上轮改坏(回归)"还是"新问题"(跨 round 因果)
    baseline 无改动,skill_diff_path 为空串。
    best_round: 当前修改基线轮(baseline_anchored=False 时 = eng.best_round),标注 is_baseline 让
    注入清单里基线轮优先。0 表示起点是 baseline(best_round 0 无,由调用方判断)。
    """
    history: list[dict] = []
    agent_dir = agent_dir.resolve()
    current_score_dir = current_score_dir.resolve()

    # 推导当前轮次(从 current_score_dir 路径推断)
    # 路径形式: agent_dir/round_N/candidate_K/run_1
    current_round_num = 0
    for p in current_score_dir.resolve().parts:
        m = _re_diff.match(r"^round_(\d+)$", p)
        if m:
            current_round_num = int(m.group(1))
            break

    # baseline diff(round_num=0)
    if current_round_num > 0:  # 跳过当前轮之前的 baseline,只看历史的
        baseline_diff = agent_dir / "baseline" / "result_diff_report_baseline.md"
        if baseline_diff.exists():
            try:
                import json as _json_mod
                sp = baseline_diff.parent / "score.json"
                sd = _json_mod.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
                rs = sd.get("result_score")
                f1_str = f"{rs:.2f}" if isinstance(rs, (int, float)) else "?"
            except Exception:
                f1_str = "?"
            history.append({
                "path": str(baseline_diff),
                "skill_diff_path": "",  # baseline 无改动
                "round_num": 0,
                "candidate_id": 0,
                "f1_str": f1_str,
                "is_baseline": best_round == 0,  # baseline 无被采纳轮时是基线
                "skill_root": str(agent_dir / "skill"),  # workspace skill = baseline 全量起点
            })

    # round_N 每个 round 选最高分候选的 result_diff_report.md(只看 round_num < current_round_num)
    for rd in sorted(agent_dir.glob("round_*")):
        if not rd.is_dir():
            continue
        m = _re_diff.match(r"^round_(\d+)$", rd.name)
        if not m:
            continue
        rn = int(m.group(1))
        if rn >= current_round_num:  # 跳过当前轮和未来轮
            continue
        best_run_dir: Path | None = None
        best_cand_id = 0
        best_score = -1.0
        for cd in sorted(rd.glob("candidate_*")):
            if not cd.is_dir():
                continue
            cand_m = _re_diff.match(r"^candidate_(\d+)$", cd.name)
            if not cand_m:
                continue
            cand_id = int(cand_m.group(1))
            for run_d in sorted(cd.glob("run_*")):
                sp = run_d / "score.json"
                if not sp.exists():
                    continue
                try:
                    import json as _json_mod
                    sd = _json_mod.loads(sp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                rs = sd.get("result_score")
                if isinstance(rs, (int, float)) and rs > best_score:
                    best_score = rs
                    best_run_dir = run_d
                    best_cand_id = cand_id
        if best_run_dir is None:
            continue
        # 修复 v2026-07-30:_generate_diff_report 写到 round_N/result_diff_report_round_N.md(2026-07-30 命名约定)
        diff_path = rd / f"result_diff_report_round_{rn}.md"
        if not diff_path.exists():
            # 兼容 fallback:旧命名 result_diff_report.md
            legacy = rd / "result_diff_report.md"
            if legacy.exists():
                diff_path = legacy
            else:
                continue
        f1_str = f"{best_score:.2f}" if isinstance(best_score, (int, float)) and best_score >= 0 else "?"
        # 改动(配对):round_N/skill_diff_round_N.md(proposal 判断 mod 效果、score-analyzer 判断回归,必需)
        skill_diff_path = rd / f"skill_diff_round_{rn}.md"
        history.append({
            "path": str(diff_path),
            "skill_diff_path": str(skill_diff_path) if skill_diff_path.exists() else "",
            "round_num": rn,
            "candidate_id": best_cand_id,
            "f1_str": f1_str,
            "is_baseline": best_round > 0 and rn == best_round,
            # 该轮最高分候选的 skill 全量快照(定位根因章节 / 理解 skill 全貌用)
            "skill_root": str(agent_dir / f"round_{rn}" / f"candidate_{best_cand_id}" / "skill"),
        })

    history.sort(key=lambda x: x["round_num"])
    return history


# gold/llm 文件名 glob 缓存(仅从 user-config evidence_paths 读)
_EVIDENCE_GLOB_CACHE: dict | None = None


def _load_evidence_globs() -> dict:
    """读业务方声明的 gold/llm 文件名 glob(带缓存)。

    framework 不感知具体文件名,glob 模式**只能**来自 user-config `evidence_paths`
    (config/evolve-user-config.yaml,与 _load_user_config 同一来源)。
    未配置时返回空列表 → `_resolve_evidence_path` 不做兜底修正(渲染层标"文件不存在")。
    注:不复用 _load_user_config —— 它只注入 env、返回已加载键名,不含 evidence_paths。
    """
    global _EVIDENCE_GLOB_CACHE
    if _EVIDENCE_GLOB_CACHE is not None:
        return _EVIDENCE_GLOB_CACHE
    globs = {"gold": [], "llm": []}
    try:
        import yaml
        scripts_dir = Path(__file__).parent
        for name in ("evolve-user-config.yaml", "user-config.yaml"):
            cfg_file = scripts_dir.parent / "config" / name
            if not cfg_file.exists():
                continue
            cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
            ep = cfg.get("evidence_paths") or {}
            if isinstance(ep, dict):
                globs["gold"] = ep.get("gold_filename_glob") or []
                globs["llm"] = ep.get("llm_output_filename_glob") or []
            break
    except Exception:
        pass
    _EVIDENCE_GLOB_CACHE = globs
    return globs


def _resolve_evidence_path(path: str, globs: list) -> str:
    """gold/llm 路径指向的文件不存在时,用配置 glob 探查同目录实际文件修正。

    返回修正后的路径;找不到匹配或参数为空则返回原路径(渲染层会标注"文件不存在")。
    """
    if not path:
        return path
    p = Path(path)
    if p.exists():
        return path
    parent = p.parent
    if not parent.is_dir():
        return path
    for g in globs:
        try:
            matches = sorted(parent.glob(g))
        except Exception:
            continue
        if matches:
            print(f"  ♻️  修正证据路径(LLM 填错文件名): {Path(path).name} → {matches[0].name}")
            return str(matches[0])
    return path


def _fix_evidence_paths(gold_per_case: dict, llm_per_case: dict) -> None:
    """对 gold/llm 路径字典就地做存在性校验 + glob 兜底修正。

    实测(taskid_20260801_183839):LLM 填约定名 R_用户需求分析.md,但评测实际产出
    全量_用户需求分析.md,路径失效 → 报告标注"文件不存在"。用 user-config 声明的
    glob 兜底找真实文件,让报告指向实际产物而非空标缺失。
    """
    globs = _load_evidence_globs()
    for cid, p in list(gold_per_case.items()):
        gold_per_case[cid] = _resolve_evidence_path(p, globs["gold"])
    for cid, p in list(llm_per_case.items()):
        llm_per_case[cid] = _resolve_evidence_path(p, globs["llm"])


def _verify_evidence_paths(gold_per_case: dict, llm_per_case: dict,
                           trace_per_case: dict) -> list:
    """渲染前的证据路径自查:校验 gold/llm/trace 存在性,返回缺失清单。

    显式步骤,让"证据路径是否有效"可观测:
    - gold/llm 已由 `_fix_evidence_paths` 做 glob 兜底修正,此处是修正后的最终校验;
    - trace:value 是 list of 路径(trace.log + subagents/*.jsonl),
      逐个校验存在性;旧数据 value 为字符串时按单元素处理。缺失由渲染层标注。
    缺失路径打日志,便于定位 LLM 填错 / 评测产物漂移。
    """
    missing = []
    for label, d in (("gold", gold_per_case), ("llm", llm_per_case),
                     ("trace", trace_per_case)):
        for cid, v in (d or {}).items():
            paths = v if isinstance(v, list) else [v]
            for p in paths:
                if p and not Path(p).exists():
                    missing.append(f"{label}:{cid}→{Path(p).name}")
    if missing:
        print(f"  ⚠️ [路径自查] {len(missing)} 个证据路径仍不存在: "
              f"{', '.join(missing[:5])}{'…' if len(missing) > 5 else ''}")
    return missing


def _first_nonempty_dict(info: dict, keys: tuple) -> dict:
    """从 info 里按 keys 顺序取首个非空 dict（兼容字段别名，取首个非空）。"""
    for k in keys:
        v = info.get(k)
        if isinstance(v, dict) and v:
            return v
    return {}


def _as_f1_value(v) -> float | None:
    """把 per-case 分数值归一为 float；list 取 mean（对齐 build_case_run_matrix）。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list) and v:
        nums = [x for x in v if isinstance(x, (int, float))]
        if nums:
            return sum(nums) / len(nums)
    return None


def _aggregate_diff_run_infos(
    run_infos: list[dict],
    *,
    rs_str: str = "?",
) -> dict:
    """跨 run 聚合 4 段 diff 数据（纯函数，无文件 IO）。

    info 内字段 key 来自 score.json info 字典（框架既有约定，非业务硬编码）：
      result_score_per_case / gold_per_case / llm_output_per_case /
      diff_notes_per_case / trace_paths_per_case /
      duration_ms_per_case / input_tokens_per_case / output_tokens_per_case
    result_score_per_case 兼容别名 per_case_scores / case_scores / f1_per_case
    （解析逻辑对齐 score_analyzer._extract_per_case_from_run，取首个非空 dict）。

    聚合策略（用户确认）：
      - per-case F1 跨 run 取平均（avg_f1），各 run 值全保留（per_run_f1）
      - gold / llm / notes / trace 全保留，按 run_index 标注来源
      - 单 run（N=1）时 run_count=1，各 {run: value} 只含 {1: value}，渲染走单 run 路径
    """
    cases: dict = {}
    run_indexes: list = []
    run_scores: list = []

    for entry in run_infos or []:
        info = entry.get("info") or {}
        if not isinstance(info, dict) or not info:
            continue  # 空 info 的 run 跳过（不计入 run_count）
        run_idx = entry.get("run_index")
        rs = entry.get("result_score")
        if isinstance(rs, (int, float)):
            run_scores.append(float(rs))
        run_indexes.append(run_idx)

        per_case = _first_nonempty_dict(info, (
            "result_score_per_case", "per_case_scores", "case_scores", "f1_per_case",
        ))
        gold = _first_nonempty_dict(info, ("gold_per_case",))
        llm = _first_nonempty_dict(info, ("llm_output_per_case",))
        notes = _first_nonempty_dict(info, ("diff_notes_per_case",))
        trace = _first_nonempty_dict(info, ("trace_paths_per_case",))
        dur = _first_nonempty_dict(info, ("duration_ms_per_case",))
        inp = _first_nonempty_dict(info, ("input_tokens_per_case",))
        out = _first_nonempty_dict(info, ("output_tokens_per_case",))

        all_case_ids = set(per_case) | set(gold) | set(llm) | set(notes) | set(trace)
        for cid in all_case_ids:
            cd = cases.setdefault(cid, {
                "avg_f1": None, "per_run_f1": {},
                "gold": {}, "llm": {}, "notes": {}, "trace": {}, "resources": {},
            })
            if cid in per_case:
                f1 = _as_f1_value(per_case[cid])
                if f1 is not None:
                    cd["per_run_f1"][run_idx] = f1
            if cid in gold:
                cd["gold"][run_idx] = gold[cid]
            if cid in llm:
                cd["llm"][run_idx] = llm[cid]
            if cid in notes:
                cd["notes"][run_idx] = notes[cid]
            if cid in trace:
                cd["trace"][run_idx] = trace[cid]
            res = {}
            if isinstance(dur.get(cid), (int, float)):
                res["duration_ms"] = dur[cid]
            if isinstance(inp.get(cid), (int, float)):
                res["input_tokens"] = inp[cid]
            if isinstance(out.get(cid), (int, float)):
                res["output_tokens"] = out[cid]
            if res:
                cd["resources"][run_idx] = res

    for cd in cases.values():
        if cd["per_run_f1"]:
            vals = list(cd["per_run_f1"].values())
            cd["avg_f1"] = sum(vals) / len(vals)

    if rs_str == "?" and run_scores:
        rs_str = f"{sum(run_scores) / len(run_scores):.2f}"

    return {
        "rs_str": rs_str,
        "run_count": len(run_indexes),
        "run_indexes": run_indexes,
        "cases": cases,
    }


def _phase3_fallback_info(phase3_dir: Path) -> dict:
    """phase3-eval 兜底探查（4 段证据字典全缺时用）。

    返回 {case_id: {"gold": abs_path, "llm": abs_path, "notes": str, "path": case_dir}}。
    复现原 _load_round_4_segments 的兜底口径：
      - gold:  inputs/gold/{gold_filename_glob} 第一个匹配
      - llm:   phase2-exec/{case_id}*/output/middle_content/**/[0-9]+-*.md（章节文件优先）
      - notes: results/eval_data.json 的 evaluation_items[0].diff_notes
    """
    import json as _json_fb

    phase2_base = phase3_dir.parent / "phase2-exec"
    out: dict = {}
    for cd in sorted(phase3_dir.iterdir()):
        if not cd.is_dir():
            continue
        case_id = cd.name.split("_")[0]
        if not case_id.startswith("RAN-"):
            continue
        entry: dict = {"gold": "", "llm": "", "notes": "", "path": str(cd)}
        gold_candidates = sorted((cd / "inputs" / "gold").glob("R_*.md"))
        if gold_candidates:
            entry["gold"] = str(gold_candidates[0].resolve())
        for p2 in sorted(phase2_base.glob(f"{case_id}*")):
            mc_dir = p2 / "output" / "middle_content"
            if mc_dir.exists():
                md_files = sorted(mc_dir.rglob("*.md"))
                chapter_files = [m for m in md_files if m.name[:2].isdigit()]
                if chapter_files:
                    entry["llm"] = str(chapter_files[0].resolve())
                    break
                if md_files:
                    entry["llm"] = str(md_files[0].resolve())
                    break
        eval_path = cd / "results" / "eval_data.json"
        if not eval_path.exists():
            for alt in cd.glob("results/*.json"):
                eval_path = alt
                break
        if eval_path.exists():
            try:
                d = _json_fb.loads(eval_path.read_text(encoding="utf-8"))
                items = d.get("evaluation_items", [])
                if items:
                    entry["notes"] = items[0].get("diff_notes", "?")
            except Exception:
                pass
        if any(entry.get(k) for k in ("gold", "llm", "notes")):
            out[case_id] = entry
    return out


def _collect_diff_run_infos(
    score_dir: Path,
    *,
    phase3_dir: Path | None = None,
    agent_dir: Path | None = None,
) -> tuple[list, str]:
    """收集当前 round 全 run 的 info 条目 + 权威分数串。

    返回 (run_infos, rs_str)。数据源优先级：
      1. candidate 聚合文件（round_N/candidate_K/candidate_K_score.json 的 runs[].info）
      2. 遍历 run_*/score.json（baseline 全 run 聚合；candidate 聚合文件缺失时 fallback）
      3. phase3-eval 兜底（所有 run 的 4 段证据全缺时，补一次归到第一个 run）
    收集时对每 run 的 gold/llm 字典就地 _fix_evidence_paths（配置 glob 兜底）。
    """
    import json as _json_collect

    run_infos: list = []
    rs_str = "?"

    # 1. candidate 聚合文件
    cand_agg = None
    if score_dir.name.startswith("run_"):
        cand_agg = score_dir.parent / f"{score_dir.parent.name}_score.json"
    else:
        cand_agg = score_dir / f"{score_dir.name}_score.json"
    if cand_agg and cand_agg.exists():
        try:
            sd = _json_collect.loads(cand_agg.read_text(encoding="utf-8"))
        except Exception:
            sd = None
        if sd and isinstance(sd.get("runs"), list) and sd["runs"]:
            rs = sd.get("avg_result_score") or sd.get("aggregate_score") or sd.get("composite")
            if isinstance(rs, (int, float)):
                rs_str = f"{float(rs):.2f}"
            for r in sd["runs"]:
                info = r.get("info") or {}
                run_infos.append({
                    "run_index": r.get("run_index"),
                    "info": info if isinstance(info, dict) else {},
                    "result_score": r.get("result_score"),
                })
                if isinstance(info, dict):
                    _fix_evidence_paths(
                        info.get("gold_per_case") or {},
                        info.get("llm_output_per_case") or {},
                    )
            if run_infos:
                return run_infos, rs_str
            run_infos = []  # 聚合文件 runs 为空 → 继续 fallback

    # 2. 遍历 run_*/score.json（baseline 全 run / candidate fallback）
    if score_dir.name == "baseline" and agent_dir is not None:
        run_root = agent_dir / "baseline"
    elif score_dir.name.startswith("run_"):
        run_root = score_dir.parent
    else:
        run_root = score_dir
    rs_vals: list = []
    if run_root.exists():
        for rd in sorted(run_root.glob("run_*")):
            sp = rd / "score.json"
            if not sp.exists():
                continue  # run 目录存在但 score.json 缺失 → 跳过
            try:
                sd = _json_collect.loads(sp.read_text(encoding="utf-8"))
            except Exception:
                continue
            info = sd.get("info") or {}
            if not isinstance(info, dict):
                info = {}
            run_infos.append({
                "run_index": int(rd.name.split("_")[1]),
                "info": info,
                "result_score": sd.get("result_score"),
            })
            _fix_evidence_paths(
                info.get("gold_per_case") or {},
                info.get("llm_output_per_case") or {},
            )
            rsv = sd.get("result_score")
            if isinstance(rsv, (int, float)):
                rs_vals.append(float(rsv))
    if run_infos:
        if rs_str == "?" and rs_vals:
            rs_str = f"{sum(rs_vals) / len(rs_vals):.2f}"
        return run_infos, rs_str

    # 3. phase3-eval 兜底（所有 run 的 4 段证据全缺时，补一次归到第一个 run）
    if phase3_dir and phase3_dir.exists():
        fb = _phase3_fallback_info(phase3_dir)
        if fb:
            info: dict = {"gold_per_case": {}, "llm_output_per_case": {}, "diff_notes_per_case": {}}
            for cid, e in fb.items():
                if e.get("gold"):
                    info["gold_per_case"][cid] = e["gold"]
                if e.get("llm"):
                    info["llm_output_per_case"][cid] = e["llm"]
                if e.get("notes"):
                    info["diff_notes_per_case"][cid] = e["notes"]
            run_infos.append({"run_index": 1, "info": info, "result_score": None})
            return run_infos, rs_str

    return [], rs_str


def _flatten_agg_to_4_segments(agg: dict) -> tuple[dict, dict, dict, dict, str, dict]:
    """把 _aggregate_diff_run_infos 结果拍平回 _load_round_4_segments 的 6-tuple 契约。

    返回 (per_case_f1={cid: avg_f1}, gold={cid: 首run路径}, llm, notes, rs_str, path_per_case={})。
    path_per_case 返回 {}（case_dir 在渲染层本就未使用，保持兼容）。
    """
    per_case_f1: dict = {}
    gold_per_case: dict = {}
    llm_per_case: dict = {}
    notes_per_case: dict = {}
    for cid, cd in (agg.get("cases") or {}).items():
        if cd.get("avg_f1") is not None:
            per_case_f1[cid] = cd["avg_f1"]
        if cd.get("gold"):
            gold_per_case[cid] = next(iter(cd["gold"].values()))
        if cd.get("llm"):
            llm_per_case[cid] = next(iter(cd["llm"].values()))
        if cd.get("notes"):
            notes_per_case[cid] = next(iter(cd["notes"].values()))
    return per_case_f1, gold_per_case, llm_per_case, notes_per_case, agg.get("rs_str", "?"), {}



def _append_run_path_evidence(lines: list, d: dict, run_indexes: list) -> None:
    """把 {run_index: path 或 path-list} 逐 run 标注列出；无条目时标 (空)。

    value 兼容:str(旧 trace 路径)原样;list(trace.log + subagents/*.jsonl)展开为多条。
    """
    if not d:
        lines.append("- (空)")
        return
    shown = False
    for ri in run_indexes:
        if ri in d and d[ri]:
            _append_fmt_trace_value(lines, ri, d[ri])
            shown = True
    for ri in sorted(set(d) - set(run_indexes)):
        if d[ri]:
            _append_fmt_trace_value(lines, ri, d[ri])
            shown = True
    if not shown:
        lines.append("- (空)")


def _append_fmt_trace_value(lines: list, ri, v) -> None:
    """把单个 run 的 trace 值(路径或路径 list)渲染为 markdown 行。"""
    if isinstance(v, list):
        for _p in v:
            if isinstance(_p, str) and _p:
                lines.append(f"  - **run_{ri}**: `{_p}`")
    elif isinstance(v, str) and v:
        lines.append(f"  - **run_{ri}**: `{v}`")


def _append_file_content_per_run(lines: list, d: dict, run_indexes: list,
                                 read_fn, label: str) -> None:
    """每个 run 单独展示文件全文(标注 run 来源 + 内容标签);内容相同的 run 折叠为「与 run_X 一致」。

    与 diff_notes 全保留口径一致:多 run 的 gold/llm 证据逐 run 可读,
    避免只贴第一份导致后续 run 的证据差异不可见(验收反馈 2026-08-03)。
    label: 内容标签(如 'gold 答案' / 'Skill 实际产出'),让标签有针对性而非笼统「全文」。
    """
    seen: dict = {}  # content -> 首个 run_index(内容相同则折叠)
    wrote_any = False
    for ri in run_indexes:
        path = d.get(ri, "")
        if not path:
            continue
        text = read_fn(path)
        if text and text in seen:
            lines.append(f"（内容与 run_{seen[text]} 一致 → 见上）")
            continue
        if text:
            seen[text] = ri
        if wrote_any:
            lines.append("")
        lines.append(f"- **run_{ri} {label}**:")
        lines.append("```markdown")
        lines.append(text if text else "(空)")
        lines.append("```")
        wrote_any = True
    if not wrote_any:
        lines.append("```markdown")
        lines.append("(空)")
        lines.append("```")


def _append_resources_multi(lines: list, resources: dict, run_indexes: list) -> None:
    """资源多列表格：每 run 一列 + 平均列（对齐单 run 资源口径 duration/input/output）。"""
    runs_with_res = [ri for ri in run_indexes if ri in resources]
    if not runs_with_res:
        lines.append("(空)")
        lines.append("")
        return
    rows = [("耗时", "duration_ms", "ms"), ("输入 Token", "input_tokens", ""),
            ("输出 Token", "output_tokens", "")]
    lines.append("| 指标 | " + " | ".join(f"run_{ri}" for ri in runs_with_res) + " | 平均 |")
    lines.append("| :--- | " + " | ".join("---:" for _ in runs_with_res) + " | ---: |")
    for label, key, unit in rows:
        cells = []
        vals = []
        for ri in runs_with_res:
            v = (resources.get(ri) or {}).get(key)
            if isinstance(v, (int, float)):
                cells.append(f"{int(v)} {unit}".strip())
                vals.append(float(v))
            else:
                cells.append("(缺)")
        avg = (sum(vals) / len(vals)) if vals else None
        avg_str = f"{avg:.0f}" if avg is not None else "(缺)"
        lines.append("| " + label + " | " + " | ".join(cells) + f" | {avg_str} |")
    lines.append("")


def _render_case_4_segments_multi(case_id: str, ev: dict, baseline_score: float | None = None) -> list[str]:
    """渲染单个 case 的多 run 证据（F1 跨 run 平均徽章 + per-run F1 表 + 全 run 证据标注来源）。

    与单 run 渲染对齐的 5 段结构（#### 1..5）：
      - F1 徽章显示「跨 run 平均」+ min/max/run 数；按 avg_f1 判定徽章（>=90 🎯 / <60 ⚠️ / 其他 📊）
      - 每 case 加 per-run F1 表格
      - gold/llm/notes/trace 段每 run 一条标注 **run_{i}**；gold/llm 内容只贴第一份全文
        （其余 run 差异通过源文件路径 Read 定位），避免报告膨胀
      - 资源消耗用多列表格（每 run 一列 + 平均列）
    """
    from pathlib import Path as _Path

    def _read_text_safe(path_str: str) -> str:
        """按绝对路径 Read 真文件;非绝对路径或文件不存在 → 留空 + 警告。"""
        if not path_str:
            return ""
        p = _Path(path_str)
        if not p.is_absolute():
            return f"⚠️ 路径非法(非绝对路径):{path_str}"
        if not p.exists():
            return f"⚠️ 文件不存在:{path_str}"
        try:
            return p.read_text(encoding="utf-8")
        except Exception as e:
            return f"⚠️ 读取失败:{path_str} ({e})"

    per_run_f1 = ev.get("per_run_f1") or {}
    avg_f1 = ev.get("avg_f1")
    # run_indexes 自推导(不依赖顶层 run_count/run_indexes 字段,case 级数据可直接传入)
    run_indexes = sorted(ev.get("run_indexes") or []) or sorted(
        set(per_run_f1) | set(ev.get("gold") or {}) | set(ev.get("llm") or {})
        | set(ev.get("notes") or {}) | set(ev.get("trace") or {}))
    gold = ev.get("gold") or {}
    llm = ev.get("llm") or {}
    notes = ev.get("notes") or {}
    trace = ev.get("trace") or {}
    resources = ev.get("resources") or {}

    lines: list[str] = [f"### {case_id}", ""]
    if avg_f1 is not None:
        f1_vals = [v for v in per_run_f1.values() if isinstance(v, (int, float))]
        f1_mark = "🎯" if avg_f1 >= 90 else ("⚠️" if avg_f1 < 60 else "📊")
        min_s = f"{min(f1_vals):.2f}" if f1_vals else "?"
        max_s = f"{max(f1_vals):.2f}" if f1_vals else "?"
        run_n = len(run_indexes) or len(f1_vals)
        lines.append(f"**{f1_mark} F1 分数(跨 run 平均):{avg_f1:.2f}**（min {min_s} / max {max_s}, {run_n} runs）")
        lines.append("")
        if run_indexes:
            lines.append("| run | F1 |")
            lines.append("| :-- | --: |")
            for ri in run_indexes:
                v = per_run_f1.get(ri)
                lines.append(f"| run_{ri} | {v:.2f} |" if isinstance(v, (int, float)) else f"| run_{ri} | (缺) |")
            lines.append(f"| **平均** | **{avg_f1:.2f}** |")
            lines.append("")
    else:
        lines.append("**F1 分数:?**")
        lines.append("")

    # 1. gold 答案（跨 run 全保留,每个 run 单独展示全文;内容相同的 run 折叠标注）
    lines.append("#### 1. gold 答案(跨 run 全保留,标注来源)")
    _append_run_path_evidence(lines, gold, run_indexes)
    _append_file_content_per_run(lines, gold, run_indexes, _read_text_safe, "gold 答案")
    lines.append("")

    # 2. Skill 实际产出（同上,每个 run 单独展示全文）
    lines.append("#### 2. Skill 实际产出(LLM 输出)(跨 run 全保留,标注来源)")
    _append_run_path_evidence(lines, llm, run_indexes)
    _append_file_content_per_run(lines, llm, run_indexes, _read_text_safe, "Skill 实际产出")
    lines.append("")

    # 3. LLM-as-Judge diff_notes（每 run 失分描述全保留）
    lines.append("#### 3. LLM-as-Judge diff_notes(跨 run 全保留,标注来源)")
    if notes:
        shown = False
        for ri in run_indexes:
            if ri in notes and notes[ri]:
                lines.append(f"- **run_{ri}**: {notes[ri]}")
                shown = True
        for ri in sorted(set(notes) - set(run_indexes)):
            if notes[ri]:
                lines.append(f"- **run_{ri}**: {notes[ri]}")
                shown = True
        if not shown:
            lines.append("```")
            lines.append("(空)")
            lines.append("```")
    else:
        lines.append("```")
        lines.append("(空)")
        lines.append("```")
    lines.append("")

    # 4. 资源消耗（多列）
    lines.append("#### 4. 资源消耗(跨 run)")
    _append_resources_multi(lines, resources, run_indexes)

    # 5. Trace 路径（每 run 全保留;低分 case 加 ⚠️ 必读标记）
    lines.append("#### 5. Trace 路径(跨 run 全保留)")
    if trace:
        is_low_score = (isinstance(baseline_score, (int, float))
                        and isinstance(avg_f1, (int, float))
                        and avg_f1 < baseline_score)
        trace_warn = " ⚠️ **必读**(低分 case,proposal-agent 诊断根因前必须 Read)" if is_low_score else ""
        _append_run_path_evidence(lines, trace, run_indexes)
        if trace_warn:
            lines[-1] = lines[-1] + trace_warn
        lines.append("")
        lines.append("📖 **Read 方法(🛑 强制必读)**:按各 run 标注顺序 `Read` 文件本体 —— 先 `trace.log`(整体轨迹,简化,先建全貌),再**逐个 Read 全部 `subagents/agent-*.jsonl`**(各 skill 完整执行轨迹,含 skill 片段)。**禁止**只停留在本段路径,必须 `Read` 真实文件后才能诊断/写 mod。")
        lines.append("")
        lines.append("🎯 **诊断价值(🛑 必读)**:从 trace 可识别「verify 失败未自愈」「LLM 自由发挥路径」「多余 Bash 步骤」「skill 环节失守/未执行」等非 SKILL.md 字段约束覆盖不到的根因。**低分 case 不 Read 完 trace 不得写 mod**,risk_evidence 必须引用 trace 具体证据。")
        lines.append("")
    else:
        lines.append("(空)")
        lines.append("")
    return lines


# score-analyzer 门禁不通过时的最大尝试次数(重试会把上次失败原因回灌进 prompt)
_SCORE_ANALYZER_MAX_ATTEMPTS = 4

# debug-pro 7 步思考法:每个 case 的诊断必须含以下 6 段,缺任一段视为思考不完整
# (正则, 展示名) —— 展示名用于降级说明里告诉排查者缺了什么
_SCORE_ANALYZER_REQUIRED_SECTIONS = [
    (r"#### 1\. gold/llm_output 对比", "#### 1 gold/llm_output 对比"),
    (r"#### 2\. trace 工具调用链路", "#### 2 trace 工具调用链路"),
    (r"#### 3\. 建议根因", "#### 3 建议根因"),
    (r"#### 4\. 建议 mod 方向", "#### 4 建议 mod 方向"),
    (r"#### 5\. 验证", "#### 5 验证"),
    (r"#### 6\. 回归风险", "#### 6 回归风险"),
]




def _load_round_4_segments(score_dir: Path, phase3_dir: Path,
                           agent_dir: Path | None = None) -> tuple[dict, dict, dict, dict, str, dict]:
    """从 score_dir 的 score.json 读 4 段数据,字典缺失则 phase3-eval 兜底。

    返回:(per_case_f1, gold_per_case, llm_output_per_case, diff_notes_per_case, result_score_str, path_per_case)
    path_per_case (2026-07-30 新增): {case_id: 完整子目录路径字符串,精确无通配符},
    让 result_diff_report.md 标注的真实路径可被 LLM/人类精确打开。

    **2026-07-31 改造**:gold_per_case / llm_output_per_case 字典的 value 是**绝对路径字符串**
    (`/...` 开头),不再是大段原文。渲染层 `_render_case_4_segments` 按路径 Read 真文件原文,
    杜绝第二次 LLM 调用"凭印象编造" gold/llm_output 内容。diff_notes_per_case 保持原样。

    **2026-08-10 改造(移植自 skillxalpha)**:委托 `_collect_diff_run_infos` + `_aggregate_diff_run_infos`
    做跨 run 聚合(per-case F1 取平均、gold/llm/notes/trace 全保留标注 run 来源),
    再拍平回 6-tuple 兼容旧契约。单 run 时行为与改造前一致。
    """
    run_infos, rs_str = _collect_diff_run_infos(
        score_dir, phase3_dir=phase3_dir, agent_dir=agent_dir,
    )
    agg = _aggregate_diff_run_infos(run_infos, rs_str=rs_str)
    return _flatten_agg_to_4_segments(agg)

def _render_case_4_segments(case_id: str, f1, gold_path: str, llm_path: str, notes_text: str, section_prefix: str = "", resources: dict | None = None, case_dir: str = "", trace_paths: str | list[str] = "", baseline_score: float | None = None, *, run_evidence: dict | None = None, middle_products: list | None = None) -> list[str]:
    """渲染单个 case 的 4 段(F1 + gold + Skill 产出 + diff_notes + 资源消耗)。

    F1 徽章单独置顶(用户要求 F1 显眼),三段证据紧跟其后。
    resources (2026-07-30 新增): {duration_ms, input_tokens, output_tokens} per case,
    让 proposal-agent 评估"涨分 vs 资源开销" trade-off。
    trace_paths: Agent 执行轨迹路径,
    list of 绝对路径 = [trace.log(整体轨迹,主推)] + [session/run/*/subagents/agent-*.jsonl(各 skill 轨迹)]。
    proposal-agent 必读(低分 case 强制)用于 trace-aware 诊断。旧数据字符串归一化为 [str] 兼容。
    baseline_score (2026-07-31 新增): 用于判定"低分 case"(f1 < baseline)是否加 ⚠️ 必读标记。

    **2026-07-31 改造**:gold_path / llm_path 是 score.json 字典里的**绝对路径字符串**,
    本函数按路径 Read 真文件原文(防止 LLM 第二次调用把"凭印象生成"的结构化字段写进 score.json)。
    diff_notes 仍是字段字符串(LLM-as-Judge 输出,不是文件原文)。

    **2026-08-10 改造(移植自 skillxalpha)**:新增 `run_evidence` 关键字参数 —— 多 run(run_count>1)时
    转调 `_render_case_4_segments_multi` 渲染(F1 跨 run 平均 + 证据标注 run 来源);
    单 run(run_count<=1)或未传时走原渲染路径,输出与改造前完全一致。
    """
    if run_evidence is not None:
        # 多 run 判定:per-run 证据(per_run_f1 / notes / gold)存在多个 run 条目时走 multi
        _ev_n = (len(run_evidence.get("per_run_f1") or {})
                 or len(run_evidence.get("notes") or {})
                 or len(run_evidence.get("gold") or {}))
        if _ev_n > 1:
            return _render_case_4_segments_multi(case_id, run_evidence, baseline_score)
    from pathlib import Path as _Path

    def _read_text_safe(path_str: str) -> str:
        """按绝对路径 Read 真文件;非绝对路径或文件不存在 → 留空 + 警告。"""
        if not path_str:
            return ""
        p = _Path(path_str)
        if not p.is_absolute():
            return f"⚠️ 路径非法(非绝对路径):{path_str}"
        if not p.exists():
            return f"⚠️ 文件不存在:{path_str}"
        try:
            return p.read_text(encoding="utf-8")
        except Exception as e:
            return f"⚠️ 读取失败:{path_str} ({e})"

    gold_text = _read_text_safe(gold_path)
    llm_text = _read_text_safe(llm_path)

    f1_str = f"{f1:.2f}" if isinstance(f1, (int, float)) else "?"
    f1_mark = "🎯" if isinstance(f1, (int, float)) and f1 >= 90 else ("⚠️" if isinstance(f1, (int, float)) and f1 < 60 else "📊")
    lines: list[str] = [
        f"### {section_prefix}{case_id}",
        "",
        f"**{f1_mark} F1 分数:{f1_str}**",
        "",
    ]
    lines.append("#### 1. gold 答案")
    lines.append("")
    lines.append("```markdown")
    lines.append(gold_text if gold_text else "(空)")
    lines.append("```")
    lines.append("")
    lines.append("#### 2. Skill 实际产出(LLM 输出)")
    lines.append("")
    lines.append("```markdown")
    lines.append(llm_text if llm_text else "(空)")
    lines.append("```")
    lines.append("")
    lines.append("#### 3. LLM-as-Judge diff_notes")
    lines.append("")
    lines.append("```")
    lines.append(notes_text if notes_text else "(空)")
    lines.append("```")
    lines.append("")
    # ── 4. 各skill中间产物(2026-08-05 新增,score-analyzer 归因依据;内容少全贴)──
    # 中间产物:02-触发原因(根因分析skill)/04-场景要素(场景要素分析skill)/06-标准场景识别(标准场景识别skill)/09-用户需求分析(用户需求分析汇总skill)
    lines.append("#### 4. 各skill中间产物")
    lines.append("")
    if middle_products:
        from pathlib import Path as _Path_mp
        for mp in middle_products:
            _mp = _Path_mp(mp) if mp else None
            _fname = _mp.name if _mp else "(空)"
            lines.append(f"**{_fname}**")
            lines.append("")
            lines.append("```markdown")
            if _mp and _mp.is_absolute() and _mp.exists():
                try:
                    _c = _mp.read_text(encoding="utf-8", errors="replace")
                    lines.append(_c if _c.strip() else "(空)")
                except Exception as _e:
                    lines.append(f"⚠️ 读取失败: {_e}")
            else:
                lines.append(f"⚠️ 文件不存在:{mp}" if mp else "(空)")
            lines.append("```")
            lines.append("")
    else:
        lines.append("(无中间产物)")
        lines.append("")
    # ── 5. 资源消耗(2026-07-30 新增,proposal-agent 评估成本/收益权衡的关键依据)──
    if resources:
        dur = resources.get("duration_ms")
        inp = resources.get("input_tokens")
        out = resources.get("output_tokens")
        lines.append("#### 5. 资源消耗(用于评估涨分 vs 成本 trade-off)")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("| :--- | ---: |")
        if isinstance(dur, (int, float)):
            sec = round(dur / 1000, 2)
            lines.append(f"| 耗时 | {int(dur)} ms ({sec}s) |")
        else:
            lines.append("| 耗时 | (缺失) |")
        if isinstance(inp, (int, float)):
            lines.append(f"| 输入 Token | {int(inp)} |")
        else:
            lines.append("| 输入 Token | (缺失) |")
        if isinstance(out, (int, float)):
            lines.append(f"| 输出 Token | {int(out)} |")
        else:
            lines.append("| 输出 Token | (缺失) |")
        lines.append("")
    # ── 6. Trace 路径 + 摘要(贴绝对路径 + 文件摘要,不贴头尾预览,强制必读) ──
    # trace_paths 是 list of 绝对路径 = [trace.log(整体轨迹,主推)] + [subagents/*.jsonl(各 skill 轨迹)],
    # 不再用 trace.jsonl(详细版)。subagents/*.jsonl 读同名 .meta.json 的 agentType 标注 skill 名。
    # 低分 case(f1 < baseline_score)加 ⚠️ 必读标记,proposal-agent 必须 Read 文件本体
    if trace_paths:
        from pathlib import Path as _Path
        import json as _json_meta
        if isinstance(trace_paths, str):
            trace_paths = [trace_paths] if trace_paths else []
        is_low_score = isinstance(baseline_score, (int, float)) and isinstance(f1, (int, float)) and f1 < baseline_score
        trace_warn = " ⚠️ **必读**(低分 case,proposal-agent 诊断根因前必须 Read)" if is_low_score else ""
        lines.append("#### 6. Trace 路径(Agent 执行轨迹,trace-aware 诊断入口)")
        lines.append("")
        lines.append(f"共 {len(trace_paths)} 份 trace 证据:整体轨迹 trace.log + 各 skill 轨迹 subagents/*.jsonl。")
        lines.append("")
        for idx, trace_path in enumerate(trace_paths, 1):
            p = _Path(trace_path)
            # 标注文件类型 + skill 名(读同名 .meta.json 的 agentType)
            label = ""
            if p.name == "trace.log":
                label = "整体轨迹(简化版,主推)"
            elif p.suffix == ".jsonl" and "subagents" in p.parts:
                meta_path = p.with_suffix(".meta.json")
                try:
                    if meta_path.exists():
                        meta = _json_meta.loads(meta_path.read_text(encoding="utf-8"))
                        at = meta.get("agentType", "")
                        label = f"skill 轨迹(subagents,agentType={at})" if at else "skill 轨迹(subagents,meta 无 agentType)"
                    else:
                        label = "skill 轨迹(subagents,meta.json 缺失)"
                except Exception:
                    label = "skill 轨迹(subagents,meta.json 读取失败)"
            lines.append(f"{idx}. `{trace_path}`" + (f" — {label}" if label else ""))
            if p.is_absolute() and p.exists():
                try:
                    size_bytes = p.stat().st_size
                    # 只统计行数/大小,不再贴头尾预览(proposal-agent 必须 Read 文件本体)
                    line_count = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
                    lines.append(f"   📊 **文件摘要**:{size_bytes:,} bytes,{line_count:,} 行")
                except Exception as e:
                    lines.append(f"   ⚠️ 文件读取失败: `{e}`")
            else:
                lines.append(f"   ⚠️ 路径非法或文件不存在(无法贴摘要):`{trace_path}`")
            lines.append("")
        lines.append("📖 **Read 方法(🛑 强制必读)**:按上述顺序 `Read` 文件本体 —— 先 `trace.log`(整体轨迹,简化,覆盖全阶段,先建全貌),再**逐个 Read 全部 `subagents/agent-*.jsonl`**(各 skill 完整执行轨迹,含 skill 片段,定位具体失守环节)。**禁止**只停留在本段路径,必须 `Read` 真实文件后才能诊断/写 mod。")
        lines.append("")
        lines.append(f"🎯 **诊断价值(🛑 必读)**:从 trace 可识别「verify 失败未自愈」「LLM 自由发挥路径」「多余 Bash 步骤」「skill 环节失守/未执行」等 SKILL.md 字段约束覆盖不到的根因;subagents 轨迹定位具体是哪个 skill 环节失守。**低分 case 不 Read 完 trace 不得写 mod**,risk_evidence 必须引用 trace 具体证据。{trace_warn}")
        lines.append("")
    # 🆕 2026-08-01 修复:#### 6 段不再由 _render_case_4_segments 渲染
    # 原因:之前每次 _generate_diff_report 重写 5 段都会带 #### 6 占位,后续 _enrich
    # 跑时旧内容叠加 → 同一 case 失分诊断出现 4-8 次(round_2/result_diff_report_baseline.md 实测)。
    # 修复:#### 6 段由 _enrich_diff_report_with_score_analyzer 独家负责追加。
    # 这里不再 append 占位。
    return lines


# score-analyzer 门禁不通过时的最大尝试次数(重试会把上次失败原因回灌进 prompt)
_SCORE_ANALYZER_MAX_ATTEMPTS = 4


def _build_score_analyzer_prompt(low_score_cases: list, traces: dict, gold_per_case: dict,
                                 llm_per_case: dict, score_dir: Path,
                                 diff_report_path: Path,
                                 history_diff_paths: list | None = None,
                                 middle_products: dict | None = None,
                                 volatility: dict | None = None) -> str:
    """拼 score-analyzer 子 Agent 的 prompt(资源路径 + 历史 diff + 任务契约 + 常见错误提示)。

    history_diff_paths: 历史轮次的 result_diff + skill_diff 配对清单(来自 _build_history_diff_paths)。
    注入后 score-analyzer 能按需读前轮"改了啥→考多少分",判断当前 case 失分是
    "上轮改坏(回归→建议回滚)"还是"新问题(新根因)"。

    volatility (2026-08-10 新增,多 run 评测才传入): {run_count, cases: {case_id: {avg_f1, stddev, per_run_f1}}}。
    run_count>1 时注入波动性分析段,引导诊断"波动大的 case"(run 间不稳定)vs"稳定低分 case",
    并给出稳定性优化方向;run=1 时 volatility=None,不注入任何波动语句。
    """
    import json as _json

    def _fmt_trace_paths(v) -> str:
        # trace 路径 value 可能是 list(trace.log + subagents/*.jsonl),join 展示
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return str(v or "")

    trace_lines = "\n".join(
        f"- {cid}: trace={_fmt_trace_paths(traces.get(cid, ''))} | gold={gold_per_case.get(cid, '')} | llm={llm_per_case.get(cid, '')}"
        for cid in low_score_cases
    )
    # 中间产物路径(score-analyzer 归因中间 skill 用,来自 score.json middle_products_per_case)
    middle_lines = "\n".join(
        f"- {cid}: {_fmt_trace_paths(middle_products.get(cid, []))}"
        for cid in low_score_cases
    )
    # SKILL.md 路径:从 score_dir 往上 2 层找
    skill_md_path = score_dir.parent.parent / "skill" / "SKILL.md"

    # 多 skill 联合优化场景:读 config.json 拿 target_skills,让子 Agent 在 mod 方向里
    # 指明具体 skill(否则 proposal-agent 不知道该改哪个)。
    # ⚠️ 不传绝对路径,只传 skill 名清单;子 Agent 用 Bash ls 找工作区。
    skill_registry_block = ""
    config_json = score_dir.parent.parent / "config.json"
    if config_json.exists():
        try:
            cfg = _json.loads(config_json.read_text(encoding="utf-8"))
            target_skills = cfg.get("target_skills") or []
            if target_skills:
                skill_lines = [f"- {s.get('name', '?')}" for s in target_skills]
                skill_registry_block = (
                    "## skill_registry(多 skill 联合优化)\n"
                    f"本任务涉及 {len(target_skills)} 个 skill(工作区都在 taskid_root/skill/<skill 名>/ 目录下,用 Bash ls 找具体路径):\n"
                    + "\n".join(skill_lines)
                    + "\n\n**重要**:每个 mod 方向必须以 `<skill 名> SKILL.md` 或 `<skill 名> scripts/*.py` 开头,\n"
                    + "不能只写相对路径(否则 proposal-agent 不知道改哪个 skill)。\n"
                    + "**不写绝对路径**——skill 名 + 相对路径即可定位。\n\n"
                )
        except (json.JSONDecodeError, OSError):
            pass

    # 历史轮次 diff 块(改动+结果配对,判断回归 vs 新问题)
    history_block = ""
    if history_diff_paths:
        lines_h = ["## 📜 历史轮次 diff(按需读,判断该 case 是『上轮改坏回归』还是『新问题』)"]
        for h in history_diff_paths:
            rn = h.get("round_num", 0)
            f1 = h.get("f1_str", "?")
            is_base = h.get("is_baseline", False)
            base_tag = "【当前修改基线·重点】" if is_base else "(参考)"
            sk_root = h.get("skill_root", "")
            if rn == 0:
                line = f"- **baseline**{base_tag}(f1={f1}): 结果 `{h['path']}`(无改动)"
                if is_base and sk_root:
                    line += f"\n    基线 skill 全量: `{sk_root}`(Read 定位根因章节,不只靠 diff)"
                lines_h.append(line)
            else:
                sd = h.get("skill_diff_path", "")
                res = h["path"]
                if sd:
                    line = f"- **round_{rn}**{base_tag}(f1={f1}): 改动 `{sd}` | 结果 `{res}` —— **配对读**,判断该轮 mod 救了/害了哪个 case"
                else:
                    line = f"- **round_{rn}**{base_tag}(f1={f1}): 结果 `{res}`(skill_diff 不存在)"
                if is_base and sk_root:
                    line += f"\n    基线 skill 全量: `{sk_root}`(Read 定位根因章节,不只靠 diff)"
                lines_h.append(line)
        lines_h.append("**用法**:某低分 case 在前轮是高分/满分 → 读对应轮 skill_diff,判断『上轮改坏了它』→ mod 方向含**回滚**;")
        lines_h.append("某 case 一直低分 → 新问题/顽固问题,给新根因。")
        history_block = "\n".join(lines_h) + "\n\n"

    # 通用性:gold/llm 文件名用 glob 匹配(从 evolve-user-config.yaml evidence_paths 读),不硬编码业务文件名
    _globs = _load_evidence_globs()
    _gold_glob = ",".join(_globs.get("gold") or ["R_*.md"])
    _llm_glob = ",".join(_globs.get("llm") or ["C_*.md"])

    # 2026-08-10 波动性分析(仅多 run 评测注入;run=1 时 volatility=None,不注入任何波动语句):
    # 引导 score-analyzer 区分"波动大的 case"(run 间不稳定,需收敛)vs"稳定低分 case"(按常规根因优化)。
    volatility_block = ""
    if volatility and volatility.get("run_count", 1) > 1:
        vlines = [
            f"## 📊 波动性分析(多 run 评测,共 {volatility['run_count']} 次 run)",
            "本任务每个 case 跑了多次评测。以下 case 的 F1 **跨 run 波动大**(标准差高 = 结果不稳定,"
            "同一 SKILL.md 在不同 run 间产出不一致):",
            "",
            "| case | 平均 F1 | 标准差 | 各 run F1 |",
            "|------|--------|--------|----------|",
        ]
        vcases = volatility.get("cases") or {}
        for cid in low_score_cases:
            vc = vcases.get(cid) or {}
            if vc.get("stddev") is None:
                continue
            pfr = vc.get("per_run_f1") or {}
            pfr_str = ", ".join(f"run_{k}={v:.2f}" for k, v in sorted(pfr.items()))
            mark = "⚠️波动大" if vc["stddev"] >= 5 else ""
            vlines.append(f"| {cid} | {vc['avg_f1']:.2f} | {vc['stddev']:.2f} | {pfr_str} | {mark}".rstrip(" |"))
        vlines += [
            "",
            "**波动 ≠ 稳定低分**:",
            "- **波动大的 case**(标准差 ≥ 5):根因可能是 Skill 指令含糊导致 run 间漂移、依赖了不稳定输入/检索顺序、"
            "或临界状态偶然命中。mod 方向要**收敛 run 间差异**(把临界判断写成确定性规则),不只提升单次分数;"
            "并在 mod 的 trade-off 里标注**是否有助于降波动**。",
            "- **稳定低分 case**(标准差 < 5):按常规根因(数量/内容/链路)优化。",
            "",
        ]
        volatility_block = "\n".join(vlines) + "\n\n"

    return (
        f"你是 score-analyzer 子 Agent,请为以下低分 case 补充失分诊断。\n\n"
        f"## 低分 case 列表\n{', '.join(low_score_cases)}\n\n"
        + skill_registry_block
        + history_block
        + volatility_block
        + f"## 资源路径(必读)\n"
        f"- trace.jsonl:见下方 trace 路径\n"
        f"- gold 真文件:按 glob `{_gold_glob}` 匹配(每个 case 的 inputs/gold/ 目录下,Read 拿真实文件名)\n"
        f"- llm_output 真文件:按 glob `{_llm_glob}` 匹配(每个 case 的 inputs/agent/ 目录下,Read 拿真实文件名)\n"
        f"- SKILL.md:{skill_md_path}\n"
        f"- diff_notes:从 phase3-eval results/*_eval_data.json 的 evaluation_items[0].diff_notes 读\n\n"
        f"## trace.jsonl 绝对路径(从 result_diff 第 5 段)\n{trace_lines}\n\n"
        f"## 中间产物内容(归因依据,result_diff 报告 `#### 4. 各skill中间产物` 已贴真文件内容)\n"
        f"- 每个低分 case 的中间产物内容已在报告 `#### 4. 各skill中间产物` 段(各中间产物真文件内容全贴),"
        f"直接 Read 报告 `#### 4` 即可(路径参考:{middle_lines}),做误差根因 + 责任归因:"
        f"对比各中间产物与 gold 逐列差异,定位失分最早在哪个中间环节引入,"
        f"再归因到产出该中间产物的 skill 环节——上游产物错→归因上游 skill,下游消费错→归因下游 skill\n\n"
        f"## result_diff_report 路径\n{diff_report_path}\n\n"
        f"## 任务\n按 `agents/score-analyzer.md` 契约输出失分诊断 markdown。\n"
        f"**输出方式(必走)**:用 Edit/Write 工具填 `{score_dir}/_template_score_analyzer.json` "
        f"(字段含义见文件内 `_comment_N` 注释),**不要**输出 markdown/JSON 文本回 framework——"
        f"framework 只读该文件做 schema 校验,并用预制模板(score_analyzer_report.md)渲染成报告。\n"
        f"要求:`overall_analysis` 四字段(失分点矩阵/共性根因聚类/满分 case 风险/推荐整体方向)必填;"
        f"`cases[]` 必须覆盖全部 {len(low_score_cases)} 个低分 case,每个 case 的 `root_causes` + `mod_directions` 必填。\n\n"
        f"## 提示(避免常见错误)\n"
        f"- **🆕 并发分析多个低分 case**:一次 message 发多个 Read(同时读多 case 的 trace / subagents / 报告 `#### 4` 中间产物),"
        f"不要串行逐个分析——避免大量往返耗时过长\n"
        f"- 用 Bash `head -50 {traces.get(low_score_cases[0], '/dev/null')}` + `grep -E \"verify|Edit|Bash\"` 看 trace 工具调用\n"
        f"- 用 Read 工具读 gold/llm_output 真文件(**默认阅读全部低分 case** 的 trace/subagents/gold/llm_output,不要凭印象)——"
        f"framework 最低要求:覆盖 ≥ {max(1, -(-len(low_score_cases) * 4 // 5))} 个低分 case(80%)"
        + (f",且**每个 run 都要覆盖 ≥ {max(1, -(-len(low_score_cases) * 4 // 5))} 个**(多 run 评测,"
           f"只读 run_1 会漏 run_2 的逐 run 根因)" if volatility and volatility.get("run_count", 1) > 1 else "")
        + f",subagents 轨迹 ≥ {max(1, -(-len(low_score_cases) * 4 // 5))} 个,否则诊断不可信\n"
        f"- trace 行号引用至少 2 处 / case\n"
        f"- **mod 方向格式**: `<skill 名> SKILL.md §X.Y 加约束` 或 `<skill 名> scripts/<file>.py 加硬门禁`(多 skill 必须指明)\n"
        f"- 禁止只写 SKILL.md 或 scripts/xxx.py(没指明哪个 skill)\n"
        f"- **三层根因分类(每条根因必标)**:区分 `数量`(元素数与 gold 差异大)/ `内容`(元素数差 ≤2 但语义不对齐)/ `链路`(上游产物缺失)。"
        f"元素数差 ≤2 时**禁止**归数量,必须逐元素对比查内容——gold=2/LLM=3 的语义漂移不能归「场景过度细化」。"
        f"每条根因须指明所在 skill 层(上游产出/下游消费),优先提炼跨 case 共性根因。\n"
        f"- **回滚上轮规则**:若根因是「上轮加的规则导致内容漂移/误伤满分 case」,mod 方向须含回滚/修正该规则,禁止叠加。\n"
        f"- **🆕 编号核实(当根因涉『文件缺失/编号不匹配』时)**:若假设是『XX 编号文件缺失/上游漏产』,"
        f"先用 Read 读相关 skill 的 SKILL.md(Output 表/templates/)核实该编号是否链上必产。"
        f"若链上产物编号跳号(如 01/02/04/05)而门禁检查写『01~07 全存在』,缺失的是空编号,"
        f"真因是门禁过严/编号写错,**不是**上游漏产——不要建议上游强制产出不存在的编号文件。"
    )


def _extract_read_paths_from_log(log_text: str) -> list:
    """从 score-analyzer 调试日志(stream-json)抽 Read 工具实际读取的 file_path。

    防 LLM 自报(_read_audit.json 可伪填):以日志里真实 Read tool_use 的 file_path 为准。
    兼容多种 jsonl 形态(content_block_start / message.content / assistant.content 嵌套 tool_use)。
    """
    paths: list = []
    for line in log_text.splitlines():
        line = line.strip()
        if '"name"' not in line or 'Read' not in line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        def _collect(o):
            if isinstance(o, dict):
                if o.get("type") == "tool_use" and o.get("name") == "Read":
                    fp = (o.get("input") or {}).get("file_path")
                    if fp:
                        paths.append(fp)
                for v in o.values():
                    _collect(v)
            elif isinstance(o, list):
                for x in o:
                    _collect(x)

        _collect(obj)
    return paths


def _run_score_analyzer_once(prompt: str, low_score_cases: list, score_dir: Path,
                             run_count: int = 1) -> tuple:
    """调 score-analyzer 子 Agent 一次并从 `_template_score_analyzer.json` 校验诊断 JSON。

    返回 `(json_data, fail_reason)`:通过全部门禁时 json_data 为诊断 JSON(dict)、fail_reason 为空串;
    任一门禁不通过时 json_data 为 None、fail_reason 说明卡在哪一步(供重试提示与降级说明复用)。

    2026-08 改造:对齐 score.json 的"LLM Edit 文件 + 框架校验"模式 —— score-analyzer 子 Agent
    用 Edit/Write 工具直接填 `score_dir/_template_score_analyzer.json`,框架**不读 LLM 输出文本**,
    只校验文件 JSON schema(overall_analysis + cases[] 覆盖 + 核心字段非空) + 反幻觉 Read 门禁。
    格式由预制模板(score_analyzer_report.md)渲染保证,不再依赖 LLM 输出 markdown 的格式稳定性。
    """
    import os as _os

    try:
        from tools import Agent
        Agent(
            mode="auto",
            description=f"分析 {len(low_score_cases)} 个低分 case 的失分原因({', '.join(low_score_cases[:3])})",
            subagent_type="score-analyzer",
            prompt=prompt,
        )
    except Exception as e:
        return None, f"score-analyzer 子 Agent 调用异常:{e}"

    # 反幻觉门禁:统计子 agent 实际 Read 工具调用次数,须 ≥ case 数(防编造 trace 行号)。
    # 计数来源:TOOL USE SUMMARY 段的 `read=N`(stream-json 模式,tools.py 生成);
    # 兼容旧格式 `ReadTool] call() invoked`(无 raw_jsonl 的 text 模式历史日志)。
    # 落盘日志路径由 tools.py:_resolve_debug_dir 决定(`{SKILLX_CURRENT_TASK_DIR}/_debug/agent_score-analyzer_*.txt`)。
    readtool_count = 0
    try:
        from tools import _resolve_debug_dir as _resolve_sa_debug
        debug_dir = _resolve_sa_debug()
    except Exception:
        debug_dir = None
    if debug_dir is None:
        base = Path(_os.environ.get("SKILLX_CURRENT_TASK_DIR", str(score_dir.parent.parent)))
        debug_dir = base / "_debug"
        if not debug_dir.exists():
            debug_dir = base  # 兼容日志直接落在根目录的旧布局
    sa_logs = sorted(debug_dir.glob("agent_score-analyzer_*.txt"), key=lambda p: p.stat().st_mtime)
    log_text = ""
    if sa_logs:
        log_text = sa_logs[-1].read_text(encoding="utf-8")
        m_read = re.search(r"\bread\s*=\s*(\d+)", log_text)
        readtool_count = int(m_read.group(1)) if m_read else len(re.findall(r"ReadTool\] call\(\) invoked", log_text))
    # 反幻觉门禁(2026-08-10 改为"覆盖率 ≥ 80%"):从 debug 日志抽 Read 实际读取的 file_path,
    # 按 req_id 统计覆盖的 distinct 低分 case 数,须 ≥ ceil(0.8 × N)(10 个至少 8 个,3 个至少 3 个)。
    # 同时要求子代理轨迹(subagents/*.jsonl —— 归因唯一证据)也覆盖 ≥ 80%,缺读诊断不可信。
    import math as _math
    read_paths = _extract_read_paths_from_log(log_text)
    covered_cases: set = set()
    subagent_cases: set = set()
    run_covered: dict = {}   # run_index -> set(该 run 里读到 ≥1 证据的低分 case)
    for _p in read_paths:
        _rm = re.search(r"/run_(\d+)/", _p)
        _ri = int(_rm.group(1)) if _rm else 1
        for _cid in low_score_cases:
            if _cid in _p:
                covered_cases.add(_cid)
                run_covered.setdefault(_ri, set()).add(_cid)
                if "/subagents/" in _p:
                    subagent_cases.add(_cid)
    target_cases = max(1, _math.ceil(0.8 * len(low_score_cases)))
    target_per_run = max(1, int(0.75 * len(low_score_cases)))  # 逐 run 覆盖用 75%(宽松于 case 的 80%)
    # 逐 run 覆盖门禁(2026-08-10):每个 run 里读到的低分 case 数都要 ≥ 75% × N(整数向下取整),
    # 且**所有 run 同时达标** —— 防只读 run_1 证据漏 run_2(一高一低 case 的逐 run 根因)。
    # 单 run(run_count=1)退化为"distinct case 覆盖 ≥ 80%",与原行为一致。
    _n_runs = max(1, int(run_count or 1))
    _failing_runs = [
        ri for ri in range(1, _n_runs + 1)
        if len(run_covered.get(ri, set())) < target_per_run
    ]
    # 子代理轨迹覆盖门禁:仅当评测产物**确实存在 subagents/*.jsonl** 时才强制(真实评测有;
    # mock/诊断脚本不生成 subagents,此时跳过 subagent 覆盖要求,避免误判 REWORK —— 与
    # score.json 的 *Agent性能指标报告 缺失容忍同源)。
    _has_subagents = False
    try:
        _has_subagents = bool(list(score_dir.rglob("subagents/*.jsonl"))[:1])
    except OSError:
        _has_subagents = False
    if readtool_count < 3 or _failing_runs or (len(subagent_cases) < target_cases and _has_subagents):
        _run_msg = ""
        if _failing_runs:
            _run_msg = (f",run {_failing_runs} 覆盖不足"
                        f"(run_{_failing_runs[0]} 覆盖 {len(run_covered.get(_failing_runs[0], set()))}/{len(low_score_cases)}"
                        f",要求每 run ≥ {target_per_run} 个低分 case,即 75%)")
        _sub_msg = (f",其中子代理轨迹(subagents/*.jsonl)覆盖 {len(subagent_cases)} 个"
                    f"(要求 ≥ {target_cases})" if _has_subagents else "")
        return None, (
            f"未通过反幻觉门禁:Read {readtool_count} 次、覆盖 {len(covered_cases)}/{len(low_score_cases)} 个低分 case"
            f"(要求 ≥ {target_cases},即 80%){_run_msg}{_sub_msg}。子 Agent 必须用 Read 实际读大部分低分 case 的 "
            f"trace/subagents/gold/llm_output(归因必须引用子代理轨迹),引用的行号才可信"
        )

    # 读 score-analyzer 填好的 _template_score_analyzer.json(LLM Edit 文件,框架不读 STDOUT 文本)
    tpl_path = score_dir / "_template_score_analyzer.json"
    if not tpl_path.exists():
        return None, f"_template_score_analyzer.json 不存在({tpl_path}),score-analyzer 未填写"
    try:
        data = json.loads(tpl_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return None, f"_template_score_analyzer.json JSON 解析失败:{e}"

    # schema 校验:overall_analysis 4 字段必填 + cases[] 覆盖全部低分 case + 核心字段非空。
    # 对齐 score.json 的 _verify_score_json_written:字段缺失 → 重试,失败原因回灌 prompt。
    overall = data.get("overall_analysis") or {}
    for field in ("matrix", "common_root_causes", "full_mark_risk", "recommendation"):
        if not overall.get(field):
            return None, f"overall_analysis.{field} 为空(整体分析字段缺失)"
    cases = data.get("cases") or []
    case_ids = {c.get("case_id") for c in cases if isinstance(c, dict)}
    missing_cases = [c for c in low_score_cases if c not in case_ids]
    if len(missing_cases) > 1:
        return None, (
            f"未通过 debug-pro 7 步门禁:cases[] 缺失 {len(missing_cases)} 个 case"
            f"({', '.join(missing_cases)})"
        )
    if len(missing_cases) == 1:
        print(f"  ⚠️ [score-analyzer] case {missing_cases[0]} 无诊断对象(已放行)")
    for c in cases:
        if not isinstance(c, dict) or not c.get("case_id"):
            return None, "cases[] 存在无 case_id 的对象"
        if not c.get("root_causes"):
            return None, f"未通过 debug-pro 7 步门禁:case {c.get('case_id')} 缺核心字段 root_causes"
        if not c.get("mod_directions"):
            return None, f"未通过 debug-pro 7 步门禁:case {c.get('case_id')} 缺核心字段 mod_directions"

    print(f"  [score-analyzer] ReadTool {readtool_count} 次、覆盖 {len(covered_cases)}/{len(low_score_cases)} 低分 case"
          f"(要求 ≥{target_cases},subagents 覆盖 {len(subagent_cases)}) + JSON schema 校验通过 → 诊断可信")
    return data, ""


def _render_score_analyzer_report(json_data: dict, volatility: dict | None = None) -> str:
    """用预制 Jinja2 模板把 score-analyzer 的 JSON 诊断渲染成 markdown 正文。

    模板 scripts/scorer/templates/score_analyzer_report.md,与 score.json 的 templates/ 机制一致。
    格式由模板保证(6 段结构固定),缺字段用 ChainableUndefined 软退化渲染为空串,不崩溃。

    volatility (2026-08-10 新增,多 run 评测才传入): {run_count, cases: {case_id: {avg_f1, stddev, per_run_f1}}}。
    模板据此渲染 per-case 的「跨 run 平均 F1 + 各 run 值 + 波动(stddev)」与稳定性优化提示;
    run=1 时 volatility=None,模板走单 run 原路径。
    """
    _tpl_path = Path(__file__).resolve().parent / "scorer" / "templates" / "score_analyzer_report.md"
    try:
        tpl = _tpl_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        from jinja2 import ChainableUndefined, Environment
        return (
            Environment(undefined=ChainableUndefined)
            .from_string(tpl)
            .render(overall=(json_data.get("overall_analysis") or {}),
                    cases=(json_data.get("cases") or []),
                    volatility=volatility)
        )
    except ImportError:
        # 退化:无 jinja2 时按模板骨架简单拼接(保底不丢诊断)
        lines = []
        overall = json_data.get("overall_analysis") or {}
        lines.append("## 📊 整体分析(所有低分 case 共性)\n")
        lines.append("### 失分点矩阵\n\n" + str(overall.get("matrix", "")))
        lines.append("### 共性根因聚类\n\n" + str(overall.get("common_root_causes", "")))
        lines.append("### 满分 case 风险 ⚠️\n\n" + str(overall.get("full_mark_risk", "")))
        lines.append("### 推荐整体方向\n\n" + str(overall.get("recommendation", "")))
        for c in json_data.get("cases") or []:
            lines.append(f"## {c.get('case_id', '?')} 失分诊断\n")
            lines.append(f"**F1**: {c.get('f1', '')}")
            lines.append(f"**核心失分模式**: {c.get('core_loss_mode', '')}")
            lines.append(f"**deepthink 总结**: {c.get('deepthink_summary', '')}")
            rp = c.get("reproduce") or {}
            lines.append("#### 1. gold/llm_output 对比(Step 1: Reproduce)\n")
            lines.append(f"- **R(gold)**: {rp.get('gold', '')}")
            lines.append(f"- **C(LLM 输出)**: {rp.get('llm', '')}")
            lines.append(f"- **命中/漏召回/误召**: {rp.get('hit', '')} / {rp.get('miss', '')} / {rp.get('wrong', '')}")
            lines.append("#### 2. trace 工具调用链路(Step 2: Isolate)\n\n" + str(c.get("trace_evidence", "")))
            lines.append("#### 3. 建议根因(Step 3: Hypothesize)")
            for rc in c.get("root_causes") or []:
                lines.append(f"- **根因**({rc.get('type', '')}, `{rc.get('skill_layer', '')}`): {rc.get('detail', '')}")
            lines.append("#### 4. 建议 mod 方向(Step 4: Instrument)")
            for md in c.get("mod_directions") or []:
                lines.append(f"- **{md.get('skill', '')}**: {md.get('direction', '')}")
            lines.append("#### 5. 验证(Step 5: Verify)\n\n" + str(c.get("verify", "")))
            rr = c.get("regression_risk") or {}
            lines.append("#### 6. 回归风险(Step 7: Regression)\n")
            lines.append(f"- **non_target_cases_risk**: {rr.get('level', '')}")
            lines.append(f"- **影响的满分 case**: {rr.get('affected_cases', '')}")
            lines.append(f"- **缓解措施**: {rr.get('mitigation', '')}")
        return "\n".join(lines)


def _degraded_loss_analysis_body(low_score_cases: list, fail_reason: str, attempts: int) -> str:
    """门禁未通过时的降级正文:说明为何没有诊断,而不是让 `## 失分分析` 段整体缺席。"""
    return (
        f"> ⚠️ **本轮诊断未生成**(已尝试 {attempts} 次)。以下为降级说明,不含子 Agent 诊断内容。\n\n"
        f"- 低分 case:{', '.join(low_score_cases)}\n"
        f"- 失败原因:{fail_reason}\n"
        f"- 影响:proposal-agent 本轮拿不到 trace 级失分根因,只能依据前 5 段证据推断。\n"
        f"- 排查入口:`_debug/agent_score-analyzer_*.txt` 最新一份的 TOOL USE SUMMARY(Read 次数) + score_dir/_template_score_analyzer.json。\n"
    )


def _write_loss_analysis_section(diff_report_path: Path, body: str) -> None:
    """把 body 写入 diff_report 的 `## 失分分析` 段(已存在则整段替换,不叠加)。"""
    if not diff_report_path.exists():
        return
    lines = diff_report_path.read_text(encoding="utf-8").splitlines(keepends=True)
    loss_idxs = [i for i, ln in enumerate(lines) if ln.startswith("## 失分分析")]
    if loss_idxs:
        lines = lines[: loss_idxs[0]]
    section = (
        "\n## 失分分析(前面所有失分原因汇总)\n\n"
        "> 本段由 score-analyzer 子 Agent 在本轮评测完成后立即生成,"
        "内容为各低分 case 的 debug-pro 7 步调试报告"
        "(Reproduce → Isolate → Hypothesize → Instrument → Verify → Regression)。\n\n"
        + body.rstrip() + "\n"
    )
    diff_report_path.write_text("".join(lines) + section, encoding="utf-8")


def _write_score_analyzer_report(diff_report_path: Path, body: str, round_num: int,
                                 best_round: int = 0,
                                 round_score: float | None = None,
                                 baseline_score: float | None = None,
                                 best_round_score: float | None = None) -> None:
    """把 score-analyzer 诊断写为独立文件 score_analyzer_report_round_{N}.md,不再内嵌 result_diff_report。

    2026-08-05 改造:失分诊断从 result_diff_report 尾部内嵌段改为独立文件,便于 proposal-agent
    按"最佳轮【重点】+ 低于最佳分轮【避坑参考】"针对性阅读。result_diff_report 尾部只留指针。
    报告开头标注元信息(本轮/修改基线/分数/涨跌),proposal 不跨文件即可定位上下文。
    """
    # 分数规范化:调用方可能传入 dict(baseline_score 是 score_baseline.json 的 baseline_score 对象)
    # 或 float/str,统一提取为数字,避免渲染出整段 JSON。
    def _norm_score(v):
        if v is None:
            return None
        if isinstance(v, dict):
            for k in ('avg_result_score', 'result_score', 'composite'):
                if k in v:
                    try:
                        return float(v[k])
                    except (TypeError, ValueError):
                        pass
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    round_score = _norm_score(round_score)
    best_round_score = _norm_score(best_round_score)
    baseline_score = _norm_score(baseline_score)

    out_dir = diff_report_path.parent
    report_name = (
        "score_analyzer_report_baseline.md"
        if round_num == 0
        else f"score_analyzer_report_round_{round_num}.md"
    )
    out_path = out_dir / report_name
    # 元信息块(2026-08-05):本轮第几轮 / 修改基线第几轮 / 各自分数 / 涨跌。
    _cur_label = "baseline(基线评测)" if round_num == 0 else f"round_{round_num}"
    _base_label = "baseline(无被采纳轮)" if best_round == 0 else f"round_{best_round}"
    _meta_lines = [
        f"- **本轮**: {_cur_label}" + (f",分数 **{round_score}**" if round_score is not None else ""),
        f"- **修改基线**: {_base_label}" + (f",分数 **{best_round_score}**" if best_round_score is not None else ""),
    ]
    if (round_num > 0 and best_round > 0 and best_round != round_num
            and round_score is not None and best_round_score is not None):
        _delta = round_score - best_round_score
        _meta_lines.append(f"- **本轮 vs 基线**: {_delta:+.2f} (" + ("涨" if _delta >= 0 else "跌") + ")")
    header = (
        "# 失分诊断报告(score-analyzer)\n\n"
        "> 元信息(不跨文件):\n"
        + "".join(f"> {m}\n" for m in _meta_lines)
        + "\n> 本报告由 score-analyzer 子 Agent 在本轮评测完成后生成,含各低分 case 的 debug-pro 7 步调试报告"
        "(Reproduce → Isolate → Hypothesize → Instrument → Verify → Regression)。\n"
        "> proposal-agent 以本文件为失分诊断的唯一来源(不再内嵌于 result_diff_report)。\n\n"
    )
    # 2026-08-05:开头拼该轮 skill_diff(修改尝试),让 proposal 读失分诊断前先建立"改了啥→为什么涨/跌"的因果。
    # baseline 无 skill_diff;round_N 的 skill_diff_round_N.md 在 apply 阶段已生成(早于本报告),可直接读取。
    if round_num > 0:
        _sd_path = diff_report_path.parent / f"skill_diff_round_{round_num}.md"
        if _sd_path.exists():
            try:
                _sd_text = _sd_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                _sd_text = ""
            if _sd_text.strip():
                # 直接原样嵌入 skill_diff(skill_diff 本身是完整 markdown,含自身 ```diff 代码块),
                # 不额外包裹 ```diff 围栏——避免嵌套代码块闭合混乱。
                header += (
                    f"## 📜 本轮 Skill 修改尝试(skill_diff_round_{round_num}.md)\n\n"
                    "> 先看本轮改了哪些 Skill 章节,再读下方失分诊断,理解「改了什么 → 为什么涨/跌」。"
                    "若该轮是【避坑参考】,重点看这些修改尝试为何未能超过最佳轮。\n\n"
                    f"{_sd_text.rstrip()}\n\n---\n\n"
                )
    out_path.write_text(header + body.rstrip() + "\n", encoding="utf-8")
    print(f"  ✅ [score-analyzer] 已写入独立文件 {out_path}")

    # 在 result_diff_report 尾部加指针段:移除旧的内嵌 `## 失分分析` 段,替换为指向独立文件的指针。
    if diff_report_path.exists():
        lines = diff_report_path.read_text(encoding="utf-8").splitlines(keepends=True)
        loss_idxs = [i for i, ln in enumerate(lines) if ln.startswith("## 失分分析")]
        if loss_idxs:
            lines = lines[: loss_idxs[0]]
        pointer = (
            "\n## 失分诊断报告(指针)\n\n"
            f"> 失分诊断由 score-analyzer 子 Agent 生成,已独立落盘为 **`{report_name}`**(与本报告同目录)。\n"
            f"> proposal-agent 应 Read 该独立文件:最佳轮 score_analyzer_report【重点分析对象】+ "
            "分数低于最佳轮的轮次【避坑参考】,逐 RAN 阅读 "
            "`#### 3. 建议根因 / #### 4. 建议 mod 方向 / #### 5. 验证 / #### 6. 回归风险`。\n\n"
        )
        diff_report_path.write_text("".join(lines) + pointer, encoding="utf-8")


def _copy_report_if_changed(src: Path, dst: Path, label: str) -> bool:
    """源存在且与目标内容不同则覆盖拷贝,返回是否真的写了盘。

    幂等:调用方可以反复调用。源(如 baseline 报告)后续补上 `## 失分分析` 也能同步下来 ——
    用 `not dst.exists()` 做一次性拷贝的话,副本会永远停在旧版本。
    """
    if not src.exists():
        return False
    try:
        content = src.read_text(encoding="utf-8")
        if dst.exists() and dst.read_text(encoding="utf-8") == content:
            return False
        dst.write_text(content, encoding="utf-8")
        return True
    except OSError as _e:
        print(f"  ⚠️ 拷贝 {label} 失败: {_e}")
        return False


def _enrich_diff_report_with_score_analyzer(diff_report_path: Path, score_dir: Path,
                                            history_diff_paths: list | None = None,
                                            best_round: int = 0,
                                            baseline_score: float | None = None) -> None:
    """调 score-analyzer 子 Agent 生成各低分 case 的失分诊断,独立落盘 score_analyzer_report_round_{N}.md。

    契约:本函数返回后,只要存在低分 case,`score_analyzer_report_round_{N}.md` 就**必定**生成 ——
    子 Agent 通过门禁则写诊断正文,未通过则写降级说明。这样每轮评测结束时独立报告即已定稿,
    下一轮 `_populate_round_history` 拷过去的不会是缺段的半成品。result_diff_report 尾部只留指针。

    history_diff_paths: 历史轮次 result_diff + skill_diff 配对,注入 prompt 让诊断判断回归/新问题。
    """
    import json as _json
    score_json = score_dir / "score.json"
    if not score_json.exists():
        # round_N 的 score_dir 指向候选聚合目录 `round_N/candidate_K`(为读 candidate_K_score.json),
        # 该目录下没有 score.json;单 run 的 score.json 在 `run_1/` 子目录。
        # 聚合文件 candidate_K_score.json 顶层**不含** info.result_score_per_case(实测 info={}),
        # 不能作为 per-case 分数来源 —— 必须回退到 run_1/score.json。
        alt_run1 = score_dir / "run_1" / "score.json"
        if alt_run1.exists():
            score_json = alt_run1
    if not score_json.exists():
        print(f"  ⚠️ [score-analyzer] {score_json} 不存在(且无 run_1/score.json 兜底),无法生成 ## 失分分析 段")
        return
    try:
        data = _json.loads(score_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as _e:
        print(f"  ⚠️ [score-analyzer] 读 {score_json} 失败({_e}),无法生成 ## 失分分析 段")
        return
    info = data.get("info", {})
    per_case = info.get("result_score_per_case", {}) or {}
    traces = info.get("trace_paths_per_case", {}) or {}
    gold_per_case = info.get("gold_per_case", {}) or {}
    llm_per_case = info.get("llm_output_per_case", {}) or {}
    middle_products = info.get("middle_products_per_case", {}) or {}

    # 2026-08-05:解析本轮聚合分 + 修改基线(best_round)分数,供独立报告开头元信息标注(不跨文件)。
    round_score: float | None = None
    _agg = info.get("result_score_aggregate")
    if _agg is None:
        _agg = info.get("avg_result_score")
    if _agg is not None:
        try:
            round_score = float(_agg)
        except (TypeError, ValueError):
            round_score = None
    best_round_score: float | None = None
    if best_round > 0 and history_diff_paths:
        for _h in history_diff_paths:
            if _h.get("round_num") == best_round:
                try:
                    best_round_score = float(_h.get("f1_str") or 0)
                except (TypeError, ValueError):
                    best_round_score = None
                break
    elif best_round == 0:
        best_round_score = baseline_score  # 修改基线 = baseline,分数 = 基线分

    # 1) 筛非 100 分 case —— 2026-08-10 修复:多 run 用"跨 run 平均"(聚合)判低分,
    #    不用 run_1 单值。否则 run_1 里恰好 100 的 case(如 RAN-6822598 run_1=100)漏判为
    #    非低分,但其跨 run 平均 < 100(波动),仍属低分需分析。聚合结果 _agg_full 供波动块复用。
    _agg_run_infos, _agg_rs, _agg_full = [], "?", {}
    try:
        _agg_run_infos, _agg_rs = _collect_diff_run_infos(score_dir)
        _agg_full = _aggregate_diff_run_infos(_agg_run_infos, rs_str=_agg_rs)
    except Exception:
        _agg_full = {}
    _agg_avg = {
        cid: cd.get("avg_f1")
        for cid, cd in (_agg_full.get("cases") or {}).items()
        if cd.get("avg_f1") is not None
    }
    _score_src = _agg_avg if _agg_avg else per_case
    low_score_cases = [
        cid for cid, score in _score_src.items()
        if isinstance(score, (int, float)) and score < 100
    ]
    if not low_score_cases:
        print("  [score-analyzer] 全 100 分 case,跳过第 6 章节分析")
        return

    # 2) 拼 prompt
    # 2026-08-10 波动性分析(仅多 run 评测注入;run=1 时 volatility=None,不注入波动语句):
    # 跨 run 聚合计算每 case avg_f1 + stddev,供 score-analyzer 区分"波动大 case"vs"稳定低分 case"。
    volatility = None
    try:
        if not _agg_full:
            _agg_run_infos, _agg_rs = _collect_diff_run_infos(score_dir)
            _agg_full = _aggregate_diff_run_infos(_agg_run_infos, rs_str=_agg_rs)
        _vagg = _agg_full
        if _vagg.get("run_count", 1) > 1:
            volatility = {"run_count": _vagg["run_count"], "cases": {}}
            for _cid, _cd in (_vagg.get("cases") or {}).items():
                _pfr = _cd.get("per_run_f1") or {}
                _vals = [v for v in _pfr.values() if isinstance(v, (int, float))]
                if len(_vals) > 1:
                    _mean = sum(_vals) / len(_vals)
                    _std = (sum((v - _mean) ** 2 for v in _vals) / len(_vals)) ** 0.5
                elif _vals:
                    _mean, _std = _vals[0], 0.0
                else:
                    _mean, _std = None, None
                # 预计算模板显示串(避免 Jinja2 min/max 不可靠):avg/min/max/stddev + per-run 串
                _f1_disp, _per_run_str = "?", ""
                if _vals:
                    _mn, _mx = min(_vals), max(_vals)
                    _f1_disp = (f"{_mean:.2f}（min {_mn:.2f} / max {_mx:.2f}, "
                                f"{len(_vals)} runs, stddev {_std:.2f}）")
                _per_run_str = ", ".join(
                    f"run_{k}={v:.2f}" for k, v in sorted(_pfr.items())
                    if isinstance(v, (int, float))
                )
                volatility["cases"][_cid] = {
                    "avg_f1": _mean, "stddev": _std, "per_run_f1": _pfr,
                    "f1_display": _f1_disp, "per_run_str": _per_run_str,
                }
    except Exception:
        volatility = None

    prompt = _build_score_analyzer_prompt(
        low_score_cases, traces, gold_per_case, llm_per_case, score_dir, diff_report_path,
        history_diff_paths=history_diff_paths, middle_products=middle_products,
        volatility=volatility,
    )

    # 2.5) 预放 _template_score_analyzer.json(score-analyzer 用 Edit/Write 填;对齐 score.json 的模板拷贝机制)
    _sa_tpl_path = score_dir / "_template_score_analyzer.json"
    if not _sa_tpl_path.exists():
        _tpl_src = Path(__file__).resolve().parent / "scorer" / "templates" / "score_analyzer.json"
        if _tpl_src.exists():
            _sa_tpl_path.write_text(_tpl_src.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            print(f"  ⚠️ [score-analyzer] 填空模板缺失:{_tpl_src}")

    # 3) 调 score-analyzer 子 Agent(门禁不通过则重试,重试时把上次失败原因回灌进 prompt)
    analysis, fail_reason = None, ""
    best_partial = None     # 所有 attempt 中最完整的 JSON(即使门禁未通过)
    best_partial_score = -1
    for attempt in range(1, _SCORE_ANALYZER_MAX_ATTEMPTS + 1):
        retry_hint = ""
        if fail_reason:
            retry_hint = (
                f"\n\n## ⚠️ 上一次输出未通过 framework 门禁(第 {attempt} 次尝试)\n"
                f"失败原因:{fail_reason}\n"
                f"请针对该原因修正后重新填写 _template_score_analyzer.json。\n"
            )
        analysis, fail_reason = _run_score_analyzer_once(
            prompt + retry_hint, low_score_cases, score_dir,
            run_count=int((volatility or {}).get("run_count", 1) or 1),
        )
        if analysis:
            break
        # 记录本次 attempt 填的 JSON(即使门禁未通过,LLM 可能已填部分诊断);
        # 用 cases 数 + root_causes/mod_directions 总数衡量"分析最多"。
        try:
            if _sa_tpl_path.exists():
                _pd = json.loads(_sa_tpl_path.read_text(encoding="utf-8"))
                _cases = _pd.get("cases") or []
                _cscore = len(_cases) + sum(
                    len((c or {}).get("root_causes") or []) + len((c or {}).get("mod_directions") or [])
                    for c in _cases if isinstance(c, dict)
                )
                if _cscore > best_partial_score:
                    best_partial_score = _cscore
                    best_partial = _pd
        except Exception:
            pass
        print(f"  ⚠️ [score-analyzer] 第 {attempt}/{_SCORE_ANALYZER_MAX_ATTEMPTS} 次失败:{fail_reason}")

    # 4) 写独立 score_analyzer_report 文件。优先级:成功 → 全部失败取"分析最多的那次"(best_partial)
    #    → 完全无分析才降级。2026-08-10:不允许出现"本轮诊断未生成"(取 best_partial 兜底)。
    if analysis:
        body = _render_score_analyzer_report(analysis, volatility=volatility)
        print(f"  ✅ [score-analyzer] 已生成诊断({len(body)} chars)")
    elif best_partial is not None and (best_partial.get("cases")):
        body = _render_score_analyzer_report(best_partial, volatility=volatility)
        print(f"  ⚠️ [score-analyzer] 全部 attempt 未过门禁,取分析最多的那次"
              f"({len(best_partial.get('cases') or [])} case)作为最终结果(不降级)")
    else:
        body = _degraded_loss_analysis_body(low_score_cases, fail_reason, _SCORE_ANALYZER_MAX_ATTEMPTS)
        print(f"  ⚠️ [score-analyzer] 无任何可用的部分分析,写入降级说明:{fail_reason}")
    # 清理模板文件(避免残留干扰下一轮评测)
    if _sa_tpl_path.exists():
        _sa_tpl_path.unlink()
    _m = re.search(r"round_(\d+)", str(diff_report_path))
    _round_num = int(_m.group(1)) if _m else 0
    _write_score_analyzer_report(diff_report_path, body, _round_num,
                                 best_round=best_round,
                                 round_score=round_score,
                                 baseline_score=baseline_score,
                                 best_round_score=best_round_score)


def _dedup_case_loss_analysis_sections(diff_report_path: Path) -> None:
    """🆕 2026-08-01 根治:去重 diff_report 里重复的 case 失分诊断段。

    背景:实测 round_2/result_diff_report_baseline.md 同一 case 段(如 `### RAN-4988439 失分诊断`)
    出现 4 次,内容字符级完全相同。framework 跑 4 次 evaluate → 4 次 _generate_diff_report
    → 每次 `_render_case_4_segments` 重写 5 段 + `_enrich_diff_report_with_score_analyzer`
    把 score-analyzer 输出 append,正则替换只在 `(待分析生成)` 占位一次(已填实不替换),
    导致 4 份 score-analyzer 内容**整段叠加**。

    修复:扫描整个 diff_report,按 `### {case_id} 失分诊断` 段起点 + `---`/`^## `/EOF 段终点,
    对**同一 case_id** 合并为 1 段(保留最长的那一份 = 最新一次写入)。
    """
    if not diff_report_path.exists():
        return
    text = diff_report_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # 找所有 `##/### {case_id} 失分诊断` 段起点行号
    # 用 #{2,3} 兼容 LLM 不稳定的标题级别(实测 ## 与 ### 都出现过)。
    import re as _re2
    section_starts = []
    for i, ln in enumerate(lines):
        m = _re2.match(r"^#{2,3} (RAN-\S+) 失分诊断", ln)
        if m:
            section_starts.append((i, m.group(1)))

    if len(section_starts) < 2:
        return  # 没重复,跳过

    # 对每个 case_id 找所有出现的行号
    from collections import defaultdict
    case_to_starts = defaultdict(list)
    for idx, cid in section_starts:
        case_to_starts[cid].append(idx)

    # 构建"段区间"集合(start_idx, end_idx, case_id)
    # 段终点 = 下一个 `---` 行 或 `^## ` 行 或 EOF
    intervals = []  # [(start, end, case_id)]
    total = len(lines)
    for cid, starts in case_to_starts.items():
        for s in starts:
            # 找段终点
            e = total
            for j in range(s + 1, total):
                stripped = lines[j].strip()
                if stripped == "---" or stripped.startswith("## ") or stripped.startswith("# "):
                    e = j
                    break
            intervals.append((s, e, cid))

    # 按 case_id 合并:每个 case 只保留 1 段(最长的)
    deduped_intervals = []
    seen_cid = {}
    for start, end, cid in sorted(intervals, key=lambda x: -((x[1] - x[0]))):
        if cid not in seen_cid:
            seen_cid[cid] = (start, end)

    # 构建新行列表:遍历原 lines,跳过被"覆盖"的重复段
    # 逻辑:对每个 case_id 只保留最长的那 1 段,其他重复段删除
    keep_intervals = set()
    for cid, (start, end) in seen_cid.items():
        keep_intervals.add((start, end))

    delete_intervals = set()
    for start, end, cid in intervals:
        if (start, end) not in keep_intervals:
            delete_intervals.add((start, end))

    if not delete_intervals:
        return  # 没重复要删

    # 重新构建 lines,跳过 delete 区间
    new_lines = []
    skip_until = -1
    for i, ln in enumerate(lines):
        if i <= skip_until:
            continue
        # 检查是否在 delete 区间内
        delete = False
        for ds, de in sorted(delete_intervals):
            if ds <= i < de:
                skip_until = de - 1
                delete = True
                break
        if delete:
            continue
        new_lines.append(ln)

    removed_count = len(lines) - len(new_lines)
    if removed_count > 0:
        diff_report_path.write_text("".join(new_lines), encoding="utf-8")
        print(f"  [score-analyzer 去重] 删除 {removed_count} 行重复 case 段(原 {len(lines)} → 新 {len(new_lines)})")


def _load_middle_products_per_case(score_dir: Path) -> dict[str, list[str]]:
    """从 score.json.info.middle_products_per_case 读取中间产物路径(score-analyzer 归因用)。

    ExtractionAgent 按 evolve-user-config.yaml extraction 5.4 提取(02/04/06/09 绝对路径)。
    返回:{case_id: [中间产物路径, ...]};字段缺失/文件缺失 → 空 dict(渲染层跳过中间产物段)。
    """
    import json as _json_mid
    sp = score_dir / "score.json"
    if not sp.exists() and not score_dir.name.startswith("run_"):
        alt = score_dir / "run_1" / "score.json"
        if alt.exists():
            sp = alt
    if not sp.exists():
        return {}
    try:
        data = _json_mid.loads(sp.read_text(encoding="utf-8"))
        paths = data.get("info", {}).get("middle_products_per_case", {})
        if not isinstance(paths, dict):
            return {}
        out: dict[str, list[str]] = {}
        for cid, v in paths.items():
            if isinstance(v, list):
                out[cid] = [p for p in v if isinstance(p, str) and p]
            elif isinstance(v, str):
                out[cid] = [v] if v else []
        return out
    except Exception:
        return {}


def _load_trace_paths_per_case(score_dir: Path) -> dict[str, list[str]]:
    """从 score.json.info.trace_paths_per_case 读取 ExtractionAgent 抽取的 trace 路径。

    ExtractionAgent 按 evolve-user-config.yaml 的 evidence_paths.trace_path_template
    把 trace 证据路径写到 score.json.info.trace_paths_per_case。
    框架层只读不推断(配置驱动)。
    返回:{case_id: [trace_path, ...]},每个 value 是 list of 绝对路径,
    含 trace.log(整体轨迹,主推)+ session/run/*/subagents/agent-*.jsonl(各 skill 轨迹)。
    旧数据 value 为字符串时归一化为 [str] 兼容;非 str/list 的脏值过滤为 []。
    文件缺失/字段缺失 → 返回空 dict(渲染层跳过 trace 段)
    """
    score_json = score_dir / "score.json"
    if not score_json.exists() and not score_dir.name.startswith("run_"):
        score_json = score_dir / "run_1" / "score.json"
    if not score_json.exists():
        return {}
    try:
        import json as _json_tp
        with open(score_json) as _f:
            data = _json_tp.load(_f)
        info = data.get("info", {})
        paths = info.get("trace_paths_per_case", {})
        if not isinstance(paths, dict):
            return {}
        out: dict[str, list[str]] = {}
        for cid, v in paths.items():
            if isinstance(v, str):
                out[cid] = [v] if v else []
            elif isinstance(v, list):
                out[cid] = [p for p in v if isinstance(p, str) and p]
            else:
                out[cid] = []
        return out
    except Exception:
        return {}


def _load_round_resources(score_dir: Path) -> dict:
    """从 score.json.info 读取 per-case 资源消耗:duration_ms / input_tokens / output_tokens。

    返回:{case_id: {"duration_ms": int, "input_tokens": int, "output_tokens": int}}
    任何字段缺失则该字段不出现(渲染层跳过)。
    """
    import json as _json_res
    out: dict = {}
    sp = score_dir / "score.json"
    if not sp.exists():
        return out
    try:
        sd = _json_res.loads(sp.read_text(encoding="utf-8"))
        info = sd.get("info") or {}
        dur_pc = info.get("duration_ms_per_case") or {}
        inp_pc = info.get("input_tokens_per_case") or {}
        out_pc = info.get("output_tokens_per_case") or {}
        for case_id in set(dur_pc) | set(inp_pc) | set(out_pc):
            res: dict = {}
            if isinstance(dur_pc.get(case_id), (int, float)):
                res["duration_ms"] = dur_pc[case_id]
            if isinstance(inp_pc.get(case_id), (int, float)):
                res["input_tokens"] = inp_pc[case_id]
            if isinstance(out_pc.get(case_id), (int, float)):
                res["output_tokens"] = out_pc[case_id]
            if res:
                out[case_id] = res
    except Exception:
        pass
    return out


def _finish_skill_bak(args) -> None:
    """任务成功 finish:清理 .bak + 清 config user_source_bak 字段(走决策 4)。"""
    _sp_list = _resolve_skill_path_list(args)
    if _sp_list:
        _cleanup_skill_bak(_sp_list)
    # 从 config.json 删除 user_source_bak 字段(避免下次启动误以为还有未恢复的备份)
    _cfg_path = Path(args.workspace).resolve() / "config.json"
    _clear_user_source_bak_from_config(_cfg_path)

# ── 实时输出：禁用 stdout/stderr 缓冲（子进程非 TTY 时默认全缓冲）──
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)


def _compute_modification_budget(round_num: int) -> int:
    """借鉴 SkillOpt lr_autonomous:前几轮允许大改(round=0 预算 8),后几轮强制微改(round≥6 预算 2)。

    配置源:`framework_configs/proposal-agent-config.yaml` 的 `modification_budget` 段
    (default=8, slope=1, floor=2)。此函数是 fallback,默认值与 yaml 对齐。
    """
    default = 8
    slope = 1
    floor = 2
    return max(default - slope * round_num, floor)


def _write_round_proposal_md(agent_dir: Path, round_num: int, candidate_id: int = 1,
                             run_count: int = 1) -> Optional[Path]:
    """把 round_N/candidate_K/optimization_summary.md 升格为 round_N/proposal.md。

    用户契约(2026-07-21 强化):
      - 每轮都要产出 round_N/proposal.md,作为本轮"提案"的可审计产物
      - 内容从 optimization_summary.md 复制,头部加上标题与时间戳
      - 同时回填 baseline/proposal.md(R1 的 proposal 就是基于 baseline 的)

    run_count (2026-08-10 新增): 评测每 case 的 run 数。run_count>1 时头部标注
    "多 run 评测(每 case N 次,分数为跨 run 平均)";=1 时保持原头部。

    Returns:
        写入的 proposal.md 路径;若 optimization_summary.md 不存在则返回 None
    """
    src = agent_dir / f"round_{round_num}" / f"candidate_{candidate_id}" / "optimization_summary.md"
    if not src.exists():
        print(f"  ⚠️ round_{round_num}/candidate_{candidate_id}/optimization_summary.md 不存在,跳过 proposal.md")
        return None

    try:
        text = src.read_text(encoding="utf-8")
    except Exception as _e:
        print(f"  ⚠️ 读 optimization_summary.md 失败: {_e}")
        return None

    # 头部加 Round 标题与时间戳,便于审计/对比 baseline/proposal.md
    _run_note = (
        f"- **评测**: 多 run(每 case {int(run_count)} 次,分数为跨 run 平均,波动性分析见 score_analyzer_report)\n"
        if int(run_count) > 1 else ""
    )
    header = (
        f"# Round {round_num} 优化提案\n\n"
        f"- **时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **来源**: ProposalAgent(单次 LLM 调用: context + gaps + modifications + Edit + summary)\n"
        f"- **优化摘要路径**: `round_{round_num}/candidate_{candidate_id}/optimization_summary.md`\n"
        + _run_note
        + "\n---\n\n"
    )
    proposal_text = header + text

    # 写到 round_N/proposal.md
    dst_round = agent_dir / f"round_{round_num}" / "proposal.md"
    dst_round.parent.mkdir(parents=True, exist_ok=True)
    dst_round.write_text(proposal_text, encoding="utf-8")
    _log_write(dst_round, f"round_{round_num}_proposal_md", agent_dir)

    # R1 时同时回填 baseline/proposal.md(R1 的提案就是基于 baseline 的)
    if round_num == 1:
        dst_baseline = agent_dir / "baseline" / "proposal.md"
        dst_baseline.parent.mkdir(parents=True, exist_ok=True)
        dst_baseline.write_text(proposal_text, encoding="utf-8")
        _log_write(dst_baseline, "baseline_proposal_md_from_r1", agent_dir)

    return dst_round


def _escape_diff_fence(text: str) -> str:
    """把 diff 内容里行首(可带前导空白)的 ```(SKILL.md 自带代码块边界)转义为 ``,
    避免其提前关闭外层 ```diff 代码块导致后续 diff 行无红绿渲染。
    注:markdown 里缩进 ≤3 空格的 ``` 也会闭合代码块,故用 [ \t]* 覆盖。"""
    import re as _re_esc
    return _re_esc.sub(r"^[ \t]*```", "``", text, flags=_re_esc.M)


def _write_round_diff_md(agent_dir: Path, round_num: int, skill_names: list, candidate_id: int = 1) -> Optional[Path]:
    """生成 round_N/skill_diff_round_N.md:对每个 Skill 输出 before vs after 的 unified diff(+++ / ---)。

    用户契约(2026-07-21):
      - 每次生成修改后的 skill 后,用代码生成所有 skill 的 diff 段落
      - 用 +++ / --- 表示(unified diff 格式)
      - 单个 md 文件,按 Skill 分段

    Args:
        agent_dir: 任务 workspace 根
        round_num: 当前轮次
        skill_names: 所有 Skill 名列表
        candidate_id: 候选编号(默认 1)

    Returns:
        写入的 skill_diff_round_N.md 路径;若 before/after 都不存在则返回 None
    """
    from orchestrators.skill_manager import skill_md_diff

    lines = [
        f"# Round {round_num} 修改 Diff 段落\n",
        f"- **时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **来源**: code-generated(对比 round_{round_num}_before_skill vs round_{round_num}/candidate_{candidate_id}/skill)",
        "- **格式**: unified diff(`+++` 新增 / `---` 删除)\n",
        "---",
        "",
    ]

    has_any_diff = False
    for name in skill_names or []:
        diff_info = skill_md_diff(agent_dir, round_num, candidate_id, name)
        # 附加文件级 diff(非 SKILL.md,如 scripts/*.py, templates/*.md)
        before_dir = agent_dir / f"round_{round_num}" / f"round_{round_num}_before_skill" / "skill" / name
        after_dir = agent_dir / f"round_{round_num}" / f"candidate_{candidate_id}" / "skill" / name
        extra_diffs = []
        if before_dir.exists() and after_dir.exists():
            extra_diffs = _collect_extra_file_diffs(before_dir, after_dir)

        if not diff_info.get("diff_text") and not extra_diffs:
            lines.append(f"\n## Skill: {name}\n\n_(无变更)_\n")
            continue

        has_any_diff = True
        lines.append(f"\n## Skill: {name}\n")
        lines.append(
            f"- added: {diff_info.get('added', 0)}, "
            f"removed: {diff_info.get('removed', 0)}, "
            f"changed_lines: {diff_info.get('changed_lines', 0)}\n"
        )
        if diff_info.get("diff_text"):
            lines.append("### SKILL.md\n")
            lines.append("```diff")
            lines.append(_escape_diff_fence(diff_info["diff_text"].rstrip()))
            lines.append("```\n")
        for extra in extra_diffs:
            lines.append(f"### {extra['rel_path']}\n")
            lines.append("```diff")
            lines.append(_escape_diff_fence(extra["diff_text"].rstrip()))
            lines.append("```\n")

    if not has_any_diff:
        lines.append("\n_(本轮所有 Skill 都没有变更)_\n")

    dst = agent_dir / f"round_{round_num}" / f"skill_diff_round_{round_num}.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines), encoding="utf-8")
    _log_write(dst, f"round_{round_num}_diff_md", agent_dir)
    return dst


def _collect_extra_file_diffs(before_dir: Path, after_dir: Path) -> list:
    """收集 SKILL.md 之外的所有文件 diff(按相对路径)。

    Returns:
        [{"rel_path": "scripts/foo.py", "diff_text": "..."}, ...]
    """
    import difflib
    extras = []
    skip_dirs = {".git", "__pycache__", ".venv", "node_modules"}
    after_files = {f.relative_to(after_dir): f for f in after_dir.rglob("*") if f.is_file()}
    before_files = {f.relative_to(before_dir): f for f in before_dir.rglob("*") if f.is_file()}
    all_paths = sorted(set(after_files) | set(before_files))
    for rel in all_paths:
        # 跳过 SKILL.md(主函数已处理) + 跳过大目录
        if str(rel) == "SKILL.md":
            continue
        if any(part in skip_dirs for part in rel.parts):
            continue
        bf = before_files.get(rel)
        af = after_files.get(rel)
        if bf is None and af is not None:
            # 新增文件:用 /dev/null 标记,统一 diff 显示"--- /dev/null\n+++ b/file"
            try:
                content = af.read_text(encoding="utf-8")
            except Exception:
                continue
            diff_text = "".join(difflib.unified_diff(
                [], content.splitlines(keepends=True),
                fromfile="/dev/null",  # 🆕 修复 2026-08-03:用 /dev/null 标记新增,避免被误认为编辑
                tofile=f"b/{rel}",
            ))
            extras.append({"rel_path": str(rel), "diff_text": diff_text})
        elif af is None and bf is not None:
            # 删除文件:用 /dev/null 标记
            try:
                content = bf.read_text(encoding="utf-8")
            except Exception:
                continue
            diff_text = "".join(difflib.unified_diff(
                content.splitlines(keepends=True), [],
                fromfile=f"a/{rel}",
                tofile="/dev/null",  # 🆕 修复 2026-08-03:用 /dev/null 标记删除
            ))
            extras.append({"rel_path": str(rel), "diff_text": diff_text})
        elif bf is not None and af is not None:
            try:
                b_text = bf.read_text(encoding="utf-8")
                a_text = af.read_text(encoding="utf-8")
            except Exception:
                continue
            if b_text == a_text:
                continue
            diff_text = "".join(difflib.unified_diff(
                b_text.splitlines(keepends=True), a_text.splitlines(keepends=True),
                fromfile=f"a/{rel}",  # 🆕 修复 2026-08-03:与新增/删除分支保持 a/b/ 标记一致
                tofile=f"b/{rel}",
            ))
            extras.append({"rel_path": str(rel), "diff_text": diff_text})
    return extras


def _write_baseline_proposal_md(agent_dir: Path, bl_gaps: list, baseline_score: float) -> Optional[Path]:
    """基线评测完成后写 baseline/proposal.md(无 LLM 调用,从 bl_gaps 推导)。

    用户契约(2026-07-21):基线阶段也要产 proposal.md,
    内容是"基线发现的 gaps + 建议的下一步方向",供 R1 proposal-agent 参考。
    不调用 LLM,直接基于 baseline/score_baseline.json + bl_gaps 渲染。

    Note: R1 的 proposal-agent 完成后会再覆盖 baseline/proposal.md(更新版)。
    """
    baseline_dir = agent_dir / "baseline"
    if not baseline_dir.exists():
        return None

    sb_path = baseline_dir / "score_baseline.json"
    if not sb_path.exists():
        return None

    # 渲染 proposal.md
    lines = [
        "# Baseline 优化提案\n",
        f"- **时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "- **来源**: ScoreAnalyzer(纯代码生成,基线评测完成时自动写)",
        f"- **基线分数**: {baseline_score:.2f}\n",
        "---",
        "",
        "## 基线发现的 gaps\n",
    ]

    if not bl_gaps:
        lines.append("_(基线无显著 gap,分数已达目标)_\n")
    else:
        lines.append(f"共 {len(bl_gaps)} 个 gap:\n")
        lines.append("| # | type | severity | message | affected_section |\n|---|---|---|---|---|")
        for i, g in enumerate(bl_gaps[:30], 1):
            t = g.get("type", "?") if isinstance(g, dict) else "?"
            sev = g.get("severity", "?") if isinstance(g, dict) else "?"
            msg = (g.get("message", "") if isinstance(g, dict) else str(g))[:120].replace("\n", " ")
            sec = (g.get("affected_section", "") if isinstance(g, dict) else "")[:60].replace("|", "\\|")
            lines.append(f"| {i} | {t} | {sev} | {msg} | {sec} |")
        if len(bl_gaps) > 30:
            lines.append(f"\n_(仅显示前 30 条,共 {len(bl_gaps)} 条)_\n")
        lines.append("")

    # 下一步方向(R1 proposal-agent 会基于此 prompt,这里给出框架性建议)
    lines.extend([
        "## 建议的下一步方向(供 R1 proposal-agent 参考)\n",
        f"- 优先修复 critical / high severity 的 gap(基线分数 {baseline_score:.2f} 反映的整体健康度)",
        "- 关注 gap 的 `affected_section` 列,针对性修改对应 Skill 的对应 H2 章节",
        "- 跨多 gap 的根因(如同一类输入路径缺失)优先用 `extract_to_script` 抽脚本",
        "- 注意防过拟合:`reason` 字段须含通用/系统/一致/共同/大多数/通常 之一",
        "",
        "---",
        "",
        "_注:此文件由 ScoreAnalyzer 自动生成(无 LLM 调用)。",
        "R1 完成后,proposal-agent 会基于本提案 + 实测 gaps 重新生成 baseline/proposal.md 与 round_1/proposal.md。_",
        "",
    ])

    dst = baseline_dir / "proposal.md"
    dst.write_text("\n".join(lines), encoding="utf-8")
    _log_write(dst, "baseline_proposal_md", agent_dir)
    return dst


def _sync_candidate_to_original(
    candidate_skill_root: Path,
    skill_path_list: list,
    log_prefix: str = "",
) -> None:
    """把 candidate 副本同步回原始 skill 路径(严格替换)。

    触发时机:每次 candidate 优化完成 → mv 到 round_N/candidate_K/ → eval 前
    目的:让原始 --skill-paths 始终是最新版本,后续手动 /sdd-eval 跑的是优化后的版本

    严格替换语义(避免文件数差异导致 stale 残留):
    1. rmtree(原始 skill 目录)—— 整个目录删干净
    2. copytree(candidate 副本 → 原始路径)—— 完全复制

    Args:
        candidate_skill_root: round_N/candidate_K/skill/ 副本根目录
        skill_path_list: 原始 --skill-paths 列表(每个 SKILL.md 的完整路径)
        log_prefix: 日志前缀(通常含轮次/候选信息)
    """
    if not candidate_skill_root.exists():
        print(f"  {log_prefix}⚠️ candidate_skill_root 不存在: {candidate_skill_root},跳过同步")
        return
    synced, failed = [], []
    for sp in skill_path_list:
        name = Path(sp).resolve().parent.name
        # candidate 侧的 skill 目录:round_N/candidate_K/skill/{name}/
        src_dir = candidate_skill_root / name
        if not src_dir.exists():
            failed.append(f"{name}(candidate 缺)")
            continue
        # 原始 skill 目录:原始 SKILL.md 的父目录(整个目录,不是单文件)
        dst_dir = Path(sp).resolve().parent
        if not dst_dir.exists():
            # 原始目录不存在(被外部删了),跳过避免误创建
            failed.append(f"{name}(原始路径不存在)")
            continue
        try:
            # 严格替换:先 rm -rf 整个原始目录
            shutil.rmtree(str(dst_dir))
            # 再 copytree 完整复制
            shutil.copytree(str(src_dir), str(dst_dir))
            synced.append(f"{name} → {dst_dir}")
        except Exception as e:
            failed.append(f"{name}({type(e).__name__}: {e})")
    if synced:
        print(f"  {log_prefix}✅ 同步 candidate → 原始路径 ({len(synced)} 个):")
        for s in synced:
            print(f"    {s}")
    if failed:
        print(f"  {log_prefix}❌ 同步失败 ({len(failed)} 个): {', '.join(failed)}")


def _sync_candidate_to_workspace_skill(agent_dir: Path, candidate_skill_root: Path) -> int:
    """候选评测前,把本轮 candidate skill 同步到 workspace skill(taskid/skill/)。

    2026-08-03 修复(用户验收发现):评测 agent 的 skill 由 `_sync_skill_to_eval_agents`
    从 workspace skill(agent_dir/skill/)同步到 `skills/`。而 workspace skill
    每轮只在 round 开始时从 best_round 继承,**apply 后不更新** → 本轮评测测的是
    best_round 版本,本轮 candidate 优化不体现在分数。

    修复:apply 完成后立即把本轮 candidate(round_N/candidate_K/skill)同步到
    workspace skill,保证评测前 `_sync_skill_to_eval_agents` 同步的是优化后版本。

    Returns: 同步的 Skill 目录数
    """
    import shutil as _sh

    ws_root = Path(agent_dir) / "skill"
    if not ws_root.is_dir() or not candidate_skill_root.is_dir():
        return 0
    synced = 0
    for sd in candidate_skill_root.iterdir():
        if not sd.is_dir():
            continue
        dst = ws_root / sd.name
        if dst.exists():
            _sh.rmtree(str(dst))
        _sh.copytree(str(sd), str(dst))
        synced += 1
    if synced:
        print(f"  📥 同步 candidate → workspace skill(taskid/skill/) {synced} 个,供评测 agent 读取")
    return synced


def _log_write(path, source: str, agent_dir=None) -> None:
    """
    统一的写文件日志（按用户要求：每次迭代任务写文件都要打印日志）。

    Args:
        path: 写入的文件路径（Path 或 str）
        source: 写入来源（如 'evaluate'、'candidate_apply'、'round_score_synthesis'）
        agent_dir: 可选，相对路径基准（Path）
    """
    p = Path(path)
    if agent_dir is not None:
        try:
            rel = p.relative_to(agent_dir)
        except ValueError:
            rel = p
    else:
        rel = p
    print(f"  ✓ 写产物: {rel} (来源: {source})", flush=True)


def parse_args():
    """命令行参数解析"""
    parser = argparse.ArgumentParser(
        description="skillx-alpha Orchestrator — 评测-优化循环编排器"
    )
    parser.add_argument("--workspace", default="",
                        help="项目工作目录（Agent 根目录，默认从 --skill-path 自动推断）")
    parser.add_argument("--skill-path", default="",
                        help="内部兼容：命令层统一使用 --skill-paths（单路径=单 Skill，多路径=Agent）；此参数供 --round 子进程 / config.json 恢复时使用")
    parser.add_argument("--agent-path", default="",
                        help="Agent 根目录（含 skills/，--mode static 下扫描全部 Skill 挨个独立优化，与 --skill-path 互斥）")
    parser.add_argument("--max-rounds", type=int, default=4,
                        help="最大轮次（默认 4）")
    parser.add_argument("--per-skill-rounds", type=int, default=1,
                        help="多 Skill 模式（--agent-path）下每个 Skill 的最大轮次（默认 3，传 0 则用 --max-rounds）")
    parser.add_argument("--evaluator-agent", default="",
                        help="外部评测 Agent 名称")
    parser.add_argument("--non-interactive", action="store_true",
                        help="非交互模式（跳过人工审批，自动 yes）")
    parser.add_argument("--enable-skill-execution", action=argparse.BooleanOptionalAction, default=True,
                        help="启用真实 Skill 执行（默认启用，--no-enable-skill-execution 可关闭）")
    parser.add_argument("--static-only", action="store_true",
                        help="仅做静态评测，不执行 skill")
    parser.add_argument("--model-reasoning", default="",
                        help="推理模型覆盖（默认 minimax）")
    # 评测专用模型参数（与优化/分析阶段的全局模型隔离）
    parser.add_argument("--eval-model", default="",
                        help="评测阶段使用的模型（LLM 解析/Gap 分析/沙箱脚本），未配置时回退到全局模型")
    parser.add_argument("--eval-api-base", default="",
                        help="评测阶段专用 API 端点地址（未配置时回退到 --api-base）")
    parser.add_argument("--eval-api-key", default="",
                        help="评测阶段专用 API 密钥（未配置时回退到 --api-key）")
    parser.add_argument("--api-base", default="",
                        help="API 端点地址（优先级高于环境变量 SKILLX_API_BASE）")
    parser.add_argument("--api-key", default="",
                        help="API 密钥（优先级高于环境变量 SKILLX_API_KEY）")
    parser.add_argument("--eval-mode", default="",
                        help="评测模式: baseline/candidate（内部使用）")
    parser.add_argument("--eval-run-index", type=int, default=1,
                        help="评测 run 索引（内部使用，控制归档目录名；默认 1）")
    parser.add_argument("--max-cases", type=int, default=0, dest="max_rans",
                        help="最多评测 CASE 数（0=全部）")
    parser.add_argument("--case-filter", default="", dest="ran_filter",
                        help="CASE 过滤正则")
    parser.add_argument("--round", type=int, default=None,
                        help="仅执行指定轮次（用于进程隔离模式，子进程从 config.json 恢复其他参数）")
    parser.add_argument("--phase", choices=("eval", "optimize"), default=None,
                        help="子进程执行阶段：eval（测+评）或 optimize（优化）")
    # ── /skill_optimize 静态模式参数（v1 全开放 + 4 层保护）──
    parser.add_argument("--mode", choices=("eval", "static", "refactor", "refactor-diff-report", "refactor-self-check", "create"), default="eval",
                        help="运行模式：eval（评测驱动）/ static（静态优化，无 eval-cmd）/ refactor（结构层重构，无 eval-cmd 无评分）/ refactor-diff-report（生成 before vs after diff HTML 报告）/ refactor-self-check（Step 11 独立自我检查，根治用户感知）/ create（无头 Skill 创建流水线，Phase A-E，零 CC 主 Agent 依赖）")
    parser.add_argument("--max-files", type=int, default=20,
                        help="静态模式：单次最多优化的文件数（默认 20）")
    parser.add_argument("--protected-assets", default="",
                        help="静态模式：强制保护的附属资产（逗号分隔 glob 模式）")
    parser.add_argument("--break-threshold", type=float, default=1.0,
                        help="静态模式：触顶 break 阈值（连续 2 轮 Δ < 此值即停，默认 1.0；用户要求降低接受门限）")
    parser.add_argument("--expert-guidance", default="",
                        help="专家经验/规范/建议（自然语言）。evolve 模式：写入 config.json 的 expert_guidance 字段，注入 ProposalAgent prompt 顶部专家指引块，支持任务中编辑 config.json；静态模式：注入所有子 Agent prompt 顶部")
    parser.add_argument("--no-revert", action="store_true",
                        help="静态模式：关闭 git revert HEAD 自动回退（仅调试用）")
    parser.add_argument("--score-mode", choices=("llm_direct", "subagent"), default=None,
                        help="评分执行路径：llm_direct=拼 prompt 直连大模型（默认）；subagent=cc tools.Agent 真子 Agent + 编码 skill 注入（慢 2-3 倍但更稳）")
    parser.add_argument("--dry-run", action="store_true",
                        help=" 静态模式：只生成 proposal，不应用 modifications（调试用）")
    # ── 多 runtime 支持（WS-1/WS-4）：子 Agent 调度后端选择 ──
    parser.add_argument("--agent-cli", default=None, choices=("claude", "codex", "dsh"),
                        help="子 Agent runtime（显式 --agent-cli > env SKILLX_AGENT_CLI > 默认 claude；"
                             "create 模式下作为 3 个子 Agent 的调度后端）")
    # ── /skill_create 无头模式（--mode create）──
    parser.add_argument("--create-skill-name", default="", help="create 模式：Skill 名(kebab-case)")
    parser.add_argument("--create-requirement", default="", help="create 模式：需求 @file.md 或自然语言")
    parser.add_argument("--create-output-dir", default="", help="create 模式：工作区绝对路径")
    parser.add_argument("--create-expert-guidance", default="", help="create 模式：专家指引(可选)")
    # ── /skill_optimize --mode refactor 重构模式参数（结构层手术，无 eval-cmd 无评分；原 /skill_refactor，v2 合并）──
    # 复用 static mode 的 --expert-guidance（行 181-182），不重复定义
    parser.add_argument("--no-fresh-session", action="store_true",
                        help="禁用每轮新进程（默认启用跨轮进程隔离）")
    parser.add_argument("--auto-apply", action="store_true",
                        help="refactor 模式：plan 草稿自动生成后，经 AgentRunner 调度 refactor-applier-agent"
                             " 在 after_skill/ 副本上应用剩余 ~20%% 编辑（无需 CC 主 Agent HITL；"
                             "不传则保持现有 CC 交互审批路径，向后兼容）")
    # 外部评测工作流参数（仅 workflow-type / workflow-script / result-path 保留；eval-config 由下方 metrics 段定义）
    parser.add_argument("--workflow-type", default="script",
                        choices=("script", "skill", "cosight_command"),
                        help="外部工作流类型（默认 script）")
    parser.add_argument("--workflow-script", default="",
                        help="外部评测脚本路径（快捷模式，无需 YAML）")
    parser.add_argument("--result-path", default="",
                        help="外部评测结果 JSON 路径（相对于 output_dir）")
    # 业务方完整评测管道参数
    parser.add_argument("--pipeline-config", default="",
                        help="业务方评测管道 YAML 配置文件路径")
    parser.add_argument("--pipeline-base-dir", default="",
                        help="业务方评测流程根目录（快捷模式，如 /path/to/SDD评测/）")
    # --pipeline-eval-cmd 与 --pipeline-eval-sh 互斥: 前者承担 slash command 自动 wrap 语义,
    # 后者明确表达"纯 shell 命令,不触发任何 wrap/extract/warn 处理"
    pipeline_cmd_group = parser.add_mutually_exclusive_group()
    pipeline_cmd_group.add_argument("--pipeline-eval-cmd", default="",
                                    help="业务方评测命令（完整 shell 命令，如 'python3 <your_eval_script>.py --arg value'；"
                                         "slash command 即以 / 开头会自动包成 cosight -p；与 --pipeline-eval-sh 互斥）")
    pipeline_cmd_group.add_argument("--pipeline-eval-sh", default="",
                                    help="业务方评测命令（纯 shell 命令，**不触发**任何 slash-command 自动 wrap/extract/warn 处理）。"
                                         "不接受 cd X && 前缀；如需切换工作目录请用 --pipeline-base-dir。"
                                         "与 --pipeline-eval-cmd 互斥（同时传则 argparse 报错退出）。")
    parser.add_argument("--pipeline-score-agg", default="mean",
                        choices=("mean",),
                        help="管道分数聚合方式（固定 mean，使用所有 CASE 平均分作为整体分数）")
    # 广度优先优化参数
    parser.add_argument("--candidates-per-round", type=int, default=1,
                        help="广度优先：每轮候选数（默认 1，单候选即深度优先；>1 才启用广度候选比较）")
    parser.add_argument("--sub-rounds-per-candidate", type=int, default=1,
                        help="广度优先：每个候选的子优化轮次（默认 1）")
    parser.add_argument("--eval-runs-per-candidate", type=int, default=1,
                        help="广度优先：每个候选的独立评测次数，取平均分（默认 1）")
    parser.add_argument("--eval-runs", type=int, default=None,
                        help="静态模式每次评估独立跑 N 次取平均（默认 None=走 static_optimizer 默认 3，1=单次）")
    parser.add_argument("--enable-proposal-review", action="store_true",
                        help="启用提案审查阶段（proposal_review），检查过拟合和范围越界")
    # 提前剪枝参数
    parser.add_argument("--prune-threshold", type=float, default=20.0,
                        help="提前剪枝阈值：候选首次评测 < baseline - threshold 时跳过剩余 runs（默认 20.0）")
    parser.add_argument("--no-prune", action="store_true",
                        help="禁用提前剪枝")
    # 多 Skill / Agent 级别优化参数
    parser.add_argument("--optimization-mode", default="single",
                        choices=("single", "agent"),
                        help="优化模式：single=单 Skill 级别（默认），agent=Agent 级别（所有 Skill 联合评测+优化）")
    parser.add_argument("--skill-paths", default="",
                        help="多 Skill 路径列表（逗号分隔）。"
                             "eval agent 模式下：同时对多个 Skill 执行评测和优化（传完整路径）。"
                             "--mode static --agent-path 下：传 Skill 目录名列表，与 --agent-path 配合精确匹配子目录名（不传则扫描全部）。")
    parser.add_argument("--agent-name", default="",
                        help="Agent 名称（agent 模式下用于目录命名和报告生成）")
    # 多维度指标参数
    parser.add_argument("--eval-config", default="",
                        help="评估配置文件路径 (eval-config.yaml)，留空=走 examples/eval-config.yaml 或代码兜底")
    # .13+ 删除 --write-back-to-source flag（硬约束：禁止任何写回源路径）
    # 之前功能:任务结束后把 best_skill/ 覆盖式 copytree 到 --skill-path(s) 传入的原始路径
    # 删除原因:用户的源 SKILL.md 是受信任资产,优化器不应有覆盖权限（详见 skills/skill-optimize/SKILL.md）
    # 全局视角知识库(consume_lib) — 注入到 ProposalAgent prompt 顶部
    # 落 config.json 的 consume_lib_path 字段,run_optimize_agent 读取
    parser.add_argument("--consume-lib-path", default="",
                        help="全局视角知识库根目录(consume_lib)。注入到 ProposalAgent "
                             "一次性优化 prompt 顶部,作为跳出 case 局部修补的全局知识参考。"
                             "留空则不注入(零副作用)。")
    return parser.parse_args()


def run_loop(args):
    """主循环：支持深度优先（单线）和广度优先（多候选）两种模式"""
    workspace = Path(args.workspace).resolve()

    # 清理旧沙箱（上次崩溃遗留）
    SandboxManager.cleanup_stale()

    # ── 初始化指标收集器 ──
    metrics_config = _init_metrics_config(args)
    from metrics import MetricsCollector
    args.metrics_collector = MetricsCollector(metrics_config)

    # 初始化状态引擎
    state_engine = StateEngine(workspace, args)

    # 初始化或恢复状态
    if not state_engine.initialize():
        return

    # 将关键 CLI 参数持久化到 config，供子进程恢复
    # 始终更新 _args 和 eval_command（即使用户续跑，也应使用最新的 CLI 参数）
    state_engine.config["_args"] = _serializable_args(args)
    _cmds = _extract_pipeline_commands(args)
    if _cmds:
        state_engine.config["eval_command"] = _cmds[0]
        state_engine.config["eval_commands"] = _cmds
    # 从评测命令解析 case_ids（如 --req-id RAN-1,RAN-2），落盘便于审查/复现
    _inject_case_ids_into_config(state_engine.config, args)

    # ========== 用户显式传入的参数写入 config.json 顶层（本轮生效，不改默认） ==========
    # 只在命令行显式传了值时写入；不写默认值，避免覆盖后续运行的配置基线
    _user_kv = getattr(args, '_user_args', None) or {}  # argparse 未提供自动注册
    for _key, _attr in [
        ("max_rounds", "max_rounds"),
        ("break_threshold", "break_threshold"),
        ("eval_runs", "eval_runs"),
        ("eval_runs_per_candidate", "eval_runs_per_candidate"),
        ("candidates_per_round", "candidates_per_round"),
        ("expert_guidance", "expert_guidance"),
        ("consume_lib_path", "consume_lib_path"),
    ]:
        _val = getattr(args, _attr, None)
        if _val is not None and _val != "" and _val is not False:
            state_engine.config[_key] = _val

    # 把 pipeline 派生配置写入 config.json（替代原 pipeline-config.yaml）
    populate_pipeline_in_config(state_engine.config, args)
    state_engine.config_store.save(state_engine.config)

    # ── 初始化 .bak 备份 + 注册异常退出钩子(走一次 backup_skill_to_bak,force=False 跳过已存在)──
    _init_skill_bak(args, state_engine)

    breadth_mode = state_engine.is_breadth_first()

    # ── 独立 baseline 评测（广度优先和深度优先都需要）──
    baseline_score, baseline_runs, baseline_std = _evaluate_baseline(state_engine, args)

    # baseline 已达标（分数>0且>=目标）则直接跳过主循环
    if baseline_score is not None and baseline_score >= DEFAULT_TARGET_SCORE and baseline_score > 0:
        state_engine.record_current_progress("completed", "baseline 达标，跳过优化循环", round_num=0,
                        phase="finish")
        return

    if breadth_mode:
        n = state_engine.candidates_per_round()
        m = state_engine.sub_rounds_per_candidate()
        print(f"\n  🔄 广度优先模式已启用: 每轮 {n} 候选 x {m} 子轮")

    # 主循环
    while True:
        round_num = state_engine.current_round

        if state_engine.should_stop():
            break

        # 轮次上限控制（独立于 should_stop，避免基线评测占用轮次）
        if round_num > args.max_rounds:
            state_engine.status = "max_rounds"
            # 同步终止态到 task_state.json(权威源)
            if hasattr(state_engine, "phase_tracker"):
                state_engine.record_current_progress(
                    status="max_rounds",
                    detail=f"达到最大轮次 {args.max_rounds},任务终止",
                    round_num=round_num,
                    phase="finish",
                )
            break

        if breadth_mode:
            # ── 广度优先模式 ──
            ok = _run_breadth_round(state_engine, args, round_num,
                                    baseline_score, baseline_runs, baseline_std)
            if not ok:
                break

            # ── 关键修复:如果本轮采纳了新候选,必须以新基线重新跑 + 生成新 proposal ──
            # 否则下一轮读到的 baseline/proposal.md 还是 round 0 的,proposal gaps 全部过期
            best_round = state_engine.best_round
            # 判断是否还有下一轮(round_num+1 <= max_rounds),以及用户没显式禁用
            enable_re_baseline = getattr(args, "enable_re_baseline", True)
            has_next_round = state_engine.current_round < args.max_rounds
            if (best_round == round_num
                    and enable_re_baseline
                    and has_next_round
                    and not state_engine.should_stop()):
                print(f"\n  🔄 切换基线:round {round_num} 最佳已采纳,重新评测新基线 "
                      f"{state_engine.eval_runs_per_candidate()} 次 + 生成新提案")
                new_bl = _re_evaluate_as_new_baseline(state_engine, args, round_num)
                if new_bl[0] is not None:
                    baseline_score, baseline_runs, baseline_std = new_bl
                    print(f"  ✅ 新基线: {baseline_score:.1f} "
                          f"(σ={baseline_std:.1f}, runs={baseline_runs})")
                else:
                    print("  ⚠️ 新基线重跑失败,沿用内存中的 current_score")
                    baseline_score = state_engine.current_score
            else:
                if not (best_round == round_num):
                    print(f"  ℹ️ round {round_num} 未采纳新候选,基线不变")
                elif not has_next_round:
                    print(f"  ℹ️ round {round_num} 是最后一轮,跳过新基线重跑")
                elif not enable_re_baseline:
                    print("  ℹ️ --no-re-baseline 已设置,跳过新基线重跑")
        else:
            # ── 深度优先模式：全内联执行 ──
            ok = run_single_round(state_engine, args, round_num)
            if not ok:
                # 达标终止
                break

            # 分数回退保护：若本轮分数低于历史最佳，回退 Skill 并跳过优化
            current_score = state_engine.current_score
            best_score = state_engine.best_score
            best_round = state_engine.best_round
            if round_num > 0 and current_score < best_score:
                print(f"\n{'='*60}")
                print(f"  ⚠️ 分数回退：{best_score} → {current_score}（下降 {best_score - current_score:.1f}）")
                print(f"  回退到历史最佳版本（Round {best_round}）")
                _revert_to_best_skill(state_engine, best_round, round_num)
                state_engine.config["reverted_rounds"] = state_engine.config.get("reverted_rounds", []) + [round_num]
                state_engine.config_store.save(state_engine.config)
                state_engine.next_round()
                continue

        # ── 清理 /tmp 沙箱残留（不记 phase，纯机械）──
        try:
            SandboxManager.cleanup_stale()
        except Exception as e:
            print(f"  ⚠️ SandboxManager.cleanup_stale 失败: {e}")

        state_engine.next_round()

    # 生成总结
    final_score = state_engine.current_score
    best_score = state_engine.best_score
    best_round = state_engine.best_round
    total_rounds = state_engine.current_round
    status = state_engine.status

    print(f"\n{'='*60}")
    print("  🏁 Orchestrator 循环完成")
    print(f"{'='*60}")
    print(f"  总轮次: {total_rounds}")
    print(f"  最终状态: {status}")
    print(f"  最终得分: {final_score:.1f}")
    print(f"  最佳得分: {best_score:.1f} (Round {best_round})")
    print(f"{'='*60}")

    # ── 关键修复:任务结束 → 把最终 best_skill 复制回原始 skill 路径 ──
    # 业务方期望:round=N, run=2, candidates=2 的多轮迭代,未超过前一轮最佳则
    # 以前一轮最佳作为最终结果。best_skill/ 副本已存在,本段把最佳 SKILL.md
    # 写回 skill_registry 中登记的原始路径,用户拿到的就是优化结果。
    if _copy_newest_skill_for_test is not None:
        _copy_newest_skill_for_test(state_engine)
    else:
        print("  ⚠️ reports.py 无 _copy_newest_skill_for_test，跳过 skill 复制")

    # .13+ 删除:write_back_best_skill_to_source(args, agent_dir=...)
    # 硬约束:禁止把 best_skill/ 写回用户源路径（详见 skills/skill-optimize/SKILL.md）
    # 之前功能:任务结束后把 best_skill/ 覆盖式 copytree 到 --skill-path(s) 传入的原始路径
    # 删除原因:用户的源 SKILL.md 是受信任资产,优化器不应有覆盖权限

    # 生成最终总览报告
    try:
        state_engine.artifact_store.save_overview_report(state_engine.workspace)
    except Exception as e:
        print(f"  ⚠️ 总览报告生成失败: {e}")

    # 非诊断模式也生成审查报告
    # ── Bug 修复：同步 in-memory 状态到 config（task_state.json 极简化后，best_score/history 只存 in-memory）──
    state_engine.config["best_score"] = state_engine.best_score
    state_engine.config["best_round"] = state_engine.best_round
    state_engine.config["history"] = state_engine.history
    state_engine.config_store.save(state_engine.config)
    try:
        _save_final_review_report(state_engine)
    except Exception as e:
        print(f"  ⚠️ 审查报告生成失败: {e}")

    state_engine.record_current_progress("completed", "orchestrator 循环完成", round_num=state_engine.current_round,
                    phase="finish")

    # ── 任务成功 finish:清理 .bak + 清 config user_source_bak 字段 ──
    _finish_skill_bak(args)


# ── Agent 级别联合优化循环 ──────────────────────────────

def _init_metrics_config(args):
    """初始化指标配置，加载优先级：
    1. CLI --eval-config 指定路径(若指定,直接用,不渲染 user 占位符)
    2. 环境变量 SKILLX_EVAL_CONFIG
    3. MetricsConfig.load()(走 framework + user 渲染路径,推荐)
    4. 兜底:内嵌默认 task
    """
    import os as _os

    from metrics import MetricsConfig

    # 1. CLI 参数(显式指定时直接用,绕开 user 渲染,允许用户自己跑 jinja2)
    if getattr(args, 'eval_config', ''):
        return MetricsConfig.from_yaml(args.eval_config)

    # 2. 环境变量
    env_path = _os.environ.get('SKILLX_EVAL_CONFIG', '')
    if env_path and Path(env_path).exists():
        return MetricsConfig.from_yaml(env_path)

    # 3. 推荐:MetricsConfig.load() 会走 framework + user 渲染路径
    #    让 {{ user.score_extraction.structure }} 等占位符被渲染
    return MetricsConfig.load()

def _inject_case_ids_from_workflow_script(script_path: str):
    """从 workflow script 中提取 CASE ID 并注入环境变量"""
    case_prefix = os.environ.get("SKILLX_CASE_PREFIX", "CASE")
    pattern = rf'{case_prefix}-[\d]+'
    regex = rf'run_batch\.py\s+((?:{pattern}(?:\s*,\s*)?)+)'
    script = Path(script_path).resolve()
    if not script.exists():
        return
    try:
        content = script.read_text(encoding="utf-8")
        match = re.search(regex, content)
        if match:
            case_ids_str = match.group(1).replace(" ", "")
            case_ids = [r.strip() for r in case_ids_str.split(",") if r.strip()]
            os.environ["SKILLX_CASE_IDS"] = ",".join(case_ids)
            print(f"  [orchestrator] 从 workflow script 提取 CASE IDs: {case_ids}")
            print(f"  [orchestrator] 已设置 SKILLX_CASE_IDS={os.environ['SKILLX_CASE_IDS']}")
    except Exception as e:
        print(f"  [orchestrator] 警告: 无法从 workflow script 提取 CASE IDs: {e}")


def _ensure_round_dir(agent_dir: Path, round_num: int) -> Path:
    """确保 round_{N} 目录存在（即使空）。

    通用：在每轮循环开始时调用，避免后续步骤因前置失败导致目录不存在。
    返回目录路径。

    修复 2026-07-31:目录创建后立即调用 _populate_round_history 把之前轮次的所有
    result_diff_report_*.md 和 skill_diff_round_*.md 拷贝进来,作为目录初始化的
    一部分。这样:
      - round_1/ 创建 → 含 baseline diff(立即可用)
      - round_2/ 创建 → 含 baseline diff + round_1 diff + round_1 skill_diff(立即可用)
      - proposal-agent 在 USER PROMPT 引导下并发 Read 这些文件,看到完整历史
    """
    from state_engine.persistence import ensure_dir as _ed
    round_dir = agent_dir / f"round_{round_num}"
    _ed(str(round_dir))
    _populate_round_history(agent_dir, round_num)
    return round_dir


def _populate_round_history(agent_dir: Path, round_num: int) -> None:
    """round_N 目录初始化:把之前轮次的所有 result_diff_report_*.md 和 skill_diff_round_*.md 拷贝进来。

    修复 2026-07-31:原 _generate_diff_report 内的跨轮拷贝逻辑(round_num > 0 复制 baseline+prev_round)
    在 Evaluate 完成后才执行,导致 round_1 proposal-agent 启动时 round_1/ 还是空目录。
    本函数把这个初始化动作前移到目录创建时,保证 proposal-agent 在 USER PROMPT 引导下能并发 Read 到完整历史。

    拷贝策略(目录创建时一次性建立):
      - baseline/result_diff_report_baseline.md → round_N/result_diff_report_baseline.md
        (如果 baseline 已生成;否则 round_1 初始化时 baseline 还没生成就跳过)
      - 对每个 k in [1, round_num-1]:
        - round_k/result_diff_report_round_k.md → round_N/result_diff_report_round_k.md
          (前一轮的分数结果)
        - round_k/skill_diff_round_k.md → round_N/skill_diff_round_k.md
          (前一轮的 Skill 改动)

    Round 1 不会拷贝 result_diff_report_round_0.md(round_0 == baseline,已有 result_diff_report_baseline.md 副本)。
    Round 2+ 会拷贝 round_1 的 result_diff_report_round_1.md 和 skill_diff_round_1.md。
    """
    if round_num < 1:
        return
    round_dir = agent_dir / f"round_{round_num}"
    if not round_dir.exists():
        return

    # 1. 复制 baseline diff_report(如果已生成)
    if round_num >= 1:
        _copy_report_if_changed(
            agent_dir / "baseline" / "result_diff_report_baseline.md",
            round_dir / "result_diff_report_baseline.md",
            f"baseline diff_report → round_{round_num}/",
        )
        # baseline score-analyzer 失分诊断(独立文件,与 result_diff 对称)
        # 2026-08-10 ④ 修复:score_analyzer_report 随 diff_report 挪到 baseline 根,
        # 源路径从 baseline/run_1/ 改为 baseline/(否则 round_N 拷不到 → 提案读不到基线诊断)。
        _copy_report_if_changed(
            agent_dir / "baseline" / "score_analyzer_report_baseline.md",
            round_dir / "score_analyzer_report_baseline.md",
            f"baseline score_analyzer_report → round_{round_num}/",
        )

    # 2. 复制所有前序轮次的 result_diff_report_round_k.md 和 skill_diff_round_k.md
    for prev_round in range(1, round_num):
        # result_diff_report_round_{prev_round}.md(分数结果)
        _copy_report_if_changed(
            agent_dir / f"round_{prev_round}" / f"result_diff_report_round_{prev_round}.md",
            round_dir / f"result_diff_report_round_{prev_round}.md",
            f"round_{prev_round}/result_diff_report_round_{prev_round}.md",
        )
        # skill_diff_round_{prev_round}.md(Skill 改动)
        _copy_report_if_changed(
            agent_dir / f"round_{prev_round}" / f"skill_diff_round_{prev_round}.md",
            round_dir / f"skill_diff_round_{prev_round}.md",
            f"round_{prev_round}/skill_diff_round_{prev_round}.md",
        )
        # round_{prev_round} score-analyzer 失分诊断(独立文件,与 result_diff 对称)
        _copy_report_if_changed(
            agent_dir / f"round_{prev_round}" / f"score_analyzer_report_round_{prev_round}.md",
            round_dir / f"score_analyzer_report_round_{prev_round}.md",
            f"round_{prev_round}/score_analyzer_report_round_{prev_round}.md",
        )


def _ensure_candidate_dir(agent_dir: Path, round_num: int, cand_id: int) -> Path:
    """确保 round_{N}/candidate_{K} 目录存在（即使空）。"""
    from state_engine.persistence import ensure_dir as _ed
    cand_dir = agent_dir / f"round_{round_num}" / f"candidate_{cand_id}"
    _ed(str(cand_dir))
    return cand_dir
    return restored_count > 0


def run_agent_loop(args):
    """
    Agent 级别联合优化循环（端到端模式）。

    架构：一个 Agent = 一个 pipeline activity，包含多个 Skill。
    一次评测执行 = 所有 Skill 一起参与，产生端到端产物。

    目录结构：
    taskid_XXX/
    ├── config.json
    ├── progress.json
    ├── skills/                    ← 多个 Skill 文件（统一目录结构）
    │   ├── SkillA/SKILL.md + references/
    │   ├── SkillB/SKILL.md + references/
    │   └── ...
    ├── baseline/                  ← 基线评测产物（直接位于 workspace 根）
    │   └── run_N/score.json, data/, skills/
    ├── round_N/                   ← 轮次产物（直接位于 workspace 根）
    │   ├── score.json, report.md, data/, skills/
    ├── score_history.md
    └── 审查报告.md
    """
    skill_path_list = _parse_skill_paths(args.skill_paths)
    if not skill_path_list:
        print("ERROR: agent 模式需要 --skill-paths 参数")
        return

    # ── 初始化指标收集器 ──
    metrics_config = _init_metrics_config(args)
    from metrics import MetricsCollector
    args.metrics_collector = MetricsCollector(metrics_config)

    # ── 推导 Agent 名称：显式指定 > eval command 的 --sub-activity > Skill 父目录名 ──
    agent_name = getattr(args, 'agent_name', '') or ''
    if not agent_name:
        pipeline_eval_cmd = getattr(args, 'pipeline_eval_cmd', '') or ''
        m = re.search(r'--sub-activity\s+([^\s]+)', pipeline_eval_cmd)
        if m:
            agent_name = m.group(1)
    if not agent_name:
        agent_name = Path(skill_path_list[0]).parent.name
    agent_dir = Path(args.workspace).resolve()
    agent_dir.mkdir(parents=True, exist_ok=True)

    skill_names = [Path(sp).parent.name for sp in skill_path_list]

    print(f"\n{'='*60}")
    print(f"  Agent 级别联合优化: {agent_name}")
    print(f"  Skill 列表: {', '.join(skill_names)}")
    print(f"  工作区: {agent_dir}")
    print(f"{'='*60}")

    # ── 1. 拷贝所有 Skill 到 skill/{name}/ ──
    skills_dir = agent_dir / "skill"
    skills_dir.mkdir(parents=True, exist_ok=True)
    skill_registry = {}  # {skill_name: workspace_skill_path}
    # 🆕 origin_skill:不可变基线(从原始拷贝,永远不再修改)
    origin_skills_dir = agent_dir / "origin_skill"
    origin_skills_dir.mkdir(parents=True, exist_ok=True)
    for sp in skill_path_list:
        name = Path(sp).parent.name
        dest = skills_dir / name
        _copy_skill_files(sp, dest)
        skill_registry[name] = str(dest / "SKILL.md")
        # origin_skill 只在不存在时创建一次,后续任何逻辑不碰它(只读基线)
        origin_dest = origin_skills_dir / name
        if not origin_dest.exists():
            _copy_skill_files(sp, origin_dest)
        print(f"  ✓ {name} → {dest}")

    # ── 1. 创建空 config（占位）──
    # 占位逻辑：StateEngine.initialize() 会创建 config.json，这里只准备目录
    # 占位逻辑结束

    # ── 2. 创建单一 StateEngine（workspace = agent_dir）──
    # 用第一个 Skill 初始化，兼容现有接口
    first_sp = skill_path_list[0]
    first_ws_skill = skill_registry[skill_names[0]]
    s_args = _make_skill_args(args, first_ws_skill)
    s_args.skill_paths = skill_path_list  # 传递所有 Skill 路径
    eng = StateEngine(agent_dir, s_args)
    eng.initialize()

    # 记录启动进度（写到 task_state.json 的 current 段）
    eng.record_current_progress("starting", "agent loop 启动", round_num=-1, phase="init")

    # ── 2.5. 把 pipeline 派生配置写入 config.json（替代原 pipeline-config.yaml）──
    # 先注入 case_ids(从 --req-id 等参数解析),便于后续 analyze_* 透传到 ScoreAnalyzerAgent
    _inject_case_ids_into_config(eng.config, args)
    populate_pipeline_in_config(eng.config, args)
    # 全局视角知识库路径(consume_lib) — 落顶层供 run_optimize_agent 读取
    _clp = (getattr(args, 'consume_lib_path', '') or '').strip()
    if _clp:
        eng.config["consume_lib_path"] = _clp
    eng.config_store.save(eng.config)

    # ── 初始化 .bak 备份 + 注册异常退出钩子 ──
    _init_skill_bak(args, eng)

    # ── 2.6 保存权威 baseline 快照(best_round==0 时每轮起点的重置源，不可变)──
    # 修复:确保 baseline/skill 存在；best_round==0 时修复 1 从它重置起点
    _base_skill_src = agent_dir / "skill"
    _base_skill_dst = agent_dir / "baseline" / "skill"
    if _base_skill_src.exists() and not _base_skill_dst.exists():
        import shutil as _shutil_base
        _base_skill_dst.parent.mkdir(parents=True, exist_ok=True)
        _shutil_base.copytree(str(_base_skill_src), str(_base_skill_dst))
        for _f in _base_skill_dst.rglob("*"):
            _f.chmod(0o555 if _f.is_dir() else 0o444)
        print(f"  📦 权威 baseline 快照已保存: {_base_skill_dst}")

    # ── 3. 基线评测（一次 pipeline 执行，所有 Skill 一起）──
    bl_args = _make_skill_args(args, first_ws_skill)
    bl_args.skill_paths = skill_path_list
    print(f"\n  📊 执行基线评测（端到端，{len(skill_path_list)} 个 Skill 一起）")
    bl_score, bl_runs, bl_std, bl_gaps = _evaluate_baseline_agent(eng, bl_args)
    # bl_gaps 在基线失败时可能不是 list（如 float/None），防御性取长度
    bl_gaps_count = len(bl_gaps) if isinstance(bl_gaps, list) else 0
    print(f"  基线分数: {bl_score:.1f} | gaps: {bl_gaps_count}")

    # 写 baseline/proposal.md(无 LLM,纯代码从 bl_gaps + score_baseline.json 渲染)
    # 用户契约:基线阶段也要产 proposal.md,供 R1 proposal-agent 参考
    try:
        _write_baseline_proposal_md(agent_dir, bl_gaps if isinstance(bl_gaps, list) else [], bl_score)
    except Exception as _e_bp:
        print(f"  ⚠️ baseline/proposal.md 写入失败: {_e_bp}")

    # 写 baseline/result_diff_report_baseline.md(综合 diff 报告,baseline→Round 1 时 proposal-agent 必读)
    # 修复 v2026-07-24:同步 round_N/result_diff_report.md 路径(单轮对比模式 + F1 徽章 + 4 段证据)
    try:
        _baseline_diff_path = _generate_diff_report(agent_dir, round_num=0, best_round=0, best_candidate_id=0)
        if _baseline_diff_path:
            print(f"  ✅ 已生成 {Path(_baseline_diff_path).relative_to(agent_dir)}")
    except Exception as _e_bdr:
        print(f"  ⚠️ baseline/result_diff_report_baseline.md 写入失败: {_e_bdr}")

    # ── 4. 扩展 StateEngine config 以 Agent 级字段 ──
    eval_commands = _extract_pipeline_commands(args)
    eng.merge_config({
        "agent_name": agent_name,
        "optimization_mode": "agent",
        "skill_names": skill_names,
        "skill_paths": skill_path_list,
        "skill_registry": skill_registry,
        "baseline_score": bl_score,
        "aggregate_baseline": bl_score,
        "eval_command": eval_commands[0] if eval_commands else "",
        "eval_commands": eval_commands,
        "_args": _serializable_args(args),
    })

    # baseline 达标检查
    if bl_score >= DEFAULT_TARGET_SCORE and bl_score > 0:
        print("\n  ✅ 基线分数已达目标！跳过优化循环")
        eng.record_current_progress("completed", "agent 基线达标", phase="finish")
        return

    # ── 初始化"当前全局最佳"为基线(running max 起点)──
    # 后续每轮比较都是"score > 当前全局最佳",而非常量基线
    # 不初始化会导致 R1 决策用 0 比较,任何正分都误判为 adopted
    # 兼容断点续跑:若已有 best_score,取 max(已有, baseline)
    eng.best_score = max(eng.best_score, bl_score) if eng.best_score > 0 else bl_score
    if eng.best_round < 0:
        eng.best_round = 0  # 0 = "尚无 round 被采纳" (区别于 -1 未初始化)
        eng.best_candidate_id = -1

    # ── 5. 主循环：基于基线的平行候选 → 选最佳 → 持久化优化 ──
    candidates_per_round = getattr(args, 'candidates_per_round', 1) or 1
    eval_runs_per_candidate = getattr(args, 'eval_runs_per_candidate', 1) or 1

    # 跨轮增量：记录当前全局最佳候选，round 2+ 起始时用于继承 Skill 状态
    # 注:不再用局部变量 _last_best_candidate_id,改用 eng.best_candidate_id
    #     这样"继承源"始终是 running max 的最佳 round 的最佳候选,而非仅上一轮

    # 跳过模式: SKILLX_START_ROUND=2 直接进 round 2(用于断点续跑/调试)
    import os as _os_skip
    _start_round = int(_os_skip.environ.get("SKILLX_START_ROUND", "1"))
    if _start_round > 1:
        print(f"  ⏭️  SKILLX_START_ROUND={_start_round}, 跳过 round 1-{_start_round-1}")

    for round_num in range(_start_round, args.max_rounds + 1):
        print(f"\n{'='*60}")
        print(f"  Round {round_num}: Agent 联合评测 + 优化")
        print(f"{'='*60}")
        print(f"  候选数: {candidates_per_round}, 每候选评测次数: {eval_runs_per_candidate}")

        # ── 起点策略:round > 1 时 workspace skill 由下方 inherit 块(L1568+)决定 ──
        #   - baseline_anchored=False(默认):继承 eng.best_round 的 candidate skill
        #   - baseline_anchored=True:锚定 round_1/round_1_before_skill(等价 baseline 起点)
        # round_1 保持原始 baseline 状态(eng.best_round==0 还没 best)
        # best_skill/ 由 _save_best_skill 在任务结束时从 round_{best_round}/candidate_{best_id}/skill/
        # 直接拷贝,与 workspace skill/ 解耦。
        if round_num > 1:
            if eng.best_round > 0 and eng.best_candidate_id > 0:
                print(f"  ℹ️  Round {round_num}: 当前最佳来自 round {eng.best_round} "
                      f"candidate {eng.best_candidate_id}（已通过 prompt 注入 proposal-agent,"
                      f"workspace skill 起点由下方 inherit 块决定）")
            else:
                print(f"  ℹ️  Round {round_num}: 当前最佳仍是基线（best_round={eng.best_round}）")

        # ── 通用：先初始化 round_x 目录框架（即使本轮无产物，目录也存在）──
        # 避免"优化器失败 → 候选 skill 不存在 → 跳过 → 目录全无"的混乱
        _ensure_round_dir(agent_dir, round_num)
        # 同时为每个候选预先建好空目录
        for _pre_cid in range(1, candidates_per_round + 1):
            _ensure_candidate_dir(agent_dir, round_num, _pre_cid)

        # 本轮使用基线 gaps（所有候选共享同一份基线 gaps）
        round_gaps = best_candidate_gaps if round_num > 1 else bl_gaps

        best_candidate_score = -1
        best_candidate_id = -1
        best_candidate_gaps = []
        all_candidate_scores = {}

        # apply 步骤已合并：LLM 直接改 candidate_skill_root 副本,eval 读副本。
        # 无需再备份/恢复用户源(v2.13+ 简化路径)。

        # 提前创建 ScoreAnalyzerAgent：每次 run_evaluation 后立即调 analyze_run 写 score.json，
        # 否则后续"读 score.json"会拿到 0.0（修复候选评测固定 0 分 bug）。
        # 复用 L218/L517 已加载的 metrics_config(framework + user 渲染版),
        # 不要再调 default_eval_config()(会丢业务方在 user-config.yaml 的 score_extraction 约束)
        from scorer import ScoreAnalyzerAgent
        _candidate_metrics_config = args.metrics_collector._config
        candidate_analyzer = ScoreAnalyzerAgent(_candidate_metrics_config)

        # ── Solution C:round > 1 且 history 非空时,重生 baseline/proposal.md ──
        # 在 candidates 生成之前调用,让 ApplyAgent 读到重生后的 proposal
        try:
            _regenerate_proposal_with_history(eng, args, round_num, candidate_analyzer)
        except Exception as _e_solc:
            print(f"  [Solution C] 调用异常(继续执行,不影响主流程): {_e_solc}")

        # 收集各候选的 run_scores（用于写 round_N/score.json 和 candidate_K_score.json）
        all_candidate_runs: dict = {}
        # 收集各候选的所有 run gaps（用于写 candidate_K_score_analysis.md）
        all_gaps_for_candidates: dict = {}

        # ── 生成 result_diff_report.md(综合 diff 报告,LLM 一次 Read 看全部信息) ──
        # 修复 v2026-07-24:调用时机移到候选评测+skill_diff_round_N.md 写入完成后(否则 phase3-eval/ 还没归档,函数 return "")
        # 实际调用见下方 line 1644 区域

        # ── 改写 workspace skill 起点 ──
        # 行为分两轨(round > 1 才有区别):
        #   - 默认(baseline_anchored=False):每轮从 eng.best_round 的 candidate_k 继承
        #   - baseline_anchored=True:每轮都从 round_1/round_1_before_skill 锚定 baseline
        # round_1 保持原始 baseline 状态(eng.best_round == 0 还没 best)
        # ── 反过拟合:best_round == 0 是 baseline,大于 0 用 best_round 的 skill ──
        try:
            import shutil as _shutil_inherit
            from orchestrators.workspace import is_baseline_anchored
            _ws_skill_root = agent_dir / "skill"
            _inherit_from = None
            _inherit_label = "baseline(原始)"
            _baseline_anchored = is_baseline_anchored()

            # baseline-anchored 模式:锚定 R1 before_skill(== baseline 起点)
            # ★ round_num > 1:R1 时 agent_dir/skill 已经是初始化 baseline,无需 R1 before_skill(R1 snapshot
            #   在下方 L1611 才开始写);R1 自然用初始化 baseline,与默认行为等价无副作用。
            #   改为 > 1 同时修 2 个 bug:(1)R1 开关 ON 时不再触发 "R1 before_skill 不存在" 死循环;
            #   (2)R2+ 才严格读 R1 before_skill 锚定 baseline(语义清晰)。
            if _baseline_anchored and round_num > 1:
                _r1_before = agent_dir / "round_1" / "round_1_before_skill" / "skill"
                if _r1_before.exists():
                    _inherit_from = _r1_before
                    _inherit_label = "baseline(anchored, from R1 before_skill)"
                else:
                    # ★ fail-closed:baseline-anchored 模式下 anchor 必须存在
                    raise FileNotFoundError(
                        f"baseline_anchored=true 但 {_r1_before} 不存在;"
                        f"需先跑过 round_1 产生 before_skill 后再启用此开关"
                    )

            # 默认链式继承(开关 OFF 时走这条) — 权威起点，无条件重置
            # best_round > 0 → 最佳候选 skill；best_round == 0 → 权威 baseline 快照
            # 修复:防止 workspace skill 被上一轮未采纳候选污染，每轮强制从最佳轮出发
            if _inherit_from is None:
                if eng.best_round > 0 and eng.best_candidate_id > 0:
                    _best_skill_src = agent_dir / f"round_{eng.best_round}" / f"candidate_{eng.best_candidate_id}" / "skill"
                    if _best_skill_src.exists():
                        _inherit_from = _best_skill_src
                        _inherit_label = f"best_R{eng.best_round}_c{eng.best_candidate_id}(score {eng.best_score:.2f})"
                else:
                    # best_round == 0 → 权威 baseline 快照(baseline/skill/，兜底 origin_skill/)
                    _base_src = agent_dir / "baseline" / "skill"
                    if not _base_src.exists():
                        _base_src = agent_dir / "origin_skill"
                    if _base_src.exists():
                        _inherit_from = _base_src
                        _inherit_label = "baseline(权威快照)"
            if _inherit_from is not None:
                if _ws_skill_root.exists():
                    _shutil_inherit.rmtree(str(_ws_skill_root))
                _shutil_inherit.copytree(str(_inherit_from), str(_ws_skill_root))
                print(f"  📥 round_{round_num}: workspace skill 起点继承自 {_inherit_label}")
        except FileNotFoundError as _e_anchor:
            # ★ baseline_anchored 模式下 anchor 缺失:R2+ 找不到 R1 before_skill
            # 必须 re-raise,不能静默回退到 agent_dir/skill 旧值(可能是 best_skill,
            # 违反"永远 baseline"语义)。原始 except 把异常吞掉,实测会沿用旧 best
            # 当 baseline 起点继续 snapshot/candidate,语义被破坏。
            if _baseline_anchored and round_num > 1:
                print("  ❌ baseline_anchored 模式 anchor 缺失,fail-closed 终止本轮")
                print(f"     {_e_anchor}")
                raise  # 必须 re-raise,否则 fail-open
            print(f"  ⚠️ workspace skill 起点继承失败(回退到 baseline): {_e_anchor}")
        except Exception as _e_inherit:
            print(f"  ⚠️ workspace skill 起点继承失败(回退到 baseline): {_e_inherit}")

        # 写本轮 before 快照（agent_dir/skill/ 整目录 = 本轮起点 = baseline 或上轮最佳）
        # 修复:before 快照不可变 —— 已存在则跳过(不 rmtree 覆盖)，生成后 chmod 只读
        try:
            import shutil as _shutil
            _before_dest = agent_dir / f"round_{round_num}" / f"round_{round_num}_before_skill" / "skill"
            _before_ready = _before_dest.exists() and any(_before_dest.rglob("SKILL.md"))
            if not _before_ready:
                _before_dest.parent.mkdir(parents=True, exist_ok=True)
                _ws_skill_root = agent_dir / "skill"
                if _ws_skill_root.exists():
                    _shutil.copytree(str(_ws_skill_root), str(_before_dest))
                    _log_write(_before_dest, f"round_{round_num}_before_skill_snapshot", agent_dir)
                    # 不可变:文件 444 / 目录 555，防止中途被覆盖
                    for _f in _before_dest.rglob("*"):
                        _f.chmod(0o555 if _f.is_dir() else 0o444)
            else:
                print(f"  ⏭️  round_{round_num}_before_skill 已存在(只读快照)，跳过重新生成")
        except Exception as _e:
            print(f"  ⚠️ 写 before 快照失败: {_e}")

        for cand_id in range(1, candidates_per_round + 1):
            print(f"\n  ▶ 候选 {cand_id}/{candidates_per_round}")

            # ── 步骤 0：把当前 skill 状态（baseline 或上轮最佳）拷贝到 candidate 副本
            # 单步子 agent 流程：在 baseline/round_{N}_candidate_{K}/ 下做提案生成 + 优化编辑,
            # 完成后整目录 mv 到 round_{N}/candidate_{K}/，eval 读最终位置。
            # 这样 baseline 目录完整记录"提案在哪生成、Skill 副本在哪被改"，
            # round_N/candidate_K/ 是干净的最终态（与 baseline 解耦）。
            _final_cand_dir = agent_dir / f"round_{round_num}" / f"candidate_{cand_id}"
            _baseline_cand_dir = agent_dir / "baseline" / f"round_{round_num}_candidate_{cand_id}"
            _baseline_cand_skill = _baseline_cand_dir / "skill"

            # 清掉旧 baseline_cand_dir(可能是上轮残留或重试用)
            if _baseline_cand_dir.exists():
                shutil.rmtree(str(_baseline_cand_dir))
            # 也清掉 round_N/candidate_K(避免 mv 目标冲突)
            if _final_cand_dir.exists():
                shutil.rmtree(str(_final_cand_dir))

            _ws_skill_root = agent_dir / "skill"
            if not _ws_skill_root.exists():
                print(f"  ⚠️ workspace skill 不存在: {_ws_skill_root},跳过候选 {cand_id}")
                continue

            # 拷贝到 baseline/round_{N}_candidate_{K}/skill(子 agent 在此工作)
            shutil.copytree(str(_ws_skill_root), str(_baseline_cand_skill))
            _log_write(_baseline_cand_skill, f"round_{round_num}_candidate_{cand_id}_skill_setup", agent_dir)
            # 兼容下游读取:用 _baseline_cand_skill 走 optimize,后续 mv
            candidate_skill_root = _baseline_cand_skill
            cand_dir = _baseline_cand_dir

            # ── 步骤 1：1 候选 = 1 次 ApplyAgent，一次性处理所有 Skill ──
            # 重构后:统一走 invoke_apply_agent_multi（apply_agent.py 共享模块）,
            # 由它统一生成 apply_status.json + 修改 candidate_K/skill/ + fail-fast 跳过逻辑。
            # (过程性 print 已删除,符合 §13 静默执行;LLM 工作过程不向 stdout 暴露)

            # ── 完整历史回顾 (Solution B 增强):round > 1 时,把**所有轮次**分数+最佳标注+上轮 mods 注入 prompt,
            #    避免 LLM 只看 round_prev(可能 miss 早期 best 决策)──
            _prev_failure_block = ""
            if round_num > 1:
                try:
                    _hist = eng.history
                    if _hist:
                        _baseline_score = eng.baseline_score

                        # ── 1. 完整历史时间线(round 1 ~ round N-1)──
                        _history_table_lines = ["| Round | Score | 增量 vs 基线 | 决策 | best_candidate_id |", "|---|---|---|---|---|"]
                        _best_ever_score = _baseline_score
                        _best_ever_round = 0
                        for _h in _hist:
                            _hr = _h.get("round", "?")
                            _hs = _h.get("score", 0)
                            _hd = _h.get("vs_baseline_delta", 0)
                            _hdecision = _h.get("decision", "?")
                            _hbest = _h.get("best_candidate_id", "?")
                            if _hs > _best_ever_score:
                                _best_ever_score = _hs
                                _best_ever_round = _hr
                            _history_table_lines.append(
                                f"| R{_hr} | {_hs:.2f} | {_hd:+.2f} | {_hdecision} | c{_hbest} |"
                            )
                        # 当前全局最佳(running max)= eng.best_score
                        _history_table = "\n".join(_history_table_lines)

                        # ── 2. 上轮 per-case 分数(详细分析 REGRESSION/Improved)──
                        _prev = _hist[-1]
                        _prev_round = _prev.get("round", round_num - 1)
                        _prev_decision = _prev.get("decision", "unknown")
                        _prev_score = _prev.get("score", 0)
                        _prev_delta = _prev.get("vs_baseline_delta", 0)
                        _prev_mods = _prev.get("modifications_summary", [])

                        # 拿"实际 best"的 per-case 分数(不是 last round)
                        # 找 best_score 对应 round 的 case_scores
                        _best_round_data = None
                        for _h in _hist:
                            if _h.get("score", 0) == eng.best_score:
                                _best_round_data = _h
                                break
                        # fallback:如果没找到(scores 相等),用最近一轮
                        if _best_round_data is None:
                            _best_round_data = _hist[-1]

                        _prev_case_scores = _best_round_data.get("case_scores", {}) or {}
                        _baseline_case_scores = _best_round_data.get("baseline_case_scores", {}) or {}

                        _per_case_table = ""
                        _regression_cases = []
                        _improved_cases = []
                        if _prev_case_scores and _baseline_case_scores:
                            _per_case_table = "| case_id | baseline | best_round | Δ | 状态 |\n|---|---|---|---|---|\n"
                            for _cid in sorted(set(_prev_case_scores) | set(_baseline_case_scores)):
                                _b = _baseline_case_scores.get(_cid, 0)
                                _p = _prev_case_scores.get(_cid, 0)
                                _d = _p - _b
                                if _d < -1.0:
                                    _status = "⚠️ **REGRESSION**"
                                    _regression_cases.append((_cid, _b, _p, _d))
                                elif _d > 1.0:
                                    _status = "✅ improved"
                                    _improved_cases.append((_cid, _b, _p, _d))
                                else:
                                    _status = "→ stable"
                                _per_case_table += f"| {_cid} | {_b:.2f} | {_p:.2f} | {_d:+.2f} | {_status} |\n"

                        # 上轮 mods 摘要
                        _mods_text = ""
                        for _m in _prev_mods[:8]:
                            _mods_text += (
                                f"  - M{_m.get('index', '?')} [{_m.get('action', '?')}] "
                                f"{_m.get('file', '?')} → {_m.get('section', '?')}\n"
                                f"    reason: {(_m.get('reason') or '')[:120]}\n"
                            )
                        if not _mods_text:
                            _mods_text = "  - (上轮无 modifications 记录)\n"

                        # 上轮产物路径
                        _prev_round_dir = agent_dir / f"round_{_prev_round}"
                        _prev_best_cand = _prev.get("best_candidate_id") or 1
                        _prev_summary_path = _prev_round_dir / f"candidate_{_prev_best_cand}" / "optimization_summary.md"
                        _prev_data_dir = _prev_round_dir / f"candidate_{_prev_best_cand}" / "data"

                        _per_case_block = ""
                        if _per_case_table:
                            _per_case_block = (
                                f"\n### Per-case 分数对比(本轮 baseline 视角)\n{_per_case_table}\n"
                                f"- ⚠️ **REGRESSION cases**(本轮重点修复,必须分析根因): "
                                f"{', '.join(f'{c[0]}({c[1]:.1f}→{c[2]:.1f}, {c[3]:+.1f})' for c in _regression_cases) or '无'}\n"
                                f"- ✅ **Improved cases**(本轮**禁止伤及**): "
                                f"{', '.join(f'{c[0]}({c[1]:.1f}→{c[2]:.1f}, {c[3]:+.1f})' for c in _improved_cases) or '无'}\n"
                                f"- 上轮产物路径(可直接 Read):\n"
                                f"  - summary: `{_prev_summary_path}`\n"
                                f"  - 评测数据: `{_prev_data_dir}`(含 phase3-eval results/*.json)\n"
                                f"  - 起点 Skill 副本: `{_prev_round_dir}/candidate_{_prev_best_cand}/skill/`\n\n"
                            )

                        # ── 3. 组装完整 history block(突出"当前最佳分数 + 上一轮 mods")──
                        _prev_failure_block = (
                            f"agent_name: 需求分析Agent\n"
                            f"\n## 📊 完整历史时间线(round 1 ~ round {_prev_round})\n"
                            f"{_history_table}\n"
                            f"\n**🏆 当前全局最佳**: R{eng.best_round} 候选 c{eng.best_candidate_id} = **{eng.best_score:.2f}** "
                            f"(基线 {_baseline_score:.2f}, 增量 {eng.best_score - _baseline_score:+.2f})\n"
                            f"\n## ⚠️ 上轮(round {_prev_round})失败回顾\n"
                            f"- 上轮决策: **{_prev_decision}** "
                            f"({('分数提升, 已采纳' if _prev_decision == 'adopted' else '分数未提升, 保留旧基线')})\n"
                            f"- 上轮最佳候选分数: **{_prev_score:.2f}** "
                            f"(基线 {_baseline_score:.2f}, 增量 {_prev_delta:+.2f})\n"
                            f"- 上轮执行的 modifications 摘要(前 {min(8, len(_prev_mods))} 条):\n"
                            f"{_mods_text}"
                            f"{_per_case_block}"
                            f"\n## 🎯 本轮核心目标(按优先级)\n"
                            f"  1. **保住当前最佳**({eng.best_score:.2f},来自 R{eng.best_round}): 任何修改必须**先 Read per-case 对比表**,自检是否会伤害 'Improved cases'\n"
                            f"  2. **修复 REGRESSION cases**:分析根因(读 phase3-eval JSON 找差异),针对性改\n"
                            f"  3. **避免重复上轮失败**:禁止 file + section 组合相同的 mod\n"
                            f"  4. 调整方向必须**有可验证的根因**支撑(不要凭感觉换)\n\n"
                        )
                except Exception as _e_prev:
                    _prev_failure_block = ""

            # ── 读 Stage 4 self_check verdict（fail-fast 跳过 apply）──
            # ⚠️ 临时禁用(2026-06-18):Stage 4 整体注释,verdict 强制 None,ApplyAgent 不再 skip。
            # 取消下面注释块即可恢复。
            _self_check_verdict = None
            # try:
            #     import json as _jsc
            #     _sc_path = agent_dir / "baseline" / "_proposal" / "stage_4_self_check.json"
            #     if _sc_path.exists():
            #         _self_check_verdict = _jsc.loads(
            #             _sc_path.read_text(encoding="utf-8")
            #         ).get("verdict")
            # except Exception:
            #     _self_check_verdict = None

            # ── Phase: apply ──
            try:
                eng.record_phase_start(round_num, "apply")
            except Exception:
                pass
            # 调优化 agent（v2 单阶段一次性:context + gaps + mods + Edit + summary 落盘）
            # 取代原 invoke_apply_agent_multi（已删除 apply_agent.py 薄壳）
            # 单步子 agent 流程：在 baseline/round_{N}_candidate_{K}/ 下工作,
            # cand_dir 显式传入,optimization_summary.md 落到 baseline 侧,整目录再 mv 到 round_N/
            run_optimize_agent(
                candidate_skill_root=candidate_skill_root,
                skill_path_list=skill_path_list,
                data_dir=agent_dir / "baseline" / "run_1" / "data",
                candidate_id=cand_id,
                round_num=round_num,
                modification_budget=_compute_modification_budget(round_num),
                extra_inputs=_prev_failure_block,
                max_attempts=3,
                cand_dir=cand_dir,
                best_round=eng.best_round,
                run_count=int(eval_runs_per_candidate or 1),
            )
            # 🆕 2026-08-03 实施 A:每个 round apply 完立即 cp 最新 LLM 修改的 skill 到 consume_lib
            # ⚠️ 必须在 eng.current_round = round_num 之后触发(避免 _cur_round=0 跳过)
            # 触发放 line 2910 之后的 mv 阶段(mv 完成后 + eng.current_round 已更新)
            # 业务方跑 /sdd-eval 时立即能测到本 round 的修改,不用等任务整体跑完
            try:
                eng.record_phase_complete(round_num, "apply")
            except Exception:
                pass

            # ── 单步子 agent 流程收尾：把 baseline/round_{N}_candidate_{K}/ 整目录 mv 到 round_{N}/candidate_{K}/
            # mv 后 _baseline_cand_dir 不存在,避免下次重跑误用旧工作区
            try:
                if _baseline_cand_dir.exists():
                    shutil.move(str(_baseline_cand_dir), str(_final_cand_dir))
                    _log_write(_final_cand_dir, f"round_{round_num}_candidate_{cand_id}_finalized", agent_dir)
            except Exception as _e_mv:
                print(f"  ⚠️ mv baseline→round 失败: {_e_mv},继续用 baseline 侧目录")

            # 写 round_N/proposal.md + round_N/skill_diff_round_N.md(用户契约:每轮提案 + 全 skill diff)
            try:
                _write_round_proposal_md(agent_dir, round_num, candidate_id=cand_id,
                                         run_count=int(eval_runs_per_candidate or 1))
            except Exception as _e_prop:
                print(f"  ⚠️ round_{round_num}/proposal.md 写入失败: {_e_prop}")
            try:
                _write_round_diff_md(agent_dir, round_num, skill_names, candidate_id=cand_id)
            except Exception as _e_diff:
                print(f"  ⚠️ round_{round_num}/skill_diff_round_{round_num}.md 写入失败: {_e_diff}")

            # ── result_diff_report_round_N.md 推迟到 Evaluate 完成后生成 ──
            # 修复 2026-07-30:原 line 1862 在 Apply 后立即调用,但此时 round_N/candidate_K/run_1/score.json
            # 还未生成( Evaluate 在 line 1924 才发生),函数只能 fallback 到 baseline/run_1/score.json,
            # 导致 result_diff_report_round_N.md 实际是 baseline 数据的副本,Round 2 proposal-agent
            # 读不到上一轮真实 F1/失分点 → 演化循环被削弱。
            # 修复方案:把 _generate_diff_report 调用推迟到所有候选 Evaluate + analyze_run + score.json
            # 合成完成之后(下方 line ~2099 区域),此时 score.json 已存在,函数能找到 Round N 真实数据。

            # ── 同步 candidate → workspace skill(评测 agent 读取,保留)──
            # 2026-08-03 修复:eval 依赖 workspace skill = candidate，apply 后必须同步
            # 修复:源路径同步(_sync_candidate_to_original)已移到 round 尾部 adopted 判定后，
            #     not_adopted 的失败改动不再污染源路径
            _final_skill_root_for_sync = _final_cand_dir / "skill"
            if _final_skill_root_for_sync.exists():
                try:
                    _sync_candidate_to_workspace_skill(agent_dir, _final_skill_root_for_sync)
                except Exception as _e_ws:
                    print(f"  ⚠️ 同步 candidate → workspace skill 失败: {_e_ws}")
            else:
                print(f"  ⚠️ _final_cand_dir/skill 不存在,跳过 workspace 同步: {_final_skill_root_for_sync}")

            # ── 步骤 2：apply 已合并，LLM 直接改 candidate_skill_root；eval 读此副本 ──
            # mv 后 candidate_skill_root 指向新位置 round_N/candidate_K/skill
            candidate_skill_root = agent_dir / f"round_{round_num}" / f"candidate_{cand_id}" / "skill"
            if not candidate_skill_root.exists():
                print(f"  ⚠️ 候选 {cand_id} skill 目录不存在: {candidate_skill_root}，跳过")
                all_candidate_scores[cand_id] = 0.0
                continue
            # apply 步骤已合并：LLM 直接改 candidate_skill_root，eval 读 workspace 副本路径
            # apply 已合并:LLM 直接改 candidate_skill_root,eval 读此副本(无 user source 覆盖)
            print(f"  📋 候选 {cand_id} skill_root: {candidate_skill_root}（eval 直接读此副本）")

            run_scores = []
            all_gaps_for_avg = []
            # eval 读 candidate_skill_root 第一个 Skill 的 SKILL.md（替代原 user source 路径）
            first_candidate_skill = next(
                (candidate_skill_root / Path(sp).parent.name / "SKILL.md"
                 for sp in skill_path_list
                 if (candidate_skill_root / Path(sp).parent.name / "SKILL.md").exists()),
                None,
            )
            if first_candidate_skill is None:
                print(f"  ⚠️ 候选 {cand_id} skill_root 下无任何 SKILL.md，跳过")
                all_candidate_scores[cand_id] = 0.0
                continue
            # 保存原 skill_path，eval 后还原（避免污染后续 round / baseline 评测）
            _saved_eng_skill_path = eng.skill_path
            _saved_args_skill_path = args.skill_path
            # 同步给 state_engine + args，让 subprocess_mgr 读 ${SKILL_PATH} 解析到候选副本
            eng.skill_path = str(first_candidate_skill)
            args.skill_path = str(first_candidate_skill)
            try:
                # ── 2026-08-03 修复:评测前强制同步本轮 candidate skill ──
                # apply 后的 sync 可能因中断/异常未生效;评测前再强制同步一次到
                # workspace skill(taskid/skill/),保证评测 agent 读到本轮 candidate。
                # 修复:源路径同步已移到 adopted 判定后,not_adopted 不再污染源路径
                try:
                    _eval_cand_skill = agent_dir / f"round_{round_num}" / f"candidate_{cand_id}" / "skill"
                    if _eval_cand_skill.exists():
                        _sync_candidate_to_workspace_skill(agent_dir, _eval_cand_skill)
                except Exception as _e_sync2:
                    print(f"  ⚠️ 评测前强制同步 candidate skill 失败: {_e_sync2}")

                for run_idx in range(1, eval_runs_per_candidate + 1):
                    eval_args = _make_skill_args(args, first_candidate_skill)
                    eval_args.skill_paths = skill_path_list
                    eval_args.eval_mode = "candidate"
                    eval_args.candidate_id = cand_id
                    eval_args.eval_run_index = run_idx

                    # 过程性 print 已删除,符合 §13 静默执行
                    eval_result = run_evaluation(eng, eval_args, round_num)

                    # 修复 0 分 bug：run_evaluation 仅归档 data/，不写 score.json。
                    # 必须在本次 run 后立即调 analyze_run 把 score.json 写出来，
                    # 否则下方的"读 score.json"会拿到 0.0（与基线路径保持一致）。
                    cand_run_dir = agent_dir / f"round_{round_num}" / f"candidate_{cand_id}" / f"run_{run_idx}"
                    if cand_run_dir.exists():
                        # ── Phase: score ── （run_evaluation 已记录 evaluate,此处仅打 score）
                        try:
                            eng.record_phase_start(round_num, "score")
                        except Exception:
                            pass
                        try:
                            _case_ids = eng.config.get("case_ids") or None
                            from orchestrators.workspace import _analyze_run_with_evidence_retry as _analyze_retry
                            _analyze_retry(
                                candidate_analyzer, cand_run_dir, round_num, cand_id, run_idx,
                                case_ids=_case_ids,
                            )
                        except Exception as _e:
                            print(f"  ⚠️ analyze_run 失败 (cand {cand_id} run {run_idx}): {_e}", flush=True)
                            try:
                                eng.record_phase_fail(round_num, "score", str(_e))
                            except Exception:
                                pass
                        else:
                            try:
                                eng.record_phase_complete(round_num, "score")
                            except Exception:
                                pass

                    # 提取真实分数：从 score.json 读 result_score（参照基线路径）
                    cand_score = 0.0
                    eval_error = False
                    gaps = []
                    if isinstance(eval_result, dict):
                        gaps = eval_result.get("gaps", [])
                        rating = eval_result.get("rating", "")
                        if rating == "BROKEN":
                            eval_error = True
                    score_json_path = cand_run_dir / "score.json"
                    if score_json_path.exists():
                        try:
                            from state_engine.persistence import \
                                load_json as _lj
                            score_data = _lj(str(score_json_path))
                            rs = score_data.get("result_score")
                            if rs is not None:
                                cand_score = float(rs)
                        except Exception:
                            pass
                    run_scores.append(cand_score)
                    all_gaps_for_avg.append(gaps)
                    label = " (⚠️ 评测执行错误)" if eval_error else ""
                    print(f"{cand_score:.1f}{label}")
            finally:
                # 恢复 skill_path 指向 workspace,避免污染后续 round/baseline 评测
                if _saved_eng_skill_path is not None:
                    eng.skill_path = _saved_eng_skill_path
                if _saved_args_skill_path is not None:
                    args.skill_path = _saved_args_skill_path

            avg_score = sum(run_scores) / len(run_scores) if run_scores else 0
            print(f"  ▸ 候选 {cand_id} 平均分: {avg_score:.1f} (runs: {[f'{s:.1f}' for s in run_scores]})")
            all_candidate_scores[cand_id] = avg_score
            all_candidate_runs[cand_id] = list(run_scores)
            all_gaps_for_candidates[cand_id] = list(all_gaps_for_avg)

            # apply 步骤合并后不再覆盖用户源，无需 restore（移除 v2.13 之前的 user_source_backup hack）

            if avg_score > best_candidate_score:
                best_candidate_score = avg_score
                best_candidate_id = cand_id
                # 合并最佳候选的所有 run gaps 去重
                seen = set()
                best_candidate_gaps = []
                for gaps_list in all_gaps_for_avg:
                    for g in gaps_list:
                        key = (g.get("type", ""), g.get("affected_section", "")[:50])
                        if key not in seen:
                            seen.add(key)
                            best_candidate_gaps.append(g)

        # apply 步骤合并后无备份目录,无需最终 restore

        # ── 候选级产物：复用 analyzer.analyze_candidate（与 baseline 入口对称） ──
        # 产物由 analyzer 统一写：
        #   - score_candidate_K_analysis.md（含各 Run 对比/聚合统计/数据来源/键值对/计算过程）
        #   - candidate_K_score_analysis.md（兼容旧版）
        #   - candidate_K_score.json（结构化摘要）
        # 候选不写 proposal（write_proposal=False），proposal 仅 baseline 写。
        _case_ids_for_analyzer = eng.config.get("case_ids") or None
        for _cand_id in all_candidate_runs.keys():
            _cand_dir = agent_dir / f"round_{round_num}" / f"candidate_{_cand_id}"
            if not _cand_dir.exists():
                continue
            try:
                candidate_analyzer.analyze_candidate(
                    _cand_dir, round_num, _cand_id,
                    strategy=f"agent_candidate_{_cand_id}",
                    case_ids=_case_ids_for_analyzer,
                    write_proposal=False,
                )
            except Exception as _e:
                print(f"  ⚠️ analyze_candidate 失败 (cand {_cand_id}): {_e}", flush=True)

        # 构造 candidate_scores 列表（与 _run_breadth_round 一致，用于 RoundReportBuilder）
        _candidate_scores_for_report = []
        for _cid, _avg in all_candidate_scores.items():
            _runs = all_candidate_runs.get(_cid, [])
            _stddev = 0.0
            if _runs and len(_runs) > 1:
                _mean = sum(_runs) / len(_runs)
                _stddev = (sum((s - _mean) ** 2 for s in _runs) / len(_runs)) ** 0.5
            # 从 candidate_K_score.json 读 per_case 矩阵（修复 Bug #4:per_case 缺失）
            _per_case: dict = {}
            try:
                _cs_path = agent_dir / f"round_{round_num}" / f"candidate_{_cid}" / f"candidate_{_cid}_score.json"
                if _cs_path.exists():
                    from state_engine.persistence import load_json as _ljpc
                    _cs_data = _ljpc(str(_cs_path))
                    for _run in _cs_data.get("runs", []):
                        for _cid_key, _cval in (_run.get("info", {}).get("result_score_per_case") or {}).items():
                            _per_case.setdefault(_cid_key, []).append(_cval)
            except Exception:
                _per_case = {}
            _candidate_scores_for_report.append({
                "id": _cid,
                "score": _avg,
                "stddev": _stddev,
                "run_scores": _runs,
                "strategy": f"agent_candidate_{_cid}",
                "per_case": _per_case,
            })
        _best_cand_for_report = None
        if _candidate_scores_for_report and best_candidate_id > 0:
            _best_cand_for_report = {
                "id": best_candidate_id,
                "score": best_candidate_score,
                "stddev": 0.0,
                "run_scores": all_candidate_runs.get(best_candidate_id, []),
                "strategy": f"agent_candidate_{best_candidate_id}",
            }

        # 写 round_N/round_N_score.json（轮级评分汇总，命名对齐参考产物）
        _round_dir = agent_dir / f"round_{round_num}"
        _round_score_data = {}
        try:
            from state_engine.persistence import ensure_dir as _ed
            from state_engine.persistence import save_json as _sj
            _round_score_data = {
                "round_num": round_num,
                "timestamp": __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "best_candidate_id": best_candidate_id if best_candidate_id > 0 else None,
                "baseline_score": bl_score,
                "candidates": [
                    {
                        "candidate_id": cs["id"],
                        "strategy": cs["strategy"],
                        "avg_result_score": round(cs["score"], 4),
                        "normalized": {"result_score": round(cs["score"], 4)},
                        "composite": round(cs["score"], 2),
                        "num_runs": len(cs["run_scores"]),
                        "stddev": round(cs["stddev"], 4),
                    }
                    for cs in _candidate_scores_for_report
                ],
                "skills": skill_names,
                "agent_name": agent_name,
            }
            _ed(str(_round_dir))
            _round_score_path = _round_dir / f"round_{round_num}_score.json"
            _sj(str(_round_score_path), _round_score_data)
            _log_write(_round_score_path, f"round_{round_num}_score_synthesis", agent_dir)
        except Exception as _e:
            print(f"  ⚠️ 写 round_N/round_N_score.json 失败: {_e}")

        # ── 生成 result_diff_report_round_N.md(综合 diff 报告,LLM 必读)──
        # 修复 2026-07-30:调用时机移到所有候选 Evaluate + analyze_run + score.json 合成完成后。
        # 此时 round_N/candidate_K/run_1/score.json 已存在,_generate_diff_report 能找到 Round N 实际数据
        # (而非 fallback 到 baseline),下轮 proposal-agent 读到的 result_diff_report_round_N.md 才是真实 F1/失分点。
        # 复制 baseline diff_report + 上一轮 diff_report 到本轮目录的逻辑在函数内部完成(line 245-263)。
        try:
            _diff_report_path = _generate_diff_report(
                agent_dir, round_num,
                best_round=eng.best_round, best_candidate_id=eng.best_candidate_id,
            )
            if _diff_report_path:
                print(f"  ✅ 已生成 {Path(_diff_report_path).relative_to(agent_dir)} (基于 Round {round_num} 实际数据)")
        except Exception as _e_dr:
            print(f"  ⚠️ round_{round_num}/result_diff_report.md 写入失败: {_e_dr}")

        # 更新 in-memory + task_state.json
        # 通用兜底：本轮若没有候选产出有效分数（best_candidate_score == -1），
        # 用基线分占位，避免 0 分掩盖真实基线水位。
        has_valid_candidate = best_candidate_score >= 0
        score = best_candidate_score if has_valid_candidate else eng.baseline_score
        gaps = best_candidate_gaps
        candidates_evaluated = sum(1 for v in all_candidate_scores.values() if v and v > 0) if has_valid_candidate else 0
        # 实时分/状态:更新 in-memory + 同步到 task_state.json
        eng.current_score = score
        eng.current_round = round_num
        # 🆕 2026-08-03 实施 A(修复版):每个 round apply 完 + eng.current_round 更新后立即 cp
        # 必须在 line 2915 之后触发,避免 _cur_round=0 跳过 cp。
        # 业务方跑 /sdd-eval 时立即能测到本 round 的修改,不用等任务整体跑完。
        try:
            _copy_newest_skill_for_test(eng)
        except Exception as _e_cpn:
            print(f"  ⚠️ copy_newest_skill 失败(r{eng.current_round} c{eng.best_candidate_id}): {_e_cpn}")

        # 在更新 best_score 前先快照旧值,供 history_entry / vs_best_delta / 决策用
        # 否则本轮 score 更新后,_current_best 已等于 score,vs_best_delta 恒为 0 且永远 not_adopted
        best_round_old_score = eng.best_score
        if score > eng.best_score:
            eng.best_score = score
            eng.best_round = round_num
            eng.best_candidate_id = best_candidate_id  # 记录产生 best_score 的候选 ID,供跨轮继承

        # 决策预测提前计算(running max 语义):有有效候选且分数 > 当前全局最佳 → 采纳
        # 必须放在 add_selection_decision 调用之前,否则 try 块里 _current_best / _predicted_decision
        # 未定义,NameError 被 except 吞掉,score_analysis.md 写不出或用错值
        _current_best = best_round_old_score  # 决策用:running max(本轮之前)
        _predicted_decision = (
            "adopted" if (has_valid_candidate and score > _current_best) else "not_adopted"
        )

        # 预初始化 _round_mods_summary (Bug #2 根因修复):L1040 add_modifications_summary
        # 在 try 块中引用此变量,Python 看到 L1076 赋值后把整函数变量视为 local,
        # 导致 L1040 触发 UnboundLocalError。在 try 块前预初始化避免此问题。
        _round_mods_summary: list = []

        # 写 round_N/round_N_score_analysis.md（用 RoundReportBuilder）
        try:
            from state_engine.persistence import RoundReportBuilder
            _rrb = RoundReportBuilder(round_num)
            _rrb.add_score_summary(bl_score, bl_runs, bl_std, _candidate_scores_for_report, _best_cand_for_report)
            _rrb.add_per_case_matrix(_candidate_scores_for_report)
            _rrb.add_gap_root_cause_analysis(_round_score_data)
            _rrb.add_modifications_summary(_round_mods_summary)
            _rrb.add_log_references(round_num)
            _rrb.add_selection_decision(
                bl_score, _best_cand_for_report, _candidate_scores_for_report,
                current_best=_current_best, decision=_predicted_decision,
            )
            _rrb.add_improvement_summary(_round_score_data)
            from state_engine.persistence import atomic_write as _aw_md
            _report_text = _rrb.render()
            _round_analysis_path = _round_dir / f"round_{round_num}_score_analysis.md"
            _aw_md(str(_round_analysis_path), _report_text)
            _log_write(_round_analysis_path, f"round_{round_num}_score_analysis_render", agent_dir)
        except Exception as _e:
            import traceback
            print(f"  ⚠️ 写 round_{round_num}/round_{round_num}_score_analysis.md 失败: {_e}")
            traceback.print_exc()

        # 按 Skill 拆分 gaps（新增 skills 字段）
        per_skill_gap_counts = {}
        for g in gaps:
            sec = g.get("affected_section", "")
            for sn in skill_names:
                if sn in sec:
                    per_skill_gap_counts[sn] = per_skill_gap_counts.get(sn, 0) + 1
                    break
            # 无明确归属的 gap 记录到所有 Skill
            if not any(sn in sec for sn in skill_names):
                for sn in skill_names:
                    per_skill_gap_counts[sn] = per_skill_gap_counts.get(sn, 0) + 1

        # 通用注：skill_scores 区分"未跑"（None）与"跑了 0 分"（0.0）
        skill_scores_repr = {
            f"candidate_{k}": (v if has_valid_candidate and v and v > 0 else None)
            for k, v in all_candidate_scores.items()
        }
        # 解析本轮 baseline proposal 的 modifications 摘要,供下轮 prev_failure_block 使用
        _round_mods_summary: list = []
        try:
            _proposal_path = agent_dir / "baseline" / "proposal.md"
            _round_mods_summary = _parse_proposal_modifications_summary(_proposal_path)
        except Exception:
            _round_mods_summary = []
        # ── Phase: proposal ── (run_optimization 已生成 baseline/proposal.md)
        try:
            eng.record_phase_start(round_num, "proposal")
        except Exception:
            pass
        try:
            eng.record_phase_complete(round_num, "proposal")
        except Exception:
            pass
        # ── 提取 per-case 分数(供下轮 subagent 看 regression/improved) ──
        _case_scores_this_round: dict = {}   # {case_id: mean_f1}
        _baseline_case_scores: dict = {}     # {case_id: baseline_f1}
        # 本轮最佳候选的 per-case(从 _candidate_scores_for_report 拿)
        try:
            for _cand in _candidate_scores_for_report or []:
                if _cand.get("id") == best_candidate_id:
                    _per_case_raw = _cand.get("per_case") or {}
                    # per_case: {case_id: [score_per_run, ...]}, 取 mean
                    for _cid, _vals in _per_case_raw.items():
                        if _vals:
                            _case_scores_this_round[_cid] = round(sum(_vals) / len(_vals), 2)
                    break
        except Exception:
            pass
        # baseline 的 per-case(从 baseline/score_baseline.json 拿)
        try:
            from state_engine.persistence import load_json as _ljbl
            _bs_path = agent_dir / "baseline" / "score_baseline.json"
            if _bs_path.exists():
                _bs = _ljbl(str(_bs_path))
                _bl_run_matrix = (_bs.get("baseline_score") or {}).get("case_run_matrix") or {}
                for _cid, _vals in _bl_run_matrix.items():
                    if _vals:
                        _baseline_case_scores[_cid] = round(sum(_vals) / len(_vals), 2)
        except Exception:
            pass

        history_entry = {
            "round": round_num,
            "score": score,
            "baseline_score": eng.baseline_score,  # 原始基线（展示用,非比较基准）
            "current_best": _current_best,  # 本轮比较的"当前全局最佳"(running max)
            "best_candidate_id": best_candidate_id,  # 2026-07-30 补:供断点恢复与跨轮继承
            "vs_baseline_delta": round(score - eng.baseline_score, 4),
            "vs_best_delta": round(score - _current_best, 4),  # 相对 running max 的增量
            "decision": _predicted_decision,
            "modifications_summary": _round_mods_summary,
            "case_scores": _case_scores_this_round,  # 本轮最佳候选 per-case 分数,供下轮 regression 分析
            "baseline_case_scores": _baseline_case_scores,  # baseline per-case 分数
            "gaps": len(gaps),
            "skill_scores": skill_scores_repr,
            "skills": {sn: {"gaps": per_skill_gap_counts.get(sn, 0)} for sn in skill_names},
            "candidates_evaluated": candidates_evaluated,
            "candidates_total": candidates_per_round,
            "timestamp": __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if not has_valid_candidate:
            history_entry["candidates_skipped"] = True
        eng.history.append(history_entry)

        # 同步到 task_state.json(权威源, 仅状态字段)
        if hasattr(eng, "phase_tracker"):
            eng.record_current_progress(
                status=f"round_{round_num}_completed",
                detail=f"round {round_num} 完成 score={score:.2f} current_best={_current_best:.2f}",
                round_num=round_num,
                phase="proposal",
            )

        if has_valid_candidate:
            print(f"\n  ▸ 本轮最佳: candidate_{best_candidate_id} ({score:.1f})")
        else:
            print(f"\n  ▸ 本轮无有效候选分数，回退到基线: {score:.1f}（{candidates_per_round} 个候选均未跑出有效分数）")

        # 达标检查
        if score >= DEFAULT_TARGET_SCORE:
            print(f"\n  ✅ 分数 {score:.1f} 已达目标 {DEFAULT_TARGET_SCORE}，优化循环终止")
            break

        # 使用最佳候选的 gaps 做最终优化（持久化到 workspace）
        # 但仅当本轮被采纳时才执行：否则 workspace 保持当前最佳(继承自 eng.best_round)
        # running max 语义:失败 → 沿用此前最佳 skill 组合,不应用本轮 proposal
        if _predicted_decision == "adopted":
            # 仅采纳时同步最佳候选 → 原始路径(供后续手动 /sdd-eval / 下轮 baseline 评测使用)
            # 修复:not_adopted 的失败改动不再回流污染源路径
            try:
                _adopted_skill_src = agent_dir / f"round_{round_num}" / f"candidate_{best_candidate_id}" / "skill"
                if _adopted_skill_src.exists():
                    _sync_candidate_to_original(
                        candidate_skill_root=_adopted_skill_src,
                        skill_path_list=skill_path_list,
                        log_prefix=f"[round {round_num}/adopted c{best_candidate_id}] ",
                    )
            except Exception as _e_sync:
                print(f"  ⚠️ adopted 同步失败: {_e_sync}")
            for sp in skill_path_list:
                skill_name = Path(sp).parent.name
                skill_sp = skill_registry[skill_name]
                s_args = _make_skill_args(args, skill_sp)
                # 过滤出与本 Skill 相关的 gaps
                skill_specific_gaps = [
                    g for g in gaps
                    if skill_name in (g.get("affected_section", "") or "")
                ] if gaps else []
                gaps_to_use = skill_specific_gaps if skill_specific_gaps else gaps
                run_optimization(eng, s_args, {
                    "gaps": gaps_to_use,
                    "context": {
                        "skill_name": skill_name,
                        "all_skill_names": skill_names,
                        "aggregate_score": score,
                    }
                }, round_num, candidate_id=best_candidate_id if best_candidate_id > 0 else -1)
        else:
            print(f"  ⏭️  Round {round_num}: not_adopted（分数 {score:.2f} <= 当前最佳 {_current_best:.2f}）"
                  f",跳过 run_optimization,workspace 保持为当前最佳 skill 组合")

        # ── 清理 /tmp 沙箱残留（不记 phase，纯机械）──
        try:
            SandboxManager.cleanup_stale()
        except Exception as e:
            print(f"  ⚠️ SandboxManager.cleanup_stale 失败: {e}")

        # 跨轮增量:不再用局部变量,改用 eng.best_candidate_id(在 best_score 更新时已同步写入)
        # 条件:仅当本轮被采纳时,eng.best_candidate_id 才会更新(decision == "adopted")
        # 若 not_adopted,eng.best_candidate_id 保持上一轮的值(可能=baseline 对应的 -1)

    # ── 生成联合审查报告 ──
    eng.record_current_progress("completed", "agent 循环完成", phase="finish")
    # ── Bug 修复：同步 in-memory 状态到 config（task_state.json 极简化后，best_score/history 只存 in-memory）──
    # 2026-07-30 修:补 best_candidate_id(原 L2284-2286 只写 best_score/best_round/history,
    #   断点恢复时 eng.best_candidate_id 默认 -1,L1597 链式继承条件失败。
    #   baseline_anchored 模式不依赖此字段,但默认模式断点恢复依赖)。
    eng.config["best_score"] = eng.best_score
    eng.config["best_round"] = eng.best_round
    eng.config["best_candidate_id"] = eng.best_candidate_id
    eng.config["history"] = eng.history
    eng.config_store.save(eng.config)
    # .13+ 删除:write_back_best_skill_to_source(args, agent_dir=agent_dir)
    # 硬约束:禁止把 best_skill/ 写回用户源路径（详见 skills/skill-optimize/SKILL.md）
    # 之前功能:多 skill 模式（--agent-path）任务结束后把 best_skill/ 覆盖式 copytree 到每个 skill 的源路径
    # 删除原因:同 L410-414,用户的源 SKILL.md 是受信任资产

    _generate_agent_report(
        agent_dir, eng.config, skill_registry, baselines={},
    )

    # ── 任务成功 finish:清理 .bak + 清 config user_source_bak 字段 ──
    _finish_skill_bak(args)


# 缓存 pipeline 命令提取结果，避免重复解析 YAML
_extracted_pipeline_commands: Optional[list] = None


# 业务方命令中常见的"case ID 列表参数"形式
_CASE_ID_FLAGS = ("--req-id", "--req_id", "--reqid", "--request-id",
                  "--request_id", "--requestid", "--case-ids", "--case_ids")
def _inject_case_ids_into_config(config: dict, args) -> None:
    """从 --pipeline-eval-cmd 解析 case_ids(如 --req-id RAN-1,RAN-2),写入 config。

    用途:
    - 审查回溯:用户给的评测范围白纸黑字记录
    - 复现:从 config 即可还原当时评测的 ID 集合
    - 报告:渲染到 score_analysis.md 的"输入 case_ids"段
    - ScoreAnalyzerAgent 透传:per-case 表 row key 优先用 case_ids
    """
    _cmds = _extract_pipeline_commands(args)
    _raw_cmd = _cmds[0] if _cmds else ""
    config["case_ids"] = _parse_case_ids_from_cmd(_raw_cmd)
    # 调试输出(出现异常时定位)
    print(f"  [case_ids] 解析自 '{_raw_cmd}': {config['case_ids']!r}")


_CASE_ID_PATTERN = re.compile(
    r"^--(?:req|request|case)[_-]?ids?(?:=|$)"
)


def _parse_case_ids_from_cmd(cmd_str: str) -> list[str]:
    """从评测命令字符串中解析 case ID 列表。

    支持形式（业务方实际命令行风格）:
        /sdd-eval --req-id RAN-5030325,RAN-6640009 --activity 需求分析
        python run.py --req_id RAN-1,RAN-2 --req_id RAN-3
        bash eval.sh --request-ids "RAN-1 RAN-2"

    规则:
    - 仅解析 --req-id / --req_id / --request-id 及其复数 / --case-ids 等命名
    - 同一标志多次出现 → 合并去重,保序
    - 值用逗号或空白分隔
    - 解析不到 → 返回空列表(不抛异常)
    - 通用性:不绑死具体 ID 格式(RAN-/CASE-/TC- 都接受),只过滤空白

    落盘到 config.json["case_ids"],用于:
    - 审查回溯:用户给的评测范围白纸黑字记录
    - 复现:从 config 即可还原当时评测的 ID 集合
    - 报告:与 score_history.md 交叉验证
    """
    if not cmd_str or not cmd_str.strip():
        return []
    try:
        import shlex
        argv = shlex.split(cmd_str)
    except ValueError:
        # 含未闭合引号等异常,回退到简单分词
        argv = cmd_str.split()

    ids: list[str] = []
    seen: set[str] = set()
    i = 0
    while i < len(argv):
        tok = argv[i]
        matched = _CASE_ID_PATTERN.match(tok)
        if not matched:
            i += 1
            continue
        # --req-id=RAN-1,RAN-2 形式
        if "=" in tok:
            value = tok.split("=", 1)[1]
            for cid in re.split(r"[,\s]+", value):
                cid = cid.strip()
                if cid and cid not in seen:
                    seen.add(cid)
                    ids.append(cid)
            i += 1
            continue
        # --req-id RAN-1,RAN-2 形式
        if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
            value = argv[i + 1]
            for cid in re.split(r"[,\s]+", value):
                cid = cid.strip()
                if cid and cid not in seen:
                    seen.add(cid)
                    ids.append(cid)
            i += 2
            continue
        i += 1
    return ids


def _extract_pipeline_commands(args) -> list:
    """从 pipeline 配置中提取评测命令列表（带缓存）。

    优先级：
    1. args.pipeline_eval_cmd（用户直接传入的命令字符串）
    2. args.pipeline_config_dict（config.json["pipeline"] 字段，dict 形态）
    3. args.pipeline_config（显式指定的 YAML 文件，仅作历史兼容兜底）
    """
    global _extracted_pipeline_commands
    if _extracted_pipeline_commands is not None:
        return _extracted_pipeline_commands

    # 1. 优先：直接传入的命令字符串
    pipeline_eval_cmd = getattr(args, 'pipeline_eval_cmd', '') or ''
    if pipeline_eval_cmd:
        _extracted_pipeline_commands = [pipeline_eval_cmd]
        return _extracted_pipeline_commands

    # 2. 从 args.pipeline_config_dict 提取（主路径，由 eval_pipeline 注入）
    pipeline_dict = getattr(args, 'pipeline_config_dict', None) or {}
    if pipeline_dict:
        steps = pipeline_dict.get("steps", []) or []
        cmds = [s.get("command", "") for s in steps if s.get("command")]
        _extracted_pipeline_commands = [c for c in cmds if c]
        return _extracted_pipeline_commands

    # 3. 历史兼容：仅当显式传入 YAML 路径时才尝试加载（不自动发现）
    pipeline_config = getattr(args, 'pipeline_config', '') or ''
    if not pipeline_config:
        _extracted_pipeline_commands = []
        return []

    p = Path(pipeline_config)
    if not p.exists():
        _extracted_pipeline_commands = []
        return []
    try:
        import yaml
        text = p.read_text(encoding="utf-8")
        cfg = yaml.safe_load(text) or {}
        pipeline = cfg.get("pipeline", cfg)
        steps = pipeline.get("steps", [])
        _extracted_pipeline_commands = [s.get("command", "") for s in steps if s.get("command")]
        return _extracted_pipeline_commands
    except Exception:
        _extracted_pipeline_commands = []
        return []


def _serializable_args(args) -> dict:
    """提取 CLI 参数中可序列化的部分，存入 config.json 供子进程恢复。

    排除已在 config 顶层的字段（max_rounds, candidates_per_round,
    eval_runs_per_candidate）。
    """
    key_attrs = [
        "skill_path", "skill_paths",
        "evaluator_agent", "non_interactive", "enable_skill_execution",
        "static_only", "model_reasoning",
        "eval_model", "eval_api_base", "eval_api_key",
        "api_base", "api_key",
        "eval_model", "eval_api_base", "eval_api_key",
        "max_cases", "case_filter",
        "no_fresh_session",
        "eval_config", "workflow_type", "workflow_script", "result_path",
        "pipeline_config", "pipeline_base_dir", "pipeline_eval_cmd",
        "pipeline_eval_sh",
        "pipeline_score_agg",
        "sub_rounds_per_candidate", "enable_proposal_review",
        "optimization_mode", "agent_name",
        "consume_lib_path",
    ]
    result = {}
    for attr in key_attrs:
        val = getattr(args, attr, None)
        if val is not None and val != "" and val is not False:
            if isinstance(val, Path):
                val = str(val)
            result[attr] = val
    return result


def _restore_args_from_config(args, config_path: Path):
    """从 config.json 恢复 CLI 参数到 args namespace（单轮模式）

    子进程优先使用 CLI 显式传递的参数，config._args 仅用于补充
    未通过 CLI 传递的参数。
    """
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return

    stored = config.get("_args", {})
    if not stored:
        return

    # 这些参数由 _spawn_phase_subprocess 通过 CLI 显式传递，不从 config 恢复
    _cli_provided = {
        "workspace", "skill_path", "round", "phase",
        "max_rounds",
        "skill_paths",
    }

    for attr, val in stored.items():
        if attr in _cli_provided:
            continue
        current = getattr(args, attr, None)
        # 只恢复仍处于 argparse 默认值的参数（None/空/零/False）
        is_default = (
            current is None or current == "" or current is False
            or current == 0 or current == 0.0 or current == []
        )
        if is_default:
            if attr.endswith("_path") or attr.endswith("_dir") or attr == "workspace":
                setattr(args, attr, Path(val))
            else:
                setattr(args, attr, val)

    # workspace 不在 _args 中，从 config 直接获取
    if not args.workspace:
        project_root = config.get("project_root", "")
        if project_root:
            args.workspace = Path(project_root)

    # skill_path 从 config 恢复：优先使用 workspace 副本路径（多轮迭代场景）
    ws_skill_path = config.get("workspace_skill_path", "")
    if ws_skill_path:
        if isinstance(ws_skill_path, list):
            for ws_p in ws_skill_path:
                if Path(ws_p).exists():
                    args.skill_path = Path(ws_p)
                    break
        elif Path(ws_skill_path).exists():
            args.skill_path = Path(ws_skill_path)
    # 回退：使用原始 skill 路径
    if not args.skill_path:
        target_skill_path = config.get("target_skill_path", "")
        if target_skill_path:
            first_path = target_skill_path[0] if isinstance(target_skill_path, list) else target_skill_path
            if first_path:
                args.skill_path = Path(first_path)

    # 恢复 bool 标志
    for flag in ("non_interactive", "no_fresh_session",
                 "enable_skill_execution", "static_only",
                 "enable_proposal_review"):
        if stored.get(flag):
            setattr(args, flag, True)


# ── 架构约束：产物禁止污染工程自身 ──────────────────────

_PROJECT_ROOT: Optional[Path] = None


def _get_eval_mode_label(args) -> str:
    """生成评测模式显示标签。"""
    if args.pipeline_config:
        return f"业务方管道 ({args.pipeline_config})"
    elif args.pipeline_base_dir:
        return f"业务方管道 ({args.pipeline_base_dir})"
    elif args.eval_config:
        return f"外部工作流 ({args.eval_config})"
    elif args.workflow_script:
        return f"外部脚本流 ({args.workflow_script})"
    elif args.evaluator_agent:
        return f"Agent ({args.evaluator_agent})"
    else:
        return "静态评测"


def _run_static_mode(args):
    """/skill_optimize 静态模式入口 — 无业务方 eval-cmd，纯 LLM judge + hill-climb

    支持两种调用方式：
    - --skill-path PATH：优化单个 Skill
    - --agent-path PATH：扫描 PATH/skills/ 下所有 Skill 独立优化
    """
    skill_path = getattr(args, "skill_path", "")
    agent_path = getattr(args, "agent_path", "")

    if not skill_path and not agent_path:
        print("\n  ❌ --mode static 必须传 --skill-path 或 --agent-path")
        sys.exit(2)
    if skill_path and agent_path:
        print("\n  ❌ --skill-path 与 --agent-path 互斥，只能传一个")
        sys.exit(2)

    if agent_path:
        _run_static_agent_mode(args)
    else:
        _run_static_single_mode(args)


# ──────────────────────────────────────────────────────────────────────
# /skill_optimize --mode refactor 结构层重构模式（原 /skill_refactor，v2 合并）
# ──────────────────────────────────────────────────────────────────────


def _resolve_refactor_skill_root(args) -> Path:
    """从 --skill-path 解析出 Skill 根目录。

    - 若传入的是 SKILL.md 文件 → 返回其父目录
    - 若传入的是目录且含 SKILL.md → 返回该目录
    - 否则报错
    """
    skill_path = Path(args.skill_path).resolve()
    if skill_path.is_file() and skill_path.name == "SKILL.md":
        return skill_path.parent
    if skill_path.is_dir() and (skill_path / "SKILL.md").exists():
        return skill_path
    print(f"\n  ❌ --skill-path 必须指向 SKILL.md 文件或含 SKILL.md 的目录: {skill_path}")
    sys.exit(2)


def _refactor_step1_build_tree(skill_root: Path, workspace: Path, args) -> Path:
    """Step 1: 调 build_relation_tree 产出 skill_file_relations.json。"""
    from optimizers.static_relations import (RELATION_TREE_FILENAME,
                                             build_relation_tree,
                                             write_relation_tree)
    out_path = workspace / RELATION_TREE_FILENAME
    if out_path.exists():
        try:
            if out_path.stat().st_mtime >= max(
                (p.stat().st_mtime for p in skill_root.rglob("*") if p.is_file()),
                default=0,
            ):
                print(f"  [refactor-step1] 复用已有 {RELATION_TREE_FILENAME}")
                return out_path
        except OSError:
            pass
    target_files = [p for p in skill_root.rglob("*") if p.is_file()]
    tree = build_relation_tree(
        skill_root=skill_root,
        target_files=target_files,
        protected_assets=[],
        history_path=None,
        max_files=50,
    )
    write_relation_tree(tree, out_path)
    print(f"  [refactor-step1] 完成:files={tree['stats']['file_count']} edges={tree['stats']['edge_count']}")
    return out_path


def _run_refactor_mode(args) -> None:
    """/skill_optimize --mode refactor 模式入口 — 只做数据收集,plan/apply/verify 由 CC 承担。

    orchestrator 产出:
    - skill_file_relations.json(Step 1 关系树)
    - refactor_diagnosis.md(Step 2 LLM 诊断)
    - before_skill/{SkillName}/  (source 初始快照,回滚源,CC 不修改)
    - after_skill/{SkillName}/   (source 修改副本,CC 的所有 Edit 在此副本上进行,
                                  源文件 live skill_root 永不改)

    之后 CC 主 Agent 读 relation tree + diagnosis → EnterPlanMode 合成 refactor plan →
    用户批准 → CC 用 Edit 改 after_skill/ 副本 → 出最终报告 → EnterPlanMode#2 确认。
    """
    from optimizers.static_plan_drafter import run_plan_draft
    from optimizers.static_refactor import run_diagnose, write_diagnosis
    from optimizers.static_refactor_automator import (run_automator,
                                                      write_automator_report)

    skill_path = getattr(args, "skill_path", "")
    if not skill_path:
        print("\n  ❌ --mode refactor 必须传 --skill-path")
        sys.exit(2)

    enforce_evolution_workspace(args)
    workspace = Path(args.workspace).resolve()
    skill_root = Path(args.skill_path).resolve()
    if skill_root.is_file() and skill_root.name == "SKILL.md":
        skill_root = skill_root.parent

    project_root = Path(__file__).resolve().parents[1]

    print(f"\n  [refactor-mode] skill={skill_root}")
    print(f"  [refactor-mode] workspace={workspace}")

    # Step 1: 关系树
    relation_tree_path = _refactor_step1_build_tree(skill_root, workspace, args)

    # before_skill/ 快照(source 初始快照,回滚源,CC 不修改)
    snapshot_dir = workspace / "before_skill"
    target_snapshot = snapshot_dir / skill_root.name
    if not target_snapshot.exists():
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_root, target_snapshot)
        print(f"  [refactor-mode] before_skill/ 快照已建:{target_snapshot}")

    # after_skill/ 副本(source 修改副本,CC 所有 Edit 在此副本上进行;
    # 源文件 live skill_root 永不改)
    after_skill_dir = workspace / "after_skill" / skill_root.name
    if not after_skill_dir.exists():
        (workspace / "after_skill").mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_root, after_skill_dir)
        print(f"  [refactor-mode] after_skill/ 副本已建:{after_skill_dir}")
    else:
        print(f"  [refactor-mode] after_skill/ 副本已存在:{after_skill_dir}(保留既有修改)")

    # Step 2: LLM 诊断 → refactor_diagnosis.md
    expert_guidance = getattr(args, "expert_guidance", "") or ""
    relation_tree = {}
    try:
        relation_tree = json.loads(relation_tree_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  [refactor-mode] ⚠ 关系树读取失败:{e}")
    skill_md_text = ""
    skill_md_path = skill_root / "SKILL.md"
    if skill_md_path.exists():
        try:
            skill_md_text = skill_md_path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"  [refactor-mode] ⚠ SKILL.md 读取失败:{e}")

    diagnosis_path = workspace / "refactor_diagnosis.md"
    llm_result = run_diagnose(
        skill_root, relation_tree, skill_md_text, project_root, expert_guidance,
    )
    if llm_result is None:
        # 降级:写 skipped 标记,CC 仍可继续(读 relation tree 自己合成 plan)
        diagnosis_path.parent.mkdir(parents=True, exist_ok=True)
        diagnosis_path.write_text(
            "# 诊断被跳过(LLM 不可用)\n\n"
            "原因:LLM 配置缺失或 call_llm_json 失败。\n"
            "请检查 config/optimize-user-config.yaml 的 llm_api.model 段。\n",
            encoding="utf-8",
        )
        print("  [refactor-mode] LLM 诊断降级,只产出关系树 + 快照")
    else:
        write_diagnosis(llm_result, diagnosis_path)
        findings_count = len(llm_result.get("findings", []))
        print(
            f"  [refactor-mode] LLM 诊断成功:findings={findings_count} → {diagnosis_path}"
        )

    # Step 2.5: 自动生成 7 步 plan 草稿(对标 d7bcf0da 实战案例 7 大类)
    # CC 在 plan mode 仍需批准/微调,但不必从零合成 plan。
    plan_draft_path = workspace / "refactor_plan_draft.md"
    draft_result = run_plan_draft(
        skill_root, relation_tree, plan_draft_path,
        skill_md_path=skill_root / "SKILL.md",
    )
    if draft_result is not None:
        print(f"  [refactor-mode] plan 草稿已生成:{draft_result}")
    else:
        print("  [refactor-mode] ⚠ plan 草稿生成失败(降级,CC 自己合成 plan)")

    # Step 3: automator 自动应用 80% 深度改动(对标 d7bcf0da)
    # 无需 LLM 推理,纯基于 orchestrator 已有数据(关系树 + 文本解析)
    # CC 只做剩余 20% 微调(例如 SKILL.md 大改、新增 references/* 内容)
    automator_report_path = workspace / "refactor_automator_report.md"
    automator_report = run_automator(skill_root, after_skill_dir, relation_tree)
    write_automator_report(automator_report, automator_report_path)
    print(
        f"  [refactor-mode] automator 报告:孤儿合并={automator_report['fd_004_orphan_merged']} | "
        f"改脚本={automator_report['fd_005_scripts_modified']} | "
        f"SK-S2={'PASS' if automator_report['fd_011_sk_s2_pass'] else 'FAIL'} | "
        f"SK-S12={'PASS' if automator_report['fd_012_sk_s12_pass'] else 'FAIL'} | "
        f"报告:{automator_report_path}"
    )

    # Step 4 (opt-in):--auto-apply 无头应用剩余 ~20% plan 编辑
    # 默认(不传 --auto-apply)保持 CC 交互审批路径，向后兼容。
    if getattr(args, "auto_apply", False):
        _refactor_auto_apply(args, workspace, after_skill_dir, skill_root)
        return

    print(
        f"\n  [refactor-mode] 数据收集完成。下一步 CC 应:\n"
        f"  1) Read {workspace}/refactor_diagnosis.md + skill_file_relations.json + refactor_plan_draft.md + refactor_automator_report.md\n"
        f"  2) EnterPlanMode:refactor_plan_draft.md 已基于 d7bcf0da 7 大类自动生成,automator 已自动应用 80% 深度改动,CC 仍需根据实际情况微调剩余 20%\n"
        f"  3) ExitPlanMode 让用户批准\n"
        f"  4) **在 {after_skill_dir} 副本上**用 Edit 工具应用剩余微调(源文件 {skill_root} 永不改)\n"
        f"  5) 出最终报告 → EnterPlanMode#2 确认完成\n"
        f"  6) 回滚源:cp -r {target_snapshot}/. {after_skill_dir}/"
    )


def _refactor_auto_apply(args, workspace, after_skill_dir, skill_root) -> None:
    """--auto-apply：在 after_skill/ 副本上经 AgentRunner 应用剩余 plan 编辑。

    流程：refactor-applier-agent 读 plan/relations/diagnosis + automator 报告 → 在
    after_skill_dir 上应用 ~20% 编辑 → 重跑 automator 补打确定性脉冲 → self-check 验证。
    全程不触碰 live skill_root；不传 --auto-apply 时此分支不进入（默认 CC 交互路径）。
    """
    from tools import Agent as _ToolsAgent
    from optimizers.static_refactor_automator import (run_automator,
                                                      write_automator_report)

    print("\n  [refactor-auto-apply] 无头应用剩余 plan 编辑…")

    # 1. 调度 refactor-applier-agent（系统提示=agent 文件，prompt=待用输入与目标目录）
    input_docs = [
        p for p in (
            workspace / "refactor_plan_draft.md",
            workspace / "skill_file_relations.json",
            workspace / "refactor_diagnosis.md",
            workspace / "refactor_automator_report.md",
        ) if p.exists()
    ]
    prompt = (
        "你是在 after_skill 副本上应用结构重构剩余 plan 编辑的编辑器子 Agent。\n"
        f"after_skill 副本（唯一可改路径）: {after_skill_dir}\n"
        f"live 源目录: {skill_root}（禁止用任何 Bash 工具 mv/rm/覆盖其下文件）\n"
        "输入文档:\n" + "\n".join(f"- {p}" for p in input_docs) + "\n\n"
        "请遵守你的系统提示中的硬约束：只改 after_skill 副本，遵循 plan 而非自拓，"
        "automator 已应用的 80% 不要回滚。"
    )
    _ToolsAgent(
        description="应用 refactor plan 剩余编辑(after_skill 副本)",
        prompt=prompt,
        subagent_type="refactor-applier-agent",
        cwd=str(after_skill_dir),
    )

    # 2. re-run automator：补打确定性脉冲（孤儿合并/脚本迁移/校验）
    relation_tree = {}
    tree_path = workspace / "skill_file_relations.json"
    if tree_path.exists():
        try:
            relation_tree = json.loads(tree_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            relation_tree = {}
    automator_report = run_automator(skill_root, after_skill_dir, relation_tree)
    report_path = workspace / "refactor_automator_report.md"
    write_automator_report(automator_report, report_path)
    print(
        f"  [refactor-auto-apply] 补打后孤儿合并={automator_report['fd_004_orphan_merged']} | "
        f"改脚本={automator_report['fd_005_scripts_modified']} | "
        f"SK-S2={'PASS' if automator_report['fd_011_sk_s2_pass'] else 'FAIL'} | "
        f"SK-S12={'PASS' if automator_report['fd_012_sk_s12_pass'] else 'FAIL'}"
    )

    # 3. self-check 验证（7 SK-S + 4 R-N）
    print("  [refactor-auto-apply] 运行独立自我检查验证…")
    _run_refactor_self_check(args)

    print(
        f"\n  [refactor-auto-apply] 完成。产物: {after_skill_dir}\n"
        f"  · 若对结果满意，回滚源: cp -r {workspace / 'before_skill' / skill_root.name}/. {after_skill_dir}/\n"
        f"  · 生成 diff 报告: python3 scripts/orchestrator.py --mode refactor-diff-report --workspace {workspace}"
    )


def _run_refactor_diff_report(args) -> None:
    """/skill_optimize --mode refactor 阶段 10a:生成 refactor_diff_report.html。

    优先用 after_skill/ 快照(CC 在阶段 9b 已抓),无快照则 fallback 到 live skill_root。
    - before_dir = workspace/before_skill/{skill_name}  (orchestrator 阶段 1 快照)
    - after_dir  = workspace/after_skill/{skill_name}  (阶段 9b 快照) OR skill_root (fallback)
    产出:{workspace}/refactor_diff_report.html(对标 skill_optimize_report.html 的 diff 章节)
    """
    from optimizers.static_refactor_diff import generate_refactor_diff_report

    workspace = Path(args.workspace).resolve()
    skill_root = Path(args.skill_path).resolve()
    if skill_root.is_file() and skill_root.name == "SKILL.md":
        skill_root = skill_root.parent
    skill_name = skill_root.name
    before_dir = workspace / "before_skill" / skill_name
    if not before_dir.exists():
        print(f"  ❌ before_skill/ 快照不存在:{before_dir}")
        print("     请先跑 `python3 scripts/orchestrator.py --mode refactor ...` 创建快照")
        sys.exit(2)

    # 优先 after_skill/ 快照(阶段 9b 产出),无则 fallback 到 live skill_root
    after_skill_snapshot = workspace / "after_skill" / skill_name
    if after_skill_snapshot.exists():
        after_dir = after_skill_snapshot
        print(f"  [refactor-diff-report] 使用 after_skill/ 快照:{after_dir}")
    elif skill_root.exists():
        after_dir = skill_root
        print(f"  [refactor-diff-report] after_skill/ 快照不存在,fallback 到 live:{after_dir}")
    else:
        print("  ❌ after_skill/ 快照与 live skill_root 均不存在")
        sys.exit(2)

    out = generate_refactor_diff_report(workspace, before_dir, after_dir, skill_name)
    print(f"  [refactor-diff-report] 已生成:{out}")


def _run_refactor_self_check(args) -> None:
    """/skill_optimize --mode refactor 阶段 10b 自我检查独立阶段(根治:让用户感知到自我检查)。

    对齐 d7bcf0da session §11 自我检查环节。自动:
    1. 跑 7 项 SK-S 静态验证(SK-S1/2/3/8/10/12/13)
    2. 跑 4 个 R-N 行为层场景(R-ScriptLink/MidLayer/IOContract/Description)
    3. 写 `{workspace}/自我检查报告.md`(用户可 file:// 直接打开感知)
    4. 写 `{workspace}/自我检查结果.json`(机器消费)

    产出独立报告,**不是事后总结**。
    """
    from optimizers.static_self_check import (run_self_check,
                                              write_self_check_json)

    workspace = Path(args.workspace).resolve()
    skill_root = Path(args.skill_path).resolve()
    if skill_root.is_file() and skill_root.name == "SKILL.md":
        skill_root = skill_root.parent
    skill_name = skill_root.name

    # 优先 after_skill/ 快照(CC 在阶段 9b 已抓)
    after_skill_dir = workspace / "after_skill" / skill_name
    if not after_skill_dir.exists():
        print(f"  ❌ after_skill/ 快照不存在:{after_skill_dir}")
        print("     请先跑 `python3 scripts/orchestrator.py --mode refactor ...` 创建快照")
        sys.exit(2)

    print("\n  🔍 [self-check] 启动独立自我检查阶段(Step 11)")
    print(f"  [self-check] Skill:{skill_name}")
    print(f"  [self-check] 目录:{after_skill_dir}")

    result = run_self_check(after_skill_dir, output_path=workspace / "自我检查报告.md")
    write_self_check_json(result, workspace / "自我检查结果.json")

    # 显眼的 console 输出(让用户在 orchestrator log 里直接看到结果)
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[result.overall]
    print(f"\n  {icon} [self-check] 自查结论:{result.overall}")
    print(f"  [self-check] 通过 {result.pass_count} / 失败 {result.fail_count} / WARN {result.warn_count}")
    print(f"  [self-check] Markdown 报告:{workspace / '自我检查报告.md'}")
    print(f"  [self-check] JSON 结果:  {workspace / '自我检查结果.json'}")

    # 列每一项结果(让用户从 stdout 就能感知)
    for sid, v in {**result.sk_s, **result.r_n}.items():
        sicon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[v["result"]]
        print(f"  {sicon}  {sid:20s} {v['result']:5s} {v['detail']}")

    # 退出码:PASS=0, WARN=0(可接受), FAIL=2
    if result.overall == "FAIL":
        sys.exit(2)
    sys.exit(0)


def _run_static_single_mode(args):
    """单 Skill 模式：优化 --skill-path 指定的单个 SKILL.md"""
    from optimizers.static_optimizer import (StaticConfig,
                                             run_static_optimization)

    enforce_evolution_workspace(args)
    workspace = Path(args.workspace).resolve()

    config = StaticConfig.from_args(args, workspace)
    print(f"  [static-mode] skill={config.skill_path}")
    print(f"  [static-mode] workspace={config.workspace}")
    print(f"  [static-mode] rounds={config.max_rounds} break_threshold={config.break_threshold}")
    print(f"  [static-mode] protected_assets={config.protected_assets}")
    print(f"  [static-mode] expert_guidance_len={len(config.expert_guidance)}")

    # v_next+：dispatch 到 unified agent（单阶段融合）或旧 6 phase
    if getattr(config, "use_unified_agent", True):
        from optimizers.static_agents import run_unified_static_optimization
        from optimizers.static_optimizer import load_framework_config
        framework_cfg = load_framework_config()
        history_raw = run_unified_static_optimization(config, framework_cfg)
        print(f"\n  [static-mode-unified] 完成 {len(history_raw)} 轮")
        for h in history_raw:
            print(f"    Round {h.round_num}: total={h.total:.2f} Δ={h.delta:+.2f} verdict={h.verdict} mods={h.modifications_count} applied={h.applied_count}")
    else:
        history = run_static_optimization(config)
        print(f"\n  [static-mode] 完成 {len(history)} 轮")
        for r in history:
            print(f"    Round {r.round_num}: score={r.score:.2f} Δ={r.delta:+.2f} verdict={r.verdict}")


def _scan_agent_skills(
    agent_path: Path,
    skill_paths_filter: Optional[List[str]] = None,
) -> list[Path]:
    """扫描 {agent_path}/skills/ 下所有含 SKILL.md 的子目录。

    Args:
        agent_path: Agent 根目录
        skill_paths_filter: 可选，Skill 目录名精确匹配列表（如
            ["子系统间接口设计", "子系统间接口设计-查询原有接口"]）。
            传了则只返回目录名在列表中的 SKILL.md；不传则扫描全部。

    Returns:
        list[Path]: SKILL.md 文件路径列表（按目录名排序）
    """
    skills_dir = agent_path / "." / "skills"
    if not skills_dir.is_dir():
        # Fallback: 兼容 agent 用 skills/ 而非 skills/
        alt_dir = agent_path / "skills"
        if alt_dir.is_dir():
            skills_dir = alt_dir
            print(f"  ℹ️  fallback: 使用 {skills_dir}（agent-path 缺 skills/）")
        else:
            print(f"  ❌ agent-path 不含 skills/ 或 skills/ 目录: {agent_path}")
            sys.exit(2)
    skill_paths: list[Path] = []
    filter_set = set(skill_paths_filter) if skill_paths_filter else None
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        if filter_set is not None and child.name not in filter_set:
            continue
        skill_md = child / "SKILL.md"
        if skill_md.is_file():
            skill_paths.append(skill_md)
    if filter_set is not None:
        matched_names = {sp.parent.name for sp in skill_paths}
        missing = filter_set - matched_names
        if missing:
            print(f"  ⚠️  --skill-paths 中以下 Skill 未在 {skills_dir} 下找到: {sorted(missing)}")
    return skill_paths


def _build_skill_summary_entry(
    skill_name: str,
    skill_path: str,
    skill_workspace: Path,
    history: list,
    max_rounds: int,
    break_threshold: float,
    status: str = "done",
) -> dict:
    """从已落盘的产物回填生成单 Skill 的 multi_skill_summary 条目。

    数据源优先级：
    1. static_history.json — 每轮 score/delta/verdict
    2. round_{N}/score.json — 8 维评分 + rating + gaps
    3. best_skill_info.json — 跨轮最佳来源
    4. progress-state.yaml — REWORK 历史
    """

    rounds_completed = len(history)
    best_score = max((r.score for r in history), default=0.0)
    baseline_score = history[0].baseline_score if history else 0.0
    last_score = history[-1].score if history else 0.0
    last_verdict = history[-1].verdict if history else "n/a"

    # 找到 best 来源的 round
    best_round_num = 0
    for r in history:
        if abs(r.score - best_score) < 0.01:
            best_round_num = r.round_num
            break

    # 找到 baseline 来源的 round（Round 1）
    baseline_round_num = history[0].round_num if history else 0

    # 8 维评分：baseline + best
    def _read_score_block(round_num: int) -> dict:
        score_path = skill_workspace / f"round_{round_num}" / "score.json"
        if not score_path.is_file():
            return {}
        try:
            with score_path.open(encoding="utf-8") as f:
                d = json.load(f)
            return {
                "total": d.get("total"),
                "rating": d.get("rating"),
                "dim_scores": d.get("dim_scores", {}),
                "gaps_count": len(d.get("gaps", [])),
                # ：多评测元数据，让顶层 summary 也能看到评估稳定性
                "eval_runs": d.get("_eval_runs", {}),
            }
        except (OSError, json.JSONDecodeError):
            return {}

    baseline_block = _read_score_block(baseline_round_num)
    best_block = _read_score_block(best_round_num)

    # best_skill_info.json
    best_info_path = skill_workspace / "best_skill_info.json"
    best_skill_info: dict = {}
    if best_info_path.is_file():
        try:
            with best_info_path.open(encoding="utf-8") as f:
                best_skill_info = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    # progress-state.yaml → REWORK
    progress_path = skill_workspace / "progress-state.yaml"
    rework_count = 0
    rework_phases: list[str] = []
    if progress_path.is_file():
        try:
            import yaml  # type: ignore[import-untyped]
            with progress_path.open(encoding="utf-8") as f:
                ps = yaml.safe_load(f) or {}
            rework_history = ps.get("rework_history") or []
            rework_count = len(rework_history)
            rework_phases = sorted({
                str(r.get("phase", ""))
                for r in rework_history
                if isinstance(r, dict) and r.get("phase")
            })
        except (OSError, ImportError):
            pass

    # 每轮详情
    rounds_detail = []
    for r in history:
        per_round = _read_score_block(r.round_num)
        rounds_detail.append({
            "round_num": r.round_num,
            "score": round(r.score, 2),
            "baseline_score": round(r.baseline_score, 2),
            "delta": round(r.delta, 2),
            "verdict": r.verdict,
            "modifications_applied": r.modifications_applied,
            "files_changed": list(r.files_changed or []),
            "rating": per_round.get("rating"),
            "gaps_count": per_round.get("gaps_count", 0),
        })

    # 触顶 break 判定
    broke_early = bool(rounds_completed > 0 and rounds_completed < max_rounds)

    return {
        "skill_name": skill_name,
        "skill_path": skill_path,
        "workspace": str(skill_workspace),
        "status": status,

        # 评分总览
        "baseline_score": round(baseline_score, 2),
        "best_score": round(best_score, 2),
        "last_score": round(last_score, 2),
        "improvement": round(best_score - baseline_score, 2),
        "last_verdict": last_verdict,
        "baseline_rating": baseline_block.get("rating"),
        "best_rating": best_block.get("rating"),

        # 8 维评分（baseline + best）
        "baseline_dim_scores": baseline_block.get("dim_scores", {}),
        "best_dim_scores": best_block.get("dim_scores", {}),

        # 轮次与配置
        "rounds_completed": rounds_completed,
        "max_rounds": max_rounds,
        "broke_early": broke_early,
        "break_threshold": break_threshold,

        # best_skill 来源
        "best_skill_info": {
            "source_round": best_skill_info.get("source_round"),
            "score": best_skill_info.get("score"),
            "timestamp": best_skill_info.get("timestamp"),
        },

        # REWORK
        "rework_count": rework_count,
        "rework_phases": rework_phases,

        # ：多评测稳定性（baseline 和 best 的 stdev，便于看  是否比  更稳）
        "baseline_total_stdev": baseline_block.get("eval_runs", {}).get("total_stdev"),
        "best_total_stdev": best_block.get("eval_runs", {}).get("total_stdev"),

        # 每轮详情
        "rounds": rounds_detail,
    }


def _run_static_agent_mode(args):
    """多 Skill 模式：扫描 --agent-path 下的所有 Skill，挨个独立优化。

    每个 Skill 一个独立 task 目录，互不影响；顶层生成 multi_skill 总结。
    Skill 范围二次确认由 commands/skill_optimize.md 在调用前完成。
    """
    from optimizers.static_optimizer import (StaticConfig,
                                             run_static_optimization)

    agent_path = Path(args.agent_path).resolve()
    print(f"  [static-mode-agent] agent_path={agent_path}")

    # 1. 扫描 skills（--skill-paths 传入 Skill 目录名列表时按精确匹配过滤；不传则扫描全部）
    skill_name_filter: Optional[List[str]] = None
    if getattr(args, "skill_paths", ""):
        # static agent 模式下 --skill-paths 接收 Skill 目录名（逗号分隔），
        # 与 --agent-path 配合精确匹配子目录名（不接完整路径，与 eval agent 模式语义不同）。
        skill_name_filter = [
            name.strip()
            for name in args.skill_paths.replace("\n", "").replace("\r", "").split(",")
            if name.strip()
        ]
        if not skill_name_filter:
            skill_name_filter = None
    skill_paths = _scan_agent_skills(agent_path, skill_paths_filter=skill_name_filter)
    if not skill_paths:
        if skill_name_filter:
            print(f"  ❌ {agent_path}/skills/ 下未匹配到 --skill-paths 指定的任何 Skill: {skill_name_filter}")
        else:
            print(f"  ❌ {agent_path}/skills/ 下未发现任何 SKILL.md")
        sys.exit(2)
    print(f"  [static-mode-agent] 发现 {len(skill_paths)} 个 Skill：")
    for sp in skill_paths:
        rel = sp.relative_to(agent_path)
        print(f"    - {rel}")

    # 2. 复用 enforce_evolution_workspace 创建顶层 task 目录
    enforce_evolution_workspace(args)
    base_workspace = Path(args.workspace).resolve()
    print(f"  [static-mode-agent] 顶层 workspace={base_workspace}")

    # 3. 逐 Skill 独立优化（每个 skill 一个子目录）
    summary: list[dict] = []
    for idx, skill_md in enumerate(skill_paths, start=1):
        skill_name = skill_md.parent.name
        skill_workspace = base_workspace / f"skill_{idx:02d}_{skill_name}"
        print(f"\n{'=' * 64}")
        print(f"  [{idx}/{len(skill_paths)}] Skill: {skill_name}")
        print(f"  workspace: {skill_workspace}")
        print(f"{'=' * 64}")

        # 构造该 skill 的 args（覆盖 skill-path / workspace）
        sub_args = argparse.Namespace(**vars(args))
        sub_args.skill_path = str(skill_md)
        sub_args.workspace = str(skill_workspace)
        # 默认每个 Skill 3 轮（与 /skill_optimize 文档一致；显式传 0 = 用 --max-rounds 兜底）
        per_skill = getattr(args, "per_skill_rounds", 3)
        if per_skill <= 0:
            sub_args.max_rounds = args.max_rounds
        else:
            sub_args.max_rounds = min(args.max_rounds, per_skill)

        try:
            config = StaticConfig.from_args(sub_args, skill_workspace)
            history = run_static_optimization(config)


            entry = _build_skill_summary_entry(
                skill_name=skill_name,
                skill_path=str(skill_md),
                skill_workspace=skill_workspace,
                history=history,
                max_rounds=sub_args.max_rounds,
                break_threshold=getattr(args, "break_threshold", 1.0),
                status="done",
            )
            summary.append(entry)
            print(f"  [{idx}/{len(skill_paths)}] {skill_name} 完成: "
                  f"baseline={entry['baseline_score']:.2f} "
                  f"best={entry['best_score']:.2f} "
                  f"Δ={entry['improvement']:+.2f} "
                  f"rounds={entry['rounds_completed']} "
                  f"verdict={entry['last_verdict']}")
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ [{idx}/{len(skill_paths)}] {skill_name} 失败: {e}")
            summary.append({
                "skill_name": skill_name,
                "skill_path": str(skill_md),
                "workspace": str(skill_workspace),
                "status": "broken",
                "error": str(e)[:200],
            })

    # 4. 顶层总结
    summary_path = base_workspace / "multi_skill_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n{'#' * 64}")
    print(f"# 多 Skill 优化完成：{len(skill_paths)} 个 skill")
    done = sum(1 for s in summary if s["status"] == "done")
    broken = sum(1 for s in summary if s["status"] == "broken")
    print(f"#   done={done}  broken={broken}")
    for s in summary:
        if s["status"] == "done":
            print(f"#   ✅ {s['skill_name']:30s} best_score={s['best_score']:6.2f} rounds={s['rounds_completed']}")
        else:
            print(f"#   ❌ {s['skill_name']:30s} {s.get('error', '')[:60]}")
    print(f"# 总结：{summary_path}")
    print(f"{'#' * 64}\n")


def _run_subprocess_mode(args):
    """单轮模式（--round N）：子进程从 config.json 恢复参数。"""
    config_path = args.workspace / "config.json"
    if config_path.exists():
        _restore_args_from_config(args, config_path)

    if not args.skill_path or not Path(args.skill_path).is_file():
        print(f"Error: Skill 文件不存在: {args.skill_path}")
        sys.exit(1)

    _setup_eval_env(args)

    # 子进程也清理旧沙箱，防止超时/崩溃残留
    SandboxManager.cleanup_stale()

    phase = args.phase or "full"
    print(f"[子进程 PID={os.getpid()}] 执行 Round {args.round} ({phase})")

    state_engine = StateEngine(args.workspace, args)
    if not state_engine.initialize():
        sys.exit(0 if state_engine.status in state_engine.TERMINAL_STATES else 1)

    if phase == "eval":
        ok = _run_eval_subprocess_inner(state_engine, args, args.round)
    elif phase == "optimize":
        ok = _run_optimize_subprocess_inner(state_engine, args, args.round)
    else:
        ok = run_single_round(state_engine, args, args.round)
    sys.exit(0 if ok else 1)


def _run_normal_loop(args):
    """正常模式：全循环（Agent 或 Single）。"""
    # 验证 skill 路径
    opt_mode = getattr(args, 'optimization_mode', 'single') or 'single'
    if opt_mode != "agent" and not Path(args.skill_path).is_file():
        print(f"Error: Skill 文件不存在: {args.skill_path}")
        sys.exit(1)

    eval_mode = _get_eval_mode_label(args)

    # ── Agent 模式 ──
    if opt_mode == "agent":
        if not args.skill_paths:
            print("ERROR: agent 模式需要 --skill-paths 参数")
            sys.exit(1)
        skill_path_list = _parse_skill_paths(args.skill_paths)
        print("skillx-alpha Orchestrator (重构版)")
        print("=" * 50)
        print("  优化模式: Agent 级别联合优化")
        print(f"  Agent 名称: {args.agent_name or 'unknown'}")
        print(f"  Skill 数量: {len(skill_path_list)}")
        for sp in skill_path_list:
            print(f"    ▸ {Path(sp).parent.name}")
        print(f"  目标分数: >= {DEFAULT_TARGET_SCORE}")
        print(f"  最大轮次: {args.max_rounds}")
        print(f"  评测模式: {eval_mode}")
        print(f"  执行模式: {'真实执行' if args.enable_skill_execution else '静态'}")
        print("  执行模式: inline 原地执行")
        print("=" * 50)

        args.workspace.mkdir(parents=True, exist_ok=True)
        from state_engine.phase_tracker import PhaseTracker
        PhaseTracker(args.workspace).update_current(
            "starting", "agent orchestrator 启动", round_num=-1, phase="init")

        _setup_eval_env(args)
        _load_eval_env_from_dotenv()
        if args.workflow_script:
            _inject_case_ids_from_workflow_script(args.workflow_script)

        try:
            sys.stdout.reconfigure(line_buffering=True)
            sys.stderr.reconfigure(line_buffering=True)
            run_agent_loop(args)
        except KeyboardInterrupt:
            print("\n\n用户中断，任务已保存。")
            sys.exit(0)
        except Exception as e:
            logger.exception(f"Agent 模式执行失败: {e}")
            sys.exit(1)
        return

    # ── Single 模式 ──
    skill_path_obj = Path(args.skill_path)
    print("skillx-alpha Orchestrator (重构版)")
    print("=" * 50)
    print(f"  目标 Skill: {skill_path_obj.parent.name}")
    print(f"  目标分数: >= {DEFAULT_TARGET_SCORE}")
    print(f"  最大轮次: {args.max_rounds}")
    print(f"  评测模式: {eval_mode}")
    print(f"  执行模式: {'真实执行' if args.enable_skill_execution else '静态'}")
    print("  执行模式: inline 原地执行（基线 → 分析 → 候选）")
    if getattr(args, 'candidates_per_round', 1) > 1:
        print(f"  广度优先: {args.candidates_per_round} 候选/轮 x {args.sub_rounds_per_candidate} 子轮/候选")
        print(f"  多次评测: {args.eval_runs_per_candidate} 次/候选（取平均）")
    if args.eval_model:
        eval_label = f"评测模型: {args.eval_model}"
        if args.eval_api_base:
            eval_label += f" | API: {args.eval_api_base}"
        print(f"  {eval_label}")
    if args.pipeline_config or args.pipeline_base_dir:
        pdir = args.pipeline_config or args.pipeline_base_dir
        print(f"  管道目录: {pdir}")
        print(f"  分数聚合: {args.pipeline_score_agg}")
    print("=" * 50)

    args.workspace.mkdir(parents=True, exist_ok=True)
    from state_engine.phase_tracker import PhaseTracker
    PhaseTracker(args.workspace).update_current(
        "starting", "orchestrator 启动", round_num=-1, phase="init")

    _setup_eval_env(args)
    _load_eval_env_from_dotenv()

    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
        run_loop(args)
    except KeyboardInterrupt:
        print("\n\n用户中断，任务已保存。")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Single 模式执行失败: {e}")
        sys.exit(1)


def _try_extract_bash_from_slash_command(cmd: str, base_dir: str) -> Optional[str]:
    """
    尝试从 slash command 文件中提取第一个 bash 代码块，作为可直接执行的 shell 命令。

    适用场景：slash command 的内容只是「执行某个 Python 脚本」的简单包装。
    与其让 `cosight -p` 解释执行（慢且消耗 tokens），不如直接执行里面的脚本。

    提取规则：
    1. 在 `<base_dir>/commands/<name>.md` 查找 slash command 定义文件
    2. 提取第一个以 ```bash 开头（忽略大小写和语言标签）的代码块内容
    3. 去掉 `cd ...` 前缀，让命令在当前 cwd（=base_dir）下执行

    Args:
        cmd: 用户传入的命令字符串（以 / 开头）
        base_dir: pipeline 评测基础目录

    Returns:
        提取出的可直接执行的 shell 命令；如果找不到或不满足条件则返回 None
    """
    if not cmd or not base_dir:
        return None
    cmd_first_token = cmd.lstrip().split(maxsplit=1)[0] if cmd else ""
    if not cmd_first_token.startswith("/"):
        return None
    # 去掉 / 前缀和可能的参数
    slash_name = cmd_first_token.lstrip("/")
    # 文件名可能带 .md 后缀
    candidate = Path(base_dir) / "." / "commands" / f"{slash_name}.md"
    if not candidate.exists():
        # 也试试去掉 .md 后缀的情况
        alt = Path(base_dir) / "." / "commands" / slash_name
        if alt.exists() and alt.is_file():
            candidate = alt
        else:
            return None
    try:
        content = candidate.read_text(encoding="utf-8")
    except Exception:
        return None
    # 匹配第一个代码块：支持带语言标签 (bash/sh/shell) 和无语言标签两种形式
    # 无语言标签必须支持,因为 slash command 的"实际命令"块经常用 ``` 包裹（不带语言）
    # 修复:之前只匹配带语言标签的代码块,会跳过"实际命令"块、误取"示例"区段的代码块
    pattern = re.compile(r"```(?:bash|sh|shell)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
    m = pattern.search(content)
    if not m:
        return None
    bash_body = m.group(1).strip()
    # 去掉行首的 `cd ... &&` 前缀（让命令在 base_dir cwd 下执行）
    bash_body = re.sub(r"^cd\s+(\"[^\"]*\"|'[^']*'|\S+)\s*&&\s*", "", bash_body, count=1)
    # 也支持 `cd ...; ...` 形式
    bash_body = re.sub(r"^cd\s+(\"[^\"]*\"|'[^']*'|\S+)\s*;\s*", "", bash_body, count=1)
    # 去掉文档里的方括号占位符（如 `[参数]`、`[arg]`、`[value]` 等），它们是说明性文字，不是真实参数
    bash_body = re.sub(r"\[[^\]]*\]", "", bash_body)
    # 清理多余空白
    bash_body = re.sub(r"\s+", " ", bash_body).strip()
    if not bash_body:
        return None
    # 修复:把 $ARGUMENTS 占位符替换成 slash command 后的实际参数
    # 例:`/mock-sdd-eval --req-id RAN-1` → 提取 `python3 scripts/x.py $ARGUMENTS` + 实际 args `--req-id RAN-1`
    if "$ARGUMENTS" in bash_body:
        # 取 slash command 后面的全部内容（去掉首个 /<name> token 及其前导空白）
        _cmd_after = cmd.lstrip()
        # 去掉 /<name>
        _parts = _cmd_after.split(maxsplit=1)
        _args = _parts[1] if len(_parts) > 1 else ""
        # 修复:过滤掉 orchestrator 级别的元数据 args,这些不是给业务脚本用的
        # --activity / --sub-activity:这些是 orchestrator 用于 agent_name 推断的元数据
        # 业务脚本（如 mock_sdd_eval.py）通常不识别它们,会导致 argparse 报错
        if _args:
            import shlex as _shlex
            try:
                _arg_list = _shlex.split(_args)
                _filtered = []
                _skip_next = False
                for _a in _arg_list:
                    if _skip_next:
                        _skip_next = False
                        continue
                    if _a in ("--activity", "--sub-activity", "--agent-name", "--skill-name"):
                        _skip_next = True  # 跳过此 flag 的 value
                        continue
                    if _a.startswith("--activity=") or _a.startswith("--sub-activity=") \
                       or _a.startswith("--agent-name=") or _a.startswith("--skill-name="):
                        continue
                    _filtered.append(_a)
                _args = " ".join(_shlex.quote(a) for a in _filtered) if _filtered else ""
            except Exception:
                pass  # shlex 解析失败时,保留原始 args(向后兼容)
        bash_body = bash_body.replace("$ARGUMENTS", _args)
    return bash_body


def _auto_wrap_slash_command(pipeline_eval_cmd: str, pipeline_base_dir: str = "") -> Optional[str]:
    """
    自动把 cosight slash command 包成 `cosight -p` 形式。

    业务方调用方式与本函数的处理路径对应：

    主路径(推荐 — 业务方用简化入参)：
        `--pipeline-base-dir DIR --pipeline-eval-cmd "/<cmd> ..."`
        → cwd 由 base_dir 提供，slash command 作为整体直接 wrap 成 `cosight -p "<cmd>"`
        → 不分析命令字符串里的 cd / && / 其它前缀，**不依赖正则**

    兜底路径(位置参数兼容 — 旧式 `cd X && /<cmd> ...`)：
        pipeline_base_dir 为空时，从位置参数里用 regex 提取 `cd X` 目标，
        wrap 后写成 `cd X && cosight -p "<cmd>"` 保留行为一致

    **重要**：cosight -p 的 prompt 里 slash command 不会被解析！
    正确的 shell 语法是：先 cd 到目录，再用 cosight -p 执行 slash command。
    例如：`cd /path && cosight -p "/sdd-eval ..." --dangerously-skip-permissions`
    错误的写法是：`cosight -p "cd /path && /sdd-eval ..." --dangerously-skip-permissions`

    Returns:
        转换后的命令(已包含 --dangerously-skip-permissions);不是 slash command 或无法处理则返回 None
    """
    import re
    cmd = (pipeline_eval_cmd or "").strip()
    if not cmd:
        return None
    # 已经显式用 `cosight -p` 包装过了,不重复包装
    if any(x in cmd.split()[:3] for x in ("cosight", "claude")) and ("-p" in cmd or "--print" in cmd):
        return None

    # ── 主路径：--pipeline-base-dir 已提供,只需识别子命令里有没有 slash command ──
    # cwd 已由 base_dir 指定,slash command 在原 cmd 任意位置都视为可 wrap
    if pipeline_base_dir:
        sub_cmds = re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmd)
        for sub in sub_cmds:
            first_token = sub.strip().split(maxsplit=1)[0]
            if first_token.startswith("/") and len(first_token) > 1 and first_token[1].isalpha():
                return f'claude -p "{cmd}" --dangerously-skip-permissions'
        # base_dir 有值但命令不含 slash command — 后续走原始 shell 执行即可
        return None

    # ── 兜底路径：pipeline_base_dir 为空,从位置参数提取 cd X && /cmd 的 X ──
    # 按 shell 操作符(`&&` `||` `;` `|`)拆分命令
    sub_cmds = re.split(r"\s*(?:&&|\|\||;|\|)\s*", cmd)
    slash_cmd_part = None
    cd_target = None

    for sub in sub_cmds:
        sub = sub.strip()
        if not sub:
            continue
        first_token = sub.split(maxsplit=1)[0]
        # 检查是否是 slash command
        if first_token.startswith("/") and len(first_token) > 1 and first_token[1].isalpha():
            slash_cmd_part = sub
            continue
        # 检查是否是 cd 命令
        if first_token == "cd":
            cd_match = re.match(r'^cd\s+("[^"]+"|\'[^\']+\'|\S+)', sub)
            if cd_match:
                cd_target = cd_match.group(1).strip('"\'')
            continue
        # 其他命令，不处理
        return None

    if not slash_cmd_part or cd_target is None:
        return None
    return f'cd {cd_target} && cosight -p "{slash_cmd_part}" --dangerously-skip-permissions'


def _warn_if_slash_command(pipeline_eval_cmd: str, pipeline_base_dir: str) -> None:
    """
    检测 --pipeline-eval-cmd 是否传入了 cosight 的 slash command（以 / 开头）。

    --pipeline-eval-cmd 的本质是 shell 命令（subprocess.Popen shell=True），
    执行目录 cwd=--pipeline-base-dir。slash command（如 /<your-slash-cmd>）
    是 cosight 内部的特殊语法，shell 无法识别，会报「没有那个文件或目录」。

    检测到 slash command 时给出明确指引，避免用户混淆。
    配合 `_auto_wrap_slash_command` 可在 main() 中自动包成 `cosight -p` 形式。
    """
    cmd = (pipeline_eval_cmd or "").strip()
    if not cmd:
        return
    # 去掉前导空白和引号
    cmd_first_token = cmd.lstrip().split(maxsplit=1)[0] if cmd else ""
    if not cmd_first_token.startswith("/"):
        return

    print("\n" + "=" * 64)
    print("  ⚠️  检测到 --pipeline-eval-cmd 是 cosight slash command！")
    print("=" * 64)
    print(f"  命令: {cmd[:120]}{'...' if len(cmd) > 120 else ''}")
    print(f"  cwd : {pipeline_base_dir or '(未设置)'}")
    print()
    print("  编排器会把 --pipeline-eval-cmd 当作 shell 命令执行")
    print("  （subprocess.Popen shell=True，cwd=--pipeline-base-dir），")
    print("  而 slash command（以 / 开头的命令）只在 cosight 内部识别，")
    print("  在 shell 中直接执行会报「没有那个文件或目录」。")
    print()
    print("  处理顺序：")
    print("    1) 主路径：--pipeline-base-dir 已提供 → 直接 wrap 成 `cosight -p \"<cmd>\"`（推荐）")
    print("    2) 优先尝试从 slash command 文件提取 bash 代码块（避免走 cosight -p）")
    print("    3) 兜底回退到 `cosight -p` 形式（并注入 --dangerously-skip-permissions）")
    print()
    print("  推荐写法（简化入参，cwd 显式拆出）:")
    print("    --pipeline-base-dir <DIR> --pipeline-eval-cmd \"/<cmd> --arg ...\"")
    print()
    print("  如需禁用自动处理，可显式用以下任一写法：")
    print()
    print("  1) 直接调用对应的 Python 脚本（在 --pipeline-base-dir 下）:")
    print("     --pipeline-eval-cmd 'python3 <your_eval_script>.py --arg value'")
    print()
    print("  2) 显式使用 type=cosight_command 的 step 配置（YAML 模式）:")
    print("     --pipeline-config <yaml>  # 在 yaml 中指定 type: cosight_command")
    print("=" * 64 + "\n")


def _run_create_mode(args):
    """--mode create：委托无头 create 流水线（orchestrators/create_pipeline.py）。

    把 orchestrator 的 --create-* / --expert-guidance / --non-interactive /
    --agent-cli 参数映射到 create_pipeline 的 Namespace。返回其 exit code。
    """
    from orchestrators.create_pipeline import run_create_pipeline

    requirement = getattr(args, "create_requirement", "") or ""
    if not requirement:
        print(
            "[ERROR] --mode create 需要 --create-requirement（@file.md 或自然语言）",
            file=sys.stderr,
        )
        return 2
    output_dir = getattr(args, "create_output_dir", "") or os.path.join(
        os.getcwd(), "output", "skills_create"
    )
    create_ns = argparse.Namespace(
        skill_name=getattr(args, "create_skill_name", "") or "unnamed-skill",
        requirement=requirement,
        output_dir=output_dir,
        expert_guidance=getattr(args, "create_expert_guidance", "") or args.expert_guidance or "",
        agent_cli=getattr(args, "agent_cli", None),
        non_interactive=args.non_interactive,
        decisions_file=None,
    )
    return run_create_pipeline(create_ns)


def main():
    args = parse_args()

    # ── 启动参数归一化：--pipeline-eval-sh 优先于 --pipeline-eval-cmd ──
    # argparse 互斥组已保证 --pipeline-eval-sh 与 --pipeline-eval-cmd 不会同时传非空值；
    # 这里把 eval-sh 归一化到 args.pipeline_eval_cmd，让下游消费者（populate_pipeline_in_config /
    # extract_sub_activity / _extract_pipeline_commands / _inject_case_ids_into_config 等）
    # 都能从同一个字段读取，零侵入。
    pipeline_eval_sh = getattr(args, 'pipeline_eval_sh', '').strip()
    if pipeline_eval_sh:
        args.pipeline_eval_cmd = pipeline_eval_sh
        print("  [eval-sh] 使用 --pipeline-eval-sh（纯 shell 命令，跳过 slash-command 检测/提取/wrap）")

    # ── 配置工作区 ──
    _setup_workspace(args)

    # 启动参数安全提示
    # 修复:同时考虑 pipeline_eval_cmd 本身(用户可能只传 --pipeline-eval-cmd 不传 base_dir/config)
    pipeline_mode = bool(
        args.pipeline_config or args.pipeline_base_dir or args.pipeline_eval_cmd
    )
    if pipeline_mode and not getattr(args, 'enable_skill_execution', True):
        print("\n  ⚠️  提示：已禁用 Skill 执行（--no-enable-skill-execution），候选产物不会在沙箱中生成，")
        print("     所有 RAN 将跳过评测。如需启用真实 Skill 执行，请移除 --no-enable-skill-execution 参数。\n")

    # 启动参数安全提示：slash command 检测 + 自动包装
    # 守卫：仅当 --pipeline-eval-cmd 路径（非 eval-sh）时才走 wrap/extract/warn
    if pipeline_mode and getattr(args, 'pipeline_eval_cmd', '') and not pipeline_eval_sh:
        _warn_if_slash_command(
            getattr(args, 'pipeline_eval_cmd', ''),
            getattr(args, 'pipeline_base_dir', ''),
        )
        # 优先尝试从 slash command 文件中直接提取 bash 命令（快速路径，跳过 cosight -p）
        base_dir = getattr(args, 'pipeline_base_dir', '') or ''
        extracted = _try_extract_bash_from_slash_command(args.pipeline_eval_cmd, base_dir)
        if extracted:
            print("  [auto-extract] 检测到 slash command 文件，直接提取 bash 命令块（无需 cosight -p）")
            print(f"  [auto-extract] 原始命令 : {args.pipeline_eval_cmd}")
            print(f"  [auto-extract] 提取命令 : {extracted}")
            print()
            args.pipeline_eval_cmd = extracted
        else:
            # 兜底：自动把 slash command 包成 `cosight -p` 形式（已含 --dangerously-skip-permissions）
            wrapped_cmd = _auto_wrap_slash_command(args.pipeline_eval_cmd, getattr(args, 'pipeline_base_dir', ''))
            if wrapped_cmd:
                print(f"  [auto-wrap] 原始命令: {args.pipeline_eval_cmd}")
                print(f"  [auto-wrap] 包装后 : {wrapped_cmd}")
                print()
                args.pipeline_eval_cmd = wrapped_cmd

    # ── 模式分发 ──
    if args.mode == "create":
        _create_rc = _run_create_mode(args)
        # 无头流水线需把失败透出给 DSH/CI/脚本（其余 mode 保持原行为）
        if _create_rc:
            sys.exit(_create_rc)
        return

    if args.mode == "refactor":
        _run_refactor_mode(args)
        return

    if args.mode == "refactor-diff-report":
        _run_refactor_diff_report(args)
        return

    if args.mode == "refactor-self-check":
        _run_refactor_self_check(args)
        return

    if args.mode == "static":
        _run_static_mode(args)
        return

    if args.round is not None:
        _run_subprocess_mode(args)
        return

    # ── 正常模式：全循环 ──
    _run_normal_loop(args)


if __name__ == "__main__":
    main()
