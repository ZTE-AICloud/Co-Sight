#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态引擎集成单测：四路探针 + A0/Q1 + Tier + 渲染（外部服务打桩）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from common.dynamic_overview import engine as engine_module  # noqa: E402
from common.dynamic_overview.engine import DynamicOverviewEngine  # noqa: E402
from common.dynamic_overview.models import DocScore, QueryPack  # noqa: E402
from watch_dog.file_watcher.overview_builder import write_overview_md  # noqa: E402
from watch_dog.file_watcher.section_index import DIM, SectionIndex  # noqa: E402


class FakeEmbedding:
    def _get_text_embeddings(self, texts):
        return [[0.01] * DIM for _ in texts]


DOC_A = """# Retention policy

Retention policy is evaluated in the control plane.

## Decision

The control plane resolves precedence rules and produces an effective snapshot.

## Data plane

Data plane services enforce the effective snapshot.
"""

DOC_B = """# Rollback

Incident rollback and audit log.

## Steps

Rollback uses the last known snapshot.
"""


def fake_rerank(_query, documents):
    return [1.0 if "retention" in text.lower() else 0.0 for text in documents]


def fake_a0(q_orig, evidence, **kwargs):
    return (
        {
            "hit_quality": "PARTIAL_HIT",
            "intermediate_result_A": "retention policy is evaluated in control plane",
            "unresolved_knowledge_gaps": ["snapshot schema"],
            "next_queries_Q1": {
                "sub_questions": ["What is the effective snapshot schema?"],
                "key_terms": ["effective snapshot", "policy_revision_id"],
            },
        },
        "",
        1.0,
        100,
    )


def fake_a0_full_with_gaps(q_orig, evidence, **kwargs):
    return (
        {
            "hit_quality": "FULL_HIT",
            "intermediate_result_A": "retention policy is evaluated in control plane",
            "unresolved_knowledge_gaps": ["optional detail"],
            "next_queries_Q1": {
                "sub_questions": ["What is the effective snapshot schema?"],
                "key_terms": ["effective snapshot"],
            },
        },
        "",
        1.0,
        100,
    )


class DynamicEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pre = root / "pre"
        self.lan = root / "lan"
        self.pre.mkdir()
        self.lan.mkdir()
        (self.pre / "a.md").write_text(DOC_A, encoding="utf-8")
        (self.pre / "b.md").write_text(DOC_B, encoding="utf-8")
        write_overview_md(self.lan, self.pre)
        builder = SectionIndex(self.lan, embedding=FakeEmbedding(), enable_ann=False)
        builder.build_from_pre_dir(self.pre, full_build=True)
        builder.finalize()
        self.route = {
            "kind": "agent",
            "label": "agent:test",
            "lan_dir": str(self.lan),
            "pre_dir": str(self.pre),
            "overview_md": str(self.lan / "overview.md"),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dynamic_run_two_hops(self) -> None:
        q = DynamicOverviewEngine.build_query_pack(
            ["How is retention policy evaluated in the control plane?"]
        )
        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()), \
             patch.object(engine_module, "batch_rerank_scores", side_effect=fake_rerank), \
             patch.object(engine_module, "call_a0", side_effect=fake_a0):
            engine = DynamicOverviewEngine([self.route], context_window=100_000)
            result = engine.run(q)

        self.assertTrue(result["ready"])
        self.assertFalse(result["degraded"])
        self.assertEqual(result["stats"]["doc_count"], 2)
        self.assertEqual(result["stats"]["hops"], 2)
        self.assertGreaterEqual(result["stats"]["tier1"], 1)
        self.assertEqual(result["stats"]["candidate_pool"], 2)
        self.assertFalse(result["stats"]["tier1_truncated"])
        self.assertFalse(result["stats"]["tier2_truncated"])
        self.assertEqual(result["stats"]["omitted_candidates"], 0)
        self.assertIn("候选池", result["merged_overview"])
        self.assertIn("retention", result["merged_overview"].lower())
        self.assertRegex(result["merged_overview"], r"\[f[0-9a-f]{3,}001\]")
        # Body-FTS chunks must inherit the enclosing section header path.
        self.assertNotIn("`(root)`", result["merged_overview"])
        self.assertEqual(
            result["diagnostics"]["a0"]["quality"], "PARTIAL_HIT"
        )
        self.assertIn("第 2 跳", result["merged_overview"])

    def test_full_hit_with_gaps_can_skip_hop2(self) -> None:
        q = DynamicOverviewEngine.build_query_pack(
            ["How is retention policy evaluated in the control plane?"]
        )
        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()), \
             patch.object(engine_module, "batch_rerank_scores", side_effect=fake_rerank), \
             patch.object(engine_module, "call_a0", side_effect=fake_a0_full_with_gaps), \
             patch.object(engine_module, "HOP2_SKIP_FULL_HIT", True):
            engine = DynamicOverviewEngine([self.route], context_window=100_000)
            result = engine.run(q)

        self.assertEqual(result["stats"]["hops"], 1)
        self.assertNotIn("第 2 跳", result["merged_overview"])

    def test_q0_rewrite_enriches_hop0_query(self) -> None:
        q = DynamicOverviewEngine.build_query_pack(
            ["How is retention policy evaluated in the control plane?"]
        )

        def fake_rewrite(pack, timeout=30.0):
            return QueryPack(
                questions=[*pack.questions, "retention snapshot schema"],
                terms=[*pack.terms, "traffic escrow"],
                entities=pack.entities,
                constraints=pack.constraints,
                identifiers=pack.identifiers,
                exclude=pack.exclude,
            )

        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()), \
             patch.object(engine_module, "batch_rerank_scores", side_effect=fake_rerank), \
             patch.object(engine_module, "call_a0", side_effect=fake_a0), \
             patch.object(engine_module, "rewrite_query", side_effect=fake_rewrite), \
             patch.object(engine_module, "QUERY_REWRITE_ENABLED", True):
            engine = DynamicOverviewEngine([self.route], context_window=100_000)
            result = engine.run(q)

        meta = result["diagnostics"]["hops"][0]["q0_rewrite"]
        self.assertTrue(meta["applied"])
        self.assertEqual(meta["added_terms"], 1)
        self.assertEqual(meta["added_questions"], 1)

    def test_q0_rewrite_disabled_does_not_call_model(self) -> None:
        q = DynamicOverviewEngine.build_query_pack(
            ["How is retention policy evaluated in the control plane?"]
        )
        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()), \
             patch.object(engine_module, "batch_rerank_scores", side_effect=fake_rerank), \
             patch.object(engine_module, "call_a0", side_effect=fake_a0), \
             patch.object(engine_module, "rewrite_query", side_effect=AssertionError("must not call")), \
             patch.object(engine_module, "QUERY_REWRITE_ENABLED", False):
            engine = DynamicOverviewEngine([self.route], context_window=100_000)
            result = engine.run(q)

        self.assertFalse(result["diagnostics"]["hops"][0].get("q0_rewrite", {}).get("applied", False))

    def test_q0_slots_and_exclude(self) -> None:
        q = DynamicOverviewEngine.build_query_pack(
            ["ERR_401_02 登录失败"],
            entities=["SSO"],
            identifiers=["ERR_401_02"],
            exclude=["retention"],
        )
        self.assertIn("ERR_401_02", q.terms)
        self.assertIn("sso", [t.lower() for t in q.terms])
        self.assertNotIn("retention", [t.lower() for t in q.terms])
        self.assertGreaterEqual(len(q.questions), 1)

    def test_apply_tiers_caps_are_candidate_pool_not_relevance(self) -> None:
        docs = {
            f"d{i}": DocScore(
                route_index=0,
                doc_id=f"d{i}",
                local_doc_id=f"F{i:03d}",
                rel_path=f"d{i}.md",
                title=f"doc {i}",
                score=1.0 - i * 0.002,
            )
            for i in range(300)
        }
        tier1, tier2, diag = DynamicOverviewEngine._apply_tiers(docs)

        self.assertEqual(diag["filtered"], 300)
        self.assertEqual(len(tier1), 100)
        self.assertEqual(len(tier2), 150)


if __name__ == "__main__":
    unittest.main()
