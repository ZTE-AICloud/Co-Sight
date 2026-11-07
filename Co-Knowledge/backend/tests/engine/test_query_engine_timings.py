"""引擎边界埋点的归属：哪段算「问题理解」，哪段算「检索/重排」。

重点不是某个引擎能跑通（那些有既有测试），而是**时间不能记错层**：

* Transform 只测 transform 本身，委托给内层引擎的时间不算问题理解；
* MultiTransform 把多个 transform 合成一段 understanding；
* Retriever 只测最外层 `_retriever.retrieve`（fusion 内部嵌套不重复计时）；
* 只有配置了 postprocessor 才产生 rerank；
* Router 的 selector 算 understanding，多选时子引擎的检索/重排累加；
* 没有请求收集器时，引擎行为完全不变。
"""
import pytest

from engine.common import stage_timing
from engine.primitives.components.query_engine import (
    RetrieverQueryEngine,
    RouterQueryEngine,
    TransformQueryEngine,
)
from engine.primitives.interfaces import RagQueryEngine
from engine.query_engine.multi_transform_query_engine import MultiTransformQueryEngine
from engine.primitives.models import (
    QueryBundle,
    QueryEngineTool,
    Response,
    SelectorResult,
    SingleSelection,
)


@pytest.fixture(autouse=True)
def _clean_collector():
    stage_timing._STAGES.set(None)
    yield
    stage_timing._STAGES.set(None)


def _fake_clock(monkeypatch, *values):
    remaining = iter(values)

    def fake_perf_counter():
        try:
            return next(remaining)
        except StopIteration as error:  # pragma: no cover - 断言保护
            raise AssertionError('perf_counter called more times than expected') from error

    monkeypatch.setattr(stage_timing, 'perf_counter', fake_perf_counter)


class _TransformStub:
    def __init__(self, query_str=None):
        self.query_str = query_str
        self.calls = 0

    def run(self, query_bundle, metadata=None):
        self.calls += 1
        if self.query_str is not None:
            query_bundle.query_str = self.query_str
        return query_bundle


class _EngineStub(RagQueryEngine):
    """内层引擎替身；可顺便记录一个检索耗时，用来证明它在 with 之外执行。"""

    def __init__(self, record_retrieval_ms=None):
        self.record_retrieval_ms = record_retrieval_ms
        self.queries = []

    def _query(self, query_bundle):
        self.queries.append(query_bundle.query_str)
        if self.record_retrieval_ms is not None:
            stage_timing.record(
                stage_timing.STAGE_RETRIEVAL, self.record_retrieval_ms)
        return Response(response='ok', query_str=query_bundle.query_str)


class _RetrieverStub:
    def __init__(self, nodes=None):
        self.nodes = list(nodes or [])
        self.calls = 0

    def retrieve(self, query_bundle):
        self.calls += 1
        return list(self.nodes)


class _CompositeRetrieverStub:
    """模拟 fusion：内部串行调用多个子检索器，但只有外层应被计时。"""

    def __init__(self):
        self.subs = [_RetrieverStub(), _RetrieverStub()]

    def retrieve(self, query_bundle):
        for sub in self.subs:
            sub.retrieve(query_bundle)
        return []


class _PostprocessorStub:
    def __init__(self, tag='reranked'):
        self.tag = tag
        self.calls = 0

    def postprocess_nodes(self, nodes, query_bundle=None):
        self.calls += 1
        return list(nodes)


class _SelectorStub:
    def __init__(self, *indices):
        self.indices = indices
        self.calls = 0

    def select(self, choices, query):
        self.calls += 1
        return SelectorResult([
            SingleSelection(index=index, reason='stub') for index in self.indices
        ])


class _SummarizerStub:
    def get_response(self, query_str, texts=None, **kwargs):
        return 'merged'


class _ToolEngineStub(_EngineStub):
    def __init__(self, record_retrieval_ms):
        super().__init__(record_retrieval_ms=record_retrieval_ms)


def test_transform_engine_measures_only_its_transform(monkeypatch):
    # Arrange
    stage_timing.start()
    inner = _EngineStub(record_retrieval_ms=999.0)
    engine = TransformQueryEngine(inner, _TransformStub('rewritten'))
    _fake_clock(monkeypatch, 2.0, 2.05)

    # Act
    result = engine.query('original')

    # Assert：understanding 只有 50ms；内层记录的 999ms 属于 retrieval
    assert result.response == 'ok'
    assert inner.queries == ['rewritten']
    assert stage_timing.snapshot() == {
        stage_timing.STAGE_UNDERSTANDING: 50.0,
        stage_timing.STAGE_RETRIEVAL: 999.0,
    }


def test_multi_transform_engine_sums_the_whole_transform_loop(monkeypatch):
    # Arrange
    stage_timing.start()
    inner = _EngineStub()
    transforms = [_TransformStub(), _TransformStub()]
    engine = MultiTransformQueryEngine(inner, transforms)
    _fake_clock(monkeypatch, 1.0, 1.3)

    # Act
    engine.query('q')

    # Assert
    assert [transform.calls for transform in transforms] == [1, 1]
    assert stage_timing.snapshot() == {stage_timing.STAGE_UNDERSTANDING: 300.0}


def test_multi_transform_engine_without_transforms_records_nothing():
    # Arrange
    stage_timing.start()
    engine = MultiTransformQueryEngine(_EngineStub(), [])

    # Act
    engine.query('q')

    # Assert：没配置改写算子，不能伪造 0ms
    assert stage_timing.snapshot() == {}


def test_retriever_engine_separates_retrieval_and_rerank(monkeypatch):
    # Arrange
    stage_timing.start()
    retriever = _RetrieverStub()
    postprocessor = _PostprocessorStub()
    engine = RetrieverQueryEngine(
        retriever=retriever, node_postprocessors=[postprocessor])
    _fake_clock(monkeypatch, 3.0, 3.1, 4.0, 4.2)

    # Act
    nodes = engine.retrieve(QueryBundle(query_str='q'))

    # Assert
    assert nodes == []
    assert retriever.calls == 1
    assert postprocessor.calls == 1
    assert stage_timing.snapshot() == {
        stage_timing.STAGE_RETRIEVAL: 100.0,
        stage_timing.STAGE_RERANK: 200.0,
    }


def test_retriever_engine_without_postprocessors_has_no_rerank(monkeypatch):
    # Arrange
    stage_timing.start()
    engine = RetrieverQueryEngine(retriever=_RetrieverStub())
    _fake_clock(monkeypatch, 3.0, 3.1)

    # Act
    engine.retrieve(QueryBundle(query_str='q'))

    # Assert
    assert stage_timing.snapshot() == {stage_timing.STAGE_RETRIEVAL: 100.0}


def test_nested_retriever_is_counted_once(monkeypatch):
    # Arrange：fusion 内部会串行调用子检索器；只应产生一个 retrieval span
    stage_timing.start()
    composite = _CompositeRetrieverStub()
    engine = RetrieverQueryEngine(retriever=composite)
    _fake_clock(monkeypatch, 1.0, 1.1)

    # Act
    engine.retrieve(QueryBundle(query_str='q'))

    # Assert
    assert [sub.calls for sub in composite.subs] == [1, 1]
    assert stage_timing.snapshot() == {stage_timing.STAGE_RETRIEVAL: 100.0}


def test_router_engine_measures_selector_as_understanding(monkeypatch):
    # Arrange
    stage_timing.start()
    selector = _SelectorStub(0)
    tool_engine = _ToolEngineStub(record_retrieval_ms=10.0)
    engine = RouterQueryEngine(
        selector=selector,
        query_engine_tools=[
            QueryEngineTool.from_defaults(tool_engine, description='a'),
        ],
        summarizer=_SummarizerStub(),
    )
    _fake_clock(monkeypatch, 5.0, 5.2)

    # Act
    result = engine.query('q')

    # Assert
    assert result.response == 'ok'
    assert stage_timing.snapshot() == {
        stage_timing.STAGE_UNDERSTANDING: 200.0,
        stage_timing.STAGE_RETRIEVAL: 10.0,
    }


def test_router_engine_multi_select_sums_child_stages(monkeypatch):
    # Arrange
    stage_timing.start()
    selector = _SelectorStub(0, 1)
    engine = RouterQueryEngine(
        selector=selector,
        query_engine_tools=[
            QueryEngineTool.from_defaults(_ToolEngineStub(10.0), description='a'),
            QueryEngineTool.from_defaults(_ToolEngineStub(25.0), description='b'),
        ],
        summarizer=_SummarizerStub(),
    )
    _fake_clock(monkeypatch, 7.0, 7.1)

    # Act
    result = engine.query('q')

    # Assert：两个子引擎顺序执行，同阶段累加（墙钟总时间）
    assert result.response == 'merged'
    assert stage_timing.snapshot() == {
        stage_timing.STAGE_UNDERSTANDING: 100.0,
        stage_timing.STAGE_RETRIEVAL: 35.0,
    }


def test_engines_are_unchanged_without_a_collector(monkeypatch):
    # Arrange：没有 start()，measure 不应该读时钟
    def fail_perf_counter():  # pragma: no cover - 被调用即失败
        raise AssertionError('perf_counter must not be called without a collector')

    monkeypatch.setattr(stage_timing, 'perf_counter', fail_perf_counter)
    retriever = _RetrieverStub()
    engine = RetrieverQueryEngine(
        retriever=retriever, node_postprocessors=[_PostprocessorStub()])

    # Act
    engine.retrieve(QueryBundle(query_str='q'))

    # Assert
    assert retriever.calls == 1
    assert stage_timing.snapshot() == {}
