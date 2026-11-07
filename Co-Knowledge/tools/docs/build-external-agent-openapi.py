#!/usr/bin/env python3
"""生成 ``docs/external-api/openapi/agent-api.yaml``（交付快照）。

用法（仓库根目录）::

    python3 tools/docs/build-external-agent-openapi.py
    python3 tools/docs/build-external-agent-openapi.py --check   # 只比对，不写文件

交付快照与 ``contracts/openapi/agent-api.yaml`` 内容一致，只替换
``info.description`` 中指向仓库内部文档的引用。交付前重新生成即可，
不要在仓库内手工维护第二份契约。
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'contracts' / 'openapi' / 'agent-api.yaml'
OUTPUT = ROOT / 'docs' / 'external-api' / 'openapi' / 'agent-api.yaml'

SOURCE_HEADER = '# 由 agent.rest.build_rest_app().openapi() 生成'
DELIVERY_HEADER = (
    '# 交付快照：由 contracts/openapi/agent-api.yaml 生成，'
    '仅替换 info.description 中的内部文档引用。\n'
)
INTERNAL_REF = 'see docs/agent-integration.md'
DELIVERY_REF = 'see the Knowledge Studio external API documentation'


def render() -> str:
    text = SOURCE.read_text(encoding='utf-8')
    if not text.startswith(SOURCE_HEADER):
        raise SystemExit(f'❌ {SOURCE} 缺少预期头注释，拒绝生成')
    body = text.split('\n', 1)[1]
    if INTERNAL_REF not in body:
        raise SystemExit(f'❌ {SOURCE} 中找不到内部文档引用，拒绝生成')
    return DELIVERY_HEADER + body.replace(INTERNAL_REF, DELIVERY_REF)


def main() -> int:
    parser = argparse.ArgumentParser(description='生成 Agent OpenAPI 交付快照')
    parser.add_argument('--check', action='store_true', help='只比对，不写文件')
    args = parser.parse_args()

    rendered = render()
    if args.check:
        current = OUTPUT.read_text(encoding='utf-8') if OUTPUT.exists() else ''
        if current != rendered:
            print(f'❌ {OUTPUT} 与契约源不一致，请重新生成')
            return 1
        print(f'✅ {OUTPUT} 与契约源一致')
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding='utf-8')
    print(f'✅ 已生成 {OUTPUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
