#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A0 JSON 解析与协议 URL 单测。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))

from common.dynamic_overview.a0 import (  # noqa: E402
    _chat_url,
    _extract_json,
    _parse_payload,
)


class A0ParseTest(unittest.TestCase):
    def test_extract_json_from_reasoning_prefix(self) -> None:
        content = (
            "thinking: the schema looks like {\"hit_quality\": ...}\n"
            "more thinking {not valid json}\n"
            "{\"hit_quality\": \"FULL_HIT\", \"intermediate_result_A\": \"x\", "
            "\"unresolved_knowledge_gaps\": [], "
            "\"next_queries_Q1\": {\"sub_questions\": [\"q\"], \"key_terms\": [\"t\"]}}"
        )
        data = _extract_json(content)
        self.assertIsNotNone(data)
        self.assertEqual(data["hit_quality"], "FULL_HIT")

    def test_parse_payload_defaults(self) -> None:
        payload = _parse_payload({
            "hit_quality": "unknown",
            "unresolved_knowledge_gaps": ["g"],
        })
        self.assertEqual(payload["hit_quality"], "PARTIAL_HIT")
        self.assertEqual(payload["next_queries_Q1"]["sub_questions"], [])
        self.assertEqual(payload["unresolved_knowledge_gaps"], ["g"])

    def test_chat_url(self) -> None:
        self.assertEqual(
            _chat_url("http://host/v1", False),
            "http://host/v1/chat/completions",
        )
        self.assertEqual(
            _chat_url("http://host/v1/", True),
            "http://host/v1/messages",
        )
        self.assertEqual(
            _chat_url("http://host/chat/completions", False),
            "http://host/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
