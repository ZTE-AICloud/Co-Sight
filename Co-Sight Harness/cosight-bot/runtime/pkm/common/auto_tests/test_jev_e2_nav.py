#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JEV-E2（T4）单测：灰区穿透晋升、整节回读、M1 先验免问、徽标正则兼容与软降级。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from common.dynamic_overview import jev_nav as jev_nav_module  # noqa: E402
from common.dynamic_overview.engine import DynamicOverviewEngine  # noqa: E402
from common.dynamic_overview.jev_nav import (  # noqa: E402
    DOC_SECTION_CHAR_BUDGET,
    apply_e2_navigation,
    build_batches,
    compute_recall_gap_report,
    format_doc_badge,
    rerank_and_promote_tiers,
    select_priority_recommendations,
)
from common.dynamic_overview.models import Candidate, DocScore, QueryPack  # noqa: E402
from common.jev_client import JevUnavailable, append_anti_injection  # noqa: E402
from watch_dog.file_watcher.overview_builder import write_overview_md  # noqa: E402
from watch_dog.file_watcher.section_index import DIM, SectionIndex  # noqa: E402


class FakeEmbedding:
    def _get_text_embeddings(self, texts):
        return [[0.01] * DIM for _ in texts]


def engine_module_ref():
    from common.dynamic_overview import engine as engine_module

    return engine_module


def tier_regexes():
    """跨任务契约正则：T2 合入后权威提取逻辑迁至 authority_extractor，
    旧位置（overview_resolver）保留回退兼容。"""
    try:
        from common.authority_extractor import _TIER1_DOC_RE, _TIER2_DOC_RE
    except ImportError:  # 旧版本未迁移时回退
        from common.overview_resolver import _TIER1_DOC_RE, _TIER2_DOC_RE
    return _TIER1_DOC_RE, _TIER2_DOC_RE


DOC_SECTION = "\n".join([
    "# Ops Bridge Runbook",            # L1 章节标题
    "",                                 # L2
    "Early context paragraph for the ops bridge runbook.",  # L3
    "",                                 # L4
    "| col1 | col2 |",                  # L5 表格表头
    "| --- | --- |",                    # L6
    "| r1 | v1 |",                      # L7
    "| r2 | v2 |",                      # L8
    "",                                 # L9
] + [
    f"Filler operational line {no} for the ops runbook body."  # L10..L24
    for no in range(10, 25)
] + [
    "Mariner failover step one: verify cluster drain state.",   # L25
    "Mariner failover step two: flip traffic to standby.",      # L26
    "Mariner failover step three: confirm health probes.",      # L27
    "Mariner failover step four: roll back on failure.",        # L28
    "Mariner failover step five: record the bridge outcome.",   # L29
    "Mariner failover step six: close the incident bridge.",    # L30
] + [
    f"Tail operational line {no} for the ops runbook body."     # L31..L35
    for no in range(31, 36)
])

DOC_A = """# Retention policy

Retention policy is evaluated in the control plane.

## Decision

The control plane resolves precedence rules and produces an effective snapshot.
"""


def make_doc(i: int, score: float, text: str = "body text") -> DocScore:
    doc_id = f"f{i:03d}"
    candidate = Candidate(
        route_index=0, doc_id=doc_id, local_doc_id=f"F{i:03d}",
        rel_path=f"dir/doc{i}.md", section_id="s1",
        start_line=1, end_line=2, text=text,
    )
    return DocScore(
        route_index=0, doc_id=doc_id, local_doc_id=f"F{i:03d}",
        rel_path=f"dir/doc{i}.md", title=f"doc {i}",
        candidates=[candidate], score=score,
    )


def fake_answers_for(entries: list[dict], gold_ids: set[str]) -> dict:
    answers: dict = {}
    for entry in entries:
        idx = entry["idx"]
        is_gold = entry["doc_id"] in gold_ids
        answers[f"target_match_{idx}"] = {
            "noul": 0.992 if is_gold else 0.0005,
        }
        answers[f"constraint_fit_{idx}"] = {
            "score": (
                {"0": 0.01, "1": 0.04, "2": 0.95}
                if is_gold else {"0": 0.98, "1": 0.02, "2": 0.0}
            ),
        }
        answers[f"doc_role_{idx}"] = {
            "choice": "other",
            "probabilities": {
                "normative": 0.0, "factual_record": 0.0,
                "tentative": 0.0, "other": 1.0,
            },
        }
    return answers


def fake_jev_answer(answers: dict, batch_count: int) -> SimpleNamespace:
    return SimpleNamespace(
        answers=answers,
        audit={
            "stage": "E2", "question_set_version": "office-e2-nav-v1",
            "model": "fake-model", "endpoint": "http://fake",
            "latency_ms": 1.0, "batch_count": batch_count,
            "question_count": 0, "payload_chars": 0,
            "usage": {"input_tokens": 0, "output_tokens": 0, "cost": 0.0},
        },
        raw={"answers": answers},
    )


class JevE2NavLogicTest(unittest.TestCase):
    """纯逻辑用例：晋升重排、徽标格式、召回差测算（不触 JEV 与 LanceDB）。"""

    def test_01_tier_regex_compat_with_badge(self) -> None:
        doc = make_doc(42, score=0.612)
        doc.jev_target_match = 0.99
        doc.jev_constraint_fit = 1.94
        doc.jev_doc_type = "runbook_sop"
        doc.jev_promoted = True
        badge = format_doc_badge(doc)
        self.assertEqual(
            badge, "[实体吻合:高 | 限定:2档 | 权威角色:运维规程SOP | ↑灰区晋升]"
        )
        tier1_line = (
            f"│   ├── [{doc.doc_id}] {doc.title}  "
            f"(命中 {doc.hit_count} 处 | 综合分: {doc.score:.3f}) {badge}"
        )
        tier1_re, tier2_re = tier_regexes()
        match = tier1_re.match(tier1_line)
        self.assertIsNotNone(match)
        self.assertEqual(match.group("gid"), "f042")
        self.assertEqual(match.group("title"), doc.title)
        self.assertEqual(match.group("score"), "0.612")
        registry = make_doc(87, score=0.540)
        registry.jev_is_registry = True
        tier2_line = (
            f"- [{registry.doc_id}] {registry.title} (score={registry.score:.3f}"
            f"; 命中 L1-L2) {format_doc_badge(registry)}"
        )
        match2 = tier2_re.match(tier2_line)
        self.assertIsNotNone(match2)
        self.assertEqual(match2.group("gid"), "f087")
        self.assertEqual(match2.group("title"), "doc 87")
        self.assertEqual(match2.group("score"), "0.540")

    def test_02_badge_format_frozen_mapping(self) -> None:
        policy = make_doc(1, score=0.5)
        policy.jev_doc_type = "policy_norm"
        policy.jev_is_registry = True
        self.assertEqual(format_doc_badge(policy), "[权威角色:正式制度规范/汇总登记表]")
        online_norm = make_doc(2, score=0.5)
        online_norm.jev_doc_role = "normative"
        self.assertEqual(format_doc_badge(online_norm), "[权威角色:正式规范]")
        tentative = make_doc(3, score=0.5)
        tentative.jev_doc_role = "tentative"
        self.assertEqual(format_doc_badge(tentative), "[权威角色:草案/示例]")
        mid = make_doc(4, score=0.5)
        mid.jev_target_match = 0.5
        self.assertEqual(format_doc_badge(mid), "[实体吻合:中]")
        empty = make_doc(5, score=0.5)
        self.assertEqual(format_doc_badge(empty), "")

    def test_03_grey_zone_promotion_zero_deletion(self) -> None:
        docs = {f"f{i:03d}": make_doc(i, score=1.0 - i * 0.003) for i in range(150)}
        ordered = sorted(docs.values(), key=lambda d: d.score, reverse=True)
        tier1 = ordered[:50]
        tier2 = ordered[50:100]
        q = QueryPack(questions=["Mariner failover steps"])

        def fake_ask(batches, **kwargs):
            answers = {}
            for state, _questions in batches:
                answers.update(fake_answers_for(state["candidates"], {"f128"}))
            return fake_jev_answer(answers, len(batches))

        with patch.object(jev_nav_module, "is_stage_enabled", return_value=True), \
             patch.object(jev_nav_module, "ask_batches_concurrent", side_effect=fake_ask):
            new_tier1, new_tier2, recommendations, diag = apply_e2_navigation(
                q, docs, tier1, tier2, contexts=[]
            )

        promoted = [d for d in new_tier1 if d.doc_id == "f128"]
        self.assertEqual(len(promoted), 1)
        self.assertTrue(promoted[0].jev_promoted)
        self.assertIn("f128", diag["promoted"])
        self.assertEqual(len(new_tier1), 51)
        self.assertEqual(len(new_tier2), 50)
        self.assertNotIn("f128", {d.doc_id for d in new_tier2})
        # 零物理删除：总池 150 篇一字不删，tier1+tier2 之外仍有 49 篇留在池中。
        in_tiers = {d.doc_id for d in new_tier1} | {d.doc_id for d in new_tier2}
        self.assertEqual(len(in_tiers), 101)
        self.assertEqual(len(docs), 150)
        self.assertEqual(len(docs.keys() - in_tiers), 49)
        rec_ids = [d.doc_id for d in recommendations]
        self.assertIn("f128", rec_ids)

    def test_04_none_probability_never_demoted(self) -> None:
        docs = {f"f{i:03d}": make_doc(i, score=1.0 - i * 0.003) for i in range(150)}
        ordered = sorted(docs.values(), key=lambda d: d.score, reverse=True)
        tier1 = ordered[:100]
        tier2 = ordered[100:150]
        # 原 Tier 1 末尾：倒数第 1 篇 target_match 缺失（None），倒数第 2 篇极低分。
        tier1[-1].jev_target_match = None
        tier1[-2].jev_target_match = 0.001
        tier1[-2].jev_constraint_fit = 0.0
        # 灰区 2 篇高吻合遗珠 → 晋升后 tier1 超限触发尾部顺移。
        for grey_i in (120, 121):
            docs[f"f{grey_i:03d}"].jev_target_match = 0.99
            docs[f"f{grey_i:03d}"].jev_constraint_fit = 2.0
        filtered = ordered

        new_tier1, new_tier2, promoted, demoted = rerank_and_promote_tiers(
            filtered, tier1, tier2, scan_limit=150
        )

        self.assertEqual(promoted, ["f120", "f121"])
        self.assertIn("f099", [d.doc_id for d in new_tier1])  # None 绝不被顺移
        self.assertIn("f098", [d.doc_id for d in new_tier2])  # 极低分被顺移
        self.assertEqual(set(demoted), {"f098"})
        self.assertEqual(len(docs), 150)

    def test_05_recommendations_gate_and_order(self) -> None:
        tier1 = [make_doc(i, score=1.0 - i * 0.01) for i in range(5)]
        tier1[0].jev_target_match = 0.99
        tier1[0].jev_constraint_fit = 2.0
        tier1[1].jev_target_match = 0.99
        tier1[1].jev_constraint_fit = 1.1  # J = 0.5445 + 0.1925 = 0.737 ≥ 0.72
        tier1[2].jev_target_match = 0.30   # 低于 0.90 门槛
        tier1[3].jev_target_match = 0.99
        tier1[3].jev_doc_role = "normative"  # 权威角色兜底入选
        tier1[4].jev_target_match = None
        for doc in tier1:
            doc.jev_score = None
        recs = select_priority_recommendations(tier1)
        ids = [d.doc_id for d in recs]
        self.assertIn("f000", ids)
        self.assertIn("f001", ids)
        self.assertIn("f003", ids)
        self.assertNotIn("f002", ids)
        self.assertNotIn("f004", ids)
        self.assertLessEqual(len(recs), 12)

    def test_06_compute_recall_gap_report(self) -> None:
        ranked = [f"d{i:03d}" for i in range(299)] + ["gold"]
        report = compute_recall_gap_report(ranked, ["gold"])
        self.assertEqual(report["recall@100"], 0.0)
        self.assertEqual(report["recall@300"], 1.0)
        self.assertEqual(report["delta_pp"], 100.0)
        self.assertEqual(report["recommend_scan_limit"], 300)
        partial = compute_recall_gap_report(ranked, ["d050", "gold"])
        self.assertEqual(partial["recall@100"], 0.5)
        self.assertEqual(partial["recall@300"], 1.0)
        self.assertEqual(partial["delta_pp"], 50.0)

    def test_07_build_batches_char_budget_and_cap(self) -> None:
        q = QueryPack(questions=["q1"])
        entries = [
            {
                "idx": i, "doc_id": f"f{i:03d}", "path": f"d{i}.md",
                "title": f"doc {i}", "doc_type_prior": "unknown",
                "is_registry_prior": False,
                "best_sections_text": "x" * 1500,
            }
            for i in range(45)
        ]
        batches = build_batches(q, entries, {})
        self.assertGreaterEqual(len(batches), 3)
        covered: list[str] = []
        for state, questions in batches:
            self.assertLessEqual(len(state["candidates"]), 20)
            payload_body = json.dumps(
                {
                    "model": "Ntele-decision-V1",
                    "state": state,
                    "questions": append_anti_injection(questions),
                },
                ensure_ascii=False,
            )
            self.assertLessEqual(len(payload_body), 50_000)
            for pos, entry in enumerate(state["candidates"]):
                covered.append(entry["doc_id"])
                # 每篇候选都带 target_match + constraint_fit（无先验时再加 doc_role），
                # 且 instructions 必须引用本批局部数组下标 candidates[{pos}]（防第 2+ 批越界），
                # score 的 criteria 必须是 list[str]（防内网 SystemOne HTTP 422）。
                tq = questions[f"target_match_{entry['idx']}"]
                fq = questions[f"constraint_fit_{entry['idx']}"]
                rq = questions[f"doc_role_{entry['idx']}"]
                self.assertIn(f"candidates[{pos}]", tq["instructions"])
                self.assertIn(f"candidates[{pos}]", fq["instructions"])
                self.assertIn(f"candidates[{pos}]", rq["instructions"])
                self.assertIsInstance(fq["criteria"], list)
                self.assertEqual(len(fq["criteria"]), 3)
        self.assertEqual(len(covered), 45)
        self.assertEqual(len(set(covered)), 45)
        # 显式调大单批篇数时，多篇同批局部下标 candidates[0..N-1] 与 50K 字符上限仍严格成立。
        with patch.dict("os.environ", {"COSIGHTBOT_JEV_E2_BATCH_DOCS": "15"}):
            multi_batches = build_batches(q, entries, {})
        self.assertGreaterEqual(len(multi_batches), 3)
        self.assertGreater(len(multi_batches[0][0]["candidates"]), 1)
        for pos, entry in enumerate(multi_batches[0][0]["candidates"]):
            self.assertIn(f"candidates[{pos}]", multi_batches[0][1][f"target_match_{entry['idx']}"]["instructions"])

    def test_07b_real_systemone_score_probabilities_parsing(self) -> None:
        # 真实内网 Ntele-decision-V1 对 score 返回 {"type":"score","score":1.99,"probabilities":{"0":...,"1":...,"2":...}}
        doc = make_doc(1, score=0.5)
        jev_nav_module._apply_answers(
            {0: doc},
            {0: (False, "unknown")},
            {
                "target_match_0": {"type": "noul", "noul": 0.996},
                "constraint_fit_0": {
                    "type": "score",
                    "score": 1.99,
                    "probabilities": {"0": 0.002, "1": 0.004, "2": 0.994},
                },
                "doc_role_0": {
                    "type": "choice",
                    "choice": "normative",
                    "probabilities": {"normative": 0.99, "factual_record": 0.005, "tentative": 0.002, "other": 0.003},
                },
            },
        )
        self.assertAlmostEqual(doc.jev_target_match, 0.996)
        self.assertGreater(doc.jev_constraint_fit, 1.98)
        self.assertEqual(doc.jev_doc_role, "normative")


class JevE2EngineTest(unittest.TestCase):
    """依赖真实 SectionIndex/RouteContext 的集成用例（外部服务打桩）。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pre = root / "pre"
        self.lan = root / "lan"
        self.pre.mkdir()
        self.lan.mkdir()
        (self.pre / "a.md").write_text(DOC_SECTION, encoding="utf-8")
        (self.pre / "b.md").write_text(DOC_A, encoding="utf-8")
        write_overview_md(self.lan, self.pre)
        self.builder = SectionIndex(self.lan, embedding=FakeEmbedding(), enable_ann=False)
        self.builder.build_from_pre_dir(self.pre, full_build=True)
        self.builder.finalize()
        self.route = {
            "kind": "agent",
            "label": "agent:test",
            "lan_dir": str(self.lan),
            "pre_dir": str(self.pre),
            "overview_md": str(self.lan / "overview.md"),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _build_engine(self) -> DynamicOverviewEngine:
        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()):
            return DynamicOverviewEngine([self.route], context_window=100_000)

    def test_08_full_section_readback_not_snippet(self) -> None:
        engine = self._build_engine()
        ctx = engine.contexts[0]
        section_rows = (
            ctx.index.section_table.to_lance().to_table().to_pylist()
        )
        target = next(
            row for row in section_rows
            if int(row["start_line"]) <= 25 and int(row["end_line"]) >= 30
        )
        doc = DocScore(
            route_index=0, doc_id="f001", local_doc_id=str(target["doc_key"]),
            rel_path="a.md", title="a",
            candidates=[Candidate(
                route_index=0, doc_id="f001", local_doc_id=str(target["doc_key"]),
                rel_path="a.md", section_id=str(target["section_id"]),
                start_line=25, end_line=30, text="",
            )],
            score=0.5,
        )
        text = jev_nav_module._extract_full_hit_sections(doc, ctx)
        self.assertTrue(text)
        self.assertLessEqual(len(text), DOC_SECTION_CHAR_BUDGET)
        # 整节回读：包含第 1 行章节标题、表格表头与前置主语，而非只有命中行。
        self.assertIn("# Ops Bridge Runbook", text)
        self.assertIn("| col1 | col2 |", text)
        self.assertIn("Early context paragraph", text)
        self.assertIn("Mariner failover step one", text)
        self.assertIn("Mariner failover step six", text)

    def test_09_m1_prior_skips_online_doc_role(self) -> None:
        self.builder.upsert_document(
            self.pre / "a.md", "a.md",
            role_info={
                "jev_doc_type": "runbook_sop",
                "jev_doc_type_conf": 0.98,
                "jev_is_registry": False,
            },
        )
        self.builder.finalize()
        engine = self._build_engine()
        ctx = engine.contexts[0]
        doc_rows = ctx.index.doc_table.to_lance().to_table(
            columns=["doc_key", "rel_path", "jev_doc_type", "jev_doc_type_conf"]
        ).to_pylist()
        target = next(row for row in doc_rows if row["rel_path"] == "a.md")
        self.assertEqual(target["jev_doc_type"], "runbook_sop")
        doc = DocScore(
            route_index=0, doc_id="f001", local_doc_id=str(target["doc_key"]),
            rel_path="a.md", title="a",
            candidates=[Candidate(
                route_index=0, doc_id="f001", local_doc_id=str(target["doc_key"]),
                rel_path="a.md", section_id="s1", start_line=1, end_line=2,
                text="Mariner failover runbook body.",
            )],
            score=0.5,
        )
        q = QueryPack(questions=["Mariner failover steps"])

        # 场景 A：E2 开关关闭 → 仅本地挂载 M1 先验并渲染权威角色徽标，零 JEV 调用。
        with patch.object(jev_nav_module, "is_stage_enabled", return_value=False), \
             patch.object(
                 jev_nav_module, "ask_batches_concurrent",
                 side_effect=AssertionError("must not call JEV when stage disabled"),
             ):
            t1, t2, recs, diag = apply_e2_navigation(q, {"f001": doc}, [doc], [], contexts=[ctx])
        self.assertTrue(diag.get("skipped"))
        self.assertEqual(doc.jev_doc_type, "runbook_sop")
        self.assertEqual(format_doc_badge(doc), "[权威角色:运维规程SOP]")
        self.assertIn("权威角色:运维规程SOP", doc.jev_badge)

        # 场景 B：E2 开启 → 有高置信先验时问题集不含 doc_role_{i}。
        captured: dict = {}

        def fake_ask(batches, **kwargs):
            captured["questions"] = {}
            answers = {}
            for state, questions in batches:
                captured["questions"].update(questions)
                answers.update(fake_answers_for(state["candidates"], {"f001"}))
            return fake_jev_answer(answers, len(batches))

        with patch.object(jev_nav_module, "is_stage_enabled", return_value=True), \
             patch.object(jev_nav_module, "ask_batches_concurrent", side_effect=fake_ask):
            t1, t2, recs, diag = apply_e2_navigation(q, {"f001": doc}, [doc], [], contexts=[ctx])
        self.assertFalse(any(k.startswith("doc_role_") for k in captured["questions"]))
        self.assertEqual(doc.jev_doc_role, "normative")
        self.assertIn("实体吻合:高", doc.jev_badge)
        self.assertIn("权威角色:运维规程SOP", doc.jev_badge)
        self.assertIn("f001", [d.doc_id for d in recs])

    def test_09b_registry_only_m1_prior_mounted_when_doc_type_empty(self) -> None:
        # T2 静态登记表快筛产出 jev_doc_type="" 且 jev_is_registry=True，E2 必须完整挂载
        self.builder.upsert_document(
            self.pre / "b.md", "b.md",
            role_info={
                "jev_doc_type": "",
                "jev_doc_type_conf": 0.0,
                "jev_is_registry": True,
            },
        )
        self.builder.finalize()
        engine = self._build_engine()
        ctx = engine.contexts[0]
        doc_rows = ctx.index.doc_table.to_lance().to_table(
            columns=["doc_key", "rel_path", "jev_doc_type", "jev_is_registry"]
        ).to_pylist()
        target = next(row for row in doc_rows if row["rel_path"] == "b.md")
        doc = DocScore(
            route_index=0, doc_id="f002", local_doc_id=str(target["doc_key"]),
            rel_path="b.md", title="2026 Q4 Tier-1 Vendors",
            candidates=[Candidate(
                route_index=0, doc_id="f002", local_doc_id=str(target["doc_key"]),
                rel_path="b.md", section_id="s1", start_line=1, end_line=2,
                text="Vendor roster table.",
            )],
            score=0.5,
        )
        q = QueryPack(questions=["List all Q4 Tier-1 vendors"])
        with patch.object(jev_nav_module, "is_stage_enabled", return_value=False):
            apply_e2_navigation(q, {"f002": doc}, [doc], [], contexts=[ctx])
        self.assertTrue(doc.jev_is_registry)
        self.assertEqual(doc.jev_badge, "[权威角色:汇总登记表]")

    def test_10_jev_unavailable_soft_degraded_keeps_tiers(self) -> None:
        q = DynamicOverviewEngine.build_query_pack(
            ["How is retention policy evaluated in the control plane?"]
        )

        def fake_rerank(_query, documents):
            return [1.0 if "retention" in text.lower() else 0.0 for text in documents]

        def fake_a0(q_orig, evidence, **kwargs):
            return (
                {
                    "hit_quality": "FULL_HIT",
                    "intermediate_result_A": "",
                    "unresolved_knowledge_gaps": [],
                    "next_queries_Q1": {"sub_questions": [], "key_terms": []},
                },
                "", 1.0, 100,
            )

        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()), \
             patch.object(engine_module_ref(), "batch_rerank_scores", side_effect=fake_rerank), \
             patch.object(engine_module_ref(), "call_a0", side_effect=fake_a0), \
             patch.object(jev_nav_module, "is_stage_enabled", return_value=False):
            engine_a = self._build_engine()
            result_a = engine_a.run(q)
        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()), \
             patch.object(engine_module_ref(), "batch_rerank_scores", side_effect=fake_rerank), \
             patch.object(engine_module_ref(), "call_a0", side_effect=fake_a0), \
             patch.object(jev_nav_module, "is_stage_enabled", return_value=True), \
             patch.object(
                 jev_nav_module, "ask_batches_concurrent",
                 side_effect=JevUnavailable("test-dummy-endpoint unreachable"),
             ):
            engine_b = self._build_engine()
            result_b = engine_b.run(q)

        self.assertTrue(result_b["ready"])
        self.assertTrue(result_b["diagnostics"]["jev_e2"]["degraded"])
        self.assertEqual(result_b["diagnostics"]["jev_e2"]["stage"], "E2")
        # 软降级下 Tier 1/2 顺序与开关关闭时完全一致（徽标与导航区均不出现）。
        self.assertEqual(result_a["merged_overview"], result_b["merged_overview"])
        self.assertEqual(result_a["stats"]["tier1"], result_b["stats"]["tier1"])
        self.assertEqual(result_a["stats"]["tier2"], result_b["stats"]["tier2"])
        self.assertNotIn("★ 优先精读建议", result_b["merged_overview"])

    def test_10b_engine_exposes_jev_e1_diagnostics_and_degraded_trace(self) -> None:
        q = QueryPack(questions=["How is retention policy evaluated?"])

        def fake_rerank(_query, documents):
            return [1.0 if "retention" in text.lower() else 0.0 for text in documents]

        def fake_a0_ok(q_orig, evidence, **kwargs):
            return (
                {
                    "hit_quality": "FULL_HIT",
                    "intermediate_result_A": "",
                    "unresolved_knowledge_gaps": [],
                    "next_queries_Q1": {"sub_questions": [], "key_terms": []},
                    "jev": {
                        "degraded": False,
                        "stage": "E1",
                        "mode": "fast_stop",
                        "direct_answer_ready": 0.99,
                    },
                },
                "", 3.5, 0,
            )

        def fake_a0_fail(q_orig, evidence, **kwargs):
            return None, "config incomplete; jev_e1_degraded: boom", 2.0, 0

        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()), \
             patch.object(engine_module_ref(), "batch_rerank_scores", side_effect=fake_rerank), \
             patch.object(engine_module_ref(), "call_a0", side_effect=fake_a0_ok), \
             patch.object(jev_nav_module, "is_stage_enabled", return_value=False):
            res_ok = self._build_engine().run(q)
        self.assertEqual(res_ok["diagnostics"]["jev_e1"]["mode"], "fast_stop")
        self.assertEqual(res_ok["diagnostics"]["a0"]["jev"]["mode"], "fast_stop")

        with patch.object(SectionIndex, "_get_embedding", return_value=FakeEmbedding()), \
             patch.object(engine_module_ref(), "batch_rerank_scores", side_effect=fake_rerank), \
             patch.object(engine_module_ref(), "call_a0", side_effect=fake_a0_fail), \
             patch("common.jev_client.is_stage_enabled", side_effect=lambda st: st == "E1"), \
             patch.object(jev_nav_module, "is_stage_enabled", return_value=False):
            res_deg = self._build_engine().run(q)
        self.assertTrue(res_deg["diagnostics"]["jev_e1"]["degraded"])
        self.assertEqual(res_deg["diagnostics"]["jev_e1"]["stage"], "E1")
        self.assertIn("jev_e1_degraded", res_deg["diagnostics"]["jev_e1"]["error"])

    def test_11_no_nav_block_without_strong_match(self) -> None:
        q = QueryPack(questions=["q1"])
        tier1 = [make_doc(1, score=0.6), make_doc(2, score=0.5)]
        stats = {
            "doc_count": 10, "tier2": 0, "candidate_pool": 2,
            "tier1_truncated": False, "tier2_truncated": False,
            "omitted_candidates": 0,
        }
        text = DynamicOverviewEngine._render(
            None, q, tier1, [], [],
            degraded=False, degraded_reason="", a0_meta={}, stats=stats,
            recommendations=[],
        )
        self.assertNotIn("★ 优先精读建议", text)

        gold = tier1[0]
        gold.jev_target_match = 0.99
        gold.jev_constraint_fit = 2.0
        gold.jev_doc_type = "runbook_sop"
        gold.jev_promoted = True
        gold.jev_badge = format_doc_badge(gold)
        text_with = DynamicOverviewEngine._render(
            None, q, tier1, [], [],
            degraded=False, degraded_reason="", a0_meta={}, stats=stats,
            recommendations=[gold],
        )
        self.assertIn("## ★ 优先精读建议", text_with)
        self.assertIn("[f001]", text_with)
        self.assertIn("↑灰区晋升", text_with)
        # 渲染出的 Tier 1 行必须仍被存量 _TIER1_DOC_RE 命中（跨任务契约）。
        tier1_re, _tier2_re = tier_regexes()
        tier1_line = next(
            line for line in text_with.splitlines()
            if line.startswith("│   ├── [f001]")
        )
        match = tier1_re.match(tier1_line)
        self.assertIsNotNone(match)
        self.assertEqual(match.group("gid"), "f001")

    def test_12_end_to_end_promotion_renders_nav_block(self) -> None:
        engine = self._build_engine()
        ctx = engine.contexts[0]
        doc_rows = ctx.index.doc_table.to_lance().to_table(
            columns=["doc_key", "rel_path"]
        ).to_pylist()
        keys = {row["rel_path"]: row["doc_key"] for row in doc_rows}
        section_rows = ctx.index.section_table.to_lance().to_table().to_pylist()
        gold_section = next(
            row for row in section_rows
            if row["doc_key"] == keys["a.md"]
            and int(row["start_line"]) <= 25 and int(row["end_line"]) >= 30
        )
        gold_doc = make_doc(999, score=0.5, text="Mariner failover steps body.")
        gold_doc.doc_id = "f999"
        gold_doc.local_doc_id = str(keys["a.md"])
        gold_doc.rel_path = "a.md"
        gold_doc.title = "a"
        gold_doc.candidates = [Candidate(
            route_index=0, doc_id="f999", local_doc_id=str(keys["a.md"]),
            rel_path="a.md", section_id=str(gold_section["section_id"]),
            start_line=25, end_line=30,
            text="Mariner failover steps body.",
        )]
        # 把金标放在池外灰区（第 101 名之外）——但本小库仅 2 篇，
        # 直接验证：灰区晋升 + 导航区渲染 + 行尾徽标全链路。
        docs = {"f999": gold_doc}
        tier1: list[DocScore] = []
        tier2: list[DocScore] = []
        q = QueryPack(questions=["Mariner failover steps"])

        def fake_ask(batches, **kwargs):
            answers = {}
            for state, _questions in batches:
                answers.update(fake_answers_for(state["candidates"], {"f999"}))
            return fake_jev_answer(answers, len(batches))

        with patch.object(jev_nav_module, "is_stage_enabled", return_value=True), \
             patch.object(jev_nav_module, "ask_batches_concurrent", side_effect=fake_ask):
            t1, t2, recs, diag = apply_e2_navigation(q, docs, tier1, tier2, contexts=[ctx])

        self.assertEqual([d.doc_id for d in t1], ["f999"])
        self.assertTrue(gold_doc.jev_promoted)
        self.assertIn("f999", diag["promoted"])
        self.assertEqual([d.doc_id for d in recs], ["f999"])
        self.assertIn("实体吻合:高", gold_doc.jev_badge)
        self.assertIn("↑灰区晋升", gold_doc.jev_badge)
        # 整节回读被送进 JEV state（包含章节标题与表格表头，而非残截片段）。
        # 经由 build_batches 复核 state 内容：
        entries = [{
            "idx": 0, "doc_id": "f999", "path": gold_doc.rel_path,
            "title": gold_doc.title, "doc_type_prior": "unknown",
            "is_registry_prior": False,
            "best_sections_text": jev_nav_module._extract_full_hit_sections(gold_doc, ctx),
        }]
        batches = build_batches(q, entries, {})
        state_text = batches[0][0]["candidates"][0]["best_sections_text"]
        self.assertIn("# Ops Bridge Runbook", state_text)
        self.assertIn("| col1 | col2 |", state_text)


if __name__ == "__main__":
    unittest.main()
