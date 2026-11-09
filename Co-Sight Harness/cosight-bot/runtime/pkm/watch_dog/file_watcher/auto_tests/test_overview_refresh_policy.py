#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建期 overview 刷新策略：首/中间刷新不读章节，收尾由调用方生成完整树。"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_RUNTIME = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_RUNTIME))
sys.path.insert(0, str(_RUNTIME / "watch_dog"))

from watch_dog.file_watcher import handler as handler_module  # noqa: E402
from watch_dog.file_watcher.handler import LlamaIndexIncrementalHandler  # noqa: E402


class OverviewRefreshPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / "src"
        self.pre = root / "pre"
        self.lan = root / "lan"
        for path in (self.src, self.pre, self.lan):
            path.mkdir()
        self.handler = LlamaIndexIncrementalHandler(self.src, agent_id="test")
        handler_module._overview_refresh_state.clear()

    def tearDown(self) -> None:
        self.handler.shutdown()
        handler_module._overview_refresh_state.clear()
        self.tmp.cleanup()

    def _force_due(self) -> None:
        state = handler_module._overview_refresh_state[str(self.lan)]
        state["ts"] = time.time() - 10_000
        state["files"] = 10_000

    def test_first_and_intermediate_refresh_without_sections(self) -> None:
        calls: list[bool | None] = []

        def fake_write(lan_dir, pre_dir, **kwargs):
            calls.append(kwargs.get("show_sections"))

        with patch.object(handler_module, "write_overview_md", side_effect=fake_write):
            self.handler._reset_overview_throttle(self.lan, total_files=1000)
            self.handler._maybe_refresh_overview(self.lan, self.pre)
            self.assertEqual(calls, [False])
            self._force_due()
            self.handler._maybe_refresh_overview(self.lan, self.pre)
            self.assertEqual(calls, [False, False])

    def test_large_build_disables_intermediate_by_threshold(self) -> None:
        calls: list[bool | None] = []

        def fake_write(lan_dir, pre_dir, **kwargs):
            calls.append(kwargs.get("show_sections"))

        with patch.object(handler_module, "write_overview_md", side_effect=fake_write):
            self.handler._reset_overview_throttle(self.lan, total_files=100_000)
            self.handler._maybe_refresh_overview(self.lan, self.pre)
            self._force_due()
            self.handler._maybe_refresh_overview(self.lan, self.pre)
            self.assertEqual(calls, [False])

    def test_intermediate_refresh_can_be_disabled(self) -> None:
        calls: list[bool | None] = []

        def fake_write(lan_dir, pre_dir, **kwargs):
            calls.append(kwargs.get("show_sections"))

        with patch.dict(os.environ, {"COSIGHTBOT_OVERVIEW_REFRESH_INTERMEDIATE": "0"}):
            with patch.object(handler_module, "write_overview_md", side_effect=fake_write):
                self.handler._reset_overview_throttle(self.lan, total_files=1000)
                self.handler._maybe_refresh_overview(self.lan, self.pre)
                self._force_due()
                self.handler._maybe_refresh_overview(self.lan, self.pre)
                self.assertEqual(calls, [False])

    def test_intermediate_sections_opt_in(self) -> None:
        calls: list[bool | None] = []

        def fake_write(lan_dir, pre_dir, **kwargs):
            calls.append(kwargs.get("show_sections"))

        with patch.dict(os.environ, {"COSIGHTBOT_OVERVIEW_REFRESH_SHOW_SECTIONS": "1"}):
            with patch.object(handler_module, "write_overview_md", side_effect=fake_write):
                self.handler._reset_overview_throttle(self.lan, total_files=1000)
                self.handler._maybe_refresh_overview(self.lan, self.pre)
                self._force_due()
                self.handler._maybe_refresh_overview(self.lan, self.pre)
                self.assertEqual(calls, [False, True])


if __name__ == "__main__":
    unittest.main()
