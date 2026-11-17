#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T7 JEV-A3 verify-answer 答案出口双向核验与字面量闸门单测。

覆盖：48 分钟预算零延迟短路、S-04 未读引文拦截与披露区未读声明豁免、
Python 精确子串预筛与 HTML 剥除兼容、正向漏步骤检出（5 步写 4 步）、
反向错误否认检出、跨批 max 聚合防误报、多模态看图豁免、中间带保守不误报、
JEV 关闭 / JevUnavailable 有痕软降级、CLI 端到端与离线回放辅助函数。
全部用例不连真实内网 JEV：概率一律注入或 Mock。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

import common.jev_client as jc  # noqa: E402
import common.jev_verify_answer as jva  # noqa: E402
from common import overview_resolver  # noqa: E402

_JEV_ENV_KEYS = [
    "COSIGHTBOT_JEV_ENABLED",
    "COSIGHTBOT_JEV_STAGES",
    "COSIGHTBOT_JEV_INTERNAL_ENDPOINTS",
    "COSIGHTBOT_JEV_INTERNAL_MODEL",
    "COSIGHTBOT_JEV_INTERNAL_API_KEY",
    "COSIGHTBOT_JEV_TIMEOUT_S",
    "COSIGHTBOT_VERIFY_BUDGET_CAP_S",
]


def clean_env(**overrides) -> dict:
    """清空全部 JEV/预算环境变量后再覆盖，避免宿主环境影响用例。"""
    env = {k: v for k, v in os.environ.items() if k not in _JEV_ENV_KEYS}
    env.update(overrides)
    return env


def _noul(prob: float | None) -> dict:
    if prob is None:
        return {"type": "noul"}
    return {"type": "noul", "noul": prob}


_RUNBOOK_DOC = """# 生产环境恢复演练 Runbook

## 演练背景

本 Runbook 适用于生产环境推理集群的季度恢复演练。

## 恢复演练步骤

以下为恢复演练的完整步骤，必须按序执行：

1. **冻结流量入口**
2. **切换只读模式**
3. **执行数据回放**
4. **校验一致性**
5. **输出演练报告并关闭演练记录**

完成上述步骤后恢复流量入口。
"""

_RUNBOOK_DRAFT = """## 生产环境恢复演练步骤

生产环境恢复演练按以下步骤执行：

1. 冻结流量入口；
2. 切换只读模式；
3. 执行数据回放；
4. 校验一致性。

以上步骤全部完成后演练结束。
"""


class BudgetCapTest(unittest.TestCase):
    """48 分钟预算上限零延迟短路：不读语料、不发起任何 JEV 请求。"""

    def test_default_cap_2880_short_circuits(self) -> None:
        with mock.patch.dict(os.environ, clean_env()):
            with mock.patch.object(jc, "is_stage_enabled", side_effect=AssertionError("不应触达开关")):
                with mock.patch.object(jc, "ask_batches_concurrent", side_effect=AssertionError("不应发起 JEV 请求")):
                    result = jva.verify_answer(
                        question="恢复演练步骤？",
                        draft="[f001] 演练步骤……",
                        read_docs=["f001"],
                        elapsed_seconds=2885.0,
                        doc_texts={"f001": "x"},
                    )
        self.assertEqual(result["action"], "PASS_BUDGET_CAP")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["max_revisions"], 0)
        self.assertIn("2880", result["reason"])

    def test_env_override_cap(self) -> None:
        with mock.patch.dict(os.environ, clean_env(COSIGHTBOT_VERIFY_BUDGET_CAP_S="100")):
            result = jva.verify_answer(
                question="q", draft="d", read_docs=[], elapsed_seconds=101.0
            )
        self.assertEqual(result["action"], "PASS_BUDGET_CAP")
        with mock.patch.dict(os.environ, clean_env(COSIGHTBOT_VERIFY_BUDGET_CAP_S="100")):
            result = jva.verify_answer(
                question="q", draft="d", read_docs=[], elapsed_seconds=99.0, doc_texts={}
            )
        self.assertNotEqual(result["action"], "PASS_BUDGET_CAP")


class S04CitationTest(unittest.TestCase):
    """S-04 未读引文拦截 + 末尾披露区未读声明豁免。"""

    def test_unread_citation_in_main_body_blocks(self) -> None:
        draft = "结论：参考 [f999] 的说明，保留期为 90 天。"
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="保留期是多少？",
                draft=draft,
                read_docs=["f001", "f002"],
                doc_texts={"f001": "文档一内容", "f002": "文档二内容"},
                jev_answers={},
            )
        self.assertEqual(result["action"], "REVISE_ONCE")
        types = {issue["type"] for issue in result["issues"]}
        self.assertIn("UNREAD_CITATION", types)
        citation_issue = next(i for i in result["issues"] if i["type"] == "UNREAD_CITATION")
        self.assertEqual(citation_issue["citation"], "f999")
        self.assertIn("S-04", citation_issue["detail"])

    def test_disclosure_unread_declaration_exempt(self) -> None:
        draft = (
            "结论：保留期为 90 天，依据 [f001]。\n\n"
            "## 披露\n\n- 未选读候选：[f999]（与题面无关）；未读 [f888]（低相关）。\n"
        )
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="保留期是多少？",
                draft=draft,
                read_docs=["f001"],
                doc_texts={"f001": "生产环境 S3 对象保留期为 90 天。"},
                jev_answers={},
            )
        self.assertEqual(result["action"], "PASS")
        self.assertEqual(result["issues"], [])

    def test_inline_disclosure_unread_declaration_with_prefixed_id_exempt(self) -> None:
        draft = (
            "结论：保留期为 90 天，依据 [fadc001]。\n\n"
            "**披露区**：未精读低相关候选 [fadc999] 与 [fadc888]。\n"
        )
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="保留期是多少？",
                draft=draft,
                read_docs=["fadc001"],
                doc_texts={"fadc001": "生产环境 S3 对象保留期为 90 天。"},
                jev_answers={},
            )
        self.assertEqual(result["action"], "PASS")
        self.assertEqual(result["issues"], [])

    def test_disclosure_normal_line_still_checked(self) -> None:
        draft = (
            "结论：保留期为 90 天，依据 [f001]。\n\n"
            "## 披露\n\n- 另见 [f888] 的对比说明。\n"
        )
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="保留期是多少？",
                draft=draft,
                read_docs=["f001"],
                doc_texts={"f001": "生产环境 S3 对象保留期为 90 天。"},
                jev_answers={},
            )
        self.assertEqual(result["action"], "REVISE_ONCE")
        types = {issue["type"] for issue in result["issues"]}
        self.assertIn("UNREAD_CITATION", types)

    def test_citation_case_insensitive_match(self) -> None:
        draft = "结论：依据 [F001]，保留期为 90 天。"
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="保留期是多少？",
                draft=draft,
                read_docs=["f001"],
                doc_texts={"f001": "生产环境 S3 对象保留期为 90 天。"},
                jev_answers={},
            )
        self.assertEqual(result["action"], "PASS")


class LiteralPrefilterTest(unittest.TestCase):
    """Python 精确子串预筛省流 + HTML <span> 剥除兼容。"""

    def test_span_stripped_identifier_passes_stage1(self) -> None:
        doc = "缓存配置：`X-<span>Redwood</span>-Cache-Bypass` 控制旁路行为。"
        draft = "按规范启用 `X-Redwood-Cache-Bypass`。"
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="缓存旁路如何配置？",
                draft=draft,
                read_docs=["f001"],
                doc_texts={"f001": doc},
                jev_answers={},
            )
        self.assertEqual(result["literal_claims"], [])
        self.assertEqual(result["action"], "PASS")

    def test_mis_copied_identifier_enters_stage2_and_triggers(self) -> None:
        doc = "缓存配置：`X-<span>Redwood</span>-Cache-Bypass` 控制旁路行为。"
        draft = "按规范启用 `X-RW-Cache-Mode`。"
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="缓存旁路如何配置？",
                draft=draft,
                read_docs=["f001"],
                doc_texts={"f001": doc},
                jev_answers={"literal_supported_0": 0.001},
            )
        self.assertIn("X-RW-Cache-Mode", result["literal_claims"])
        self.assertEqual(result["action"], "REVISE_ONCE")
        issue = next(i for i in result["issues"] if i["type"] == "UNSUPPORTED_LITERAL")
        self.assertEqual(issue["claim"], "X-RW-Cache-Mode")
        self.assertLessEqual(issue["p_supported"], 0.02)

    def test_exact_match_identifier_never_asked(self) -> None:
        doc = "缓存配置键为 X-Redwood-Cache-Bypass。"
        draft = "配置键 X-Redwood-Cache-Bypass 需显式开启。"
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="配置键是什么？",
                draft=draft,
                read_docs=["f001"],
                doc_texts={"f001": doc},
                jev_answers={"literal_supported_0": 0.0},
            )
        self.assertEqual(result["literal_claims"], [])
        self.assertEqual(result["action"], "PASS")


class MissingPointTest(unittest.TestCase):
    """正向漏点检测：5 步 Runbook 写 4 步 -> 精准抓获第 5 步。"""

    def _verify(self) -> dict:
        jev_answers = {
            "source_has_item_0": 0.99,
            "draft_covers_item_0": 0.99,
        }
        for idx in range(1, 5):
            jev_answers[f"source_has_item_{idx}"] = 0.99
            jev_answers[f"draft_covers_item_{idx}"] = 0.99
        jev_answers["source_has_item_5"] = 0.99
        jev_answers["draft_covers_item_5"] = 0.001
        with mock.patch.dict(os.environ, clean_env()):
            return jva.verify_answer(
                question="生产环境恢复演练的完整步骤有哪些？",
                draft=_RUNBOOK_DRAFT,
                read_docs=["f001"],
                doc_texts={"f001": _RUNBOOK_DOC},
                jev_answers=jev_answers,
            )

    def test_fifth_step_extracted_into_checklist(self) -> None:
        result = self._verify()
        checklist_text = " | ".join(item["text"] for item in result["checklist"])
        self.assertIn("输出演练报告并关闭演练记录", checklist_text)

    def test_missing_point_triggered_with_location(self) -> None:
        result = self._verify()
        self.assertEqual(result["action"], "REVISE_ONCE")
        self.assertEqual(result["max_revisions"], 1)
        missing = [i for i in result["issues"] if i["type"] == "MISSING_POINT"]
        self.assertEqual(len(missing), 1)
        issue = missing[0]
        self.assertIn("演练报告", issue["item"])
        self.assertEqual(issue["doc_id"], "f001")
        self.assertRegex(issue["line_range"] or "", r"^L\d+-L\d+$")
        self.assertGreaterEqual(issue["p_source"], 0.95)
        self.assertLessEqual(issue["p_draft"], 0.02)


class FalseNegationTest(unittest.TestCase):
    """反向错误否认检测：声称"未找到"但原文有明确记录。"""

    _DOC = "生产环境恢复演练频次为每季度 1 次，由 SRE 平台自动调度。"

    def test_false_negation_detected(self) -> None:
        draft = "知识库中未提及生产环境恢复演练频次。"
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="生产环境恢复演练频次是多少？",
                draft=draft,
                read_docs=["f001"],
                doc_texts={"f001": self._DOC},
                jev_answers={"contradicts_not_found_0": 0.985},
            )
        self.assertEqual(result["action"], "REVISE_ONCE")
        issue = next(i for i in result["issues"] if i["type"] == "FALSE_NEGATION")
        self.assertIn("未提及", issue["claim"])
        self.assertGreaterEqual(issue["p_contradicts"], 0.95)

    def test_no_negation_words_zero_questions(self) -> None:
        draft = "生产环境恢复演练频次为每季度 1 次。"
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="生产环境恢复演练频次是多少？",
                draft=draft,
                read_docs=["f001"],
                doc_texts={"f001": self._DOC},
                jev_answers={},
            )
        self.assertEqual(result["negation_claims"], [])
        self.assertEqual(result["action"], "PASS")


class CrossBatchAggregationTest(unittest.TestCase):
    """跨批次聚合防假阳性：任一批次有支持即不误报 UNSUPPORTED_LITERAL。"""

    def _big_doc(self, marker_body: str, filler: str) -> str:
        return f"# 大文档\n\n{marker_body}\n\n{filler}\n"

    def test_supported_in_second_batch_never_false_positive(self) -> None:
        filler = "这是一段与核验判定无关的背景描述文字，用于撑大批次体量。" * 1900
        doc_a = self._big_doc("文档 A 记录网络割接窗口的背景说明。", filler)
        doc_b = self._big_doc("生产环境 S3 对象保留期为 90 天，不得擅自缩短。", filler)
        draft = "生产环境 S3 对象保留期为 90 天，依据已读文档。"
        question = "生产环境 S3 对象的保留期是多少天？"

        captured: dict = {}

        def fake_ask(batches, *, stage, question_set_version, **kwargs):
            captured["batch_count"] = len(batches)
            answers = {}
            for state, questions in batches:
                joined = json.dumps(state, ensure_ascii=False)
                for key in questions:
                    if key.startswith("literal_supported_"):
                        prob = 0.996 if "90 天" in joined else 0.0001
                    else:
                        prob = 0.99
                    answers[key] = _noul(prob)
            return jc.JevAnswer(answers=answers, audit={"stage": stage, "batch_count": len(batches)}, raw={})

        with mock.patch.dict(
            os.environ,
            clean_env(COSIGHTBOT_JEV_ENABLED="1", COSIGHTBOT_JEV_STAGES="A3"),
        ):
            with mock.patch.object(jc, "ask_batches_concurrent", side_effect=fake_ask):
                result = jva.verify_answer(
                    question=question,
                    draft=draft,
                    read_docs=["f001", "f002"],
                    doc_texts={"f001": doc_a, "f002": doc_b},
                )
        self.assertGreaterEqual(captured.get("batch_count", 0), 2)
        self.assertEqual(result["action"], "PASS")
        self.assertFalse(any(i["type"] == "UNSUPPORTED_LITERAL" for i in result["issues"]))


class VisualDocProtectionTest(unittest.TestCase):
    """多模态看图节点（ppt_slide/doc_page/slide/page/image）防误打回保护。"""

    def test_visual_doc_soft_note_instead_of_hard_block(self) -> None:
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="缓存旁路如何配置？",
                draft="按架构图说明启用 `X-Redwood-Cache-Bypass`。",
                read_docs=["f003"],
                read_doc_metas=[{"kind": "ppt_slide", "node_id": "f003"}],
                doc_texts={"f003": "该 PPT 章节正文无该配置键文本。"},
                jev_answers={"literal_supported_0": 0.001},
            )
        self.assertEqual(result["visual_docs"], True)
        self.assertEqual(result["action"], "PASS")
        self.assertTrue(result["visual_check_notes"])
        self.assertFalse(any(i["type"] == "UNSUPPORTED_LITERAL" for i in result["issues"]))

    def test_normalized_resolver_visual_kinds_and_image_relpath(self) -> None:
        for meta in (
            {"kind": "page", "node_id": "f004"},
            {"kind": "slide", "node_id": "f005"},
            {"kind": "image", "node_id": "f006"},
            {"kind": "ppt_slides", "node_id": "f007"},
            {"kind": "main_doc", "image_relpath": "x_pdf_images/p1.png", "node_id": "f008"},
        ):
            with mock.patch.dict(os.environ, clean_env()):
                result = jva.verify_answer(
                    question="图中配置键是什么？",
                    draft="按扫描图启用 `X-Scan-Only-Key`。",
                    read_docs=[meta["node_id"]],
                    read_doc_metas=[meta],
                    doc_texts={meta["node_id"]: "空白 OCR 页"},
                    jev_answers={"literal_supported_0": 0.0005},
                )
            self.assertTrue(result["visual_docs"], msg=str(meta))
            self.assertEqual(result["action"], "PASS", msg=str(meta))

    def test_meta_accounting_filtered_and_disclosure_stripped_from_stage_two_state(self) -> None:
        captured: list[tuple[dict, dict]] = []

        def fake_ask(pairs, *, stage, question_set_version=""):
            captured.extend(pairs)
            answers = {
                name: {"probability": 0.99, "answer": "true"}
                for _, qdict in pairs
                for name in qdict
            }
            return jc.JevResponse(answers=answers, audit={"stage": stage, "batches": len(pairs)})

        big_doc = "\n\n".join(
            f"## 章节 {i}\n保留期规范细则段落 " + ("合规保留策略说明文字 " * 1800)
            for i in range(1, 5)
        )
        draft = (
            "综合已精读的 [f001] 与 [f002] 共 2 篇文档，结论如下：\n"
            "生产环境对象保留期为 90 天 [f001]；学术考核要求每年发表不少于 2 篇论文 [f001]。\n\n"
            "## 披露\n"
            "- 未选读候选：[f099]（草案拟议 180 天，未生效）。\n"
        )
        with mock.patch.dict(
            os.environ, clean_env(COSIGHTBOT_JEV_ENABLED="1", COSIGHTBOT_JEV_STAGES="A3")
        ):
            with mock.patch.object(jc, "ask_batches_concurrent", side_effect=fake_ask):
                result = jva.verify_answer(
                    question="保留期与考核要求分别是什么？",
                    draft=draft,
                    read_docs=["f001", "f002"],
                    doc_texts={"f001": big_doc, "f002": "补充说明"},
                )
        self.assertEqual(result["action"], "PASS")
        # R9/R10 元记账句 "共 2 篇文档" 不进入 literal_claims，而领域断言 "90 天"、"2 篇论文" 正常保留
        self.assertFalse(any("共 2 篇文档" in c for c in result["literal_claims"]))
        self.assertTrue(any("90 天" in c for c in result["literal_claims"]))
        self.assertTrue(any("2 篇论文" in c for c in result["literal_claims"]))
        # 披露区不混入 state.draft_answer，且每批 state + anti-injection questions <= 50K 预算
        self.assertGreaterEqual(len(captured), 2)
        for batch_state, batch_questions in captured:
            self.assertNotIn("草案拟议 180 天", batch_state["draft_answer"])
            payload_chars = len(json.dumps(batch_state, ensure_ascii=False)) + len(
                json.dumps(jc.append_anti_injection(batch_questions), ensure_ascii=False)
            )
            self.assertLessEqual(payload_chars, jva.BATCH_CHAR_BUDGET)


class MiddleBandConservativeTest(unittest.TestCase):
    """内网极化中间带保守不误报：draft_covers=0.15（> 0.02）不触发打回。"""

    def test_middle_band_returns_pass(self) -> None:
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="恢复演练频次是多少？",
                draft="恢复演练频次为每季度 1 次。",
                read_docs=["f001"],
                doc_texts={"f001": "生产环境恢复演练频次为每季度 1 次。"},
                jev_answers={"source_has_item_0": 0.99, "draft_covers_item_0": 0.15},
            )
        self.assertEqual(result["action"], "PASS")
        self.assertEqual(result["issues"], [])


class SoftDegradationTest(unittest.TestCase):
    """JEV 关闭或 JevUnavailable 有痕软降级：阶段一硬检 100% 生效，绝不阻断交卷。"""

    def test_stage_disabled_pass_with_degraded_diag(self) -> None:
        with mock.patch.dict(os.environ, clean_env()):
            with mock.patch.object(jc, "ask_batches_concurrent", side_effect=AssertionError("不应发起请求")):
                result = jva.verify_answer(
                    question="保留期是多少？",
                    draft="结论：依据 [f001]，保留期为 90 天。",
                    read_docs=["f001"],
                    doc_texts={"f001": "生产环境 S3 对象保留期为 90 天。"},
                )
        self.assertEqual(result["action"], "PASS")
        self.assertTrue(result["jev"].get("degraded"))
        self.assertEqual(result["jev"].get("stage"), "A3")

    def test_stage_disabled_unread_citation_still_blocks(self) -> None:
        with mock.patch.dict(os.environ, clean_env()):
            result = jva.verify_answer(
                question="保留期是多少？",
                draft="结论：依据 [f999]，保留期为 90 天。",
                read_docs=["f001"],
                doc_texts={"f001": "生产环境 S3 对象保留期为 90 天。"},
            )
        self.assertEqual(result["action"], "REVISE_ONCE")
        self.assertIn("UNREAD_CITATION", {i["type"] for i in result["issues"]})

    def test_jev_unavailable_degrades_not_blocks(self) -> None:
        with mock.patch.dict(
            os.environ,
            clean_env(COSIGHTBOT_JEV_ENABLED="1", COSIGHTBOT_JEV_STAGES="A3"),
        ):
            with mock.patch.object(
                jc, "ask_batches_concurrent", side_effect=jc.JevUnavailable("all endpoints failed")
            ):
                result = jva.verify_answer(
                    question="恢复演练频次是多少？",
                    draft="结论：依据 [f001]，恢复演练频次为每季度 1 次。",
                    read_docs=["f001"],
                    doc_texts={"f001": "生产环境恢复演练频次为每季度 1 次。"},
                )
        self.assertEqual(result["action"], "PASS")
        self.assertTrue(result["jev"].get("degraded"))
        self.assertIn("all endpoints failed", result["jev"].get("error", ""))


class _EncodedIO(io.StringIO):
    """带 encoding 属性的 stdout 替身（overview_resolver.main 会读 sys.stdout.encoding）。"""

    encoding = "utf-8"


class CliEndToEndTest(unittest.TestCase):
    """CLI 端到端：verify-answer 参数经 overview_resolver.main() 执行后的 JSON 与退码。"""

    def _run_main(self, argv: list[str]) -> tuple[int, str]:
        buf = _EncodedIO()
        with mock.patch.dict(os.environ, clean_env(COSIGHTBOT_HOME=self.tmp.name)):
            with mock.patch.object(sys, "argv", ["overview_resolver.py", "--agent-id", "main", *argv]):
                with redirect_stdout(buf):
                    code = overview_resolver.main()
        return int(code), buf.getvalue()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, text: str) -> str:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_cli_pass_flow_exit_zero(self) -> None:
        q = self._write("q.txt", "保留期是多少？")
        d = self._write("draft.md", "结论：依据 [f001]，保留期为 90 天。")
        code, out = self._run_main(
            [
                "verify-answer",
                "--question-file", q,
                "--draft-file", d,
                "--read-docs", "f001",
                "--elapsed-seconds", "1420",
            ]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["action"], "PASS")

    def test_cli_budget_cap_exit_zero(self) -> None:
        q = self._write("q.txt", "保留期是多少？")
        d = self._write("draft.md", "结论：保留期为 90 天。")
        code, out = self._run_main(
            [
                "verify-answer",
                "--question-file", q,
                "--draft-file", d,
                "--read-docs", "",
                "--elapsed-seconds", "2885",
            ]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["action"], "PASS_BUDGET_CAP")

    def test_cli_missing_draft_file_exit_one(self) -> None:
        q = self._write("q.txt", "保留期是多少？")
        code, out = self._run_main(
            [
                "verify-answer",
                "--question-file", q,
                "--draft-file", str(self.root / "no_such_draft.md"),
                "--read-docs", "f001",
            ]
        )
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)

    def test_run_cli_returns_structured_result(self) -> None:
        q = self._write("q2.txt", "缓存旁路如何配置？")
        d = self._write("draft2.md", "启用 `X-RW-Cache-Mode`。")
        args = argparse.Namespace(
            question_file=q, draft_file=d, read_docs="f001", elapsed_seconds=10.0
        )
        buf = io.StringIO()
        with mock.patch.dict(os.environ, clean_env()):
            with redirect_stdout(buf):
                code = jva.run_cli(args, [])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["ok"])
        self.assertIn("X-RW-Cache-Mode", payload["literal_claims"])


class ReplayHelperTest(unittest.TestCase):
    """evaluate_a3_replay_samples：错题检出率与对题误报率测算。"""

    def test_replay_metrics(self) -> None:
        wrong_sample = {
            "question": "生产环境恢复演练的完整步骤有哪些？",
            "draft": _RUNBOOK_DRAFT,
            "read_docs": ["f001"],
            "doc_texts": {"f001": _RUNBOOK_DOC},
            "jev_answers": {
                "source_has_item_0": 0.99, "draft_covers_item_0": 0.99,
                "source_has_item_1": 0.99, "draft_covers_item_1": 0.99,
                "source_has_item_2": 0.99, "draft_covers_item_2": 0.99,
                "source_has_item_3": 0.99, "draft_covers_item_3": 0.99,
                "source_has_item_4": 0.99, "draft_covers_item_4": 0.99,
                "source_has_item_5": 0.99, "draft_covers_item_5": 0.001,
            },
            "expected_issue_types": ["MISSING_POINT"],
        }
        correct_sample = {
            "question": "保留期是多少？",
            "draft": "结论：依据 [f001]，保留期为 90 天。",
            "read_docs": ["f001"],
            "doc_texts": {"f001": "生产环境 S3 对象保留期为 90 天。"},
            "jev_answers": {},
            "expected_issue_types": [],
        }
        with mock.patch.dict(os.environ, clean_env()):
            metrics = jva.evaluate_a3_replay_samples([wrong_sample, correct_sample])
        self.assertEqual(metrics["total"], 2)
        self.assertEqual(metrics["detected"], 1)
        self.assertEqual(metrics["missed"], 0)
        self.assertEqual(metrics["false_positives"], 0)
        self.assertEqual(metrics["detection_rate"], 1.0)
        self.assertEqual(metrics["false_positive_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
