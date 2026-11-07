"""``compat.problem`` / ``compat.api.*`` 的契约测试（纯逻辑，不连库）。

钉住四件事：

1. 文案键 / 字面量 / 旧数字码到 ``ProblemSpec`` 的映射（404/409/413/422/500 等）；
2. RFC 9457 响应体的必填字段、media type 与 HTTP 状态码；
3. ``detail`` 的中英切换（沿用 ``Accept-Language`` 归一化后的 ``zh``/``en``）；
4. 仅协议端点 ``/health``、``/mcp`` 不走 problem+json；``/query``、``/agent``
   与 ``/retrieval/graph`` 都已并入统一契约。
"""

import json

from infrastructure.http.pagination import page
from infrastructure.http.responses import accepted, created, no_content
from shared.prefixes import (AGENT_MCP_PATH, AGENT_PREFIX, GRAPH_RETRIEVE_PATH,
                             RKB_PREFIX)
from shared.problem import (KEY_SPECS, LITERAL_SPECS, ProblemSpec, generic_detail,
                            owns_problem_path, problem_response, resolve_problem,
                            title_for)


def test_key_mapping_covers_not_found_conflict_and_validation():
    assert resolve_problem(key='kbase.not.exist') == ProblemSpec(
        404, 'knowledge_base_not_found', 'Knowledge base not found')
    assert resolve_problem(key='workflow.exist') == ProblemSpec(
        409, 'workflow_exists', 'Workflow exists')
    assert resolve_problem(key='kbase.name.validation') == ProblemSpec(
        422, 'validation_failed', 'Validation failed')


def test_file_name_conflict_is_409_and_payload_limit_is_413():
    assert resolve_problem(key='file.upload.rename').status == 409
    assert resolve_problem(key='file.upload.rename').code == 'file_name_conflict'
    assert resolve_problem(key='RetCode.file.size.limit.check').status == 413
    assert resolve_problem(key='RetCode.file.size.limit.check').code == 'payload_too_large'


def test_literal_mapping_and_literal_prefix():
    assert resolve_problem(literal='知识库不存在').status == 404
    assert resolve_problem(literal='任务不存在').status == 404
    assert resolve_problem(literal='该知识库已有优化任务正在执行').status == 409
    assert resolve_problem(literal='算子不存在，算子ID：7').status == 404
    assert resolve_problem(literal='知识库索引数量已达上限(10)').status == 413
    assert resolve_problem(literal='Required request body is missing').status == 400


def test_error_codes_are_only_fallbacks():
    assert resolve_problem(error_code='0001').status == 500
    assert resolve_problem(error_code='0004').status == 422
    assert resolve_problem(error_code='1001').code == 'file_name_conflict'
    # 未知业务码回落 400，而不是 500
    assert resolve_problem(error_code='0005') == ProblemSpec(
        400, 'bad_request', 'Bad request')


def test_explicit_status_and_code_win_over_numeric_mapping():
    spec = resolve_problem(error_code='0001', status=409,
                           problem_code='task_conflict')
    assert spec == ProblemSpec(409, 'task_conflict', 'Task conflict')


def test_problem_response_is_rfc9457_with_localized_detail():
    response = problem_response(
        ProblemSpec(404, 'knowledge_base_not_found', 'Knowledge base not found'),
        generic_detail(resolve_problem(key='kbase.not.exist'), 'zh'),
        instance='/api/co-knowledge/v1/knowledge-bases/nope',
    )

    assert response.status_code == 404
    assert response.headers['content-type'].startswith('application/problem+json')
    body = json.loads(response.body)
    assert body == {
        'type': 'urn:ragstudio:problem:knowledge_base_not_found',
        'title': 'Knowledge base not found',
        'status': 404,
        'detail': '知识库不存在',
        'instance': '/api/co-knowledge/v1/knowledge-bases/nope',
        'code': 'knowledge_base_not_found',
    }


def test_generic_detail_zh_en_and_never_empty():
    spec = ProblemSpec(422, 'validation_failed', 'Validation failed')
    assert generic_detail(spec, 'zh') == '参数不合法，请检查后重试'
    assert generic_detail(spec, 'en') == (
        'Request validation failed; check the parameters and retry')
    # 未登记的语言按英文；未登记的具体码回落状态码文案，仍非空
    assert generic_detail(spec, 'de')
    assert generic_detail(ProblemSpec(418, 'teapot', 'Teapot'), 'zh')


def test_title_is_derived_stably_and_has_abbreviation_override():
    assert title_for('knowledge_base_not_found') == 'Knowledge base not found'
    assert title_for('api_key_not_found') == 'API key not found'


def test_owns_problem_path_includes_rest_but_not_protocol_endpoints():
    assert owns_problem_path(f'{RKB_PREFIX}/knowledge-bases')
    assert owns_problem_path(f'{RKB_PREFIX}/agent-keys')
    assert owns_problem_path(f'{AGENT_PREFIX}/search')
    assert owns_problem_path(GRAPH_RETRIEVE_PATH)
    assert owns_problem_path(f'{RKB_PREFIX}/query')
    assert not owns_problem_path(f'{RKB_PREFIX}/health')
    assert not owns_problem_path(AGENT_MCP_PATH)
    assert not owns_problem_path('/some/other/path')


def test_pagination_shape_is_uniform():
    assert page([{'id': 1}], 11, 2, 10) == {
        'items': [{'id': 1}], 'total': 11, 'page': 2, 'pageSize': 10}
    assert page([], 0, 1, 10, nameChain=['a']) == {
        'items': [], 'total': 0, 'page': 1, 'pageSize': 10, 'nameChain': ['a']}


def test_success_response_helpers_set_expected_statuses():
    assert created({'id': 'x'}, location='/api/co-knowledge/v1/x').status_code == 201
    assert accepted().status_code == 202
    assert json.loads(accepted().body) == {'accepted': True}
    assert no_content().status_code == 204
    assert no_content().body == b''


def test_every_explicit_key_has_a_sane_spec():
    """防止映射表里出现 None 或非法状态码（新增键时最容易抄错）。"""

    for key, spec in KEY_SPECS.items():
        assert isinstance(spec, ProblemSpec), key
        assert 400 <= spec.status < 600, key
        assert spec.code and spec.code.islower(), key


def test_literal_specs_are_valid():
    for literal, spec in LITERAL_SPECS.items():
        assert 400 <= spec.status < 600, literal
