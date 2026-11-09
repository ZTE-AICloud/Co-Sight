"""
Score Analyzer 子Agent
=====================
核心流程：
1. 分析每个 run：调用 ExtractionAgent 提取指标 → 用模板写 score_analysis.md → 从分析中凝练出 score.json
2. 分析一轮的所有候选：聚合各 run 数据 → 同轮归一化 → 选最优 → 写聚合文件
3. 调用 ProposalAgent 生成优化提案 → 从提案的 problems 提取 gaps 供 OptimizerGateway 使用

评分模式：
- 仅 F1 模式：当 quantitative_names() 仅返回 ['result_score'] 且 normalization='none' 时，
  跳过跨 run 归一化比较，直接使用 F1 分数（已是 0-100 尺度）。
- 多维度模式：对需要归一化的指标做 min-max，已量化指标（如 F1）直接 value/100。
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from metrics.config import MetricsConfig

from .artifact_scanner import ArtifactScanner
from .models import CandidateScore, RawMetric, RoundScore, RunScore
from .normalizer import RoundNormalizer

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _derive_macro_f1(per_case_scores: dict, clip: bool = True) -> Optional[float]:
    """由 per-case 分数算 macro-F1(macro-mean over cases,百分制 0~100,2 位小数)。

    设计原则:
    - 只接受 dict 输入;非数值 / None 跳过。
    - 范围裁剪:默认 clip 到 0~100,避免个别 case 出现 f1>1 的异常值把均值拉爆。
    - 空字典 → 返回 None(框架据此跳过派生,保留 LLM 填的 result_score)。

    用法:_verify_score_json_written() 调用本函数,与 LLM 填的 result_score 交叉校验,
    差 > 0.5 强制覆写。修复 R8 那种"per_case 对、result_score 错"(55.74 vs 真值 62.56)
    的阻塞性 bug。
    """
    if not isinstance(per_case_scores, dict) or not per_case_scores:
        return None
    vals: List[float] = []
    for v in per_case_scores.values():
        if not isinstance(v, (int, float)):
            continue
        x = float(v)
        if clip:
            x = min(max(x, 0.0), 100.0)
        vals.append(x)
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def _compute_aggregate_formula_text(per_case_scores: dict, method: str = "macro_f1") -> dict:
    """由 per_case 字典计算 macro-F1 算式详情(自描述,grep 可读)。

    🆕 2026-08-04 落地:每次 analyze_run 落盘后,framework 都会调本函数把算式
    显式落到 `info._aggregate_formula_text`,任何人 grep 都能看到
    `result_score` 是怎么算的,不再需要 LLM 凭印象填 result_score_raw。

    Returns:
        {
            "method": "macro_f1",
            "formula": "sum(clip(v, 0, 100) for v in per_case_scores.values()) / len(per_case_scores) = (25.00,0.00,...) / 9 = 563.00/9 = 62.56",
            "clip_range": "[0, 100]",
            "decimal_places": 2,
            "sum": 563.0,
            "count": 9,
            "average": 62.56,
            "per_case_values": {"RAN-3404224": 25.0, ...},
            "clipped_values": {"RAN-3404224": 25.0, ...}
        }
    """
    if not isinstance(per_case_scores, dict) or not per_case_scores:
        return {"method": method, "error": "per_case_scores 为空,无法算"}
    vals: List[float] = []
    for v in per_case_scores.values():
        if not isinstance(v, (int, float)):
            continue
        vals.append(float(v))
    if not vals:
        return {"method": method, "error": "per_case_scores 全非数值"}
    clipped = [min(max(v, 0.0), 100.0) for v in vals]
    total = sum(clipped)
    n = len(clipped)
    avg = round(total / n, 2) if n else 0.0
    clipped_str = ",".join(f"{v:.2f}" for v in clipped)
    formula = (
        f"sum(clip(v, 0, 100) for v in per_case_scores.values()) / len(per_case_scores) "
        f"= ({clipped_str}) / {n} = {total:.2f}/{n} = {avg}"
    )
    return {
        "method": method,
        "formula": formula,
        "clip_range": "[0, 100]",
        "decimal_places": 2,
        "sum": round(total, 4),
        "count": n,
        "average": avg,
        "per_case_values": {str(k): float(v) for k, v in per_case_scores.items() if isinstance(v, (int, float))},
        "clipped_values": {str(k): clipped[i] for i, k in enumerate(per_case_scores.keys()) if isinstance(per_case_scores[k], (int, float))},
    }


def _enforce_result_score_zero_override(payload: dict, *, hard_overwrite: bool = True) -> None:
    """result_score 与 per_case 字典的一致性校正（原名 zero_override，已扩展）。

    背景:LLM 按模板约定把顶层 result_score 填 0 占位，真值应由 info.per_case_scores
    的 macro-F1 派生；但也存在 LLM 填了非零错误值的情况（此前只纠正 rs==0 → 漏纠）。

    规则（aggregate 为 macro_f1/mean 时生效，加权聚合业务不受影响）:
    - per_case 字典 derived == 0 → 不动（整轮确实失败）
    - rs == 0 且 derived > 0.5 → 派生覆写（正常路径，INFO 日志）
    - rs > 0 但与 derived 偏差超过 max(2.0, 5%*derived) → 以 per_case 为准覆写（WARN）
    - per_case 字典不存在 → 不动（避免破坏真实 0 分场景）
    """
    if not isinstance(payload, dict):
        return
    rs = payload.get("result_score")
    info = payload.setdefault("info", {})
    if not isinstance(info, dict):
        return
    per_case = info.get("per_case_scores") or info.get("result_score_per_case") or {}
    if not isinstance(per_case, dict) or not per_case:
        return  # per_case 为空,保留 LLM 填的 0
    # 算 derived
    derived = _derive_macro_f1(per_case)
    if derived is None:
        return
    if not isinstance(rs, (int, float)):
        return
    # 真分:derived > 0
    if derived > 0.5:
        _need_override = False
        _reason = ""
        if rs == 0:
            # 模板约定"result_score 填 0 占位,framework 派生"→ 正常路径,不是异常
            _need_override = True
            _reason = "LLM 按模板填 0 占位"
        elif info.get("result_score_aggregate", "macro_f1") in ("macro_f1", "mean"):
            # 非零值也要与 per_case 宏平均保持一致（此前只纠正 rs==0，
            # LLM 填错的正数会被放过）。加权聚合业务不受影响（aggregate 非 macro_f1/mean）。
            _tolerance = max(2.0, 0.05 * derived)
            if abs(float(rs) - derived) > _tolerance:
                _need_override = True
                _reason = f"与 per_case 宏平均偏差 > {_tolerance:.2f}"
        if _need_override:
            if rs == 0:
                print(
                    f"  ℹ️ [score.json] result_score 未填（模板约定 0 占位），"
                    f"framework 按 per_case macro-F1 派生 {derived:.2f}"
                )
            else:
                print(
                    f"  ⚠️ [score.json] result_score={rs} 与 per_case macro-F1={derived:.2f} "
                    f"不一致（{_reason}），以 per_case 为准覆写为 {derived:.2f}"
                )
            payload["result_score"] = derived
            payload["result_score_raw"] = round(derived / 100.0, 4)
            _auto = info.setdefault("_auto_derived", {})
            _auto["result_score_overridden"] = True
            _auto["result_score_stated_by_llm"] = rs
            _auto["result_score_derived"] = derived
            # 写 _aggregate_formula_text 也确保一致
            info["_aggregate_formula_text"] = _compute_aggregate_formula_text(
                per_case, method=info.get("result_score_aggregate", "macro_f1")
            )


def _enforce_result_score_raw_consistency(payload: dict, *, hard_overwrite: bool = True) -> None:
    """🆕 2026-08-04 落地:强制 result_score_raw = result_score / 100。

    之前 R8 那次,LLM 误填 result_score=55.74 / result_score_raw=0.5574 但
    per_case 字典 macro-F1 真值是 62.56,framework 三个字段全失同步。
    现在 _auto_derived 之后立即校验 + 覆写 result_score_raw,
    让 result_score_raw 字段永远是 result_score / 100 的精确反推。

    行为:
    - 差 ≤ 0.001(允许浮点误差)→ 不覆写,只打 info
    - 差 > 0.001 → 强制覆写 + 打 warn(LLM 误填 95% 都是这种)
    """
    if not isinstance(payload, dict):
        return
    rs = payload.get("result_score")
    if not isinstance(rs, (int, float)) or not (0 <= rs <= 100):
        return
    expected_raw = round(float(rs) / 100.0, 4)
    stated_raw = payload.get("result_score_raw")
    if not isinstance(stated_raw, (int, float)):
        stated_raw = 0.0
    delta = abs(float(stated_raw) - expected_raw)
    if delta > 0.001:
        print(
            f"  ⚠️ [score.json] result_score_raw={stated_raw} 与 result_score/100={expected_raw} 差 {delta:.4f} > 0.001,强制覆写"
        )
        payload["result_score_raw"] = expected_raw
        # 在 _auto_derived 里加审计 trail
        info = payload.setdefault("info", {})
        _auto = info.setdefault("_auto_derived", {})
        _auto["result_score_raw_corrected"] = True
        _auto["result_score_raw_stated_by_llm"] = float(stated_raw)
        _auto["result_score_raw_derived"] = expected_raw
    else:
        # 一致时也覆写(确保精度 4 位,避免 LLM 填 0.5574 这种 4 位精度的旧值)
        if hard_overwrite:
            payload["result_score_raw"] = expected_raw


def _auto_fill_evidence_and_resources(score_path: Path, case_ids: list) -> dict:
    """framework 自动从产物目录派生 evidence/token 字典,LLM 不用填这 6 个字典。

    🆕 2026-08-04 设计目标:
    - LLM 只填 per_case_scores / diff_notes / source 3 项(自己 Read 一次能拿到的)
    - gold/llm_output/trace 3 个 absolute path 字典 + token/duration 3 个 per-case 字典
      都由 framework 用 ls+realpath+Read 自动派生
    - 修复 R8 那种"LLM 把 6 个字典全留空,凭印象说"按约定"的阻塞性 bug
    - 业务方 user-config.yaml 的 evidence_paths 段声明 glob 规则,framework 用
      config 驱动而非硬编码

    关键设计:
    - 找不到文件 → 对应 case 的 value 留空(不假造),记入 warnings
    - 覆盖写入 score.json 之前**只** fill 缺失字段,LLM 已填的字段保留
    - 函数幂等:可多次调用,只 fill 缺失部分

    Args:
        score_path: run_dir/score.json
        case_ids: 用户指定 case 白名单

    Returns:
        {
            "filled": {"gold_per_case": [...], "llm_output_per_case": [...], ...},
            "warnings": ["RAN-xxx gold 路径未找到(尝试: R_*.md / 全量_*.md)"],
            "stats": {"found_gold": 9, "found_llm_output": 9, ...}
        }
    """

    summary = {"filled": {}, "warnings": [], "stats": {}}
    if not score_path.exists():
        summary["warnings"].append(f"score_path 不存在:{score_path}")
        return summary

    try:
        payload = json.loads(score_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as _e:
        summary["warnings"].append(f"JSON 解析失败:{_e}")
        return summary
    if not isinstance(payload, dict):
        summary["warnings"].append("score.json 顶层不是 dict")
        return summary
    info_obj = payload.setdefault("info", {})
    if not isinstance(info_obj, dict):
        summary["warnings"].append("info 不是 dict")
        return summary

    run_dir = score_path.parent
    data_dir = run_dir / "data"
    if not data_dir.exists():
        data_dir = run_dir  # 兜底:可能在 run_dir 直下

    # 加载 user-config.yaml 的 evidence_paths 段(若可访问)
    evidence_cfg = _load_evidence_paths()
    gold_subdir = evidence_cfg.get("gold_subdir", "inputs/gold")
    agent_subdir = evidence_cfg.get("agent_subdir", "inputs/agent")
    results_subdir = evidence_cfg.get("results_subdir", "results")
    gold_globs = evidence_cfg.get("gold_filename_glob", ["R_*.md", "全量_*.md"])
    llm_globs = evidence_cfg.get("llm_output_filename_glob", ["C_*.md", "全量_*.md"])

    # 找 case_id 列表:用 score.json 已有的 per_case_scores / result_score_per_case / case_ids
    case_pool: List[str] = list(
        (info_obj.get("per_case_scores") or info_obj.get("result_score_per_case") or {}).keys()
    ) or list(case_ids or [])

    # ── A) gold_per_case / llm_output_per_case / trace_paths_per_case ──
    for dict_key, subdir, globs, file_kind in (
        ("gold_per_case", gold_subdir, gold_globs, "gold"),
        ("llm_output_per_case", agent_subdir, llm_globs, "llm_output"),
    ):
        target = info_obj.setdefault(dict_key, {})
        if not isinstance(target, dict):
            target = {}
            info_obj[dict_key] = target
        filled_count = 0
        for cid in case_pool:
            if target.get(cid):  # LLM 已填
                continue
            case_dirs = sorted(
                d for d in (data_dir / "phase3-eval").iterdir()
                if d.is_dir() and d.name.startswith(f"{cid}_")
            ) if (data_dir / "phase3-eval").exists() else []
            for case_dir in case_dirs:
                inputs_dir = case_dir / subdir
                if not inputs_dir.exists():
                    continue
                # 用 ls 拿真实文件列表
                try:
                    actual_files = sorted(p.name for p in inputs_dir.iterdir() if p.is_file())
                except OSError:
                    continue
                # 用 glob 模式匹配,取第一个
                import fnmatch
                picked = None
                for g in globs:
                    for fname in actual_files:
                        if fnmatch.fnmatch(fname, g):
                            picked = fname
                            break
                    if picked:
                        break
                if not picked:
                    continue
                # realpath 转绝对路径
                src = inputs_dir / picked
                try:
                    rp = src.resolve()
                except OSError:
                    continue
                target[cid] = str(rp)
                filled_count += 1
                break
        summary["stats"][f"found_{file_kind}"] = filled_count
        summary["filled"][dict_key] = filled_count
        if filled_count < len(case_pool):
            missing = [c for c in case_pool if not target.get(c)]
            summary["warnings"].append(
                f"{dict_key}: 缺 {len(missing)}/{len(case_pool)} case 的绝对路径: {missing[:3]}..."
            )

    # trace_paths_per_case:value 是 list of 绝对路径(trace.log 整体轨迹 + subagents/*.jsonl 各 skill 轨迹)
    target = info_obj.setdefault("trace_paths_per_case", {})
    if not isinstance(target, dict):
        target = {}
        info_obj["trace_paths_per_case"] = target
    filled_count = 0
    for cid in case_pool:
        phase2_dir = data_dir / "phase2-exec"
        if not phase2_dir.exists():
            continue
        try:
            matches = sorted(
                d for d in phase2_dir.iterdir()
                if d.is_dir() and d.name.startswith(f"{cid}_")
            )
        except OSError:
            continue
        for case_dir in matches:
            trace_paths = []
            trace_log = case_dir / "trace" / "trace.log"
            if trace_log.exists():
                try:
                    trace_paths.append(str(trace_log.resolve()))
                except OSError:
                    trace_paths.append(str(trace_log))
            run_root = case_dir / "session" / "run"
            if run_root.exists():
                try:
                    for run_dir in sorted(run_root.iterdir()):
                        sa = run_dir / "subagents"
                        if sa.is_dir():
                            for jf in sorted(sa.glob("agent-*.jsonl")):
                                try:
                                    trace_paths.append(str(jf.resolve()))
                                except OSError:
                                    trace_paths.append(str(jf))
                except OSError:
                    pass
            if trace_paths:
                # 兜底补全:与 LLM 已填值合并去重(LLM 常只填 trace.log,这里补上全部 subagents)
                existing = target.get(cid)
                if isinstance(existing, list):
                    target[cid] = list(dict.fromkeys(existing + trace_paths))
                elif isinstance(existing, str):
                    target[cid] = list(dict.fromkeys([existing] + trace_paths))
                else:
                    target[cid] = trace_paths
                filled_count += 1
                break
    summary["stats"]["found_trace"] = filled_count
    summary["filled"]["trace_paths_per_case"] = filled_count

    # ── B) input_tokens_per_case / output_tokens_per_case / duration_ms_per_case ──
    import re as _re

    for dict_key, label, regex, unit_multiplier in (
        ("input_tokens_per_case", "输入Token", r"\|\s*输入Token\s*\|\s*(\d+(?:\.\d+)?)\s*([KMG]?)", 1),
        ("output_tokens_per_case", "输出Token", r"\|\s*输出Token\s*\|\s*(\d+(?:\.\d+)?)\s*([KMG]?)", 1),
        ("duration_ms_per_case", "总耗时", r"\|\s*总耗时\s*\|\s*(\d+)ms", 1),
    ):
        target = info_obj.setdefault(dict_key, {})
        if not isinstance(target, dict):
            target = {}
            info_obj[dict_key] = target
        filled_count = 0
        for cid in case_pool:
            if target.get(cid):
                continue
            case_dirs = sorted(
                d for d in (data_dir / "phase3-eval").iterdir()
                if d.is_dir() and d.name.startswith(f"{cid}_")
            ) if (data_dir / "phase3-eval").exists() else []
            for case_dir in case_dirs:
                results_dir = case_dir / results_subdir
                if not results_dir.exists():
                    continue
                # 找 *Agent性能指标报告.md
                report_files = sorted(p for p in results_dir.glob("*Agent性能指标报告.md"))
                if not report_files:
                    continue
                try:
                    text = report_files[0].read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                m = _re.search(regex, text)
                if not m:
                    continue
                val = float(m.group(1))
                unit = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
                # K → ×1000, M → ×1000_000, G → ×1000_000_000
                multiplier = {"K": 1000, "M": 1_000_000, "G": 1_000_000_000}.get(unit, 1)
                final = int(val * multiplier)
                target[cid] = final
                filled_count += 1
                break
        summary["stats"][f"filled_{dict_key}"] = filled_count
        summary["filled"][dict_key] = filled_count
        if filled_count < len(case_pool):
            missing = [c for c in case_pool if not target.get(c)]
            summary["warnings"].append(
                f"{dict_key}: 缺 {len(missing)}/{len(case_pool)} case: {missing[:3]}..."
            )

    # ── C) 派生 avg_* 和 valid_* count(基于已填 per_case 字典) ──
    def _macro_mean(d: dict) -> tuple:
        vals = [v for v in (d or {}).values() if isinstance(v, (int, float)) and v > 0]
        return (sum(vals) // len(vals) if vals else 0, len(vals))

    for src_key, avg_key, count_key in (
        ("input_tokens_per_case", "avg_input_tokens", "valid_token_case_count"),
        ("output_tokens_per_case", "avg_output_tokens", "valid_token_case_count"),
        ("duration_ms_per_case", "avg_duration_ms", "valid_duration_case_count"),
    ):
        d = info_obj.get(src_key) or {}
        avg, cnt = _macro_mean(d)
        # 只在 LLM 没填 / 填了 0 时覆写
        if not info_obj.get(avg_key):
            info_obj[avg_key] = avg
        if not info_obj.get(count_key):
            info_obj[count_key] = cnt
    # avg_duration_seconds
    if info_obj.get("avg_duration_ms") and not info_obj.get("avg_duration_seconds"):
        info_obj["avg_duration_seconds"] = round(info_obj["avg_duration_ms"] / 1000.0, 2)

    # 落盘
    score_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return summary


def _load_evidence_paths() -> dict:
    """从 user-config.yaml 读 evidence_paths 段,framework 端用 glob 驱动 evidence 派生。

    兼容多份 user-config.yaml(实际运行版 + 规范源),失败时返回合理默认值。
    """
    candidates = [
        Path("/media/vdb/skillx-alpha/cosight-agent-core-skillx-alpha/config/evolve-user-config.yaml"),
        Path("/media/vdb/skillx-alpha/skillx-alpha-agents/config/evolve-user-config.yaml"),
    ]
    for cfg_path in candidates:
        if not cfg_path.exists():
            continue
        try:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            ep = (data or {}).get("evidence_paths") or {}
            if ep:
                # 把 list 字段转 list(str),yaml 默认已是 list
                return {
                    "gold_subdir": str(ep.get("gold_subdir", "inputs/gold")),
                    "agent_subdir": str(ep.get("agent_subdir", "inputs/agent")),
                    "results_subdir": str(ep.get("results_subdir", "results")),
                    "gold_filename_glob": list(ep.get("gold_filename_glob", ["R_*.md", "全量_*.md"])),
                    "llm_output_filename_glob": list(ep.get("llm_output_filename_glob", ["C_*.md", "全量_*.md"])),
                }
        except Exception:
            continue
    return {
        "gold_subdir": "inputs/gold",
        "agent_subdir": "inputs/agent",
        "results_subdir": "results",
        "gold_filename_glob": ["R_*.md", "全量_*.md"],
        "llm_output_filename_glob": ["C_*.md", "全量_*.md"],
    }

# ProposalAgent 业务配置默认路径（可通过 PROPOSAL_AGENT_CONFIG 环境变量覆盖）
DEFAULT_PROPOSAL_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "framework_configs" / "proposal-agent-config.yaml"
)


class ScoreAnalyzerAgentBase:
    """评分分析子 Agent 的基类，定义共用初始化与辅助方法。"""

    def __init__(self, metrics_config: Optional[MetricsConfig] = None):
        self.metrics_config = metrics_config or MetricsConfig.load()
        self.scanner = ArtifactScanner()  # 兜底回退
        self._proposal_cfg: dict = self._load_proposal_agent_config()  # 业务配置一次性加载

    # ─── Skill 文件路径扫描 ───

    @staticmethod
    def _collect_all_round_dirs(round_dir: Path) -> List[Path]:
        """从 round_dir 向上找到 workspace_root，枚举 baseline/ + 所有 round_*/。

        目的：proposal.md 的"文件覆盖清单"扫描**所有已完成的轮次**产物，
        让优化提案能吸收 baseline 与此前所有 round 的产物经验。

        - round_dir = baseline/                  → [baseline/]
        - round_dir = round_N/                  → [baseline/, round_1/, ..., round_N/]
        - round_dir = round_N/candidate_K/      → [baseline/, round_1/, ..., round_N/]
          (candidate 是 round_N 的子目录；round_N 整体扫描已覆盖所有候选)
        - round_dir = best_skill/ 等其他顶层 dir → [round_dir]（兜底，非预期）

        返回路径列表；调用方按需扫描每个 dir 的产物。
        """
        # 向上找含 baseline/ 的最近祖先 = workspace_root
        workspace_root = round_dir
        visited = set()
        while workspace_root != workspace_root.parent and workspace_root not in visited:
            visited.add(workspace_root)
            if (workspace_root / "baseline").exists():
                break
            workspace_root = workspace_root.parent
        else:
            # 兜底：找不到 baseline/ 视为单层（如 best_skill/），返回 [round_dir]
            return [round_dir]

        dirs: List[Path] = []
        baseline_dir = workspace_root / "baseline"
        if baseline_dir.exists():
            dirs.append(baseline_dir)
        for rd in sorted(workspace_root.glob("round_*")):
            if rd.is_dir():
                dirs.append(rd)
        return dirs


    @staticmethod
    def _scan_layer_artifacts(layer_dir: Path, scope: str = "baseline") -> List[Dict[str, str]]:
        """扫描层目录（baseline/ 或 round_N/candidate_K/）下的所有产物文件。

        产物范围：
        - score_baseline.json（baseline 级 JSON 汇总，含完整 13 个资源字段+ stddev/cv/per_run_f1）
        - proposal.md / _proposal/stage_{1,2,3}_*.json（提案产物）
        - run_*/data/**（phase1-build/phase2-exec/phase3-eval/phase4-diagnosis 产物）
        - 注：删除了 score_baseline_analysis.md 生成 — score_baseline.json 已含完整数据（结构化、机器可读），冗余 MD 无意义
        - run_*/logs/eval_*.log（eval-cmd stdout/stderr 日志）
        - run_*/score.json / score_analysis.md（run 级评分）

        返回 [{file, status, reason}, ...] 列表，用于补充 LLM coverage 缺漏。
        file 为相对 layer_dir 的路径，状态默认 unchanged（产物不被 orchestrator 改写）。
        """
        artifacts = []
        if not layer_dir.exists():
            return artifacts

        # layer_dir 顶层文件（baseline_score.json / score_baseline.* / proposal.md）
        for p in sorted(layer_dir.iterdir()):
            if p.is_file() and not p.name.startswith(".") and p.suffix in (".json", ".md"):
                rel = p.name
                if p.name == "proposal.md":
                    reason = "本轮优化提案；LLM 生成产物"
                elif p.name.startswith("score_baseline"):
                    reason = "本轮评分聚合（baseline 级）；框架纯代码生成"
                else:
                    reason = "产物文件"
                artifacts.append({"file": rel, "status": "unchanged", "reason": reason})

        # _proposal/ 内部 stage JSON
        proposal_subdir = layer_dir / "_proposal"
        if proposal_subdir.exists():
            for p in sorted(proposal_subdir.rglob("*")):
                if p.is_file():
                    rel = str(p.relative_to(layer_dir))
                    if "stage_1" in p.name:
                        reason = "Stage 1 上下文：扫描 data/ + skills + 失败统计"
                    elif "stage_2" in p.name:
                        reason = "Stage 2 缺口分析：从 Stage 1 提炼可优化 gap"
                    elif "stage_3" in p.name:
                        reason = "Stage 3 修改建议：每个 gap 对应 file/section/current/new_content"
                    else:
                        reason = "提案中间产物"
                    artifacts.append({"file": rel, "status": "unchanged", "reason": reason})

        # run_*/ 子目录：data/, logs/, score.json, score_analysis.md
        for run_dir in sorted(layer_dir.glob("run_*")):
            if not run_dir.is_dir():
                continue
            run_idx = run_dir.name.split("_")[1]
            # data/phase{1,2,3,4}-*/** （沙箱归档）
            data_dir = run_dir / "data"
            if data_dir.exists():
                # 阶段目录加一个汇总条目；其下具体 JSON 在 LLM 阶段 1 探查
                for phase_dir in sorted(data_dir.glob("phase*")):
                    rel = str(phase_dir.relative_to(layer_dir))
                    artifacts.append({"file": rel, "status": "archived", 
                                     "reason": f"run {run_idx} 沙箱归档（仅 score 提取阶段读取，optimize 阶段不修改）"})
            # logs/eval_*.log
            logs_dir = run_dir / "logs"
            if logs_dir.exists():
                for log in sorted(logs_dir.glob("*.log")):
                    rel = str(log.relative_to(layer_dir))
                    artifacts.append({"file": rel, "status": "captured",
                                     "reason": f"run {run_idx} eval-cmd stdout/stderr（fire-and-poll 落盘）"})
            # score.json + score_analysis.md
            for fname in ("score.json", "score_analysis.md"):
                fp = run_dir / fname
                if fp.exists():
                    rel = str(fp.relative_to(layer_dir))
                    reason = "score.json: LLM 提取器写入（per-run 评分）" if fname == "score.json" else "score_analysis.md: LLM 端到端分析"
                    artifacts.append({"file": rel, "status": "unchanged", "reason": reason})

        return artifacts


    @staticmethod
    def _find_skill_paths(data_dir: Path, round_dir: Path) -> list:
        """扫描并返回所有 Skill 文件路径列表。

        从多个可能的位置搜索 SKILL.md 及相关文件，
        返回已确认存在的路径列表，注入给子 Agent 的 prompt。

        路径层级（以 data_dir 为起点）：
        - data_dir/../skill/           → candidate_K/skill/ 或 round_N/skill/（单 Skill 模式）
        - data_dir/../../skill/        → round_N/skill/（兜底）
        - data_dir/../../../skill/     → workspace/skill/（实际存放位置，最兜底）
        - round_dir/skill/ 或 skills/  → 从 round_dir 直接搜索

        去重策略：按文件相对路径去重（如 "特性域变更分析/SKILL.md"），
        优先保留最靠近 data_dir 的副本（candidate 级别优先）。
        """
        paths = []

        # 从 data_dir 逐级向上搜索（覆盖 run → candidate → workspace 三层）
        # 越近的路径越先搜索，保证 candidate 级别路径在前面
        parent = data_dir
        for _ in range(4):
            parent = parent.parent
            if not parent.exists():
                continue
            for sub in ["skill", "skills"]:
                base = parent / sub
                if base.exists() and base.is_dir():
                    for p in base.rglob("*"):
                        if p.is_file():
                            paths.append(str(p))

        # 从 round_dir 根级直接搜索（兜底）
        for sub in ["skill", "skills"]:
            base = round_dir / sub
            if base.exists() and base.is_dir():
                for p in base.rglob("*"):
                    if p.is_file():
                        paths.append(str(p))

        # 从 round_dir 下的 round_N_before_skill/skill/ 搜索(方案 B 已删 after_skill 写盘)
        for base in round_dir.glob("*_before_skill/skill"):
            if base.exists() and base.is_dir():
                for p in base.rglob("*"):
                    if p.is_file():
                        paths.append(str(p))

        # 去重：按文件相对路径（skill_name/file）去重，保留最先找到的（最近路径）
        seen_rel = set()
        unique = []
        for p in paths:
            # 提取相对路径：从第一个 skill/skills 目录开始的部分
            rel = p
            for marker in ["/skill/", "/skills/"]:
                idx = rel.find(marker)
                if idx >= 0:
                    rel = rel[idx + len(marker):]  # 如 "特性域变更分析/SKILL.md"
                    break
            if rel not in seen_rel:
                seen_rel.add(rel)
                unique.append(p)

        # 不限制返回数量：让 LLM 看到 Skill 目录下的所有文件
        return unique

    # ─── 模式检测 ───

    def _is_only_f1_mode(self) -> bool:
        """检测是否仅使用 result_score 作为量化指标。"""
        quant_names = self.metrics_config.quantitative_names()
        return len(quant_names) == 1 and quant_names[0] == "result_score"

    # ─── ProposalAgent 业务配置加载 ───
    # 业务方通过 examples/proposal-agent-config.yaml 自定义所有 prompt/gap 提取逻辑。
    # 框架不感知任何业务字段，只做通用加载 + jinja 渲染 + 分发 extractor。

    def _load_proposal_agent_config(self, path: Optional[Path] = None) -> dict:
        """加载 ProposalAgent 业务配置 YAML。返回 dict,失败时返回 {}。

        路径优先级: 参数 > 环境变量 > 默认 examples/proposal-agent-config.yaml
        """
        config_path = (
            Path(path)
            if path
            else Path(os.environ.get("PROPOSAL_AGENT_CONFIG", DEFAULT_PROPOSAL_CONFIG_PATH))
        )
        if not config_path.exists():
            print(f"  [ProposalConfig] 配置文件不存在: {config_path}，将使用空配置（gap 提取与 prompt 渲染退化为跳过）")
            return {}
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            print(f"  [ProposalConfig] 已加载业务配置: {config_path}")
            return cfg
        except Exception as e:
            print(f"  [ProposalConfig] 加载失败 ({type(e).__name__}: {e})，使用空配置")
            return {}

    @staticmethod
    def _render_template(template: str, **kwargs) -> str:
        """jinja 风格占位符渲染：仅支持 {{ var_name }},不支持控制流/过滤器。

        未定义的占位符(典型如 `{{ user.xxx }}`,框架未注入 user 配置时)用
        ChainableUndefined 软退化(渲染为空串),避免子 Agent 因单个未渲染占位符
        整个 stage 失败。
        """
        if not template:
            return ""
        try:
            from jinja2 import ChainableUndefined, Environment
            return (
                Environment(undefined=ChainableUndefined)
                .from_string(template)
                .render(**kwargs)
            )
        except ImportError:
            # 退化: 简单 str.replace,业务方字段名不带花括号
            out = template
            for k, v in kwargs.items():
                out = out.replace("{{ " + k + " }}", str(v))
            return out

    def _render_focus_block(self, cfg: dict, only_f1: bool) -> str:
        """按 only_f1 选 focus_blocks 中对应 block。"""
        blocks = cfg.get("focus_blocks") or {}
        key = "f1_focus" if only_f1 else "general_focus"
        return blocks.get(key, "")

    def _build_anti_overfitting_text(self, cfg: dict) -> str:
        """渲染 anti_overfitting_rules 列表为有序文本。"""
        rules = cfg.get("anti_overfitting_rules") or []
        rendered = [self._render_template(r) for r in rules]
        return "\n".join(f"{i+1}. {r}" for i, r in enumerate(rendered) if r)

    def _render_proposal_prompt_round(self, cfg: dict, context: dict,
                                      data_dir: Path, skill_files_rel: list,
                                      round_dir: Path) -> str:
        """渲染「轮次级/baseline 级」的多阶段 prompt(4 阶段拆分 + 输出格式)。"""
        only_f1 = self._is_only_f1_mode()

        focus_block = self._render_focus_block(cfg, only_f1)
        anti_text = self._build_anti_overfitting_text(cfg)

        sections = cfg.get("prompt_sections") or {}
        stage_1 = self._render_template(
            sections.get("stage_1_load_context", ""),
            data_dir=str(data_dir),
            skill_files_rel=json.dumps(sorted(skill_files_rel), ensure_ascii=False, indent=2),
        )
        stage_2 = sections.get("stage_2_identify_gaps", "")
        stage_3 = self._render_template(
            sections.get("stage_3_translate_to_mods", ""),
        )
        stage_4 = self._render_template(
            sections.get("stage_4_self_check", ""),
            anti_overfitting_rules_text=anti_text,
        )
        output_fmt = self._render_template(cfg.get("output_format", ""))

        return (
            f"你是一名 Skill 优化专家。下面采用**多阶段拆分**方式逐步完成提案——\n"
            f"请**严格按顺序**走完每个阶段,不要跳步、不要在 Stage 1 之前就开始写 modification。\n\n"
            f"{focus_block}"
            f"## 评分上下文\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
            f"---\n\n"
            f"{stage_1}\n---\n\n"
            f"{stage_2}\n---\n\n"
            f"{stage_3}\n---\n\n"
            f"{stage_4}\n---\n\n"
            f"{output_fmt}"
        )

    def _render_proposal_prompt_candidate(self, cfg: dict, context: dict,
                                          data_dir: Path, skill_files_rel: list,
                                          cand_dir: Path, round_num: int, cand_id: int) -> str:
        """渲染「单 candidate」prompt(精简版,给 LLM 自由度)。"""
        only_f1 = self._is_only_f1_mode()
        focus_block = self._render_focus_block(cfg, only_f1)

        sections = cfg.get("prompt_sections") or {}
        render_ctx = dict(
            round_num=round_num,
            cand_id=cand_id,
            focus_block=focus_block,
            context=json.dumps(context, ensure_ascii=False, indent=2),
            data_dir=str(data_dir),
            skill_files_rel=json.dumps(sorted(skill_files_rel), ensure_ascii=False, indent=2),
            cand_dir=str(cand_dir),
        )
        intro = self._render_template(
            sections.get("candidate_mode_intro", ""),
            **render_ctx,
        )
        # candidate_output_format 也支持 {{ cand_dir }} 等占位符(LLM 需要知道写到哪里)
        output_fmt = self._render_template(
            cfg.get("candidate_output_format", ""),
            **render_ctx,
        )
        prompt = (intro + "\n" + output_fmt).strip()
        if not prompt:
            # 配置缺 candidate_mode_intro / candidate_output_format 时的最小兜底。
            # 否则空 prompt 会让 claude -p 直接失败（Input contained only whitespace）。
            prompt = (
                f"你是 Skill 优化提案生成器，任务：针对 candidate_{cand_id}"
                f"（round {round_num}）生成并落地优化方案。\n\n"
                f"## 上下文\n{render_ctx['context']}\n\n"
                f"## 评测产物目录\n{data_dir}\n\n"
                f"## 待优化 Skill 副本\n{cand_dir}\n\n"
                f"## 要求\n"
                f"1. 先 Read 评测产物（score.json / summary.json / outputs.jsonl / goldeval 结果等）确认失分点；\n"
                f"2. 用 Edit/Write 直接修改 {cand_dir} 下的 SKILL.md 或 scripts/*.py；\n"
                f"3. 必须把改动摘要写入 {cand_dir}/optimization_summary.md（不落盘视为失败）。\n"
            )
        return prompt

    # ─── Gap 提取器分发 ───
    # 兜底:LLM ProposalAgent 返回空 problems 时,从结构化诊断数据补 gap。
    # 全部 extractors 都是声明式 YAML 配置,框架按 type 分发。
    # 框架只实现通用的「从嵌套 dict 取值」和「从 JSON 文件读嵌套字段」两种原始操作。
    # 业务方在 YAML 里配置:从哪个 info 字段、读哪个 JSON 文件、取哪个嵌套路径。
    # 框架代码不引用任何具体业务字段名(phase3-eval / common_causes / zero_root_cause 等)。

    def _apply_gap_extractors(self, runs: list, cfg: dict) -> list:
        """按 cfg.gap_extractors 顺序执行,合并所有 enabled=true 的提取器结果。

        返回统一 schema 的 gap list,按 root_cause 文本去重,供下游 OptimizerGateway 使用。
        """
        extractors = cfg.get("gap_extractors") or []
        if not extractors:
            return []

        all_gaps: list = []
        for ex in extractors:
            if not ex.get("enabled", True):
                continue
            ex_type = ex.get("type", "")
            try:
                if ex_type == "from_info_field":
                    gaps = self._extract_gaps_from_info_field(runs, ex)
                elif ex_type == "from_run_json":
                    gaps = self._extract_gaps_from_run_json(runs, ex)
                else:
                    print(f"  [GapExtractor] 未知 type={ex_type}，跳过")
                    continue
                all_gaps.extend(gaps)
            except Exception as e:
                print(f"  [GapExtractor] {ex.get('name', ex_type)} 失败: {type(e).__name__}: {e}")

        # 按 root_cause 文本去重
        deduped: list = []
        seen: set = set()
        for g in all_gaps:
            rc = g.get("root_cause", "")
            if rc in seen:
                continue
            seen.add(rc)
            deduped.append(g)
        return deduped

    @staticmethod
    def _dig_path(d: dict, path: str):
        """按 'a.b.c' 路径从嵌套 dict 中取值。任意一段缺失则返回 None。"""
        cur = d
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def _extract_gaps_from_info_field(self, runs: list, ex: dict) -> list:
        """从 run.raw.info[field_path] 提取 gap。field_path 完全由 YAML 配置。

        info 是 RunScore 的内嵌 dict,评测时已写入(run.raw.info)。
        业务方在 YAML 中指定要提取哪个嵌套字段路径,框架不引用任何具体业务字段名。
        """
        field_path = ex.get("field_path", "")
        if not field_path:
            return []

        gaps = []
        for r in runs:
            info = r.raw.info or {}
            val = self._dig_path(info, field_path)
            if not val or not isinstance(val, str):
                continue
            gaps.append({
                "type": ex.get("gap_type", "zero_score_root_cause"),
                "severity": ex.get("severity", "critical"),
                "scope": ex.get("scope", "systemic"),
                "message": val,
                "root_cause": val,
                "fix_suggestion": ex.get("fix_suggestion", ""),
            })
        return gaps

    def _extract_gaps_from_run_json(self, runs: list, ex: dict) -> list:
        """从 run.data_dir 下的某 JSON 文件的嵌套字段提取 gap。

        参数(YAML 配置):
          json_glob:    run.data_dir 下的 glob 模式(如 'phase*-eval/*/results/*.json')
          field_path:   JSON 内的嵌套字段路径(如 'differences.0.root_cause')
          item_strategy: 'first' / 'all' / 'per_file' (默认 first: 每个 run 取第一个匹配文件)
        """
        json_glob = ex.get("json_glob", "")
        field_path = ex.get("field_path", "")
        if not json_glob or not field_path:
            return []

        gaps = []
        for r in runs:
            data_dir = Path(r.analysis_path).parent / "data" if r.analysis_path else None
            if not data_dir or not data_dir.exists():
                continue
            for json_path in sorted(data_dir.glob(json_glob)):
                try:
                    payload = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                val = self._dig_path(payload, field_path)
                if not val or not isinstance(val, str):
                    continue
                gaps.append({
                    "type": ex.get("gap_type", "evaluation_diff"),
                    "severity": ex.get("severity", "critical"),
                    "scope": ex.get("scope", "systemic"),
                    "message": val,
                    "root_cause": val,
                    "fix_suggestion": ex.get("fix_suggestion", ""),
                    "evidence_path": str(json_path),
                })
        return gaps

    # ─── failure_layer 关键词兜底分类器(Stage 2 后置) ───

    # 兜底匹配顺序:pipeline_* 先匹配(避免被通用 skill 关键词抢占),skill 最后
    _FAILURE_LAYER_ORDER: tuple = (
        "pipeline_artifact",
        "pipeline_unit",
        "pipeline_input",
        "pipeline_eval",
        "skill",
    )

    def _apply_failure_layer_classifier(self, gaps: list, cfg: dict) -> list:
        """按 cfg.failure_layer_keywords 关键词兜底分类 failure_layer=unknown 的 gap。

        仅 LLM/gap_extractor 填 unknown(或不填)时启用,LLM 已填具体 layer 的 gap 不被覆盖。
        关键词匹配:子串包含(避免空格/标点歧义),先匹配先得(pipeline 类优先于 skill 兜底)。
        匹配后自动:
          - gap.failure_layer = matched_layer
          - gap.unsolvable_by_skill = (matched_layer != "skill")
        """
        keywords_cfg = cfg.get("failure_layer_keywords")
        if not isinstance(keywords_cfg, dict) or not keywords_cfg or not gaps:
            return gaps

        matched_count = 0
        for g in gaps:
            if not isinstance(g, dict):
                continue
            existing = str(g.get("failure_layer", "") or "").strip()
            if existing and existing != "unknown":
                continue  # LLM 已填具体 layer,不覆盖

            # 拼接要匹配的文本: root_cause + description + message
            text = " ".join([
                str(g.get("root_cause", "") or ""),
                str(g.get("description", "") or ""),
                str(g.get("message", "") or ""),
            ]).strip()
            if not text:
                continue

            layer_match = None
            for layer_name in self._FAILURE_LAYER_ORDER:
                kw_list = keywords_cfg.get(layer_name) or []
                if not isinstance(kw_list, (list, tuple)):
                    continue
                for kw in kw_list:
                    if kw and isinstance(kw, str) and kw in text:
                        layer_match = layer_name
                        break
                if layer_match:
                    break

            if layer_match:
                g["failure_layer"] = layer_match
                g["unsolvable_by_skill"] = (layer_match != "skill")
                matched_count += 1
            else:
                # 兜底也没匹配上:显式标 unknown(若尚未填)+ unsolvable_by_skill=false
                g.setdefault("failure_layer", "unknown")
                g.setdefault("unsolvable_by_skill", False)

        if matched_count > 0:
            print(f"  [FailureLayerClassifier] 关键词兜底分类 {matched_count}/{len(gaps)} 个 gap")
        return gaps

    # ─── 子 Agent 调用 ───

    def _analyze_with_agent(
        self,
        data_dir: Path,
        template_path: Path,
        output_kind: str,
        extraction_task: str,
        case_ids: Optional[list] = None,
    ) -> str:
        """LLM 填空:喂一个模板 → 调 LLM → 抽 fence → 返回填好的内容。

        框架 0 硬计算:不扫文件、不算分、不填模板、不绑死字段名。
        业务方提供:模板文件 + YAML 业务任务描述。
        LLM 自主探查 data_dir,自己写数学算式,把结果填进模板。
        LLM 用 ```fenced code block``` 包裹填好的内容输出。
        框架用 fence 抽取器取出内容,落盘到对应文件。

        对 output_kind == "json" 额外做:语法校验 → 失败时调 LLM 修复 → 多次失败兜底空对象。

        Args:
            data_dir: 评测产物目录
            template_path: 模板文件路径(md 或 json)
            output_kind: "md" 或 "json",仅用于日志/提示
            extraction_task: YAML 中的自然语言业务任务
            case_ids: 用户指定的 CASE 白名单(可选)

        Returns: 模板填写后的字符串(已抽离 fence)。LLM 未产出 fence 时返回空串/json 失败时返回 {}。
        """
        # 1) 读模板
        template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""

        # 2) 拼 prompt
        case_ids_line = ", ".join(case_ids) if case_ids else "(全量,未指定)"
        lang_hint = "markdown" if output_kind == "md" else "json"
        prompt = (
            f"你是评测分析师。完成一件事:把评测结果填入下方模板。\n\n"
            f"## 业务任务(YAML 描述,业务差异都在这里)\n"
            f"{extraction_task}\n\n"
            f"## 模板(严格按此填写,所有 <...> 占位符都要替换成实际内容)\n"
            f"{template}\n\n"
            f"## 评测产物目录\n"
            f"{data_dir}\n\n"
            f"## 用户指定的 CASE 白名单(可选)\n"
            f"{case_ids_line}\n\n"
            f"## 输出格式(硬约束:必须用围栏包裹,违反则任务失败)\n"
            f"**必须**把你填写完整的模板内容,放在唯一一对 ```{lang_hint} ... ``` 围栏代码块里。\n"
            f"**禁止**输出裸 JSON / 裸 Markdown,框架的抽取函数只认围栏代码块。\n"
            f"**禁止**输出多个围栏(```markdown 和 ```json 不能在同一份输出里)。\n"
            f"围栏外可以有 1 行简短说明(如\"已按要求填好模板\"),但**围栏内必须是完整模板**。\n"
            f"围栏示例:\n"
            f"```{lang_hint}\n<填好的完整模板内容>\n```\n"
        )

        # 🆕 证据路径重试提示:analyze_run REWORK 时,force 重跑注入上次失效路径清单,
        # 让 LLM 明确知道上次填了不存在的路径,本次必须先 ls 探查实际产物再填真实路径。
        import os as _os_rh
        _retry_hint = _os_rh.environ.get("SKILLX_EVIDENCE_RETRY_HINT", "").strip()
        if _retry_hint:
            prompt += (
                "\n## ⚠️ 上次证据路径失效(本次必须修正)\n"
                f"上次填写的证据路径指向**不存在的文件**:{_retry_hint}\n"
                "**本次必须先 `ls` 探查实际产物目录,再填真实的、存在的绝对路径**。\n"
                "禁止按约定文件名猜(如 R_*.md 不存在时,改用实际存在的 全量_*.md / gold.md / req_design_document.md 等)。\n"
            )

        # 3) 调 LLM(带重试:deepseek API 偶发 provider_response_error)
        result = _call_agent_with_retry(
            max_retries=3,
            mode="auto",
            description=f"分析 {data_dir} 的评测结果并填充{output_kind}模板",
            subagent_type=self.metrics_config.get_extractor_agent(),
            prompt=prompt,
        )

        # 4) 用 fence 抽取填好的内容
        content = _extract_fenced_block(result, lang_hint) or ""

        # 4.0) 🆕 2026-08-01 根治:content 为空时从 _debug 日志抽 JSON(stage 4)
        # 背景:实测 taskid_20260801_073320 frame 3 fence 抽取失败 → score.json 0 字节
        # 修复:从最新 _debug/agent_*.txt 的 ## raw_jsonl / ## STDOUT 段抓 LLM 真输出
        # 优先级:raw_jsonl 段 > STDOUT 段 > 当前 result
        if not content:
            import os as _os
            _debug_dir = _os.environ.get("SKILLX_CURRENT_TASK_DIR", "")
            if _debug_dir:
                _log_files = sorted(
                    Path(_debug_dir).glob("agent_*.txt"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                for _log in _log_files:
                    _log_text = _log.read_text(encoding="utf-8", errors="replace")
                    # 优先 raw_jsonl 段
                    _m = re.search(r"## raw_jsonl \(begin\)(.*?)## raw_jsonl \(end\)", _log_text, re.DOTALL)
                    if _m:
                        _seg = _m.group(1)
                        for _line in _seg.splitlines():
                            _line = _line.strip()
                            if not _line:
                                continue
                            try:
                                _obj = json.loads(_line)
                            except json.JSONDecodeError:
                                continue
                            # 找包含 result_score/info 的完整 JSON 对象
                            if isinstance(_obj, dict) and ("result_score" in _obj or "info" in _obj):
                                # 可能是嵌套的 message.content [{}]
                                if "info" in _obj:
                                    content = json.dumps(_obj, ensure_ascii=False)
                                else:
                                    # 找内层的 assistant 消息
                                    _msg = _obj.get("message", {})
                                    if isinstance(_msg, dict):
                                        _cont = _msg.get("content")
                                        if isinstance(_cont, list):
                                            for _blk in _cont:
                                                if isinstance(_blk, dict) and _blk.get("type") == "text":
                                                    if "result_score" in _blk.get("text", "") or '"info"' in _blk.get("text", ""):
                                                        content = _blk["text"]
                                                        break
                                if content:
                                    break
                    if content:
                        print(f"  [score.json] 从 _debug {Path(_log).name} 的 raw_jsonl 段抽出 JSON")
                        break
                    # 退路:STDOUT 段
                    _m2 = re.search(r"## STDOUT \(begin\)(.*?)## STDOUT \(end\)", _log_text, re.DOTALL)
                    if _m2:
                        _seg2 = _m2.group(1)
                        # 找最后一个 ```json ... ``` 块
                        _matches = re.findall(r"```json\s*\n(.*?)\n```", _seg2, re.DOTALL)
                        if _matches:
                            content = _matches[-1].strip()
                            print(f"  [score.json] 从 _debug {Path(_log).name} 的 STDOUT 最后一个 \`\`\`json 块抽出 JSON")
                            break

        # 4.5) Fence 抽取失败时重试一次:让 LLM 明确"围栏独立成行"
        #     原因:LLM 有时把 ```` ```json ```` 紧接在前文后(``...结果 0.5。  ```json{...}``)
        #     导致正则 `` ```json\s*\n `` 抽不到。重试时明确独立成行 + 前后空行。
        if not content and result:
            print(f"  ⚠️ LLM 未产出 ```{lang_hint} 代码块,触发 fence 重试(独立成行强化)")
            preview = (result or "")[:500].replace("\n", " ")
            print(f"  [debug] 第 1 次输出预览: {preview!r}")
            fence_retry_prompt = self._build_fence_retry_prompt(
                lang_hint, data_dir, template, case_ids, extraction_task, result
            )
            result2 = Agent(
                mode="auto",
                description=f"[重试] 分析 {data_dir} 并填充{output_kind}模板",
                subagent_type=self.metrics_config.get_extractor_agent(),
                prompt=fence_retry_prompt,
            )
            content = _extract_fenced_block(result2, lang_hint) or ""
            if content:
                print(f"  ✅ Fence 重试成功,继续 {output_kind} 抽取")
            else:
                print(f"  ❌ Fence 重试仍失败,{output_kind} 文件将为空")
                preview2 = (result2 or "")[:500].replace("\n", " ")
                print(f"  [debug] 第 2 次输出预览: {preview2!r}")

        if not content:
            print(f"  ⚠️ LLM 未产出 ```{lang_hint} 代码块,{output_kind} 文件将为空")
            preview = (result or "")[:500].replace("\n", " ")
            print(f"  [debug] LLM 输出预览(前 500 字符): {preview!r}")
            return content

        # 5) JSON 额外步骤:语法校验 + LLM 修复
        if output_kind == "json":
            # 🆕 2026-08-01 根治:content 含 `_comment_X` 字段时,先剥掉再 json.loads
            # 实测 taskid_20260801_073320/0006:LLM 把 JSON 填在 templates 的 ```json ... ``` 块内,
            # 模板的 `_comment_1: "本 JSON 是合法模板,LLM 只需把下方零值占位符(0/0.0/"")" ` 字段
            # 含半角双引号嵌套,破坏整体 JSON 语法。修复:抽 fence 后剥 `_comment_X` 字段
            # (这些是模板注释,不是 LLM 实际输出,不应进 score.json)
            content = self._strip_template_comments(content)
            content = self._validate_and_fix_json(content, template, data_dir, case_ids, extraction_task)
        return content

    def _strip_template_comments(self, content: str) -> str:
        """🆕 2026-08-01 抽 fence 后剥 `_comment_X` 字段(模板注释,不是 LLM 真输出)。

        模板 score.json 包含 `_comment_1` ~ `_comment_6` 字段含半角双引号嵌套,
        LLM 填字段后整体 JSON 语法破坏(json.loads 失败)。修复:在 fence 抽取后
        json.loads 前,正则剥 `"_comment_X": "..."` 字段(类似 SQL 注释清理)。
        """
        # 匹配 "key": "value"(value 可含 \n \\ \" 但 key 是 _comment_X 固定)
        # 简化:剥所有 `"_comment_X": "...",?` 字段(value 可含 \n 但不含未转义的 ")
        # 用更简单写法:找 "_comment_X": " 到匹配的 " (跳过 \\"),
        # 边界:前一个 , 或 { 或首,后一个 , 或 } 或尾
        out = content
        # 迭代剥,直到没匹配
        for _ in range(10):  # 最多剥 10 层嵌套
            pattern = re.compile(
                r'[\n,]\s*"_comment_\d+"\s*:\s*"',
                re.MULTILINE,
            )
            m = pattern.search(out)
            if not m:
                break
            # 从 m.end() 位置找匹配的 "
            i = m.end()
            depth = 0
            while i < len(out):
                if out[i] == "\\" and i + 1 < len(out):
                    i += 2
                    continue
                if out[i] == '"':
                    if depth == 0:
                        # 找完整字符串结束 → 跳过 "," 或 "}"
                        i += 1
                        while i < len(out) and out[i] in " \t":
                            i += 1
                        if i < len(out) and out[i] == ",":
                            i += 1
                        # 删 _comment_X...这一段
                        out = out[:m.start()] + out[i:]
                        break
                    depth -= 1
                elif out[i] == "(":
                    depth += 1
                elif out[i] == ")":
                    depth -= 1
                i += 1
            else:
                break
        return out

    def _build_fence_retry_prompt(
        self,
        lang: str,
        data_dir: Path,
        template: str,
        case_ids: Optional[list],
        extraction_task: str,
        prev_output: str,
    ) -> str:
        """Fence 抽取失败时的重试 prompt。强调围栏独立成行 + 前后空行。"""
        case_ids_line = ", ".join(case_ids) if case_ids else "(全量,未指定)"
        return (
            f"你之前的输出**抽不到围栏**,框架没拿到填好的模板,**任务失败**。\n\n"
            f"## 失败原因(已诊断)\n"
            f"你把 ```` ```{lang} ```` 紧接在前文后(如 ``...结果 0.5。  ```{lang}{{...}}``),\n"
            f"导致正则 `` ```lang\\s*\\n `` 不匹配。**必须重试,围栏严格独立成行**。\n\n"
            f"## 铁律(硬约束,违反仍然失败)\n"
            f"1. 围栏开始前**必须有换行**(`\\n`),让 ```` ```{lang} ```` 独占一行\n"
            f"2. 围栏内**第一个字符**必须是模板内容(不是空格、不是 `{{`)\n"
            f"3. 围栏结束 ` ``` ` **独占一行**,前后都有换行\n"
            f"4. **整份输出只能有一对外层围栏**(```markdown 或 ```{lang}),不要再嵌套任何 ``` 块\n\n"
            f"## 围栏铁律示例(严格按此格式)\n"
            f"```\n"
            f"已按要求填好 {lang} 模板。\n\n"
            f"```{lang}\n"
            f"<填好的完整模板内容,第一个字符直接是模板字段>\n"
            f"```\n"
            f"```\n\n"
            f"**注意**:上面这个外层示例是普通代码块(无 `{lang}` 标签),不要混淆。\n"
            f"实际输出时,**只用一对 ```` ```{lang} ```` 围栏**,把模板内容完整放进去。\n\n"
            f"## 业务任务(同上)\n"
            f"{extraction_task}\n\n"
            f"## 模板(原样,只填字段不发明)\n"
            f"{template}\n\n"
            f"## 评测产物目录\n"
            f"{data_dir}\n\n"
            f"## 用户指定的 CASE 白名单(可选)\n"
            f"{case_ids_line}\n\n"
            f"## 你之前的输出(参考,不要复制错误格式)\n"
            f"```\n"
            f"{(prev_output or '')[:1000]}\n"
            f"```\n\n"
            f"## 现在请你:\n"
            f"1. 用 Read/Bash/Grep 工具重新探查 {data_dir} 验证数据\n"
            f"2. 重新填写模板,严格遵守围栏铁律\n"
            f"3. 输出格式:先空一行,再 ```` ```{lang} ```` 围栏,围栏后立即换行写模板内容,再换行 `` ``` `` 收尾"
        )

    def _validate_and_fix_json(
        self,
        content: str,
        template: str,
        data_dir: Path,
        case_ids: Optional[list],
        extraction_task: str,
        max_attempts: int = 2,
    ) -> str:
        """校验 LLM 输出的 JSON 语法。失败时调 LLM 修复,多次失败兜底空对象。

        Args:
            content: LLM 抽离 fence 后的 JSON 字符串
            template: JSON 模板原文(供修复时参考)
            data_dir: 评测产物目录(供修复时探查)
            case_ids: CASE 白名单
            extraction_task: 业务任务
            max_attempts: 修复尝试次数(默认 2 次,共 3 次 LLM 调用)

        Returns:
            合法 JSON 字符串。失败兜底: "{}"
        """
        # 1) 第一次尝试:直接解析
        for attempt in range(max_attempts + 1):
            try:
                json.loads(content)
                if attempt > 0:
                    print(f"  [JsonFix] 第 {attempt} 次修复后 JSON 语法合法")
                return content
            except json.JSONDecodeError as e:
                if attempt >= max_attempts:
                    print(f"  ⚠️ JSON 语法修复 {max_attempts} 次仍失败,兜底空对象: {e}")
                    return "{}"
                print(f"  [JsonFix] JSON 语法非法(第 {attempt+1}/{max_attempts+1} 次尝试): {e}")
                preview = content[:200].replace("\n", " ")
                print(f"  [JsonFix] 错误内容预览: {preview!r}...")

                # 2) 调 LLM 修复
                fix_prompt = (
                    f"你之前填写的 JSON 模板有语法错误,无法被 json.loads 解析。\n\n"
                    f"## 错误信息\n{type(e).__name__}: {e}\n\n"
                    f"## 错误位置(字符 {e.pos},行 {e.lineno} 列 {e.colno})\n\n"
                    f"## 你之前输出的内容(有语法错误)\n```json\n{content}\n```\n\n"
                    f"## JSON 模板(原样,只填字段不发明)\n{template}\n\n"
                    f"## 任务\n"
                    f"1. 用 Read/Bash/Grep 工具重新探查 {data_dir} 验证数据(可选)\n"
                    f"2. **只修复语法**,不要改字段名/字段值/字段顺序\n"
                    f"3. 重新输出完整的 JSON 字符串,用 ```json ... ``` 围栏包裹\n\n"
                    f"## 关键约束\n"
                    f"- 字符串内的引号必须用 \\\" 转义\n"
                    f"- 数字、布尔、null 不要加引号\n"
                    f"- 对象/数组的逗号、括号必须严格成对\n"
                    f"- **不要再加任何额外说明文字**,围栏内只能有合法 JSON"
                )
                from tools import Agent
                fix_result = Agent(
                    mode="auto",
                    description="修复非法 JSON 语法",
                    subagent_type=self.metrics_config.get_extractor_agent(),
                    prompt=fix_prompt,
                )
                new_content = _extract_fenced_block(fix_result, "json") or ""
                if not new_content:
                    print("  [JsonFix] LLM 修复未产出 ```json 围栏,继续尝试")
                    continue
                content = new_content
        return "{}"



    # 阶段产物子目录名(相对 round_dir)
    _PROPOSAL_STAGES_DIR = "_proposal"

    def _generate_proposal_via_agent(self, round_dir: Path, round_score: RoundScore,
                                      candidate_ids: list = None,
                                      skill_path: Optional[str] = None,
                                      prev_failure_block: str = "") -> Optional[dict]:
        """分阶段生成 proposal(Stage 1 加载上下文 + Stage 2 识别 gaps + Stage 3 翻译 modifications)。

        Stage 4 (自检) 仍留到下一轮。
        阶段产物写到 `{round_dir}/_proposal/stage_{1,2,3}.json`,框架从阶段产物拼装最终 proposal。

        Args:
            prev_failure_block: Solution C 注入的上轮失败回顾(文本块)。
                非空时会传给 Stage 3 prompt,让 ProposalAgent 主动避开 history 的 file+section 组合。
        """
        # 1) 准备 _proposal/ 子目录
        stages_dir = round_dir / self._PROPOSAL_STAGES_DIR
        stages_dir.mkdir(parents=True, exist_ok=True)

        # 2) 阶段 1:加载上下文(LLM 优先,fallback 扫描)
        stage_1 = self._run_stage_1(stages_dir, round_dir, round_score)
        if not stage_1:
            print("  [ProposalAgent] Stage 1 LLM 失败,改用扫描兜底")
            stage_1 = self._fallback_stage_1(stages_dir, round_dir, round_score)

        # 3) 阶段 2:识别 gaps(LLM 优先,fallback gap_extractors)
        stage_2 = self._run_stage_2(stages_dir, round_dir, round_score, stage_1)
        if not stage_2 or not stage_2.get("gaps"):
            print("  [ProposalAgent] Stage 2 LLM 失败或 gaps 为空,改用 gap_extractors 兜底")
            stage_2 = self._fallback_stage_2(stages_dir, round_score)

        # 4) 阶段 3:把 systemic gaps 翻译成 modifications(LLM 优先,fallback 最小集)
        stage_3 = self._run_stage_3(stages_dir, round_dir, round_score, stage_1, stage_2,
                                    prev_failure_block=prev_failure_block)
        if not stage_3 or not stage_3.get("modifications"):
            print("  [ProposalAgent] Stage 3 LLM 失败或 modifications 为空,改用最小兜底")
            stage_3 = self._fallback_stage_3(stages_dir, stage_1, stage_2)

        # 4.5) 阶段 4:覆盖率与一致性自检(借鉴 SkillOpt skill_aware 校验)
        # 硬校验失败时,violations 透传到 proposal.problems 供 caller 决策。
        # 框架**不强制重做 stage_3**(避免无限循环);caller 可选:用 fallback 替换/记录违例/重跑
        # ⚠️ 临时禁用(2026-06-18):R5/R3 规则可能过严,ApplyAgent 全部 skip 导致无改进。
        # 取消下面 3 行注释即可恢复。
        stage_4 = {"verdict": "ACCEPTED", "hard_check": {"violations": []}, "llm_verdict": None}
        # stage_4 = self._run_stage_4_self_check(
        #     stages_dir, round_dir, round_score, stage_1, stage_3)
        # if stage_4.get("verdict") == "REJECTED":
        #     violations = stage_4.get("hard_check", {}).get("violations", [])
        #     print(f"  [ProposalAgent] Stage 4 REJECTED "
        #           f"({len(violations)} 条违例),保留 stage_3 输出并暴露 violations")

        # 5) 拼装最终 proposal(包含 stage_3 modifications)
        # 透传 baseline 的 case_run_matrix 到 problems[].case_id / score,
        # 让 proposal.md 的"发现的问题"表格直接显示分数和 case_id(避免 "—" / "N/A" 全空)
        baseline_matrix = None
        if round_score and round_score.baseline_score:
            baseline_matrix = round_score.baseline_score.case_run_matrix
        proposal = self._assemble_proposal_from_stages(
            stage_1, stage_2, stage_3, case_run_matrix=baseline_matrix,
            stage_4=stage_4)
        if not proposal:
            print("  [ProposalAgent] 未生成有效提案")
            return None

        print(f"  [ProposalAgent] 分阶段生成: {proposal.get('summary', 'N/A')}")
        return proposal

    # ─── 阶段 1:加载上下文 ───

    def _run_stage_1(self, stages_dir: Path, round_dir: Path,
                     round_score: RoundScore) -> Optional[dict]:
        """Stage 1:1 次 LLM 调用 + 校验 + 写文件。断点续跑:产物已存在则跳过。"""
        output_path = stages_dir / "stage_1_context.json"
        if output_path.exists():
            try:
                data = json.loads(output_path.read_text(encoding="utf-8"))
                if data.get("skill_files"):
                    print(f"  [Stage 1] 断点续跑,复用 {output_path.name}")
                    return data
            except Exception:
                pass  # 解析失败,继续重跑

        data_dir = self._resolve_data_dir(round_dir, round_score)
        # 计算 workspace 根(从 round_dir 往上两级 = taskid 目录)和前序轮次数
        # 例如 round_dir = .../taskid/round_1/candidate_1,workspace_root = .../taskid
        workspace_root = round_dir.parent.parent if round_dir else None
        prev_round_max = max(0, round_score.round_num - 1) if round_score else 0
        prompt = self._render_stage_1_prompt(
            data_dir, round_score, output_path,
            workspace_root=workspace_root,
            prev_round_max=prev_round_max,
        )
        print(f"  [Stage 1] 调用 LLM 写 {output_path.name} ...")
        import time as _time
        t0 = _time.time()
        from tools import Agent
        result = Agent(
            mode="auto",
            description="ProposalAgent Stage 1: 加载上下文",
            subagent_type="ProposalAgent",
            prompt=prompt,
        )
        # 优先:LLM 写到 output_path(用 Write 工具)
        data = self._read_written_stage_file(output_path, t0)
        if not data:
            # 退化:从 stdout 解析
            data = self._parse_json_output(result)
        # LLM 可能返回 list（如直接输出 skill_files 数组）→ 归一化为 dict，避免 .get 崩溃
        if isinstance(data, list):
            data = {"skill_files": data}
        if not isinstance(data, dict) or not data.get("skill_files"):
            print("  [Stage 1] LLM 输出校验失败 (无 skill_files)")
            return None
        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [Stage 1] 写入 {output_path.name}: {len(data.get('skill_files', []))} 个 Skill")
        return data

    def _render_stage_1_prompt(self, data_dir: Path, round_score: RoundScore,
                                output_path: Path,
                                workspace_root: Optional[Path] = None,
                                prev_round_max: int = 0) -> str:
        """渲染 Stage 1 prompt: focus_block + stage_1 文本 + output_format。

        Args:
            workspace_root: workspace 根目录(任务 taskid 目录)。
                用于注入到 Stage 1 prompt 的"workspace 全景"段,让 LLM 自己用 Bash + Read
                探索 baseline/score_baseline.json + round_*/candidate_*/optimization_summary.md 等
                历史产物,吸收跨轮经验(避免 R1 proposal 跟 baseline 视角撞车)。
                None 或不存在时,_render_template 的 ChainableUndefined 会软退化为空串。
            prev_round_max: 当前轮之前的最大轮次(用于模板里的 `for r in $(seq 1 {{ prev_round_max }})`)。
                0 表示无前序轮次(R1 阶段),模板里 `seq 1 0` 不会执行任何命令。
        """
        cfg = self._proposal_cfg
        focus = self._render_focus_block(cfg, self._is_only_f1_mode())
        sections = cfg.get("prompt_sections") or {}

        # 跨 run CASE 分数矩阵 + per-case 稳定性（解决"6/6 CASE 跨 run 0↔非 0 波动未被识别"问题）
        # 来源:baseline_score.case_run_matrix / per_case_stddev / per_case_cv（数据层已预计算）
        bl = round_score.baseline_score
        case_run_matrix_json = json.dumps(
            (bl.case_run_matrix or {}) if bl else {}, ensure_ascii=False, indent=2
        )
        per_case_stddev_json = json.dumps(
            (bl.per_case_stddev or {}) if bl else {}, ensure_ascii=False, indent=2
        )
        per_case_cv_json = json.dumps(
            (bl.per_case_cv or {}) if bl else {}, ensure_ascii=False, indent=2
        )
        baseline_stddev = (bl.stddev if bl else 0.0) or 0.0
        baseline_cv = (bl.cv if bl else 0.0) or 0.0
        baseline_avg = (bl.avg_result_score if bl else 0.0) or 0.0

        # workspace_root: 注入 workspace 路径到 Stage 1 prompt 第 2.5 步"扫描 workspace 全景"段
        # prev_round_max: 注入前序轮次数到 `for r in $(seq 1 N)` 循环上界
        # round_num / target_label: 注入轮次和目标标签,让 LLM 知道自己在哪一轮、面向什么
        workspace_root_str = str(workspace_root) if workspace_root else "(未提供)"
        stage_text = self._render_template(
            sections.get("stage_1_load_context", ""),
            data_dir=str(data_dir),
            stage_1_output_path=str(output_path),
            case_run_matrix=case_run_matrix_json,
            per_case_stddev=per_case_stddev_json,
            per_case_cv=per_case_cv_json,
            baseline_stddev=f"{baseline_stddev:.2f}",
            baseline_cv=f"{baseline_cv:.2f}",
            baseline_avg=f"{baseline_avg:.2f}",
            workspace_root=workspace_root_str,
            prev_round_max=str(prev_round_max),
            round_num=str(round_score.round_num),
            target_label="baseline",
        )
        output_fmt = self._render_template(
            cfg.get("output_format", ""),
            stage_output_path=str(output_path),
        )
        context = {
            "round_num": round_score.round_num,
            "target_label": "baseline",
            "baseline_stddev": baseline_stddev,
            "baseline_cv": baseline_cv,
            "case_count": len(bl.case_run_matrix) if bl and bl.case_run_matrix else 0,
        }
        return (
            f"你是 ProposalAgent 的 Stage 1(加载上下文子阶段)。\n"
            f"**重要**:本轮只实施 Stage 1 + Stage 2,不要尝试做 Stage 3/4(留到下一轮)。\n\n"
            f"{focus}\n"
            f"## 评分上下文\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
            f"---\n\n{stage_text}\n---\n\n{output_fmt}"
        )

    def _fallback_stage_1(self, stages_dir: Path, round_dir: Path,
                          round_score: RoundScore) -> dict:
        """Stage 1 兜底:用 Path 扫描生成,无 LLM 调用。"""
        data_dir = self._resolve_data_dir(round_dir, round_score)
        skill_hints = self._find_skill_paths(data_dir, round_dir)
        skill_files = []
        seen: set = set()
        for sp in skill_hints:
            if not sp or sp in seen:
                continue
            seen.add(sp)
            try:
                content = Path(sp).read_text(encoding="utf-8")
                h2 = [line[3:].strip() for line in content.splitlines()
                      if line.startswith("## ")]
            except Exception:
                h2 = []
            # 提取相对路径(去掉 /skill/ 或 /skills/ 前缀)
            rel = sp
            for marker in ("/skill/", "/skills/"):
                idx = sp.find(marker)
                if idx >= 0:
                    rel = sp[idx + len(marker):]
                    break
            skill_files.append({"path": rel, "h2_sections": h2})

        # 扫 4 个 phase 子目录的关键产物
        data_artifacts: dict = {}
        for phase in ("phase1-build", "phase2-exec", "phase3-eval", "phase4-diagnosis"):
            phase_dir = data_dir / phase
            if phase_dir.exists():
                items = []
                for p in sorted(phase_dir.rglob("*")):
                    if p.is_file():
                        items.append(str(p.relative_to(phase_dir)))
                # 不限制每 phase 数量:让 LLM 看到所有产物
                data_artifacts[phase] = items

        data = {
            "skill_files": skill_files,
            "data_artifacts": data_artifacts,
            "context": {
                "round_num": round_score.round_num,
                "skill_names": [sf["path"].split("/")[0] for sf in skill_files],
                "target_label": "baseline",
            },
        }
        output_path = stages_dir / "stage_1_context.json"
        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [Stage 1 fallback] 扫描生成 {len(skill_files)} 个 Skill 文件")
        return data

    # ─── 阶段 2:识别 gaps ───

    def _run_stage_2(self, stages_dir: Path, round_dir: Path,
                     round_score: RoundScore, stage_1: dict) -> Optional[dict]:
        """Stage 2:单次 LLM 调用识别 gaps。

        断点续跑:stage_2_gaps.json 已存在则跳过。
        """
        output_path = stages_dir / "stage_2_gaps.json"
        if output_path.exists():
            try:
                data = json.loads(output_path.read_text(encoding="utf-8"))
                if data.get("gaps"):
                    print(f"  [Stage 2] 断点续跑,复用 {output_path.name}")
                    return data
            except Exception:
                pass

        if not stage_1:
            print("  [Stage 2] 缺少 stage_1,跳过 LLM")
            return None

        return self._stage_2_call_llm_single(
            stages_dir, round_dir, round_score, stage_1)

    def _stage_2_call_llm_single(self, stages_dir: Path, round_dir: Path,
                                 round_score: RoundScore, stage_1: dict) -> Optional[dict]:
        """Stage 2 单次 LLM 调用:识别 gaps 并写入 stage_2_gaps.json。"""
        output_path = stages_dir / "stage_2_gaps.json"
        input_path = stages_dir / "stage_1_context.json"
        data_dir = self._resolve_data_dir(round_dir, round_score)
        prompt = self._render_stage_2_prompt(data_dir, round_score, input_path, output_path)
        print(f"  [Stage 2] 调用 LLM 写 {output_path.name} ...")
        import time as _time
        t0 = _time.time()
        from tools import Agent
        result = Agent(
            mode="auto",
            description="ProposalAgent Stage 2: 识别 gaps",
            subagent_type="ProposalAgent",
            prompt=prompt,
        )
        data = self._read_written_stage_file(output_path, t0)
        if not data:
            data = self._parse_json_output(result)
        # LLM 可能直接输出 gaps 数组 → 归一化为 dict
        if isinstance(data, list):
            data = {"gaps": data}
        if not isinstance(data, dict) or not data.get("gaps"):
            print("  [Stage 2] LLM 输出校验失败 (无 gaps)")
            return None
        gaps_list = data.get("gaps") or []
        if gaps_list:
            data["gaps"] = self._apply_failure_layer_classifier(
                gaps_list, self._proposal_cfg)
        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [Stage 2] 写入 {output_path.name}: {len(data.get('gaps', []))} 个 gaps")
        return data

    def _render_stage_2_prompt(self, data_dir: Path, round_score: RoundScore,
                                input_path: Path, output_path: Path) -> str:
        """渲染 Stage 2 prompt: focus_block + stage_2 文本 + output_format。"""
        cfg = self._proposal_cfg
        focus = self._render_focus_block(cfg, self._is_only_f1_mode())
        sections = cfg.get("prompt_sections") or {}
        # 稳定性 + 跨 run 注入（解决"baseline CV 高被误归 Skill"问题）
        bl = round_score.baseline_score
        baseline_stddev = (bl.stddev if bl else 0.0) or 0.0
        baseline_cv = (bl.cv if bl else 0.0) or 0.0
        baseline_avg = (bl.avg_result_score if bl else 0.0) or 0.0
        # 稳定性阈值（来自 framework YAML，可被覆盖）
        stability_cv_warn = cfg.get("stability_cv_warn", 0.20)
        stability_cv_untrusted = cfg.get("stability_cv_untrusted", 0.35)
        stability_min_runs_for_cv = cfg.get("stability_min_runs_for_cv", 3)
        stage_text = self._render_template(
            sections.get("stage_2_identify_gaps", ""),
            stage_1_input_path=str(input_path),
            stage_2_output_path=str(output_path),
            baseline_stddev=f"{baseline_stddev:.2f}",
            baseline_cv=f"{baseline_cv:.2f}",
            baseline_avg=f"{baseline_avg:.2f}",
            stability_cv_warn=f"{stability_cv_warn}",
            stability_cv_untrusted=f"{stability_cv_untrusted}",
            stability_min_runs_for_cv=f"{stability_min_runs_for_cv}",
        )
        output_fmt = self._render_template(
            cfg.get("output_format", ""),
            stage_output_path=str(output_path),
        )
        return (
            f"你是 ProposalAgent 的 Stage 2(识别 gaps 子阶段)。\n"
            f"**重要**:先读上阶段产物 {input_path},再写本阶段产物 {output_path}。\n"
            f"**不要**做 Stage 3 (gaps → modifications) 或 Stage 4 (自检) —— 留到下一轮。\n\n"
            f"{focus}\n---\n\n{stage_text}\n---\n\n{output_fmt}"
        )

    def _fallback_stage_2(self, stages_dir: Path, round_score: RoundScore) -> dict:
        """Stage 2 兜底:复用 _apply_gap_extractors 提 gap。"""
        runs = (round_score.baseline_score.runs if round_score.baseline_score else [])
        gaps_raw = self._apply_gap_extractors(runs, self._proposal_cfg)
        # 转成 stage_2 schema(gap_id / occurrence / affected_section / severity)
        gaps = []
        for i, g in enumerate(gaps_raw, 1):
            gaps.append({
                "gap_id": f"G{i}",
                "scope": g.get("scope", "systemic"),
                "occurrence": "1/1 CASE 直接复现",
                "root_cause": g.get("root_cause") or g.get("message", ""),
                "evidence": g.get("evidence") or g.get("fix_suggestion", ""),
                "affected_section": None,
                "severity": g.get("severity", "high"),
                "fix_suggestion": g.get("fix_suggestion", ""),
            })
        # failure_layer 关键词兜底:gap_extractor 输出的 gap 默认无 failure_layer,触发分类
        if gaps:
            gaps = self._apply_failure_layer_classifier(gaps, self._proposal_cfg)
        data = {"gaps": gaps}
        output_path = stages_dir / "stage_2_gaps.json"
        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [Stage 2 fallback] gap_extractors 兜底生成 {len(gaps)} 个 gaps")
        return data

    # ─── 阶段 3:把 systemic gaps 翻译成 modifications ───

    def _run_stage_3(self, stages_dir: Path, round_dir: Path,
                     round_score: RoundScore, stage_1: dict, stage_2: dict,
                     prev_failure_block: str = "") -> Optional[dict]:
        """Stage 3 单次 LLM 路径:把 systemic gaps 翻译成 modifications。

        断点续跑:stage_3_modifications.json 已存在则直接复用。

        Args:
            prev_failure_block: Solution C 注入的上轮失败回顾,透传到 _run_stage_3_single。
        """
        output_path = stages_dir / "stage_3_modifications.json"
        if output_path.exists():
            try:
                data = json.loads(output_path.read_text(encoding="utf-8"))
                if data.get("modifications") is not None:
                    print(f"  [Stage 3] 断点续跑,复用 {output_path.name}")
                    return data
            except Exception:
                pass

        if not stage_1 or not stage_2:
            print("  [Stage 3] 缺少 stage_1/stage_2,跳过 LLM")
            return None

        return self._run_stage_3_single(
            stages_dir, round_dir, round_score, stage_1, stage_2,
            prev_failure_block=prev_failure_block)

    def _run_stage_3_single(self, stages_dir: Path, round_dir: Path,
                             round_score: RoundScore, stage_1: dict,
                             stage_2: dict,
                             prev_failure_block: str = "") -> Optional[dict]:
        """Stage 3 单次 LLM 路径(原 _run_stage_3 主体逻辑)。

        Args:
            prev_failure_block: Solution C 上轮失败回顾,渲染时拼接到 prompt。
        """
        output_path = stages_dir / "stage_3_modifications.json"
        input_path = stages_dir / "stage_2_gaps.json"
        data_dir = self._resolve_data_dir(round_dir, round_score)
        prompt = self._render_stage_3_prompt(data_dir, round_score,
                                              stage_1, input_path, output_path,
                                              prev_failure_block=prev_failure_block)
        # 预算计算(与 _render_stage_3_prompt 同步)
        cfg = self._proposal_cfg
        budget_cfg = cfg.get("stage_3_modification_budget") or {}
        budget_default = int(budget_cfg.get("default", 8))
        budget_slope = int(budget_cfg.get("slope", 1))
        budget_floor = int(budget_cfg.get("floor", 2))
        round_num = round_score.round_num if round_score else 0
        modification_budget = max(
            budget_default - budget_slope * round_num, budget_floor,
        )
        print(f"  [Stage 3 single] 调用 LLM 写 {output_path.name}"
              f"(budget={modification_budget}) ...")
        import time as _time
        t0 = _time.time()
        from tools import Agent
        result = Agent(
            mode="auto",
            description="ProposalAgent Stage 3: 翻译 modifications",
            subagent_type="ProposalAgent",
            prompt=prompt,
        )
        data = self._read_written_stage_file(output_path, t0)
        if not data:
            data = self._parse_json_output(result)
        # LLM 可能直接输出 modifications 数组 → 归一化为 dict
        if isinstance(data, list):
            data = {"modifications": data}
        if not isinstance(data, dict) or data.get("modifications") is None:
            print("  [Stage 3 single] LLM 输出校验失败 (无 modifications 字段)")
            return None
        # modification_budget 硬截断
        return self._enforce_modification_budget(
            data, output_path, modification_budget,
        )

    def _enforce_modification_budget(self, data: dict, output_path: Path,
                                      modification_budget: int) -> dict:
        """modification_budget 硬截断:按 severity 排序,超出预算的进 uncovered_gaps。

        Stage 3 单次 LLM 路径共用此函数,确保截断逻辑一致。

        根治：modification_budget=0 表示不限制（直接返回，不截断）。
        """
        mods = data.get("modifications", []) or []
        if modification_budget <= 0:
            # 0 = 不限制 mod 总数（根治：用户要求涉及多文件时不限制）
            return data
        if len(mods) > modification_budget:
            sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            mods_sorted = sorted(
                mods, key=lambda m: sev_order.get(m.get("severity", "low"), 99),
            )
            kept = mods_sorted[:modification_budget]
            dropped = mods_sorted[modification_budget:]
            data["modifications"] = kept
            existing_uncovered = data.get("uncovered_gaps") or []
            for m in dropped:
                existing_uncovered.append({
                    "gap_id": m.get("gap_id") or m.get("mod_id", "?"),
                    "mod_id": m.get("mod_id"),
                    "severity": m.get("severity", "low"),
                    "scope": "single_point",
                    "reason": f"被 modification_budget({modification_budget}) 截断,超出预算",
                })
            data["uncovered_gaps"] = existing_uncovered
            print(f"  [Stage 3 budget] LLM 输出 {len(mods)} 条,硬截断到"
                  f" {modification_budget} 条;{len(dropped)} 条进入 uncovered_gaps")
        # 写文件由调用方负责
        return data


    def _render_stage_3_prompt(self, data_dir: Path, round_score: RoundScore,
                                stage_1: dict, input_path: Path,
                                output_path: Path,
                                round_dir: Path = None,
                                prev_failure_block: str = "") -> str:
        """渲染 Stage 3 prompt: focus_block + stage_3 文本 + output_format。

        Solution C 注入点: 若 prev_failure_block 非空,在 stage_text 末尾追加。
        consume_lib 注入点: 若 config.json 含 consume_lib_path,在 stage_text 之前追加。
        """
        cfg = self._proposal_cfg
        focus = self._render_focus_block(cfg, self._is_only_f1_mode())
        sections = cfg.get("prompt_sections") or {}
        # 把 stage_1 的 skill_files 路径列表转成 JSON 字符串,供模板渲染
        skill_files_rel = json.dumps(
            [sf.get("path", "") for sf in (stage_1 or {}).get("skill_files", [])],
            ensure_ascii=False,
        )
        # modification_budget: 借鉴 SkillOpt lr_autonomous,前几轮允许大改、后几轮强制微改
        budget_cfg = cfg.get("stage_3_modification_budget") or {}
        budget_default = int(budget_cfg.get("default", 8))
        budget_slope = int(budget_cfg.get("slope", 1))
        budget_floor = int(budget_cfg.get("floor", 2))
        round_num = round_score.round_num if round_score else 0
        modification_budget = max(
            budget_default - budget_slope * round_num, budget_floor,
        )
        stage_text = self._render_template(
            sections.get("stage_3_translate_to_mods", ""),
            stage_1_skill_files=skill_files_rel,
            stage_2_input_path=str(input_path),
            stage_3_output_path=str(output_path),
            modification_budget=modification_budget,
            round_num=round_num,
        )
        output_fmt = self._render_template(
            cfg.get("output_format", ""),
            stage_output_path=str(output_path),
        )
        # Solution C:上轮失败回顾(若非空)在 stage_text 与 output_fmt 之间注入
        prev_block = ""
        if prev_failure_block:
            prev_block = (
                "\n---\n\n"
                "## ⚠️ 跨轮历史信号(Solution C:ProposalAgent 必须看到)\n"
                "本轮 Stage 3 生成的 modifications **不得**与上轮重复。\n"
                "上轮执行了 N 条 modifications,本轮必须调整方向(如改 H2 章节、改执行步骤、改前置要求)。\n\n"
                f"{prev_failure_block}\n"
            )
        # consume_lib:领域知识库参考(若 config.json 配置了 consume_lib_path)
        consume_block = self._render_consume_lib_block(round_dir) if round_dir else ""
        return (
            f"你是 ProposalAgent 的 Stage 3(把 gaps 翻译成 modifications 子阶段)。\n"
            f"**重要**:先读上阶段产物 {input_path} 和 stage_1 扫描到的 Skill 文件清单,再写本阶段产物 {output_path}。\n"
            f"**不要**做 Stage 4(自检)—— 留到下一轮。\n\n"
            f"{focus}\n---\n\n{stage_text}{consume_block}{prev_block}\n---\n\n{output_fmt}"
        )

    def _fallback_stage_3(self, stages_dir: Path, stage_1: dict,
                          stage_2: dict) -> dict:
        """Stage 3 兜底:LLM 失败时,基于 gap 的 fix_suggestion 生成最小 modifications 列表。

        原则:
        - coverage 全列(每个 skill_file 一条,默认 unchanged)
        - modifications 仅在 gap 提供 affected_section 时尝试,否则空
        - 不臆测具体 new_content,留给 ApplyAgent 在 LLM 模式下补全
        """
        skill_files = (stage_1 or {}).get("skill_files", [])
        gaps = (stage_2 or {}).get("gaps", [])

        # coverage:覆盖所有扫描到的文件
        coverage = [
            {"file": sf.get("path", ""), "status": "unchanged",
             "reason": "Stage 3 fallback: 无 LLM modifications,默认不变"}
            for sf in skill_files
        ]
        # modifications:从 gaps 的 affected_section 派生最小条目
        modifications: list = []
        for i, g in enumerate(gaps, 1):
            section = g.get("affected_section")
            if not section:
                continue
            modifications.append({
                "mod_id": f"M{i}",
                "action": "modify",
                "file": "(待 ApplyAgent 匹配)",  # LLM 模式下会有精确 file
                "section": section,
                "current_content": None,
                "new_content": g.get("fix_suggestion", ""),
                "reason": g.get("root_cause", ""),
            })

        data = {
            "modifications": modifications,
            "coverage": coverage,
            "_provenance": "fallback (LLM Stage 3 失败)",
        }
        output_path = stages_dir / "stage_3_modifications.json"
        output_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [Stage 3 fallback] 兜底生成 {len(modifications)} 处 modifications, "
              f"{len(coverage)} 个 coverage")
        return data

    # ─── 阶段 4:覆盖率与一致性自检 ───

    def _run_stage_4_self_check(self, stages_dir: Path, round_dir: Path,
                                 round_score: RoundScore, stage_1: dict,
                                 stage_3: dict) -> dict:
        """Stage 4:覆盖率与一致性自检(借鉴 SkillOpt skill_aware 校验)。

        双层防护:
        1) Python 硬校验(check_overfit.check_overfit):R1-R8 8 条 anti-overfitting 规则
        2) 硬校验通过 → LLM soft verdict(coverage/gap_id 一致性等语义级)

        产物: stages_dir/stage_4_self_check.json

        Returns:
            dict: {
                "verdict": "PASS" / "NEEDS_FIX" / "REJECTED" / "SKIPPED",
                "hard_check": {"passed": bool, "violations": [...], ...},
                "llm_verdict": {...} (仅硬校验通过时),
            }
        """
        output_path = stages_dir / "stage_4_self_check.json"

        # 断点续跑:产物已存在则跳过
        if output_path.exists():
            try:
                data = json.loads(output_path.read_text(encoding="utf-8"))
                if data.get("verdict") and "hard_check" in data:
                    print(f"  [Stage 4] 断点续跑,复用 {output_path.name}")
                    return data
            except Exception:
                pass

        if not stage_3 or not stage_3.get("modifications"):
            print("  [Stage 4] 无 modifications,跳过自检")
            return {"verdict": "SKIPPED", "hard_check": {"passed": True, "violations": []}}

        # 1) 解析源文件 + 加载 business_terms(R1 用)
        source_files = self._resolve_skill_source_files(stage_1, round_dir)
        business_terms = self._load_business_terms()

        # 2) Python 硬校验
        from .check_overfit import check_overfit
        hard_result = check_overfit(stage_3, source_files, business_terms)
        timestamp = datetime.now().isoformat()

        if not hard_result["passed"]:
            # 硬校验失败 → 拒收,violations 暴露给 caller 重做 stage_3
            output = {
                "stage": 4,
                "timestamp": timestamp,
                "verdict": "REJECTED",
                "hard_check": {
                    "passed": False,
                    "violations": hard_result["violations"],
                    "rules_applied": hard_result.get("rules_applied", []),
                    "checked_count": hard_result.get("checked_count", 0),
                },
                "llm_verdict": None,
                "summary": (f"硬校验失败:{len(hard_result['violations'])} 条违例,"
                            f"Stage 3 需要重做"),
            }
            output_path.write_text(
                json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [Stage 4] 硬校验 REJECTED:"
                  f"{len(hard_result['violations'])} 条违例")
            return output

        # 3) 硬校验通过 → LLM soft verdict
        hard_summary = (
            f"硬校验已通过,共 {hard_result['checked_count']} 条 modifications "
            f"通过 R1-R8 检查"
        )
        print(f"  [Stage 4] 硬校验通过({hard_result['checked_count']} mods),"
              f"调 LLM soft verdict ...")

        s3_input_path = stages_dir / "stage_3_modifications.json"
        skill_files_rel = json.dumps(
            [sf.get("path", "") for sf in (stage_1 or {}).get("skill_files", [])],
            ensure_ascii=False,
        )

        cfg = self._proposal_cfg
        sections = cfg.get("prompt_sections") or {}
        stage_text = self._render_template(
            sections.get("stage_4_self_check", ""),
            stage_3_input_path=str(s3_input_path),
            stage_4_output_path=str(output_path),
            stage_1_skill_files=skill_files_rel,
            hard_check_summary=hard_summary,
            stage_4_violations_context="",
        )
        output_fmt = self._render_template(
            cfg.get("output_format", ""),
            stage_output_path=str(output_path),
        )
        prompt = (
            f"你是 ProposalAgent 的 Stage 4(覆盖率与一致性自检)。\n"
            f"**重要**:只做软裁决(coverage/gap_id 一致性等),"
            f"不要重复硬校验。\n"
            f"**输入**: 读 {s3_input_path} 拿到 stage_3 modifications。\n"
            f"**输出**: 写 {output_path}。\n\n"
            f"{stage_text}\n---\n\n{output_fmt}"
        )

        import time as _time
        t0 = _time.time()
        from tools import Agent
        result = Agent(
            mode="auto",
            description="ProposalAgent Stage 4: 自检",
            subagent_type="ProposalAgent",
            prompt=prompt,
        )
        llm_data = self._read_written_stage_file(output_path, t0)
        if not llm_data:
            llm_data = self._parse_json_output(result)
        if not llm_data:
            print("  [Stage 4] LLM 输出解析失败,降级为 PASS")
            llm_data = {
                "verdict": "PASS",
                "checks": {},
                "issues": [],
                "summary": "LLM 输出降级",
            }

        output = {
            "stage": 4,
            "timestamp": timestamp,
            "verdict": llm_data.get("verdict", "NEEDS_FIX"),
            "hard_check": {
                "passed": True,
                "violations": [],
                "rules_applied": hard_result.get("rules_applied", []),
                "checked_count": hard_result.get("checked_count", 0),
            },
            "llm_verdict": {
                "verdict": llm_data.get("verdict"),
                "checks": llm_data.get("checks", {}),
                "issues": llm_data.get("issues", []),
                "summary": llm_data.get("summary", ""),
            },
            "summary": (f"硬校验通过 + LLM verdict="
                        f"{llm_data.get('verdict', '?')}"),
        }
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [Stage 4] 写入 {output_path.name}:"
              f"verdict={output['verdict']}")
        return output

    def _resolve_skill_source_files(self, stage_1: dict, round_dir: Path
                                     ) -> Dict[str, str]:
        """从 stage_1.skill_files 解析回绝对路径,读取源文件内容。

        Returns:
            Dict[str, str]: {rel_path: content} 供 check_overfit R6 校验
        """
        source_files: Dict[str, str] = {}
        skill_files = (stage_1 or {}).get("skill_files", [])

        # 收集可能的 skill/ 根目录(从 round_dir 向上 4 层)
        skill_roots: list = []
        parent = round_dir
        for _ in range(4):
            parent = parent.parent
            if not parent.exists():
                continue
            for sub in ["skill", "skills"]:
                base = parent / sub
                if base.exists() and base.is_dir():
                    skill_roots.append(base)

        for sf in skill_files:
            rel_path = sf.get("path", "")
            if not rel_path:
                continue
            # 绝对路径直接读
            abs_path = Path(rel_path)
            if abs_path.is_absolute() and abs_path.exists():
                try:
                    source_files[rel_path] = abs_path.read_text(
                        encoding="utf-8", errors="replace")
                except Exception:
                    pass
                continue
            # 相对路径:尝试 skill_roots 下的拼接
            for root in skill_roots:
                candidate = root / rel_path
                if candidate.exists() and candidate.is_file():
                    try:
                        source_files[rel_path] = candidate.read_text(
                            encoding="utf-8", errors="replace")
                    except Exception:
                        pass
                    break
        return source_files

    def _load_business_terms(self) -> List[str]:
        """从 config/user-config.yaml 加载 overfit.business_terms。

        失败时返回空列表(R1 业务术语检查不启用,但其余 R2-R8 仍生效)。
        """
        try:
            from pathlib import Path as _P
            config_path = _P("config/user-config.yaml")
            if not config_path.exists():
                return []
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            overfit = cfg.get("overfit") or {}
            terms = overfit.get("business_terms") or []
            return [t for t in terms if isinstance(t, str) and t.strip()]
        except Exception:
            return []

    # ─── 拼装 + 辅助 ───

    def _assemble_proposal_from_stage_2(self, stage_1: dict, stage_2: dict) -> Optional[dict]:
        """向后兼容入口:仅 Stage 1+2,modifications 留空。"""
        return self._assemble_proposal_from_stages(
            stage_1, stage_2, {"modifications": [], "coverage": []})

    def _assemble_proposal_from_stages(self, stage_1: dict, stage_2: dict,
                                         stage_3: Optional[dict] = None,
                                         case_run_matrix: Optional[Dict[str, List[float]]] = None,
                                         stage_4: Optional[dict] = None) -> Optional[dict]:
        """从 Stage 1+2+3 拼装最终 proposal。

        stage_3 缺省时退化为旧行为(modifications 留空),保证向后兼容。
        case_run_matrix: 用于把"零分 case 列表"透传到 proposal.md 的"发现的问题"表格
            —— 取每 gap 的 supporting_cases 第一个 case_id 的跨 run 均分,作为该 gap 的
            "分数"列填充,避免 reader 无法一眼识别哪几条 gap 对应 0 分 case。
        """
        if not stage_1 or not stage_2:
            return None
        gaps = stage_2.get("gaps", [])
        stage_3 = stage_3 or {}
        modifications = stage_3.get("modifications", []) or []
        coverage = stage_3.get("coverage")
        if coverage is None:
            # 兜底:从 skill_files 派生 coverage,所有文件默认 unchanged
            coverage = [
                {"file": sf.get("path", ""), "status": "unchanged",
                 "reason": "无对应 modification"}
                for sf in stage_1.get("skill_files", [])
            ]

        # Stage 3 modifications 字段归一化:stage_3_modifications.json 用
        # operation/target_file/target_section/content/rationale,proposal.md 渲染器
        # 读 action/file/section/reason/current_content/new_content。两套字段名共存
        # 时归一化为 proposal 侧期望的字段,避免"修改建议"渲染为 [UNKNOWN]。
        modifications = [self._normalize_modification_field_names(m) for m in modifications]

        # 透传 case_id + 跨 run 均分(供 proposal.md 的"发现的问题"表格直接显示)
        matrix = case_run_matrix or {}
        problems = []
        for g in gaps:
            supporting = g.get("supporting_cases") or []
            primary_case = supporting[0] if supporting else None
            score_for_case = None
            if primary_case and isinstance(matrix.get(primary_case), list):
                vals = [v for v in matrix[primary_case] if v is not None]
                if vals:
                    score_for_case = sum(vals) / len(vals)
            problems.append({
                "scope": g.get("scope"),
                "occurrence": g.get("occurrence"),
                "root_cause": g.get("root_cause"),
                "evidence": g.get("evidence"),
                "affected_section": g.get("affected_section"),
                "severity": g.get("severity"),
                # 新增:供 proposal.md 表格直接显示(避免 "—" + "N/A" 全空)
                "case_id": primary_case or "—",
                "score": (round(score_for_case, 4) if score_for_case is not None
                          else g.get("score", "N/A")),
            })

        # 透传 Stage 4 硬校验违例到 problems,供 apply 阶段读 verdict 决策
        # (REJECTED 时跳过 apply,避免 R8 等格式违例被反复应用)
        if stage_4 and isinstance(stage_4.get("hard_check"), dict):
            violations = stage_4["hard_check"].get("violations") or []
            for v in violations:
                problems.append({
                    "gap_id": f"S4-{v.get('mod_id', '?')}",
                    "type": "stage_4_violation",
                    "scope": "self_check",
                    "severity": v.get("severity", "high"),
                    "rule_id": v.get("rule_id"),
                    "mod_id": v.get("mod_id"),
                    "root_cause": v.get("detail", ""),
                    "evidence": None,
                    "affected_section": None,
                    "case_id": "—",
                    "score": "N/A",
                    "source": "stage_4_self_check",
                })

        return {
            "summary": f"分阶段生成(Stage 1+2+3):扫描 {len(stage_1.get('skill_files', []))} 个 Skill,识别 {len(gaps)} 个 gaps,生成 {len(modifications)} 处 modifications",
            "problems": problems,
            "coverage": coverage,
            "modifications": modifications,
            "_stage_provenance": {
                "stage_1": str(Path("baseline") / self._PROPOSAL_STAGES_DIR / "stage_1_context.json") if hasattr(self, "_PROPOSAL_STAGES_DIR") else "_proposal/stage_1_context.json",
                "stage_2": "_proposal/stage_2_gaps.json",
                "stage_3": "_proposal/stage_3_modifications.json",
                "stage_4": "_proposal/stage_4_self_check.json" if stage_4 else None,
            },
            "self_check": stage_4,
        }

    def _normalize_modification_field_names(self, m: dict) -> dict:
        """归一化 modification 字段名,兼容 stage_3_modifications 与旧 proposal 双 schema。

        stage_3 schema:operation / change_type / target_file / target_section / content / rationale / anchor
        proposal schema:action / file / section / reason / current_content / new_content
        两套字段名映射后落到同一 dict,优先保留 proposal 侧已存在的字段(避免覆盖)。
        """
        if not isinstance(m, dict):
            return m
        field_map = [
            ("operation", "action"),
            ("change_type", "action"),
            ("target_file", "file"),
            ("target_section", "section"),
            ("rationale", "reason"),
            ("content", "new_content"),
            ("before", "current_content"),
        ]
        normalized = dict(m)
        for src, dst in field_map:
            if normalized.get(src) is not None and normalized.get(dst) is None:
                normalized[dst] = normalized[src]
        return normalized

    def _resolve_data_dir(self, round_dir: Path, round_score: RoundScore) -> Path:
        """定位 best run 的 data 目录(与原 _generate_proposal_via_agent 同款逻辑)。"""
        target_runs = []
        if round_score.baseline_score and round_score.baseline_score.runs:
            target_runs = round_score.baseline_score.runs
        if round_score.candidates:
            for c in round_score.candidates:
                if c.runs:
                    target_runs.extend(c.runs)
        if not target_runs:
            return round_dir / "data"
        best_run = max(target_runs, key=lambda r: r.raw.result_score or 0)
        data_dir = (Path(best_run.analysis_path).parent / "data"
                    if best_run.analysis_path else None)
        if not data_dir or not data_dir.exists():
            data_dir = round_dir / "data"
        if not data_dir.exists():
            data_dir = round_dir
        return data_dir

    def _read_written_stage_file(self, output_path: Path, t0: float) -> Optional[dict]:
        """读 LLM 用 Write 工具写的 stage 产物文件。

        分阶段写入的核心收益:即使 LLM 没在 stdout 输出 JSON,
        只要它用 Write 工具把 JSON 写到了 output_path,框架就能读到。
        通过 mtime > t0 过滤(只在 LLM 调用后才算 LLM 写入)。
        """
        if not output_path.exists():
            return None
        try:
            mtime = output_path.stat().st_mtime
        except OSError:
            return None
        if mtime <= t0:
            # 文件 mtime 早于 LLM 调用开始,说明是 fallback 之前留下的
            return None
        try:
            data = json.loads(output_path.read_text(encoding="utf-8"))
            print(f"  [Stage] LLM 写入文件: {output_path.name} ({len(data)} keys)")
            return data
        except Exception as e:
            print(f"  [Stage] LLM 写入文件 {output_path.name} 解析失败: {e}")
            return None

    def _load_proposal_from_disk(self, round_dir: Path, round_score: RoundScore) -> Optional[dict]:
        """从 `{round_dir}/_proposal/stage_*.json` 拼装 proposal。

        返回:
            dict: 解析后的 proposal;找不到或解析失败则返回 None
        """
        # 从 _proposal/stage_*.json 拼装(分阶段写入的产物)
        stages_dir = round_dir / self._PROPOSAL_STAGES_DIR
        if stages_dir.exists():
            s1 = stages_dir / "stage_1_context.json"
            s2 = stages_dir / "stage_2_gaps.json"
            s3 = stages_dir / "stage_3_modifications.json"
            if s2.exists() and s1.exists():
                try:
                    stage_1 = json.loads(s1.read_text(encoding="utf-8"))
                    stage_2 = json.loads(s2.read_text(encoding="utf-8"))
                    stage_3 = None
                    if s3.exists():
                        try:
                            stage_3 = json.loads(s3.read_text(encoding="utf-8"))
                        except Exception as e:
                            print(f"  [ProposalAgent:stages-fallback] stage_3 解析失败: {e}")
                    if stage_3 is not None:
                        proposal = self._assemble_proposal_from_stages(
                            stage_1, stage_2, stage_3,
                            case_run_matrix=(
                                round_score.baseline_score.case_run_matrix
                                if round_score and round_score.baseline_score else None))
                        mod_count = len(stage_3.get("modifications", []))
                    else:
                        # 向后兼容:无 stage_3 时只拼 1+2
                        proposal = self._assemble_proposal_from_stage_2(stage_1, stage_2)
                        mod_count = 0
                    if proposal:
                        print(f"  [ProposalAgent:stages-fallback] 从 {stages_dir.name}/stage_*.json 拼装: "
                              f"{len(stage_2.get('gaps', []))} 个 gaps, "
                              f"{mod_count} 处 modifications")
                        return proposal
                except Exception as e:
                    print(f"  [ProposalAgent:stages-fallback] stage 产物解析失败: {e}")
        return None

    def _write_proposal_md(self, round_dir: Path, round_num: int, proposal: dict,
                            scope: str = "round",
                            skill_names: Optional[List[str]] = None):
        """写 proposal.md 到对应目录。

        通用化：按 scope 决定文件名和标题，不依赖具体业务。
        - scope="round"   → round_dir/round_{N}_proposal.md（Round 级优化提案）
        - scope="baseline" → round_dir/proposal.md（基于基线产出的提案，目录名即 baseline/）

        Args:
            skill_names: 多 Skill 模式下的 Skill 名列表（baseline 阶段使用）。
                当提供时，modifications / coverage 按 Skill 维度分段落渲染。
        """
        if not proposal:
            return

        if scope == "baseline":
            # 基线级：round_dir 是 baseline_dir，写到 baseline/proposal.md
            file_name = "proposal.md"
            title = "Baseline 优化提案"
        else:
            # 默认 round 级
            file_name = f"round_{round_num}_proposal.md"
            title = f"Round {round_num} 优化提案"

        lines = [
            f"# {title}",
            "",
            f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "- **来源**: ProposalAgent（子 Agent 驱动）",
            "",
            "## 概述",
            "",
            proposal.get("summary", "无概述"),
            "",
        ]

        # 问题列表
        problems = proposal.get("problems", [])
        if problems:
            lines.append(f"## 发现的问题（{len(problems)} 个）")
            lines.append("")
            lines.append("| CASE | 分数 | 根因 | 证据 |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for p in problems:
                score = p.get("score", "N/A")
                if isinstance(score, float):
                    # 统一百分制 0~100,2 位小数
                    score = f"{score:.2f}"
                elif score is None:
                    score = "N/A"
                case_id = p.get("case_id", "—")
                cause = p.get("root_cause") or "—"
                evidence = p.get("evidence") or "—"
                # 截断过长内容
                if cause and len(cause) > 80:
                    # 不截断 cause（之前 77 字符截断让用户看不到完整根因）
                    cause = cause
                if evidence and len(evidence) > 80:
                    # 不截断 evidence（之前 77 字符截断让用户看不到完整证据）
                    evidence = evidence
                lines.append(f"| {case_id} | {score} | {cause} | {evidence} |")
            lines.append("")

        # baseline + 多 Skill 模式：在顶部列出涉及 Skill，让用户知道提案覆盖了哪些 Skill
        if scope == "baseline" and skill_names:
            lines.append("## 涉及 Skill")
            lines.append("")
            lines.append("本提案基于端到端全流程聚合评测（所有 Skill 一起跑 1 次），"
                         f"共涉及 {len(skill_names)} 个 Skill：")
            lines.append("")
            for sn in skill_names:
                lines.append(f"- **{sn}**")
            lines.append("")
            lines.append("> 详细修改按 Skill 分段落展示在后文「按 Skill 拆分的修改建议」中。")
            lines.append("")

        # 文件覆盖清单（coverage）—— 必填项，覆盖 Skill 文件 + 所有已完成的轮次产物
        # 跨轮次扫描：baseline/ + round_1/ + ... + round_N/，让提案能吸收所有经验
        coverage = list(proposal.get("coverage", []))
        llm_files = {c.get("file", "") for c in coverage}
        all_dirs = self._collect_all_round_dirs(round_dir)
        artifacts: List[Dict[str, str]] = []
        for d in all_dirs:
            # rel_prefix 标当前 dir 在 workspace 中的角色（baseline / round_N）
            rel_prefix = d.name if d.name != d.parent.name else "."
            for art in self._scan_layer_artifacts(d, scope="baseline"):
                # 给 artifact 文件名加轮次前缀（避免不同轮的同名文件冲突）
                file_path = art["file"]
                if rel_prefix != "." and not file_path.startswith(rel_prefix + "/"):
                    file_path = f"{rel_prefix}/{file_path}"
                art_copy = dict(art)
                art_copy["file"] = file_path
                if art_copy["file"] not in llm_files:
                    artifacts.append(art_copy)
                    llm_files.add(art_copy["file"])
        coverage.extend(artifacts)  # 把跨轮次扫描到的产物合并到 coverage 列表
        if coverage:
            n_skill = len(proposal.get('coverage', []))
            n_art = len(artifacts)
            layers = ", ".join(d.name for d in all_dirs)
            lines.append(f"## 文件覆盖清单（{len(coverage)} 个文件 = {n_skill} 个 Skill 文件 + {n_art} 个产物文件，扫描层：{layers}）")
            lines.append("")
            lines.append("> 提案覆盖被测 Skill 的全部文件 + **所有已完成轮次（baseline/ round_1/..round_N/）**下所有产物文件（score/log/data/_proposal），吸收全周期经验。")
            lines.append("")
            lines.append("| 文件 | 状态 | 说明 |")
            lines.append("| :--- | :--- | :--- |")
            for c in coverage:
                file_path = c.get("file", "—")
                status = c.get("status", "—")
                reason = c.get("reason", "—")
                # 不截断 reason（之前 100 字符截断让用户看不到完整上下文）
                lines.append(f"| {file_path} | {status} | {reason} |")
            lines.append("")

        # 修改建议
        modifications = proposal.get("modifications", [])
        if modifications:
            # baseline + 多 Skill：按 Skill 分段落
            if scope == "baseline" and skill_names:
                lines.extend(self._render_modifications_grouped_by_skill(
                    modifications, skill_names
                ))
            else:
                lines.append(f"## 修改建议（{len(modifications)} 处）")
                lines.append("")
                for i, m in enumerate(modifications, 1):
                    action = m.get("action", "unknown").upper()
                    mod_file = m.get("file", "—")  # 改名 mod_file，避免覆盖外层 file_name
                    section = m.get("section", "—")
                    reason = m.get("reason", "—")
                    lines.append(f"### {i}. [{action}] {mod_file} → {section}")
                    lines.append(f"**理由**: {reason}")
                    lines.append("")
                    current = m.get("current_content", "")
                    if current:
                        lines.append("**当前内容**:")
                        lines.append("```markdown")
                        lines.append(current)
                        # current_content 不能截断——Edit 工具要求严格匹配,
                        # 截断会让 ApplyAgent 拿到的 current_content 与文件实际不一致,
                        # 导致 Edit 找不到匹配项或错位插入。
                        lines.append("```")
                        lines.append("")
                    new_content = m.get("new_content", "")
                    if new_content:
                        lines.append("**建议内容**:")
                        lines.append("```markdown")
                        # 写完整的 new_content,ApplyAgent 需要它做 Edit 精确替换。
                        # 截断会让 ApplyAgent 拿到字面 "... (截断)" 而误判无法应用。
                        lines.append(new_content)
                        lines.append("```")
                        lines.append("")

        proposal_path = round_dir / file_name
        # 通用：确保目录存在（不依赖上游是否已建好）
        from state_engine.persistence import ensure_dir as _ed
        _ed(str(round_dir))
        proposal_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  [ScoreAnalyzer] 已写 {file_name}: {len(proposal.get('modifications', []))} 处修改, "
              f"{len(proposal.get('coverage', []))} 个文件覆盖")

    def _render_modifications_grouped_by_skill(
        self, modifications: list, skill_names: list
    ) -> list:
        """按 Skill 分组渲染 modifications（baseline + 多 Skill 模式专用）。

        Args:
            modifications: ProposalAgent 返回的 modification 列表，每条带 file 字段
            skill_names: Skill 名称列表（顺序敏感，按用户传入顺序渲染）

        Returns:
            Markdown 行列表，可直接拼接到 _write_proposal_md 的 lines 后面
        """
        from collections import defaultdict
        lines = [f"## 按 Skill 拆分的修改建议（{len(modifications)} 处）", ""]

        # 按 Skill 分组：file 字段前缀 = "SkillName/..." 或 "SkillName\..."
        grouped = defaultdict(list)
        other_mods = []
        for m in modifications:
            mod_file = m.get("file", "")
            matched = False
            for sn in skill_names:
                # 用 "/" 或 "\" 切分首段，判断是否以 Skill 名为前缀
                if mod_file == sn or mod_file.startswith(sn + "/") or mod_file.startswith(sn + "\\"):
                    grouped[sn].append(m)
                    matched = True
                    break
            if not matched:
                other_mods.append(m)

        # 按 skill_names 顺序渲染
        for sn in skill_names:
            mods = grouped.get(sn, [])
            lines.append(f"### {sn}")
            lines.append("")
            if not mods:
                lines.append("本 Skill 无修改建议。")
                lines.append("")
                continue
            lines.append(f"共 {len(mods)} 处修改：")
            lines.append("")
            for i, m in enumerate(mods, 1):
                action = m.get("action", "unknown").upper()
                mod_file = m.get("file", "—")
                section = m.get("section", "—")
                reason = m.get("reason", "—")
                lines.append(f"#### {i}. [{action}] {mod_file} → {section}")
                lines.append(f"**理由**: {reason}")
                lines.append("")
                current = m.get("current_content", "")
                if current:
                    lines.append("**当前内容**:")
                    lines.append("```markdown")
                    # current_content 不能截断——Edit 工具要求严格匹配,
                    # 截断会让 ApplyAgent 拿到的 current_content 与文件实际不一致,
                    # 导致 Edit 找不到匹配项或错位插入。
                    lines.append(current)
                    lines.append("```")
                    lines.append("")
                new_content = m.get("new_content", "")
                if new_content:
                    lines.append("**建议内容**:")
                    lines.append("```markdown")
                    # 写完整的 new_content,ApplyAgent 需要它做 Edit 精确替换。
                    lines.append(new_content)
                    lines.append("```")
                    lines.append("")

        # 兜底：未匹配到任何 Skill 的 modifications
        if other_mods:
            lines.append("### 其他（未匹配到已知 Skill）")
            lines.append("")
            for i, m in enumerate(other_mods, 1):
                action = m.get("action", "unknown").upper()
                mod_file = m.get("file", "—")
                section = m.get("section", "—")
                reason = m.get("reason", "—")
                lines.append(f"#### {i}. [{action}] {mod_file} → {section}")
                lines.append(f"**理由**: {reason}")
                lines.append("")
        return lines

    def _parse_json_output(self, output: str):
        """从可能夹杂日志的输出中提取 JSON。"""
        if not output or not output.strip():
            return {}

        # 去掉 cosight think 块标记
        output = output.replace("</think>", "").replace("<think>", "")

        # 先尝试直接解析
        try:
            data = json.loads(output.strip())
            return data
        except (json.JSONDecodeError, TypeError):
            pass

        # 提取 markdown code fence 中的 JSON
        fence_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', output, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except (json.JSONDecodeError, TypeError):
                pass

        # 找最后一个 { ... } 或 [ ... ] 块
        depth = 0
        start = None
        opener = None
        for i, ch in enumerate(output):
            if ch in ('{', '['):
                if depth == 0:
                    start = i
                    opener = ch
                depth += 1
            elif ch == ('}' if opener == '{' else ']'):
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        return json.loads(output[start:i+1])
                    except json.JSONDecodeError:
                        pass
        return {}

    # ─── 单个 run 分析 ───

    def analyze_run(
        self,
        run_dir: Path,
        round_num: int,
        candidate_id: int,
        run_index: int,
        case_ids: Optional[list] = None,
        force: bool = False,
    ) -> RunScore:
        """分析一个 run:填空式两步(先生成 md,再生成 json)→ 落盘两个文件。

        步骤:
        1) 拷贝模板到 run_dir(让 LLM 可视化看到参考) — 仅在目标不存在时,避免被覆盖刷新 mtime
        2) 第 1 次 LLM 调用:填 md 模板 → 写 score_analysis.md
        3) 第 2 次 LLM 调用:填 json 模板 → 写 score.json
        4) 框架从 md 内容中识别 result_score(关键词 + 范围,通用模式)

        幂等性保护:
        - force=False(默认)且 score.json 已存在 → 直接读 result_score 返回,跳过模板复制和 LLM 调用。
          防止 analyze_baseline / analyze_candidate / analyze_round 二次调用重复触发 LLM 调、
          并覆盖模板文件(导致 _template_* mtime 漂移)。
        - force=True → 强制重跑完整 3 步(用于手工重生成场景)。

        框架 0 硬编码:不扫文件、不算分、不填模板、不绑死字段名。
        LLM 用工具自主探查 data_dir,自己写数学算式。

        case_ids: 用户通过 --req-id 指定的 CASE 白名单,空=全量。
        force: 强制重跑(默认 False)。已存在的 score.json 会被视为有效,直接读取复用。
        """
        data_dir = run_dir / "data"
        if not data_dir.exists():
            data_dir = run_dir

        # 🆕 2026-08-01:md 模板路径注释保留(不再使用,代码不删以便回退)
        md_template_path = TEMPLATES_DIR / "score_analysis.md"
        json_template_path = TEMPLATES_DIR / "score.json"
        md_template_dest = run_dir / "_template_score_analysis.md"
        json_template_dest = run_dir / "_template_score.json"
        md_path = run_dir / "score_analysis.md"  # 仍定义但下面不再写
        json_path = run_dir / "score.json"

        # 0) 幂等性 fast-path:score.json 已存在 → 直接读取,跳过模板复制和 LLM 调
        if not force and json_path.exists():
            try:
                existing = json.loads(json_path.read_text(encoding="utf-8"))
                rs = existing.get("result_score")
                info = existing.get("info") if isinstance(existing.get("info"), dict) else {}
                expected = set(case_ids or [])
                evidence_complete = not expected or all(
                    isinstance(info.get(key), dict) and expected.issubset(info[key].keys())
                    for key in (
                        "gold_per_case",
                        "llm_output_per_case",
                        "diff_notes_per_case",
                        "trace_paths_per_case",
                    )
                )
                if rs is not None and evidence_complete:
                    return RunScore(
                        raw=RawMetric(
                            round_num=round_num,
                            candidate_id=candidate_id,
                            run_index=run_index,
                            result_score=float(rs),
                            info=info,
                        ),
                        reasoning="(从已有 score.json 读取,跳过重复 LLM 调)",
                        analysis_path=str(json_path),  # 🆕 2026-08-01:不再依赖 md_path
                    )
            except (json.JSONDecodeError, ValueError, OSError):
                # 解析失败:降级为完整重跑
                pass

        # 1) 拷贝模板到 run_dir(仅在目标不存在时,避免被覆盖刷新 mtime)
        # 🆕 2026-08-01:不拷贝 md 模板,只拷贝 json 模板
        for src, dst in [
            # (md_template_path, md_template_dest),  # 🆕 2026-08-01:不再拷贝 md 模板
            (json_template_path, json_template_dest),
        ]:
            if src.exists() and not dst.exists():
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        # 2) 🆕 2026-08-01 注释:不再生成 score_analysis.md
        #    原 md 生成逻辑(2 次 LLM 中的第 1 次),因 md → json 派生失败导致 round_1/2 误报 0 分,
        #    现直接跳过这步,LLM 只填 score.json。md 模板和派生函数保留以便回退。
        # md_content = self._analyze_with_agent(
        #     data_dir=data_dir,
        #     template_path=md_template_path,
        #     output_kind="md",
        #     extraction_task=self.metrics_config.extraction_task,
        #     case_ids=case_ids,
        # )
        # md_path.write_text(md_content, encoding="utf-8")

        # 3) 🆕 2026-08-01 最简化:LLM 直接 Edit `_template_score.json`
        #    框架**不读 LLM 输出文本**,只校验 LLM 写入的 score.json 是否完整。
        #    原方案让 LLM 输 ```json``` 文本 → framework 抽 fence → 解析 → 落盘,
        #    多步容易因 fence 抽取失败导致 score.json 0 字节。改为:LLM 直接 Edit 文件,
        #    framework 只校验 JSON schema 完整 + 重命名到 score.json。
        score_write_prompt = (
            self.metrics_config.extraction_task
            + "\n\n"
            + "## 任务(2026-08-01 改造方案 + 2026-08-04 macro-F1 自动派生)\n"
            + f"请用 **Edit** 或 **Write** 工具直接修改模板文件 `{json_template_dest}`。\n"
            + f"框架**不**解析你的输出文本,只校验文件 `{json_template_dest}` 的完整性。\n"
            + f"完成编辑后,框架会把 `{json_template_dest}` 重命名(复制)到 `{json_path}`。\n\n"
            + "## 必填字段(JSON schema):\n"
            + "- `info.per_case_scores`: {case_id: 0~100 数字} 字典,key 覆盖全部 case_ids,这是 macro-F1 的输入,LLM 必填\n"
            + "- `info.result_score_per_case`: 同义字段(兼容旧名),可填可不填\n"
            + "- `info.result_score_source`: 本次 macro-F1 来源说明(必填,如 `以 S7 evaluation_items[0].f1 × 100 转百分制(macro-F1 聚合,2 位小数)`)\n"
            + "- `info.gold_per_case`: {case_id: 绝对路径} 字典,gold 真文件路径\n"
            + "- `info.llm_output_per_case`: {case_id: 绝对路径} 字典,LLM 实际产出路径\n"
            + "- `info.diff_notes_per_case`: {case_id: 字符串} 字典,LLM-as-Judge 失分描述\n"
            + "- `info.trace_paths_per_case`: {case_id: [绝对路径,...]} 字典,value 是 **list**(第 1 位 trace.log + 后续 subagents/*.jsonl)\n"
            + "- `info.input_tokens_per_case` / `output_tokens_per_case` / `duration_ms_per_case`: 整数 per-case 字典\n\n"
            + "## 重要:result_score 顶层字段由 framework 自动派生\n"
            + "- **LLM 不要算 result_score,只需填 per_case_scores 字典**\n"
            + "- 框架会用 `derived = round(sum(clip(v, 0, 100) for v in per_case_scores.values()) / len(per_case_scores), 2)` 算出 macro-F1\n"
            + "- 若 LLM 误填了 result_score 字段,framework 会用 derived 强制覆写(差 > 0.5 打 warn,审计 metadata 写入 info._auto_derived)\n"
            + "- 你的唯一职责:把 9 个 case 的 F1 × 100 准确填进 per_case_scores 字典,不要在上面叠加额外换算\n\n"
            + "## 重要:绝对路径必须用 Bash realpath 拿(2026-08-04)\n"
            + "- gold_per_case / llm_output_per_case 的 value **必须**以 `/` 开头的绝对路径字符串\n"
            + "- trace_paths_per_case 的 value **必须**是 list of 以 `/` 开头的绝对路径(第 1 位 trace.log + 后续 subagents/*.jsonl)\n"
            + "- 拿法:用 Bash tool 调 `realpath <file>` 或 `readlink -f <file>`,不要凭印象写相对路径\n"
            + "- 任何一个 case 留空 → framework 校验不通过 → REWORK\n\n"
            + "## 必做动作(用工具,不要用纯文本输出)\n"
            + "1. **Read** 模板文件 `{json_template_dest}` 看清 0 值占位符\n"
            + "2. 用 **Edit** 工具替换 0 值/空字符串为实际值(每个 case_id 一组 entry)\n"
            + "3. 或用 **Write** 工具整体重写文件\n"
            + "4. 不要在 prompt 里输出 JSON 文本——让工具调用落到 sandbox 文件即可\n"
        )
        # 🆕 2026-08-03:加重试机制(deepseek API 偶发 provider_response_error,失败会 score.json 不生成 → 0 分)
        _call_agent_with_retry(
            max_retries=3,
            mode="auto",
            description=f"填充 score.json 模板({len(case_ids) if case_ids else '?'} case)",
            subagent_type=self.metrics_config.get_extractor_agent(),
            prompt=score_write_prompt,
        )

        # 3.1) 校验 LLM 是否真写了 score.json
        # 不依赖 LLM 输出文本,只看 json_template_dest / json_path 文件
        _last_verify_error = ""  # 闭包变量,记录上一次校验失败原因,REWORK 时给 LLM 反馈

        def _verify_score_json_written() -> bool:
            """校验 json_template_dest 文件存在 + JSON 合法 + 4 类 per-case 字典齐全。

            🆕 2026-08-04 改造:
            1. 增加 per-case 字典 value 非空校验(以前只校验"是 dict" + "key 集合 ⊇ case_ids",
               LLM 留空串就放行 → R8 那种"per_case 对、result_score 错"也能通过)。
            2. 增加 macro-F1 派生校验(从 info.per_case_scores 自动算,与 LLM 填的
               result_score 比对,差 > 0.5 强制覆写 + 写 info._auto_derived metadata)。
            3. 校验失败返回 False 时,记录在 self 作用域的 _last_verify_error,
               让上层 REWORK prompt 能告知 LLM 哪里填错了。
            """
            nonlocal _last_verify_error
            _last_verify_error = ""
            for candidate_path in (json_template_dest, json_path):
                if not candidate_path.exists():
                    continue
                try:
                    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as _e:
                    _last_verify_error = f"JSON 解析失败:{_e}"
                    return False
                if not isinstance(payload, dict):
                    _last_verify_error = "顶层不是 dict"
                    return False
                rs = payload.get("result_score")
                if not isinstance(rs, (int, float)) or not (0 <= rs <= 100):
                    _last_verify_error = f"result_score={rs!r} 不是 0~100 数字"
                    return False
                info_obj = payload.get("info")
                if not isinstance(info_obj, dict):
                    _last_verify_error = "info 不是 dict"
                    return False
                expected = set(case_ids or [])
                # 单步 eval 场景（goldeval 等）没有 inputs/gold、inputs/agent 证据目录：
                # 证据类 per-case 字典（gold/llm_output/diff_notes/trace）降级为可选，
                # 否则 ExtractionAgent 会因"不是 dict / 缺 case_id"被 REWORK 到耗尽。
                _has_evidence_dirs = False
                for _p3 in (run_dir / "data" / "phase3-eval", run_dir / "phase3-eval"):
                    if _p3.exists():
                        try:
                            if list(_p3.glob("*/inputs/gold")) or list(_p3.glob("*/inputs/agent")):
                                _has_evidence_dirs = True
                                break
                        except Exception:
                            pass
                # 6 个必填 per-case 字典
                _EVIDENCE_KEYS = {
                    "gold_per_case", "llm_output_per_case",
                    "diff_notes_per_case", "trace_paths_per_case",
                }
                for key in (
                    "gold_per_case",
                    "llm_output_per_case",
                    "diff_notes_per_case",
                    "trace_paths_per_case",
                    "result_score_per_case",
                    "per_case_scores",
                ):
                    if key in _EVIDENCE_KEYS and not _has_evidence_dirs:
                        continue
                    value = info_obj.get(key)
                    if not isinstance(value, dict):
                        _last_verify_error = f"info.{key} 不是 dict"
                        return False
                    if expected and not expected.issubset(value.keys()):
                        _last_verify_error = (
                            f"info.{key} 缺 case_id:"
                            f"{sorted(expected - value.keys())}"
                        )
                        return False

                # 🆕 2026-08-04:value 非空校验
                # gold/llm_output 字典:每个 case 的 value 必须以 / 开头的绝对路径字符串
                for key in ("gold_per_case", "llm_output_per_case"):
                    if not _has_evidence_dirs:
                        continue  # 单步 eval 场景无 gold/agent 证据目录 → 可选
                    value = info_obj.get(key) or {}
                    empty_cases = [
                        c for c in (expected or value.keys())
                        if not (isinstance(value.get(c), str) and value.get(c, "").startswith("/"))
                    ]
                    if empty_cases:
                        _last_verify_error = (
                            f"info.{key} 缺绝对路径 (value 必须以 / 开头, 用 Bash realpath 拿):"
                            f"{empty_cases[:5]}"
                        )
                        return False

                # trace_paths_per_case:value 是 list of 绝对路径(trace.log + subagents/*.jsonl),
                # 兼容旧格式 str(单 trace.jsonl 路径)
                # 单步 eval 场景（goldeval 等）产物里没有 trace/subagents → 该字段缺失视为合法，
                # 否则 ExtractionAgent 会被迫 REWORK 5 次（实测 dsh 场景每次 ~7 分钟）。
                _trace_val = info_obj.get("trace_paths_per_case") or {}
                _has_trace_artifacts = False
                for _probe_root in (run_dir / "data", run_dir):
                    if not _probe_root.exists():
                        continue
                    try:
                        if any(_probe_root.rglob("trace.log")) or any(_probe_root.rglob("subagents")):
                            _has_trace_artifacts = True
                            break
                    except Exception:
                        pass
                _empty_trace = [
                    c for c in (expected or _trace_val.keys())
                    if not (
                        (isinstance(_trace_val.get(c), list) and len(_trace_val[c]) > 0
                         and all(isinstance(x, str) and x.startswith("/") for x in _trace_val[c]))
                        or (isinstance(_trace_val.get(c), str) and _trace_val[c].startswith("/"))
                    )
                ]
                if _empty_trace and _has_trace_artifacts and _has_evidence_dirs:
                    _last_verify_error = (
                        f"info.trace_paths_per_case 缺绝对路径 (value 必须是 list of / 开头绝对路径, 用 Bash realpath 拿):"
                        f"{_empty_trace[:5]}"
                    )
                    return False

                # token/duration 字典:每个 case 的 value 必须是 >0 整数(file 存在时)。
                # 全部 case 全 0 → 只有产物目录**确实存在** `*Agent性能指标报告.md` 时才判 LLM 没读;
                # 报告合法缺失(如 mock/诊断场景)时,0 是合法的 —— 对齐 score.json 模板
                # "_comment_3": "缺失则填 0,不影响 result_score"。
                _has_perf_reports = False
                _p3_base = run_dir / "data" / "phase3-eval"
                if _p3_base.exists():
                    for _cd in _p3_base.iterdir():
                        if _cd.is_dir() and (_cd / "results").is_dir():
                            if list((_cd / "results").glob("*Agent性能指标报告.md")):
                                _has_perf_reports = True
                                break
                for key in (
                    "input_tokens_per_case",
                    "output_tokens_per_case",
                    "duration_ms_per_case",
                ):
                    value = info_obj.get(key) or {}
                    # 全部 case 无 token(全 0)且产物目录有 *Agent性能指标报告.md
                    # 说明 LLM 没 Read 该文件 → 算严重 fail,触发 REWORK
                    zero_count = sum(
                        1 for c in (expected or value.keys())
                        if isinstance(value.get(c), (int, float)) and value.get(c) <= 0
                    )
                    total_count = len(expected or value.keys()) or 0
                    if total_count > 0 and zero_count == total_count and _has_perf_reports:
                        # 100% case 全 0 → LLM 完全没读 *Agent性能指标报告.md
                        _last_verify_error = (
                            f"info.{key} 全部 case=0(共 {total_count} 个),"
                            f"说明 LLM 未 Read `*Agent性能指标报告.md` 提取 token/duration"
                        )
                        return False

                # 🆕 2026-08-04:macro-F1 派生校验(从 info.per_case_scores 字典自动算)
                # 优先读 per_case_scores,fallback 到 result_score_per_case
                _per_case = (
                    info_obj.get("per_case_scores")
                    or info_obj.get("result_score_per_case")
                    or {}
                )
                _derived = _derive_macro_f1(_per_case, clip=True)
                if _derived is not None:
                    _stated = float(rs)
                    _delta = abs(_derived - _stated)
                    _auto_meta = {
                        "method": "macro_f1",
                        "stated_by_llm": _stated,
                        "derived_from_per_case": _derived,
                        "delta": round(_derived - _stated, 4),
                        "case_count": len(_per_case),
                    }
                    if _delta > 0.5:
                        if _stated == 0:
                            print(
                                f"  ℹ️ [score.json] result_score 未填（模板约定 0 占位），"
                                f"framework 按 per_case macro-F1 派生 {_derived:.2f}"
                            )
                        else:
                            print(
                                f"  ⚠️ [score.json] result_score={_stated} 与 per_case_scores 字典 "
                                f"macro-F1={_derived} 差 {_delta:.2f} > 0.5，以 per_case 为准覆写"
                            )
                        payload["result_score"] = _derived
                        payload["result_score_raw"] = round(_derived / 100.0, 4)
                        payload.setdefault("info", {})["_auto_derived"] = _auto_meta
                        # 落盘覆写后的 payload
                        candidate_path.write_text(
                            json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        # 差 ≤ 0.5 不覆写,但在 info 里留 _auto_derived 作审计
                        payload.setdefault("info", {})["_auto_derived"] = _auto_meta
                        candidate_path.write_text(
                            json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                else:
                    # per_case_scores 为空(全 0 / 缺字段)
                    if expected:
                        _last_verify_error = (
                            "info.per_case_scores 全空或非数值,无法派生 macro-F1"
                        )
                        return False

                # 通过校验
                if candidate_path != json_path:
                    # 模板在 json_template_dest,真分数在 json_path → 复制
                    json_path.write_text(candidate_path.read_text(encoding="utf-8"), encoding="utf-8")
                return True
            return False

        if not _verify_score_json_written():
            print(f"  ⚠️ [score.json] LLM 没写或 schema 不完整,最多 REWORK 5 次 (原因: {_last_verify_error})")

            # 最多 5 次重试:更明确的指令
            max_retries = 5
            attempt = 0
            while attempt < max_retries:
                attempt += 1
                retry_prompt = score_write_prompt + (
                    f"\n\n## ⚠️ 第 {attempt}/{max_retries} 次重试:上次未成功\n"
                    + f"**失败原因(framework 校验返回):** {_last_verify_error or '未知(可能没 Write/Edit)'}\n"
                    + "**强制要求用 Write 或 Edit 工具修改 `{json_template_dest}` 后立即返回**,不要只输出 JSON 文本。\n"
                    + "完成后用一个空的 Bash `echo done` 验证。\n"
                )
                try:
                    from tools import Agent
                    Agent(
                        mode="auto",
                        description=f"REWORK {attempt}/{max_retries}: 直接 Edit score.json 模板",
                        subagent_type=self.metrics_config.get_extractor_agent(),
                        prompt=retry_prompt,
                        output_format="text",  # 不强求 JSON fence
                    )
                except Exception as e:
                    print(f"  ⚠️ Retry {attempt} 失败: {e}")

                if _verify_score_json_written():
                    print(f"  ✅ Retry {attempt} 成功,score.json 已落地")
                    break
                print(f"  ⚠️ Retry {attempt} 仍未落地,继续尝试")
            else:
                print("  ⚠️ [score.json] 5 次重试仍未落地,framework 跳过本次评分")
                return RunScore(
                    raw=RawMetric(
                        round_num=round_num,
                        candidate_id=candidate_id,
                        run_index=run_index,
                        result_score=0.0,
                        info={"_score_json_failed": True, "case_ids": case_ids},
                    ),
                    reasoning="(LLM 多次未落地 score.json,framework 跳过)",
                    analysis_path=str(json_path),
                )

        # 3.2) 删除模板文件(框架不再需要)
        for template_file in [json_template_dest]:
            try:
                if template_file.exists():
                    template_file.unlink()
            except OSError as e:
                print(f"  ⚠️ 删除模板文件失败 {template_file}: {e}")

        # 🆕 2026-08-04 3.3) framework 自动派生 evidence / token 字典
        # 修复 LLM 凭印象留空(2026-08-04 bug):gold/llm_output/trace/token/duration
        # 6 个字典由 framework 用 ls+realpath+Read 自动 fill,LLM 只填 per_case_scores / diff_notes / source
        try:
            _auto_summary = _auto_fill_evidence_and_resources(json_path, case_ids or [])
            if _auto_summary.get("warnings"):
                print(f"  ℹ️  [auto-fill evidence] warnings: {len(_auto_summary['warnings'])} 条")
                for _w in _auto_summary["warnings"][:3]:
                    print(f"      · {_w}")
            if _auto_summary.get("filled"):
                _filled_str = ", ".join(
                    f"{k}={v}" for k, v in _auto_summary["filled"].items() if v
                )
                if _filled_str:
                    print(f"  ℹ️  [auto-fill evidence] filled: {_filled_str}")
        except Exception as _e_auto:
            print(f"  ⚠️ [auto-fill evidence] 失败 (继续): {_e_auto}")

        # 🆕 2026-08-04 3.4) framework 自动写 result_score_raw 一致性 + 算式自描述
        # 解决 R8 那种 result_score=62.56 / result_score_raw=0.5574 的失同步 bug
        # + R11 那种 LLM 凭印象填 0 但 per_case 字典有真值的失同步 bug
        try:
            if json_path.exists():
                _payload = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(_payload, dict):
                    # 0) result_score=0 但 per_case 字典 derived>0 → 强制覆写(LLM 凭印象填 0 修复)
                    _enforce_result_score_zero_override(_payload, hard_overwrite=True)
                    # 1) result_score_raw = result_score / 100 强制覆写
                    _enforce_result_score_raw_consistency(_payload, hard_overwrite=True)
                    # 2) 写 _aggregate_formula_text(算式自描述,grep 可读)
                    _info = _payload.setdefault("info", {})
                    _per_case = _info.get("per_case_scores") or _info.get("result_score_per_case") or {}
                    _method = _info.get("result_score_aggregate", "macro_f1")
                    _info["_aggregate_formula_text"] = _compute_aggregate_formula_text(_per_case, method=_method)
                    # 3) 落盘(framework 自动派生,LLM 无需写)
                    json_path.write_text(
                        json.dumps(_payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
        except Exception as _e_calc:
            print(f"  ⚠️ [auto-derive result_score_raw/formula] 失败 (继续): {_e_calc}")

        # 4) 🆕 2026-08-01:从 score.json 读 result_score(LLM 直填,不再经 md 派生)
        result_score = 0.0
        if json_path.exists():
            try:
                _parsed_score = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(_parsed_score, dict):
                    _rs = _parsed_score.get("result_score")
                    if isinstance(_rs, (int, float)):
                        result_score = float(_rs)
            except (json.JSONDecodeError, ValueError, OSError):
                pass

        # 5) 构造 RawMetric(只用于流程状态,不参与计算)
        # 同时从 score.json 抽 result_score_per_case 等结构化信息注入 raw.info,
        # 供 build_case_run_matrix 生成 case_run_matrix / per_case_stddev / per_case_cv。
        # 字段名 result_score_per_case 来自 user-config.yaml score_extraction 段(通用化),
        # 兼容缺省时降级为通用别名。
        info: Dict[str, Any] = {
            "result_score_source": "LLM 直接填 score.json(2026-08-01,跳过 md 中间产物)",
        }
        # 2026-08-01 改造:从 score.json 文件读(framework 刚派生落盘的),不再依赖 LLM json_content
        if json_path.exists():
            try:
                parsed = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    inner_info = parsed.get("info") or {}
                    if isinstance(inner_info, dict):
                        # 透传 score.json 的完整 info(包含 input_tokens/output_tokens/duration_ms
                        # 等资源消耗字段,供 candidate 级聚合使用)
                        info.update(inner_info)
                        # 兼容旧 contract 字段别名(result_score_per_case / per_case_scores 等)
                        for key in ("result_score_per_case", "per_case_scores",
                                    "case_scores", "f1_per_case"):
                            v = inner_info.get(key)
                            if isinstance(v, dict) and v:
                                info.setdefault("_per_case_field_used", key)
                                break
            except (json.JSONDecodeError, ValueError, OSError):
                pass

        # 5.5) 自动诊断产物状况:由 ProposalAgent 直接读 score.json + 探查产物,
        # 不在框架层重复扫描(避免冗余,见 feedback_no_diagnose_hardcoded_paths)。

        raw = RawMetric(
            round_num=round_num,
            candidate_id=candidate_id,
            run_index=run_index,
            result_score=result_score,
            info=info,
        )

        return RunScore(
            raw=raw,
            reasoning="(LLM 端到端生成,见 score_analysis.md 和 score.json)",
            analysis_path=str(md_path),
        )

    def _format_value_list(self, vals: list) -> str:
        """格式化值列表为字符串：数字保留原样，其它加引号。"""
        parts = []
        for v in vals:
            if isinstance(v, (int, float)):
                parts.append(str(v))
            elif isinstance(v, str):
                # 避免过长或包含管道符破坏表格
                s = v if len(v) <= 30 else v[:27] + "..."
                s = s.replace("|", "\\|")
                parts.append(f"\"{s}\"")
            else:
                s = str(v)[:30].replace("|", "\\|")
                parts.append(s)
        return ", ".join(parts)


def _format_agg_formula(aggregate: str, vals: list) -> str:
    """根据 aggregate 类型格式化计算公式。通用化，不耦合业务。"""
    if not vals:
        return "无数据可计算"
    n = len(vals)
    if aggregate == "avg":
        s = sum(v for v in vals if isinstance(v, (int, float)))
        return f"sum({n} 项) / {n} = {s} / {n} = {s / n:.2f}"
    if aggregate == "sum":
        s = sum(v for v in vals if isinstance(v, (int, float)))
        return f"sum({n} 项) = {s}"
    if aggregate == "count":
        return f"len({n} 项) = {n}"
    if aggregate == "max":
        m = max(v for v in vals if isinstance(v, (int, float)))
        return f"max({n} 项) = {m}"
    if aggregate == "min":
        m = min(v for v in vals if isinstance(v, (int, float)))
        return f"min({n} 项) = {m}"
    if aggregate == "time_span":
        return f"time_span({n} 项时间戳) = max - min（毫秒）"
    if aggregate == "merge":
        return f"merge({n} 项) = 列表/字典合并"
    return f"{aggregate}({n} 项) = （未实现的聚合类型）"


def build_case_run_matrix(runs: list, per_case_field: str = "result_score_per_case") -> dict:
    """从 RunScore 列表构建跨 run CASE 分数矩阵。

    解决问题:6/6 CASE 跨 run 0↔非 0 波动,但提案只看到单 run,零分析。

    通用性:
      - 字段名 (result_score_per_case) 由 user-config.yaml 的 score_extraction 段声明,
        本 helper 接受外部传入,不在内部硬编码。
      - 走与 _extract_gaps_from_info_field 相同的 "_dig_path" 模式兼容嵌套字段。

    Args:
        runs: List[RunScore] 或等价 dict-list
              每个 run 需含 raw.info[per_case_field] = {case_id: [scores]}
        per_case_field: info 内 per-case 字段名,默认 result_score_per_case

    Returns:
        {
          "matrix": {case_id: [r1_score, r2_score, ...]},  # 与 runs 同序
          "per_case_stddev": {case_id: σ},
          "per_case_cv": {case_id: CV%},
          "case_ids": [list],  # 按平均分降序,便于报告输出
          "run_count": N,
        }
    """
    matrix: Dict[str, List[float]] = {}
    case_avg: Dict[str, float] = {}

    for r in runs or []:
        info = r.raw.info if hasattr(r, "raw") else (r.get("info") or {})
        per_case = info.get(per_case_field) or {}
        for case_id, scores in per_case.items():
            # 兼容两种格式:
            # - 单值 (e.g., {"RAN-xxx": 0.5}) → 每个 run 对该 case 贡献一个分数
            # - 列表 (e.g., {"RAN-xxx": [0.5, 0.3]}) → 单 run 内部多次子评测(取均值)
            if isinstance(scores, (int, float)):
                case_score = float(scores)
            elif isinstance(scores, (list, tuple)):
                case_score = sum(scores) / len(scores) if scores else 0.0
            else:
                continue  # 非数值类型,跳过
            matrix.setdefault(case_id, []).append(case_score)
            case_avg[case_id] = case_avg.get(case_id, 0.0) + case_score

    # 算 per-case stddev/CV（样本标准差 n-1）
    import statistics
    per_case_stddev: Dict[str, float] = {}
    per_case_cv: Dict[str, float] = {}
    for case_id, vals in matrix.items():
        if len(vals) > 1:
            try:
                per_case_stddev[case_id] = float(statistics.stdev(vals))
            except statistics.StatisticsError:
                per_case_stddev[case_id] = 0.0
        else:
            per_case_stddev[case_id] = 0.0
        mean_v = case_avg[case_id] / max(len(matrix[case_id]), 1) if matrix[case_id] else 0.0
        per_case_cv[case_id] = (per_case_stddev[case_id] / mean_v) if mean_v > 0 else 0.0

    # 按平均分降序排序 case_ids,便于报告稳定输出
    case_ids_sorted = sorted(
        case_avg.keys(),
        key=lambda c: -(case_avg[c] / max(len(matrix[c]), 1)),
    )

    return {
        "matrix": matrix,
        "per_case_stddev": per_case_stddev,
        "per_case_cv": per_case_cv,
        "case_ids": case_ids_sorted,
        "run_count": len(runs or []),
    }


def _call_agent_with_retry(max_retries: int = 3, **kwargs):
    """调子 Agent(ExtractionAgent 等),失败时重试 N 次(指数退避)。

    实测(2026-08-03):deepseek API 偶发 `provider_response_error` / `Unable to connect`,
    Agent() 返回空(不抛异常)。若不重试,score.json 不生成 → 该 run 0 分、评测全 0。
    重试返回非空结果;仍失败返回 ""(调用方降级处理)。
    """
    import time as _time
    last_err = ""
    for attempt in range(max_retries):
        try:
            from tools import Agent
            result = Agent(**kwargs)
            if result:
                return result
            last_err = "Agent 返回空(可能 provider_response_error / API 连接失败)"
        except Exception as e:
            last_err = str(e)
        if attempt < max_retries - 1:
            _delay = 5 * (attempt + 1)
            print(f"  ⚠️ [ExtractionAgent] 第 {attempt + 1}/{max_retries} 次尝试失败({last_err}),"
                  f"{_delay}s 后重试")
            _time.sleep(_delay)
    print(f"  ❌ [ExtractionAgent] {max_retries} 次重试仍失败: {last_err}")
    return ""


def _extract_fenced_block(text: str, lang: str) -> Optional[str]:
    """从 LLM 输出中抽离 ```lang 围栏代码块的内容。

    框架 0 业务耦合:不假设 LLM 输出结构,只匹配 ```lang 围栏。
    找不到对应围栏时返回 None。

    Args:
        text: LLM 完整输出
        lang: 围栏语言标识(如 "markdown" / "json" / "" 通用)

    Returns: 围栏内的文本(已 strip),未找到时 None
    """
    if not text:
        return None
    # 匹配 ```<lang> 开头,内容任意,``` 结尾
    m = re.search(
        rf"```{re.escape(lang)}\s*\n(.*?)\n```",
        text, re.DOTALL | re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    # 退化:如果没指定 lang 或 lang 通用,匹配任意 ``` 块(取第一个)
    if not lang:
        m = re.search(r"```\w*\s*\n(.*?)\n```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
    # 兜底:LLM 未用围栏包裹,直接输出 raw JSON/MD 时的通用救场
    # 框架 0 业务耦合,只判断"看起来就是合法内容" → 原样返回
    # 下游 _validate_and_fix_json 会再做一次 json.loads 校验,不会污染数据
    stripped = text.strip()
    if not stripped:
        return None
    # JSON 兜底:以 { 或 [ 开头且能 json.loads 解析
    if lang == "json" and stripped[0] in ("{", "["):
        import json as _json
        try:
            _json.loads(stripped)
            return stripped
        except _json.JSONDecodeError:
            pass
    # MD 兜底:含 markdown 标题或看起来不像纯文本(避免空 LLM 答复被误判)
    if lang == "markdown" and re.search(r"^#{1,6}\s+\S", stripped, re.MULTILINE):
        return stripped
    return None


def _extract_result_score_from_md(md_content: str) -> float:
    """从 LLM 自由输出的 markdown 中识别 result_score 数字(百分制 0~100)。

    最朴素的兜底:不预设任何 schema/段名/字段名,扫描 markdown 中的
    数字并挑最可能是 result_score 的那个。

    优先级:
    1. 通用分数关键词(score/f1/accuracy/precision/quality/metric)附近
       0~30 字符内的第一个数字;若该数字在 0~100 之间则按原值返回
    2. 全文第一个 0~100 之间的数字
    3. 都抽不到 → 0.0(框架不兜底算分)

    通用性:不绑死 result_score 字段名、不绑死"## 摘要"段名、不绑死
    YAML frontmatter 格式。LLM 可以自由把分数放在 markdown 任何位置。

    统一制度:百分制 0~100,保留 2 位小数。

    Returns: 0.0~100.0 之间的 float,失败时 0.0。
    """
    if not md_content or not md_content.strip():
        return 0.0

    # 模式 1: 通用分数关键词附近的数字(不绑死 result_score)
    # 关键词列表:通用分数词汇 + 中文分数词
    # 关键:数字**前**必须有数字边界（:或：或 is 或 为 等强分隔符），避免"f1=2PR/(P+R)"等公式描述
    # 把 "2" 误识别为 result_score
    m = re.search(
        r"(?:^|[\s\n:：]|is|are|为|是|等于|得分|分数|score|f1|accuracy|precision|quality|metric|综合分|总分)"
        r"[:：是为\s]*[\(\[]*([\d.]+)(?:[\s)\]%,，;。]|$)",
        md_content, re.IGNORECASE,
    )
    if m:
        try:
            val = float(m.group(1))
            if 0.0 <= val <= 100.0:
                # 百分制 0~100,统一保留 2 位小数
                return round(val, 2)
        except (ValueError, TypeError):
            pass

    # 模式 2: 全文第一个 0~100 之间的数字(纯兜底)
    for m in re.finditer(r"([\d.]+)", md_content):
        try:
            val = float(m.group(1))
            if 0.0 < val <= 100.0:
                return round(val, 2)
        except (ValueError, TypeError):
            continue

    return 0.0


def _try_derive_score_json_from_md(md_path: Path, json_template_path: Path, case_ids=None) -> Optional[str]:
    """2026-08-01 改造:framework 直接从 score_analysis.md 自动派生 score.json,不再调第二次 LLM。

    设计原则:用稳定 markdown 表格结构做正则解析,**不依赖** LLM 输出细节。
    解析失败 → 返回 None,调用方降级到 LLM 第二次调用(或空兜底)。

    解析范围(对应 score.json 的 4 类字典 + 资源消耗):
    - 顶层:result_score / timestamp / case_count / aggregate_method / zero_root_cause
    - 资源聚合:avg_input_tokens / avg_output_tokens / avg_duration_ms
              input_tokens / output_tokens / duration_ms(sum 字段)
              valid_token_case_count / valid_duration_case_count
    - per-case 字典:result_score_per_case / input_tokens_per_case
                    output_tokens_per_case / duration_ms_per_case
                    gold_per_case / llm_output_per_case / diff_notes_per_case
                    trace_paths_per_case

    Returns:合法 JSON 字符串,失败返回 None。
    """
    try:
        if not md_path.exists() or not json_template_path.exists():
            return None
        md_text = md_path.read_text(encoding="utf-8")
        template_text = json_template_path.read_text(encoding="utf-8")
        # 1) 解析 JSON 模板 → 拿到结构 + 默认值
        template = json.loads(template_text)
        info = template.get("info", {})

        # 2) 解析"## 摘要"段(单行 - **键**: 值)
        # 🆕 2026-08-01:优先匹配 `**结果分数**: <num>` 这个精确锚点(避免 _extract_result_score_from_md
        # 把 "Run: 1" 等无关数字识别为 result_score)
        result_score_m = re.search(r"\*\*结果分数\*\*:\s*([\d.]+)", md_text)
        if result_score_m:
            try:
                result_score = float(result_score_m.group(1))
            except (ValueError, TypeError):
                result_score = _extract_result_score_from_md(md_text)
        else:
            result_score = _extract_result_score_from_md(md_text)
        case_count_m = re.search(r"\*\*CASE 总数\*\*:\s*(\d+)", md_text)
        aggregate_m = re.search(r"\*\*分数聚合方式\*\*:\s*(.+?)(?:\n|$)", md_text)
        avg_in_m = re.search(r"\*\*平均输入 Token\*\*:\s*(\d+)", md_text)
        avg_out_m = re.search(r"\*\*平均输出 Token\*\*:\s*(\d+)", md_text)
        avg_dur_m = re.search(r"\*\*平均时间消耗\*\*:\s*(\d+)", md_text)
        total_in_m = re.search(r"\*\*总输入 Token\*\*[^*]*:\s*(\d+)", md_text)
        total_out_m = re.search(r"\*\*总输出 Token\*\*[^*]*:\s*(\d+)", md_text)
        total_dur_m = re.search(r"\*\*总时间消耗\*\*[^*]*:\s*(\d+)", md_text)

        # 3) 解析"## 各 CASE 明细"表格 — 抽取 per-case 分数 + 资源消耗
        per_case_score: dict[str, float] = {}
        per_case_in: dict[str, int] = {}
        per_case_out: dict[str, int] = {}
        per_case_dur: dict[str, int] = {}
        # 匹配 markdown 表格行:|`RAN-xxx`|<分数>|<in>|<out>|<dur>|<是/否>|...
        case_table_re = re.compile(
            r"^\|\s*([A-Za-z0-9_-]{3,})\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
            re.MULTILINE,
        )
        for m in case_table_re.finditer(md_text):
            cid, score, inp, outp, dur = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            # 过滤掉表头(分数 0.0 且 cid 不是 RAN-/CASE-/TC- 等)
            if not cid[0].isalpha() or cid.upper() not in {"RAN"} and not cid.startswith(("CASE-", "TC-", "REQ-", "TEST-")):
                # 简单白名单:首段以字母开头 + 含数字
                if not any(ch.isdigit() for ch in cid):
                    continue
            try:
                per_case_score[cid] = float(score)
                per_case_in[cid] = int(inp)
                per_case_out[cid] = int(outp)
                per_case_dur[cid] = int(dur)
            except (ValueError, TypeError):
                continue

        # 4) 解析"## CASE 证据数据"表格 — gold/llm_output/diff_notes 绝对路径
        gold_per_case: dict[str, str] = {}
        llm_per_case: dict[str, str] = {}
        diff_notes_per_case: dict[str, str] = {}
        # 匹配 `| <cid> | `/.../gold/...` | `/.../agent/...` | <diff_notes 全文> |`
        evidence_re = re.compile(
            r"^\|\s*([A-Za-z0-9_-]{3,})\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*$",
            re.MULTILINE,
        )
        for m in evidence_re.finditer(md_text):
            cid, gold_v, llm_v, notes = m.group(1), m.group(2), m.group(3), m.group(4)
            # 过滤表头(CASE ID 列名)
            if cid.upper() in {"CASE", "CASE_ID", "CASE ID"}:
                continue
            gold_per_case[cid] = gold_v
            llm_per_case[cid] = llm_v
            diff_notes_per_case[cid] = notes

        # 5) 解析"## CASE Trace 路径"表格 — trace 绝对路径
        trace_per_case: dict[str, str] = {}
        trace_re = re.compile(
            r"^\|\s*([A-Za-z0-9_-]{3,})\s*\|\s*`([^`]*trace\.jsonl)`\s*\|",
            re.MULTILINE,
        )
        for m in trace_re.finditer(md_text):
            cid, trace_v = m.group(1), m.group(2)
            if cid.upper() in {"CASE", "CASE_ID", "CASE ID"}:
                continue
            trace_per_case[cid] = trace_v

        # 6) 填充 info 字典
        if result_score > 0:
            info["result_score"] = result_score
            info["result_score_raw"] = result_score
        if case_count_m:
            info["case_count"] = int(case_count_m.group(1))
        if aggregate_m:
            info["aggregate_method"] = aggregate_m.group(1).strip()
        info["result_score_per_case"] = per_case_score
        info["input_tokens_per_case"] = per_case_in
        info["output_tokens_per_case"] = per_case_out
        info["duration_ms_per_case"] = per_case_dur

        # 🆕 2026-08-01 加固:gold/llm_output 路径按 glob 校验,不匹配自动 fallback
        # (防 LLM 看到 inputs/gold/gold.md 87994B 大文件后,凭直觉选错成 gold.md 而非 R_*.md)
        import fnmatch
        gold_globs = ["R_*.md", "全量_*.md"]
        llm_globs = ["C_*.md", "全量_*.md"]

        def _enforce_glob(path: str, globs: list, case_dir: Path) -> str:
            """若路径 basename 不匹配 glob,从 case_dir/inputs/{gold,agent}/ 重新按 glob 第一个匹配。"""
            name = Path(path).name
            if any(fnmatch.fnmatch(name, g) for g in globs):
                return path
            # 不匹配 → 在 case_dir/inputs/{gold,agent}/ 下找第一个 glob 匹配
            for sub in [case_dir / "inputs" / "gold", case_dir / "inputs" / "agent"]:
                if not sub.exists():
                    continue
                for g in globs:
                    matches = sorted(sub.glob(g))
                    if matches:
                        new_path = str(matches[0].resolve())
                        if new_path != path:
                            print(f"  [glob校验] {name} 不匹配 {globs},自动 fallback 到 {Path(new_path).name}")
                        return new_path
            return path  # 找不到任何匹配 → 保留原路径(让 framework 上层告警)

        # 反推每个 case 的 case_dir(从 gold 路径推断:phase3-eval/{case}_*/inputs/gold/R_*.md)
        for cid in list(gold_per_case.keys()):
            gp = gold_per_case[cid]
            # 反推 case_dir(从 gold_per_case 路径往上两级)
            case_dir = Path(gp).parent.parent.parent  # inputs/gold/file → case_dir
            gold_per_case[cid] = _enforce_glob(gp, gold_globs, case_dir)
            lp = llm_per_case.get(cid, "")
            if lp:
                case_dir2 = Path(lp).parent.parent.parent
                llm_per_case[cid] = _enforce_glob(lp, llm_globs, case_dir2)

        info["gold_per_case"] = gold_per_case
        info["llm_output_per_case"] = llm_per_case
        info["diff_notes_per_case"] = diff_notes_per_case
        info["trace_paths_per_case"] = trace_per_case

        # 资源消耗优先用 LLM 报告的 avg/total;否则由 per-case 算
        if avg_in_m:
            info["avg_input_tokens"] = int(avg_in_m.group(1))
        elif per_case_in:
            valid = [v for v in per_case_in.values() if v > 0]
            info["avg_input_tokens"] = int(sum(valid) / len(valid)) if valid else 0
        if avg_out_m:
            info["avg_output_tokens"] = int(avg_out_m.group(1))
        elif per_case_out:
            valid = [v for v in per_case_out.values() if v > 0]
            info["avg_output_tokens"] = int(sum(valid) / len(valid)) if valid else 0
        if avg_dur_m:
            info["avg_duration_ms"] = int(avg_dur_m.group(1))
        elif per_case_dur:
            valid = [v for v in per_case_dur.values() if v > 0]
            info["avg_duration_ms"] = int(sum(valid) / len(valid)) if valid else 0
        info["avg_duration_seconds"] = round(info["avg_duration_ms"] / 1000, 2)

        if total_in_m:
            info["input_tokens"] = int(total_in_m.group(1))
        elif per_case_in:
            info["input_tokens"] = sum(per_case_in.values())
        if total_out_m:
            info["output_tokens"] = int(total_out_m.group(1))
        elif per_case_out:
            info["output_tokens"] = sum(per_case_out.values())
        if total_dur_m:
            info["duration_ms"] = int(total_dur_m.group(1))
        elif per_case_dur:
            info["duration_ms"] = sum(per_case_dur.values())
        info["duration_seconds"] = round(info["duration_ms"] / 1000, 2)

        # valid_*_count = per-case 中 >0 的 case 数
        info["valid_token_case_count"] = sum(1 for v in per_case_in.values() if v > 0)
        info["valid_duration_case_count"] = sum(1 for v in per_case_dur.values() if v > 0)

        # 7) zero_root_cause / timestamp
        zero_m = re.search(r"## 根因分析[\s\S]*?(?=\n## |\Z)", md_text)
        # timestamp 用 mtime(避免 LLM 编造时间)
        import datetime
        ts = datetime.datetime.fromtimestamp(md_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        template["timestamp"] = ts

        # 8) result_score_source 描述(契约固定)
        info["result_score_source"] = "framework 从 score_analysis.md 自动派生(regex 解析,fail-safe 到 LLM 二次调用)"

        # 9) 校验 evidence 完整性 — 任一字典为空说明解析失败
        if not per_case_score or not gold_per_case:
            return None

        template["info"] = info
        template["result_score"] = result_score if result_score > 0 else template.get("result_score", 0)
        return json.dumps(template, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [md→json] 派生失败: {e}")
        return None


def _aggregate_resource_usage(runs):
    """从 runs[].raw.info 聚合 input_tokens/output_tokens/duration_ms/f1 的 4 类统计。

    口径从 sum 改 per-case + mean,与 result_score 一致。
    - mean_input_tokens:macro-mean over cases(每个 run 内部算 mean,跨 run 再 mean)
    - per_case_input_tokens:dict {case_id: tokens} 跨 run 同 case_id 取 mean
    - valid_token_case_count:token>0 的 case 数(mean 分母)
    - 缺失 case 自动从 mean 分母中隔离(避免 sum 口径被 0 拉低)

    兼容旧 schema(LLM 端填的是 sum 而非 mean):
    - 优先读 info.avg_input_tokens(新契约,推荐)
    - fallback 到 info.input_tokens / case_count(旧 sum 折算)
    - per-case dict 缺失时:从 input_tokens 推不出 per-case,空 dict
    """
    in_mean_sum = out_mean_sum = dur_mean_sum = 0  # 跨 run mean 累加,顶层 mean = sum/N
    in_sum = out_sum = dur_sum = 0  # 跨 run sum 累加(deprecated,total_* 字段)
    in_count = out_count = dur_count = 0
    f1_sum = 0.0
    f1_count = 0
    in_vals, out_vals, dur_vals, f1_vals = [], [], [], []
    per_case_in: dict = {}   # case_id -> list[int]
    per_case_out: dict = {}
    per_case_dur: dict = {}
    valid_input_cases: set = set()      # input_tokens>0 的 case
    valid_output_cases: set = set()     # output_tokens>0 的 case
    valid_duration_cases: set = set()   # duration_ms>0 的 case

    def _resolve_run(info: dict, key_sum: str, key_avg: str, key_per_case: str, per_case_dict: dict, valid_set: set) -> tuple[int, int]:
        """解析单个 run 的 token/duration 数值,返回 (mean_for_run, sum_for_run)。

        - mean_for_run:macro-mean over cases(排除 token=0 的 case);per-case dict 缺失时 fallback 到 key_avg → key_sum
        - sum_for_run:sum over cases(含 0 值);per-case dict 缺失时 fallback 到 key_sum
        同时填充 per_case_dict(累积所有 case_id 用于跨 run mean)。
        """
        per_case_raw = info.get(key_per_case) or {}
        if isinstance(per_case_raw, dict) and per_case_raw:
            all_vals = [int(v) for v in per_case_raw.values() if isinstance(v, (int, float))]
            valid_vals = [int(v) for v in all_vals if int(v) > 0]
            for cid, v in per_case_raw.items():
                if isinstance(v, (int, float)):
                    iv = int(v)
                    per_case_dict.setdefault(str(cid), []).append(iv)
                    if iv > 0:
                        valid_set.add(str(cid))
            mean_v = int(round(sum(valid_vals) / len(valid_vals))) if valid_vals else 0
            sum_v = sum(all_vals)
            return mean_v, sum_v
        # fallback:旧契约,只有 sum 或 avg(顶层字段)
        avg_v = info.get(key_avg)
        if not isinstance(avg_v, (int, float)) or avg_v <= 0:
            avg_v = info.get(key_sum)
        sum_v_raw = info.get(key_sum)
        if not isinstance(sum_v_raw, (int, float)) or sum_v_raw <= 0:
            sum_v_raw = avg_v if isinstance(avg_v, (int, float)) and avg_v > 0 else 0
        mean_v_fb = int(avg_v) if isinstance(avg_v, (int, float)) and avg_v > 0 else 0
        sum_v_fb = int(sum_v_raw) if isinstance(sum_v_raw, (int, float)) and sum_v_raw > 0 else 0
        return mean_v_fb, sum_v_fb

    for r in runs or []:
        info = getattr(getattr(r, "raw", None), "info", None) or {}
        in_mean, in_sum_v = _resolve_run(info, "input_tokens", "avg_input_tokens", "input_tokens_per_case", per_case_in, valid_input_cases)
        out_mean, out_sum_v = _resolve_run(info, "output_tokens", "avg_output_tokens", "output_tokens_per_case", per_case_out, valid_output_cases)
        dur_mean, dur_sum_v = _resolve_run(info, "duration_ms", "avg_duration_ms", "duration_ms_per_case", per_case_dur, valid_duration_cases)
        # mean 跨 run 取 mean of means
        if in_mean > 0:
            in_mean_sum += in_mean
            in_count += 1
            in_vals.append(in_mean)
        else:
            in_vals.append(0)
        if out_mean > 0:
            out_mean_sum += out_mean
            out_count += 1
            out_vals.append(out_mean)
        else:
            out_vals.append(0)
        if dur_mean > 0:
            dur_mean_sum += dur_mean
            dur_count += 1
            dur_vals.append(dur_mean)
        else:
            dur_vals.append(0)
        # sum 跨 run 累加(deprecated,作向后兼容)
        in_sum += in_sum_v
        out_sum += out_sum_v
        dur_sum += dur_sum_v
        # f1 跨 run 聚合(与 token/duration 同样模式;不能 sum,只能 mean)
        f1 = info.get("result_score")
        if isinstance(f1, (int, float)) and 0 <= f1 <= 100:
            f1_sum += float(f1); f1_count += 1
            f1_vals.append(float(f1))
        else:
            f1_vals.append(0.0)

    # 跨 run per-case dict:同一 case_id 取 mean
    per_case_input_tokens_final = {cid: int(round(sum(vs) / len(vs))) for cid, vs in per_case_in.items() if vs}
    per_case_output_tokens_final = {cid: int(round(sum(vs) / len(vs))) for cid, vs in per_case_out.items() if vs}
    per_case_duration_ms_final = {cid: int(round(sum(vs) / len(vs))) for cid, vs in per_case_dur.items() if vs}

    # 顶层 mean:跨 run 取 mean of means
    mean_in = int(round(in_mean_sum / in_count)) if in_count else 0
    mean_out = int(round(out_mean_sum / out_count)) if out_count else 0
    mean_dur = int(round(dur_mean_sum / dur_count)) if dur_count else 0

    def _stddev_pct(vals):
        if len(vals) < 2: return 0
        m = sum(vals) / len(vals)
        return int(round((sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5))

    def _stddev_float(vals):
        """与 _stddev_pct 同样公式但保留浮点精度(用于 f1)"""
        if len(vals) < 2: return 0.0
        m = sum(vals) / len(vals)
        return round(((sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5), 4)

    def _cv(vals):
        """CV = stddev / mean(基于 mean 口径,与 result_score.cv 一致)"""
        if len(vals) < 2: return 0.0
        m = sum(vals) / len(vals)
        if m == 0: return 0.0
        sd = (sum((x - m) ** 2 for x in vals) / len(vals)) ** 0.5
        return round(sd / m, 4)

    return {
        # 新字段:per-case + mean 口径(主推,跟 result_score 一致)
        "mean_input_tokens": mean_in,
        "mean_output_tokens": mean_out,
        "mean_duration_ms": mean_dur,
        "mean_duration_seconds": round(mean_dur / 1000, 2) if mean_dur else 0.0,
        "per_case_input_tokens": per_case_input_tokens_final,
        "per_case_output_tokens": per_case_output_tokens_final,
        "per_case_duration_ms": per_case_duration_ms_final,
        "valid_token_case_count": len(valid_input_cases & valid_output_cases),  # input AND output 都有效
        "valid_duration_case_count": len(valid_duration_cases),
        # 旧字段:deprecated 保留作向后兼容(sum 口径,会被 0 拉低)
        "total_input_tokens": in_sum,
        "total_output_tokens": out_sum,
        "total_duration_ms": dur_sum,
        # stddev/cv 基于 mean 算(与 result_score 一致)
        "stddev_input_tokens": _stddev_pct(in_vals),
        "cv_input_tokens": _cv(in_vals),
        "stddev_output_tokens": _stddev_pct(out_vals),
        "cv_output_tokens": _cv(out_vals),
        "stddev_duration_ms": _stddev_pct(dur_vals),
        "cv_duration_ms": _cv(dur_vals),
        # f1 跨 run 聚合(与 token/duration 同样模式;f1 不能 sum,只 mean)
        "avg_f1": round(f1_sum / f1_count, 2) if f1_count else 0.0,
        "stddev_f1": _stddev_float(f1_vals),
        "cv_f1": _cv(f1_vals),
        "per_run_f1": [round(v, 2) for v in f1_vals],
    }












class ScoreAnalyzerAgent(ScoreAnalyzerAgentBase):
    """评测评分分析子 Agent：编排指标提取与缺口分析的统一入口。

    继承自 ScoreAnalyzerAgentBase 的初始化与辅助方法，补充 baseline / 候选 / 轮次
    分层汇总等高层方法。通用设计：不耦合任何具体业务字段，所有规则来自 YAML。
    """

    @staticmethod
    def _extract_per_case_from_run(run_score):
        """从 RunScore 的 raw.info 抽 per-case 分数。

        analyze_run 已注入 result_score_per_case / per_case_scores / case_scores / f1_per_case
        等通用字段名，按注入顺序返回首个非空 dict。
        """
        info = getattr(getattr(run_score, "raw", None), "info", None) or {}
        for key in ("result_score_per_case", "per_case_scores", "case_scores", "f1_per_case"):
            v = info.get(key)
            if isinstance(v, dict) and v:
                return {str(k): float(val) for k, val in v.items() if val is not None}
        return {}

    @staticmethod
    def _avg(values):
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else 0.0

    @staticmethod
    def _round_pct(x):
        """百分制字段(0~100):写入 JSON 前 round 到 2 位小数。None 透传。

        统一制度:所有分数字段(avg_result_score/composite/normalized/result_score)
        都用百分制 0~100,2 位小数。
        """
        return None if x is None else round(float(x), 2)

    @staticmethod
    def _avg_opt(values):
        """返回 Optional[float]，当所有值都为 None 时返回 None。"""
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else None

    @staticmethod
    def _extract_run_index(name):
        """从 'run_3' 提取 3。"""
        parts = name.rsplit("_", 1)
        if len(parts) == 2:
            try:
                return int(parts[1])
            except ValueError:
                return -1
        return -1


    # ─── 分层汇总（baseline/候选/轮次）通用方法 ───

    def write_layered_summary_md(self, layer_dir: Path, layer_label: str,
                                  runs: list, agg_composite: Optional[float] = None,
                                  stddev: Optional[float] = None,
                                  extra_sections: Optional[List[str]] = None) -> Path:
        """生成"分层汇总 MD"（baseline/候选/轮次级），含数据来源、键值对、计算过程。

        通用化：基于传入的 runs 列表自动生成，不耦合具体业务字段。
        命名约定：output = `<layer_dir>/score_<layer_label>_analysis.md`

        Args:
            layer_dir: 层级目录（如 baseline/、round_1/candidate_0/、round_1/）
            layer_label: 层级标签（如 "baseline"、"candidate_0"、"round_1"）
            runs: 该层级下所有 run 的 RunScore 列表
            agg_composite: 聚合综合分（可选）
            stddev: 标准差（可选）
            extra_sections: 额外 MD 区块（可选，如 proposal、selection_decision）

        Returns:
            生成的 MD 文件路径
        """
        only_f1 = self._is_only_f1_mode()
        mode_text = "仅 F1（已量化，无需归一化）" if only_f1 else "多维度归一化"

        lines = [
            f"# {layer_label} 评分分析报告",
            "",
            f"- **层级**: {layer_label}",
            f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **Run 数**: {len(runs)}",
            f"- **评分模式**: {mode_text}",
            "",
        ]

        # 1. 各 Run 分数对比表
        lines.append("## 各 Run 分数对比")
        lines.append("")
        lines.append("| Run | 结果分数 | 结果来源 | 数据来源文件数 |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for r in runs:
            inf = r.raw.info or {}
            rs = f"{r.raw.result_score:.2f}" if r.raw.result_score is not None else "N/A"
            src = inf.get("result_score_source", "—") or "—"
            per_source_r = self._collect_per_source_files(r, inf)
            n_files = len(per_source_r)
            lines.append(f"| Run {r.raw.run_index} | {rs} | {src[:50]}{'...' if len(src) > 50 else ''} | {n_files} |")
        lines.append("")

        # 2. 聚合统计
        if agg_composite is not None or stddev is not None:
            lines.append("## 聚合统计")
            lines.append("")
            if agg_composite is not None:
                lines.append(f"- **综合分（avg × 100）**: {agg_composite:.2f}")
            if stddev is not None:
                lines.append(f"- **标准差（σ）**: {stddev:.2f}")
            # 列出所有 run 的原始分数
            run_scores = [r.raw.result_score for r in runs if r.raw.result_score is not None]
            if run_scores:
                lines.append(f"- **Run 分数**: [{', '.join(f'{s:.2f}' for s in run_scores)}]")
                avg = sum(run_scores) / len(run_scores)
                lines.append(f"- **计算**: mean([{', '.join(f'{s:.2f}' for s in run_scores)}]) = {avg:.2f}")
            lines.append("")

        # 3. 数据来源文件清单（汇总各 run 的 per_source，去重）
        lines.append("## 数据来源文件")
        lines.append("")
        lines.append("以下文件参与了该层级的评分指标提取。")
        lines.append("去重：跨 Run 共享同一文件路径时只展示一次。")
        lines.append("")
        seen_files = set()
        per_source_seen_per_run: List[Tuple[object, Dict[str, list]]] = []
        for r in runs:
            inf = r.raw.info or {}
            per_source_r = self._collect_per_source_files(r, inf)
            per_source_seen_per_run.append((r, per_source_r))
            json_path = inf.get("result_score_json_path") or "auto"
            for fpath in sorted(per_source_r.keys()):
                if fpath in seen_files:
                    continue
                seen_files.add(fpath)
                vals = per_source_r[fpath]
                lines.append(f"- `{fpath}` → 提取到 {len(vals)} 个值（json_path=`{json_path}`）")
        if not seen_files:
            lines.append("- （无匹配文件）")
        lines.append("")

        # 4. 键值对明细（汇总各 run 的扁平原始值）
        lines.append("## 键值对明细")
        lines.append("")
        for r, per_source_r in per_source_seen_per_run:
            inf = r.raw.info or {}
            json_path = inf.get("result_score_json_path") or "auto"
            if not per_source_r:
                continue
            lines.append(f"### Run {r.raw.run_index}（json_path=`{json_path}`）")
            lines.append("")
            lines.append("| 文件 | 原始值（完整列表） |")
            lines.append("| :--- | :--- |")
            for fpath in sorted(per_source_r.keys()):
                vals = per_source_r[fpath]
                vals_str = self._format_value_list(vals)
                lines.append(f"| `{fpath}` | {vals_str} |")
            lines.append("")

        # 5. 计算过程推理
        lines.append("## 计算过程")
        lines.append("")
        for r in runs:
            inf = r.raw.info or {}
            json_path = inf.get("result_score_json_path") or "auto"
            aggregate = inf.get("result_score_aggregate", "avg")
            all_vals = inf.get("result_score_raw_values", [])
            if not all_vals:
                continue
            lines.append(f"### Run {r.raw.run_index}")
            lines.append("")
            lines.append(f"1. 匹配文件 {len(inf.get('result_score_per_source', {}))} 个")
            lines.append(f"2. 按 json_path `{json_path}` 提取，共 {len(all_vals)} 个值")
            lines.append(f"3. 原始值: `{self._format_value_list(all_vals[:30])}`"
                        + (f"（仅显示前 30 个，共 {len(all_vals)}）" if len(all_vals) > 30 else ""))
            lines.append(f"4. 聚合: `{aggregate}` → {_format_agg_formula(aggregate, all_vals)}")
            if r.raw.result_score is not None:
                lines.append(f"5. 本 Run 最终分数: `{r.raw.result_score}`")
            lines.append("")

        # 6. 各 Run 的 _analysis.md 完整内容（嵌入）
        # 通用化：直接读取 run 目录下的 score_analysis.md 并嵌入，保证与单个 run 模板一致
        # 避免在聚合层重新生成（业务耦合），且能保留每个 run 的完整推理过程
        embedded_runs = self._embed_run_analysis_md(runs)
        if embedded_runs:
            lines.append("## 各 Run 详细分析（嵌入）")
            lines.append("")
            lines.append("以下为每个 Run 自身的 score_analysis.md 完整内容（自动嵌入，避免重复生成）。")
            lines.append("")
            lines.append(embedded_runs)
            lines.append("")

        # 7. 额外区块（如 proposal、selection_decision）
        if extra_sections:
            for section in extra_sections:
                lines.append(section)
                lines.append("")

        # 写入文件
        out_path = layer_dir / f"score_{layer_label}_analysis.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        # 清理旧名（兼容旧 task 产物）：candidate_K_score_analysis.md / round_K_score_analysis.md
        legacy_names = []
        if layer_label.startswith("candidate_"):
            legacy_names.append(layer_dir / f"{layer_label}_score_analysis.md")
        elif layer_label.startswith("round_"):
            legacy_names.append(layer_dir / f"{layer_label}_score_analysis.md")
        for legacy in legacy_names:
            if legacy.exists() and legacy != out_path:
                try:
                    legacy.unlink()
                except OSError:
                    pass
        return out_path

    def _embed_run_analysis_md(self, runs: list) -> str:
        """读取每个 run 的 score_analysis.md 并拼接为嵌入区块。

        通用化：直接读取 run_dir/score_analysis.md 文本（已由 analyze_run 生成），
        不耦合业务字段。返回拼接后的字符串（每个 run 之间用分割线隔开）。
        """
        if not runs:
            return ""
        chunks: List[str] = []
        for r in runs:
            # 优先使用 analysis_path（RunScore 的标准字段，由 analyze_run 写入）
            analysis_path = getattr(r, "analysis_path", None)
            if not analysis_path:
                continue
            md_path = Path(analysis_path)
            if not md_path.exists():
                continue
            try:
                content = md_path.read_text(encoding="utf-8").rstrip()
            except Exception:
                continue
            # 把一级标题降级为三级，避免与聚合层标题冲突
            content = re.sub(r"^#\s+", "### ", content, count=1, flags=re.MULTILINE)
            chunks.append(content)
            chunks.append("\n\n---\n\n")
        if not chunks:
            return ""
        # 去掉最后一个分割线
        if chunks[-1].strip() == "---":
            chunks.pop()
        return "".join(chunks)

    def _collect_per_source_files(self, run_score, info: dict) -> Dict[str, list]:
        """通用收集"每个数据来源文件 → 提取的原始值列表"。

        兼容 LLM 不同流派：
        - 流派 A:info["result_score_per_source"] = {fpath: [vals]}（直接）
        - 流派 B:info["result_score_per_case"] = {case_id: score} → 映射到 data_dir 下对应文件
        - 兜底:从 run.analysis_path 推导 data_dir,glob 业务方评测产物 JSON

        返回:key 是相对 data_dir 的文件路径(流派 A)/case_id(流派 B)/relative_path(兜底),
             顺序稳定(按 key 排序)便于跨 Run 去重展示。
        """
        # 流派 A:per_source 直接返回
        per_source = info.get("result_score_per_source")
        if isinstance(per_source, dict) and per_source:
            return {str(k): list(v) if isinstance(v, list) else [v] for k, v in per_source.items()}

        # 流派 B:per_case → 尝试在 data_dir 下找与 case_id 同名的目录
        per_case = info.get("result_score_per_case")
        if isinstance(per_case, dict) and per_case:
            data_dir = self._resolve_data_dir_from_run(run_score)
            result: Dict[str, list] = {}
            for case_id, val in per_case.items():
                case_id_str = str(case_id)
                # 优先尝试在 data_dir 下找 case_id 子目录里的 results JSON
                rel_path = None
                if data_dir and data_dir.exists():
                    # 常见结构: data_dir/{case_id}/results/*.json
                    case_dir = data_dir / case_id_str
                    if case_dir.exists():
                        for cand_pat in ("results/*.json", "*.json"):
                            cand_files = sorted(case_dir.glob(cand_pat))
                            if cand_files:
                                rel_path = str(cand_files[0].relative_to(data_dir))
                                break
                # 找不到具体文件 → 用 case_id 作为兜底 key(避免丢数据)
                key = rel_path if rel_path else case_id_str
                result[key] = [val]
            return result

        # 兜底:从 data_dir 扫描
        data_dir = self._resolve_data_dir_from_run(run_score)
        if data_dir and data_dir.exists():
            glob_patterns = ["phase*eval/**/results/*.json", "**/results/*.json", "**/*.json"]
            for pat in glob_patterns:
                files = sorted(data_dir.glob(pat))
                if files:
                    return {str(f.relative_to(data_dir)): ["<scanned>"] for f in files}
        return {}

    def _resolve_data_dir_from_run(self, run_score) -> Optional[Path]:
        """从 RunScore.analysis_path 推导 data_dir 路径。"""
        ap = getattr(run_score, "analysis_path", None)
        if not ap:
            return None
        p = Path(ap)
        run_dir = p.parent if p.name == "score_analysis.md" else p.parent
        data_dir = run_dir / "data"
        if data_dir.exists():
            return data_dir
        return run_dir if run_dir.exists() else None
    # ─── 单个 candidate 分析 ───

    def analyze_candidate(self, cand_dir: Path, round_num: int, cand_id: int,
                          strategy: str = "", case_ids: Optional[list] = None,
                          write_proposal: bool = True) -> Optional[CandidateScore]:
        """分析单个 candidate 的所有 run，生成：
        1. 各 run 的 score_analysis.md + score.json（analyze_run 内部完成）
        2. 候选级 score_candidate_X_analysis.md（含数据来源、键值对、计算过程）
        3. 候选级 candidate_X_score.json（结构化摘要）
        4. 候选级 candidate_X_proposal.md（仅当 write_proposal=True）

        case_ids: 透传给 analyze_run,用于 per-case 表对齐用户指令的 CASE 白名单。
        write_proposal: 候选是否生成 proposal.md。默认 True 保持向后兼容；
                       agent 模式传 False 跳过 step 5（proposal 是 baseline 产物）。

        统一百分制:composite/normalized 内部计算(不再依赖 analyze_round 阶段补全)
        """
        run_dirs = sorted(cand_dir.glob("run_*"))
        if not run_dirs:
            return None

        runs = []
        for rd in run_dirs:
            run_idx = self._extract_run_index(rd.name)
            run_score = self.analyze_run(
                rd, round_num, cand_id, run_idx,
                case_ids=case_ids,
            )
            runs.append(run_score)

        # ── 资源消耗聚合(来自 runs[].raw.info.input_tokens/output_tokens/duration_ms)──
        # 跨 run 聚合:per-case + mean 口径(主推);total_* 保留 deprecated
        _ru = _aggregate_resource_usage(runs)
        cs = CandidateScore(
            round_num=round_num,
            candidate_id=cand_id,
            strategy=strategy,
            runs=runs,
            avg_result_score=self._avg([r.raw.result_score for r in runs]),
            # 新字段(主推,跟 result_score 一致)
            mean_input_tokens=_ru["mean_input_tokens"],
            mean_output_tokens=_ru["mean_output_tokens"],
            mean_duration_ms=_ru["mean_duration_ms"],
            mean_duration_seconds=_ru["mean_duration_seconds"],
            per_case_input_tokens=_ru["per_case_input_tokens"],
            per_case_output_tokens=_ru["per_case_output_tokens"],
            per_case_duration_ms=_ru["per_case_duration_ms"],
            valid_token_case_count=_ru["valid_token_case_count"],
            valid_duration_case_count=_ru["valid_duration_case_count"],
            # 旧字段(deprecated,保留作向后兼容;sum 口径)
            total_input_tokens=_ru["total_input_tokens"],
            total_output_tokens=_ru["total_output_tokens"],
            total_duration_ms=_ru["total_duration_ms"],
            stddev_input_tokens=_ru["stddev_input_tokens"],
            cv_input_tokens=_ru["cv_input_tokens"],
            stddev_output_tokens=_ru["stddev_output_tokens"],
            cv_output_tokens=_ru["cv_output_tokens"],
            stddev_duration_ms=_ru["stddev_duration_ms"],
            cv_duration_ms=_ru["cv_duration_ms"],
            # f1 跨 run 聚合(与 token/duration 同样模式;f1 不能 sum 只 mean)
            avg_f1=_ru["avg_f1"],
            stddev_f1=_ru["stddev_f1"],
            cv_f1=_ru["cv_f1"],
            per_run_f1=_ru["per_run_f1"],
        )

        # ── 跨 run 矩阵(与 analyze_round baseline 对齐:candidate 也应带 case_run_matrix)──
        # 之前只给 baseline_score 填 case_run_matrix,candidates 保持空 {},导致 round_N_score.json
        # 顶层 candidate 与 baseline 不对称(仅有 avg,无 per-case)。
        try:
            per_case_field = self._proposal_cfg.get("score_extraction", {}).get(
                "per_case_field", "result_score_per_case"
            )
        except Exception:
            per_case_field = "result_score_per_case"
        _m = build_case_run_matrix(runs, per_case_field=per_case_field)
        cs.case_run_matrix = _m["matrix"]
        cs.per_case_stddev = _m["per_case_stddev"]
        cs.per_case_cv = _m["per_case_cv"]

        # ── 归一化 + composite:同 analyze_round 保持一致,避免 candidate JSON 出现 composite=0
        only_f1 = self._is_only_f1_mode()
        if not only_f1:
            RoundNormalizer.normalize([cs], self.metrics_config)
        else:
            cs.composite = cs.avg_result_score or 0.0
            cs.normalized = {"result_score": cs.avg_result_score or 0.0}

        # ── 候选级产物：JSON 结构化摘要（机器可读）──
        # score_candidate_X_analysis.md 已删除（per-run score_analysis.md + 机器可读 JSON 已足够，
        # 避免 LLM 冗余生成与 candidate_1_score.json 重复的内容）
        self._write_candidate_score_json(cand_dir, round_num, cand_id, cs)
        # ProposalAgent 生成 candidate_X_proposal.md（仅 write_proposal=True）
        if write_proposal:
            proposal = self._generate_proposal_for_candidate(cand_dir, round_num, cand_id, cs)
            if proposal:
                self._write_candidate_proposal_md(cand_dir, round_num, cand_id, proposal)

        return cs

    def _write_candidate_score_json(self, cand_dir: Path, round_num: int,
                                    cand_id: int, cs: CandidateScore):
        """写 candidate_X_score.json 到候选目录。

        精度策略:统一百分制 0~100,所有分数 2 位小数。
        """
        data = {
            "round_num": round_num,
            "candidate_id": cand_id,
            "strategy": cs.strategy,
            "composite": self._round_pct(cs.composite),
            "avg_result_score": self._round_pct(cs.avg_result_score),
            "normalized": {k: self._round_pct(v) for k, v in cs.normalized.items()},
            "num_runs": len(cs.runs),
            # 资源消耗聚合（业务方自定义的数据结构：sum/mean/stddev/cv）
            "total_input_tokens": cs.total_input_tokens,
            "total_output_tokens": cs.total_output_tokens,
            "total_duration_ms": cs.total_duration_ms,
            "total_duration_seconds": round(cs.total_duration_ms / 1000, 2) if cs.total_duration_ms else 0.0,
            # avg_input/output/duration 已废弃,见 models.py 注释
            "stddev_input_tokens": cs.stddev_input_tokens,
            "cv_input_tokens": cs.cv_input_tokens,
            "stddev_output_tokens": cs.stddev_output_tokens,
            "cv_output_tokens": cs.cv_output_tokens,
            "stddev_duration_ms": cs.stddev_duration_ms,
            "cv_duration_ms": cs.cv_duration_ms,
            # f1 跨 run 聚合（与 token/duration 同样模式；f1 不能 sum 只 mean）
            "avg_f1": cs.avg_f1,
            "stddev_f1": cs.stddev_f1,
            "cv_f1": cs.cv_f1,
            "per_run_f1": cs.per_run_f1,
            "runs": [
                {
                    "run_index": r.raw.run_index,
                    "result_score": self._round_pct(r.raw.result_score),
                    "info": r.raw.info,
                }
                for r in cs.runs
            ],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        score_path = cand_dir / f"candidate_{cand_id}_score.json"
        score_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _generate_proposal_for_candidate(self, cand_dir: Path, round_num: int,
                                         cand_id: int, cs: CandidateScore) -> Optional[dict]:
        """为单个 candidate 调用 ProposalAgent 生成优化提案。"""
        if not cs.runs:
            return None

        # 定位最佳运行的 data 目录
        best_run = max(cs.runs, key=lambda r: r.raw.result_score or 0)
        data_dir = Path(best_run.analysis_path).parent / "data" if best_run.analysis_path else None
        if not data_dir or not data_dir.exists():
            data_dir = cand_dir / "data"
        if not data_dir.exists():
            data_dir = cand_dir

        run_info = best_run.raw.info or {}
        context = {
            "round_num": round_num,
            "candidate_id": cand_id,
            "strategy": cs.strategy,
            "run_index": best_run.raw.run_index,
            "result_score": best_run.raw.result_score,
            "info": run_info,
            "avg_result_score": cs.avg_result_score,
            "composite": cs.composite,
            "target_score": getattr(self.metrics_config, 'target_score', 100),
        }

        # 扫描可能的 Skill 文件路径（供 prompt 注入给子 Agent）
        skill_hints = self._find_skill_paths(data_dir, cand_dir)

        # 提取所有 Skill 文件的相对路径集合（用于 coverage 校验）
        all_skill_files_rel = set()
        for sp in skill_hints:
            for marker in ("/skill/", "/skills/"):
                idx = sp.find(marker)
                if idx >= 0:
                    all_skill_files_rel.add(sp[idx + len(marker):])
                    break
            else:
                all_skill_files_rel.add(sp)

        # 单 candidate 模式的精简 prompt 也由 YAML 注入(candidate_mode_intro + candidate_output_format)。
        prompt = self._render_proposal_prompt_candidate(
            cfg=self._proposal_cfg,
            context=context,
            data_dir=data_dir,
            skill_files_rel=sorted(all_skill_files_rel),
            cand_dir=cand_dir,
            round_num=round_num,
            cand_id=cand_id,
        )

        from tools import Agent
        Agent(
            mode="auto",
            description=f"为 candidate_{cand_id} (round {round_num}) 生成优化提案",
            subagent_type="ProposalAgent",
            prompt=prompt,
        )

        # ProposalAgent 是执行型 agent：直接 Edit 文件并落盘 optimization_summary.md，
        # 不返回结构化 {problems, modifications, coverage}（历史 one-shot JSON 解析必然失败，
        # 导致"未生成有效提案"误报 + 候选提案文档缺失）。改为探测其产物文件，
        # 存在即视为提案成功，summary 取文件头部供候选提案文档展示。
        summary_path = cand_dir / "optimization_summary.md"
        if summary_path.exists():
            summary = summary_path.read_text(encoding="utf-8", errors="ignore")[:200]
            print(f"  [ProposalAgent] Candidate {cand_id} 已生成优化总结: {summary_path.name}")
            return {"summary": summary, "problems": [], "modifications": [], "coverage": []}
        print(f"  [ProposalAgent] Candidate {cand_id} 未生成 optimization_summary.md，跳过候选提案")
        return None

    def _write_candidate_proposal_md(self, cand_dir: Path, round_num: int,
                                     cand_id: int, proposal: dict):
        """写 candidate_{cand_id}/proposal.md 到候选目录（与 eval_pipeline apply 定位一致）。"""
        if not proposal:
            return

        lines = [
            f"# Candidate {cand_id} 优化提案 (Round {round_num})",
            "",
            f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- **候选 ID**: {cand_id}",
            "- **来源**: ProposalAgent（子 Agent 驱动）",
            "",
            "## 概述",
            "",
            proposal.get("summary", "无概述"),
            "",
        ]

        problems = proposal.get("problems", [])
        if problems:
            lines.append(f"## 发现的问题（{len(problems)} 个）")
            lines.append("")
            lines.append("| CASE | 分数 | 根因 | 证据 |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for p in problems:
                score = p.get("score", "N/A")
                if isinstance(score, float):
                    # 统一百分制 0~100,2 位小数
                    score = f"{score:.2f}"
                case_id = p.get("case_id", "—")
                cause = p.get("root_cause") or "—"
                evidence = p.get("evidence") or "—"
                if cause and len(cause) > 80:
                    # 不截断 cause（之前 77 字符截断让用户看不到完整根因）
                    cause = cause
                if evidence and len(evidence) > 80:
                    # 不截断 evidence（之前 77 字符截断让用户看不到完整证据）
                    evidence = evidence
                lines.append(f"| {case_id} | {score} | {cause} | {evidence} |")
            lines.append("")

        # 文件覆盖清单（coverage）—— 必填项，覆盖 Skill 文件 + 所有已完成的轮次产物
        # 跨轮次扫描：baseline/ + round_1/ + ... + round_N/，让提案能吸收所有经验
        coverage = list(proposal.get("coverage", []))
        llm_files = {c.get("file", "") for c in coverage}
        all_dirs = self._collect_all_round_dirs(cand_dir)
        artifacts: List[Dict[str, str]] = []
        for d in all_dirs:
            rel_prefix = d.name if d.name != d.parent.name else "."
            for art in self._scan_layer_artifacts(d, scope="candidate"):
                file_path = art["file"]
                if rel_prefix != "." and not file_path.startswith(rel_prefix + "/"):
                    file_path = f"{rel_prefix}/{file_path}"
                art_copy = dict(art)
                art_copy["file"] = file_path
                if art_copy["file"] not in llm_files:
                    artifacts.append(art_copy)
                    llm_files.add(art_copy["file"])
        coverage.extend(artifacts)  # 把跨轮次扫描到的产物合并到 coverage 列表
        if coverage:
            n_skill = len(proposal.get('coverage', []))
            n_art = len(artifacts)
            layers = ", ".join(d.name for d in all_dirs)
            lines.append(f"## 文件覆盖清单（{len(coverage)} 个文件 = {n_skill} 个 Skill 文件 + {n_art} 个产物文件，扫描层：{layers}）")
            lines.append("")
            lines.append("> 提案覆盖被测 Skill 的全部文件 + **所有已完成轮次（baseline/ round_1/..round_N/）**下所有产物文件（score/log/data/_proposal），吸收全周期经验。")
            lines.append("")
            lines.append("| 文件 | 状态 | 说明 |")
            lines.append("| :--- | :--- | :--- |")
            for c in coverage:
                file_path = c.get("file", "—")
                status = c.get("status", "—")
                reason = c.get("reason", "—")
                # 不截断 reason（之前 100 字符截断让用户看不到完整上下文）
                lines.append(f"| {file_path} | {status} | {reason} |")
            lines.append("")

        modifications = proposal.get("modifications", [])
        if modifications:
            lines.append(f"## 修改建议（{len(modifications)} 处）")
            lines.append("")
            for i, m in enumerate(modifications, 1):
                action = m.get("action", "unknown").upper()
                mod_file = m.get("file", "—")  # 改名 mod_file，避免覆盖外层 file_name
                section = m.get("section", "—")
                reason = m.get("reason", "—")
                lines.append(f"### {i}. [{action}] {mod_file} → {section}")
                lines.append(f"**理由**: {reason}")
                lines.append("")
                current = m.get("current_content", "")
                if current:
                    lines.append("**当前内容**:")
                    lines.append("```markdown")
                    # current_content 不能截断——Edit 工具要求严格匹配,
                    # 截断会让 ApplyAgent 拿到的 current_content 与文件实际不一致,
                    # 导致 Edit 找不到匹配项或错位插入。
                    lines.append(current)
                    lines.append("```")
                    lines.append("")
                new_content = m.get("new_content", "")
                if new_content:
                    lines.append("**建议内容**:")
                    lines.append("```markdown")
                    # 写完整的 new_content,ApplyAgent 需要它做 Edit 精确替换。
                    lines.append(new_content)
                    lines.append("```")
                    lines.append("")

        proposal_path = cand_dir / "proposal.md"
        proposal_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  [ScoreAnalyzer] 已写 candidate_{cand_id}/proposal.md: "
              f"{len(proposal.get('modifications', []))} 处修改, "
              f"{len(proposal.get('coverage', []))} 个文件覆盖")

    # ─── 整轮分析 ───

    def analyze_round(self, round_dir: Path, round_num: int,
                      candidate_ids: Optional[List[int]] = None,
                      strategy_map: Optional[Dict[int, str]] = None,
                      case_ids: Optional[list] = None) -> RoundScore:
        """分析一轮的所有候选。

        case_ids: 透传给 analyze_candidate / analyze_run,用于 per-case 表对齐用户指令的 CASE 白名单。
        """
        strategy_map = strategy_map or {}
        only_f1 = self._is_only_f1_mode()

        # 自动发现 candidate 目录（未显式指定 candidate_ids 时）
        if not candidate_ids:
            candidate_ids = []
            for d in sorted(round_dir.iterdir()):
                if d.is_dir() and d.name.startswith("candidate_"):
                    try:
                        cid = int(d.name.split("_")[1])
                        candidate_ids.append(cid)
                    except (ValueError, IndexError):
                        pass

        # 1. 分析每个候选的所有 run（同时生成 per-candidate 文件）
        candidate_scores = []
        for cand_id in candidate_ids:
            cand_dir = round_dir / f"candidate_{cand_id}"
            if not cand_dir.exists():
                continue

            strategy = strategy_map.get(cand_id, "")
            cs = self.analyze_candidate(
                cand_dir, round_num, cand_id, strategy,
                case_ids=case_ids,
            )
            if cs is not None:
                candidate_scores.append(cs)

        # 2. 分析 baseline（如有）
        baseline_score = None
        baseline_dir = round_dir / "baseline"
        if baseline_dir.exists():
            bl_run_dirs = sorted(baseline_dir.glob("run_*"))
            if bl_run_dirs:
                bl_runs = []
                for rd in bl_run_dirs:
                    run_idx = self._extract_run_index(rd.name)
                    run_score = self.analyze_run(
                        rd, -1, -1, run_idx,
                        case_ids=case_ids,
                    )
                    bl_runs.append(run_score)
                baseline_score = CandidateScore(
                    round_num=-1,
                    candidate_id=-1,
                    strategy="baseline",
                    runs=bl_runs,
                    avg_result_score=self._avg([r.raw.result_score for r in bl_runs]),
                )

        # 3. 归一化 + composite
        all_for_norm = candidate_scores + ([baseline_score] if baseline_score else [])

        if not only_f1:
            RoundNormalizer.normalize(all_for_norm, self.metrics_config)
        else:
            for cs in all_for_norm:
                # 统一百分制:avg_result_score 已是 0~100,直接赋值
                cs.composite = cs.avg_result_score or 0.0
                cs.normalized = {"result_score": cs.avg_result_score or 0.0}

        # 4. 选最优
        best_id = None
        if candidate_scores:
            best = max(candidate_scores, key=lambda c: c.composite)
            best_id = best.candidate_id

        # 5. 构建 RoundScore
        round_score = RoundScore(
            round_num=round_num,
            baseline_score=baseline_score,
            candidates=candidate_scores,
            best_candidate_id=best_id,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # 6. 调用 ProposalAgent 生成优化提案（子 Agent 驱动）
        proposal = self._generate_proposal_via_agent(round_dir, round_score, candidate_ids)

        # 7. 从提案的 problems 提取 gaps 供下游使用
        gaps = proposal.get("problems", []) if proposal else []

        # 7.1 兜底:若 ProposalAgent 也未产出 problems,按 YAML gap_extractors 配置
        #     提取 gap,避免 proposal/apply 被「无缺口」短路掉导致整轮零修改。
        if not gaps:
            all_runs = []
            if round_score.baseline_score and round_score.baseline_score.runs:
                all_runs.extend(round_score.baseline_score.runs)
            for c in round_score.candidates:
                all_runs.extend(c.runs)
            # 兜底:LLM 未产出 problems 时,按 proposal-agent-config.yaml 的 gap_extractors 配置
            # 提取 gap。框架不感知具体业务字段名(zero_root_cause 等在 YAML 里)。
            fb = self._apply_gap_extractors(all_runs, self._proposal_cfg)
            if fb:
                print(f"  [GapFallback] ProposalAgent 未产出 problems,按 YAML 中 "
                      f"{len(self._proposal_cfg.get('gap_extractors', []))} 个 extractor "
                      f"从 {len(all_runs)} 个 run 提取 {len(fb)} 个 gap")
                gaps = fb

        # 7. 从提案的 problems 提取 gaps 供下游使用(优先用 GapAnalysis 结果)
        if not gaps and proposal:
            gaps = proposal.get("problems", [])

        # 8. 写聚合文件 ── 只写 proposal.md。
        # 轮次级 score.json / round_1_report.md / round_analysis.json 由 orchestrator 写入,这里不再重复写。
        # 历史曾在这里写 round_N_score.json / round_N_score_analysis.md / score_round_N_analysis.md,
        # 三个文件与 orchestrator 的同名文件内容重复,造成产物目录里出现 3 份"分数摘要"。
        # 8.4) 写 proposal.md
        if proposal:
            self._write_proposal_md(round_dir, round_num, proposal)

        return round_score

    def analyze_baseline(self, baseline_dir: Path, round_num: int,
                         case_ids: Optional[list] = None) -> RoundScore:
        """分析 baseline 的所有 run。

        case_ids: 透传给 analyze_run,用于 per-case 表对齐用户指令的 CASE 白名单。
        """
        run_dirs = sorted(baseline_dir.glob("run_*"))
        runs = []
        for rd in run_dirs:
            run_idx = self._extract_run_index(rd.name)
            run_score = self.analyze_run(
                rd, -1, -1, run_idx,
                case_ids=case_ids,
            )
            runs.append(run_score)

        only_f1 = self._is_only_f1_mode()

        # ── 资源消耗聚合(baseline 同样跨 run 汇总 time/tokens)──
        # per-case + mean 口径(主推);total_* 保留 deprecated
        _ru = _aggregate_resource_usage(runs)
        baseline_score = CandidateScore(
            round_num=-1,
            candidate_id=-1,
            strategy="baseline",
            runs=runs,
            avg_result_score=self._avg([r.raw.result_score for r in runs]),
            # 新字段(主推,跟 result_score 一致)
            mean_input_tokens=_ru["mean_input_tokens"],
            mean_output_tokens=_ru["mean_output_tokens"],
            mean_duration_ms=_ru["mean_duration_ms"],
            mean_duration_seconds=_ru["mean_duration_seconds"],
            per_case_input_tokens=_ru["per_case_input_tokens"],
            per_case_output_tokens=_ru["per_case_output_tokens"],
            per_case_duration_ms=_ru["per_case_duration_ms"],
            valid_token_case_count=_ru["valid_token_case_count"],
            valid_duration_case_count=_ru["valid_duration_case_count"],
            # 旧字段(deprecated,保留作向后兼容;sum 口径)
            total_input_tokens=_ru["total_input_tokens"],
            total_output_tokens=_ru["total_output_tokens"],
            total_duration_ms=_ru["total_duration_ms"],
            stddev_input_tokens=_ru["stddev_input_tokens"],
            cv_input_tokens=_ru["cv_input_tokens"],
            stddev_output_tokens=_ru["stddev_output_tokens"],
            cv_output_tokens=_ru["cv_output_tokens"],
            stddev_duration_ms=_ru["stddev_duration_ms"],
            cv_duration_ms=_ru["cv_duration_ms"],
            # f1 跨 run 聚合(与 token/duration 同样模式;f1 不能 sum 只 mean)
            avg_f1=_ru["avg_f1"],
            stddev_f1=_ru["stddev_f1"],
            cv_f1=_ru["cv_f1"],
            per_run_f1=_ru["per_run_f1"],
        )

        # ── 跨 run 矩阵 + 稳定性指标（解决"6/6 CASE 跨 run 0↔非 0 波动未被识别"问题）──
        # 字段名 result_score_per_case 来自 user-config.yaml score_extraction 段（通用化）
        try:
            per_case_field = self._proposal_cfg.get("score_extraction", {}).get(
                "per_case_field", "result_score_per_case"
            )
        except Exception:
            per_case_field = "result_score_per_case"
        m = build_case_run_matrix(runs, per_case_field=per_case_field)
        baseline_score.case_run_matrix = m["matrix"]
        baseline_score.per_case_stddev = m["per_case_stddev"]
        baseline_score.per_case_cv = m["per_case_cv"]
        run_scores_for_cv = [r.raw.result_score for r in runs if r.raw.result_score is not None]
        if len(run_scores_for_cv) >= 2:
            import statistics as _stat
            try:
                baseline_score.stddev = float(_stat.stdev(run_scores_for_cv))
            except _stat.StatisticsError:
                baseline_score.stddev = 0.0
        if baseline_score.avg_result_score > 0:
            baseline_score.cv = baseline_score.stddev / baseline_score.avg_result_score

        if only_f1:
            baseline_score.composite = baseline_score.avg_result_score or 0.0
            baseline_score.normalized = {"result_score": baseline_score.avg_result_score or 0.0}

        round_score = RoundScore(
            round_num=round_num,
            baseline_score=baseline_score,
            candidates=[],
            best_candidate_id=None,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # ── 严格顺序：纯代码产物 → LLM 产物 ──
        # 1) score_baseline.json（纯代码：含完整聚合数据，baseline_md 已废弃见下）
        # 2) _proposal/stage_{1,2,3}.json + proposal.md（LLM 产物）
        # 注：删除了 score_baseline_analysis.md 生成 — score_baseline.json 已含完整数据（stddev/per_case/avg/composite/
        #     stddev_*/cv_*/per_run_f1 等），再写一份冗余 MD 没意义。
        # 如需 baseline 阶段的可读分析，看 score_baseline.json 即可（结构化、机器可读、含所有 13 个资源字段）。
        run_scores = [r.raw.result_score for r in runs if r.raw.result_score is not None]
        if len(run_scores) >= 2:
            mean = sum(run_scores) / len(run_scores)
            stddev = (sum((s - mean) ** 2 for s in run_scores) / len(run_scores)) ** 0.5
        else:
            stddev = 0.0

        # 1) JSON 结构化摘要（仅含 baseline_score + candidates，不含 gaps）
        self._write_baseline_score_json(baseline_dir, round_score)

        # 3) 提案生成 —— 已迁移到 run_optimize_agent(单次 LLM 一次完成 context + 提案 + Edit + summary)
        #    避免 ScoreAnalyzerAgent.analyze_baseline(3 次 LLM Stage 1+2+3) + run_optimize_agent(1 次 LLM) 重复
        #    总 LLM 调从 4 次降到 1 次,时间从 25-30 分钟降到 5-10 分钟
        #    _proposal/stage_{1,2,3}.json 与 proposal.md 不再生成;审计/回放看 optimization_summary.md + skill diff

        return round_score

    def _write_baseline_score_json(self, baseline_dir: Path, rs: RoundScore):
        """写 baseline/score_baseline.json（纯代码生成，不含 gaps）。

        gaps 由后续 _generate_proposal_via_agent 写到 _proposal/stage_*.json,
        并在 proposal.md 中体现。score_baseline.json 仅含聚合分数/cases 矩阵。

        Args:
            baseline_dir: baseline 目录
            rs: RoundScore 对象
        """
        data = {
            "round_num": "baseline",
            "timestamp": rs.timestamp,
            "best_candidate_id": rs.best_candidate_id,
            "baseline_score": self._candidate_to_dict(rs.baseline_score) if rs.baseline_score else None,
            "candidates": [self._candidate_to_dict(c) for c in rs.candidates],
        }
        # 统一写入 score_baseline.json（与 persistence.save_baseline_score 一致）
        score_path = baseline_dir / "score_baseline.json"
        score_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # 清理旧名（兼容旧 task 产物，不阻断）
        legacy_path = baseline_dir / "baseline_score.json"
        if legacy_path.exists():
            try:
                legacy_path.unlink()
            except OSError:
                pass
    def _candidate_to_dict(self, c: CandidateScore) -> dict:
        """将 CandidateScore 转为 dict,用于 JSON 写入。

        精度策略(写入前统一 round,内存保留全精度):
        - 统一百分制 0~100,所有分数 2 位小数
        """
        return {
            "candidate_id": c.candidate_id,
            "strategy": c.strategy,
            "avg_result_score": self._round_pct(c.avg_result_score),
            "normalized": {k: self._round_pct(v) for k, v in c.normalized.items()},
            "composite": self._round_pct(c.composite),
            "num_runs": len(c.runs),
            "stddev": self._round_pct(c.stddev),
            "cv": self._round_pct(c.cv),
            "case_run_matrix": {
                k: [self._round_pct(x) for x in v] for k, v in c.case_run_matrix.items()
            },
            "per_case_stddev": {k: self._round_pct(v) for k, v in c.per_case_stddev.items()},
            "per_case_cv": {k: self._round_pct(v) for k, v in c.per_case_cv.items()},
            # 资源消耗聚合(来自 runs[].raw.info.input_tokens/output_tokens/duration_ms)
            # baseline/candidate 两级 JSON 都输出,供外部脚本做计费/性能分析
            # per-case + mean 字段(主推,与 result_score 口径一致)
            "mean_input_tokens": c.mean_input_tokens,
            "mean_output_tokens": c.mean_output_tokens,
            "mean_duration_ms": c.mean_duration_ms,
            "mean_duration_seconds": c.mean_duration_seconds,
            "per_case_input_tokens": c.per_case_input_tokens,
            "per_case_output_tokens": c.per_case_output_tokens,
            "per_case_duration_ms": c.per_case_duration_ms,
            "valid_token_case_count": c.valid_token_case_count,
            "valid_duration_case_count": c.valid_duration_case_count,
            # 旧字段(deprecated,保留作向后兼容;sum 口径,会被 0 拉低)
            "total_input_tokens": c.total_input_tokens,
            "total_output_tokens": c.total_output_tokens,
            "total_duration_ms": c.total_duration_ms,
            # 资源稳定性(跨 run stddev/cv,与 score 的 stddev/cv 同公式;CV 基于 mean)
            "stddev_input_tokens": c.stddev_input_tokens,
            "cv_input_tokens": c.cv_input_tokens,
            "stddev_output_tokens": c.stddev_output_tokens,
            "cv_output_tokens": c.cv_output_tokens,
            "stddev_duration_ms": c.stddev_duration_ms,
            "cv_duration_ms": c.cv_duration_ms,
            "runs": [
                {
                    "run_index": r.raw.run_index,
                    "result_score": self._round_pct(r.raw.result_score),
                    # 每 run 的 per-case 明细,供 run×case 复盘直接读取
                    # 字段名兼容通用别名(result_score_per_case / per_case_scores /
                    # case_scores / f1_per_case),由 analyze_run 注入 raw.info
                    "result_score_per_case": {
                        k: self._round_pct(val)
                        for k, val in self._extract_per_case_from_run(r).items()
                    },
                    # 每 run 的资源消耗(从 raw.info 抽出)
                    # 加 mean + per-case dict(主推)
                    "input_tokens": (r.raw.info or {}).get("input_tokens", 0) if r.raw.info else 0,
                    "output_tokens": (r.raw.info or {}).get("output_tokens", 0) if r.raw.info else 0,
                    "duration_ms": (r.raw.info or {}).get("duration_ms", 0) if r.raw.info else 0,
                    "duration_seconds": (r.raw.info or {}).get("duration_seconds", 0.0) if r.raw.info else 0.0,
                    "avg_input_tokens": (r.raw.info or {}).get("avg_input_tokens", 0) if r.raw.info else 0,
                    "avg_output_tokens": (r.raw.info or {}).get("avg_output_tokens", 0) if r.raw.info else 0,
                    "avg_duration_ms": (r.raw.info or {}).get("avg_duration_ms", 0) if r.raw.info else 0,
                    "input_tokens_per_case": (r.raw.info or {}).get("input_tokens_per_case", {}) if r.raw.info else {},
                    "output_tokens_per_case": (r.raw.info or {}).get("output_tokens_per_case", {}) if r.raw.info else {},
                    "duration_ms_per_case": (r.raw.info or {}).get("duration_ms_per_case", {}) if r.raw.info else {},
                }
                for r in c.runs
            ],
        }


