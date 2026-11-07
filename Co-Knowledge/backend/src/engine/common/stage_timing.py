"""请求级阶段耗时收集器（只在一次 `/query` 内有效）。

为什么需要它：对话测试页要展示「问题理解 / 向量检索 / 关键字检索 / 重排序」的真实
耗时，而这些阶段发生在引擎深处（query transform、retriever、node postprocessors），
没有统一的响应对象可以往上带。这里沿用 `infrastructure.logging.trace` 的
contextvar 模式：

* `chat.app.chat()` 在请求入口 ``start()``，``finally`` 里 ``reset()``；
* 引擎在阶段边界用 ``measure()`` 累加；
* handler 在 ``engine.query()`` 返回后立刻 ``snapshot()``，把**普通 dict** 显式传给
  ``_streamer`` / ``_get_answer_from_result``（流式生成器可能在别的 context 里执行，
  不能在里面读 contextvar）。

口径：

* 单位毫秒；同一阶段执行多次（例如 Router 多选）累加，表示该阶段的墙钟总时间；
* `retrieval` 是检索合计，`vector_retrieval` / `keyword_retrieval` 是混合检索下
  按检索器类型拆出的分项（子检索器自己记录；外层合计仍保留，两者不是相加关系）；
* 未启用的阶段不出现（不是 0）——展示层用 ``—`` 区分「没跑」和「跑了 0ms」；
* 没有 ``start()`` 时所有函数都是 no-op，引擎在单测/其他入口里行为不变。

刻意不做的：跨线程共享一个 collector。contextvar 复制到子线程时会共享同一个 dict，
本模块用锁保证累加不丢；raw ``threading.Thread`` 不会继承 context，那些线程里的埋点
不会被记录 —— 当前请求链路是同步单线程，够用，也不要为此引入全局状态。
"""
from __future__ import annotations

import contextvars
import math
import threading
from contextlib import contextmanager
from time import perf_counter
from typing import Dict, Iterator, Optional

#: 阶段名（内部 key；对外契约映射见 :mod:`engine.retrieval_evidence`）
STAGE_UNDERSTANDING = 'understanding'
#: 检索总耗时（最外层 retriever；混合检索时包含 fusion 与全部子检索器）
STAGE_RETRIEVAL = 'retrieval'
#: 按检索器类型拆分的分段耗时（混合/条件工作流才可能出现；子检索器各记一段，
#: 与 STAGE_RETRIEVAL 是「合计 vs 分项」的关系，展示层优先用分项）
STAGE_VECTOR_RETRIEVAL = 'vector_retrieval'
STAGE_KEYWORD_RETRIEVAL = 'keyword_retrieval'
#: 图谱检索（KnowledgeGraphRetriever 调用 RKB `/retrieval/graph` 的耗时）。
#: 图谱工作流没有向量/关键字分项，只有合计，面板不能把它标成「向量检索」。
STAGE_GRAPH_RETRIEVAL = 'graph_retrieval'
STAGE_RERANK = 'rerank'

_STAGE_ORDER = (STAGE_UNDERSTANDING, STAGE_RETRIEVAL, STAGE_VECTOR_RETRIEVAL,
                STAGE_KEYWORD_RETRIEVAL, STAGE_GRAPH_RETRIEVAL, STAGE_RERANK)

_STAGES: contextvars.ContextVar[Optional[Dict[str, float]]] = contextvars.ContextVar(
    'rag_stage_timings', default=None)
#: contextvar 被复制进子线程时，多个线程会共享同一个 dict；累加必须串行化。
_LOCK = threading.Lock()


def _safe_ms(value: object) -> Optional[float]:
    """把不可信的耗时收敛成非负有限数；bool 是 int 的子类，必须显式排除。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def start() -> contextvars.Token:
    """开启一次请求的阶段收集，返回 token（供 :func:`reset`）。"""
    return _STAGES.set({})


def reset(token: contextvars.Token) -> None:
    """结束收集。跨 context 误用时兜底清空，别让异常盖住业务错误（同 trace）。"""
    try:
        _STAGES.reset(token)
    except (ValueError, TypeError):
        _STAGES.set(None)


def record(stage: str, milliseconds: float) -> None:
    """累加一个阶段耗时；没有活动的收集器时什么都不做。"""
    stages = _STAGES.get()
    if stages is None or not isinstance(stage, str) or not stage:
        return
    value = _safe_ms(milliseconds)
    if value is None:
        return
    with _LOCK:
        stages[stage] = stages.get(stage, 0.0) + value


@contextmanager
def measure(stage: str) -> Iterator[None]:
    """测量 ``with`` 块的墙钟时间，结束时累加到 ``stage``。

    没有活动收集器时直接 yield，不读时钟；内部已经捕获的失败（例如重排器降级）
    也会因为 ``finally`` 而计入真实耗时。
    """
    if _STAGES.get() is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        record(stage, (perf_counter() - started) * 1000.0)


def snapshot() -> Dict[str, float]:
    """当前请求的阶段耗时副本（毫秒，1 位小数）；无收集器时返回空 dict。"""
    stages = _STAGES.get()
    if not stages:
        return {}
    with _LOCK:
        items = list(stages.items())
    result: Dict[str, float] = {}
    for stage, milliseconds in items:
        value = _safe_ms(milliseconds)
        if value is not None:
            result[stage] = round(value, 1)
    # 固定顺序，日志/测试稳定；未知阶段放后面
    ordered = {stage: result[stage] for stage in _STAGE_ORDER if stage in result}
    ordered.update({stage: value for stage, value in result.items() if stage not in ordered})
    return ordered
