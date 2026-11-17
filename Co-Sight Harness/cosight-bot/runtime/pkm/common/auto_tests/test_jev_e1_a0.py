#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节点 JEV-E1（T3）A0 三档快筛与去预览污染单测。

覆盖：开关关闭向后兼容、FULL_HIT 秒停（零 LLM 调用）、防假停强制降档、
去预览污染（违规 intermediate_result_A 强制清空）、无显式槽位兜底要素、
轻量 Q1 LLM 故障确定性兜底、JEV 故障有痕软降级、空证据包短路、
阈值环境变量微调、轻量 Prompt 模板与离线回放假停率统计。
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

import common.jev_client as jc  # noqa: E402
from common.dynamic_overview import a0 as a0_mod  # noqa: E402
from common.dynamic_overview import a0_jev  # noqa: E402
from common.dynamic_overview import prompts as prompts_mod  # noqa: E402
from common.dynamic_overview.models import QueryPack  # noqa: E402

_JEV_ENV_KEYS = [
    "COSIGHTBOT_JEV_ENABLED",
    "COSIGHTBOT_JEV_STAGES",
    "COSIGHTBOT_JEV_INTERNAL_ENDPOINTS",
    "COSIGHTBOT_JEV_INTERNAL_MODEL",
    "COSIGHTBOT_JEV_INTERNAL_API_KEY",
    "COSIGHTBOT_JEV_TIMEOUT_S",
    "COSIGHTBOT_JEV_E1_READY_MIN",
    "COSIGHTBOT_JEV_E1_CLUE_MIN",
    "COSIGHTBOT_JEV_E1_FULLHIT_MIN",
]

_ENDPOINT = "http://198.51.100.10:31011/v1/systemone"
_MODEL = "Ntele-decision-V1"


def jev_env(**overrides) -> dict:
    """清空全部 JEV 环境变量后再覆盖，避免宿主环境影响用例。"""
    env = {k: v for k, v in os.environ.items() if k not in _JEV_ENV_KEYS}
    env.update(overrides)
    return env


def _ready_env(**overrides) -> dict:
    env = jev_env(
        COSIGHTBOT_JEV_ENABLED="1",
        COSIGHTBOT_JEV_INTERNAL_ENDPOINTS=_ENDPOINT,
        COSIGHTBOT_JEV_INTERNAL_MODEL=_MODEL,
    )
    env.update(overrides)
    return env


def _noul(p: float) -> dict:
    return {"type": "noul", "noul": p}


def _choice(dist: dict) -> dict:
    return {"type": "choice", "choice": max(dist, key=dist.get), "probabilities": dist}


def _jev_answer(answers: dict, latency_ms: float = 12.3) -> jc.JevAnswer:
    return jc.JevAnswer(answers=answers, audit={"latency_ms": latency_ms}, raw={})


def _qp(**overrides) -> QueryPack:
    base = dict(
        questions=["EU-West 区域生产环境 S3 保留期是多少？"],
        terms=[],
        entities=["EU-West"],
        constraints=["生产环境"],
        identifiers=["ERR_401"],
        exclude=[],
    )
    base.update(overrides)
    return QueryPack(**base)


def _covered_clues(n: int, p: float = 0.96) -> dict:
    return {f"clue_{i}": _noul(p) for i in range(n)}


class SwitchOffCompatTest(unittest.TestCase):
    """开关关闭时 100% 走原有 legacy 路径，不触发任何 JEV 分发。"""

    def test_global_disabled_routes_to_legacy(self):
        legacy = mock.Mock(return_value=("legacy-payload", "", 50.0, 100))
        jev_path = mock.Mock(side_effect=AssertionError("JEV path must not run"))
        with mock.patch.dict(os.environ, jev_env(), clear=True), \
                mock.patch.object(a0_mod, "_call_a0_legacy_llm", legacy), \
                mock.patch.object(a0_jev, "call_a0_jev", jev_path):
            result = a0_mod.call_a0(_qp(), "evidence", doc_count=10,
                                    directory_map="map", timeout=30.0)
        self.assertEqual(result, ("legacy-payload", "", 50.0, 100))
        legacy.assert_called_once()
        jev_path.assert_not_called()

    def test_stage_subset_without_e1_routes_to_legacy(self):
        legacy = mock.Mock(return_value=(None, "A0 LLM config incomplete", 0.0, 0))
        jev_path = mock.Mock(side_effect=AssertionError("JEV path must not run"))
        env = _ready_env(COSIGHTBOT_JEV_STAGES="E2,A3")
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(a0_mod, "_call_a0_legacy_llm", legacy), \
                mock.patch.object(a0_jev, "call_a0_jev", jev_path):
            a0_mod.call_a0(_qp(), "evidence", doc_count=10, directory_map="map")
        legacy.assert_called_once()
        jev_path.assert_not_called()


class FastStopTest(unittest.TestCase):
    """FULL_HIT 秒停路径：完全不调用生成式 LLM，预览恒为空。"""

    def test_fast_stop_zero_llm_calls(self):
        answers = {
            "hit_quality": _choice({"FULL_HIT": 0.992, "PARTIAL_HIT": 0.006, "MISS": 0.002}),
            "direct_answer_ready": _noul(0.988),
            **_covered_clues(3, 0.96),
        }
        q1_llm = mock.Mock(side_effect=AssertionError("LLM must not be called on fast stop"))
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", return_value=_jev_answer(answers)) as ask_mock, \
                mock.patch.object(a0_jev, "call_a0_q1_only", q1_llm):
            payload, error, elapsed, tokens = a0_mod.call_a0(
                _qp(), "evidence text", doc_count=10, directory_map="map"
            )
        ask_mock.assert_called_once()
        q1_llm.assert_not_called()
        self.assertEqual(error, "")
        self.assertEqual(payload["hit_quality"], "FULL_HIT")
        self.assertEqual(payload["intermediate_result_A"], "")
        self.assertEqual(payload["unresolved_knowledge_gaps"], [])
        self.assertEqual(payload["next_queries_Q1"], {"sub_questions": [], "key_terms": []})
        self.assertEqual(tokens, 0)
        self.assertEqual(payload["jev"]["mode"], "fast_stop")
        self.assertEqual(payload["jev"]["winner_prob"], 0.992)
        self.assertEqual(payload["jev"]["direct_answer_ready"], 0.988)
        self.assertGreaterEqual(elapsed, 0.0)

    def test_fast_stop_request_has_no_intent_correction(self):
        captured = {}

        def fake_ask(**kwargs):
            captured.update(kwargs)
            return _jev_answer({
                "hit_quality": _choice({"FULL_HIT": 0.99, "PARTIAL_HIT": 0.005, "MISS": 0.005}),
                "direct_answer_ready": _noul(0.99),
                **_covered_clues(1, 0.97),
            })

        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", side_effect=fake_ask):
            payload, _e, _ms, _tk = a0_mod.call_a0(
                _qp(entities=[], constraints=[], identifiers=[], terms=["专线割接"]),
                "evidence", doc_count=5, directory_map="map"
            )
        self.assertEqual(payload["hit_quality"], "FULL_HIT")
        questions = captured["questions"]
        self.assertEqual(captured["stage"], "E1")
        self.assertEqual(
            set(questions["hit_quality"]["criteria"]), {"FULL_HIT", "PARTIAL_HIT", "MISS"}
        )
        self.assertIn("clue_0", questions)
        self.assertNotIn("INTENT_CORRECTION", json.dumps(questions, ensure_ascii=False))


class AntiFalseStopTest(unittest.TestCase):
    """防假停降档保护：FULL_HIT 但 p_ready/clue 不达标时强制降为 PARTIAL_HIT。"""

    def test_low_ready_downgrades_full_hit(self):
        answers = {
            "hit_quality": _choice({"FULL_HIT": 0.88, "PARTIAL_HIT": 0.10, "MISS": 0.02}),
            "direct_answer_ready": _noul(0.42),
            **_covered_clues(3, 0.97),
        }
        q1_llm = mock.Mock(return_value=(
            {"unresolved_knowledge_gaps": [], "next_queries_Q1": {"sub_questions": ["q"], "key_terms": ["t"]}},
            "", 100.0, 50, {"model": "m"},
        ))
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", return_value=_jev_answer(answers)), \
                mock.patch.object(a0_jev, "call_a0_q1_only", q1_llm):
            payload, _e, _ms, _tk = a0_mod.call_a0(
                _qp(), "evidence", doc_count=10, directory_map="map"
            )
        self.assertEqual(payload["hit_quality"], "PARTIAL_HIT")
        self.assertEqual(payload["intermediate_result_A"], "")
        self.assertEqual(q1_llm.call_args.kwargs["missing_clues"], [])
        self.assertEqual(q1_llm.call_args.kwargs["jev_quality"], "PARTIAL_HIT")

    def test_missing_clue_downgrades_and_is_passed_to_q1(self):
        answers = {
            "hit_quality": _choice({"FULL_HIT": 0.97, "PARTIAL_HIT": 0.02, "MISS": 0.01}),
            "direct_answer_ready": _noul(0.99),
            "clue_0": _noul(0.999),   # identifier ERR_401 已覆盖
            "clue_1": _noul(0.003),   # entity EU-West 未覆盖
            "clue_2": _noul(0.991),   # constraint 生产环境 已覆盖
        }
        q1_llm = mock.Mock(return_value=(
            {"unresolved_knowledge_gaps": [], "next_queries_Q1": {"sub_questions": ["q"], "key_terms": ["EU-West"]}},
            "", 100.0, 50, {"model": "m"},
        ))
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", return_value=_jev_answer(answers)), \
                mock.patch.object(a0_jev, "call_a0_q1_only", q1_llm):
            payload, _e, _ms, _tk = a0_mod.call_a0(
                _qp(), "evidence", doc_count=10, directory_map="map"
            )
        self.assertEqual(payload["hit_quality"], "PARTIAL_HIT")
        self.assertEqual(q1_llm.call_args.kwargs["missing_clues"], ["EU-West"])
        self.assertEqual(payload["jev"]["missing_clues"], ["EU-West"])
        self.assertIn("EU-West", payload["unresolved_knowledge_gaps"])

    def test_ready_min_env_override_tightens_gate(self):
        answers = {
            "hit_quality": _choice({"FULL_HIT": 0.99, "PARTIAL_HIT": 0.01, "MISS": 0.0}),
            "direct_answer_ready": _noul(0.98),
            **_covered_clues(3, 0.99),
        }
        q1_llm = mock.Mock(return_value=(
            {"unresolved_knowledge_gaps": [], "next_queries_Q1": {"sub_questions": [], "key_terms": []}},
            "", 10.0, 10, {},
        ))
        env = _ready_env(COSIGHTBOT_JEV_E1_READY_MIN="0.99")
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(jc, "ask", return_value=_jev_answer(answers)), \
                mock.patch.object(a0_jev, "call_a0_q1_only", q1_llm):
            payload, _e, _ms, _tk = a0_mod.call_a0(
                _qp(), "evidence", doc_count=10, directory_map="map"
            )
        self.assertEqual(payload["hit_quality"], "PARTIAL_HIT")
        self.assertNotEqual(payload["jev"]["mode"], "fast_stop")


class PreviewPollutionTest(unittest.TestCase):
    """去预览污染：LLM 违规输出 intermediate_result_A 也强制清空。"""

    def test_smuggled_preview_is_always_cleared(self):
        answers = {
            "hit_quality": _choice({"PARTIAL_HIT": 0.93, "FULL_HIT": 0.05, "MISS": 0.02}),
            "direct_answer_ready": _noul(0.51),
            **_covered_clues(3, 0.97),
        }
        q1_llm = mock.Mock(return_value=(
            {
                "unresolved_knowledge_gaps": ["g1"],
                "next_queries_Q1": {"sub_questions": ["q1"], "key_terms": ["t1"]},
                "intermediate_result_A": "私自编造的答案预览",
            },
            "", 100.0, 50, {"model": "m"},
        ))
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", return_value=_jev_answer(answers)), \
                mock.patch.object(a0_jev, "call_a0_q1_only", q1_llm):
            payload, _e, _ms, tokens = a0_mod.call_a0(
                _qp(), "evidence", doc_count=10, directory_map="map"
            )
        self.assertEqual(payload["intermediate_result_A"], "")
        self.assertEqual(payload["hit_quality"], "PARTIAL_HIT")
        self.assertEqual(payload["next_queries_Q1"]["sub_questions"], ["q1"])
        self.assertGreater(tokens, 0)


class FallbackCluesTest(unittest.TestCase):
    """无显式槽位时的兜底要素提取（防空列表放水）。"""

    def test_extract_clues_falls_back_to_positive_terms(self):
        qp = _qp(entities=[], constraints=[], identifiers=[], terms=["专线割接", "SLA"])
        clues = a0_jev._extract_clues(qp)
        self.assertEqual([text for _kind, text in clues], ["专线割接", "SLA"])
        self.assertTrue(all(kind == "term" for kind, _text in clues))

    def test_extract_clues_caps_at_max_and_dedupes(self):
        qp = _qp(identifiers=[f"ID-{i}" for i in range(12)] + ["ID-0"])
        clues = a0_jev._extract_clues(qp)
        self.assertEqual(len(clues), a0_jev.MAX_CLUES)
        lowered = [text.lower() for _kind, text in clues]
        self.assertEqual(len(set(lowered)), len(lowered))

    def test_extract_clues_filters_punctuation_noise(self):
        # "-" 长度不足、"??" 为纯标点、"A" 长度不足：全部过滤；"AB" 保留。
        qp = _qp(identifiers=["-", "??", "A", "AB"], entities=[], constraints=[], terms=[])
        clues = a0_jev._extract_clues(qp)
        self.assertEqual([text for _kind, text in clues], ["AB"])
        self.assertEqual(a0_jev._extract_clues(_qp(identifiers=["-", "??"], entities=[], constraints=[], terms=[])), [])


class Q1DeterministicFallbackTest(unittest.TestCase):
    """轻量 Q1 LLM 故障时基于 missing_clues 的确定性兜底。"""

    def test_llm_failure_falls_back_to_missing_clues(self):
        answers = {
            "hit_quality": _choice({"PARTIAL_HIT": 0.95, "FULL_HIT": 0.03, "MISS": 0.02}),
            "direct_answer_ready": _noul(0.40),
            "clue_0": _noul(0.0001),  # identifier ERR_401 缺失
            "clue_1": _noul(0.0002),  # entity EU-West 缺失
            "clue_2": _noul(0.99),    # constraint 生产环境 已覆盖
        }
        q1_llm = mock.Mock(return_value=(None, "A0 request failed: HTTPError: 500", 100.0, 123, {}))
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", return_value=_jev_answer(answers)), \
                mock.patch.object(a0_jev, "call_a0_q1_only", q1_llm):
            payload, error, _ms, _tk = a0_mod.call_a0(
                _qp(), "evidence", doc_count=10, directory_map="map"
            )
        q1_llm.assert_called_once()
        self.assertEqual(error, "")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["hit_quality"], "PARTIAL_HIT")
        self.assertEqual(payload["intermediate_result_A"], "")
        self.assertEqual(payload["next_queries_Q1"]["key_terms"], ["ERR_401", "EU-West"])
        self.assertTrue(payload["next_queries_Q1"]["sub_questions"])
        self.assertIn("ERR_401", " ".join(payload["next_queries_Q1"]["sub_questions"]))
        self.assertTrue(payload["jev"]["q1_llm_fallback"])

    def test_llm_failure_without_missing_clues_falls_back_to_legacy(self):
        answers = {
            "hit_quality": _choice({"PARTIAL_HIT": 0.95, "FULL_HIT": 0.03, "MISS": 0.02}),
            "direct_answer_ready": _noul(0.50),
            **_covered_clues(3, 0.99),
        }
        q1_llm = mock.Mock(return_value=(None, "A0 returned empty/invalid JSON", 100.0, 123, {}))
        legacy = mock.Mock(return_value=(
            {"hit_quality": "PARTIAL_HIT", "intermediate_result_A": "草稿",
             "unresolved_knowledge_gaps": [], "next_queries_Q1": {"sub_questions": [], "key_terms": []}},
            "", 50.0, 100,
        ))
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", return_value=_jev_answer(answers)), \
                mock.patch.object(a0_jev, "call_a0_q1_only", q1_llm), \
                mock.patch.object(a0_mod, "_call_a0_legacy_llm", legacy):
            payload, _e, _ms, _tk = a0_mod.call_a0(
                _qp(), "evidence", doc_count=10, directory_map="map"
            )
        legacy.assert_called_once()
        self.assertEqual(payload["intermediate_result_A"], "")
        self.assertTrue(payload["jev"]["legacy_llm_fallback"])


class JevDegradedTest(unittest.TestCase):
    """JEV 故障有痕软降级：回退 legacy LLM 且清空预览。"""

    def test_jev_unavailable_degrades_to_legacy_with_trace(self):
        legacy_payload = {
            "hit_quality": "PARTIAL_HIT",
            "intermediate_result_A": "legacy 草稿预览",
            "unresolved_knowledge_gaps": ["g"],
            "next_queries_Q1": {"sub_questions": ["q"], "key_terms": ["t"]},
        }
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", side_effect=jc.JevUnavailable("timeout")), \
                mock.patch.object(a0_mod, "_call_a0_legacy_llm",
                                  return_value=(legacy_payload, "", 50.0, 100)) as legacy, \
                mock.patch.object(a0_jev, "log_event") as log_mock:
            payload, error, _ms, tokens = a0_mod.call_a0(
                _qp(), "evidence", doc_count=10, directory_map="map"
            )
        legacy.assert_called_once()
        self.assertEqual(error, "")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["intermediate_result_A"], "")
        self.assertEqual(payload["unresolved_knowledge_gaps"], ["g"])
        self.assertEqual(payload["next_queries_Q1"]["key_terms"], ["t"])
        self.assertTrue(payload["jev"]["degraded"])
        self.assertEqual(payload["jev"]["stage"], "E1")
        self.assertIn("timeout", payload["jev"]["error"])
        self.assertEqual(tokens, 100)
        events = [call.args[1] for call in log_mock.call_args_list]
        self.assertIn("a0:jev:degraded", events)

    def test_jev_unexpected_error_also_degrades(self):
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", side_effect=KeyError("boom")), \
                mock.patch.object(a0_mod, "_call_a0_legacy_llm",
                                  return_value=(None, "A0 LLM config incomplete", 0.0, 0)):
            payload, error, _ms, _tk = a0_mod.call_a0(
                _qp(), "evidence", doc_count=10, directory_map="map"
            )
        self.assertIsNone(payload)
        self.assertIn("config incomplete", error)
        self.assertIn("jev_e1_degraded", error)


class EmptyEvidenceTest(unittest.TestCase):
    """空证据包短路：不浪费 JEV 请求，直接按 MISS 生成二跳词。"""

    def test_empty_evidence_skips_jev(self):
        q1_llm = mock.Mock(return_value=(
            {"unresolved_knowledge_gaps": [], "next_queries_Q1": {"sub_questions": ["q"], "key_terms": ["t"]}},
            "", 100.0, 50, {"model": "m"},
        ))
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask") as ask_mock, \
                mock.patch.object(a0_jev, "call_a0_q1_only", q1_llm):
            payload, _e, _ms, _tk = a0_mod.call_a0(
                _qp(), "   ", doc_count=10, directory_map="map"
            )
        ask_mock.assert_not_called()
        q1_llm.assert_called_once()
        self.assertEqual(payload["hit_quality"], "MISS")
        self.assertEqual(payload["intermediate_result_A"], "")
        self.assertEqual(payload["jev"]["mode"], "empty_evidence")
        self.assertEqual(q1_llm.call_args.kwargs["missing_clues"], ["ERR_401", "EU-West", "生产环境"])


class Q1PromptTemplateTest(unittest.TestCase):
    """轻量模板：仅两顶层键、无预览字段；原 A0 模板保持不变。"""

    def test_q1_only_system_has_no_preview_field(self):
        self.assertNotIn("intermediate_result_A", prompts_mod.A0_Q1_ONLY_SYSTEM)
        self.assertIn("unresolved_knowledge_gaps", prompts_mod.A0_Q1_ONLY_SYSTEM)
        self.assertIn("next_queries_Q1", prompts_mod.A0_Q1_ONLY_SYSTEM)
        self.assertIn("严禁生成任何试答草稿或结论预览", prompts_mod.A0_Q1_ONLY_SYSTEM)

    def test_legacy_a0_system_unchanged(self):
        self.assertIn("intermediate_result_A", prompts_mod.A0_SYSTEM)
        self.assertIn("INTENT_CORRECTION", prompts_mod.A0_SYSTEM)

    def test_build_q1_only_user_prompt_carries_jev_context(self):
        prompt = prompts_mod.build_a0_q1_only_user_prompt(
            _qp(), "证据包内容", doc_count=42, directory_map="目录态势",
            jev_quality="PARTIAL_HIT", missing_clues=["EU-West", "ERR_401"],
        )
        self.assertIn("PARTIAL_HIT", prompt)
        self.assertIn("EU-West", prompt)
        self.assertIn("ERR_401", prompt)
        self.assertIn("总文档 42 篇", prompt)
        self.assertIn("证据包内容", prompt)


class ExtractJsonQ1Test(unittest.TestCase):
    """_extract_json 兼容仅含 unresolved_knowledge_gaps 的轻量 Q1 JSON。"""

    def test_extracts_gaps_only_json(self):
        data = a0_mod._extract_json('前置思考 {"unresolved_knowledge_gaps": ["g"], '
                                    '"next_queries_Q1": {"sub_questions": [], "key_terms": ["t"]}}')
        self.assertIsNotNone(data)
        self.assertEqual(data["unresolved_knowledge_gaps"], ["g"])


class ReplayEvalTest(unittest.TestCase):
    """离线回放统计：false_stop_rate 准确计算与门禁判定。"""

    def test_evaluate_replay_samples_counts_false_stops(self):
        def fast_stop(p_ready: float):
            return ({"hit_quality": "FULL_HIT", "intermediate_result_A": "",
                     "unresolved_knowledge_gaps": [], "next_queries_Q1": {},
                     "jev": {"mode": "fast_stop", "direct_answer_ready": p_ready,
                             "missing_clues": []}}, "", 10.0, 0)

        def hop2(p_ready: float):
            return ({"hit_quality": "PARTIAL_HIT", "intermediate_result_A": "",
                     "unresolved_knowledge_gaps": [], "next_queries_Q1": {},
                     "jev": {"mode": "hop2_q1", "direct_answer_ready": p_ready,
                             "missing_clues": ["x"]}}, "", 10.0, 50)

        # 样本顺序与 side_effect 一一对应：前 4 条真值需要二跳，其中 2 条被误判秒停。
        outcomes = [fast_stop(0.99), hop2(0.40), fast_stop(0.97), hop2(0.30),
                    fast_stop(0.96), hop2(0.55), hop2(0.60), hop2(0.70),
                    hop2(0.80), hop2(0.90)]
        truth = [True, True, True, True, False, False, False, False, False, False]
        samples = [
            {"q_orig": _qp(), "evidence": f"ev-{i}", "directory_map": "map",
             "need_hop2_ground_truth": truth[i]}
            for i in range(10)
        ]
        with mock.patch.object(a0_jev, "call_a0_jev", side_effect=outcomes):
            report = a0_jev.evaluate_e1_replay_samples(samples)
        self.assertEqual(report["evaluated"], 10)
        self.assertEqual(report["fast_stop_count"], 3)
        self.assertEqual(report["false_stop_count"], 2)
        self.assertAlmostEqual(report["fast_stop_rate"], 0.3, places=4)
        self.assertAlmostEqual(report["false_stop_rate"], 0.2, places=4)
        self.assertFalse(report["false_stop_gate_pass"])
        self.assertEqual(report["question_set_version"], "office-e1-a0-v1")
        self.assertEqual(report["p_ready_quantiles"]["p50"], 0.7)

    def test_evaluate_replay_samples_all_good_passes_gate(self):
        outcome = ({"hit_quality": "FULL_HIT", "intermediate_result_A": "",
                    "unresolved_knowledge_gaps": [], "next_queries_Q1": {},
                    "jev": {"mode": "hop2_q1", "direct_answer_ready": 0.5,
                            "missing_clues": []}}, "", 10.0, 0)
        samples = [{"q_orig": _qp(), "evidence": "ev", "directory_map": "map",
                    "need_hop2_ground_truth": True} for _ in range(5)]
        with mock.patch.object(a0_jev, "call_a0_jev", return_value=outcome):
            report = a0_jev.evaluate_e1_replay_samples(samples)
        self.assertEqual(report["false_stop_rate"], 0.0)
        self.assertTrue(report["false_stop_gate_pass"])


class EvidenceTruncationTest(unittest.TestCase):
    """state 组装：证据包与目录态势按上限截断。"""

    def test_state_truncation_limits(self):
        captured = {}

        def fake_ask(**kwargs):
            captured.update(kwargs)
            return _jev_answer({
                "hit_quality": _choice({"FULL_HIT": 0.99, "PARTIAL_HIT": 0.01, "MISS": 0.0}),
                "direct_answer_ready": _noul(0.99),
                **_covered_clues(1, 0.99),
            })

        long_evidence = "x" * 50_000
        long_map = "m" * 8_000
        with mock.patch.dict(os.environ, _ready_env(), clear=True), \
                mock.patch.object(jc, "ask", side_effect=fake_ask):
            a0_mod.call_a0(_qp(identifiers=[], entities=[], constraints=[], terms=["abc"]),
                           long_evidence, doc_count=10, directory_map=long_map)
        state = captured["state"]
        self.assertEqual(len(state["evidence_pack"]), a0_jev.MAX_EVIDENCE_CHARS)
        self.assertEqual(len(state["directory_map"]), a0_jev.MAX_DIR_MAP_CHARS)


if __name__ == "__main__":
    unittest.main()
