#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""batch_rerank_scores 分片与索引对齐单测。"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from watch_dog.file_watcher import embedding_model  # noqa: E402


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class RerankBatchTest(unittest.TestCase):
    def test_splits_and_aligns_scores(self) -> None:
        calls: list[dict] = []

        def fake_post(url, headers, json, timeout, proxies):
            calls.append({"url": url, "count": len(json["documents"])})
            return _FakeResponse({
                "results": [
                    {"index": i, "relevance_score": i / 1000.0}
                    for i in range(len(json["documents"]))
                ]
            })

        env = {
            "COSIGHTBOT_RERANK_API_URL": "http://rerank.test",
            "COSIGHTBOT_RERANK_MAX_BATCH": "200",
        }
        with patch.dict(os.environ, env):
            with patch.object(embedding_model.requests, "post", side_effect=fake_post):
                scores = embedding_model.batch_rerank_scores(
                    "query", [str(i) for i in range(450)], timeout=1
                )

        self.assertIsNotNone(scores)
        self.assertEqual([c["count"] for c in calls], [200, 200, 50])
        self.assertEqual(len(scores), 450)
        self.assertAlmostEqual(scores[0], 0.0)
        self.assertAlmostEqual(scores[199], 0.199)
        self.assertAlmostEqual(scores[200], 0.0)  # 第二批从本地 index 0 开始
        self.assertAlmostEqual(scores[449], 0.049)

    def test_failed_batch_returns_none(self) -> None:
        def fake_post(*args, **kwargs):
            raise RuntimeError("boom")

        env = {
            "COSIGHTBOT_RERANK_API_URL": "http://rerank.test",
            "COSIGHTBOT_RERANK_MAX_BATCH": "100",
        }
        with patch.dict(os.environ, env):
            with patch.object(embedding_model.requests, "post", side_effect=fake_post):
                scores = embedding_model.batch_rerank_scores(
                    "query", [str(i) for i in range(150)], timeout=1
                )
        self.assertIsNone(scores)


if __name__ == "__main__":
    unittest.main()
