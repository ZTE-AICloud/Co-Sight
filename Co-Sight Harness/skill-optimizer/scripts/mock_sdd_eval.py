#!/usr/bin/env python3
"""
Mock SDD 评测脚本
=================

模拟真实 SDD 评测的 4 阶段产物结构，供 skillx-alpha-agents 端到端跑通使用。

**设计目的**：让业务方无需调 LLM 即可验证：
1. orchestrator 的 4 阶段产物归档（baseline/candidate/run_1/data/）是否正常
2. ExtractionAgent 是否能解析出分数（result_score, parent_node_score）
3. ApplyAgent 是否能根据分数缺口修改 SKILL.md
4. 下一轮评测时 SKILL.md 的修改是否被正确读到

**使用方法**：
    python3 mock_sdd_eval.py \
        --req-id RAN-001,RAN-002 \
        --activity 需求分析 \
        --sub-activity 特性域变更分析 \
        --output-dir /path/to/sandbox/data \
        --round-num 1

**模拟的分数规律**：
- baseline 阶段（round=0）：固定给 0.30（模拟未优化 Skill）
- 候选阶段（round≥1）：随轮次线性提升 (round * 0.12 + 0.30)，模拟"Skill 越优化分数越高"
- 加 ±0.05 的随机扰动模拟评测噪声
- 不同 candidate 给 ±0.05 的策略差异

**产物结构**（与真实评测一致）：
    ${output_dir}/
    ├── phase1-build/sub-activity-sets/特性域变更分析/<CASE_ID>.json  (gold)
    ├── phase2-exec/<CASE_ID>_<ts>/trace.log
    ├── phase3-eval/<CASE_ID>/results/<CASE_ID>-需求分析-特性域变更分析-<ts>.json
    └── phase4-diagnosis/diagnosis_run_<ts>/
        ├── dashboard.md
        ├── findings.json
        └── REPORT-<CASE_ID>_特性域变更分析.md
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List


def parse_case_ids(req_id_str: str) -> List[str]:
    return [x.strip() for x in req_id_str.split(",") if x.strip()]


def write_gold(out_dir: Path, case_id: str, sub_activity: str) -> None:
    """写 phase1-build gold 标准（每个 CASE 一份）"""
    gold_dir = out_dir / "phase1-build" / "sub-activity-sets" / sub_activity
    gold_dir.mkdir(parents=True, exist_ok=True)
    gold = {
        "case_id": case_id,
        "sub_activity": sub_activity,
        "gold_features": ["特性1", "特性2", "特性3"],
        "gold_cases": [
            {"name": f"{case_id}-用例1", "feature": "特性1", "change_point": "变更点A"},
            {"name": f"{case_id}-用例2", "feature": "特性2", "change_point": "变更点B"},
        ],
        "gold_change_points": ["变更点A", "变更点B"],
    }
    (gold_dir / f"{case_id}.json").write_text(
        json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_trace(out_dir: Path, case_id: str) -> None:
    """写 phase2-exec 执行轨迹（每个 CASE 一份）"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    trace_dir = out_dir / "phase2-exec" / f"{case_id}_{ts}"
    trace_dir.mkdir(parents=True, exist_ok=True)
    log = [
        f"[{datetime.now().isoformat()}] [START] case={case_id}",
        f"[{datetime.now().isoformat()}] [TOOL] Read(SKILL.md)",
        f"[{datetime.now().isoformat()}] [TOOL] Write(特性域变更分析报告.md)",
        f"[{datetime.now().isoformat()}] [DONE] case={case_id}",
    ]
    (trace_dir / "trace.log").write_text("\n".join(log), encoding="utf-8")


def write_eval(out_dir: Path, case_id: str, sub_activity: str, score: float) -> None:
    """写 phase3-eval 评测结果（含 parent_node_score 和 children.f1）"""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    results_dir = out_dir / "phase3-eval" / case_id / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    # 模拟 3 个 children (特性用例 / 用例变更点 / 影响范围) 的 f1
    # 其中 1 个的 f1 等于 score, 另外 2 个由 score 派生
    base_f1 = score
    f1_a = max(0.0, min(100.0, base_f1 + random.uniform(-5, 5)))
    f1_b = max(0.0, min(100.0, base_f1 + random.uniform(-5, 5)))
    parent_score = (f1_a + f1_b + base_f1) / 3.0
    eval_data = {
        "req_id": case_id,
        "node": sub_activity,
        "timestamp": ts,
        "total_score": round(parent_score, 2),
        "parent_node_score": round(parent_score, 2),
        "children": [
            {
                "name": "特性用例",
                "rule_path": f"需求分析/{sub_activity}/特性用例",
                "weight": 0.4,
                "recall": {"numerator": 1, "denominator": 1, "score": round(f1_a, 2)},
                "precision": {"numerator": 1, "denominator": 1, "score": round(f1_a, 2)},
                "f1": round(f1_a, 2),
            },
            {
                "name": "用例变更点",
                "rule_path": f"需求分析/{sub_activity}/用例变更点",
                "weight": 0.4,
                "recall": {"numerator": 0.8, "denominator": 1, "score": round(f1_b, 2)},
                "precision": {"numerator": 0.8, "denominator": 1, "score": round(f1_b, 2)},
                "f1": round(f1_b, 2),
            },
            {
                "name": "影响范围",
                "rule_path": f"需求分析/{sub_activity}/影响范围",
                "weight": 0.2,
                "recall": {"numerator": 0.6, "denominator": 1, "score": round(base_f1, 2)},
                "precision": {"numerator": 0.6, "denominator": 1, "score": round(base_f1, 2)},
                "f1": round(base_f1, 2),
            },
        ],
    }
    fname = f"{case_id}-需求分析-{sub_activity}-{ts}.json"
    (results_dir / fname).write_text(
        json.dumps(eval_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def write_diagnosis(out_dir: Path, case_id: str, score: float) -> None:
    """写 phase4-diagnosis 诊断报告"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    diag_dir = out_dir / "phase4-diagnosis" / f"diagnosis_run_{ts}"
    diag_dir.mkdir(parents=True, exist_ok=True)
    findings = {
        "case_id": case_id,
        "score": round(score, 2),
        "rules_triggered": ["R008_instruction_missing_action"] if score < 50 else [],
        "root_causes": [
            "Skill 章节缺少明确的产出物格式说明",
            "执行步骤未指定工具调用约束",
        ] if score < 50 else [],
    }
    (diag_dir / "findings.json").write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = f"""# 诊断报告: {case_id}

## 基本信息
- Case: {case_id}
- Score: {score:.2f}
- 时间: {ts}

## 根因分析
- Skill 章节缺少明确的产出物格式说明
- 执行步骤未指定工具调用约束

## 修复建议
- 在 SKILL.md 中补充"结果输出"格式约束
- 为每一步指定具体工具和必填字段
"""
    (diag_dir / f"REPORT-{case_id}_特性域变更分析.md").write_text(report, encoding="utf-8")
    # 顺手写 dashboard.md
    (diag_dir / "dashboard.md").write_text(
        f"# Dashboard\n\n- Cases: 1\n- Avg Score: {score:.2f}\n", encoding="utf-8"
    )


def simulate_score(round_num: int, candidate_id: int, case_id: str) -> float:
    """
    模拟一轮评测的真实分数

    设计目标：每次评测有真实差异（不同轮/候选/case 都不一样），
    同时保持 mock 内部确定性（同 case_id + 同样的 round/candidate 必返回同分）。
    差异维度：
    - 基础分：case_id hash 决定（每 case 有自己的"难度"）
    - 轮次提升：每轮 +1.5（优化在累积）
    - 候选差异：candidate 1 vs candidate 2 给 ±2
    - 噪声：±1.5（hash 加 round）

    让框架能观察到：
    - 单 case 多次 run 分数稳定（hash 锁住 case_id 维度）
    - 不同候选产生不同分数（便于"选最优候选"）
    - 跨轮次分数有上升趋势（便于迭代验证）
    """
    import hashlib

    # case 难度：每 case 在 0~30 区间（基础分）
    h_case = hashlib.md5(case_id.encode()).hexdigest()
    case_bucket = int(h_case[:4], 16) % 31  # 0~30
    case_base = 20.0 + case_bucket * 0.8  # 20~44

    # 轮次提升：每轮 +1.5（圆 0 不加，圆 1 加 1.5，圆 2 加 3.0...）
    round_bonus = max(0, round_num) * 1.5

    # 候选差异：candidate 1 +2, candidate 2 +0（候选 1 略优）
    candidate_delta = 2.0 if candidate_id == 1 else 0.0

    # 小幅噪声：用 round+candidate 锁住的确定性扰动
    h_run = hashlib.md5(f"{case_id}|{round_num}|{candidate_id}".encode()).hexdigest()
    noise = (int(h_run[:4], 16) % 11 - 5) * 0.3  # -1.5 ~ +1.5

    score = case_base + round_bonus + candidate_delta + noise
    return max(0.0, min(100.0, score))


def detect_round_candidate_from_path(out_dir: Path) -> tuple[int, int]:
    """
    从产物输出路径自动解析 round_num 和 candidate_id。

    约定：
    - 路径含 /baseline/ → (0, 0)
    - 路径含 /round_N/candidate_K/ → (N, K)
    - 其他 → (0, 0)
    """
    import re
    parts = out_dir.as_posix()
    m = re.search(r"/round_(\d+)/candidate_(\d+)/", parts)
    if m:
        return int(m.group(1)), int(m.group(2))
    if "/baseline/" in parts or parts.endswith("/baseline"):
        return 0, 0
    return 0, 0


def main() -> int:
    p = argparse.ArgumentParser(description="Mock SDD eval")
    p.add_argument("--req-id", required=True, help="逗号分隔的 case_id 列表")
    p.add_argument("--activity", required=True, help="活动名（如 '需求分析'）")
    p.add_argument("--sub-activity", required=True, help="子活动名（如 '特性域变更分析'）")
    p.add_argument("--output-dir", default="./data",
                   help="产物输出根目录（默认 ./data，相对 cwd；orchestrator 调用时通常传 --pipeline-base-dir/data）")
    p.add_argument("--round-num", type=int, default=-1,
                   help="当前轮次（0=baseline），默认 -1 表示从 output-dir 路径自动解析")
    p.add_argument("--candidate-id", type=int, default=-1,
                   help="候选 ID（0=baseline），默认 -1 表示从 output-dir 路径自动解析")
    p.add_argument("--sleep", type=float, default=10.0,
                   help="每 case 模拟耗时（秒），默认 10s 让单次 eval 接近 1 分钟（快速回归用）")
    args = p.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    case_ids = parse_case_ids(args.req_id)

    # 优先用 CLI 参数；否则从路径自动解析
    if args.round_num < 0 or args.candidate_id < 0:
        auto_round, auto_cand = detect_round_candidate_from_path(out_dir)
        if args.round_num < 0:
            args.round_num = auto_round
        if args.candidate_id < 0:
            args.candidate_id = auto_cand

    print(f"[mock_sdd_eval] round={args.round_num} candidate={args.candidate_id} "
          f"cases={len(case_ids)} → {out_dir}", flush=True)

    for cid in case_ids:
        score = simulate_score(args.round_num, args.candidate_id, cid)
        write_gold(out_dir, cid, args.sub_activity)
        write_trace(out_dir, cid)
        write_eval(out_dir, cid, args.sub_activity, score)
        write_diagnosis(out_dir, cid, score)
        print(f"  ✓ {cid}: parent_node_score={score:.2f}", flush=True)
        if args.sleep > 0:
            # 加 ±30% 随机扰动，模拟不同 case 评测耗时差异
            actual_sleep = args.sleep * random.uniform(0.7, 1.3)
            time.sleep(actual_sleep)
    print("[mock_sdd_eval] done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
