#!/usr/bin/env python3
"""三种建流模板的端到端验收：顺序检索 / 混合检索 / 条件检索。

与 `verify-orchestration.py` 的分工：那个脚本自己拼一份**手写画布**去验编排链路
（改不动模板也照样过），这个脚本**不写画布**，只用建流接口播种出来的默认画布 ——
验的正是模板本身：

  ① 建流（template=三者之一）→ 读回画布：引擎对、节点齐、连线条数对；
  ② 画布里的绑定（知识库名 / 向量模型）在**两份 variables 里都在**
     （前端保存回写的是 `data.variables`，只填一份时「打开画布再保存」会静默丢绑定）；
  ③ 发布（走发布的硬门槛校验）→ `POST /query` 真的拿到答案。

用法（仓库根目录）::

    python3 tools/verify/verify-workflow-templates.py
    python3 tools/verify/verify-workflow-templates.py --kb merge-verify-kb
    python3 tools/verify/verify-workflow-templates.py --keep      # 保留验收工作流

退出码：0 = 三个模板全通过；1 = 有失败（见输出里的 ❌）。
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

# 宿主若配了 http_proxy，去容器网段的请求会被代理截胡（实测表现为超时）。本脚本一律绕过。
os.environ['no_proxy'] = '*'
os.environ['NO_PROXY'] = '*'

TIMEOUT = 300

#: 模板 → 编排引擎（画布 `otherNodeConfigList` 里的 QUERY_ENGINE 伪节点）
ENGINE_OF_TEMPLATE = {
    'Sequential': 'SequentialQueryEngine',
    'Blended': 'BlendedQueryEngine',
    'Conditional': 'ConditionalQueryEngine',
}
#: 模板 → 画布上该有的检索算子（引擎已按画布重建连线；这里只核对「路径都在」）
RETRIEVERS_OF_TEMPLATE = {
    'Sequential': {'VectorRetriever'},
    'Blended': {'KeywordRetriever', 'VectorRetriever', 'FusionRetriever'},
    'Conditional': {'KeywordRetriever', 'VectorRetriever'},
}
#: 模板 → 连线条数。定死是为了抓「分支被摊平成一条链」：13 节点 9 条边 vs 8 条边，
#: 摊平后条数会变，而保存、发布、preCheck 都不会报错。
EXPECTED_EDGES = {'Sequential': 5, 'Blended': 8, 'Conditional': 9}


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
            return f'http://{ip}:8091{RKB_PREFIX}'
    except Exception:
        pass
    return 'http://127.0.0.1:8091' + RKB_PREFIX


def unwrap(payload):
    """纯 REST：problem body（含 status）→ (code, detail)，成功 → ('0000', '')。"""
    if isinstance(payload, dict) and 'status' in payload and 'code' in payload:
        return str(payload.get('code')), str(payload.get('detail') or '')
    return '0000', ''


def operators_of(node_config, stage_key):
    result = []
    for node in node_config:
        for container in (node.get('variables'), (node.get('data') or {}).get('variables')):
            if not isinstance(container, dict):
                continue
            stage = container.get(stage_key)
            if isinstance(stage, list):
                result.extend(stage)
    return result


def knowledge_names(operator):
    kwargs = operator.get('kwargs') or {}
    if isinstance(kwargs.get('knowledge_base_name'), list):
        return kwargs['knowledge_base_name']
    for info in kwargs.get('knowledge_info_list') or []:
        if isinstance(info.get('knowledge_base_name'), list):
            return info['knowledge_base_name']
    return []


def variable_copies(node):
    """节点的两份 variables：`variables` 与 `data.variables`（前端保存时用的是后者）。"""
    return node.get('variables'), (node.get('data') or {}).get('variables')


def simulate_frontend_save(canvas):
    """按前端 `exportGraph()` 的口径重造一份保存报文。

    前端画布把算子存了两份（`variables` 与 `data.variables`）：显示读 `data.variables`，
    **保存时也按它回写顶层 `variables`**（前端即
    `item.variables = targetItem.store.data?.data?.variables`）。所以这里照做一遍 ——
    播种只填一份时，这一遍就会把绑定冲掉，而发布不报错、日志也不报错。
    """
    saved = json.loads(json.dumps(canvas))
    nodes = saved.get('nodeConfigDTOList') or []
    for node in nodes:
        nested = (node.get('data') or {}).get('variables')
        if nested is not None:
            node['variables'] = json.loads(json.dumps(nested))
    edges = next((node for node in (saved.get('otherNodeConfigList') or [])
                  if node.get('componentType') == 'EDGES'), None)
    if edges:
        for node in nodes:
            node['outputVariables'] = [
                {'key': 'text', 'targetNode': edge['target']}
                for edge in edges['variables'].get('edges', []) if edge['source'] == node['nodeId']]
    return saved


def check_canvas(template, canvas, kbase_name):
    """画布检查：引擎 / 连线 / **逐算子逐副本的绑定** / 分支走向。返回问题列表。

    检查刻意做**细**：这条链路上最贵的是静默失败（保存成功、发布成功、HTTP 200，
    只是检索不到东西），所以「某一路检索器没绑上库」「合成器没绑库」「两条分支共用
    一个合成器」都必须在这里判成问题，而不是靠人工看答案像不像。
    """
    problems = []
    node_config = canvas.get('nodeConfigDTOList') or []
    other = canvas.get('otherNodeConfigList') or []

    engine_node = [n for n in other if n.get('componentType') == 'QUERY_ENGINE']
    engine = ((engine_node[0].get('variables') or {}).get('queryengine') or {}).get('operator') \
        if engine_node else None
    if engine != ENGINE_OF_TEMPLATE[template]:
        problems.append(f'引擎是 {engine!r}，期望 {ENGINE_OF_TEMPLATE[template]!r}')

    edges_node = [n for n in other if n.get('componentType') == 'EDGES']
    pairs = [{'source': edge.get('source'), 'target': edge.get('target')}
             for edge in ((edges_node[0].get('variables') or {}).get('edges') or [])] if edges_node else []
    edge_count = len(pairs)
    if not edge_count:
        problems.append('画布没有连线')
    elif edge_count != EXPECTED_EDGES[template]:
        problems.append(f'连线条数是 {edge_count}，模板应当有 {EXPECTED_EDGES[template]} 条'
                        '（少了就是分支被摊平）')

    retrievers = {op.get('operator') for op in operators_of(node_config, 'retriever')}
    missing = RETRIEVERS_OF_TEMPLATE[template] - retrievers
    if missing:
        problems.append(f'少了检索算子 {sorted(missing)}')

    for node in node_config:
        top, nested = variable_copies(node)
        if json.dumps(top, sort_keys=True, ensure_ascii=False) != \
                json.dumps(nested, sort_keys=True, ensure_ascii=False):
            problems.append(f"{node.get('componentType')} 的两份 variables 不一致")
        for label, container in (('variables', top), ('data.variables', nested)):
            problems.extend(_check_bindings(label, node.get('componentType'), container, kbase_name))

    problems.extend(_check_branch_wiring(template, node_config, pairs))
    return problems, edge_count, sorted(retrievers)


def _check_bindings(label, component_type, container, kbase_name):
    """一份 ``variables`` 里的绑定：每个检索器（融合器除外）与每个合成器都要绑上库。"""
    problems = []
    if not isinstance(container, dict):
        return problems
    for operator in container.get('retriever') or []:
        if operator.get('operator') == 'FusionRetriever':
            continue                      # 融合器只合并下游结果，本身没有绑定字段
        names = knowledge_names(operator)
        if names != [kbase_name]:
            problems.append(f'{label}/{component_type}/{operator.get("operator")} 绑的是 {names}，'
                            f'期望 [{kbase_name!r}]')
        kwargs = operator.get('kwargs') or {}
        if 'embedding' in kwargs and not kwargs.get('embedding'):
            problems.append(f'{label}/{component_type}/{operator.get("operator")} 的向量模型是空的')
    for operator in container.get('responsesynthesizer') or []:
        for config in (operator.get('kwargs') or {}).get('generator-config') or []:
            if config.get('knowledge_base_name') != [kbase_name]:
                problems.append(f'{label}/{component_type}/合成器 的 generator-config 绑的是 '
                                f'{config.get("knowledge_base_name")}，期望 [{kbase_name!r}]')
    return problems


def _check_branch_wiring(template, node_config, pairs):
    """分支走向：每条检索路径都要能走到**自己的**后检索/合成器。

    条件检索是两条分支，每条各带一个合成器。分支被摊平成一条链时（保存/发布都不报错），
    这里会看到两条路径共用同一个合成器 —— 正是最该拦下的退化。
    """
    problems = []
    has_retriever = {}
    has_synthesizer = {}
    for node in node_config:
        variables = node.get('variables') or {}
        node_id = node.get('nodeId') or node.get('id')
        has_retriever[node_id] = bool(variables.get('retriever'))
        has_synthesizer[node_id] = bool(variables.get('responsesynthesizer'))

    reached = {}
    for node_id, is_retriever in has_retriever.items():
        if not is_retriever:
            continue
        chain = _chain_all_nodes(pairs, node_id)
        synthesizers = [reached_node for reached_node in chain if has_synthesizer.get(reached_node)]
        if len(synthesizers) != 1:
            problems.append(f'检索节点 {node_id} 走到 {len(synthesizers)} 个合成器（应为 1 个）')
        reached[node_id] = synthesizers[0] if synthesizers else None

    if template == 'Conditional' and len(set(reached.values())) != len(reached):
        problems.append(f'两条分支共用了同一个合成器：{reached}（分支被摊平了）')
    return problems


def _chain_all_nodes(pairs, start):
    """与运行期 `RagContext._scan_next_node` 一致：每步取**第一条**出边，不回头。"""
    found = []

    def scan(current):
        for pair in pairs:
            if pair['source'] == current and pair['target'] not in found:
                found.append(pair['target'])
                scan(pair['target'])
                break

    scan(start)
    return found


def run_template(web, rkb, template, picked, keep):
    flow_api = web + '/api/co-knowledge/v1'
    app_id = f'RAG_Workflow_vt_{template.lower()}'
    print(f'\n【{template}】建流 {app_id}（绑 {picked["name"]}）')

    call(flow_api + f'/workflows/{urllib.parse.quote(app_id)}', 'DELETE')  # 清掉上次残留
    # boundInfo 直接送**下拉项的完整对象**（前端 `getSelectdKbList()` 就是这么送的）：
    # 建流要按 `embeddingModel` 回填检索器的向量模型，少这个字段会被显式拒
    # （`kbase.embedding.unknown`）—— 猜一个默认值会让检索静默查不到东西。
    status, payload = call(flow_api + '/workflows', 'POST', {
        'name': f'模板验收-{template}', 'workFlowId': app_id, 'template': template,
        'knowledgeType': 'knowledgeBase', 'description': 'tools/verify 模板验收',
        'boundInfo': {'running': [picked]},
    })
    code, msg = unwrap(payload)
    if code != '0000':
        print(f'   ❌ 建流失败：{code} {msg}')
        return False
    print(f'   建流 OK（HTTP {status}）')

    _, payload = call(flow_api + f'/workflows/{urllib.parse.quote(app_id)}/flow')
    canvas = payload or {}
    problems, edge_count, retrievers = check_canvas(template, canvas, picked['tableName'])
    print(f"   画布：{len(canvas.get('nodeConfigDTOList') or [])} 节点 / {edge_count} 条边 / "
          f"检索器 {retrievers}")
    if problems:
        for problem in problems:
            print(f'   ❌ {problem}')
        return False
    print('   ✅ 引擎、连线、绑定（两份 variables）都对')

    # 模拟「用户在画布上点保存」：报文按前端 exportGraph() 的口径重造一遍再存回去，
    # 然后重新读回来看绑定还在不在（只填一份 variables 时，这一步就会把绑定冲掉）
    status, payload = call(flow_api + f'/workflows/{urllib.parse.quote(app_id)}/flow', 'PUT',
                           simulate_frontend_save(canvas))
    if unwrap(payload)[0] != '0000':
        print(f'   ❌ 模拟保存失败：{unwrap(payload)}')
        return False
    _, payload = call(flow_api + f'/workflows/{urllib.parse.quote(app_id)}/flow')
    problems, _, _ = check_canvas(template, payload or {}, picked['tableName'])
    if problems:
        for problem in problems:
            print(f'   ❌ 保存一轮后：{problem}')
        return False
    print('   ✅ 模拟「打开画布 → 保存」一轮后，绑定仍在')

    _, payload = call(flow_api + f'/workflows/{urllib.parse.quote(app_id)}/publication', 'POST', {})
    code, msg = unwrap(payload)
    if code != '0000':
        print(f'   ❌ 发布失败：{code} {msg}')
        return False
    print(f'   发布 OK（version={(payload or {}).get("version")}）')

    status, payload = call(rkb + '/query', 'POST', {
        'question': '这个知识库里的文档讲了什么？', 'conversation_id': 'vt-' + app_id,
        'workflow_id': app_id, 'stream': False, 'feedback': 'true',
    })
    answer = (payload or {}).get('answer') or ''
    ok = status == 200 and bool(answer)
    print(f"   问答：HTTP {status} 答案 {len(answer)} 字")
    if not ok:
        print(f'   ❌ 未拿到答案：{json.dumps(payload, ensure_ascii=False)[:300]}')
    else:
        print(f'   答案片段：{answer[:120]!r}')
        print('   ⚠️ 人工核对：答案要来自文档，而不是「无法访问知识库」这类兜底话术'
              '（兜底话术 = 检索那一段没生效，HTTP 仍是 200）')

    if not keep:
        call(flow_api + f'/workflows/{urllib.parse.quote(app_id)}', 'DELETE')
        print('   已清理验收工作流')
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--web', default='http://127.0.0.1', help='web 入口（nginx 反代）')
    ap.add_argument('--rkb', default='', help='RKB 基址；留空自动解析容器 IP')
    ap.add_argument('--kb', default='', help='指定知识库名；留空则自动挑第一个文档库')
    ap.add_argument('--keep', action='store_true', help='保留验收工作流（不删）')
    args = ap.parse_args()

    web = args.web.rstrip('/')
    rkb = resolve_rkb(args.rkb).rstrip('/')
    flow_api = web + '/api/co-knowledge/v1'
    print(f'web={web}  RKB={rkb}')

    _, payload = call(flow_api + '/workflows/knowledge-bases')
    grouped = payload or {}
    kbases = [kb for kb in (list(grouped.get('running') or []) + list(grouped.get('dev') or []))
              if kb.get('tableName') and not str(kb.get('tableName')).startswith('graph')]
    if args.kb:
        kbases = [kb for kb in kbases if kb.get('name') == args.kb] or kbases
    if not kbases:
        print('❌ 没有可用的文档知识库：先建库并导入文档（见 README「最小链路验证」）')
        return 1
    picked = kbases[0]
    print(f'用 {picked["name"]}（baseName={picked["tableName"]}，'
          f'embedding={picked.get("embeddingModel")}）')

    results = {template: run_template(web, rkb, template, picked, args.keep)
               for template in ('Sequential', 'Blended', 'Conditional')}
    print('\n结论：')
    for template, ok in results.items():
        print(f'   {template:12} {"✅ 通过" if ok else "❌ 失败"}')
    return 0 if all(results.values()) else 1


if __name__ == '__main__':
    sys.exit(main())
