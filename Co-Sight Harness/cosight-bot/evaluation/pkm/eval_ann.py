#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ANN（IVF-PQ）与 flat 的检索延迟/文档级召回对比。

用法（在 cosightbot-pkm 根目录）：
  COSIGHTBOT_HOME=/media/vdc/cosightbot-runtime/cosightbot-pkm/data \
  .venv/bin/python evaluation/eval_ann.py \
    --questions ../design/.../full51w-static-baseline/per_question.jsonl \
    --output-dir /tmp/eval-ann --ann-queries 30 --flat-queries 5
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

load_env()

from common import overview_resolver as resolver  # noqa: E402
from watch_dog.file_watcher.embedding_model import OnlineBGEEmbedding  # noqa: E402
from watch_dog.file_watcher.section_index import SectionIndex  # noqa: E402

DSID_RE = re.compile(r"dsid_([0-9a-f]{32})", re.IGNORECASE)


def load_questions(path: Path, limit: int, stride: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if stride > 1:
        rows = rows[::stride]
    return rows[:limit] if limit > 0 else rows


def doc_ids_for_dsid(node_index: dict[str, str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for local_id, rel_path in node_index.items():
        if "_chapters/" in rel_path:
            continue
        match = DSID_RE.search(rel_path)
        if match:
            out.setdefault(f"dsid_{match.group(1).lower()}", set()).add(local_id)
    return out


def ranked_docs(rows: list[dict[str, Any]]) -> list[str]:
    docs: list[str] = []
    seen: set[str] = set()
    for row in rows:
        doc = str(row.get("doc_key") or "")
        if doc and doc not in seen:
            seen.add(doc)
            docs.append(doc)
    return docs


def recall_at(docs: list[str], expected_ids: set[str], k: int) -> bool:
    return bool(set(docs[:k]) & expected_ids)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * pct)))], 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="ANN vs flat 检索对比")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ann-queries", type=int, default=30)
    parser.add_argument("--flat-queries", type=int, default=5)
    parser.add_argument("--stride", type=int, default=15)
    parser.add_argument("--top-k", type=int, default=200)
    parser.add_argument("--agent-id", default="main")
    args = parser.parse_args()

    questions = load_questions(args.questions, args.ann_queries, args.stride)
    routes = [
        r for r in resolver.collect_routes(args.agent_id, None)
        if r.get("kind") == "agent"
    ]
    if not routes:
        print("no agent route", file=sys.stderr)
        return 2
    route = routes[0]
    lan_dir = Path(route["lan_dir"])
    idx = SectionIndex(lan_dir)
    if not idx.ann_ready:
        print("ANN index not ready; run build/finalize first", file=sys.stderr)
        return 2
    flat = SectionIndex(lan_dir)
    flat.ann_ready = False

    node_index = resolver._load_node_index(lan_dir)
    dsid_ids = doc_ids_for_dsid(node_index)
    expected = [
        set().union(*[dsid_ids.get(str(d).lower(), set()) for d in q.get("expected_doc_ids", [])])
        for q in questions
    ]
    embedding = OnlineBGEEmbedding()
    vectors = embedding._get_text_embeddings([q["question"] for q in questions])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    variants = {20: [], 50: [], 100: []}
    flat_rows: list[dict[str, Any]] = []
    per_query: list[dict[str, Any]] = []
    for qi, (question, vec, exp_ids) in enumerate(zip(questions, vectors, expected)):
        row: dict[str, Any] = {
            "question_id": question.get("question_id"),
            "expected_count": len(exp_ids),
            "variants": {},
        }
        ann_docs_by_n: dict[int, list[str]] = {}
        for nprobes in variants:
            t0 = time.perf_counter()
            rows = idx.search_sections(
                vec, top_k=args.top_k, nprobes=nprobes, refine_factor=10
            )
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            docs = ranked_docs(rows)
            ann_docs_by_n[nprobes] = docs
            hit10 = recall_at(docs, exp_ids, 10) if exp_ids else None
            hit50 = recall_at(docs, exp_ids, 50) if exp_ids else None
            row["variants"][str(nprobes)] = {
                "latency_ms": elapsed,
                "doc_count": len(docs),
                "hit@10": hit10,
                "hit@50": hit50,
            }
            variants[nprobes].append({
                "latency_ms": elapsed,
                "hit10": hit10,
                "hit50": hit50,
            })
        if qi < args.flat_queries:
            t0 = time.perf_counter()
            rows = flat.search_sections(
                vec, top_k=args.top_k, bypass_index=True
            )
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            docs = ranked_docs(rows)
            flat_row = {
                "question_id": question.get("question_id"),
                "latency_ms": elapsed,
                "doc_count": len(docs),
                "hit@10": recall_at(docs, exp_ids, 10) if exp_ids else None,
                "hit@50": recall_at(docs, exp_ids, 50) if exp_ids else None,
                "overlap@10": {},
                "overlap@50": {},
            }
            for nprobes, ann_docs in ann_docs_by_n.items():
                flat_row["overlap@10"][str(nprobes)] = round(
                    len(set(docs[:10]) & set(ann_docs[:10])) / max(1, len(set(docs[:10]))), 4
                )
                flat_row["overlap@50"][str(nprobes)] = round(
                    len(set(docs[:50]) & set(ann_docs[:50])) / max(1, len(set(docs[:50]))), 4
                )
            flat_rows.append(flat_row)
            row["flat"] = flat_row
        per_query.append(row)

    def variant_summary(nprobes: int) -> dict[str, Any]:
        values = variants[nprobes]
        lat = [v["latency_ms"] for v in values]
        hits10 = [v["hit10"] for v in values if v["hit10"] is not None]
        hits50 = [v["hit50"] for v in values if v["hit50"] is not None]
        overlaps10 = [r["overlap@10"][str(nprobes)] for r in flat_rows if str(nprobes) in r["overlap@10"]]
        overlaps50 = [r["overlap@50"][str(nprobes)] for r in flat_rows if str(nprobes) in r["overlap@50"]]
        return {
            "queries": len(values),
            "latency_p50_ms": percentile(lat, 0.50),
            "latency_p95_ms": percentile(lat, 0.95),
            "expected_recall@10": round(sum(hits10) / len(hits10), 4) if hits10 else None,
            "expected_recall@50": round(sum(hits50) / len(hits50), 4) if hits50 else None,
            "flat_overlap@10": round(sum(overlaps10) / len(overlaps10), 4) if overlaps10 else None,
            "flat_overlap@50": round(sum(overlaps50) / len(overlaps50), 4) if overlaps50 else None,
        }

    flat_lat = [r["latency_ms"] for r in flat_rows]
    summary = {
        "questions": len(questions),
        "flat_queries": len(flat_rows),
        "top_k": args.top_k,
        "flat": {
            "latency_p50_ms": percentile(flat_lat, 0.50),
            "latency_p95_ms": percentile(flat_lat, 0.95),
            "expected_recall@10": (
                round(sum(r["hit@10"] for r in flat_rows if r["hit@10"] is not None)
                      / max(1, sum(1 for r in flat_rows if r["hit@10"] is not None)), 4)
            ),
            "expected_recall@50": (
                round(sum(r["hit@50"] for r in flat_rows if r["hit@50"] is not None)
                      / max(1, sum(1 for r in flat_rows if r["hit@50"] is not None)), 4)
            ),
        },
        "ann": {str(n): variant_summary(n) for n in variants},
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "per_query.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in per_query),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
