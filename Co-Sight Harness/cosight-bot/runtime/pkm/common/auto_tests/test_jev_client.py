#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公共 JEV 客户端与开关底座（T0）单测。

覆盖：开关矩阵、配置三态自检与端点规范化、三种原语安全解析、
反注入幂等、拆批不丢不重、HTTP 代理绕过/重试/2MB 上限/密钥零泄漏、
多批并发聚合与重名键防护。
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

_DUMMY_KEY = "test-dummy-secret-key"

_JEV_ENV_KEYS = [
    "COSIGHTBOT_JEV_ENABLED",
    "COSIGHTBOT_JEV_STAGES",
    "COSIGHTBOT_JEV_CHANNEL",
    "COSIGHTBOT_JEV_INTERNAL_ENDPOINTS",
    "COSIGHTBOT_JEV_INTERNAL_MODEL",
    "COSIGHTBOT_JEV_INTERNAL_API_KEY",
    "COSIGHTBOT_JEV_EXTERNAL_ENDPOINTS",
    "COSIGHTBOT_JEV_EXTERNAL_MODEL",
    "COSIGHTBOT_JEV_EXTERNAL_API_KEY",
    "JEV_EXTERNAL_ENDPOINTS",
    "JEV_EXTERNAL_MODEL",
    "JEV_EXTERNAL_API_KEY",
    "COSIGHTBOT_JEV_TIMEOUT_S",
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


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, chunks=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._chunks = chunks

    def iter_content(self, chunk_size=65536):
        if self._chunks is not None:
            yield from self._chunks
        else:
            yield json.dumps(self._payload, ensure_ascii=False).encode("utf-8")


def _ok_payload(answers=None, model="jev-1.14.0"):
    return {
        "model": model,
        "answers": answers if answers is not None else {"q1": {"type": "noul", "noul": 0.99}},
        "usage": {"input_tokens": 100, "output_tokens": 10, "cost": 0.0042},
    }


class SwitchMatrixTest(unittest.TestCase):
    def test_default_disabled(self):
        with mock.patch.dict(os.environ, jev_env(), clear=True):
            self.assertFalse(jc.is_jev_enabled())
            self.assertFalse(jc.is_stage_enabled("E1"))

    def test_enabled_all_stages_default(self):
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            self.assertTrue(jc.is_jev_enabled())
            for stage in jc.VALID_STAGES:
                self.assertTrue(jc.is_stage_enabled(stage), stage)

    def test_stage_subset_selection(self):
        with mock.patch.dict(os.environ, _ready_env(COSIGHTBOT_JEV_STAGES="e1,a3"), clear=True):
            self.assertTrue(jc.is_stage_enabled("E1"))
            self.assertTrue(jc.is_stage_enabled("a3"))
            self.assertFalse(jc.is_stage_enabled("E2"))
            self.assertFalse(jc.is_stage_enabled("M1"))  # M1 已迁出 JEV，非法阶段名恒为 False

    def test_invalid_stage_names(self):
        with mock.patch.dict(os.environ, _ready_env(COSIGHTBOT_JEV_STAGES="E1,BOGUS,A3"), clear=True):
            self.assertEqual(jc.enabled_stages(), frozenset({"E1", "A3"}))
            self.assertFalse(jc.is_stage_enabled("BOGUS"))
            self.assertFalse(jc.is_stage_enabled(""))
            self.assertFalse(jc.is_stage_enabled(None))

    def test_explicit_empty_stages_disables_all(self):
        with mock.patch.dict(os.environ, _ready_env(COSIGHTBOT_JEV_STAGES=""), clear=True):
            self.assertEqual(jc.enabled_stages(), frozenset())
            self.assertFalse(jc.is_stage_enabled("E1"))


class ConfigStatusTest(unittest.TestCase):
    def test_unconfigured(self):
        with mock.patch.dict(os.environ, jev_env(), clear=True):
            status = jc.config_status()
            self.assertEqual(status["state"], "unconfigured")
            self.assertEqual(
                status["missing"],
                ["COSIGHTBOT_JEV_INTERNAL_ENDPOINTS", "COSIGHTBOT_JEV_INTERNAL_MODEL"],
            )
            self.assertIn("COSIGHTBOT_JEV_INTERNAL_ENDPOINTS", status["detail"])
            self.assertNotIn("api_key", status)

    def test_incomplete_names_missing_var(self):
        with mock.patch.dict(os.environ, jev_env(COSIGHTBOT_JEV_INTERNAL_ENDPOINTS=_ENDPOINT), clear=True):
            status = jc.config_status()
            self.assertEqual(status["state"], "incomplete")
            self.assertEqual(status["missing"], ["COSIGHTBOT_JEV_INTERNAL_MODEL"])
            self.assertIn("COSIGHTBOT_JEV_INTERNAL_MODEL", status["detail"])

    def test_ready_internal_no_key(self):
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            status = jc.config_status()
            self.assertEqual(status["state"], "ready")
            self.assertEqual(status["missing"], [])
            self.assertEqual(status["endpoints"], [_ENDPOINT])
            self.assertEqual(status["model"], _MODEL)
            self.assertTrue(status["enabled"])
            self.assertNotIn("api_key", status)

    def test_load_settings_none_when_unconfigured(self):
        with mock.patch.dict(os.environ, jev_env(), clear=True):
            self.assertIsNone(jc.load_settings())
            with self.assertRaises(jc.JevUnavailable) as ctx:
                jc.require_settings()
            self.assertIn("COSIGHTBOT_JEV_INTERNAL_ENDPOINTS", str(ctx.exception))

    def test_endpoint_normalization_three_forms(self):
        cases = [
            "http://198.51.100.10:31011/v1/systemone",
            "198.51.100.10:31011",
            "http://198.51.100.10:31011/v1/systemone/",
        ]
        for raw in cases:
            self.assertEqual(jc.normalize_endpoint(raw), _ENDPOINT, raw)

    def test_endpoint_explicit_path_preserved(self):
        self.assertEqual(
            jc.normalize_endpoint("https://gw.internal:8443/api/alpha/decisions"),
            "https://gw.internal:8443/api/alpha/decisions",
        )
        # 绝不在 /v1/systemone 后再拼接其他路径
        self.assertNotIn(
            "/api/alpha/decisions",
            jc.normalize_endpoint("http://198.51.100.10:31011/v1/systemone"),
        )


class ParsersTest(unittest.TestCase):
    def test_probability_valid_values(self):
        for value in (0, 1, 0.0, 1.0, 0.998, 1e-5):
            self.assertEqual(jc.probability({"noul": value}), float(value), value)

    def test_probability_invalid_values(self):
        bad = [-0.01, 1.01, True, False, "0.8", None, {}, {"noul": float("nan")}]
        self.assertIsNone(jc.probability(None))
        self.assertIsNone(jc.probability("0.5"))
        for answer in bad:
            self.assertIsNone(jc.probability(answer), answer)

    def test_choice_winner_from_choice_dict(self):
        answer = {"choice": {"FULL_HIT": 0.992, "PARTIAL_HIT": 0.007, "MISS": 0.001}}
        self.assertEqual(jc.choice_winner(answer), ("FULL_HIT", 0.992))
        self.assertEqual(
            jc.choice_distribution(answer),
            {"FULL_HIT": 0.992, "PARTIAL_HIT": 0.007, "MISS": 0.001},
        )

    def test_choice_winner_allowed_filter(self):
        answer = {"choice": {"FULL_HIT": 0.9, "PARTIAL_HIT": 0.08, "MISS": 0.02}}
        self.assertEqual(
            jc.choice_winner(answer, allowed=("FULL_HIT", "MISS")), ("FULL_HIT", 0.9)
        )
        self.assertEqual(
            jc.choice_winner(answer, allowed=("PARTIAL_HIT",)), ("PARTIAL_HIT", 0.08)
        )
        self.assertEqual(jc.choice_winner(answer, allowed=("NOPE",)), (None, None))

    def test_choice_winner_invalid_and_top_level_mapping(self):
        self.assertEqual(jc.choice_winner({"choice": "FULL_HIT"}), (None, None))
        self.assertEqual(jc.choice_winner(None), (None, None))
        self.assertEqual(jc.choice_winner({"choice": {"A": 1.5, "B": "x"}}), (None, None))
        # 顶层映射与 probabilities 字段两种兼容封装
        self.assertEqual(jc.choice_winner({"FULL_HIT": 1.0, "MISS": 0.0}), ("FULL_HIT", 1.0))
        self.assertEqual(
            jc.choice_winner(
                {"type": "choice", "choice": "a", "probabilities": {"a": 0.9, "b": 0.1}}
            ),
            ("a", 0.9),
        )

    def test_expected_score(self):
        answer = {"score": {"0": 0.1, "1": 0.2, "2": 0.7}}
        self.assertAlmostEqual(jc.expected_score(answer), 1.6)
        # 真实内网 SystemOne 响应封装：score 为标量，档位字典位于 probabilities
        sysone = {
            "type": "score",
            "score": 1.6,
            "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
        }
        self.assertAlmostEqual(jc.expected_score(sysone), 1.6)
        # 非 bool/越界概率档位被剔除后归一化
        answer2 = {"score": {"0": 0.5, "1": True, "2": 0.5, "3": 2.0}}
        self.assertAlmostEqual(jc.expected_score(answer2), 1.0)
        self.assertIsNone(jc.expected_score({}))
        self.assertIsNone(jc.expected_score({"type": "score", "score": 1.6}))
        self.assertIsNone(jc.expected_score({"score": {"0": "x"}}))
        self.assertIsNone(jc.expected_score({"score": {"0": 0.0, "1": 0.0}}))


class AntiInjectionTest(unittest.TestCase):
    def test_idempotent_and_no_mutation(self):
        original = {
            "hit_quality": {
                "type": "choice",
                "instructions": "判定证据包命中档位。",
                "criteria": {"FULL_HIT": "完整命中", "PARTIAL_HIT": "部分命中", "MISS": "未命中"},
            },
            "direct_answer_ready": {"type": "noul", "instructions": "是否可直接回答？"},
        }
        snapshot = json.dumps(original, ensure_ascii=False, sort_keys=True)
        once = jc.append_anti_injection(original)
        twice = jc.append_anti_injection(once)
        self.assertEqual(once, twice)
        for spec in once.values():
            self.assertTrue(spec["instructions"].endswith(jc.ANTI_INJECTION_SUFFIX))
            self.assertEqual(spec["instructions"].count(jc.ANTI_INJECTION_SUFFIX), 1)
        # 原输入字典未被修改
        self.assertEqual(json.dumps(original, ensure_ascii=False, sort_keys=True), snapshot)
        # criteria dict 键值结构保持不变
        self.assertEqual(
            set(once["hit_quality"]["criteria"]), {"FULL_HIT", "PARTIAL_HIT", "MISS"}
        )
        # criteria 中已带后缀时不重复追加
        pre = {
            "q": {
                "type": "noul",
                "instructions": "判断。",
                "criteria": {"true": jc.ANTI_INJECTION_SUFFIX, "false": "否"},
            }
        }
        out = jc.append_anti_injection(pre)
        self.assertFalse(out["q"]["instructions"].endswith(jc.ANTI_INJECTION_SUFFIX))


class PlanBatchesTest(unittest.TestCase):
    def test_no_loss_no_dup_multi_batches(self):
        items = [f"item-{i:02d}" + "x" * 5000 for i in range(25)]
        batches = jc.plan_batches(
            items,
            budget_chars=55000,
            base_state_chars=2000,
            per_item_chars=len,
            per_item_question_chars=320,
        )
        self.assertGreater(len(batches), 1)
        merged = [item for batch in batches for item in batch]
        self.assertEqual(merged, items)  # 顺序保持、不丢不重、不截断
        for batch in batches:
            cost = sum(len(item) + 320 for item in batch)
            self.assertLessEqual(2000 + cost, 55000)

    def test_oversize_item_own_batch_not_truncated(self):
        big = "y" * 60000
        items = ["small", big, "small2"]
        batches = jc.plan_batches(
            items,
            budget_chars=55000,
            base_state_chars=2000,
            per_item_chars=len,
            per_item_question_chars=320,
        )
        merged = [item for batch in batches for item in batch]
        self.assertEqual(merged, items)
        self.assertIn([big], batches)
        self.assertEqual(len(big), 60000)  # 绝不截断

    def test_empty_input(self):
        self.assertEqual(
            jc.plan_batches([], budget_chars=55000, base_state_chars=2000,
                            per_item_chars=len, per_item_question_chars=320),
            [],
        )


class HttpAskTest(unittest.TestCase):
    def test_ask_proxies_headers_and_timeout(self):
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with mock.patch("common.jev_client.requests.post", return_value=_FakeResponse(payload=_ok_payload())) as post:
                result = jc.ask(stage="E1", question_set_version="t-v1", state={"doc": "x"}, questions={"q1": {"type": "noul", "instructions": "?"}})
                self.assertEqual(result.answers["q1"]["noul"], 0.99)
            kwargs = post.call_args.kwargs
            self.assertEqual(kwargs["proxies"], {"http": None, "https": None})
            self.assertEqual(kwargs["headers"]["User-Agent"], "CoSightBot-Office-JEV/1.0")
            self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
            self.assertNotIn("Authorization", kwargs["headers"])  # 免鉴权不带该头
            self.assertEqual(kwargs["timeout"], (5.0, 15.0))  # 连接超时 min(5, t)
            body = json.loads(kwargs["data"].decode("utf-8"))
            self.assertEqual(body["model"], _MODEL)
            self.assertIn(jc.ANTI_INJECTION_SUFFIX, body["questions"]["q1"]["instructions"])
            # 显式 timeout 参数优先
            with mock.patch("common.jev_client.requests.post", return_value=_FakeResponse(payload=_ok_payload())) as post2:
                jc.ask(stage="E1", question_set_version="t-v1", state={}, questions={"q1": {"type": "noul", "instructions": "?"}}, timeout=60.0)
            self.assertEqual(post2.call_args.kwargs["timeout"], (5.0, 60.0))

    def test_ask_403_switches_endpoint(self):
        responses = [
            _FakeResponse(status_code=403),
            _FakeResponse(payload=_ok_payload()),
        ]
        env = _ready_env(COSIGHTBOT_JEV_INTERNAL_ENDPOINTS="http://10.0.0.1:1/v1/systemone," + _ENDPOINT)
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("common.jev_client.requests.post", side_effect=responses) as post:
                with mock.patch("common.jev_client.time.sleep") as sleeper:
                    result = jc.ask(stage="E2", question_set_version="t-v1", state={}, questions={"q1": {"type": "noul", "instructions": "?"}})
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args_list[0].args[0], "http://10.0.0.1:1/v1/systemone")
            self.assertEqual(post.call_args_list[1].args[0], _ENDPOINT)
            sleeper.assert_not_called()  # 403 不重试同一端点
            self.assertEqual(result.audit["endpoint"], _ENDPOINT)

    def test_ask_502_retries_then_success(self):
        responses = [
            _FakeResponse(status_code=502),
            _FakeResponse(payload=_ok_payload()),
        ]
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with mock.patch("common.jev_client.requests.post", side_effect=responses) as post:
                with mock.patch("common.jev_client.time.sleep") as sleeper:
                    result = jc.ask(stage="A1", question_set_version="t-v1", state={}, questions={"q1": {"type": "noul", "instructions": "?"}})
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args_list[0].args[0], _ENDPOINT)
            self.assertEqual(post.call_args_list[1].args[0], _ENDPOINT)
            sleeper.assert_called_once_with(1.5)

    def test_ask_all_endpoints_fail_no_key_leak(self):
        env = _ready_env(
            COSIGHTBOT_JEV_INTERNAL_ENDPOINTS="http://10.0.0.1:1/v1/systemone," + _ENDPOINT,
            COSIGHTBOT_JEV_INTERNAL_API_KEY=_DUMMY_KEY,
        )
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("common.jev_client.requests.post", side_effect=[_FakeResponse(status_code=502)] * 4):
                with mock.patch("common.jev_client.time.sleep"):
                    with self.assertLogs("common.jev_client", level="WARNING") as logs:
                        with self.assertRaises(jc.JevUnavailable) as ctx:
                            jc.ask(stage="A3", question_set_version="t-v1", state={}, questions={"q1": {"type": "noul", "instructions": "?"}})
        message = str(ctx.exception)
        self.assertIn("stage=A3", message)
        self.assertIn("10.0.0.1:1", message)
        self.assertIn("198.51.100.10:31011", message)
        self.assertNotIn(_DUMMY_KEY, message)
        self.assertNotIn(_DUMMY_KEY, "\n".join(logs.output))

    def test_ask_rejects_oversize_response(self):
        big_chunk = b"x" * (jc.MAX_RESPONSE_BYTES + 1024)
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with mock.patch("common.jev_client.requests.post", return_value=_FakeResponse(chunks=[big_chunk])):
                with mock.patch("common.jev_client.time.sleep"):
                    with self.assertRaises(jc.JevUnavailable):
                        jc.ask(stage="A1", question_set_version="t-v1", state={}, questions={"q1": {"type": "noul", "instructions": "?"}})

    def test_ask_audit_fields_and_usage_compat(self):
        payload = _ok_payload()
        payload["usage"] = {"prompt_tokens": 11, "completion_tokens": 3, "cost": 0.5}
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with mock.patch("common.jev_client.requests.post", return_value=_FakeResponse(payload=payload)):
                result = jc.ask(stage="A2", question_set_version="qs-v9", state={"doc": "x"}, questions={"q1": {"type": "noul", "instructions": "?"}})
        audit = result.audit
        self.assertEqual(audit["stage"], "A2")
        self.assertEqual(audit["question_set_version"], "qs-v9")
        self.assertEqual(audit["requested_model"], _MODEL)
        self.assertEqual(audit["model"], "jev-1.14.0")
        self.assertEqual(audit["endpoint"], _ENDPOINT)
        self.assertGreaterEqual(audit["latency_ms"], 0.0)
        self.assertEqual(audit["batch_count"], 1)
        self.assertEqual(audit["question_count"], 1)
        self.assertGreater(audit["payload_chars"], 0)
        self.assertEqual(
            audit["usage"], {"input_tokens": 11, "output_tokens": 3, "cost": 0.5}
        )
        self.assertEqual(audit, result.audit)
        self.assertIn("answers", result.raw)

    def test_ask_bad_payload_raises(self):
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            # 响应 JSON 非字典
            with mock.patch("common.jev_client.requests.post", return_value=_FakeResponse(payload=[1, 2])):
                with mock.patch("common.jev_client.time.sleep"):
                    with self.assertRaises(jc.JevUnavailable):
                        jc.ask(stage="E1", question_set_version="t-v1", state={}, questions={"q1": {"type": "noul", "instructions": "?"}})
            # 缺少字典型 answers
            with mock.patch("common.jev_client.requests.post", return_value=_FakeResponse(payload={"model": _MODEL})):
                with mock.patch("common.jev_client.time.sleep"):
                    with self.assertRaises(jc.JevUnavailable):
                        jc.ask(stage="E1", question_set_version="t-v1", state={}, questions={"q1": {"type": "noul", "instructions": "?"}})

    def test_ask_apply_anti_injection_off(self):
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with mock.patch("common.jev_client.requests.post", return_value=_FakeResponse(payload=_ok_payload())) as post:
                jc.ask(stage="E1", question_set_version="t-v1", state={}, questions={"q1": {"type": "noul", "instructions": "?"}}, apply_anti_injection=False)
        body = json.loads(post.call_args.kwargs["data"].decode("utf-8"))
        self.assertNotIn(jc.ANTI_INJECTION_SUFFIX, body["questions"]["q1"]["instructions"])


class AskBatchesConcurrentTest(unittest.TestCase):
    @staticmethod
    def _audit(idx):
        return {
            "stage": "A1",
            "question_set_version": "t-v1",
            "requested_model": _MODEL,
            "model": _MODEL,
            "endpoint": _ENDPOINT,
            "latency_ms": 10.0 * (idx + 1),
            "batch_count": 1,
            "question_count": 2,
            "payload_chars": 1000 * (idx + 1),
            "usage": {"input_tokens": 10 * (idx + 1), "output_tokens": idx + 1, "cost": 0.1 * (idx + 1)},
        }

    def test_single_batch_shortcut(self):
        batches = [({"doc": "x"}, {"q1": {"type": "noul", "instructions": "?"}})]
        fake = jc.JevAnswer(answers={"q1": {"noul": 0.5}}, audit=self._audit(0), raw={})
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with mock.patch.object(jc, "ask", return_value=fake) as ask_mock:
                result = jc.ask_batches_concurrent(batches, stage="A1", question_set_version="t-v1")
        ask_mock.assert_called_once()
        self.assertEqual(result.answers, {"q1": {"noul": 0.5}})

    def test_multi_batch_merge_and_aggregate(self):
        batches = [
            ({"doc": "a"}, {"q1": {"type": "noul", "instructions": "?"}, "q2": {"type": "noul", "instructions": "?"}}),
            ({"doc": "b"}, {"q3": {"type": "noul", "instructions": "?"}, "q4": {"type": "noul", "instructions": "?"}}),
            ({"doc": "c"}, {"q5": {"type": "noul", "instructions": "?"}, "q6": {"type": "noul", "instructions": "?"}}),
        ]

        def fake_ask(**kwargs):
            idx = "abc".index(kwargs["state"]["doc"])
            return jc.JevAnswer(
                answers={f"q{2 * idx + 1}": {"noul": 0.1 * (idx + 1)}, f"q{2 * idx + 2}": {"noul": 0.9}},
                audit=self._audit(idx),
                raw={},
            )

        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with mock.patch.object(jc, "ask", side_effect=fake_ask) as ask_mock:
                result = jc.ask_batches_concurrent(batches, stage="A1", question_set_version="t-v1", max_workers=3)
        self.assertEqual(ask_mock.call_count, 3)
        self.assertEqual(set(result.answers), {"q1", "q2", "q3", "q4", "q5", "q6"})
        audit = result.audit
        self.assertEqual(audit["batch_count"], 3)
        self.assertEqual(audit["question_count"], 6)
        self.assertEqual(audit["payload_chars"], 1000 + 2000 + 3000)
        self.assertEqual(audit["usage"]["input_tokens"], 10 + 20 + 30)
        self.assertEqual(audit["usage"]["output_tokens"], 1 + 2 + 3)
        self.assertAlmostEqual(audit["usage"]["cost"], 0.6)
        self.assertAlmostEqual(audit["sum_batch_latency_ms"], 10.0 + 20.0 + 30.0)
        self.assertGreaterEqual(audit["latency_ms"], 0.0)
        self.assertEqual(audit["stage"], "A1")

    def test_duplicate_question_key_raises(self):
        batches = [
            ({"doc": "a"}, {"q1": {"type": "noul", "instructions": "?"}}),
            ({"doc": "b"}, {"q1": {"type": "noul", "instructions": "?"}}),
        ]
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with self.assertRaises(ValueError):
                jc.ask_batches_concurrent(batches, stage="A1", question_set_version="t-v1")

    def test_any_batch_failure_raises_unavailable(self):
        batches = [
            ({"doc": "a"}, {"q1": {"type": "noul", "instructions": "?"}}),
            ({"doc": "b"}, {"q2": {"type": "noul", "instructions": "?"}}),
        ]
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with mock.patch.object(jc, "ask", side_effect=jc.JevUnavailable("boom")):
                with self.assertRaises(jc.JevUnavailable):
                    jc.ask_batches_concurrent(batches, stage="A1", question_set_version="t-v1")

    def test_first_batch_failure_cancels_queued_batches(self):
        batches = [
            ({"doc": f"d{i}"}, {f"q{i}": {"type": "noul", "instructions": "?"}})
            for i in range(10)
        ]
        with mock.patch.dict(os.environ, _ready_env(), clear=True):
            with mock.patch.object(jc, "ask", side_effect=jc.JevUnavailable("boom")) as ask_mock:
                with self.assertRaises(jc.JevUnavailable):
                    jc.ask_batches_concurrent(
                        batches, stage="E2", question_set_version="t-v1", max_workers=1
                    )
        # max_workers=1 下第 1 批抛错后立即 cancel_futures=True，绝不继续串行跑完剩余排队批次。
        self.assertLessEqual(ask_mock.call_count, 2)

    def test_build_degraded_diag(self):
        diag = jc.build_degraded_diag("E2", RuntimeError("timeout"))
        self.assertEqual(diag, {"degraded": True, "stage": "E2", "error": "timeout"})


class QuestionsRegistryTest(unittest.TestCase):
    def test_stage_versions_and_polarized_vs_external_thresholds(self):
        from common import jev_questions as jq

        self.assertEqual(set(jq.QUESTION_SET_VERSIONS), {"E1", "E2", "A1", "A2", "A3"})
        # 内网 Ntele-decision-V1 二值极化刻度
        t_internal = jq.get_stage_thresholds("E1", model="Ntele-decision-V1")
        self.assertEqual(t_internal["direct_ready_min"], 0.95)
        self.assertEqual(jq.get_stage_thresholds("A1", model="Ntele-decision-V1")["drop_in_scope_max"], 0.005)
        # 外网 typesafe/jev-1.14 平滑参考刻度
        t_external = jq.get_stage_thresholds("E1", model="typesafe/jev-1.14")
        self.assertEqual(t_external["direct_ready_min"], 0.80)
        self.assertEqual(jq.get_stage_thresholds("A1", model="jev-1.14.0")["drop_in_scope_max"], 0.08)
        # 返回副本，防原地修改污染全局注册表
        t_internal["direct_ready_min"] = 0.1
        self.assertEqual(jq.E1_THRESHOLDS["direct_ready_min"], 0.95)

    def test_default_channel_never_falls_back_to_external_env(self):
        # 即使环境里同时存在 JEV_EXTERNAL_*，未显式设 COSIGHTBOT_JEV_CHANNEL=external 时绝不读取或回退外网
        env = jev_env(
            COSIGHTBOT_JEV_ENABLED="1",
            JEV_EXTERNAL_ENDPOINTS="https://ext-gw-1.example,https://ext-gw-2.example",
            JEV_EXTERNAL_MODEL="jev-1.14",
            JEV_EXTERNAL_API_KEY=_DUMMY_KEY,
        )
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(jc.load_settings())
            status = jc.config_status()
            self.assertEqual(status["channel"], "internal")
            self.assertEqual(status["state"], "unconfigured")

    def test_explicit_external_channel_aliases_path_proxy_and_thresholds(self):
        from common import jev_questions as jq

        env = jev_env(
            COSIGHTBOT_JEV_ENABLED="1",
            COSIGHTBOT_JEV_CHANNEL="external",
            JEV_EXTERNAL_ENDPOINTS="https://ext-gw-1.example,https://ext-gw-2.example/custom/path",
            JEV_EXTERNAL_MODEL="jev-1.14",
            JEV_EXTERNAL_API_KEY=_DUMMY_KEY,
        )
        with mock.patch.dict(os.environ, env, clear=True):
            settings = jc.require_settings()
            self.assertEqual(settings.channel, "external")
            self.assertEqual(
                settings.endpoints,
                (
                    "https://ext-gw-1.example/api/alpha/decisions",
                    "https://ext-gw-2.example/custom/path",
                ),
            )
            self.assertEqual(jq.get_stage_thresholds("E1")["direct_ready_min"], 0.80)
            with mock.patch("common.jev_client.requests.post", return_value=_FakeResponse(payload=_ok_payload())) as post:
                jc.ask(stage="E1", question_set_version="t-v1", state={}, questions={"q1": {"type": "noul", "instructions": "?"}})
            kwargs = post.call_args.kwargs
            # external 显式模式允许复用系统出网代理（不传 proxies={"http": None, ...}）
            self.assertNotIn("proxies", kwargs)
            self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {_DUMMY_KEY}")


if __name__ == "__main__":
    unittest.main()
