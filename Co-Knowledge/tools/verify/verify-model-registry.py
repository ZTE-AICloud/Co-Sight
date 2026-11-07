"""模型注册表端到端验收：**证明「不停机新增模型」这句主张**。

这是本功能唯一不能靠单测覆盖的性质 —— 单测证明「解析层会读注册表」，
只有真打服务才能证明「接口写完，**没有重启任何容器**，所有消费面立刻跟着变」。

链路（每一环都是真的，不打桩）::

    ① 读基线：/models 列表 + 两个消费面（画布下拉 / system/llm-models）的当前内容
    ② 注册一个新 LLM（指向**当前真实在用的那个生成端点**，只换显示名）
    ②b PUT 更新刚注册的那行（改名）→ 消费面立刻跟着变、**行数不变**
    ③ 不重启任何东西，立刻再读两个消费面 → 必须多出这一条
    ④ 连接测试打真端点 → **真实调用必须成功**，并探到模型清单
    ⑤ 注册一个 embedding（指向当前真实 embedding 端点，维度 1024）
       → /system/embedding-models 里出现，且实测维度与登记一致
    ⑥ 删掉两条 → 消费面**逐项复原**（不留残渣；本仓对验收脚本留残留有前车之鉴）

跑法（宿主机，直连 nginx）::

    python3 tools/verify/verify-model-registry.py

前提：栈在跑（`docker compose -f deploy/docker-compose.yml up -d`）。
**脚本会自行清理**：除非中途异常退出时被 Ctrl-C，注册的两条会被删掉。
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

os.environ.pop('http_proxy', None)
os.environ.pop('HTTP_PROXY', None)

WEB = os.environ.get('WEB', 'http://127.0.0.1/api/co-knowledge/v1')

#: 注册的测试模型名：带前缀，便于一眼看出是验收脚本留下的
LLM_NAME = 'verify-registry-llm'
EMBEDDING_NAME = 'verify-registry-embedding'

failures = []


def call(method, path, body=None, timeout=120):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        WEB + path, data=data, method=method,
        headers={'X-Emp-No': 'admin', 'Accept-Language': 'zh-CN',
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read() or b'{}')
    except urllib.error.HTTPError as e:
        return {'_http': e.code, '_body': e.read()[:200].decode('utf-8', 'replace')}
    except Exception as e:
        return {'_err': f'{type(e).__name__}: {e}'}


def ok(label, condition, detail=''):
    print(f'  {"ok  " if condition else "FAIL"} {label}{("：" + detail) if detail else ""}')
    if not condition:
        failures.append(f'{label} {detail}')


def envelope_bo(payload):
    """纯 REST：2xx body 就是资源；HTTPError 由 call() 标成 `_http`。"""
    if not payload or payload.get('_http'):
        return None
    return payload


def model_names(kind):
    bo = envelope_bo(call('GET', f'/models?kind={kind}&pageSize=200'))
    if not bo:
        return None
    return [row['modelName'] for row in bo.get('items') or []]


def canvas_models():
    """画布「大模型」下拉（与 system/llm-models 共用 `GET /system/llm-models`）。"""
    bo = envelope_bo(call('GET', '/system/llm-models'))
    if bo is None:
        return None
    return [(item.get('value'), item.get('label')) for item in bo or []]


def zaetask_llm_list():
    """建图谱/分块优化页的必填下拉（`{value, label}`）。"""
    bo = envelope_bo(call('GET', '/system/llm-models'))
    if bo is None:
        return None
    return [(item.get('value'), item.get('label')) for item in bo or []]


def embedding_all():
    bo = envelope_bo(call('GET', '/system/embedding-models'))
    if bo is None:
        return None
    return list(bo or [])


def find_row(kind, name):
    bo = envelope_bo(call('GET', f'/models?kind={kind}&pageSize=200'))
    for row in (bo or {}).get('items') or []:
        if row['modelName'] == name:
            return row
    return None


def main():
    print('=== 模型注册表端到端验收 ===')

    # ---- ① 基线 --------------------------------------------------------
    print('\n① 读基线')
    baseline_llm_rows = model_names('llm')
    baseline_canvas = canvas_models()
    baseline_zaetask = zaetask_llm_list()
    baseline_embeddings = embedding_all()
    if not all(x is not None for x in
               (baseline_llm_rows, baseline_canvas, baseline_zaetask, baseline_embeddings)):
        print('基线读取失败 —— 栈没起来或前缀不对，先修好再跑本脚本。')
        return 1
    ok('基线：/models 有 LLM 行', len(baseline_llm_rows) > 0, f'{len(baseline_llm_rows)} 条')
    ok('基线：画布下拉非空', len(baseline_canvas) > 0, f'{len(baseline_canvas)} 条')
    ok('基线：system/llm-models 非空', len(baseline_zaetask) > 0, f'{len(baseline_zaetask)} 条')

    # 注册用的端点/参数全部从**当前默认模型**抄 —— 保证「新增的这条」在真实端点上可用，
    # 否则连接测试会红，而那是端点不可达、不是注册表的问题
    anchor = find_row('llm', baseline_canvas[0][0]) or find_row('llm', baseline_llm_rows[0])
    if anchor is None:
        print('找不到可作锚点的默认 LLM 行，无法继续。')
        return 1

    created = {'llm': None, 'embedding': None}
    try:
        # ---- ② 思考预置目录 --------------------------------------------
        print('\n② 读取思考预置目录（按当前模型名自动匹配）')
        catalog = envelope_bo(call(
            'GET',
            '/models/thinking-presets?modelName='
            + urllib.parse.quote(anchor['modelName'])))
        ok('预置目录非空', bool(catalog and catalog.get('presets')),
           f'{len((catalog or {}).get("presets") or [])} 条')
        ok('预置目录带允许键与大小上限',
           bool(catalog and catalog.get('allowedPayloadKeys')
                and catalog.get('maxPayloadBytes')))

        # ---- ③ 注册新 LLM ----------------------------------------------
        print('\n③ 注册一个新 LLM（指向当前在用的生成端点）')
        bo = envelope_bo(call('POST', '/models', {
            'modelKind': 'llm',
            'modelName': LLM_NAME,
            'displayName': '验收用模型',
            'baseUrl': anchor['baseUrl'],
            'apiKey': '',                      # 端点 key 在库里那把上，这里不用重填
            'chatPath': anchor['chatPath'],
            'modelsPath': anchor['modelsPath'],
            'timeout': anchor['timeout'],
            'thinkingMode': 'preset',
            'thinkingPreset': 'deepseek-vllm',
        }))
        if not bo:
            print('注册失败，后续不跑了。')
            return 1
        created['llm'] = bo['modelId']
        ok('注册返回了 modelId', bool(bo['modelId']))
        ok('preset 思考配置往返',
           bo.get('thinkingMode') == 'preset'
           and bo.get('thinkingPreset') == 'deepseek-vllm'
           and bo.get('thinkingPayload') == {'chat_template_kwargs': {'thinking': False}},
           str(bo.get('thinkingPayload')))

        # ---- ②b PUT 更新 ---------------------------------------------------
        # 前端「编辑」保存走的就是它。钉两件事：改名立刻透到消费面；
        # **行数不变**（编辑若误发 POST，会「保存成功」但原行没动、静默多出
        # 一条重复行）。
        print('\n③b PUT 更新刚注册的 LLM（改名 → 消费面 / 行数）')
        rows_before_update = model_names('llm') or []
        updated = envelope_bo(call('PUT', f'/models/{created["llm"]}', {
            'displayName': '验收用模型（已改名）',
        }))
        ok('PUT 返回 0000', bool(updated))
        ok('部分 PUT 保留思考配置',
           updated.get('thinkingMode') == 'preset'
           and updated.get('thinkingPreset') == 'deepseek-vllm',
           f'{updated.get("thinkingMode")}/{updated.get("thinkingPreset")}')
        ok('PUT 是按主键改、不是新建（LLM 行数不变）',
           len(model_names('llm') or []) == len(rows_before_update),
           f'{len(model_names("llm") or [])} vs 改前 {len(rows_before_update)}')
        ok('改名立刻透到画布下拉',
           (LLM_NAME, '验收用模型（已改名）') in (canvas_models() or []))
        # 改回原名，不扰动后面 ③ 的断言
        envelope_bo(call('PUT', f'/models/{created["llm"]}', {'displayName': '验收用模型'}))

        # ---- ③ 不重启，读消费面 ----------------------------------------
        print('\n④ 不重启任何容器，立刻读两个消费面')
        now_canvas = canvas_models()
        now_zaetask = zaetask_llm_list()
        ok('画布下拉立刻多出该模型',
           (LLM_NAME, '验收用模型') in (now_canvas or []),
           f'{len(now_canvas or [])} 条（基线 {len(baseline_canvas)}）')
        ok('system/llm-models 立刻多出该模型',
           (LLM_NAME, '验收用模型') in (now_zaetask or []),
           f'{len(now_zaetask or [])} 条（基线 {len(baseline_zaetask)}）')
        ok('两条消费面用的是**同一份**清单',
           sorted(now_canvas or []) == sorted(now_zaetask or []))
        ok('该模型已被登记为可选（不再需要改 .env + 重建）',
           LLM_NAME in (model_names('llm') or []))
        listing = find_row('llm', LLM_NAME)
        ok('列表里密钥显示为脱敏/未配置（不回明文）',
           listing is not None and 'apiKey' not in listing)
        ok('列表返回思考配置',
           listing is not None
           and listing.get('thinkingMode') == 'preset'
           and listing.get('thinkingPreset') == 'deepseek-vllm')

        # ---- ④ 连接测试打真端点 -----------------------------------------
        print('\n⑤ 连接测试（真实调用 + 清单探测）')
        # 测**带 key 的那一行**（就是锚点本身）：端点是 LiteLLM，不带 Authorization 会 401。
        # LLM 的判据是 `chatOk`（真实 POST /chat/completions），清单只作补充信息 ——
        # 实测过 qwen3-32b 在清单里但调用 404，只看清单会假绿。
        anchor_id = anchor['modelId']
        result = envelope_bo(call('POST', f'/models/{anchor_id}/test', {}))
        ok('连接测试返回了结果', isinstance(result, dict))
        if isinstance(result, dict):
            ok('真实调用成功（chatOk）且探到模型清单',
               result.get('chatOk') is True and result.get('probed') is True,
               str(result.get('message'))[:120])
            ok('实测耗时已记录', int(result.get('latencyMs') or -1) >= 0,
               f"{result.get('latencyMs')}ms")

        # 刚注册的那一行**没有** key（上面刻意留空）：清单与真实调用都失败，
        # 必须如实报成失败，而不是因为没有 key 就宣称可用。
        result = envelope_bo(call('POST', f'/models/{created["llm"]}/test', {}))
        ok('无 key 的行：真实调用与清单探测都如实报失败',
           isinstance(result, dict) and result.get('ok') is False
           and result.get('chatOk') is False and result.get('probed') is None,
           str(result.get('message'))[:80] if isinstance(result, dict) else '')

        # ---- ⑤ 注册 embedding 并验证维度 ---------------------------------
        print('\n⑥ 注册一个新 embedding（同端点、同维度）')
        embed_row = find_row('embedding', baseline_embeddings[0]) if baseline_embeddings else None
        if embed_row is None:
            print('找不到可作锚点的 embedding 行，跳过这一步。')
        else:
            bo = envelope_bo(call('POST', '/models', {
                'modelKind': 'embedding',
                'modelName': EMBEDDING_NAME,
                'apiModel': embed_row['apiModel'],
                'baseUrl': embed_row['baseUrl'],
                'embeddingsPath': embed_row['embeddingsPath'],
                'dimension': embed_row['dimension'],
            }))
            if not bo:
                print('embedding 注册失败，跳过这一步。')
            else:
                created['embedding'] = bo['modelId']
                ok('embedding 立刻出现在 /system/embedding-models',
                   EMBEDDING_NAME in (embedding_all() or []))
                result = envelope_bo(call('POST', f'/models/{created["embedding"]}/test', {}))
                ok('实测维度与登记一致',
                   isinstance(result, dict) and result.get('dimensionMatches') is True,
                   f"实测 {result.get('dimension') if isinstance(result, dict) else '?'}")
    finally:
        # ---- ⑥ 清理 ----------------------------------------------------
        print('\n⑦ 清理（删除本次注册的行，断言消费面逐项复原）')
        for kind, model_id in created.items():
            if not model_id:
                continue
            envelope_bo(call('DELETE', f'/models/{model_id}'))
            ok(f'删除 {kind} 行', find_row(kind, LLM_NAME if kind == 'llm' else EMBEDDING_NAME) is None)

        after_canvas = canvas_models()
        after_zaetask = zaetask_llm_list()
        after_llm_rows = model_names('llm')
        ok('画布下拉完全复原', sorted(after_canvas or []) == sorted(baseline_canvas),
           f'{len(after_canvas or [])} vs 基线 {len(baseline_canvas)}')
        ok('system/llm-models 完全复原', sorted(after_zaetask or []) == sorted(baseline_zaetask))
        ok('/models 的 LLM 行完全复原', sorted(after_llm_rows or []) == sorted(baseline_llm_rows))
        if baseline_embeddings:
            ok('/system/embedding-models 完全复原',
               sorted(embedding_all() or []) == sorted(baseline_embeddings))

    print(f'\n{len(failures)} 项未通过' if failures else '\n结论： ✅ 模型注册表端到端打通（新增模型无需重启）')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
