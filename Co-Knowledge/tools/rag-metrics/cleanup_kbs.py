"""清理评测知识库：先删文件（含切片/向量/ES），再删库，最后删残留 ES 索引。

产品 ``delete_kbase`` 要求库内文件数为 0；直接删库会报
``kbase.can.not.delete.include.knowledge``。本脚本按 e2e cleanup 的顺序做，
并额外清掉 ``doc_<id>__backup_*`` 之类的残留索引。
"""

from __future__ import annotations

import argparse
import time
from typing import List

import requests

BASE = 'http://127.0.0.1/api/co-knowledge/v1'
ES = 'http://127.0.0.1:9200'


def envelope(response: requests.Response):
    payload = response.json()
    code = payload.get('code')
    if isinstance(code, dict):
        code = code.get('code')
    return code, payload.get('bo'), payload


def list_files(kb_id: str) -> List[dict]:
    response = requests.post(
        f'{BASE}/directory/search/pageFile/all?kbaseId={kb_id}',
        json={'currentPage': 1, 'pageSize': 100}, timeout=60)
    code, bo, payload = envelope(response)
    if code != '0000':
        return []
    return list((bo or {}).get('data') or [])


def delete_kb(kb_id: str, wait: int = 300) -> None:
    files = list_files(kb_id)
    print(f'{kb_id}: {len(files)} files')
    for row in files:
        file_id = row.get('id')
        if not file_id:
            continue
        try:
            response = requests.post(
                f'{BASE}/file/delete/{file_id}?kbaseId={kb_id}', timeout=120)
            code, _, _ = envelope(response)
            print(f'  delete file {file_id}: {code}')
        except Exception as error:                                # noqa: BLE001
            print(f'  delete file {file_id} failed: {error}')

    deadline = time.time() + wait
    while time.time() < deadline:
        remaining = list_files(kb_id)
        if not remaining:
            break
        print(f'  waiting: {len(remaining)} files left')
        time.sleep(3)
    remaining = list_files(kb_id)
    if remaining:
        raise SystemExit(f'{kb_id}: 文件未清空（{len(remaining)}），拒绝删库')

    response = requests.post(f'{BASE}/kbase/delete/{kb_id}', timeout=120)
    code, _, payload = envelope(response)
    print(f'  delete kb {kb_id}: {code} {payload.get("message") or ""}')

    # 残留 ES 索引（主索引通常已删；backup/staging 需要手工清）
    try:
        indices = requests.get(
            f'{ES}/_cat/indices?h=index&format=json', timeout=30).json()
        for item in indices:
            name = item.get('index', '')
            if name.startswith(f'doc_{kb_id}'):
                requests.delete(f'{ES}/{name}', timeout=60)
                print(f'  delete es index {name}')
    except Exception as error:                                    # noqa: BLE001
        print(f'  es cleanup skipped: {error}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('kb_ids', nargs='+')
    args = parser.parse_args()
    for kb_id in args.kb_ids:
        delete_kb(kb_id)


if __name__ == '__main__':
    main()
