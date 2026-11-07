#!/usr/bin/env python3
"""Agent MCP（Streamable HTTP）端到端验收。

容器内有 mcp 客户端，推荐这样跑（不落盘）：

    docker compose -f deploy/docker-compose.yml exec -T \
      -e RKB_AGENT_TEST_KEY="$KEY" \
      -e RKB_AGENT_MCP_URL=http://127.0.0.1:8091/api/co-knowledge/v1/mcp \
      rag-knowledge-base python3 - < tools/verify/verify-agent-mcp.py

也可以直接用宿主已安装的 ``mcp``：

    RKB_AGENT_TEST_KEY=ragk_... python3 tools/verify/verify-agent-mcp.py

可选：``RKB_AGENT_MCP_URL``（默认 http://127.0.0.1/api/co-knowledge/v1/mcp）、
``RKB_AGENT_TEST_QUERY``、``RKB_AGENT_TEST_WORKFLOW``（已发布工作流 ID；提供时
额外验证 ``run_workflow`` 的 JSON 与 ``stream=true``（MCP progress 通知）两条路）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import requests

URL = os.environ.get('RKB_AGENT_MCP_URL', 'http://127.0.0.1/api/co-knowledge/v1/mcp').rstrip('/')
KEY = (os.environ.get('RKB_AGENT_TEST_KEY') or '').strip()
QUERY = os.environ.get('RKB_AGENT_TEST_QUERY', '这是一段用于验证任务队列的正文')
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


def _text(result) -> str:
    content = getattr(result, 'content', None) or []
    if not content:
        return ''
    return getattr(content[0], 'text', '') or ''


async def run_positive() -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {'Authorization': f'Bearer {KEY}'}
    async with streamablehttp_client(URL, headers=headers) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            check('mcp initialize', True)

            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            check('mcp tools/list', names == {
                'list_knowledge_bases', 'search_knowledge', 'ask_knowledge_base',
                'list_workflows', 'run_workflow'}, str(names))

            result = await session.call_tool('list_knowledge_bases', {})
            check('mcp list_knowledge_bases', getattr(result, 'isError', True) is False,
                  _text(result)[:300])
            try:
                payload = json.loads(_text(result))
            except ValueError:
                payload = {}
            knowledge_bases = payload.get('knowledge_bases') or []
            check('mcp list_knowledge_bases non-empty', bool(knowledge_bases),
                  _text(result)[:300])

            result = await session.call_tool('search_knowledge',
                                             {'query': QUERY, 'top_k': 5})
            check('mcp search_knowledge', getattr(result, 'isError', True) is False,
                  _text(result)[:300])
            try:
                search_payload = json.loads(_text(result))
            except ValueError:
                search_payload = {}
            if not (search_payload.get('results') or []):
                warn('mcp search_knowledge empty', f'query={QUERY!r}')

            result = await session.call_tool('ask_knowledge_base',
                                             {'question': QUERY, 'top_k': 5})
            if getattr(result, 'isError', False) and 'answer_unavailable' in _text(result):
                print('SKIP mcp ask_knowledge_base: 未配置生成模型')
            else:
                check('mcp ask_knowledge_base', getattr(result, 'isError', True) is False,
                      _text(result)[:300])

            result = await session.call_tool('list_workflows',
                                             {'publish_type': 1, 'size': 5})
            if getattr(result, 'isError', False) and 'forbidden_scope' in _text(result):
                print('SKIP mcp list_workflows: Key 未授予 workflow:read')
            else:
                check('mcp list_workflows', getattr(result, 'isError', True) is False,
                      _text(result)[:300])

            if not WORKFLOW_ID:
                print('SKIP mcp run_workflow: 未设置 RKB_AGENT_TEST_WORKFLOW')
            else:
                await _run_workflow(session, stream=False)
                await _run_workflow(session, stream=True)


async def _run_workflow(session, *, stream: bool) -> None:
    """执行一次已发布工作流；stream=True 时同时核对 progress 通知。"""
    label = 'mcp run_workflow(stream)' if stream else 'mcp run_workflow'
    progress = []

    async def _on_progress(value, total, message):
        progress.append((value, message))

    arguments = {'question': QUERY, 'conversation_id': 'verify-agent-mcp',
                 'workflow_id': WORKFLOW_ID}
    if stream:
        arguments['stream'] = True
    result = await session.call_tool('run_workflow', arguments,
                                     progress_callback=_on_progress if stream else None)
    if getattr(result, 'isError', False) and 'forbidden_scope' in _text(result):
        print(f'SKIP {label}: Key 未授予 workflow:run')
        return
    check(label, getattr(result, 'isError', True) is False, _text(result)[:300])
    try:
        payload = json.loads(_text(result))
    except ValueError:
        payload = {}
    check(f'{label} -> conversation_id',
          payload.get('conversation_id') == 'verify-agent-mcp', _text(result)[:300])
    check(f'{label} -> answer', bool(payload.get('answer')), _text(result)[:300])
    if stream:
        # 工具结果仍是完整答案；token 以 progress 通知旁路送达（节流后至少一条）
        check(f'{label} -> progress notifications', bool(progress),
              f'progress={progress[:3]}')


def run_negative() -> None:
    headers = {'Content-Type': 'application/json',
               'Accept': 'application/json, text/event-stream'}
    body = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                       'clientInfo': {'name': 'verify', 'version': '0'}}}
    response = requests.post(URL, headers=headers, json=body, timeout=30)
    check('mcp missing key -> 401', response.status_code == 401, response.text[:300])


def main() -> int:
    if not KEY:
        print('缺少 RKB_AGENT_TEST_KEY', file=sys.stderr)
        return 2
    run_negative()
    asyncio.run(run_positive())
    print()
    print(f'summary: failures={len(failures)} warnings={len(warnings)}')
    if warnings:
        print('  warnings:', ', '.join(warnings))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
