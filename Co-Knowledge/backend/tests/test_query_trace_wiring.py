"""`/query` 与 TraceState/background 的接线（不连 DB）。"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import chat.app as app_module
from chat.app import _streamer, _trace_background
from chat.router import DEFAULT_PREFIX, register_query_api
from chat.trace_state import TraceState
from engine.common import const, stage_timing
from engine.common.exception.rag_exception import RagException
from engine.custom_llm.openai_llm import prepare_text_data
from engine.primitives.models import RagNodeWithScore, TextNode

CONVERSATION_ID = 'dlg-trace-wiring-001'


@pytest.fixture(autouse=True)
def _reset_sse_app_status():
    """sse-starlette 的退出 Event 是模块级全局量；TestClient 每个用例新建事件循环。"""
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    yield


class _StreamingResponse:
    def __init__(self, tokens, source_nodes=None, fail_after=None):
        self.source_nodes = source_nodes or []
        self.query_str = '改写后的问句'
        self.response_gen = self._gen(tokens, fail_after)

    @staticmethod
    def _gen(tokens, fail_after):
        for index, token in enumerate(tokens):
            if fail_after is not None and index == fail_after:
                raise RuntimeError('stream exploded')
            yield token


class _PlainResponse:
    def __init__(self, text, source_nodes=None):
        self.response = text
        self.source_nodes = source_nodes or []
        self.query_str = '改写后的问句'


class _FakeEngine:
    def __init__(self, result, timings=(10.0, 20.0, 30.0)):
        self._result = result
        self._timings = timings

    def query(self, question):
        for stage, milliseconds in zip(
                (stage_timing.STAGE_UNDERSTANDING, stage_timing.STAGE_RETRIEVAL,
                 stage_timing.STAGE_RERANK), self._timings):
            stage_timing.record(stage, milliseconds)
        return self._result


def _node(source='doc.md', score=6.0, base='doc_1'):
    node = TextNode(text='片段', metadata={'source': source})
    node.source_name = source
    return RagNodeWithScore(node=node, score=score, base_name=base)


def _client(monkeypatch, result):
    monkeypatch.setattr(
        app_module.rag, 'build_query_engine',
        lambda *args, **kwargs: _FakeEngine(result))
    app = FastAPI()
    register_query_api(app, DEFAULT_PREFIX)
    return TestClient(app)


@pytest.fixture
def captured(monkeypatch):
    records = []
    monkeypatch.setenv('RKB_QUERY_TRACE_ENABLED', 'true')
    monkeypatch.setattr(app_module, 'enqueue_trace', lambda state: records.append(
        state.snapshot()) or True)
    return records


def test_streaming_request_records_ok_with_all_metrics(captured, monkeypatch):
    result = _StreamingResponse(
        [prepare_text_data(CONVERSATION_ID, '你好'), prepare_text_data(CONVERSATION_ID, '世界'),
         '[DONE]'],
        source_nodes=[_node(), _node('other.md', 3.0)])
    client = _client(monkeypatch, result)

    response = client.post(f'{DEFAULT_PREFIX}/query', json={
        'question': '你好呀', 'conversation_id': CONVERSATION_ID,
        'workflow_id': 'wf-1', 'stream': True, 'include_retrieval': True})

    assert response.status_code == 200
    assert len(captured) == 1
    record = captured[0]
    assert record['status'] == 'ok'
    assert record['is_stream'] is True
    assert record['conversation_id'] == CONVERSATION_ID
    assert record['workflow_id'] == 'wf-1'
    assert record['question_len'] == 3
    assert record['answer_len'] == 4
    assert record['understanding_ms'] == 10.0
    assert record['retrieval_ms'] == 20.0
    assert record['rerank_ms'] == 30.0
    assert record['generate_ms'] is not None
    assert record['first_token_ms'] is not None
    assert record['total_ms'] is not None
    assert record['hit_count'] == 2
    assert record['source_count'] == 2
    assert record['kb_count'] == 1
    assert record['top_score'] == 6.0


def test_bad_source_nodes_do_not_fail_the_answer(captured, monkeypatch):
    """统计只是展示数据；source_nodes 形状不对不能把 200 变成 500。"""
    result = _StreamingResponse(
        [prepare_text_data(CONVERSATION_ID, '答案'), '[DONE]'], source_nodes=42)
    client = _client(monkeypatch, result)

    response = client.post(f'{DEFAULT_PREFIX}/query', json={
        'question': 'x', 'conversation_id': CONVERSATION_ID, 'stream': True})

    assert response.status_code == 200
    assert captured[0]['status'] == 'ok'
    assert captured[0]['hit_count'] == 0


def test_non_stream_request_records_total_without_generate(captured, monkeypatch):
    payload = {'conversation_id': CONVERSATION_ID, 'answer': '答案',
               'placeholder': {}, 'citation': {}}
    result = _PlainResponse(json.dumps(payload, ensure_ascii=False),
                            source_nodes=[_node()])
    client = _client(monkeypatch, result)

    response = client.post(f'{DEFAULT_PREFIX}/query', json={
        'question': '普通问题', 'conversation_id': CONVERSATION_ID,
        'workflow_id': 'wf-1', 'stream': False, 'include_retrieval': True})

    assert response.status_code == 200
    record = captured[0]
    assert record['status'] == 'ok'
    assert record['is_stream'] is False
    assert record['answer_len'] == 2
    assert record['total_ms'] is not None
    assert record['generate_ms'] is None
    assert record['first_token_ms'] is None


def test_pre_stream_error_records_problem_status(captured, monkeypatch):
    def boom(*args, **kwargs):
        raise RagException(-1, 'published-workflow-not-found', 'wf-1')

    monkeypatch.setattr(app_module.rag, 'build_query_engine', boom)
    app = FastAPI()
    register_query_api(app, DEFAULT_PREFIX)

    response = TestClient(app).post(f'{DEFAULT_PREFIX}/query', json={
        'question': 'x', 'conversation_id': CONVERSATION_ID, 'stream': False})

    assert response.status_code == 404
    record = captured[0]
    assert record['status'] == 'error'
    assert record['error_code'] == 'published_workflow_not_found'
    assert record['http_status'] == 404
    assert record['error_status'] == 404
    assert record['total_ms'] is not None


def test_disabled_switch_records_nothing(captured, monkeypatch):
    monkeypatch.setenv('RKB_QUERY_TRACE_ENABLED', 'false')
    result = _PlainResponse('{"answer":"ok"}')
    client = _client(monkeypatch, result)

    response = client.post(f'{DEFAULT_PREFIX}/query', json={
        'question': 'x', 'conversation_id': CONVERSATION_ID, 'stream': False})

    assert response.status_code == 200
    assert captured == []


def test_streamer_error_marks_error_and_wire_status_200():
    state = TraceState(trace_id='t', conversation_id='d', workflow_id='w', org_id='',
                       is_stream=True, question_len=1, request_started=0.0)
    response = _StreamingResponse(
        [prepare_text_data('d', '先给一段'), 'boom'], fail_after=1)

    events = list(_streamer(response, 'd', include_retrieval=False, trace_state=state))

    assert [event.event for event in events] == ['token', 'error']
    record = state.snapshot()
    assert record['status'] == 'error'
    assert record['error_code'] == 'internal_error'
    assert record['http_status'] == 200
    assert record['error_status'] == 500


def test_streamer_close_marks_client_disconnect():
    state = TraceState(trace_id='t', conversation_id='d', workflow_id='w', org_id='',
                       is_stream=True, question_len=1, request_started=0.0)
    response = _StreamingResponse(['一', '二', '三'])
    stream = _streamer(response, 'd', include_retrieval=False, trace_state=state)

    next(stream)
    stream.close()

    record = state.snapshot()
    assert record['status'] == 'client_disconnect'
    assert record['error_code'] == 'client_disconnected'
    assert record['answer_len'] == 1


def test_streamer_empty_response_counts_default_answer():
    state = TraceState(trace_id='t', conversation_id='d', workflow_id='w', org_id='',
                       is_stream=True, question_len=1, request_started=0.0)
    response = _StreamingResponse(['Empty Response'])

    list(_streamer(response, 'd', include_retrieval=False, trace_state=state))

    record = state.snapshot()
    assert record['status'] == 'ok'
    assert record['answer_len'] == len(const.default_answer)


def test_trace_background_is_none_when_disabled():
    assert _trace_background(None) is None
