#!/usr/bin/env python3
"""Agent REST facade 端到端验收。

前置：服务已启动、数据库已初始化、`RKB_AGENT_TEST_KEY` 指向一把有效 Key。

    RKB_AGENT_TEST_KEY=ragk_... python3 tools/verify/verify-agent-api.py

可选环境变量：
    RKB_AGENT_BASE_URL     默认 http://127.0.0.1/api/co-knowledge/v1/agent
    RKB_AGENT_RKB_BASE     默认 http://127.0.0.1/api/co-knowledge/v1（用于验证未知路径的 problem 兜底）
    RKB_AGENT_TEST_KB      指定知识库 ID；省略用列表里的第一个
    RKB_AGENT_TEST_QUERY   检索词；默认命中仓库自带的样例文本
    RKB_AGENT_TEST_WORKFLOW 已发布工作流 ID；提供时额外验证 POST /agent/query

判据：
* 硬失败：401/403/422/404 语义、列表/详情、search 返回非空、answer 200 且带引用
  （若部署没有生成模型，answer 503 记为 SKIP，不阻断）；
* 软失败：检索为空、answer no_results —— 打印 WARN，仍返回 0（换 query 再跑）。
"""

from __future__ import annotations

import os
import sys

import requests

BASE = os.environ.get('RKB_AGENT_BASE_URL', 'http://127.0.0.1/api/co-knowledge/v1/agent').rstrip('/')
RKB_BASE = os.environ.get('RKB_AGENT_RKB_BASE', 'http://127.0.0.1/api/co-knowledge/v1').rstrip('/')
KEY = (os.environ.get('RKB_AGENT_TEST_KEY') or '').strip()
QUERY = os.environ.get('RKB_AGENT_TEST_QUERY', '这是一段用于验证任务队列的正文')
KB_ID = (os.environ.get('RKB_AGENT_TEST_KB') or '').strip()
WORKFLOW_ID = (os.environ.get('RKB_AGENT_TEST_WORKFLOW') or '').strip()

failures: list[str] = []
warnings: list[str] = []


def check(name: str, condition: bool, detail: str = '') -> None:
    if condition:
        print(f'PASS {name}')
    else:
        print(f'FAIL {name}: {detail}')
        failures.append(name)


def warn(name: str, detail: str) -> None:
    print(f'WARN {name}: {detail}')
    warnings.append(name)


def body(response) -> str:
    return response.text[:500].replace('\n', ' ')


def main() -> int:
    if not KEY:
        print('缺少 RKB_AGENT_TEST_KEY；先在容器内用 python3 -m agent_api.cli create 建一把',
              file=sys.stderr)
        return 2

    session = requests.Session()
    auth = {'Authorization': f'Bearer {KEY}'}

    # 1. 无 Key -> 401
    response = session.get(f'{BASE}/knowledge-bases', timeout=30)
    check('missing key -> 401', response.status_code == 401, body(response))
    check('missing key -> WWW-Authenticate',
          response.headers.get('WWW-Authenticate') == 'Bearer', str(response.headers))

    # 2. 列表
    response = session.get(f'{BASE}/knowledge-bases', headers=auth, timeout=30)
    check('list knowledge bases -> 200', response.status_code == 200, body(response))
    payload = response.json() if response.status_code == 200 else []
    knowledge_bases = payload if isinstance(payload, list) else []
    check('list knowledge bases -> non-empty', bool(knowledge_bases), body(response))
    check('list knowledge bases -> bare array', isinstance(payload, list), body(response))
    check('list knowledge bases -> X-Request-Id',
          bool(response.headers.get('X-Request-Id')), str(response.headers))
    if not knowledge_bases:
        print('没有可访问的文档库；请给 Key 加 kb_ids 或建库')
        return 1

    selected = KB_ID or knowledge_bases[0]['id']
    response = session.get(f'{BASE}/knowledge-bases/{selected}', headers=auth, timeout=30)
    check('get knowledge base -> 200', response.status_code == 200, body(response))
    if response.status_code == 200:
        check('get knowledge base -> plain object',
              (response.json() or {}).get('id') == selected, body(response))

    # 3. 检索
    response = session.post(f'{BASE}/search', headers=auth, timeout=120,
                            json={'query': QUERY, 'knowledge_base_ids': [selected],
                                  'mode': 'auto', 'top_k': 5})
    check('search -> 200', response.status_code == 200, body(response))
    search_payload = response.json() if response.status_code == 200 else {}
    results = search_payload.get('results') or []
    if results:
        first = results[0]
        check('search -> citation_id', str(first.get('citation_id', '')).startswith('S'),
              str(first))
        check('search -> text', bool(first.get('text')), str(first)[:200])
        check('search -> knowledge_base_id', first.get('knowledge_base_id') == selected,
              str(first)[:200])
    else:
        warn('search -> empty', f'query={QUERY!r} 在 {selected} 没有命中；换 RKB_AGENT_TEST_QUERY')

    # 4. 问答（没有生成模型时 503 记为 SKIP）
    response = session.post(f'{BASE}/answer', headers=auth, timeout=300,
                            json={'question': QUERY, 'knowledge_base_ids': [selected],
                                  'top_k': 5})
    if response.status_code == 503 and 'answer_unavailable' in response.text:
        print('SKIP answer: 部署未配置生成模型（503 answer_unavailable）')
    else:
        check('answer -> 200', response.status_code == 200, body(response))
        answer_payload = response.json() if response.status_code == 200 else {}
        answer_data = answer_payload if isinstance(answer_payload, dict) else {}
        if answer_data.get('no_results'):
            warn('answer -> no_results', body(response))
        elif answer_data.get('answer'):
            check('answer -> has answer', True)
            check('answer -> has citations', bool(answer_data.get('citations')), body(response))
        else:
            check('answer -> has answer', False, body(response))

    # 5. 参数校验
    response = session.post(f'{BASE}/search', headers=auth, timeout=30,
                            json={'query': 'q', 'top_k': 999})
    check('top_k over limit -> 422', response.status_code == 422, body(response))
    check('top_k over limit -> problem+json',
          response.headers.get('Content-Type', '').startswith('application/problem+json'),
          str(response.headers))
    check('top_k over limit -> validation_failed',
          (response.json() or {}).get('code') == 'validation_failed', body(response))

    # 6. 未知路径 -> 404 problem+json
    response = session.get(f'{BASE}/definitely-not-a-route', headers=auth, timeout=30)
    check('agent unknown path -> 404 problem', response.status_code == 404, body(response))
    check('agent unknown path -> not_found',
          (response.json() or {}).get('code') == 'not_found', body(response))

    # 7. 主 API 的未知路径同样是 404 problem（不再是 200 + 0005）
    response = session.get(f'{RKB_BASE}/nope/nothing', timeout=30)
    check('rkb catch-all -> 404 problem',
          response.status_code == 404, f'{response.status_code} {body(response)}')
    check('rkb catch-all -> not_found',
          (response.json() or {}).get('code') == 'not_found', body(response))

    # 8. Agent Key 执行工作流（POST /agent/query）
    query_url = f'{BASE}/query'
    response = session.post(query_url, headers=auth, timeout=60,
                            json={'question': QUERY,
                                  'conversation_id': 'verify-agent-query'})
    query_scope_ok = True
    if response.status_code == 403 and 'forbidden_scope' in response.text:
        query_scope_ok = False
        print('SKIP agent query: Key 未授予 workflow:run')
    elif response.status_code in (404, 503):
        query_scope_ok = False
        print(f'SKIP agent query: Agent REST/query 未启用或服务未就绪（{body(response)}）')
    else:
        check('agent query without workflow_id -> 422',
              response.status_code == 422, body(response))
        check('agent query without workflow_id -> problem+json',
              response.headers.get('Content-Type', '').startswith('application/problem+json'),
              str(response.headers))

    if WORKFLOW_ID and query_scope_ok:
        response = session.post(query_url, headers=auth, timeout=300,
                                json={'question': QUERY,
                                      'conversation_id': 'verify-agent-query',
                                      'workflow_id': WORKFLOW_ID})
        if response.status_code == 503:
            print(f'SKIP agent query: 部署未就绪（{body(response)}）')
        else:
            check('agent query -> 200', response.status_code == 200, body(response))
            payload = response.json() if response.status_code == 200 else {}
            answer = payload if isinstance(payload, dict) else {}
            check('agent query -> conversation_id',
                  answer.get('conversation_id') == 'verify-agent-query', body(response))
            check('agent query -> answer', bool(answer.get('answer')), body(response))

    print()
    print(f'summary: failures={len(failures)} warnings={len(warnings)}')
    if warnings:
        print('  warnings:', ', '.join(warnings))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
