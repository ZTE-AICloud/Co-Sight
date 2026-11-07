#!/usr/bin/env python3
"""从 FastAPI 运行时路由生成 ``contracts/openapi/rkb-api.yaml``。

用法（仓库根目录）::

    python3 tools/verify/generate-rkb-openapi.py
    python3 tools/verify/generate-rkb-openapi.py --check   # 只比对，不写文件

主应用在运行时关闭了 Swagger（``docs_url/openapi_url=None``），这份静态文件是对外
交付的 OpenAPI；``backend/tests/test_rkb_openapi_snapshot.py`` 会保证它与路由表一致。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / 'backend' / 'src'
OUTPUT = ROOT / 'contracts' / 'openapi' / 'rkb-api.yaml'
VERSION_FILE = ROOT / 'contracts' / 'VERSION'

sys.path.insert(0, str(BACKEND_SRC))

from app import app                                            # noqa: E402
from infrastructure.http.openapi_contract import build_rkb_openapi          # noqa: E402

HEADER = (
    '# 由 tools/verify/generate-rkb-openapi.py 从 FastAPI 路由生成；'
    '改动接口后重新生成并跑 test_rkb_openapi_snapshot.py。\n'
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='只比对，不写文件')
    args = parser.parse_args()

    version = VERSION_FILE.read_text(encoding='utf-8').strip()
    schema = build_rkb_openapi(app, version=version)
    rendered = HEADER + yaml.safe_dump(schema, sort_keys=False, allow_unicode=True)
    if args.check:
        current = OUTPUT.read_text(encoding='utf-8') if OUTPUT.exists() else ''
        if current != rendered:
            print(f'❌ {OUTPUT} 与运行时路由不一致，请重新生成')
            return 1
        print(f'✅ {OUTPUT} 与运行时路由一致')
        return 0
    OUTPUT.write_text(rendered, encoding='utf-8')
    print(f'✅ 已生成 {OUTPUT}（{len(schema["paths"])} 条路径）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
