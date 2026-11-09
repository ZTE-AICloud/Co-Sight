#!/usr/bin/env python3
"""
子 Agent 端到端调试（通过 cosight -p）
=====================================
1. ExtractionAgent → 4 维度分数 + info 原始值
2. ScoreAnalyzer → MD + JSON 产物
3. ProposalAgent → proposal.md (含 problems)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from metrics.config import MetricsConfig
from scorer.score_analyzer import ScoreAnalyzerAgent

METRICS_CONFIG = MetricsConfig.from_yaml(
    str(Path(__file__).parent.parent / "framework_configs" / "eval-config.yaml")
)


def test_extraction_e2e():
    """测试 ExtractionAgent 端到端。"""
    print("=" * 60)
    print("1. ExtractionAgent 端到端")
    print("=" * 60)

    agent = ScoreAnalyzerAgent(metrics_config=METRICS_CONFIG)
    print(f"  extractor_agent: {METRICS_CONFIG.get_extractor_agent()}")

    test_dir = Path("/media/vdc/skillx-alpha/evolution_workspace/特性域变更分析/taskid_20260529_201303/baseline/run_1")
    if not test_dir.exists():
        print(f"  ✗ {test_dir} 不存在")
        return

    print(f"  开始分析 {test_dir}...")
    run_score = agent.analyze_run(test_dir, round_num=0, candidate_id=-1, run_index=1)

    print("\n  结果:")
    print(f"    result_score:       {run_score.raw.result_score}")
    info = run_score.raw.info or {}
    for k, v in info.items():
        val = str(v)[:80]
        print(f"    info.{k}: {val}")

    # 检查产物
    score_json = test_dir / "score.json"
    if score_json.exists():
        d = json.loads(score_json.read_text(encoding="utf-8"))
        print("\n  ✓ score.json:")
        for k in ['result_score']:
            print(f"    {k}: {d.get(k)}")

    score_md = test_dir / "score_analysis.md"
    if score_md.exists():
        lines = score_md.read_text(encoding="utf-8").splitlines()
        print(f"\n  ✓ score_analysis.md: {len(lines)} 行")
        for line in lines[:20]:
            print(f"    {line}")

    print()


def test_gap_e2e():
    """测试 GapAnalysisAgent 端到端。"""
    print("=" * 60)
    print("2. GapAnalysisAgent 端到端")
    print("=" * 60)

    agent = ScoreAnalyzerAgent(metrics_config=METRICS_CONFIG)

    round_dir = Path("/media/vdc/skillx-alpha/evolution_workspace/特性域变更分析/taskid_20260529_201303/round_1")
    if not round_dir.exists():
        print(f"  ✗ {round_dir} 不存在")
        return

    print("  开始分析 round 1...")
    round_score = agent.analyze_round(
        round_dir,
        round_num=1,
        candidate_ids=[1, 2, 3],
    )

    print("\n  结果:")
    print(f"    best_candidate_id: {round_score.best_candidate_id}")
    for c in round_score.candidates:
        print(f"    C{c.candidate_id}: composite={c.composite:.1f}, result={c.avg_result_score:.2f}")
    if round_score.baseline_score:
        bl = round_score.baseline_score
        print(f"    baseline: composite={bl.composite:.1f}")

    # 检查 proposal.md
    proposal_md = round_dir / "round_1_proposal.md"
    if proposal_md.exists():
        content = proposal_md.read_text(encoding="utf-8")
        print(f"\n  ✓ round_1_proposal.md: {len(content)} 字符")
        # 尝试提取 problems
        import re
        fence = re.search(r'```(?:json)?\s*\n(.*?)\n```', content, re.DOTALL)
        if fence:
            try:
                data = json.loads(fence.group(1))
                problems = data.get("problems", [])
                print(f"    problems: {len(problems)} 个")
                for p in problems[:5]:
                    print(f"    [{p.get('severity', '?')}] {p.get('type', '?')}: {p.get('message', '')[:60]}")
            except:
                pass
    else:
        print("\n  ⚠ round_1_proposal.md 不存在")

    # 检查 round 级 MD
    round_md = round_dir / "round_1_score_analysis.md"
    if round_md.exists():
        lines = round_md.read_text(encoding="utf-8").splitlines()
        print(f"\n  ✓ round_1_score_analysis.md: {len(lines)} 行")
        for line in lines[:20]:
            print(f"    {line}")

    print()


if __name__ == "__main__":
    test_extraction_e2e()
    test_gap_e2e()
    print("=" * 60)
    print("端到端调试完成")
    print("=" * 60)
