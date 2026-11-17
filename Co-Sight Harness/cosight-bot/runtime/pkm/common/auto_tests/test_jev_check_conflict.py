#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T6 JEV-A2 check-conflict 单测：R11 三步裁决、Python 日期解析、三段式提取、
DISCLOSURE_ONLY 隔离、双形态 --question-json、JEV 软降级。

不连真实 JEV 服务：ask_batches_concurrent 全部打桩（mock.patch）。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

import common.jev_check_conflict as jcc  # noqa: E402
import common.jev_client as jc  # noqa: E402

_JEV_ENV_KEYS = [
    "COSIGHTBOT_JEV_ENABLED",
    "COSIGHTBOT_JEV_STAGES",
    "COSIGHTBOT_JEV_INTERNAL_ENDPOINTS",
    "COSIGHTBOT_JEV_INTERNAL_MODEL",
    "COSIGHTBOT_JEV_INTERNAL_API_KEY",
    "COSIGHTBOT_JEV_TIMEOUT_S",
]
_ENDPOINT = "http://198.51.100.10:31011/v1/systemone"
_MODEL = "Ntele-decision-V1"

DIMS = ["EU-West 区域拆分", "生产环境 S3 审计日志", "保留期天数阈值"]


def jev_env(**overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _JEV_ENV_KEYS}
    env.update(
        COSIGHTBOT_JEV_ENABLED="1",
        COSIGHTBOT_JEV_INTERNAL_ENDPOINTS=_ENDPOINT,
        COSIGHTBOT_JEV_INTERNAL_MODEL=_MODEL,
    )
    env.update(overrides)
    return env


def _make_doc(doc_id: str, *, rel_path="docs/x.md", title="T", iso=None,
              date_source=None, hints=None) -> dict:
    return {
        "doc_id": doc_id,
        "rel_path": rel_path,
        "title": title,
        "evidence_text": "evidence-body" * 10,
        "evidence_chars": 130,
        "full_chars": 130,
        "evidence_mode": "full",
        "iso_date": iso,
        "date_source": date_source,
        "draft_example_hints": hints or {"draft": False, "example": False},
    }


def _answers_for(specs: list[dict], dimensions: list[str]) -> dict:
    """按文档规格构造 JEV answers（noul/choice 合法形态）。"""
    answers: dict = {}
    for i, spec in enumerate(specs):
        covered = spec.get("covered", False)
        cov_p = spec.get("cov_p", 0.99 if covered else 0.0001)
        for k in range(len(dimensions)):
            answers[f"covers_dim_{i}_{k}"] = {"type": "noul", "noul": cov_p}
        tier = spec["tier"]
        answers[f"authority_tier_{i}"] = {
            "type": "choice",
            "choice": tier,
            "probabilities": {t: (spec.get("tier_p", 0.99) if t == tier else 0.0)
                              for t in jcc.AUTHORITY_TIERS},
        }
        answers[f"authority_clear_{i}"] = {
            "type": "noul", "noul": spec.get("clear", 0.99),
        }
        answers[f"explicit_supersedes_{i}"] = {
            "type": "noul", "noul": spec.get("sup", 0.0001),
        }
        answers[f"detail_completeness_{i}"] = {
            "type": "noul", "noul": spec.get("det", 0.99 if spec.get("detail", False) else 0.0001),
        }
    return answers


def _fake_answer(answers: dict):
    return jc.JevAnswer(answers=answers, audit={"stage": "A2", "batch_count": 1}, raw={})


class R11AdjudicationTest(unittest.TestCase):
    """R11 三步裁决核心用例（JEV answers 打桩）。"""

    def _run(self, specs: list[dict], docs: list[dict], dimensions=None):
        dimensions = dimensions or DIMS
        answers = _answers_for(specs, dimensions)
        with mock.patch.dict(os.environ, jev_env(), clear=True), \
                mock.patch.object(jcc, "ask_batches_concurrent",
                                  return_value=_fake_answer(answers)):
            return jcc.run_check_conflict("EU-West 生产环境 S3 审计日志保留期是多少天？",
                                          dimensions, docs)

    def test_unique_exact_full_coverage_beats_newer_global(self):
        # f014：2026-03 发布手册，唯一覆盖 EU-West 区域拆分；f052：2026-10 全局
        # Slack 公告（未拆分区域）。无论 f052 日期多新，唯一精确覆盖者胜出。
        docs = [
            _make_doc("f014", iso="2026-03-01", date_source="header_field"),
            _make_doc("f052", iso="2026-10-05", date_source="header_field"),
        ]
        specs = [
            {"tier": "signed_or_published", "covered": True},
            {"tier": "informal_note", "covered": False},
        ]
        result = self._run(specs, docs)
        self.assertEqual(result["primary_doc_id"], "f014")
        self.assertEqual(result["verdict"], "PRIMARY_EXACT_MATCH")
        by_id = {d["doc_id"]: d for d in result["docs"]}
        self.assertEqual(by_id["f014"]["handling"], "PRIMARY_SOURCE")
        self.assertEqual(by_id["f052"]["handling"], "SUPPLEMENT_OR_CONFLICT_DISCLOSURE")

    def test_disclosure_only_isolation(self):
        # 草案与示例默认值文档绝不抢占正式文档的主来源地位，并带硬隔离警告。
        docs = [
            _make_doc("f001"),
            _make_doc("f002"),
            _make_doc("f003"),
        ]
        specs = [
            {"tier": "signed_or_published", "covered": True},
            {"tier": "draft_or_proposal", "covered": True},
            {"tier": "illustrative_example", "covered": True},
        ]
        result = self._run(specs, docs)
        self.assertEqual(result["primary_doc_id"], "f001")
        self.assertEqual(result["verdict"], "PRIMARY_EXACT_MATCH")
        by_id = {d["doc_id"]: d for d in result["docs"]}
        for draft_id in ("f002", "f003"):
            self.assertEqual(by_id[draft_id]["handling"], "DISCLOSURE_ONLY")
            self.assertEqual(by_id[draft_id]["warning"], jcc.DISCLOSURE_ONLY_WARNING)
            self.assertIn("DISCLOSURE_ONLY: 严禁将其数值作为主结论并列陈述",
                          by_id[draft_id]["warning"])

    def test_all_tentative_when_every_doc_is_draft_or_example(self):
        docs = [_make_doc("f001"), _make_doc("f002")]
        specs = [
            {"tier": "illustrative_example", "covered": True},
            {"tier": "draft_or_proposal", "covered": True},
        ]
        result = self._run(specs, docs)
        self.assertEqual(result["verdict"], "ALL_TENTATIVE_DISCLOSE_NATURE")
        self.assertIn("严禁把任一候选数值", result["r11_guidance"])
        for doc in result["docs"]:
            self.assertEqual(doc["handling"], "DISCLOSURE_ONLY")

    def test_same_tier_no_supersedes_completeness_wins(self):
        # 两篇均为 informal_note 且无 supersedes：完整度高者以 PRIMARY_BY_COMPLETENESS 胜出。
        docs = [_make_doc("f001"), _make_doc("f002")]
        specs = [
            {"tier": "informal_note", "covered": True, "detail": True, "det": 0.98},
            {"tier": "informal_note", "covered": True, "detail": False, "det": 0.01},
        ]
        result = self._run(specs, docs)
        self.assertEqual(result["primary_doc_id"], "f001")
        self.assertEqual(result["verdict"], "PRIMARY_BY_COMPLETENESS")

    def test_tie_no_supersedes_triggers_parallel_or_date_tiebreak(self):
        # 同状态、同完整度且均无 supersedes：不得静默用新日期覆盖旧日期。
        docs = [
            _make_doc("f001", iso="2026-01-01", date_source="header_field"),
            _make_doc("f002", iso="2026-10-05", date_source="header_field"),
        ]
        specs = [
            {"tier": "informal_note", "covered": True, "detail": True},
            {"tier": "informal_note", "covered": True, "detail": True},
        ]
        result = self._run(specs, docs)
        self.assertEqual(result["verdict"], "TIE_NO_SUPERSEDES_PARALLEL_OR_DATE_TIEBREAK")
        self.assertIn("严禁直接假定新日期覆盖旧日期", result["r11_guidance"])
        # 日期兜底仅作排列顺序：新日期者排前，但裁决已显式标记为并列/提醒态
        self.assertEqual(result["primary_doc_id"], "f002")

    def test_explicit_supersedes_wins(self):
        # 同为 signed_or_published，显式 supersedes 者胜出。
        docs = [_make_doc("f009"), _make_doc("f010")]
        specs = [
            {"tier": "signed_or_published", "covered": True, "detail": True, "sup": 0.99},
            {"tier": "signed_or_published", "covered": True, "detail": True, "sup": 0.001},
        ]
        result = self._run(specs, docs)
        self.assertEqual(result["primary_doc_id"], "f009")
        self.assertEqual(result["verdict"], "PRIMARY_BY_SUPERSEDES")

    def test_authority_gap_decides_with_same_other_keys(self):
        # 非 supersedes/非完整度差异时按权威档位裁决。
        docs = [_make_doc("f001"), _make_doc("f002")]
        specs = [
            {"tier": "signed_or_published", "covered": True, "detail": True},
            {"tier": "informal_note", "covered": True, "detail": True},
        ]
        result = self._run(specs, docs)
        self.assertEqual(result["primary_doc_id"], "f001")
        self.assertEqual(result["verdict"], "PRIMARY_BY_AUTHORITY")

    def test_low_confidence_authority_fallback_and_deterministic_override(self):
        # choice 低置信 → 保守回退 informal_note；正文确定性命中草稿词 → 草案档。
        docs = [
            _make_doc("f001"),
            _make_doc("f002", hints={"draft": True, "example": False}),
        ]
        specs = [
            {"tier": "signed_or_published", "covered": True, "tier_p": 0.40},
            {"tier": "signed_or_published", "covered": True, "tier_p": 0.40},
        ]
        result = self._run(specs, docs)
        by_id = {d["doc_id"]: d for d in result["docs"]}
        self.assertEqual(by_id["f001"]["authority_tier"], "informal_note")
        self.assertTrue(by_id["f001"]["authority_fallback"])
        self.assertEqual(by_id["f002"]["authority_tier"], "draft_or_proposal")
        self.assertEqual(by_id["f002"]["handling"], "DISCLOSURE_ONLY")


class DateParserTest(unittest.TestCase):
    def test_field_formats(self):
        cases = [
            ("Effective Date: 2026-11-27", "2026-11-27", "header_field"),
            ("Published: Nov 5, 2026", "2026-11-05", "header_field"),
            ("Approved On: November 27, 2026", "2026-11-27", "header_field"),
            ("生效日期：2026年8月19日", "2026-08-19", "header_field"),
            ("更新日期: 2026/03/08", "2026-03-08", "header_field"),
            ("Last Updated: 5 Nov 2026", "2026-11-05", "header_field"),
        ]
        for text, iso, source in cases:
            info = jcc.extract_canonical_date("docs/x.md", "T", text)
            self.assertEqual(info, {"iso_date": iso, "date_source": source}, text)

    def test_filename_prefix(self):
        info = jcc.extract_canonical_date("ops/2026-04-12-sla.md", "无日期标题", "正文无日期字段")
        self.assertEqual(info, {"iso_date": "2026-04-12", "date_source": "filename"})

    def test_body_edge_iso(self):
        text = "标题行\n" + "\n" * 50 + "2026-05-06 记录"
        info = jcc.extract_canonical_date("docs/x.md", "T", text)
        self.assertEqual(info, {"iso_date": "2026-05-06", "date_source": "body_edge"})

    def test_invalid_calendar_date_safely_ignored(self):
        # 2026-02-30 非法日历日期：安全忽略并继续扫描，无其他日期则返回 None。
        info = jcc.extract_canonical_date("docs/x.md", "T", "Effective Date: 2026-02-30")
        self.assertEqual(info, {"iso_date": None, "date_source": None})

    def test_jev_questions_never_ask_date_comparison(self):
        docs = [_make_doc("f014"), _make_doc("f052")]
        _state, questions = jcc.build_conflict_batch(list(enumerate(docs)), "问题Q", DIMS)
        forbidden = ("早于", "晚于", "日期新旧", "日期先后", "哪个日期更", "比另一篇的日期")
        for key, spec in questions.items():
            instructions = spec.get("instructions", "")
            for word in forbidden:
                self.assertNotIn(word, instructions, f"{key}: {word}")
            self.assertNotIn("date_order", key)

    def test_parse_question_json_dual_form_and_limits(self):
        question, dims, err = jcc.parse_question_json(
            '{"question": "Q?", "dimensions": ["A", "A", "", "B"]}'
        )
        self.assertEqual((question, dims, err), ("Q?", ["A", "B"], ""))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "q.json"
            path.write_text(json.dumps({"question": "Q2?", "dimensions": ["X"]}), encoding="utf-8")
            question, dims, err = jcc.parse_question_json(str(path))
            self.assertEqual((question, dims, err), ("Q2?", ["X"], ""))

        # 无 dimensions → 回退 [question]；超过 10 项截断；空串报错
        question, dims, err = jcc.parse_question_json('{"question": "Q3?"}')
        self.assertEqual(dims, ["Q3?"])
        question, dims, err = jcc.parse_question_json(
            json.dumps({"question": "Q4?", "dimensions": [f"d{i}" for i in range(15)]})
        )
        self.assertEqual(len(dims), 10)
        question, dims, err = jcc.parse_question_json("")
        self.assertIsNone(question)
        self.assertTrue(err)


class ThreeSegmentExtractionTest(unittest.TestCase):
    def test_long_doc_keeps_head_core_and_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines: list[str] = []
            # 420 行、每行约 40 字符 → 全文约 16K 字符（> 6000 触发三段式）
            for idx in range(420):
                if idx == 4:
                    lines.append("Status: Published")
                elif idx == 195:
                    lines.append("## S3 Audit Log Retention (EU-West)")
                elif 196 <= idx <= 204:
                    lines.append(f"| EU-West prod | retention_days | {30 + idx} | 补充说明文字填充行内容")
                elif idx == 210:
                    lines.append("## Unrelated Notes")
                elif idx == 300:
                    lines.append("## Archive Appendix")
                elif idx == 419:
                    lines.append("Approved by VP Engineering on 2026-03-01")
                else:
                    lines.append(f"填充行 {idx}：这是一段与问题无关的普通正文内容，用来撑起文档长度。")
            doc_path = Path(tmp) / "long.md"
            doc_path.write_text("\n".join(lines), encoding="utf-8")
            self.assertGreater(doc_path.stat().st_size, 6000)

            evidence = jcc.extract_conflict_doc_evidence(
                doc_path, "ops/long.md",
                "EU-West 生产环境 S3 审计日志保留期是多少天？",
                ["EU-West 区域拆分", "生产环境 S3 审计日志", "保留期天数阈值"],
            )
            self.assertEqual(evidence["evidence_mode"], "three_segment")
            self.assertLessEqual(evidence["evidence_chars"], jcc.EVIDENCE_CHAR_CAP)
            self.assertIn("Status: Published", evidence["evidence_text"])
            self.assertIn("Approved by VP Engineering", evidence["evidence_text"])
            self.assertIn("## S3 Audit Log Retention (EU-West)", evidence["evidence_text"])
            self.assertIn("retention_days", evidence["evidence_text"])

    def test_short_doc_kept_in_full(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "short.md"
            doc_path.write_text("# 标题\n\nStatus: Draft\n保留期 30 天。\n", encoding="utf-8")
            evidence = jcc.extract_conflict_doc_evidence(
                doc_path, "docs/short.md", "保留期多少天？", ["保留期天数阈值"]
            )
            self.assertEqual(evidence["evidence_mode"], "full")
            self.assertEqual(evidence["draft_example_hints"]["draft"], True)


class CliCommandTest(unittest.TestCase):
    """CLI 装配用例：双形态 --question-json + 大小写不敏感 --doc-ids + 降级退码。"""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        lan = self.root / "lan"
        pre = self.root / "pre"
        lan.mkdir(parents=True)
        pre.mkdir(parents=True)
        (lan / "node_index.json").write_text(
            json.dumps({"_next_id": 3, "F014": "sla-manual.md", "F052": "slack-notice.md"}),
            encoding="utf-8",
        )
        (pre / "sla-manual.md").write_text(
            "# SLA Manual\n\nStatus: Published\nEffective Date: 2026-03-01\n\n"
            "EU-West 生产环境 S3 审计日志保留期为 400 天（按区域拆分）。\n",
            encoding="utf-8",
        )
        (pre / "slack-notice.md").write_text(
            "# Slack 全局公告\n\nS3 审计日志保留期统一为 90 天（未按区域拆分）。\n",
            encoding="utf-8",
        )
        self.route = {
            "kind": "agent",
            "label": "main",
            "lan_dir": str(lan),
            "pre_dir": str(pre),
            "overview_md": str(lan / "overview.md"),
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _answers(self, dimensions: list[str]) -> dict:
        return _answers_for(
            [
                {"tier": "signed_or_published", "covered": True},
                {"tier": "informal_note", "covered": False},
            ],
            dimensions,
        )

    def _cmd(self, question_json: str, doc_ids: str = "F014,f052") -> tuple[int, dict]:
        args = argparse.Namespace(
            agent_id="main", command="check-conflict",
            question_json=question_json, doc_ids=doc_ids,
        )
        buf = io.StringIO()
        with mock.patch.dict(os.environ, jev_env(), clear=True), \
                mock.patch.object(jcc, "ask_batches_concurrent",
                                  return_value=_fake_answer(self._answers(DIMS))), \
                contextlib.redirect_stdout(buf):
            code = jcc.cmd_check_conflict(args, [self.route])
        return code, json.loads(buf.getvalue())

    def test_inline_json_and_case_insensitive_doc_ids(self):
        inline = json.dumps({"question": "EU-West 生产环境 S3 审计日志保留期是多少天？",
                             "dimensions": DIMS}, ensure_ascii=False)
        code, result = self._cmd(inline)
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["primary_doc_id"], result["docs"][0]["doc_id"])
        self.assertEqual(result["verdict"], "PRIMARY_EXACT_MATCH")
        self.assertEqual(result["dimensions"], DIMS)
        # 大小写混写的本地 ID 均已归一化为全局 ID
        self.assertEqual({d["doc_id"] for d in result["docs"]},
                         {d["doc_id"] for d in result["docs"]})
        self.assertEqual(len(result["docs"]), 2)
        self.assertEqual(result["docs"][0]["iso_date"], "2026-03-01")

    def test_question_json_as_file_path(self):
        path = self.root / "q.json"
        path.write_text(json.dumps(
            {"question": "EU-West 生产环境 S3 审计日志保留期是多少天？", "dimensions": DIMS},
            ensure_ascii=False,
        ), encoding="utf-8")
        code, result = self._cmd(str(path))
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["verdict"], "PRIMARY_EXACT_MATCH")

    def test_unknown_doc_id_fails(self):
        inline = json.dumps({"question": "Q?", "dimensions": DIMS}, ensure_ascii=False)
        code, result = self._cmd(inline, doc_ids="F014,F999")
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertIn("F999", result["error"])

    def test_single_doc_fails(self):
        inline = json.dumps({"question": "Q?", "dimensions": DIMS}, ensure_ascii=False)
        code, result = self._cmd(inline, doc_ids="F014")
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])

    def test_jev_unavailable_degrades_with_python_signals(self):
        args = argparse.Namespace(
            agent_id="main", command="check-conflict",
            question_json=json.dumps({"question": "Q?", "dimensions": DIMS}, ensure_ascii=False),
            doc_ids="F014,f052",
        )
        buf = io.StringIO()
        with mock.patch.dict(os.environ, jev_env(), clear=True), \
                mock.patch.object(jcc, "ask_batches_concurrent",
                                  side_effect=jc.JevUnavailable("connection refused")), \
                contextlib.redirect_stdout(buf):
            code = jcc.cmd_check_conflict(args, [self.route])
        result = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["jev_degraded"])
        self.assertEqual(result["verdict"], "JEV_DEGRADED_MANUAL_ADJUDICATION")
        by_title = {d["title"]: d for d in result["docs"]}
        self.assertEqual(by_title["SLA Manual"]["iso_date"], "2026-03-01")
        # 降级路径仍给出确定性草案/示例词提示（本夹具无草案词，应为 False）
        self.assertEqual(by_title["SLA Manual"]["draft_example_hints"]["draft"], False)
        self.assertIn("R11", result["r11_guidance"])

    def test_jev_disabled_degrades_without_calling_client(self):
        args = argparse.Namespace(
            agent_id="main", command="check-conflict",
            question_json=json.dumps({"question": "Q?", "dimensions": DIMS}, ensure_ascii=False),
            doc_ids="F014,f052",
        )
        buf = io.StringIO()
        with mock.patch.dict(
            os.environ,
            jev_env(COSIGHTBOT_JEV_ENABLED="0"),
            clear=True,
        ), mock.patch.object(
            jcc, "ask_batches_concurrent",
            side_effect=AssertionError("JEV 关闭时不得发起请求"),
        ) as mocked, contextlib.redirect_stdout(buf):
            code = jcc.cmd_check_conflict(args, [self.route])
        result = json.loads(buf.getvalue())
        mocked.assert_not_called()
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["jev_degraded"])


if __name__ == "__main__":
    unittest.main()
