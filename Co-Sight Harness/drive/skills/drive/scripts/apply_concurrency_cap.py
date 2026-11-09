"""apply_concurrency_cap.py — 按 max_concurrent 切分超量 wave。

从 stdin 读 wave-scheduling 输出的 envelope，按 `--max-concurrent` 切分
任一超过上限的 wave，stdout 输出切分后的 waves JSON 数组。

调用顺序：
    agents_to_tasks.py → /wave-scheduling → apply_concurrency_cap.py

用法:
    cat waves.json | python3 apply_concurrency_cap.py --max-concurrent 4
"""
from __future__ import annotations

import argparse
import json
import sys

from envelope import Envelope, REASON_INVALID_ARG, REASON_SCHEMA_INVALID


def cap(waves: list[list[str]], max_concurrent: int) -> list[list[str]]:
    if max_concurrent < 1:
        raise ValueError(f"max_concurrent 必须 ≥ 1，收到 {max_concurrent}")
    result: list[list[str]] = []
    for wave in waves:
        if len(wave) <= max_concurrent:
            result.append(list(wave))
            continue
        for i in range(0, len(wave), max_concurrent):
            result.append(list(wave[i : i + max_concurrent]))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按 max_concurrent 切分超量 wave")
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=16,
        help="单 wave 最大 agent 数（来自 workflow.yaml orchestration.max_concurrent_agents）",
    )
    args = parser.parse_args(argv)

    try:
        raw = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        env = Envelope.fail(REASON_INVALID_ARG, error=f"stdin JSON 解析失败: {exc}")
        print(env.to_json(), flush=True)
        return 1

    if not isinstance(raw, dict) or not raw.get("ok"):
        env = Envelope.fail(
            REASON_SCHEMA_INVALID,
            error="stdin envelope ok=false",
            upstream=raw if isinstance(raw, dict) else None,
        )
        print(env.to_json(), flush=True)
        return 1

    waves = raw.get("data", {}).get("waves")
    if not isinstance(waves, list):
        env = Envelope.fail(REASON_SCHEMA_INVALID, error="envelope.data.waves 必须是 list")
        print(env.to_json(), flush=True)
        return 1

    try:
        capped = cap(waves, args.max_concurrent)
    except ValueError as exc:
        env = Envelope.fail(REASON_INVALID_ARG, error=str(exc))
        print(env.to_json(), flush=True)
        return 1

    print(json.dumps(capped, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
