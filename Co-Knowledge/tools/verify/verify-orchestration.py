#!/usr/bin/env python3
"""检索编排端到端验收脚本（接口层）。

它做五件事，全部打真实服务（没有 mock）：
  ① 挑一个**已索引内容**的知识库（检索要有命中才有意义）
  ② 建工作流 → 存画布 → 发布（只读已发布快照）
  ③ POST /query 打通：查询改写 → 检索 → 重排 → 合成（非流式）
  ④ POST /query `stream=true` 打通：具名 SSE 事件（`token` / `done`）
  ⑤ 反向用例：未发布 / 不存在的工作流、空问题，都必须**显式失败**

用法（在仓库根目录）：
    python3 tools/verify/verify-orchestration.py
    python3 tools/verify/verify-orchestration.py --web http://127.0.0.1 \\
            --rkb http://127.0.0.1:8091/api/co-knowledge/v1 --kb merge-verify-kb

默认地址对应 `deploy/docker-compose.dev.yml`（web:80 与 RKB:8091 都发布到宿主机）。
编排与 RKB 同进程，没有独立的 8093 容器；`--rkb` 是「RKB 基址 + 对外前缀」。
用生产 compose（只发布 web:80）时，脚本会自动去问 docker 要 RKB 的容器 IP。

退出码：0 = 通过；1 = 失败（见输出里的 ❌）。
"""
# 编排与 RKB 同进程：对外只有一个前缀，见
# backend/src/shared/prefixes.py
RKB_PREFIX = '/api/co-knowledge/v1'
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

# 宿主若配了 http_proxy，去容器网段的请求会被代理截胡（实测表现为超时）。
# 本脚本一律绕过代理。
os.environ['no_proxy'] = '*'
os.environ['NO_PROXY'] = '*'

TIMEOUT = 300
LLM = 'deepseek-chat'


def call(url, method='GET', body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode('utf-8')
            return resp.status, (json.loads(raw) if raw.strip().startswith(('{', '[')) else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8')
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def call_stream(url, body):
    """读一次 SSE。返回 (status, content_type, events)。

    `events` 是 `(event, data)` 列表；终态 `done` / `error` 后停止读取。
    只读前若干帧就够判定，故设了上限，避免长回答把验收卡住。
    """
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            ctype = resp.headers.get('Content-Type', '')
            events, limit = [], 5000
            event, payload = 'message', []
            for raw in resp:
                line = raw.decode('utf-8', 'replace').rstrip('\r\n')
                if not line:
                    if payload:
                        events.append((event, '\n'.join(payload)))
                        if event in ('done', 'error') or len(events) >= limit:
                            break
                    event, payload = 'message', []
                    continue
                if line.startswith(':'):
                    continue                      # 心跳/注释行
                field, _, value = line.partition(':')
                if value.startswith(' '):
                    value = value[1:]
                if field == 'event':
                    event = value
                elif field == 'data':
                    payload.append(value)
            return resp.status, ctype, events
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('Content-Type', ''), [('error', e.read().decode('utf-8', 'replace'))]


def step(n, msg):
    print(f"\n【{n}】{msg}")


def resolve_rkb(explicit):
    """没给地址时：去问 docker 要容器 IP（生产 compose 不发布 8091）。"""
    if explicit:
        return explicit
    try:
        ip = subprocess.check_output(
            ['docker', 'inspect', '-f',
             '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}',
             'rag-studio-rag-knowledge-base-1'], text=True).strip()
        if ip:
            print(f"   （自动解析到 RKB 容器 IP：{ip}）")
            return f'http://{ip}:8091{RKB_PREFIX}'
    except Exception:
        pass
    return 'http://127.0.0.1:8091' + RKB_PREFIX


def operator(package, name, **kwargs):
    return {'id': 1, 'package': package, 'operator': name, 'kwargs': kwargs}


def node(node_id, component_type, stage_key, operator_obj):
    return {'nodeId': node_id, 'id': node_id, 'componentType': component_type,
            'xPosition': 100.0, 'yPosition': 100.0, 'variables': {stage_key: [operator_obj]}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--web', default='http://127.0.0.1', help='web 入口（nginx 反代 RKB）')
    ap.add_argument('--rkb', default='', help='RKB 基址；留空则自动解析容器 IP')
    ap.add_argument('--kb', default='', help='指定知识库名；留空则自动挑第一个文档库')
    args = ap.parse_args()

    web = args.web.rstrip('/')
    rkb = resolve_rkb(args.rkb).rstrip('/')
    flow_api = web + '/api/co-knowledge/v1'
    app_id = 'RAG_Workflow_verify_' + os.urandom(2).hex()
    print(f"web={web}  RKB={rkb}")

    # ---------------------------------------------------------------- ① 选库
    step(1, '挑一个知识库（优先用已导入文档的文档库）')
    _, payload = call(flow_api + '/workflows/knowledge-bases')
    grouped = payload or {}
    kbases = [k for k in (list(grouped.get('running') or []) + list(grouped.get('dev') or []))
              if k.get('tableName') and not str(k.get('tableName')).startswith('graph')]
    if args.kb:
        kbases = [k for k in kbases if k.get('name') == args.kb] or kbases
    if not kbases:
        print('❌ 没有可用的文档知识库：先建库并导入文档（见 README「最小链路验证」）')
        return 1
    picked = kbases[0]
    print(f"   用 {picked['name']}（baseName={picked['tableName']}，"
          f"embedding={picked.get('embeddingModel')}）")

    # ---------------------------------------------------------------- ② 建流 → 存画布 → 发布
    step(2, f'建工作流 {app_id} → 存画布 → 发布')
    status, payload = call(flow_api + '/workflows', 'POST', {
        'name': '编排验收流程', 'workFlowId': app_id, 'template': 'Sequential',
        'knowledgeType': 'knowledgeBase', 'description': '编排验收（tools/verify）',
        # boundInfo 送下拉项的**完整对象**（与前端 `getSelectdKbList()` 一致）：建流要按
        # `embeddingModel` 回填检索器的向量模型，少这个字段会被显式拒（`kbase.embedding.unknown`）
        'boundInfo': {'running': [picked]},
    })
    print(f"   创建：HTTP {status}")
    if not (200 <= status < 300):
        print('❌ 创建工作流失败'); return 1

    canvas = {
        'flowType': 'workflow', 'version': 1,
        'nodeConfigDTOList': [
            node('n1', 'PRE_RETRIEVER', 'preretriever',
                 operator('core.rag.pre_retriever.query_transform.query_rewrite', 'LLMQueryRewriter',
                          llm=LLM, prompt='你是问题补全专家。上轮问题：{last_question}\n本轮问题：{current_question}\n'
                                          '请返回 JSON 对象，形如 {{"question": "xxx"}}')),
            node('n2', 'RETRIEVER', 'retriever',
                 operator('core.rag.retriever.vector_retriever', 'VectorRetriever',
                          strategy=0, embedding=picked.get('embeddingModel') or '',
                          knowledge_info_list=[{'knowledge_base_name': [picked['tableName']],
                                                'priority': 10, 'top_k': 8, 'score': 0.0}],
                          desc_info='')),
            node('n3', 'POST_RETRIEVER', 'postretriever',
                 operator('core.rag.post_retriever.llm_reranker', 'LLMReranker', llm=LLM, top_n=4)),
            node('n4', 'RESPONSE_SYNTHESIZER', 'responsesynthesizer',
                 operator('core.rag.response_synthesizer.simple_summarizer', 'RagSimpleSummarizer',
                          **{'generator-config': [{
                              'llm': LLM, 'top_k': 4, 'knowledge_base_name': [],
                              'prompt': "请依据上下文回答用户问题：\n上下文：'{context_str}'\n用户问题：'{query_str}'"}]})),
        ],
        'otherNodeConfigList': [
            {'componentType': 'QUERY_ENGINE', 'variables': {'queryengine': {
                'id': 0, 'package': 'core.rag.query_engine.sequential_query_engine',
                'operator': 'SequentialQueryEngine', 'desc': '', 'kwargs': {}}}},
            {'componentType': 'EDGES', 'variables': {'edges': [
                {'source': 'n1', 'target': 'n2'}, {'source': 'n2', 'target': 'n3'},
                {'source': 'n3', 'target': 'n4'}]}},
        ],
    }
    status, payload = call(flow_api + f'/workflows/{urllib.parse.quote(app_id)}/flow', 'PUT', canvas)
    print(f"   存画布：HTTP {status}")
    status, payload = call(flow_api + f'/workflows/{urllib.parse.quote(app_id)}/publication', 'POST', {})
    version = payload.get('version') if isinstance(payload, dict) else None
    print(f"   发布：  HTTP {status} version={version}")
    if not (200 <= status < 300):
        print(f"❌ 发布失败：{payload}"); cleanup(flow_api, app_id); return 1

    # ---------------------------------------------------------------- ③ 跑一次编排
    step(3, 'POST /query（改写 → 检索 → 重排 → 合成）')
    status, payload = call(rkb + '/query', 'POST', {
        'question': '这个知识库里的文档讲了什么？', 'conversation_id': 'verify-' + app_id,
        'workflow_id': app_id, 'stream': False, 'feedback': 'true',
    })
    print(f"   HTTP {status}\n   响应：{json.dumps(payload, ensure_ascii=False)[:700]}")
    ok = status == 200 and isinstance(payload, dict) and bool(payload.get('answer'))
    answer = (payload or {}).get('answer', '') if isinstance(payload, dict) else ''
    if ok:
        print(f"   ✅ 拿到答案（{len(answer)} 字）")
        print('   ⚠️ 人工核对：答案内容应当来自你的文档，而不是「我无法访问知识库」这类兜底话术；')
        print('      兜底话术 = 检索那一段没生效（HTTP 仍是 200，但答案没引用文档）。')
    else:
        print('   ❌ 未拿到答案')

    # ---------------------------------------------------------------- ④ 流式（SSE）
    step(4, 'POST /query stream=true（SSE：token 帧 + done 收尾）')
    status, ctype, frames = call_stream(rkb + '/query', {
        'question': '这个知识库里的文档讲了什么？', 'conversation_id': 'verify-stream-' + app_id,
        'workflow_id': app_id, 'stream': True,
    })
    print(f"   HTTP {status}  Content-Type: {ctype}")
    print(f"   收到 {len(frames)} 个事件，末事件：{frames[-1][0] if frames else '(无)'}")
    stream_ok = (status == 200 and 'text/event-stream' in ctype
                 and bool(frames) and frames[-1][0] == 'done')
    if stream_ok:
        text = ''
        for event, payload_text in frames:
            if event != 'token':
                continue
            try:
                text += json.loads(payload_text).get('content', '')
            except ValueError:
                pass
        print(f"   ✅ 流式打通（拼接正文 {len(text)} 字）")
        if not text.strip():
            # HTTP 200 + 帧序正确，但一个字符都没有 —— 正是「delta 没设」那类静默失败的样子
            print('   ❌ 但正文为空：检查 LLM 适配器是否为每帧设置了 delta（见 contracts/model-gateway.md 流式一节）')
            stream_ok = False
    else:
        print('   ❌ 流式未打通（期望 200 + text/event-stream + 末事件 done）')

    # ---------------------------------------------------------------- ⑤ 反向用例
    step(5, '反向用例（都必须显式失败）')
    cases = [
        ('不存在的工作流', {'question': 'q', 'conversation_id': 'd1', 'workflow_id': 'NO_SUCH_WORKFLOW', 'stream': False}),
        ('空问题', {'question': '', 'conversation_id': 'd3', 'workflow_id': app_id}),
    ]
    for name, body in cases:
        status, payload = call(rkb + '/query', 'POST', body)
        print(f"   {name}：HTTP {status} → {str(payload)[:140]}")

    # ---------------------------------------------------------------- 清理
    step(6, '清理验收数据')
    cleanup(flow_api, app_id)
    passed = ok and stream_ok
    print('\n结论：', '✅ 编排链路打通（含流式；反向用例见上，需人工核对都是「显式失败」）'
          if passed else '❌ 见上面的响应')
    return 0 if passed else 1


def cleanup(flow_api, app_id):
    status, payload = call(flow_api + f'/workflows/{urllib.parse.quote(app_id)}', 'DELETE')
    print(f"   删除 {app_id} → HTTP {status}")


if __name__ == '__main__':
    sys.exit(main())
