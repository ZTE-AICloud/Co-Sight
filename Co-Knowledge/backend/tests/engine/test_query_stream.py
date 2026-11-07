"""`POST /query` 的对外契约：非流式纯 JSON + 流式具名 SSE 事件。

钉住四件事：

  1. 非流式成功体就是回答对象（没有 `{code,message,data}` 信封）；
  2. 出第一字节前的失败是真实状态码 + `application/problem+json`；
  3. 流式是标准 SSE：`retrieval` / `token` / `done`，任何中途异常变成终态
     `error`（HTTP 已是 200，不能改状态）；
  4. 反代所需的 `X-Accel-Buffering: no` 仍在（`sse-starlette` 负责）。

全程**不碰真实检索与真实上游**：`build_query_engine` 被换成一个假 engine。
"""
import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import chat.app as app_module
from chat.app import _check_response, _streamer
from engine.common import const, stage_timing
from engine.common.exception.rag_exception import RagException
from engine.custom_llm.openai_llm import prepare_text_data
from engine.primitives.models import RagNodeWithScore, TextNode
from chat.router import DEFAULT_PREFIX, register_query_api

CONVERSATION_ID = 'conversation-stream-regression-001'


@pytest.fixture(autouse=True)
def _reset_sse_app_status():
    """sse-starlette 2.1.3 的退出信号 Event 是模块级全局量。

    TestClient 每个用例新建一个事件循环；上一个循环里的 Event 一旦残留，下一个
    用例会报 “bound to a different event loop”。生产只有一个循环，不受影响。
    """
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    yield


class _FakeStreamingResponse:
    """llama-index `StreamingResponse` 的最小替身：只有 `response_gen` 有用。"""

    def __init__(self, tokens, source_nodes=None, query_str=''):
        self.response_gen = iter(tokens)
        self.source_nodes = source_nodes or []
        self.query_str = query_str


class _FakePlainResponse:
    """非流式 `Response` 的替身：有 `.response`，**没有** `response_gen`。"""

    def __init__(self, text, source_nodes=None, query_str=''):
        self.response = text
        self.source_nodes = source_nodes or []
        self.query_str = query_str


class _FakeEngine:
    def __init__(self, result, timings=None):
        self._result = result
        self._timings = dict(timings or {})

    def query(self, question):
        # 模拟引擎在阶段边界累加；真正的收集器由 handler 的 start/reset 管理。
        for stage, milliseconds in self._timings.items():
            stage_timing.record(stage, milliseconds)
        return self._result


def _patch_engine(monkeypatch, result, timings=None):
    """把 `rag.build_query_engine` 换成返回假 engine —— 检索链路完全不执行。"""
    monkeypatch.setattr(
        app_module.rag, 'build_query_engine',
        lambda rag_request, request_headers, *a, **kw: _FakeEngine(result, timings))


def _client():
    """按**生产同形的路径**发请求：挂到真实前缀下，而不是根路径。"""
    test_app = FastAPI()
    register_query_api(test_app, DEFAULT_PREFIX)
    return TestClient(test_app)


def _events(body):
    """把 SSE 正文解析成 `[(event, data), ...]`（兼容 CRLF / LF）。"""

    result = []
    for frame in re.split(r'\r\n\r\n|\n\n', body):
        if not frame.strip():
            continue
        event, data = 'message', []
        for line in re.split(r'\r\n|\n|\r', frame):
            if not line or line.startswith(':'):
                continue
            field, _, value = line.partition(':')
            if value.startswith(' '):
                value = value[1:]
            if field == 'event':
                event = value
            elif field == 'data':
                data.append(value)
        if data:
            result.append((event, '\n'.join(data)))
    return result


def _payload(event):
    return json.loads(event[1])


# ---------------------------------------------------------------------------
# 非流式
# ---------------------------------------------------------------------------

def test_query_non_stream_returns_the_answer_object(monkeypatch):
    payload = {'conversation_id': CONVERSATION_ID, 'answer': '非流式答案',
               'placeholder': {}, 'citation': {}}
    _patch_engine(monkeypatch, _FakePlainResponse(json.dumps(payload, ensure_ascii=False)))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '普通问题', 'conversation_id': CONVERSATION_ID, 'stream': False})

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/json')
    assert response.json() == payload


def test_query_non_stream_error_is_problem_json(monkeypatch):
    def _boom(*args, **kwargs):
        raise RagException(-1, 'published-workflow-not-found', 'wf-1')

    monkeypatch.setattr(app_module.rag, 'build_query_engine', _boom)

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '普通问题', 'conversation_id': CONVERSATION_ID, 'stream': False})

    assert response.status_code == 404
    assert response.headers['content-type'].startswith('application/problem+json')
    assert response.json()['code'] == 'published_workflow_not_found'


# ---------------------------------------------------------------------------
# 流式：响应头与事件序列
# ---------------------------------------------------------------------------

def test_query_stream_returns_sse_with_no_buffering_header(monkeypatch):
    tokens = [prepare_text_data(CONVERSATION_ID, '你好'),
              prepare_text_data(CONVERSATION_ID, '，世界'),
              '[DONE]']
    _patch_engine(monkeypatch, _FakeStreamingResponse(tokens))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '流式问题', 'conversation_id': CONVERSATION_ID, 'stream': True})

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert response.headers['x-accel-buffering'] == 'no'


def test_query_stream_event_sequence_and_done(monkeypatch):
    contents = ['第一段', '第二段', '第三段']
    tokens = [prepare_text_data(CONVERSATION_ID, text) for text in contents] + ['[DONE]']
    _patch_engine(monkeypatch, _FakeStreamingResponse(tokens))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '流式问题', 'conversation_id': CONVERSATION_ID, 'stream': True})
    events = _events(response.text)

    assert [name for name, _ in events] == ['token'] * len(contents) + ['done']
    assert [_payload(e)['content'] for e in events[:-1]] == contents
    assert _payload(events[-1]) == {'conversation_id': CONVERSATION_ID,
                                   'finish_reason': 'stop'}
    assert '[DONE]' not in response.text


def test_accept_header_can_request_a_stream(monkeypatch):
    _patch_engine(monkeypatch, _FakeStreamingResponse(
        [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]']))

    response = _client().post(
        f'{DEFAULT_PREFIX}/query',
        json={'question': '流式问题', 'conversation_id': CONVERSATION_ID},
        headers={'Accept': 'text/event-stream'})

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')


def test_streamer_empty_response_branch_emits_default_answer_then_done():
    events = list(_streamer(_FakeStreamingResponse(['Empty Response']), CONVERSATION_ID))

    assert events[0].event == 'token'
    assert json.loads(events[0].data)['content'] == const.default_answer
    assert events[1].event == 'done'


def test_streamer_non_json_token_is_passed_through():
    events = list(_streamer(_FakeStreamingResponse(['裸文本']), CONVERSATION_ID))

    assert json.loads(events[0].data)['content'] == '裸文本'
    assert events[1].event == 'done'


# ---------------------------------------------------------------------------
# 流式：失败
# ---------------------------------------------------------------------------

def test_query_stream_without_response_gen_is_a_422_problem(monkeypatch):
    """出第一字节前失败：真实状态码 + problem+json（不是半截 SSE）。"""
    _patch_engine(monkeypatch, _FakePlainResponse('不是流式响应'))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '流式问题', 'conversation_id': CONVERSATION_ID, 'stream': True})

    assert response.status_code == 422
    assert response.headers['content-type'].startswith('application/problem+json')
    assert response.json()['code'] == 'question_not_match_desc_info'


def _raising_tokens():
    yield prepare_text_data(CONVERSATION_ID, '已收到的正文')
    raise RagException(-2, 'request-llm-failed')


def test_mid_stream_error_becomes_a_terminal_error_event(monkeypatch):
    _patch_engine(monkeypatch, _FakeStreamingResponse(_raising_tokens()))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '流式问题', 'conversation_id': CONVERSATION_ID, 'stream': True})
    events = _events(response.text)

    assert [name for name, _ in events] == ['token', 'error']
    problem = _payload(events[-1])
    assert problem['code'] == 'llm_unavailable'
    assert problem['status'] == 502
    assert problem['conversation_id'] == CONVERSATION_ID


def test_mid_stream_unexpected_error_is_internal_error(monkeypatch):
    def _boom():
        yield prepare_text_data(CONVERSATION_ID, '半截')
        raise RuntimeError('boom')

    _patch_engine(monkeypatch, _FakeStreamingResponse(_boom()))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '流式问题', 'conversation_id': CONVERSATION_ID, 'stream': True})
    events = _events(response.text)

    assert events[-1][0] == 'error'
    assert _payload(events[-1])['code'] == 'internal_error'


def test_check_response_raises_without_response_gen():
    with pytest.raises(RagException) as exc_info:
        _check_response(_FakePlainResponse('不是流式响应'))
    assert exc_info.value.get_error_tag() == 'question_not_match_desc_info'

    _check_response(_FakeStreamingResponse(['[DONE]']))


# ---------------------------------------------------------------------------
# 检索证据事件
# ---------------------------------------------------------------------------

def _evidence_node(text='片段正文', source_name='doc.md', score=0.8,
                   base_name='doc_1'):
    node = TextNode(text=text, metadata={
        'source': f'{const.source_format}file-id{const.source_format}',
        'knowledge_name': f'{const.base_format}{base_name}{const.base_format}',
        'node_id': f'{const.node_id_format}chunk-1{const.node_id_format}',
        'chunk_index': f'{const.chunk_index_format}3{const.chunk_index_format}',
    })
    node.source_name = source_name
    return RagNodeWithScore(node=node, score=score, base_name=base_name)


def test_streamer_emits_retrieval_event_before_tokens():
    tokens = [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]']
    fake = _FakeStreamingResponse(tokens, source_nodes=[_evidence_node()],
                                  query_str='改写后的问句')

    events = list(_streamer(fake, CONVERSATION_ID, include_retrieval=True))

    assert [event.event for event in events] == ['retrieval', 'token', 'done']
    evidence = json.loads(events[0].data)
    assert evidence['conversation_id'] == CONVERSATION_ID
    assert evidence['evidence']['query'] == '改写后的问句'
    assert evidence['evidence']['items'][0]['source'] == 'doc.md'
    assert json.loads(events[1].data)['content'] == '答案'


def test_streamer_include_retrieval_default_keeps_old_sequence():
    tokens = [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]']
    fake = _FakeStreamingResponse(tokens, source_nodes=[_evidence_node()])

    events = list(_streamer(fake, CONVERSATION_ID))

    assert [event.event for event in events] == ['token', 'done']


def test_streamer_emits_empty_evidence_when_no_nodes():
    tokens = [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]']
    fake = _FakeStreamingResponse(tokens)

    events = list(_streamer(fake, CONVERSATION_ID, include_retrieval=True))

    evidence = json.loads(events[0].data)
    assert evidence['evidence']['items'] == []
    assert evidence['evidence']['stats']['total'] == 0


def test_streamer_evidence_failure_does_not_break_answer(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError('serializer exploded')

    monkeypatch.setattr(app_module, 'build_retrieval_evidence', _boom)
    tokens = [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]']

    events = list(_streamer(_FakeStreamingResponse(tokens), CONVERSATION_ID,
                            include_retrieval=True))

    assert [event.event for event in events] == ['token', 'done']
    assert json.loads(events[0].data)['content'] == '答案'


def test_query_stream_request_flag_adds_retrieval_event(monkeypatch):
    tokens = [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]']
    _patch_engine(monkeypatch, _FakeStreamingResponse(
        tokens, source_nodes=[_evidence_node()]))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '流式问题', 'conversation_id': CONVERSATION_ID,
        'stream': True, 'include_retrieval': True})

    events = _events(response.text)
    assert [name for name, _ in events] == ['retrieval', 'token', 'done']
    assert json.loads(events[0][1])['evidence']['items'][0]['source'] == 'doc.md'


def test_query_non_stream_includes_retrieval_when_requested(monkeypatch):
    payload = {'conversation_id': CONVERSATION_ID, 'answer': '非流式答案',
               'placeholder': {}, 'citation': {}}
    _patch_engine(monkeypatch, _FakePlainResponse(
        json.dumps(payload, ensure_ascii=False),
        source_nodes=[_evidence_node()],
        query_str='改写后的问句',
    ))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '普通问题', 'conversation_id': CONVERSATION_ID,
        'stream': False, 'include_retrieval': True})

    data = response.json()
    assert data['answer'] == '非流式答案'
    assert data['retrieval']['query'] == '改写后的问句'
    assert data['retrieval']['items'][0]['source'] == 'doc.md'


def test_query_non_stream_omits_retrieval_by_default(monkeypatch):
    payload = {'conversation_id': CONVERSATION_ID, 'answer': '非流式答案',
               'placeholder': {}, 'citation': {}}
    _patch_engine(monkeypatch, _FakePlainResponse(
        json.dumps(payload, ensure_ascii=False), source_nodes=[_evidence_node()]))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '普通问题', 'conversation_id': CONVERSATION_ID, 'stream': False})

    assert 'retrieval' not in response.json()


# ---------------------------------------------------------------------------
# 阶段耗时：handler 负责 start/snapshot/reset，证据帧只是透传
# ---------------------------------------------------------------------------

def test_streamer_retrieval_event_carries_timings():
    tokens = [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]']
    fake = _FakeStreamingResponse(tokens, source_nodes=[_evidence_node()],
                                  query_str='改写后的问句')

    events = list(_streamer(
        fake, CONVERSATION_ID, include_retrieval=True,
        timings={stage_timing.STAGE_RETRIEVAL: 12.3}))

    evidence = json.loads(events[0].data)['evidence']
    assert evidence['timings'] == {'retrievalMs': 12.3}


def test_query_stream_retrieval_frame_carries_stage_timings(monkeypatch):
    tokens = [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]']
    _patch_engine(
        monkeypatch,
        _FakeStreamingResponse(tokens, source_nodes=[_evidence_node()]),
        timings={
            stage_timing.STAGE_UNDERSTANDING: 20.0,
            stage_timing.STAGE_RETRIEVAL: 30.0,
            stage_timing.STAGE_RERANK: 40.0,
        },
    )

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '流式问题', 'conversation_id': CONVERSATION_ID,
        'stream': True, 'include_retrieval': True})

    events = _events(response.text)
    evidence = json.loads(events[0][1])['evidence']
    assert evidence['timings'] == {
        'understandingMs': 20.0,
        'retrievalMs': 30.0,
        'rerankMs': 40.0,
    }


def test_query_non_stream_retrieval_carries_stage_timings(monkeypatch):
    payload = {'conversation_id': CONVERSATION_ID, 'answer': '非流式答案',
               'placeholder': {}, 'citation': {}}
    _patch_engine(
        monkeypatch,
        _FakePlainResponse(
            json.dumps(payload, ensure_ascii=False),
            source_nodes=[_evidence_node()],
            query_str='改写后的问句',
        ),
        timings={stage_timing.STAGE_RERANK: 55.5},
    )

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '普通问题', 'conversation_id': CONVERSATION_ID,
        'stream': False, 'include_retrieval': True})

    assert response.json()['retrieval']['timings'] == {'rerankMs': 55.5}


def test_query_starts_and_resets_the_stage_collector(monkeypatch):
    calls = []
    real_start = stage_timing.start
    real_reset = stage_timing.reset

    def fake_start():
        calls.append('start')
        return real_start()

    def fake_reset(token):
        calls.append('reset')
        return real_reset(token)

    monkeypatch.setattr(app_module.stage_timing, 'start', fake_start)
    monkeypatch.setattr(app_module.stage_timing, 'reset', fake_reset)
    _patch_engine(monkeypatch, _FakePlainResponse('{"answer":"ok"}'))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '普通问题', 'conversation_id': CONVERSATION_ID, 'stream': False})

    assert response.status_code == 200
    assert calls == ['start', 'reset']


def test_query_stream_resets_the_stage_collector(monkeypatch):
    calls = []
    real_start = stage_timing.start
    real_reset = stage_timing.reset

    def fake_start():
        calls.append('start')
        return real_start()

    def fake_reset(token):
        calls.append('reset')
        return real_reset(token)

    monkeypatch.setattr(app_module.stage_timing, 'start', fake_start)
    monkeypatch.setattr(app_module.stage_timing, 'reset', fake_reset)
    tokens = [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]']
    _patch_engine(monkeypatch, _FakeStreamingResponse(tokens))

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '流式问题', 'conversation_id': CONVERSATION_ID, 'stream': True})

    assert response.status_code == 200
    # 生成器可能稍后才被迭代；handler 的 finally 必须在返回流式响应前复位
    assert calls == ['start', 'reset']


def test_query_resets_the_stage_collector_on_error(monkeypatch):
    calls = []
    real_start = stage_timing.start
    real_reset = stage_timing.reset

    def fake_start():
        calls.append('start')
        return real_start()

    def fake_reset(token):
        calls.append('reset')
        return real_reset(token)

    monkeypatch.setattr(app_module.stage_timing, 'start', fake_start)
    monkeypatch.setattr(app_module.stage_timing, 'reset', fake_reset)

    def _boom(*args, **kwargs):
        raise RagException(-1, 'published-workflow-not-found', 'wf-1')

    monkeypatch.setattr(app_module.rag, 'build_query_engine', _boom)

    response = _client().post(f'{DEFAULT_PREFIX}/query', json={
        'question': '普通问题', 'conversation_id': CONVERSATION_ID, 'stream': False})

    assert response.status_code == 404
    assert calls == ['start', 'reset']
