"""flow 域的两条回归：文案语言（L1）与参数/请求体校验顺序（L2）。

断言里写的就是对外契约规定的文案与状态。

**L1 —— 文案语言只能认 ``Accept-Language``**

浏览器只发 ``Accept-Language``；若按 ``language-option`` 判定，同一请求的文案语言
会与浏览器语言相反（浏览器 zh-CN 却回英文）。flow_api 的文案语言必须直接复用
kb_api 的 ``identity.language``（同实现、同实测表）。

**L2 —— 校验顺序**

路径变量与请求体在**参数绑定阶段**就完成绑定，早于服务层查库。
新 API 把工作流 id 放进路径，因此「缺 appId」这条 query 校验不再存在；
请求体必填与「先查工作流」的相对顺序仍由服务层保证。
"""

import pytest

from conftest import DEFAULT_BOUND_INFO, KB_SERVICE_PREFIX

NO_SUCH = 'nosuch'
ZH_WORKFLOW_MISSING = '知识检索 nosuch 不存在'
EN_WORKFLOW_MISSING = 'Knowledge retrieval nosuch does not exist'
ZH_ILLEGAL_ARGUMENT = '参数不合法，请检查后重试'
EN_ILLEGAL_ARGUMENT = 'Malformed request; check the request and retry'
REQUIRED_BODY_MISSING = 'Malformed request; check the request and retry'


def _kb_body(response):
    """成功返回合成 code；失败返回 problem 的 code/detail（不再有信封）。"""
    if 200 <= response.status_code < 300:
        return {'code': '0000', 'msg': None}
    body = response.json()
    assert response.headers['content-type'].startswith('application/problem+json')
    return {'code': body['code'], 'msg': body['detail']}


# ----------------------------------------------------------------------
# L1：完整语言矩阵（Accept-Language 实测表 + 两个私有头的死代码地位）
# ----------------------------------------------------------------------

LANGUAGE_CASES = [
    ('无头 → 英文（服务端默认 locale en_US）', {}, EN_WORKFLOW_MISSING),
    ('zh-CN → 中文（唯一有专属 properties 的 locale）', {'Accept-Language': 'zh-CN'}, ZH_WORKFLOW_MISSING),
    ('zh-cn 小写也认', {'Accept-Language': 'zh-cn'}, ZH_WORKFLOW_MISSING),
    ('zh → 英文（没有 zh 的 properties，回落 en_US 而不是基础包）', {'Accept-Language': 'zh'}, EN_WORKFLOW_MISSING),
    ('zh-TW → 英文', {'Accept-Language': 'zh-TW'}, EN_WORKFLOW_MISSING),
    ('en-US → 英文', {'Accept-Language': 'en-US'}, EN_WORKFLOW_MISSING),
    ('* → 中文（解析出空语言 → 取基础包，基础包是中文）', {'Accept-Language': '*'}, ZH_WORKFLOW_MISSING),
    ('zh-CN,en;q=0.9 → 中文（按 q 值取主标签）', {'Accept-Language': 'zh-CN,en;q=0.9'}, ZH_WORKFLOW_MISSING),
    ('en-US,zh-CN;q=0.9 → 英文', {'Accept-Language': 'en-US,zh-CN;q=0.9'}, EN_WORKFLOW_MISSING),
    ('de → 英文', {'Accept-Language': 'de'}, EN_WORKFLOW_MISSING),
    ('language-option: zh-CN 单独出现 → 英文（文案不看它）', {'language-option': 'zh-CN'}, EN_WORKFLOW_MISSING),
    ('X-Lang-Id: zh_CN 单独出现 → 英文（LocaleResolverConfig 是死代码）', {'X-Lang-Id': 'zh_CN'}, EN_WORKFLOW_MISSING),
    ('两个头掐架 → 听 Accept-Language',
     {'language-option': 'en-US', 'Accept-Language': 'zh-CN'}, ZH_WORKFLOW_MISSING),
]


@pytest.mark.parametrize(
    'headers,expected', [(headers, expected) for _, headers, expected in LANGUAGE_CASES],
    ids=[name for name, _, _ in LANGUAGE_CASES])
def test_published_message_language_follows_accept_language(client, headers, expected):
    """``GET /workflows/{id}/publication``（0005 业务错误）上的完整语言矩阵。"""
    response = client.get(f'{KB_SERVICE_PREFIX}/workflows/{NO_SUCH}/publication',
                          headers=headers)
    code = _kb_body(response)
    assert code['code'] != '0000'
    assert code['msg'] == expected


# 三类错误路径各来一遍 zh-CN / en-US / 无头
# （0005 与 0004 两条渲染路径都要看，别只测一条）
ENDPOINT_CASES = [
    ('GET /workflows/{id}/publication', 'get', f'/workflows/{NO_SUCH}/publication',
     None, ZH_WORKFLOW_MISSING, EN_WORKFLOW_MISSING),
    ('POST /workflows/{id}/validate', 'post', f'/workflows/{NO_SUCH}/validate', {},
     ZH_WORKFLOW_MISSING, EN_WORKFLOW_MISSING),
    ('PATCH /workflows/{id}', 'patch', f'/workflows/{NO_SUCH}', {},
     '知识检索名称不能为空', 'Knowledge retrieval name cannot be empty'),
]
LANGUAGE_HEADERS = [
    ('none', {}, False),
    ('zh-CN', {'Accept-Language': 'zh-CN'}, True),
    ('en-US', {'Accept-Language': 'en-US'}, False),
]


@pytest.mark.parametrize('header_name,headers,expect_chinese', LANGUAGE_HEADERS,
                         ids=[name for name, _, _ in LANGUAGE_HEADERS])
@pytest.mark.parametrize('name,method,path,json_body,zh,en', ENDPOINT_CASES,
                         ids=[name for name, *_ in ENDPOINT_CASES])
def test_endpoint_message_language_matrix(client, name, method, path, json_body,
                                          zh, en, header_name, headers, expect_chinese):
    """三个端点 × 三种语言头：zh-CN 出中文、en-US/无头出英文，路由间不能各说各话。"""
    url = f'{KB_SERVICE_PREFIX}{path}'
    if method == 'get':
        response = client.get(url, headers=headers)
    elif method == 'patch':
        response = client.patch(url, json=json_body, headers=headers)
    else:
        response = client.post(url, json=json_body, headers=headers)
    code = _kb_body(response)
    assert code['code'] != '0000'
    assert code['msg'] == (zh if expect_chinese else en)


def test_flow_language_conclusion_is_identical_to_kb_api():
    """两套兼容层对同一请求头必须给出**同一个**结论（flow 的实现就是委托 kb_api）。"""
    from workflow.router import _message_language
    from infrastructure.http.identity import language as kb_language

    class _Req:
        def __init__(self, header):
            self.headers = {} if header is None else {'accept-language': header}

    for header in [None, '', 'zh-CN', 'zh-cn', 'zh_CN', 'zh', 'zh-TW', 'en', 'en-US', 'de',
                   '*', 'zh-CN,en;q=0.9', 'en-US,zh-CN;q=0.9', 'zh-CN;q=0,en;q=1']:
        assert _message_language(_Req(header)) == kb_language(_Req(header)), header


def test_template_variant_language_is_still_language_option(client):
    """建流播种的**模板变体**语言仍取 ``language-option``（本轮不动它）。

    模板选的是画布里的中文/英文提示词（内容变体，落库后不再变），错误文案才看
    ``Accept-Language``。这条盯的是「改造文案语言时别把播种那条路一起改了」。
    """
    response = client.post(f'{KB_SERVICE_PREFIX}/workflows',
                           json={'workFlowId': 'wf_tpl_lang', 'name': 'x',
                                 'template': 'Sequential',
                                 'boundInfo': DEFAULT_BOUND_INFO},
                           headers={'X-Emp-No': 'admin', 'language-option': 'zh-CN',
                                    'Accept-Language': 'en-US'})
    assert response.status_code == 201, response.json()

    canvas = client.get(f'{KB_SERVICE_PREFIX}/workflows/wf_tpl_lang/flow').json()
    prompts = [op['kwargs']['prompt']
               for node in canvas['nodeConfigDTOList']
               for ops in (node.get('variables') or {}).values() if isinstance(ops, list)
               for op in ops if isinstance(op.get('kwargs'), dict) and 'prompt' in op['kwargs']]
    assert any('问题补全' in prompt for prompt in prompts), prompts


# ----------------------------------------------------------------------
# L2：请求体必填与体绑定规则
# ----------------------------------------------------------------------

REQUIRED_BODY_ENDPOINTS = [
    ('PUT', '/workflows/nosuch/flow'),
    ('POST', '/workflows/nosuch/validate'),
    ('POST', '/workflows'),
    ('PATCH', '/workflows/nosuch'),
]


@pytest.mark.parametrize('method,path', REQUIRED_BODY_ENDPOINTS,
                         ids=[f'{m} {p}' for m, p in REQUIRED_BODY_ENDPOINTS])
def test_required_body_is_checked_before_the_store_lookup(client, method, path):
    """0 字节体 → 0004 ``Required request body is missing``（必填体缺失）。"""
    code = _kb_body(client.request(method, f'{KB_SERVICE_PREFIX}{path}'))
    assert code['code'] == 'malformed_request'
    assert code['msg'] == REQUIRED_BODY_MISSING


def test_missing_body_message_is_not_localized(client):
    """这句是 ``ExceptionAdvice`` 里写死的英文 —— zh-CN 请求也不变（基线实测）。"""
    code = _kb_body(client.patch(f'{KB_SERVICE_PREFIX}/workflows/nosuch',
                                 headers={'Accept-Language': 'zh-CN'}))
    assert code['code'] == 'malformed_request'
    assert code['msg'] == '请求格式不合法，请检查后重试'


BODY_BINDING_CASES = [
    (b'null', REQUIRED_BODY_MISSING),                      # 字面量 null → 仍算「缺体」
    (b'   ', EN_ILLEGAL_ARGUMENT),                         # 空白不是「缺体」，是解析失败
    (b'{not json', EN_ILLEGAL_ARGUMENT),                   # 畸形 JSON
    (b'[1,2]', EN_ILLEGAL_ARGUMENT),                       # 数组进不了 DTO
    (b'123', EN_ILLEGAL_ARGUMENT),
    (b'"str"', EN_ILLEGAL_ARGUMENT),
]


@pytest.mark.parametrize('raw_body,expected', BODY_BINDING_CASES,
                         ids=[repr(raw) for raw, _ in BODY_BINDING_CASES])
def test_request_body_binding_rules_match_the_baseline(client, raw_body, expected):
    """四种体的归宿逐条固定（见 ``envelope.parse_json_body`` 的表）。"""
    response = client.post(f'{KB_SERVICE_PREFIX}/workflows/{NO_SUCH}/validate',
                           content=raw_body, headers={'content-type': 'application/json'})
    code = _kb_body(response)
    assert code['code'] == 'malformed_request'
    assert code['msg'] == expected


def test_workflow_knowledge_bases_is_a_get(client):
    """``GET /workflows/knowledge-bases``：只读，没有请求体必填约束。"""
    code = _kb_body(client.get(f'{KB_SERVICE_PREFIX}/workflows/knowledge-bases'))
    assert code['code'] == '0000'


def test_precheck_looks_up_the_workflow_before_validating_the_canvas(client):
    """体绑定过了之后，服务层第一句仍是查工作流 —— 不存在时报 0005，别被空画布抢答。"""
    code = _kb_body(client.post(f'{KB_SERVICE_PREFIX}/workflows/{NO_SUCH}/validate',
                                json={}))
    assert code['code'] == 'workflow_not_found'
    assert code['msg'] == EN_WORKFLOW_MISSING
