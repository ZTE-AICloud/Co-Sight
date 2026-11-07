"""`chat.trace_writer` 的队列/熔断/开关（不启动真实写线程）。"""
from __future__ import annotations

import queue

import pytest

from chat import trace_writer
from chat.trace_state import TraceState


def _state():
    state = TraceState(
        trace_id='t', conversation_id='d', workflow_id='w', org_id='',
        is_stream=False, question_len=1, request_started=0.0)
    state.finish_non_stream(0.1, 3)
    return state


@pytest.fixture(autouse=True)
def _reset_writer(monkeypatch):
    trace_writer._reset_for_tests()
    monkeypatch.setattr(trace_writer, '_ensure_worker', lambda: None)
    monkeypatch.setattr(trace_writer, '_QUEUE', queue.Queue(maxsize=100))
    yield
    trace_writer._reset_for_tests()


def test_trace_enabled_reads_env(monkeypatch):
    for value in ('1', 'true', 'yes', 'on', ''):
        monkeypatch.setenv('RKB_QUERY_TRACE_ENABLED', value)
        assert trace_writer.trace_enabled() is True
    for value in ('0', 'false', 'no', 'off'):
        monkeypatch.setenv('RKB_QUERY_TRACE_ENABLED', value)
        assert trace_writer.trace_enabled() is False


def test_enqueue_noops_when_disabled_or_state_missing(monkeypatch):
    monkeypatch.setenv('RKB_QUERY_TRACE_ENABLED', 'false')
    assert trace_writer.enqueue_trace(_state()) is False
    monkeypatch.setenv('RKB_QUERY_TRACE_ENABLED', 'true')
    assert trace_writer.enqueue_trace(None) is False


def test_enqueue_puts_a_finalized_payload(monkeypatch):
    monkeypatch.setenv('RKB_QUERY_TRACE_ENABLED', 'true')

    assert trace_writer.enqueue_trace(_state()) is True
    payload = trace_writer._QUEUE.get_nowait()
    assert payload['status'] == 'ok'
    assert payload['answer_len'] == 3
    assert payload['generate_ms'] is None


def test_enqueue_returns_false_when_queue_is_full(monkeypatch):
    monkeypatch.setenv('RKB_QUERY_TRACE_ENABLED', 'true')
    monkeypatch.setattr(trace_writer, '_QUEUE', queue.Queue(maxsize=1))
    trace_writer._QUEUE.put_nowait({'sentinel': True})

    assert trace_writer.enqueue_trace(_state()) is False


def test_breaker_opens_after_three_failures_and_skips_db(monkeypatch):
    calls = []
    monkeypatch.setattr(
        trace_writer.repository_pg, 'persist_query_trace',
        lambda payload: calls.append(payload) or False)

    for _ in range(trace_writer.FAILURE_THRESHOLD):
        assert trace_writer._process_one({}) is False
    assert trace_writer._is_skipping() is True

    # 熔断期内直接丢，不再碰 DB
    calls.clear()
    assert trace_writer._process_one({}) is False
    assert calls == []


def test_success_resets_the_breaker(monkeypatch):
    monkeypatch.setattr(
        trace_writer.repository_pg, 'persist_query_trace', lambda payload: True)

    assert trace_writer._process_one({}) is True
    assert trace_writer._CONSECUTIVE_FAILURES == 0
    assert trace_writer._is_skipping() is False


def test_reset_for_tests_clears_breaker_state(monkeypatch):
    monkeypatch.setattr(
        trace_writer.repository_pg, 'persist_query_trace', lambda payload: False)
    for _ in range(trace_writer.FAILURE_THRESHOLD):
        trace_writer._process_one({})
    assert trace_writer._is_skipping() is True

    trace_writer._reset_for_tests()
    assert trace_writer._is_skipping() is False
    assert trace_writer._CONSECUTIVE_FAILURES == 0
