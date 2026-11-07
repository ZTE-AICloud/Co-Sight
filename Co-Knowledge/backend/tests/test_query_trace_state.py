"""`chat.trace_state.TraceState` 的状态机与线程竞态口径。

钉住：首个终态胜出；断连兜底；流式/非流式的 generate/total 定义；坏值不污染行。
"""
from __future__ import annotations

import math
import threading

from chat.trace_state import TraceState


def _state(*, is_stream=True, **overrides):
    values = dict(
        trace_id='trace-1',
        conversation_id='dlg-1',
        workflow_id='wf-1',
        org_id='org-1',
        is_stream=is_stream,
        question_len=12,
        request_started=100.0,
    )
    values.update(overrides)
    return TraceState(**values)


def test_stream_ok_fills_stage_generation_and_first_token():
    # Arrange
    state = _state()
    state.set_stage_timings({
        'understanding': 12.345, 'retrieval': 20.04, 'rerank': 30.0})
    state.set_retrieval_summary({
        'hit_count': 5, 'source_count': 3, 'kb_count': 1, 'top_score': 6.0})

    # Act
    state.mark_generation_started(101.0)
    state.mark_first_token(101.5)
    state.add_answer_chars(4)
    state.add_answer_chars(6)
    state.finish_ok(103.0)

    # Assert
    snapshot = state.snapshot()
    assert snapshot['status'] == 'ok'
    assert snapshot['answer_len'] == 10
    assert snapshot['understanding_ms'] == 12.3
    assert snapshot['retrieval_ms'] == 20.0
    assert snapshot['rerank_ms'] == 30.0
    assert snapshot['generate_ms'] == 2000.0
    assert snapshot['first_token_ms'] == 1500.0
    assert snapshot['total_ms'] == 3000.0
    assert snapshot['hit_count'] == 5
    assert snapshot['source_count'] == 3
    assert snapshot['kb_count'] == 1
    assert snapshot['top_score'] == 6.0


def test_stream_error_records_problem_status_and_keeps_wire_200():
    state = _state()
    state.mark_generation_started(101.0)

    state.finish_error(102.0, 'llm_unavailable', 200, 502)

    snapshot = state.snapshot()
    assert snapshot['status'] == 'error'
    assert snapshot['error_code'] == 'llm_unavailable'
    assert snapshot['http_status'] == 200
    assert snapshot['error_status'] == 502
    assert snapshot['generate_ms'] == 1000.0
    assert snapshot['total_ms'] == 2000.0


def test_client_disconnect_is_the_default_for_a_running_stream():
    state = _state()
    state.mark_generation_started(101.0)
    state.add_answer_chars(3)

    state.finalize_if_running(104.0)

    snapshot = state.snapshot()
    assert snapshot['status'] == 'client_disconnect'
    assert snapshot['error_code'] == 'client_disconnected'
    assert snapshot['http_status'] is None
    assert snapshot['error_status'] is None
    assert snapshot['answer_len'] == 3
    assert snapshot['generate_ms'] == 3000.0
    assert snapshot['total_ms'] == 4000.0


def test_snapshot_finalizes_a_running_stream_instead_of_writing_running():
    state = _state()
    state.mark_generation_started(101.0)

    snapshot = state.snapshot(now=105.0)

    assert snapshot['status'] == 'client_disconnect'
    assert snapshot['total_ms'] == 5000.0


def test_non_stream_finalize_is_internal_error_not_disconnect():
    state = _state(is_stream=False)

    state.finalize_if_running(104.0)

    snapshot = state.snapshot()
    assert snapshot['status'] == 'error'
    assert snapshot['error_code'] == 'internal_error'
    assert snapshot['http_status'] == 500
    assert snapshot['error_status'] == 500
    assert snapshot['total_ms'] == 4000.0
    assert snapshot['generate_ms'] is None
    assert snapshot['first_token_ms'] is None


def test_non_stream_success_has_total_but_no_generate_or_first_token():
    state = _state(is_stream=False)

    state.finish_non_stream(103.0, 7)

    snapshot = state.snapshot()
    assert snapshot['status'] == 'ok'
    assert snapshot['answer_len'] == 7
    assert snapshot['total_ms'] == 3000.0
    assert snapshot['generate_ms'] is None
    assert snapshot['first_token_ms'] is None


def test_first_terminal_state_wins():
    state = _state()
    state.mark_generation_started(101.0)

    state.finish_ok(102.0)
    state.finish_error(103.0, 'late_error', 200, 500)
    state.finalize_if_running(104.0)
    state.add_answer_chars(99)

    snapshot = state.snapshot()
    assert snapshot['status'] == 'ok'
    assert snapshot['error_code'] == ''
    assert snapshot['generate_ms'] == 1000.0
    assert snapshot['answer_len'] == 0


def test_invalid_values_are_ignored_or_clamped():
    state = _state()
    state.set_stage_timings({
        'understanding': -1, 'retrieval': math.nan, 'rerank': True})
    state.set_retrieval_summary({
        'hit_count': -2, 'source_count': '3', 'kb_count': 1,
        'top_score': math.inf})
    state.add_answer_chars(-5)

    snapshot = state.snapshot(now=101.0)
    assert snapshot['understanding_ms'] is None
    assert snapshot['retrieval_ms'] is None
    assert snapshot['rerank_ms'] is None
    assert snapshot['hit_count'] == 0
    assert snapshot['source_count'] == 0
    assert snapshot['kb_count'] == 1
    assert snapshot['top_score'] is None
    assert snapshot['answer_len'] == 0


def test_answer_length_is_thread_safe():
    state = _state()
    state.mark_generation_started(101.0)

    def worker():
        for _ in range(500):
            state.add_answer_chars(1)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    state.finish_ok(102.0)

    assert state.snapshot()['answer_len'] == 2000
