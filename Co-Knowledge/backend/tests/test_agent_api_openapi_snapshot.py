"""运行时 OpenAPI 与 ``contracts/openapi/agent-api.yaml`` 快照一致。

快照由 ``agent_api.rest.build_rest_app().openapi()`` 生成；改接口后重新生成，
否则 Agent 平台导入的契约会与实际行为漂移。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agent.rest import build_rest_app

SNAPSHOT = Path(__file__).resolve().parents[2] / 'contracts' / 'openapi' / 'agent-api.yaml'


def test_openapi_matches_snapshot(monkeypatch):
    monkeypatch.delenv('RKB_AGENT_PUBLIC_BASE', raising=False)
    snapshot = yaml.safe_load(SNAPSHOT.read_text(encoding='utf-8'))
    assert build_rest_app().openapi() == snapshot
