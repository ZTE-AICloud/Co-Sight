"""一次 `/query` 的耗时/结果状态（跨 handler 与 SSE worker 线程）。

为什么不是裸 dict：`_streamer` 由 `iterate_in_threadpool` 逐帧调用，客户端断开时
background 可能先跑、worker 线程随后才从 `next()` 返回；两边都会写状态。这里用锁 +
**首个终态胜出**，保证落库的是确定值（断连可能胜过刚好完成的请求，是已知取舍）。

本模块不碰 DB/网络，只做状态机，便于单测。
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from chat import schema

STATUS_RUNNING = 'running'


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _ms(value: Any) -> Optional[float]:
    number = _finite(value)
    return round(number, 1) if number is not None and number >= 0 else None


def _count(value: Any) -> int:
    number = _finite(value)
    return max(0, int(number)) if number is not None else 0


@dataclass
class TraceState:
    trace_id: str
    conversation_id: str
    workflow_id: str
    org_id: str
    is_stream: bool
    question_len: int
    request_started: float

    status: str = STATUS_RUNNING
    error_code: str = ''
    http_status: Optional[int] = None
    error_status: Optional[int] = None
    answer_len: int = 0

    understanding_ms: Optional[float] = None
    retrieval_ms: Optional[float] = None
    rerank_ms: Optional[float] = None
    generate_ms: Optional[float] = None
    first_token_ms: Optional[float] = None
    total_ms: Optional[float] = None

    hit_count: int = 0
    source_count: int = 0
    kb_count: int = 0
    top_score: Optional[float] = None

    generation_started: Optional[float] = None
    first_token_at: Optional[float] = None

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    # ── 阶段数据 ────────────────────────────────────────────────────────
    def set_stage_timings(self, timings: Optional[Mapping[str, Any]]) -> None:
        """写入引擎阶段耗时（内部 key: understanding/retrieval/rerank）。"""
        if not isinstance(timings, Mapping):
            return
        with self._lock:
            understanding = _ms(timings.get('understanding'))
            retrieval = _ms(timings.get('retrieval'))
            rerank = _ms(timings.get('rerank'))
            if understanding is not None:
                self.understanding_ms = understanding
            if retrieval is not None:
                self.retrieval_ms = retrieval
            if rerank is not None:
                self.rerank_ms = rerank

    def set_retrieval_summary(self, summary: Optional[Mapping[str, Any]]) -> None:
        """写入命中统计（全部 source_nodes，不受 evidence 20 条截断）。"""
        if not isinstance(summary, Mapping):
            return
        with self._lock:
            if 'hit_count' in summary:
                self.hit_count = _count(summary.get('hit_count'))
            if 'source_count' in summary:
                self.source_count = _count(summary.get('source_count'))
            if 'kb_count' in summary:
                self.kb_count = _count(summary.get('kb_count'))
            if 'top_score' in summary:
                self.top_score = _finite(summary.get('top_score'))

    # ── 流式过程 ────────────────────────────────────────────────────────
    def mark_generation_started(self, now: float) -> None:
        with self._lock:
            if self.status == STATUS_RUNNING and self.generation_started is None:
                self.generation_started = now

    def mark_first_token(self, now: float) -> None:
        with self._lock:
            if self.status == STATUS_RUNNING and self.first_token_at is None:
                self.first_token_at = now
                self.first_token_ms = self._elapsed_ms(self.request_started, now)

    def add_answer_chars(self, count: int) -> None:
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            return
        with self._lock:
            if self.status == STATUS_RUNNING:
                self.answer_len += count

    # ── 终态 ────────────────────────────────────────────────────────────
    def finish_ok(self, now: float) -> None:
        with self._lock:
            if self.status != STATUS_RUNNING:
                return
            self.status = schema.STATUS_OK
            self._finalize_timings_locked(now, with_generate=True)

    def finish_error(self, now: float, error_code: str,
                     http_status: Optional[int],
                     error_status: Optional[int]) -> None:
        with self._lock:
            if self.status != STATUS_RUNNING:
                return
            self.status = schema.STATUS_ERROR
            self.error_code = str(error_code or '')
            self.http_status = http_status
            self.error_status = error_status
            self._finalize_timings_locked(now, with_generate=True)

    def finish_non_stream(self, now: float, answer_len: int) -> None:
        with self._lock:
            if self.status != STATUS_RUNNING:
                return
            self.status = schema.STATUS_OK
            self.answer_len = max(0, int(answer_len or 0))
            self.total_ms = self._elapsed_ms(self.request_started, now)

    def finalize_if_running(self, now: float) -> None:
        """断连/异常兜底：把仍在 running 的状态收敛成合法终态。"""
        with self._lock:
            if self.status == STATUS_RUNNING:
                self._finalize_if_running_locked(now)

    def snapshot(self, now: Optional[float] = None) -> Dict[str, Any]:
        """返回可直接 INSERT 的扁平 dict；若仍是 running，先按兜底终态收敛。"""
        with self._lock:
            if self.status == STATUS_RUNNING:
                self._finalize_if_running_locked(
                    now if now is not None else time.perf_counter())
            return {
                'trace_id': self.trace_id,
                'conversation_id': self.conversation_id,
                'workflow_id': self.workflow_id,
                'org_id': self.org_id,
                'is_stream': bool(self.is_stream),
                'status': self.status,
                'error_code': self.error_code or '',
                'http_status': self.http_status,
                'error_status': self.error_status,
                'question_len': max(0, int(self.question_len or 0)),
                'answer_len': max(0, int(self.answer_len or 0)),
                'understanding_ms': _ms(self.understanding_ms),
                'retrieval_ms': _ms(self.retrieval_ms),
                'rerank_ms': _ms(self.rerank_ms),
                'generate_ms': _ms(self.generate_ms),
                'first_token_ms': _ms(self.first_token_ms),
                'total_ms': _ms(self.total_ms),
                'hit_count': max(0, int(self.hit_count or 0)),
                'source_count': max(0, int(self.source_count or 0)),
                'kb_count': max(0, int(self.kb_count or 0)),
                'top_score': _finite(self.top_score),
            }

    # ── 内部 ────────────────────────────────────────────────────────────
    def _finalize_if_running_locked(self, now: float) -> None:
        if self.is_stream:
            self.status = schema.STATUS_CLIENT_DISCONNECT
            self.error_code = 'client_disconnected'
            self.http_status = None
            self.error_status = None
            self._finalize_timings_locked(now, with_generate=True)
        else:
            self.status = schema.STATUS_ERROR
            self.error_code = 'internal_error'
            self.http_status = 500
            self.error_status = 500
            self.total_ms = self._elapsed_ms(self.request_started, now)

    def _finalize_timings_locked(self, now: float, with_generate: bool) -> None:
        self.total_ms = self._elapsed_ms(self.request_started, now)
        if with_generate and self.generation_started is not None:
            self.generate_ms = self._elapsed_ms(self.generation_started, now)
        if self.first_token_at is not None and self.first_token_ms is None:
            self.first_token_ms = self._elapsed_ms(self.request_started, self.first_token_at)

    @staticmethod
    def _elapsed_ms(start: Optional[float], end: float) -> Optional[float]:
        if start is None:
            return None
        return round(max(0.0, (end - start) * 1000.0), 1)
