#!/usr/bin/env python3
"""Text2SQL 评测：把「执行成功」拆成可分别观测的几项指标。

只测执行成功率是不够的——SQL 执行成功只说明语法和权限没问题，不说明选对了表、
映射对了值、算对了口径。这里按下面几组指标分别打分：

* **Guard Accuracy**：应当被拒绝的 SQL 是否被拒、错误码是否对得上（含误杀）；
* **SQL Validity**：自然语言用例是否产出可执行 SQL（没有校验期错误）；
* **Execution Success**：真的跑出结果的比例；
* **Table Recall@K**：上下文里是否包含用例声明的相关表；
* **Latency / Token Cost**：p50、p95 与 token 消耗。

用法（仓库根目录）::

    python3 tools/verify/text2sql-benchmark.py \\
        --base http://127.0.0.1:8080/api/co-knowledge/v1 \\
        --username admin --password admin \\
        --datasource 'Text2SQL 演示库' \\
        --out /tmp/text2sql-benchmark.json

``--cases`` 可换成自己的用例文件（结构见 text2sql-benchmark-cases.json）。
退出码：所有用例都符合预期时为 0，否则为 1（便于接入 CI）。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE / 'text2sql-benchmark-cases.json'


def login(session: requests.Session, base: str, username: str, password: str) -> None:
    response = session.post(f'{base}/auth/login',
                            json={'username': username, 'password': password},
                            timeout=15)
    response.raise_for_status()


def resolve_datasource(session: requests.Session, base: str, wanted: str) -> dict:
    items = session.get(f'{base}/text2sql/datasources', timeout=15).json()['items']
    for item in items:
        if wanted in (item['id'], item['name']):
            return item
    raise SystemExit(f'找不到数据源 {wanted!r}；可用：'
                     + ', '.join(f"{item['name']}({item['id']})" for item in items))


def run_case(session: requests.Session, base: str, datasource_id: str,
             case: dict) -> dict:
    payload = {'question': case.get('question') or case['id'],
               'datePolicy': 'relative', 'parameters': {}}
    if case.get('sql'):
        payload['sql'] = case['sql']
    started = time.perf_counter()
    response = session.post(f'{base}/text2sql/datasources/{datasource_id}/query',
                            json=payload, timeout=300)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    body = response.json() if response.content else {}
    error = body.get('error') or {}
    retrieval = body.get('retrieval') or {}
    context = retrieval.get('context') or {}
    tables = context.get('tables') or [
        item.get('fullName') or item.get('name') for item in retrieval.get('tables') or []]
    return {
        'id': case['id'],
        'kind': case.get('kind', 'query'),
        'status': response.status_code,
        'errorCode': error.get('code'),
        'errorStage': error.get('stage'),
        'tables': tables,
        'rowCount': (body.get('result') or {}).get('row_count'),
        'byteTruncated': (body.get('result') or {}).get('byte_truncated'),
        'attempts': (body.get('validation') or {}).get('attempts'),
        'latencyMs': elapsed_ms,
        'totalMs': (body.get('timing') or {}).get('total_ms'),
        'usage': body.get('usage') or {},
        'sql': (body.get('sql') or {}).get('final') or '',
    }


def evaluate(cases: list[dict], results: list[dict]) -> dict:
    by_id = {result['id']: result for result in results}
    guard_cases = [case for case in cases if case.get('expectError')]
    query_cases = [case for case in cases if case.get('kind') == 'query']

    guard_hits = [case for case in guard_cases
                  if by_id[case['id']]['errorCode'] == case['expectError']]
    guard_false_positives = [case for case in guard_cases
                             if case['id'] in by_id and by_id[case['id']]['errorCode'] is None]

    valid = [case for case in query_cases
             if by_id[case['id']]['errorCode'] is None]
    executed = [case for case in query_cases
                if by_id[case['id']]['errorCode'] is None
                and (by_id[case['id']]['rowCount'] or 0) > 0]

    recalls = []
    for case in query_cases:
        expected = set(case.get('expectTables') or [])
        if not expected:
            continue
        got = set(by_id[case['id']]['tables'] or [])
        recalls.append(len(expected & got) / len(expected))

    latencies = [result['latencyMs'] for result in results]
    tokens = sum(int((result['usage'] or {}).get('total_tokens') or 0) for result in results)
    return {
        'cases': len(cases),
        'guardAccuracy': round(len(guard_hits) / len(guard_cases), 3) if guard_cases else None,
        'guardFalsePositives': [case['id'] for case in guard_false_positives],
        'sqlValidity': round(len(valid) / len(query_cases), 3) if query_cases else None,
        'executionSuccess': round(len(executed) / len(query_cases), 3) if query_cases else None,
        'tableRecall': round(statistics.fmean(recalls), 3) if recalls else None,
        'latencyP50Ms': int(statistics.median(latencies)) if latencies else None,
        'latencyP95Ms': int(sorted(latencies)[max(int(len(latencies) * 0.95) - 1, 0)])
        if latencies else None,
        'totalTokens': tokens,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Text2SQL 评测')
    parser.add_argument('--base', default='http://127.0.0.1:8080/api/co-knowledge/v1')
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password', default='admin')
    parser.add_argument('--datasource', required=True,
                        help='数据源 id 或名称')
    parser.add_argument('--cases', default=str(DEFAULT_CASES))
    parser.add_argument('--out', default='')
    args = parser.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding='utf-8'))['cases']
    session = requests.Session()
    session.headers.update({'Origin': args.base.rsplit('/api/', 1)[0]})
    login(session, args.base, args.username, args.password)
    datasource = resolve_datasource(session, args.base, args.datasource)

    results = []
    for case in cases:
        result = run_case(session, args.base, datasource['id'], case)
        results.append(result)
        flag = 'OK  ' if result['errorCode'] == case.get('expectError') else 'DIFF'
        print(f"{flag} {case['id']:24s} error={result['errorCode'] or '-':24s} "
              f"rows={result['rowCount']} {result['latencyMs']}ms")

    summary = evaluate(cases, results)
    print()
    for key, value in summary.items():
        print(f'{key:22s} {value}')

    if args.out:
        Path(args.out).write_text(
            json.dumps({'datasource': datasource['id'], 'summary': summary,
                        'results': results}, ensure_ascii=False, indent=2),
            encoding='utf-8')
        print(f'\n明细已写入 {args.out}')

    mismatched = [result for result, case in zip(results, cases)
                  if result['errorCode'] != case.get('expectError')]
    return 0 if not mismatched else 1


if __name__ == '__main__':
    sys.exit(main())
