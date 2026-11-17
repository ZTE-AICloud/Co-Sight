#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-authority 三源合一权威提取（T2）单测。

覆盖：原 15 个英文词向后兼容、中文权威词命中与目录名不误报、行尾
[权威角色:...] 徽标解析（title 不含徽标尾巴）、doc_skeleton 标量列兜底
（jev_doc_type 权威体裁 / jev_is_registry 登记）、★ 优先精读建议行解析、
返回 JSON 向后兼容、空输入行为，以及 cmd_check_authority 端到端
（真实 lancedb doc_skeleton 表批量查询 + 静默降级）。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))

import lancedb  # noqa: E402
import pyarrow as pa  # noqa: E402

import common.overview_resolver as orr  # noqa: E402
from common.authority_extractor import (  # noqa: E402
    AUTHORITY_TERMS,
    AUTHORITY_TERMS_EN,
    ROLE_DISPLAY_NAMES,
    extract_authority_candidates,
    parse_overview_docs,
)


def _tier1(gid, title, score="0.612", hits=4, badge=""):
    suffix = f" {badge}" if badge else ""
    return f"│   ├── [{gid}] {title}  (命中 {hits} 处 | 综合分: {score}){suffix}"


def _tier2(gid, title, score="0.500", badge=""):
    suffix = f" {badge}" if badge else ""
    return f"- [{gid}] {title} (score={score}000) {suffix}".rstrip()


OVERVIEW_TEXT = "\n".join([
    "## ★ 优先精读建议（综合实体吻合度、限定条件与权威/台账角色生成）",
    "- [f042] 2026-11-27 Mariner Health Ops Bridge  [实体吻合:高 | 限定:2档 | 权威角色:运维规程SOP]",
    "",
    "## 一、Tier 1 候选池（共 85 篇）",
    "├── [DIR] ops/handoffs/",
    _tier1("f042", "2026-11-27 Mariner Health Ops Bridge", badge="[权威角色:运维规程SOP]"),
    _tier1("f010", "信息安全管理制度", score="0.480"),
    _tier1("f043", "Weekly Sync Notes", score="0.300"),
    "├── [DIR] procurement/",
    _tier1("f087", "2026 Q4 Tier-1 Vendors", score="0.540"),
    "## 二、Tier 2 候选池",
    _tier2("f020", "核心网割接操作规程", score="0.42"),
    _tier2("f043", "Weekly Sync Notes", score="0.11"),
])


class BackwardCompatTest(unittest.TestCase):
    def test_original_15_en_terms_preserved(self):
        self.assertEqual(
            AUTHORITY_TERMS[:len(AUTHORITY_TERMS_EN)], AUTHORITY_TERMS_EN)
        text = "\n".join([
            _tier1("f001", "Production Incident Runbook"),
            _tier1("f002", "Final Terms and Approval Decision (SLA)"),
            _tier1("f003", "Experiment Lab Acceptance PRD"),
        ])
        result = extract_authority_candidates(text)
        self.assertTrue(result["ok"])
        by_id = {c["node_id"]: c for c in result["authority_candidates"]}
        self.assertIn("runbook", by_id["f001"]["matched_terms"])
        self.assertIn("final", by_id["f002"]["matched_terms"])
        self.assertIn("experiment lab", by_id["f003"]["matched_terms"])
        # JSON 向后兼容：原键全保留，terms 含原 15 词
        for key in ("ok", "authority_total", "authority_candidates", "terms", "hint"):
            self.assertIn(key, result)
        for term in AUTHORITY_TERMS_EN:
            self.assertIn(term, result["terms"])

    def test_entry_original_keys_preserved(self):
        result = extract_authority_candidates(_tier1("f001", "Ops Runbook"))
        entry = result["authority_candidates"][0]
        for key in ("node_id", "tier", "score", "title", "matched_terms"):
            self.assertIn(key, entry)
        self.assertEqual(entry["tier"], 1)
        self.assertEqual(entry["score"], 0.612)


class ChineseTermsTest(unittest.TestCase):
    def test_zh_authority_titles_hit(self):
        text = "\n".join([
            _tier1("f101", "信息安全管理制度"),
            _tier1("f102", "核心网割接操作规程"),
            _tier1("f103", "供应商准入台账"),
        ])
        result = extract_authority_candidates(text)
        by_id = {c["node_id"]: c for c in result["authority_candidates"]}
        self.assertIn("制度", by_id["f101"]["matched_terms"])
        self.assertIn("规程", by_id["f102"]["matched_terms"])
        self.assertIn("台账", by_id["f103"]["matched_terms"])
        self.assertEqual(result["authority_total"], 3)

    def test_dir_name_never_matched(self):
        text = "\n".join([
            "├── [DIR] policies/",
            _tier1("f043", "Weekly Sync Notes", score="0.300"),
            "├── [DIR] runbooks/",
            _tier2("f044", "standup minutes", score="0.2"),
        ])
        result = extract_authority_candidates(text)
        self.assertEqual(result["authority_total"], 0)


class BadgeSourceTest(unittest.TestCase):
    def test_tier1_badge_only_hit_with_clean_title(self):
        text = _tier1(
            "f042", "2026-11-27 Mariner Health Ops Bridge",
            badge="[实体吻合:高 | 限定:2档 | 权威角色:运维规程SOP]")
        result = extract_authority_candidates(text)
        self.assertEqual(result["authority_total"], 1)
        entry = result["authority_candidates"][0]
        # title 不含徽标尾巴
        self.assertEqual(entry["title"], "2026-11-27 Mariner Health Ops Bridge")
        self.assertEqual(entry["authority_role"], "运维规程SOP")
        self.assertIn("badge", entry["match_sources"])
        self.assertNotIn("title_term", entry["match_sources"])
        self.assertEqual(entry["matched_terms"], [])

    def test_tier2_badge_hit(self):
        text = _tier2("f087", "2026 Q4 Tier-1 Vendors", badge="[权威角色:汇总登记表]")
        result = extract_authority_candidates(text)
        entry = result["authority_candidates"][0]
        self.assertEqual(entry["tier"], 2)
        self.assertEqual(entry["authority_role"], "汇总登记表")
        self.assertIn("badge", entry["match_sources"])

    def test_tentative_badge_never_treated_as_authority(self):
        # T4(JEV-E2) 对 tentative 文档渲染 [权威角色:草案/示例]，绝不可被误召回为权威必读
        text = "\n".join([
            _tier1(
                "f055", "2026-11-20 Payment Flow Notes",
                badge="[实体吻合:高 | 权威角色:草案/示例 | ↑灰区晋升]",
            ),
            _tier1(
                "f056", "2026-11-21 Core Gateway Spec",
                badge="[实体吻合:高 | 权威角色:正式规范 | ↑灰区晋升]",
            ),
            _tier1(
                "f057", "2026-11-22 Vendor Policy Master",
                badge="[权威角色:正式制度规范/汇总登记表]",
            ),
        ])
        result = extract_authority_candidates(text)
        by_id = {c["node_id"]: c for c in result["authority_candidates"]}
        self.assertNotIn("f055", by_id)
        self.assertEqual(by_id["f056"]["authority_role"], "正式规范")
        self.assertEqual(by_id["f057"]["authority_role"], "正式制度规范/汇总登记表")


class SkeletonSourceTest(unittest.TestCase):
    def test_skeleton_doc_type_hit_without_badge(self):
        text = _tier1("f042", "2026-11-27 Mariner Health Ops Bridge")

        def lookup(doc_ids):
            self.assertEqual(doc_ids, ["f042"])
            return {"f042": {"jev_doc_type": "runbook_sop",
                             "jev_doc_type_conf": 0.996,
                             "jev_is_registry": False}}

        result = extract_authority_candidates(text, skeleton_lookup=lookup)
        entry = result["authority_candidates"][0]
        self.assertIn("doc_skeleton", entry["match_sources"])
        self.assertEqual(entry["jev_doc_type"], "runbook_sop")
        self.assertFalse(entry["jev_is_registry"])
        self.assertEqual(entry["authority_role"], ROLE_DISPLAY_NAMES["runbook_sop"])

    def test_skeleton_registry_hit(self):
        text = _tier1("f087", "2026 Q4 Tier-1 Vendors")

        def lookup(doc_ids):
            return {"f087": {"jev_doc_type": "", "jev_doc_type_conf": 0.0,
                             "jev_is_registry": True}}

        result = extract_authority_candidates(text, skeleton_lookup=lookup)
        entry = result["authority_candidates"][0]
        self.assertTrue(entry["jev_is_registry"])
        self.assertEqual(entry["authority_role"], "汇总登记表")
        # 非权威体裁的普通 doc_type 不触发来源 C 命中
        text2 = _tier1("f090", "Casual Chat Log")

        def lookup2(doc_ids):
            return {"f090": {"jev_doc_type": "meeting_comm",
                             "jev_doc_type_conf": 0.99, "jev_is_registry": False}}

        result2 = extract_authority_candidates(text2, skeleton_lookup=lookup2)
        self.assertEqual(result2["authority_total"], 0)

    def test_lookup_failure_degrades_silently(self):
        text = _tier1("f042", "Weekly Sync Notes")

        def broken_lookup(doc_ids):
            raise RuntimeError("lancedb boom")

        result = extract_authority_candidates(text, skeleton_lookup=broken_lookup)
        self.assertEqual(result["authority_total"], 0)
        self.assertTrue(result["ok"])


class StarRecommendationTest(unittest.TestCase):
    def test_star_line_parsed_with_badge(self):
        text = "\n".join([
            "## ★ 优先精读建议（综合实体吻合度、限定条件与权威/台账角色生成）",
            "- [f099] Vendor Onboarding Checklist  [实体吻合:高 | 权威角色:汇总登记表]",
            "",
            "## 一、Tier 1 候选池（共 85 篇）",
            _tier1("f001", "Ops Runbook"),
        ])
        records, _ = parse_overview_docs(text)
        star = [r for r in records if r["tier"] == 0]
        self.assertEqual(len(star), 1)
        self.assertEqual(star[0]["node_id"], "f099")
        self.assertEqual(star[0]["title"], "Vendor Onboarding Checklist")
        self.assertEqual(star[0]["authority_role"], "汇总登记表")

    def test_star_deduped_against_tier1_rich_entry(self):
        # f042 同时出现在 ★ 区与 Tier 1：保留带分数/路径的 Tier 1 富信息条目
        records, _ = parse_overview_docs(OVERVIEW_TEXT)
        f042 = [r for r in records if r["node_id"] == "f042"]
        self.assertEqual(len(f042), 1)
        self.assertEqual(f042[0]["tier"], 1)
        self.assertEqual(f042[0]["path"], "ops/handoffs")
        self.assertAlmostEqual(f042[0]["score"], 0.612)

    def test_star_sorted_first(self):
        result = extract_authority_candidates(OVERVIEW_TEXT)
        tiers = [c["tier"] for c in result["authority_candidates"]]
        self.assertEqual(tiers, sorted(tiers))


class MiscBehaviorTest(unittest.TestCase):
    def test_empty_input_rejected(self):
        result = extract_authority_candidates("")
        self.assertFalse(result["ok"])
        self.assertIn("empty input", result["error"])

    def test_duplicate_gid_deduped(self):
        text = "\n".join([
            _tier1("f043", "Ops Runbook", score="0.9"),
            _tier2("f043", "Ops Runbook", score="0.1"),
        ])
        result = extract_authority_candidates(text)
        self.assertEqual(result["authority_total"], 1)
        self.assertEqual(result["authority_candidates"][0]["tier"], 1)


class CmdCheckAuthorityEndToEndTest(unittest.TestCase):
    """端到端：cmd_check_authority 从真实 doc_skeleton.lance 批量兜底查询。"""

    def _build_route(self, lan: Path, *, with_node_index: bool = False) -> dict:
        # 严格对齐真实 SectionIndex：仅存储大写本地 ID F042 / F087
        table = pa.table({
            "doc_key": pa.array(["F042", "F087"], type=pa.string()),
            "jev_doc_type": pa.array(
                ["runbook_sop", ""], type=pa.string()),
            "jev_doc_type_conf": pa.array([0.996, 0.0], type=pa.float32()),
            "jev_is_registry": pa.array([False, True], type=pa.bool_()),
        })
        db = lancedb.connect(str(lan))
        db.create_table("doc_skeleton", data=table)
        if with_node_index:
            (lan / "node_index.json").write_text(json.dumps({
                "F042": "ops/handoffs/2026-11-27-mariner-health-ops-bridge.md",
                "F087": "procurement/2026-q4-tier1-vendors.md",
            }), encoding="utf-8")
            (lan / "overview.md").write_text(
                "# overview-format: v1\n- [F042] Mariner\n- [F087] Vendors\n",
                encoding="utf-8",
            )
        return {"kind": "agent", "label": "main", "lan_dir": str(lan),
                "pre_dir": str(lan), "overview_md": str(lan / "overview.md"),
                "ready": True}

    def test_end_to_end_hit_via_skeleton_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            lan = Path(tmp)
            route = self._build_route(lan)
            overview = lan / "merged_overview.md"
            overview.write_text(OVERVIEW_TEXT, encoding="utf-8")
            args = SimpleNamespace(file=str(overview), agent_id="test")
            buf = io.StringIO()
            with mock.patch.object(orr, "collect_routes", return_value=[route]), \
                    contextlib.redirect_stdout(buf):
                rc = orr.cmd_check_authority(args)
            self.assertEqual(rc, 0)
            result = json.loads(buf.getvalue())
            by_id = {c["node_id"]: c for c in result["authority_candidates"]}
            # 弱标题 f042：徽标 + 标量列（大写 F042 映射回小写 f042）双源命中
            self.assertIn("badge", by_id["f042"]["match_sources"])
            self.assertIn("doc_skeleton", by_id["f042"]["match_sources"])
            self.assertEqual(by_id["f042"]["jev_doc_type"], "runbook_sop")
            # 弱标题 f087：无徽标、无标题词，仅靠大写 F087 jev_is_registry=True 兜底命中
            self.assertIn("doc_skeleton", by_id["f087"]["match_sources"])
            self.assertTrue(by_id["f087"]["jev_is_registry"])
            self.assertEqual(by_id["f087"]["authority_role"], "汇总登记表")
            # 普通文档不误报
            self.assertNotIn("f043", by_id)

    def test_end_to_end_real_prefixed_global_id_mapping(self):
        # 真实线上场景：merged_overview 中为带路由前缀的全局 ID f<prefix>042 / f<prefix>087
        with tempfile.TemporaryDirectory() as tmp:
            lan = Path(tmp)
            route = self._build_route(lan, with_node_index=True)
            _, remaps = orr._build_global_node_index([route])
            gid_42 = remaps[0][1]["F042"]
            gid_87 = remaps[0][1]["F087"]
            self.assertNotEqual(gid_87, "f087")
            overview_text = "\n".join([
                "## ★ 优先精读建议",
                f"- [{gid_42}] 2026-11-27 Mariner Health Ops Bridge  [↑灰区晋升]",
                "## 一、Tier 1 候选池",
                "├── [DIR] procurement/",
                _tier1(gid_87, "2026 Q4 Tier-1 Vendors", score="0.540"),
            ])
            overview = lan / "merged_overview.md"
            overview.write_text(overview_text, encoding="utf-8")
            args = SimpleNamespace(file=str(overview), agent_id="test")
            buf = io.StringIO()
            with mock.patch.object(orr, "collect_routes", return_value=[route]), \
                    contextlib.redirect_stdout(buf):
                rc = orr.cmd_check_authority(args)
            self.assertEqual(rc, 0)
            result = json.loads(buf.getvalue())
            by_id = {c["node_id"]: c for c in result["authority_candidates"]}
            self.assertEqual(by_id[gid_42]["title"], "2026-11-27 Mariner Health Ops Bridge")
            self.assertEqual(by_id[gid_42]["jev_doc_type"], "runbook_sop")
            self.assertEqual(by_id[gid_42]["authority_role"], "运维规程SOP")
            self.assertTrue(by_id[gid_87]["jev_is_registry"])
            self.assertEqual(by_id[gid_87]["authority_role"], "汇总登记表")

    def test_routes_failure_falls_back_to_text_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            overview = Path(tmp) / "merged_overview.md"
            overview.write_text(_tier1("f001", "Ops Runbook"), encoding="utf-8")
            args = SimpleNamespace(file=str(overview), agent_id="test")
            with mock.patch.object(orr, "collect_routes",
                                   side_effect=RuntimeError("state missing")):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = orr.cmd_check_authority(args)
            self.assertEqual(rc, 0)
            result = json.loads(buf.getvalue())
            self.assertEqual(result["authority_total"], 1)
            self.assertEqual(
                result["authority_candidates"][0]["match_sources"], ["title_term"])

    def test_missing_route_skeleton_degrades_to_two_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = {"lan_dir": str(Path(tmp)), "pre_dir": str(Path(tmp)),
                     "overview_md": str(Path(tmp) / "overview.md"),
                     "kind": "agent", "label": "main", "ready": True}
            overview = Path(tmp) / "merged_overview.md"
            overview.write_text(OVERVIEW_TEXT, encoding="utf-8")
            args = SimpleNamespace(file=str(overview), agent_id="test")
            with mock.patch.object(orr, "collect_routes", return_value=[route]):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = orr.cmd_check_authority(args)
            self.assertEqual(rc, 0)
            result = json.loads(buf.getvalue())
            by_id = {c["node_id"]: c for c in result["authority_candidates"]}
            # 无 doc_skeleton.lance：f087 不命中，f042 仍靠徽标命中
            self.assertNotIn("f087", by_id)
            self.assertEqual(by_id["f042"]["match_sources"], ["badge"])


if __name__ == "__main__":
    unittest.main()
