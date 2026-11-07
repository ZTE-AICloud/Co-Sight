#!/usr/bin/env python3
"""校验 Agent REST OpenAPI 与 ``contracts/openapi/agent-api.yaml`` 一致。

两种模式：

    # 直接 import 子应用（不需要运行中的服务；CI/本地都可用）
    python3 tools/verify/verify-agent-openapi.py

    # 对比运行中的服务
    python3 tools/verify/verify-agent-openapi.py --url http://127.0.0.1/api/co-knowledge/v1/agent/openapi.json

脚本会把 ``PYTHONPATH`` 补上 ``backend/src``；依赖 PyYAML（已在 requirements.lock）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / 'contracts' / 'openapi' / 'agent-api.yaml'


def _runtime_schema(url: str | None) -> dict:
    if url:
        import requests

        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()

    src = ROOT / 'backend' / 'src'
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    os.environ.setdefault('RKB_AGENT_PUBLIC_BASE', '/api/co-knowledge/v1/agent')
    from agent.rest import build_rest_app

    return build_rest_app().openapi()


def _diff(expected, actual, path='') -> list[str]:
    """给出可读的差异；只报前 10 条。"""
    if type(expected) is not type(actual):
        return [f'{path or "<root>"}: type {type(expected).__name__} != {type(actual).__name__}']
    if isinstance(expected, dict):
        problems = []
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                problems.append(f'{path}/{key}: only in runtime')
            elif key not in actual:
                problems.append(f'{path}/{key}: only in snapshot')
            else:
                problems.extend(_diff(expected[key], actual[key], f'{path}/{key}'))
            if len(problems) >= 10:
                return problems[:10]
        return problems
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f'{path}: length {len(expected)} != {len(actual)}']
        problems = []
        for index, (left, right) in enumerate(zip(expected, actual)):
            problems.extend(_diff(left, right, f'{path}[{index}]'))
            if len(problems) >= 10:
                return problems[:10]
        return problems
    return [] if expected == actual else [f'{path}: {expected!r} != {actual!r}']


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=None,
                        help='运行中的 OpenAPI URL；省略则直接 import 子应用')
    args = parser.parse_args(argv)

    expected = yaml.safe_load(SNAPSHOT.read_text(encoding='utf-8'))
    actual = _runtime_schema(args.url)
    problems = _diff(expected, actual)
    if problems:
        print('FAIL: OpenAPI 与快照不一致')
        for problem in problems:
            print('  -', problem)
        print('\n重新生成快照：')
        print('  PYTHONPATH=backend/src python3 - <<PY ... build_rest_app().openapi() ... PY')
        return 1
    print('PASS: OpenAPI 与 contracts/openapi/agent-api.yaml 一致 '
          f'({len(actual.get("paths", {}))} paths, openapi={actual.get("openapi")})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
