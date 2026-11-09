"""workflow-builder/scripts/render_dag.py smoke test。

覆盖：
1. import 不依赖 /tmp 残留文件（之前 bug：open('/tmp/component-css.txt') 在 import 时崩）
2. assets/component.css 真实存在
3. component_css() 返回 CSS 文本
4. DAG workflow.yaml 能渲染出含关键类（.node / .editor / .canvas-wrap / .side）的 HTML
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

import render_dag  # noqa: E402  (sys.path via conftest)

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
COMPONENT_CSS = PLUGIN_ROOT / "skills" / "workflow-builder" / "assets" / "component.css"


def test_component_css_file_exists():
    """回归测试：之前 module-level open('/tmp/component-css.txt') 在新 session 必崩。

    现在 CSS 在 assets/component.css（相对脚本），import 不再依赖任何 /tmp 残留。
    """
    assert COMPONENT_CSS.is_file(), f"missing {COMPONENT_CSS}"


def test_component_css_function_returns_text():
    css = render_dag.component_css()
    assert isinstance(css, str)
    assert len(css) > 1000, "component CSS looks suspiciously short"
    # 关键组件类应出现
    for cls in [".node", ".editor", ".canvas-wrap", ".side", ".toolbar"]:
        assert cls in css, f"component_css() missing class {cls!r}"


def test_dag_render_contains_key_classes(tmp_path: Path):
    """DAG workflow.yaml 渲染结果应包含核心视觉类。"""
    wf = tmp_path / "workflow.yaml"
    wf.write_text(
        """mode: dag
agents:
  - id: a
    agent: drive:analyzer
    depends_on: []
  - id: b
    agent: drive:executor
    depends_on: [a]
""",
        encoding="utf-8",
    )
    html = render_dag.render_html(tmp_path, "a")

    # 关键类 + 节点 id 都应在 HTML 里
    for needle in [".node", ".editor", ".canvas-wrap", ".side", ">a<", ">b<", "drive:analyzer", "drive:executor"]:
        assert needle in html, f"DAG HTML missing {needle!r}"


def test_phase_render_contains_key_classes(tmp_path: Path):
    """Phase workflow.yaml 渲染结果应包含核心视觉类。"""
    wf = tmp_path / "workflow.yaml"
    wf.write_text(
        """mode: phase
phases:
  - name: analyze
    agent: drive:analyzer
  - name: execute
    agent: drive:executor
""",
        encoding="utf-8",
    )
    html = render_dag.render_html(tmp_path, "analyze")

    for needle in [".node", ".editor", ".canvas-wrap", "analyze", "execute"]:
        assert needle in html, f"phase HTML missing {needle!r}"