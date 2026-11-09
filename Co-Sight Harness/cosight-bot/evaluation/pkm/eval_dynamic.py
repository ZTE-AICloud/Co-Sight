#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态 overview 批量评测（500 题/12 题）。

默认只跑 hop0（四路探针 + rerank + Tier），不调用 A0，适合 500 题召回/延迟
基线；`--a0-sample N` 可额外对 N 道题跑完整 A0/Q1 二跳。

用法（在 cosightbot-pkm 根目录）：
  COSIGHTBOT_HOME=/media/vdc/cosightbot-runtime/cosightbot-pkm/data \
  .venv/bin/python evaluation/eval_dynamic.py \
    --questions ../design/.../full51w-static-baseline/per_question.jsonl \
    --output-dir /tmp/eval-dynamic-500 \
    --limit 500
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME = _ROOT / "runtime"
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from common.bootstrap import load_env  # noqa: E402

# 必须先加载 .env，再导入 embedding_model/动态引擎：它们的环境变量常量在
# 模块导入时读取，晚加载会得到空的 EMBEDDING_API_URL/RERANK_API_URL。
load_env()

from common import overview_resolver as resolver  # noqa: E402
from common.dynamic_overview.engine import DynamicOverviewEngine  # noqa: E402
from common.dynamic_overview.models import HopRecord  # noqa: E402

DSID_RE = re.compile(r"dsid_([0-9a-f]{32})", re.IGNORECASE)
NODE_RE = re.compile(r"\[([Ff][0-9A-Fa-f]*\d{3,})\]")
TIER1_RE = re.compile(r"\bTier[\s_-]*1\b", re.IGNORECASE)
TIER2_RE = re.compile(r"\bTier[\s_-]*2\b", re.IGNORECASE)


def load_questions(
    path: Path, limit: int, offset: int, stride: int = 1
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    rows = rows[offset:]
    if stride > 1:
        rows = rows[::stride]
    return rows[:limit] if limit > 0 else rows


def parse_overview(overview: str) -> dict[str, dict[str, Any]]:
    """返回 {global_node_id_lower: {rank,tier}}；Tier 标题切换层级。"""
    hits: dict[str, dict[str, Any]] = {}
    tier = "unknown"
    rank = 0
    for line in (overview or "").splitlines():
        if TIER1_RE.search(line):
            tier = "tier1"
        elif TIER2_RE.search(line):
            tier = "tier2"
        for raw in NODE_RE.findall(line):
            node_id = raw.lower()
            if node_id in hits:
                continue
            rank += 1
            hits[node_id] = {"rank": rank, "tier": tier}
    return hits


def build_expected_index(routes: list[dict]) -> tuple[dict[str, set[str]], int]:
    """dsid -> 该文档的全局节点 ID 集合（只收主文档，排除 _chapters alias）。"""
    global_index, _ = resolver._build_global_node_index(routes)
    by_dsid: dict[str, set[str]] = {}
    for global_id, entry in global_index.items():
        rel_path = str(entry.get("rel_path") or "")
        if "_chapters/" in rel_path:
            continue
        match = DSID_RE.search(rel_path)
        if match:
            by_dsid.setdefault(f"dsid_{match.group(1).lower()}", set()).add(global_id.lower())
    return by_dsid, len(global_index)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return round(ordered[index], 2)


def evaluate_one(
    question: dict[str, Any],
    merged: str,
    elapsed: float,
    *,
    dsid_index: dict[str, set[str]],
    stats: dict[str, Any] | None = None,
    degraded: bool = False,
) -> dict[str, Any]:
    expected = [
        str(x).lower() for x in question.get("expected_doc_ids", []) if str(x).strip()
    ]
    present = [dsid for dsid in expected if dsid in dsid_index]
    hits = parse_overview(merged)
    tier1_ids = {nid for nid, meta in hits.items() if meta["tier"] == "tier1"}
    tier2_ids = {nid for nid, meta in hits.items() if meta["tier"] == "tier2"}
    any_ids = set(tier1_ids) | set(tier2_ids)

    matched_tier1: list[str] = []
    matched_any: list[str] = []
    best_rank: int | None = None
    for dsid in present:
        ids = dsid_index[dsid]
        if ids & tier1_ids:
            matched_tier1.append(dsid)
        if ids & any_ids:
            matched_any.append(dsid)
        ranks = [hits[nid]["rank"] for nid in ids if nid in hits]
        if ranks:
            candidate = min(ranks)
            best_rank = candidate if best_rank is None else min(best_rank, candidate)

    expected_count = len(expected)
    present_count = len(present)
    return {
        "question_id": question.get("question_id"),
        "question_type": question.get("question_type"),
        "question": question.get("question", ""),
        "expected_doc_ids": expected,
        "expected_count": expected_count,
        "library_present_count": present_count,
        "matched_tier1": len(matched_tier1),
        "tier1_recall": (
            len(matched_tier1) / present_count if present_count else None
        ),
        "matched_any": len(matched_any),
        "tier1_or_tier2_recall": (
            len(matched_any) / present_count if present_count else None
        ),
        "best_rank": best_rank,
        "reciprocal_rank": (1.0 / best_rank) if best_rank else 0.0 if present_count else None,
        "tier1_count": len(tier1_ids),
        "tier2_count": len(tier2_ids),
        "elapsed_seconds": round(elapsed, 3),
        "degraded": bool(degraded),
        "stats": stats or {},
    }


def run_hop0(engine: DynamicOverviewEngine, question: dict[str, Any]) -> tuple[str, dict, dict, bool]:
    q = engine.build_query_pack([question["question"]])
    selected, docs, diag = engine._run_hop(q, 0)
    tier1, tier2, tier_diag = engine._apply_tiers(docs)
    stats = {
        "doc_count": engine.total_doc_count,
        "tier1": len(tier1),
        "tier2": len(tier2),
        "hops": 1,
        "terms": q.positive_terms(),
        "a0_tokens": 0,
        "rerank": diag.get("rerank", False),
        "elapsed_ms": round(diag.get("elapsed_ms", 0.0), 1),
    }
    rec = HopRecord(
        hop=0, questions=q.questions, terms=q.terms,
        docs=len(docs), new_docs=len(docs), candidates=len(selected),
        rerank=diag.get("rerank", False), elapsed_ms=diag.get("elapsed_ms", 0.0),
    )
    merged = engine._render(
        q, tier1, tier2, [rec],
        degraded=False, degraded_reason="", a0_meta={}, stats=stats,
    )
    diagnostics = {
        "hops": [{
            "hop": 0,
            "docs": len(docs),
            "raw_candidates": diag.get("raw_candidates"),
            "merged_candidates": diag.get("merged_candidates"),
            "selected_candidates": len(selected),
            "rerank": diag.get("rerank", False),
            "candidate_node_ids": sorted({c.doc_id for c in selected}),
            "new_candidate_node_ids": sorted({c.doc_id for c in selected}),
        }],
        "tier": tier_diag,
        "probe_counts": diag.get("probe_counts", {}),
        "probe_docs": diag.get("probe_docs", {}),
    }
    if diag.get("q0_rewrite") is not None:
        diagnostics["hops"][0]["q0_rewrite"] = diag["q0_rewrite"]
    return merged, stats, diagnostics, False


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    annotated = [r for r in rows if r["expected_count"] > 0]
    present = [r for r in annotated if r["library_present_count"] > 0]
    latencies = [r["elapsed_seconds"] for r in rows if r.get("elapsed_seconds")]
    matched_t1 = sum(r["matched_tier1"] for r in present)
    matched_any = sum(r["matched_any"] for r in present)
    present_refs = sum(r["library_present_count"] for r in present)
    top10 = sum(
        1 for r in present
        if r["best_rank"] is not None and r["best_rank"] <= 10
    )
    reciprocal = [r["reciprocal_rank"] for r in present if r["reciprocal_rank"] is not None]
    return {
        "questions_total": len(rows),
        "questions_with_expected": len(annotated),
        "questions_present": len(present),
        "availability": round(len(rows) / len(annotated), 4) if annotated else None,
        "expected_refs": sum(r["expected_count"] for r in annotated),
        "library_present_refs": present_refs,
        "tier1_matched_refs": matched_t1,
        "tier1_recall": round(matched_t1 / present_refs, 4) if present_refs else None,
        "tier1_or_tier2_matched_refs": matched_any,
        "tier1_or_tier2_recall": round(matched_any / present_refs, 4) if present_refs else None,
        "top10_question_recall": round(top10 / len(present), 4) if present else None,
        "mrr": round(sum(reciprocal) / len(reciprocal), 4) if reciprocal else None,
        "avg_tier1": round(statistics.mean([r["tier1_count"] for r in rows]), 2) if rows else None,
        "avg_tier2": round(statistics.mean([r["tier2_count"] for r in rows]), 2) if rows else None,
        "latency_p50_s": _percentile(latencies, 0.50),
        "latency_p95_s": _percentile(latencies, 0.95),
        "degraded_count": sum(1 for r in rows if r.get("degraded")),
        "rerank_true_count": sum(1 for r in rows if r.get("stats", {}).get("rerank")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="动态 overview 批量评测")
    parser.add_argument("--questions", type=Path, required=True, help="Phase2 per_question.jsonl")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0, help="0=全部")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--stride", type=int, default=1, help="按步长抽样，如 5=每 5 题取 1")
    parser.add_argument("--a0-sample", type=int, default=0, help="额外跑完整 A0/Q1 的题数（0=不跑）")
    parser.add_argument("--agent-id", default="main")
    parser.add_argument("--context-window", type=int, default=256_000)
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument("--debug", action="store_true", help="输出逐探针候选文档 ID")
    args = parser.parse_args()

    questions = load_questions(
        args.questions, args.limit, args.offset, args.stride
    )
    if not questions:
        print("no questions", file=sys.stderr)
        return 2
    routes = [r for r in resolver.collect_routes(args.agent_id, None) if r.get("kind") == "agent"]
    if not routes:
        print("no agent route; check COSIGHTBOT_HOME/material binding", file=sys.stderr)
        return 2
    dsid_index, node_index_entries = build_expected_index(routes)
    engine = DynamicOverviewEngine(
        routes, context_window=args.context_window, debug=args.debug
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    responses_path = args.output_dir / "responses.jsonl"
    per_question_path = args.output_dir / "per_question.jsonl"
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    with responses_path.open("w", encoding="utf-8") as responses, per_question_path.open(
        "w", encoding="utf-8"
    ) as per_q:
        for idx, question in enumerate(questions, 1):
            t0 = time.perf_counter()
            use_a0 = idx <= args.a0_sample
            try:
                if use_a0:
                    result = engine.run(engine.build_query_pack([question["question"]]))
                    merged = result.get("merged_overview", "")
                    stats = result.get("stats", {})
                    diag = result.get("diagnostics", {})
                    degraded = bool(result.get("degraded"))
                    ready = bool(result.get("ready"))
                else:
                    merged, stats, diag, degraded = run_hop0(engine, question)
                    ready = True
                elapsed = time.perf_counter() - t0
                row = evaluate_one(
                    question, merged, elapsed,
                    dsid_index=dsid_index, stats=stats, degraded=degraded,
                )
                row["ready"] = ready
                response = {
                    "question_id": question.get("question_id"),
                    "ready": ready,
                    "merged_overview": merged,
                    "elapsed_seconds": round(elapsed, 3),
                    "stats": stats,
                    "degraded": degraded,
                    "diagnostics": diag,
                }
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                row = evaluate_one(
                    question, "", elapsed, dsid_index=dsid_index,
                    stats={"error": f"{type(exc).__name__}: {exc}"},
                    degraded=True,
                )
                row["ready"] = False
                response = {
                    "question_id": question.get("question_id"),
                    "ready": False,
                    "error_code": "EVAL_EXCEPTION",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": round(elapsed, 3),
                    "merged_overview": "",
                }
            rows.append(row)
            responses.write(json.dumps(response, ensure_ascii=False) + "\n")
            per_q.write(json.dumps(row, ensure_ascii=False) + "\n")
            # 释放逐题文件行缓存，避免 500 题累积占用内存
            for ctx in engine.contexts:
                ctx._line_cache.clear()
            if args.progress_every and (idx % args.progress_every == 0 or idx == len(questions)):
                done = idx
                elapsed_total = time.perf_counter() - started
                eta = elapsed_total / done * (len(questions) - done)
                print(
                    json.dumps({
                        "progress": f"{done}/{len(questions)}",
                        "elapsed_s": round(elapsed_total, 1),
                        "eta_s": round(eta, 1),
                        "tier1_recall": round(
                            sum(r["matched_tier1"] for r in rows)
                            / max(1, sum(r["library_present_count"] for r in rows)), 4
                        ),
                    }, ensure_ascii=False),
                    flush=True,
                )
    summary = summarize(rows)
    summary.update({
        "questions_file": str(args.questions),
        "agent_id": args.agent_id,
        "node_index_entries": node_index_entries,
        "a0_sample": args.a0_sample,
        "total_elapsed_s": round(time.perf_counter() - started, 1),
    })
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
