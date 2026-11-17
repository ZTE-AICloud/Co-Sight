#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 文档角色先验（Qwen 小模型实现，T2）单测。

覆盖：中英文静态规则快筛（英文/中文权威词、草稿反例词、登记表快筛）、
弱标题单篇一请求并发分类（请求体关闭思考模式/logprobs、首 token 概率解析、
0.70 置信门槛、登记表 Y/N 概率）、小模型未配置跳过、请求失败软降级不中断构建、
以及 SectionIndex 集成（role_info 落 doc_skeleton 三列且静态命中零小模型请求）。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_RUNTIME = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from watch_dog.file_watcher import doc_role_classifier as drc  # noqa: E402
from watch_dog.file_watcher.section_index import SectionIndex  # noqa: E402

DIM = 1024


class FakeEmbedding:
    def _get_text_embeddings(self, texts):
        return [[0.01 * (i + 1)] * DIM for i in range(len(texts))]


def _sk(sections=None, tables=None):
    return {
        "sections": sections or [],
        "tables": tables or [],
    }


def _table(row_count):
    return {"columns": ["Vendor ID", "Status"], "row_count": row_count}


M1_ENV = {
    "COSIGHTBOT_M1_MODEL": "Qwen-test",
    "OPENAI_BASE_URL": "http://llm.invalid/v1",
    "OPENAI_API_KEY": "dummy-key",
}


def _lp(token, p):
    import math
    return {"token": token, "logprob": math.log(p)}


def _chat_payload(letter="B", p_letter=0.96, registry="N", p_reg=0.02):
    """模拟 chat/completions 响应：首 token 为体裁字母，随后 ' Y'/' N' 为登记表。"""
    other_letter = "G" if letter != "G" else "F"
    return {
        "choices": [{
            "message": {"content": f"{letter} {registry}"},
            "logprobs": {"content": [
                {"token": letter, "logprob": 0.0, "top_logprobs": [
                    _lp(letter, p_letter), _lp(other_letter, round(1.0 - p_letter, 6)),
                ]},
                {"token": f" {registry}", "logprob": 0.0, "top_logprobs": [
                    _lp(" Y", p_reg), _lp(" N", round(1.0 - p_reg, 6)),
                ]},
            ]},
        }],
        "usage": {"prompt_tokens": 500, "completion_tokens": 3},
    }


class StaticRulesTest(unittest.TestCase):
    def test_en_runbook_static_hit(self):
        with mock.patch.object(drc, "_post_chat") as llm_call:
            role = drc.classify_by_static_rules(
                "ops/runbooks/production-incident.md",
                "Production Incident Runbook", _sk(),
            )
        self.assertIsNotNone(role)
        self.assertEqual(role["jev_doc_type"], "runbook_sop")
        self.assertEqual(role["jev_doc_type_conf"], 1.0)
        self.assertEqual(role["source"], "rule")
        self.assertFalse(role["jev_is_registry"])
        llm_call.assert_not_called()

    def test_zh_contingency_plan_static_hit(self):
        role = drc.classify_by_static_rules(
            "研发云/割接/2026-plan.md", "研发云专线割接应急预案.md", _sk()
        )
        self.assertIsNotNone(role)
        self.assertEqual(role["jev_doc_type"], "runbook_sop")
        self.assertEqual(role["jev_doc_type_conf"], 1.0)

    def test_h1_title_also_matched(self):
        # 标题无体裁词，但 H1 章节标题显式声明为应急预案
        sk = _sk(sections=[{"header_path": "1. 强制切换步骤", "level": 1,
                            "title": "应急预案"}])
        role = drc.classify_by_static_rules("ops/x.md", "2026-11-27 bridge.md", sk)
        self.assertIsNotNone(role)
        self.assertEqual(role["jev_doc_type"], "runbook_sop")

    def test_draft_words_never_authoritative(self):
        self.assertIsNone(drc.classify_by_static_rules(
            "policies/draft.md", "Draft RFC: Payment Policy", _sk()))
        self.assertIsNone(drc.classify_by_static_rules(
            "policies/zh.md", "支付管理制度（征求意见稿）.md", _sk()))
        self.assertIsNone(drc.classify_by_static_rules(
            "policies/tpl.md", "审批流程模板.md", _sk()))

    def test_parent_dir_name_never_matched(self):
        # 父目录名含 policy/runbook 绝不触发：只匹配标题与 H1
        self.assertIsNone(drc.classify_by_static_rules(
            "policies/runbooks/2026-11-27 chat.md", "2026-11-27 chat.md", _sk()))

    def test_registry_static_hit_requires_table(self):
        sk_with_table = _sk(tables=[_table(46)])
        role = drc.classify_by_static_rules(
            "procurement/vendors.md", "供应商准入台账.md", sk_with_table)
        self.assertIsNotNone(role)
        self.assertTrue(role["jev_is_registry"])
        self.assertEqual(role["jev_doc_type"], "")
        # 无表格证据时不静态标记（交由小模型看正文判断）
        self.assertIsNone(
            drc.classify_by_static_rules("procurement/vendors.md", "供应商准入台账.md", _sk()))

    def test_weak_title_returns_none(self):
        self.assertIsNone(drc.classify_by_static_rules(
            "ops/handoffs/2026-11-27-mariner.md",
            "2026-11-27 Mariner Health Ops Bridge", _sk()))


class WeakLlmClassificationTest(unittest.TestCase):
    def _items(self, n):
        return [
            {
                "doc_id": f"f{i:03d}",
                "path": f"ops/handoffs/doc-{i}.md",
                "title": f"2026-11-{i:02d} Ops Bridge {i}",
                "h1_h3_outline": ["1. P0 Escalation Thresholds"],
                "first_paragraph": "Mandatory failover steps for prod clusters.",
            }
            for i in range(n)
        ]

    def test_unconfigured_returns_skipped_defaults(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(drc, "_post_chat") as llm_call:
            self.assertFalse(drc.m1_stage_enabled())
            results = drc.classify_weak_docs(self._items(3))
        self.assertEqual(len(results), 3)
        for role in results.values():
            self.assertEqual(role["jev_doc_type"], "")
            self.assertEqual(role["source"], "skipped")
            self.assertFalse(role["jev_is_registry"])
        llm_call.assert_not_called()

    def test_explicit_disable_and_model_required(self):
        env = dict(M1_ENV, COSIGHTBOT_M1_ENABLED="0")
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertIsNone(drc.m1_config())
        env = {k: v for k, v in M1_ENV.items() if k != "COSIGHTBOT_M1_MODEL"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertIsNone(drc.m1_config())

    def test_config_defaults_and_overrides(self):
        with mock.patch.dict("os.environ", M1_ENV, clear=True):
            cfg = drc.m1_config()
        self.assertEqual(cfg["model"], "Qwen-test")
        self.assertEqual(cfg["url"], "http://llm.invalid/v1/chat/completions")
        self.assertEqual(cfg["api_key"], "dummy-key")
        self.assertEqual(cfg["workers"], 8)
        env = dict(M1_ENV, COSIGHTBOT_M1_BASE_URL="http://m1.invalid/v1/",
                   COSIGHTBOT_M1_API_KEY="m1-key", COSIGHTBOT_M1_WORKERS="3")
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = drc.m1_config()
        self.assertEqual(cfg["url"], "http://m1.invalid/v1/chat/completions")
        self.assertEqual(cfg["api_key"], "m1-key")
        self.assertEqual(cfg["workers"], 3)

    def test_request_body_disables_thinking_and_requests_logprobs(self):
        captured = {}

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return _chat_payload()

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.update(url=url, headers=headers, body=json, timeout=timeout)
            return _Resp()

        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc._SESSION, "post", side_effect=fake_post):
            results = drc.classify_weak_docs(self._items(1))
        body = captured["body"]
        self.assertEqual(body["model"], "Qwen-test")
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertTrue(body["logprobs"])
        self.assertEqual(body["temperature"], 0)
        self.assertLessEqual(body["max_tokens"], 8)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer dummy-key")
        user = json.loads(body["messages"][1]["content"])
        self.assertEqual(user["doc_id"], "f000")
        self.assertEqual(results["f000"]["jev_doc_type"], "runbook_sop")

    def test_one_request_per_doc_and_index_mapping(self):
        calls = []

        def fake_post_chat(cfg, item):
            calls.append(item["doc_id"])
            letter = "B" if int(item["doc_id"][1:]) % 2 == 0 else "F"
            return _chat_payload(letter=letter, p_letter=0.96)

        with mock.patch.dict("os.environ", dict(M1_ENV, COSIGHTBOT_M1_WORKERS="4"), clear=True), \
                mock.patch.object(drc, "_post_chat", side_effect=fake_post_chat):
            results = drc.classify_weak_docs(self._items(30))
        self.assertEqual(sorted(calls), [f"f{i:03d}" for i in range(30)])
        self.assertEqual(len(results), 30)
        self.assertEqual(results["f000"]["jev_doc_type"], "runbook_sop")
        self.assertEqual(results["f001"]["jev_doc_type"], "meeting_comm")
        self.assertAlmostEqual(results["f000"]["jev_doc_type_conf"], 0.96, places=3)
        self.assertEqual(results["f000"]["source"], "llm")

    def test_low_confidence_conservative_unknown(self):
        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat",
                                  return_value=_chat_payload(letter="B", p_letter=0.55)):
            results = drc.classify_weak_docs(self._items(2))
        for role in results.values():
            self.assertEqual(role["jev_doc_type"], "unknown")
            self.assertAlmostEqual(role["jev_doc_type_conf"], 0.55, places=3)

    def test_threshold_boundary_accepts_at_070(self):
        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat",
                                  return_value=_chat_payload(letter="A", p_letter=0.70)):
            results = drc.classify_weak_docs(self._items(1))
        self.assertEqual(results["f000"]["jev_doc_type"], "policy_norm")

    def test_model_unknown_letter_h_is_unknown(self):
        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat",
                                  return_value=_chat_payload(letter="H", p_letter=0.95)):
            results = drc.classify_weak_docs(self._items(1))
        self.assertEqual(results["f000"]["jev_doc_type"], "unknown")

    def test_registry_probability_threshold(self):
        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat",
                                  return_value=_chat_payload(letter="G", p_letter=0.92, registry="Y", p_reg=0.71)):
            results = drc.classify_weak_docs(self._items(1))
        self.assertTrue(results["f000"]["jev_is_registry"])
        self.assertEqual(results["f000"]["jev_doc_type"], "other")
        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat",
                                  return_value=_chat_payload(letter="G", p_letter=0.92, registry="N", p_reg=0.38)):
            results = drc.classify_weak_docs(self._items(1))
        self.assertFalse(results["f000"]["jev_is_registry"])

    def test_missing_logprobs_falls_back_to_unknown(self):
        payload = {"choices": [{"message": {"content": "B N"}}]}
        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat", return_value=payload):
            results = drc.classify_weak_docs(self._items(1))
        self.assertEqual(results["f000"]["jev_doc_type"], "unknown")
        self.assertEqual(results["f000"]["jev_doc_type_conf"], 0.0)
        self.assertFalse(results["f000"]["jev_is_registry"])

    def test_failure_degrades_single_doc_without_interrupting(self):
        def fake_post_chat(cfg, item):
            if item["doc_id"] == "f001":
                raise drc.M1LlmUnavailable("gateway down")
            return _chat_payload()

        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat", side_effect=fake_post_chat):
            results = drc.classify_weak_docs(self._items(3))
        self.assertEqual(results["f000"]["source"], "llm")
        self.assertEqual(results["f001"]["source"], "degraded")
        self.assertEqual(results["f001"]["jev_doc_type"], "")
        self.assertEqual(results["f001"]["jev_doc_type_conf"], 0.0)
        self.assertFalse(results["f001"]["jev_is_registry"])
        self.assertEqual(results["f002"]["source"], "llm")

    def test_post_chat_retries_transient_errors_then_raises(self):
        class _Resp:
            status_code = 503

            def raise_for_status(self):
                pass

        cfg = {"model": "m", "url": "http://x/v1/chat/completions", "api_key": "k",
               "workers": 1, "timeout": 1.0}
        with mock.patch.object(drc._SESSION, "post", return_value=_Resp()) as post, \
                mock.patch.object(drc.time, "sleep"):
            with self.assertRaises(drc.M1LlmUnavailable):
                drc._post_chat(cfg, {"doc_id": "x"})
        self.assertEqual(post.call_count, drc.M1_MAX_ATTEMPTS)


class SectionIndexIntegrationTest(unittest.TestCase):
    WEAK_DOC = """2026-11-27 Mariner Health Ops Bridge notes.

Effective 2026-11-27, this document defines the mandatory on-call failover
and rollback steps for Mariner Health dedicated inference clusters.

## 1. P0 Escalation Thresholds

P0 page threshold is 2 minutes.

## 2. Mandatory Failover Steps (Prod)

Follow the runbook order strictly.
"""

    STATIC_DOC = """# 信息安全管理制度

全员必须遵守的信息安全管理制度。

## 1. 访问控制

最小权限原则。
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pre = root / "pre"
        self.lan = root / "lan"
        (self.pre / "ops" / "handoffs").mkdir(parents=True)
        (self.pre / "policies").mkdir(parents=True)
        (self.pre / "ops" / "handoffs" / "2026-11-27-mariner-health-ops-bridge.md") \
            .write_text(self.WEAK_DOC, encoding="utf-8")
        (self.pre / "policies" / "information-security.md") \
            .write_text(self.STATIC_DOC, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_role_info_lands_in_doc_skeleton_columns(self):
        index = SectionIndex(self.lan, embedding=FakeEmbedding())
        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat",
                                  return_value=_chat_payload()) as llm_call:
            summary = index.build_from_pre_dir(self.pre, full_build=True)
        self.assertEqual(summary["docs"], 2)

        # 只有弱标题文档（1 篇）请求小模型，静态命中文档零请求
        self.assertEqual(llm_call.call_count, 1)

        rows = index.doc_table.to_lance().to_table().to_pylist()
        by_key = {r["doc_key"]: r for r in rows}
        weak_key = [k for k in by_key if "mariner" in k][0]
        static_key = [k for k in by_key if "information-security" in k][0]
        self.assertEqual(by_key[weak_key]["jev_doc_type"], "runbook_sop")
        self.assertAlmostEqual(by_key[weak_key]["jev_doc_type_conf"], 0.96, places=4)
        self.assertFalse(by_key[weak_key]["jev_is_registry"])
        # 静态命中文档零小模型请求，conf=1.0
        self.assertEqual(by_key[static_key]["jev_doc_type"], "policy_norm")
        self.assertEqual(by_key[static_key]["jev_doc_type_conf"], 1.0)
        # doc_meta JSON 镜像同键
        meta = json.loads(by_key[static_key]["doc_meta"])
        self.assertEqual(meta["jev_doc_type"], "policy_norm")
        self.assertIn("jev_is_registry", meta)

    def test_registry_static_hit_lands_without_llm(self):
        registry_doc = """# 供应商准入台账

| Vendor ID | Vendor Name | Tier | Status |
|---|---|---|---|
""" + "\n".join(f"| VND-{i:03d} | Vendor {i} | Tier-1 | Active |" for i in range(1, 7)) + "\n"
        (self.pre / "policies" / "vendor-registry.md").write_text(
            registry_doc, encoding="utf-8")
        index = SectionIndex(self.lan, embedding=FakeEmbedding())
        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat") as llm_call:
            index.build_from_pre_dir(
                self.pre, rel_paths=["policies/vendor-registry.md"])
        llm_call.assert_not_called()
        rows = index.doc_table.to_lance().to_table().to_pylist()
        self.assertTrue(rows[0]["jev_is_registry"])

    def test_llm_down_build_still_succeeds(self):
        index = SectionIndex(self.lan, embedding=FakeEmbedding())
        with mock.patch.dict("os.environ", M1_ENV, clear=True), \
                mock.patch.object(drc, "_post_chat",
                                  side_effect=drc.M1LlmUnavailable("down")):
            summary = index.build_from_pre_dir(self.pre, full_build=True)
        self.assertEqual(summary["docs"], 2)
        self.assertEqual(summary["failed"], 0)
        rows = index.doc_table.to_lance().to_table().to_pylist()
        by_key = {r["doc_key"]: r for r in rows}
        weak_key = [k for k in by_key if "mariner" in k][0]
        static_key = [k for k in by_key if "information-security" in k][0]
        # 弱标题文档小模型降级落默认空标签；静态命中文档不受影响
        self.assertEqual(by_key[weak_key]["jev_doc_type"], "")
        self.assertEqual(by_key[weak_key]["jev_doc_type_conf"], 0.0)
        self.assertFalse(by_key[weak_key]["jev_is_registry"])
        self.assertEqual(by_key[static_key]["jev_doc_type"], "policy_norm")

    def test_single_upsert_uses_static_rules_without_llm(self):
        index = SectionIndex(self.lan, embedding=FakeEmbedding())
        summary = index.upsert_document(
            self.pre / "policies" / "information-security.md",
            "policies/information-security.md",
        )
        self.assertGreaterEqual(summary["sections"], 1)
        index.commit()
        rows = index.doc_table.to_lance().to_table().to_pylist()
        self.assertEqual(rows[0]["jev_doc_type"], "policy_norm")
        self.assertEqual(rows[0]["jev_doc_type_conf"], 1.0)


if __name__ == "__main__":
    unittest.main()
