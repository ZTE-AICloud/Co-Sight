#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T5 / JEV-A1 filter-hits 单测。

覆盖：多形态 --scan-json 解析与去重、截断扫描告警、小节整段回溯与表格表头
补齐、三桶极化阈值分流、草稿混合保护、全灭异常安全阀、55K 预算自动拆批、
JEV 关闭/JevUnavailable 软降级、CLI 端到端调用（main() 分发 + 参数校验）。
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
import common.jev_filter_hits as jfh  # noqa: E402
import common.overview_resolver as ovr  # noqa: E402

_JEV_ENV_KEYS = [
    "COSIGHTBOT_JEV_ENABLED",
    "COSIGHTBOT_JEV_STAGES",
    "COSIGHTBOT_JEV_INTERNAL_ENDPOINTS",
    "COSIGHTBOT_JEV_INTERNAL_MODEL",
    "COSIGHTBOT_JEV_INTERNAL_API_KEY",
    "COSIGHTBOT_JEV_TIMEOUT_S",
]


def jev_env(**overrides) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _JEV_ENV_KEYS}
    env.update(overrides)
    return env


def _hit(node_id, rel_path, snippets, route_label="agent:demo", term_hits=None):
    return {
        "node_id": node_id,
        "route_label": route_label,
        "rel_path": rel_path,
        "term_hits": term_hits or {"vendor": 1},
        "snippets": snippets,
    }


def _snippet(line_no, text, term="vendor"):
    return {"term": term, "line_no": line_no, "text": text}


def _item(idx, node_id="f0001", text="body"):
    return {
        "idx": idx,
        "node_id": node_id,
        "rel_path": f"docs/doc{idx}.md",
        "header_path": "H1",
        "section_line_range": "1:10",
        "section_text": text,
        "context_source": "section",
    }


def _answers_for(probs: dict) -> dict:
    """把 {idx: (p_in, p_draft)} 组装成 JEV answers 形态。"""
    answers = {}
    for idx, (p_in, p_draft) in probs.items():
        if p_in is None:
            answers[f"in_scope_{idx}"] = {"type": "noul"}
        else:
            answers[f"in_scope_{idx}"] = {"type": "noul", "noul": p_in}
        if p_draft is None:
            answers[f"is_draft_or_template_{idx}"] = {"type": "noul"}
        else:
            answers[f"is_draft_or_template_{idx}"] = {"type": "noul", "noul": p_draft}
    return answers


class _TmpRoutes:
    """构造带 node_index.json 的假 route 与 pre-processed 文档。"""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        lan = self.root / "lancedb" / "demo"
        pre = self.root / "pre" / "demo"
        lan.mkdir(parents=True)
        pre.mkdir(parents=True)
        self.lan_dir = lan
        self.pre_dir = pre
        self.route = {
            "kind": "agent",
            "label": "agent:demo",
            "lan_dir": str(lan),
            "pre_dir": str(pre),
            "overview_md": str(lan / "overview.md"),
        }

    def write_node_index(self, mapping: dict) -> None:
        payload = {"_next_id": len(mapping) + 1}
        payload.update(mapping)
        (self.lan_dir / "node_index.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def write_doc(self, rel_path: str, text: str) -> Path:
        path = self.pre_dir / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def cleanup(self) -> None:
        self.tmp.cleanup()


class LoadScanHitsTest(unittest.TestCase):
    def _write(self, tmp: _TmpRoutes, name: str, text: str) -> Path:
        path = tmp.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_single_page_and_dedup_across_terms(self):
        tmp = _TmpRoutes()
        try:
            page = {
                "ok": True, "truncated": False, "hits_remaining": 0,
                "hits": [
                    _hit("f001", "a.md", [_snippet(10, "line10", "vendor")], term_hits={"vendor": 2}),
                    _hit("f001", "a.md", [_snippet(10, "line10", "vendor"), _snippet(22, "line22", "active")], term_hits={"active": 1}),
                    _hit("f002", "b.md", [_snippet(3, "line3", "vendor")]),
                ],
            }
            hits, warn = jfh.load_scan_hits(self._write(tmp, "scan.json", json.dumps(page)))
            self.assertFalse(warn)
            self.assertEqual(len(hits), 2)
            first = hits[0]
            self.assertEqual(first["node_id"], "f001")
            # 同一文档跨词/跨页命中合并且按行号排序去重
            self.assertEqual([s["line_no"] for s in first["snippets"]], [10, 22])
            self.assertEqual(first["term_hits"], {"vendor": 2, "active": 1})
        finally:
            tmp.cleanup()

    def test_multipage_array_merges_and_keeps_order(self):
        tmp = _TmpRoutes()
        try:
            pages = [
                {"ok": True, "truncated": False, "hits": [_hit("f001", "a.md", [_snippet(5, "l5")])]},
                {"ok": True, "truncated": False, "hits": [_hit("f001", "a.md", [_snippet(30, "l30")]), _hit("f002", "b.md", [_snippet(1, "l1")])]},
            ]
            hits, warn = jfh.load_scan_hits(self._write(tmp, "scan.json", json.dumps(pages)))
            self.assertFalse(warn)
            self.assertEqual([h["node_id"] for h in hits], ["f001", "f002"])
            self.assertEqual([s["line_no"] for s in hits[0]["snippets"]], [5, 30])
        finally:
            tmp.cleanup()

    def test_jsonl_and_plain_hits_array(self):
        tmp = _TmpRoutes()
        try:
            lines = [
                json.dumps({"ok": True, "truncated": False, "hits": [_hit("f001", "a.md", [_snippet(2, "l2")])]}),
                json.dumps({"ok": True, "truncated": False, "hits": [_hit("f002", "b.md", [_snippet(8, "l8")])]}),
            ]
            hits, warn = jfh.load_scan_hits(self._write(tmp, "scan.jsonl", "\n".join(lines)))
            self.assertFalse(warn)
            self.assertEqual([h["node_id"] for h in hits], ["f001", "f002"])

            plain = [_hit("f042", "c.md", [_snippet(9, "l9")])]
            hits2, warn2 = jfh.load_scan_hits(self._write(tmp, "hits.json", json.dumps(plain)))
            self.assertFalse(warn2)
            self.assertEqual([h["node_id"] for h in hits2], ["f042"])
        finally:
            tmp.cleanup()

    def test_truncated_warning_on_last_page(self):
        tmp = _TmpRoutes()
        try:
            pages = [
                {"ok": True, "truncated": True, "hits_remaining": 12, "hits": [_hit("f001", "a.md", [_snippet(1, "l1")])]},
            ]
            hits, warn = jfh.load_scan_hits(self._write(tmp, "scan.json", json.dumps(pages)))
            self.assertTrue(warn)
            self.assertEqual(len(hits), 1)
            # hits_remaining > 0 同样触发告警
            pages2 = [{"ok": True, "truncated": False, "hits_remaining": 3, "hits": []}]
            _hits2, warn2 = jfh.load_scan_hits(self._write(tmp, "scan2.json", json.dumps(pages2)))
            self.assertTrue(warn2)
        finally:
            tmp.cleanup()

    def test_invalid_inputs_raise(self):
        tmp = _TmpRoutes()
        try:
            with self.assertRaises(ValueError):
                jfh.load_scan_hits(self._write(tmp, "bad.json", json.dumps({"ok": True, "error": "x"})))
            with self.assertRaises(ValueError):
                jfh.load_scan_hits(self._write(tmp, "bad2.json", "{not json"))
        finally:
            tmp.cleanup()


class ExpandSectionContextTest(unittest.TestCase):
    def _vendor_ledger(self) -> str:
        lines = ["# Vendor Master Table", "", "Intro paragraph about vendors.", ""]
        lines.append("| ID | Name | Tier | Status |")
        lines.append("|---|---|---|---|")
        for i in range(7, 121):
            lines.append(f"| VND-{i:03d} | Vendor-{i} | Tier-1 | Active |")
        return "\n".join(lines) + "\n"

    def test_small_section_kept_full(self):
        tmp = _TmpRoutes()
        try:
            body = "# Section A\n\n" + ("Detail line about vendor quota.\n" * 10)
            tmp.write_doc("docs/small.md", body)
            tmp.write_node_index({"F001": "docs/small.md"})
            index, _ = ovr._build_global_node_index([tmp.route])
            hit = _hit("f001", "docs/small.md", [_snippet(5, "Detail line")])
            ctx = jfh.expand_hit_section_context(hit, [tmp.route], index)
            self.assertEqual(ctx["context_source"], "section")
            self.assertEqual(ctx["section_line_range"], f"1:{len(body.splitlines())}")
            self.assertEqual(ctx["header_path"], "Section A")
            self.assertIn("Detail line about vendor quota.", ctx["section_text"])
            self.assertLessEqual(len(ctx["section_text"]), jfh.SECTION_CHAR_CAP)
        finally:
            tmp.cleanup()

    def test_long_section_table_header_prefixed(self):
        tmp = _TmpRoutes()
        try:
            doc = self._vendor_ledger()
            tmp.write_doc("procurement/vendors.md", doc)
            tmp.write_node_index({"F001": "procurement/vendors.md"})
            index, _ = ovr._build_global_node_index([tmp.route])
            hit = _hit("f001", "procurement/vendors.md", [_snippet(95, "| VND-095 |")])
            ctx = jfh.expand_hit_section_context(hit, [tmp.route], index)
            self.assertEqual(ctx["context_source"], "section")
            self.assertLessEqual(len(ctx["section_text"]), jfh.SECTION_CHAR_CAP)
            # 表头两行被前置固定在摘录块顶部，且命中行保留
            self.assertIn("| ID | Name | Tier | Status |", ctx["section_text"])
            self.assertIn("|---|---|---|---|", ctx["section_text"])
            self.assertIn("| VND-095 | Vendor-95 | Tier-1 | Active |", ctx["section_text"])
            self.assertIn("[章节路径: Vendor Master Table]", ctx["section_text"])
            # 行号区间必须数值上覆盖命中行 95，便于后续 read-doc --line-range 精读
            lo, hi = (int(x) for x in ctx["section_line_range"].split(":"))
            self.assertLessEqual(lo, 95)
            self.assertGreaterEqual(hi, 95)
        finally:
            tmp.cleanup()

    def test_snippet_fallback_when_file_missing(self):
        tmp = _TmpRoutes()
        try:
            index, _ = ovr._build_global_node_index([tmp.route])
            hit = _hit(None, "ghost/missing.md", [_snippet(4, "ghost line text")])
            ctx = jfh.expand_hit_section_context(hit, [tmp.route], index)
            self.assertEqual(ctx["context_source"], "snippet_fallback")
            self.assertIn("ghost line text", ctx["section_text"])
            self.assertEqual(ctx["section_line_range"], "4:4")
        finally:
            tmp.cleanup()

    def test_two_non_overlapping_sections(self):
        tmp = _TmpRoutes()
        try:
            body = (
                "# Alpha\n\n" + ("alpha vendor line.\n" * 40)
                + "# Beta\n\n" + ("beta vendor line.\n" * 40)
            )
            tmp.write_doc("docs/two.md", body)
            tmp.write_node_index({"F001": "docs/two.md"})
            index, _ = ovr._build_global_node_index([tmp.route])
            hit = _hit("f001", "docs/two.md", [_snippet(5, "alpha vendor"), _snippet(50, "beta vendor")])
            ctx = jfh.expand_hit_section_context(hit, [tmp.route], index)
            self.assertEqual(ctx["context_source"], "section")
            self.assertLessEqual(len(ctx["section_text"]), jfh.SECTION_CHAR_CAP)
            self.assertIn("[章节路径: Alpha]", ctx["section_text"])
            self.assertIn("[章节路径: Beta]", ctx["section_text"])
            self.assertIn("alpha vendor line.", ctx["section_text"])
            self.assertIn("beta vendor line.", ctx["section_text"])
        finally:
            tmp.cleanup()


class RouteBucketsTest(unittest.TestCase):
    def test_polarized_routing(self):
        items = [_item(i, f"f{i:04d}") for i in range(4)]
        answers = _answers_for({0: (0.995, 0.001), 1: (0.25, 0.01), 2: (0.0002, 0.0), 3: (None, None)})
        confirmed, grey, dropped = jfh.route_buckets(items, answers)
        self.assertEqual([r["node_id"] for r in confirmed], ["f0000"])
        self.assertEqual([r["p_in_scope"] for r in confirmed], [0.995])
        self.assertEqual([r["node_id"] for r in dropped], ["f0002"])
        grey_ids = [r["node_id"] for r in grey]
        self.assertEqual(sorted(grey_ids), ["f0001", "f0003"])
        self.assertTrue(all(r["grey_reason"] == "uncertain_band" for r in grey))

    def test_draft_mixed_protection(self):
        items = [_item(0, "f0001"), _item(1, "f0002")]
        answers = _answers_for({0: (0.99, 0.97), 1: (0.99, 0.10)})
        confirmed, grey, dropped = jfh.route_buckets(items, answers)
        # 高相关但疑似草稿/作废：绝不静默丢进 dropped，而是交 grey 实读确认
        self.assertEqual([r["node_id"] for r in confirmed], ["f0002"])
        self.assertEqual([r["node_id"] for r in grey], ["f0001"])
        self.assertEqual(grey[0]["grey_reason"], "suspected_draft_or_superseded")
        self.assertEqual(dropped, [])


class SafetyValveAndBatchingTest(unittest.TestCase):
    def test_all_dropped_safety_valve(self):
        items = [_item(i, f"f{i:04d}") for i in range(12)]
        answers = _answers_for({i: (0.0001, 0.0) for i in range(12)})
        confirmed, grey, dropped = jfh.route_buckets(items, answers)
        self.assertEqual(len(confirmed), 0)
        self.assertEqual(len(grey), 0)
        confirmed2, grey2, dropped2, warned = jfh.apply_all_dropped_safety_valve(
            confirmed, grey, dropped
        )
        self.assertTrue(warned)
        self.assertEqual(len(grey2), 5)
        self.assertTrue(all(r["grey_reason"] == "all_dropped_safety_guard" for r in grey2))
        self.assertEqual(len(dropped2), 7)
        # 抽回的是 p_in 最高的前 5 条（此处同为 0.0001，按原顺序取前 5）
        self.assertEqual([r["node_id"] for r in grey2], [f"f{i:04d}" for i in range(5)])

    def test_budget_batching_60_items(self):
        items = [_item(i, f"f{i:04d}", text="x" * 1100) for i in range(60)]
        base_state = {"question": "q", "include_rule": "r", "exclude_rule": "e"}
        batches = jfh._plan_item_batches(items, base_state)
        self.assertGreater(len(batches), 2)
        seen: list[int] = []
        all_keys: list[str] = []
        for batch in batches:
            self.assertLessEqual(len(batch), jfh.MAX_ITEMS_PER_BATCH)
            state, questions = jfh._build_batch_pair(batch, base_state)
            payload_len = len(json.dumps({"state": state, "questions": questions}, ensure_ascii=False))
            self.assertLessEqual(payload_len, jfh.PAYLOAD_CHAR_BUDGET)
            self.assertEqual([it["idx"] for it in state["items"]], [it["idx"] for it in batch])
            for pos, it in enumerate(batch):
                idx = it["idx"]
                self.assertIn(f"`items[{pos}]`", questions[f"in_scope_{idx}"]["instructions"])
                self.assertIn(f"`items[{pos}]`", questions[f"is_draft_or_template_{idx}"]["instructions"])
            seen.extend(it["idx"] for it in batch)
            all_keys.extend(questions.keys())
        # 完整对齐原始索引：不丢不重
        self.assertEqual(sorted(seen), list(range(60)))
        self.assertEqual(len(all_keys), len(set(all_keys)))
        self.assertEqual(len(all_keys), 120)

    def test_single_oversized_item_gets_own_batch(self):
        items = [_item(0, text="y" * 60000), _item(1, text="small")]
        batches = jfh._split_by_count(
            jc.plan_batches(items, budget_chars=jfh.PAYLOAD_CHAR_BUDGET,
                            per_item_chars=jfh._item_payload_chars),
            jfh.MAX_ITEMS_PER_BATCH,
        )
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(batches[0]), 1)
        self.assertEqual(batches[0][0]["idx"], 0)
        self.assertEqual(batches[1][0]["idx"], 1)


class SoftDegradeTest(unittest.TestCase):
    def _run_cmd(self, tmp: _TmpRoutes, scan_file: Path):
        args = argparse.Namespace(
            question="列出所有 active 的 Tier-1 供应商",
            include_rule="Tier-1 且 active 的正式供应商记录",
            exclude_rule="",
            scan_json=str(scan_file),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = jfh.cmd_filter_hits(args, [tmp.route])
        return code, json.loads(buf.getvalue())

    def test_stage_disabled_soft_degrade(self):
        tmp = _TmpRoutes()
        try:
            tmp.write_doc("docs/a.md", "# T\nvendor line\n")
            tmp.write_node_index({"F001": "docs/a.md"})
            scan = tmp.root / "scan.json"
            scan.write_text(json.dumps({
                "ok": True, "truncated": False,
                "hits": [_hit("f001", "docs/a.md", [_snippet(2, "vendor line")])],
            }), encoding="utf-8")
            env = jev_env()  # 全部 JEV 变量清空 -> A1 关闭
            with mock.patch.dict(os.environ, env, clear=True):
                code, result = self._run_cmd(tmp, scan)
            self.assertEqual(code, 0)
            self.assertTrue(result["ok"])
            self.assertTrue(result["jev_degraded"])
            self.assertEqual(result["total_input_docs"], 1)
            self.assertEqual(result["grey_count"], 1)
            self.assertEqual(result["grey_docs"][0]["grey_reason"], "jev_degraded")
            self.assertEqual(result["confirmed_count"], 0)
            self.assertEqual(result["dropped_noise_count"], 0)
        finally:
            tmp.cleanup()

    def test_jev_unavailable_soft_degrade(self):
        tmp = _TmpRoutes()
        try:
            tmp.write_doc("docs/a.md", "# T\nvendor line\n")
            tmp.write_node_index({"F001": "docs/a.md"})
            scan = tmp.root / "scan.json"
            scan.write_text(json.dumps({
                "ok": True, "truncated": False,
                "hits": [_hit("f001", "docs/a.md", [_snippet(2, "vendor line")])],
            }), encoding="utf-8")
            env = jev_env(
                COSIGHTBOT_JEV_ENABLED="1",
                COSIGHTBOT_JEV_INTERNAL_ENDPOINTS="http://127.0.0.1:1/v1/systemone",
                COSIGHTBOT_JEV_INTERNAL_MODEL="Ntele-decision-V1",
            )
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(
                     jfh.jev_client, "ask_batches_concurrent",
                     side_effect=jc.JevUnavailable("all endpoints failed"),
                 ):
                code, result = self._run_cmd(tmp, scan)
            self.assertEqual(code, 0)
            self.assertTrue(result["ok"])
            self.assertTrue(result["jev_degraded"])
            self.assertEqual(result["grey_count"], 1)
            self.assertEqual(result["grey_docs"][0]["grey_reason"], "jev_degraded")
            self.assertTrue(result["audit"]["jev"]["degraded"])
        finally:
            tmp.cleanup()


class CliEndToEndTest(unittest.TestCase):
    """通过 overview_resolver.main() 参数注入调用 filter-hits 的端到端验证。"""

    class _Stdout(io.StringIO):
        encoding = "utf-8"

    def _run_main(self, argv: list[str], route_env: dict):
        tmp = _TmpRoutes()
        try:
            route = tmp.route
            with mock.patch.dict(os.environ, route_env, clear=True), \
                 mock.patch.object(ovr, "collect_routes", return_value=[route]), \
                 mock.patch.object(ovr, "check_route_ready", side_effect=lambda r: dict(r, ready=True)), \
                 mock.patch.object(sys, "argv", ["overview_resolver.py", "--agent-id", "main"] + argv), \
                 redirect_stdout(self._Stdout()) as buf:
                code = ovr.main()
            return code, buf.getvalue()
        finally:
            tmp.cleanup()

    def test_main_dispatch_ok_and_degraded(self):
        tmp = _TmpRoutes()
        try:
            tmp.write_doc("docs/a.md", "# T\nvendor line\n")
            tmp.write_node_index({"F001": "docs/a.md"})
            scan = tmp.root / "scan.json"
            scan.write_text(json.dumps({
                "ok": True, "truncated": False,
                "hits": [_hit("f001", "docs/a.md", [_snippet(2, "vendor line")])],
            }), encoding="utf-8")
            env = jev_env()  # A1 关闭 -> 软降级但退出码 0
            argv = [
                "filter-hits",
                "--question", "列出所有 active 的 Tier-1 供应商",
                "--include-rule", "Tier-1 且 active 的正式供应商记录",
                "--exclude-rule", "",
                "--scan-json", str(scan),
            ]
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(ovr, "collect_routes", return_value=[tmp.route]), \
                 mock.patch.object(ovr, "check_route_ready", side_effect=lambda r: dict(r, ready=True)), \
                 mock.patch.object(sys, "argv", ["overview_resolver.py", "--agent-id", "main"] + argv), \
                 redirect_stdout(self._Stdout()) as buf:
                code = ovr.main()
            result = json.loads(buf.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(result["ok"])
            self.assertTrue(result["jev_degraded"])
            self.assertEqual(result["total_input_docs"], 1)
            self.assertIn("next_step_hint", result)
        finally:
            tmp.cleanup()

    def test_main_dispatch_invalid_params_exit_1(self):
        env = jev_env()
        code, out = self._run_main(
            ["filter-hits", "--question", "q", "--include-rule", "", "--scan-json", "/nonexistent/scan.json"],
            env,
        )
        result = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_main_dispatch_missing_question_exit_1(self):
        tmp = _TmpRoutes()
        try:
            scan = tmp.root / "scan.json"
            scan.write_text(json.dumps({"ok": True, "truncated": False, "hits": []}), encoding="utf-8")
            env = jev_env()
            with mock.patch.dict(os.environ, env, clear=True), \
                 mock.patch.object(ovr, "collect_routes", return_value=[tmp.route]), \
                 mock.patch.object(ovr, "check_route_ready", side_effect=lambda r: dict(r, ready=True)), \
                 mock.patch.object(sys, "argv", [
                     "overview_resolver.py", "--agent-id", "main", "filter-hits",
                     "--include-rule", "r", "--scan-json", str(scan),
                 ]), \
                 redirect_stdout(self._Stdout()) as buf:
                code = ovr.main()
            result = json.loads(buf.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(result["ok"])
            self.assertIn("--question", result["error"])
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
