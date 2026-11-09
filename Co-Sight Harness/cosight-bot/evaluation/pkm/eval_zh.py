#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文标注集评测：Tier1 文档覆盖 + Tier1 事实点覆盖。

用法（在 cosightbot-pkm 根目录，COSIGHTBOT_HOME 指向中文库）：
  .venv/bin/python evaluation/eval_zh.py \
    --questions ../design/.../p3-4a-zh-20q.jsonl \
    --output-dir /tmp/eval-zh
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME = _ROOT / "runtime"
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))
sys.path.insert(0, str(_ROOT / "evaluation"))

from common.bootstrap import load_env  # noqa: E402

load_env()

from common import overview_resolver as resolver  # noqa: E402
from common.dynamic_overview.engine import DynamicOverviewEngine  # noqa: E402
import eval_dynamic as ev  # noqa: E402


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * pct)))], 2)


def main() -> int:
    ap = argparse.ArgumentParser(description="中文标注集评测")
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--agent-id", default="main")
    ap.add_argument("--context-window", type=int, default=256_000)
    args = ap.parse_args()

    questions = [
        json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    routes = [r for r in resolver.collect_routes(args.agent_id, None) if r.get("kind") == "agent"]
    if not routes:
        print("no agent route", file=sys.stderr)
        return 2
    route = routes[0]
    engine = DynamicOverviewEngine(routes, context_window=args.context_window)
    ctx = engine.contexts[0]
    global_to_rel = {
        ctx.global_id(local): rel for local, rel in ctx.local_rel.items()
    }
    pre_dir = Path(route["pre_dir"])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    responses_path = args.output_dir / "responses.jsonl"
    with responses_path.open("w", encoding="utf-8") as responses:
        for idx, item in enumerate(questions, 1):
            t0 = time.perf_counter()
            result = engine.run(engine.build_query_pack([item["question"]]))
            elapsed = time.perf_counter() - t0
            merged = result.get("merged_overview", "")
            parsed = ev.parse_overview(merged)
            tier1_ids = {nid for nid, meta in parsed.items() if meta["tier"] == "tier1"}
            tier2_ids = {nid for nid, meta in parsed.items() if meta["tier"] == "tier2"}
            tier1_rels = {global_to_rel.get(nid.lower(), "") for nid in tier1_ids}
            any_rels = tier1_rels | {global_to_rel.get(nid.lower(), "") for nid in tier2_ids}
            tier1_rels.discard("")
            any_rels.discard("")

            expected_docs = [str(x) for x in item.get("expected_docs") or []]
            doc_t1 = [doc for doc in expected_docs if any(doc in rel for rel in tier1_rels)]
            doc_any = [doc for doc in expected_docs if any(doc in rel for rel in any_rels)]

            fact_t1 = 0
            fact_any = 0
            facts = [str(x) for x in item.get("expected_facts") or []]
            t1_text = ""
            any_text = ""
            for rel in tier1_rels:
                p = pre_dir / rel
                if p.is_file():
                    t1_text += "\n" + p.read_text(encoding="utf-8", errors="replace")
            for rel in any_rels:
                p = pre_dir / rel
                if p.is_file():
                    any_text += "\n" + p.read_text(encoding="utf-8", errors="replace")
            for fact in facts:
                if fact and fact.lower() in t1_text.lower():
                    fact_t1 += 1
                if fact and fact.lower() in any_text.lower():
                    fact_any += 1

            stats = result.get("stats") or {}
            row = {
                "question_id": item.get("question_id"),
                "question": item["question"],
                "expected_docs": expected_docs,
                "tier1_docs": sorted(tier1_rels),
                "tier2_docs": sorted(any_rels - tier1_rels),
                "doc_hit_tier1": len(doc_t1) == len(expected_docs) and bool(expected_docs),
                "doc_hit_any": len(doc_any) == len(expected_docs) and bool(expected_docs),
                "facts_total": len(facts),
                "facts_tier1": fact_t1,
                "facts_any": fact_any,
                "fact_hit_tier1": bool(facts) and fact_t1 == len(facts),
                "fact_hit_any": bool(facts) and fact_any == len(facts),
                "degraded": bool(result.get("degraded")),
                "degraded_reason": result.get("degraded_reason"),
                "elapsed_seconds": round(elapsed, 2),
                "stats": stats,
            }
            rows.append(row)
            responses.write(json.dumps({
                "question_id": row["question_id"],
                "ready": result.get("ready"),
                "merged_overview": merged,
                "stats": stats,
                "degraded": result.get("degraded"),
                "diagnostics": result.get("diagnostics"),
            }, ensure_ascii=False) + "\n")
            print(json.dumps({
                "progress": f"{idx}/{len(questions)}",
                "doc_t1": row["doc_hit_tier1"],
                "fact_t1": f"{fact_t1}/{len(facts)}",
                "elapsed_s": row["elapsed_seconds"],
            }, ensure_ascii=False), flush=True)

    summary = {
        "questions": len(rows),
        "doc_tier1_hits": sum(1 for r in rows if r["doc_hit_tier1"]),
        "doc_any_hits": sum(1 for r in rows if r["doc_hit_any"]),
        "fact_tier1_hits": sum(1 for r in rows if r["fact_hit_tier1"]),
        "fact_any_hits": sum(1 for r in rows if r["fact_hit_any"]),
        "degraded": sum(1 for r in rows if r["degraded"]),
        "latency_p50_s": percentile([r["elapsed_seconds"] for r in rows], 0.50),
        "latency_p95_s": percentile([r["elapsed_seconds"] for r in rows], 0.95),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "per_question.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
