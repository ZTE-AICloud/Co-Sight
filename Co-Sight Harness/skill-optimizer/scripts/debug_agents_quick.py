#!/usr/bin/env python3
"""
子 Agent 快速验证（单个 ExtractionAgent 调用，不跑完整 round）
"""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from tools import Agent


def test_extraction_single():
    """单次调用 ExtractionAgent 验证 cosight -p 管道。"""
    print("=" * 60)
    print("ExtractionAgent 快速验证")
    print("=" * 60)

    data_dir = "/media/vdc/skillx-alpha/evolution_workspace/特性域变更分析/taskid_20260529_201303/baseline/run_1/data"

    prompt = (
        f"扫描 {data_dir} 目录，提取指标。"
        f"读取 phase3-eval 下的 JSON 文件获取 f1 分数。"
        f"输出纯 JSON（不要 markdown fence）："
        f'{{"result_score": 0~1, '
        f'"info": {{"result_score_raw": x, "result_score_source": "..."}}}}'
    )

    start = time.time()
    result = Agent(
        description="提取 baseline/run_1 指标",
        prompt=prompt,
        subagent_type="ExtractionAgent",
    )
    elapsed = time.time() - start
    print(f"  耗时: {elapsed:.1f}s")
    print(f"  返回长度: {len(result)} 字符")
    print(f"  返回内容:\n{result[:1000]}")

    # 清理 fence
    cleaned = result.strip()
    fence_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        data = json.loads(cleaned)
        print(f"\n  ✓ JSON 解析成功:")
        for k in ['result_score']:
            print(f"    {k}: {data.get(k)}")
        info = data.get('info', {})
        for k, v in info.items():
            print(f"    info.{k}: {str(v)[:60]}")
        return True
    except json.JSONDecodeError as e:
        print(f"\n  ✗ JSON 解析失败: {e}")
        return False


def test_gap_single():
    """单次调用 GapAnalysisAgent 验证 cosight -p 管道。"""
    print("\n" + "=" * 60)
    print("GapAnalysisAgent 快速验证")
    print("=" * 60)

    score_data = {
        "round_num": 1,
        "best_candidate_id": 2,
        "candidates": [
            {"candidate_id": 1, "composite": 24.6},
            {"candidate_id": 2, "composite": 47.3},
            {"candidate_id": 3, "composite": 18.1},
        ],
        "baseline": {"composite": 4.4},
    }

    prompt = (
        f"分析本轮评分数据，识别缺口。目标分数: 100\n"
        f"评分数据: {json.dumps(score_data, ensure_ascii=False, indent=2)}\n"
        f"输出纯 JSON 数组（不要 markdown fence）：\n"
        f'[{{"type": "score_gap", "severity": "critical", "message": "...", "affected_section": "...", "root_cause": "...", "fix_suggestion": "..."}}]'
    )

    start = time.time()
    result = Agent(
        description="分析 round 1 缺口",
        prompt=prompt,
        subagent_type="GapAnalysisAgent",
    )
    elapsed = time.time() - start
    print(f"  耗时: {elapsed:.1f}s")
    print(f"  返回长度: {len(result)} 字符")
    print(f"  返回内容:\n{result[:800]}")

    # 清理 fence
    cleaned = result.strip()
    fence_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', cleaned, re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        gaps = json.loads(cleaned)
        print(f"\n  ✓ JSON 解析成功, {len(gaps)} 个缺口:")
        for g in gaps[:3]:
            print(f"    [{g.get('severity', '?')}] {g.get('type', '?')}: {g.get('message', '')[:60]}")
        return True
    except json.JSONDecodeError as e:
        print(f"\n  ✗ JSON 解析失败: {e}")
        return False


if __name__ == "__main__":
    test_extraction_single()
    print("\n调试完成")
