#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""overview_resolver V4 全局节点 ID 单测：路由前缀稳定 + 本地 ID 兼容。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))

from common import overview_resolver  # noqa: E402


class GlobalNodeIdTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _route(self, name: str) -> dict:
        lan = self.root / "lancedb" / name
        pre = self.root / "pre" / name
        lan.mkdir(parents=True)
        pre.mkdir(parents=True)
        (lan / "node_index.json").write_text(
            json.dumps({"_next_id": 3, "F001": "doc.md"}),
            encoding="utf-8",
        )
        return {
            "kind": "agent",
            "label": name,
            "lan_dir": str(lan),
            "pre_dir": str(pre),
            "overview_md": str(lan / "overview.md"),
        }

    def test_route_prefixes_are_stable_and_distinct(self) -> None:
        a = self._route("agent-a")
        b = self._route("agent-b")
        first = overview_resolver._assign_route_prefixes([a, b])
        second = overview_resolver._assign_route_prefixes([a, b])
        self.assertEqual(first, second)
        self.assertEqual(len(set(first)), 2)
        # 路由顺序不影响各自前缀
        reversed_prefixes = overview_resolver._assign_route_prefixes([b, a])
        self.assertEqual(reversed_prefixes, list(reversed(first)))

    def test_global_id_uses_route_prefix_and_accepts_local_id(self) -> None:
        a = self._route("agent-a")
        b = self._route("agent-b")
        routes = [a, b]
        prefixes = overview_resolver._assign_route_prefixes(routes)
        index, remaps = overview_resolver._build_global_node_index(routes)

        g_a = f"f{prefixes[0]}001"
        g_b = f"f{prefixes[1]}001"
        self.assertIn(g_a, index)
        self.assertIn(g_b, index)
        self.assertNotEqual(g_a, g_b)
        self.assertEqual(remaps[0][1]["F001"], g_a)
        self.assertEqual(remaps[1][1]["F001"], g_b)
        # `_next_id` 不能被当成节点
        self.assertNotIn("_next_id", index)

        # 精确全局 ID（大小写不敏感）
        self.assertEqual(overview_resolver._lookup_global_id(index, g_a), g_a)
        self.assertEqual(overview_resolver._lookup_global_id(index, g_a.upper()), g_a)
        # 多路由下本地 F001 有歧义 -> 宁缺毋错
        self.assertIsNone(overview_resolver._lookup_global_id(index, "F001"))

    def test_single_route_local_id_fallback(self) -> None:
        a = self._route("agent-a")
        prefix = overview_resolver._assign_route_prefixes([a])[0]
        index, _ = overview_resolver._build_global_node_index([a])
        self.assertEqual(
            overview_resolver._lookup_global_id(index, "F001"),
            f"f{prefix}001",
        )

    def test_promoted_chapter_not_counted_as_alias(self) -> None:
        a = self._route("agent-a")
        lan = Path(a["lan_dir"])
        (lan / "node_index.json").write_text(
            json.dumps({
                "_next_id": 4,
                "F001": "main.md",
                "F002": "main_chapters/part.md",
                "F003": "other_chapters/hidden.md",
            }),
            encoding="utf-8",
        )
        (lan / "overview.md").write_text(
            "# overview-format: v2-compressed\n---\n\n"
            "[F001] main\n[F002] part\n",
            encoding="utf-8",
        )
        prefix = overview_resolver._assign_route_prefixes([a])[0]
        index, _ = overview_resolver._build_global_node_index([a])
        promoted = index[f"f{prefix}002"]
        hidden = index[f"f{prefix}003"]
        self.assertFalse(promoted["is_alias"])
        self.assertTrue(hidden["is_alias"])
        self.assertEqual(overview_resolver._count_doc_nodes(index), 2)

    def test_local_id_exact_match_beats_numeric_suffix(self) -> None:
        a = self._route("agent-a")
        (Path(a["lan_dir"]) / "node_index.json").write_text(
            json.dumps({
                "_next_id": 1007,
                "F006": "a.md",
                "F1006": "b.md",
            }),
            encoding="utf-8",
        )
        prefix = overview_resolver._assign_route_prefixes([a])[0]
        index, _ = overview_resolver._build_global_node_index([a])
        # 两者数字后缀都是 "006"，必须按 local_id 精确匹配
        self.assertEqual(
            overview_resolver._lookup_global_id(index, "F006"),
            f"f{prefix}006",
        )
        self.assertEqual(
            overview_resolver._lookup_global_id(index, "F1006"),
            f"f{prefix}1006",
        )


if __name__ == "__main__":
    unittest.main()
