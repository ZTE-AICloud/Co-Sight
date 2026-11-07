"""检索器的分项耗时：混合检索时向量 / 关键字各记一段。

背景：`RetrieverQueryEngine` 只测最外层 retriever，混合检索的 fusion 会把子检索器
包进同一个 `retrieval` 合计里，面板就只剩一个「向量检索」。这里钉住两个子检索器
各自的埋点，且明确它们与合计是「分项 vs 合计」而非相加关系。

没有请求收集器时（单测 / 其他入口）埋点必须是 no-op。
"""
import pytest

from engine.common import stage_timing
from engine.primitives.components.fusion import FUSION_MODES, QueryFusionRetriever
from engine.primitives.components.query_engine import RetrieverQueryEngine
from engine.primitives.models import QueryBundle
from engine.retriever import keyword_retriever, knowledgegraph_retriever, vector_retriever
from engine.retriever.keyword_retriever import KeywordRetriever
from engine.retriever.knowledgegraph_retriever import KnowledgeGraphRetriever
from engine.retriever.vector_retriever import VectorRetriever


class _Header:
    """只提供检索器构造时用到的 `set_mode`；`build_headers` 走 getattr 容错。"""

    def set_mode(self, mode):
        self.mode = mode


@pytest.fixture(autouse=True)
def _clean_collector():
    stage_timing._STAGES.set(None)
    yield
    stage_timing._STAGES.set(None)


def _vector_retriever():
    return VectorRetriever({
        'headers': _Header(),
        'knowledge_info_list': [{'knowledge_base_name': ['doc_demo']}],
    })


def _keyword_retriever():
    return KeywordRetriever({
        'headers': _Header(),
        'knowledge_base_name': ['doc_demo'],
    })


def _graph_retriever():
    return KnowledgeGraphRetriever({
        'headers': _Header(),
        'knowledge_base_name': ['graph_demo'],
        'embedding': 'Qwen3-Embedding-0.6B',
    })


def _stub_kb_client(monkeypatch):
    monkeypatch.setattr(
        vector_retriever, 'invoke_knowledge_base_client',
        lambda headers, body: [])
    monkeypatch.setattr(
        keyword_retriever, 'invoke_knowledge_base_client',
        lambda headers, body: [])


def test_vector_retriever_records_only_its_own_stage(monkeypatch):
    # Arrange
    stage_timing.start()
    _stub_kb_client(monkeypatch)

    # Act
    nodes = _vector_retriever().retrieve(QueryBundle(query_str='q'))

    # Assert
    assert nodes == []
    snapshot = stage_timing.snapshot()
    assert list(snapshot) == [stage_timing.STAGE_VECTOR_RETRIEVAL]
    assert snapshot[stage_timing.STAGE_VECTOR_RETRIEVAL] >= 0


def test_keyword_retriever_records_only_its_own_stage(monkeypatch):
    # Arrange
    stage_timing.start()
    _stub_kb_client(monkeypatch)

    # Act
    nodes = _keyword_retriever().retrieve(QueryBundle(query_str='q'))

    # Assert
    assert nodes == []
    snapshot = stage_timing.snapshot()
    assert list(snapshot) == [stage_timing.STAGE_KEYWORD_RETRIEVAL]
    assert snapshot[stage_timing.STAGE_KEYWORD_RETRIEVAL] >= 0


def test_graph_retriever_records_only_its_own_stage(monkeypatch):
    """图谱检索只有一路：记录 graph_retrieval 分项，面板才能标成「图谱检索」。"""
    # Arrange
    stage_timing.start()
    monkeypatch.setattr(
        knowledgegraph_retriever, 'invoke_knowledge_graph_client',
        lambda headers, body: {'base_results': []})

    # Act
    nodes = _graph_retriever().retrieve(QueryBundle(query_str='q'))

    # Assert
    assert nodes == []
    snapshot = stage_timing.snapshot()
    assert list(snapshot) == [stage_timing.STAGE_GRAPH_RETRIEVAL]
    assert snapshot[stage_timing.STAGE_GRAPH_RETRIEVAL] >= 0


def test_fusion_engine_keeps_total_and_both_split_stages(monkeypatch):
    """混合检索：outer retrieval（合计）+ vector / keyword（分项）同时存在。"""
    # Arrange
    stage_timing.start()
    _stub_kb_client(monkeypatch)
    fusion = QueryFusionRetriever(
        retrievers=[_vector_retriever(), _keyword_retriever()],
        similarity_top_k=10,
        mode=FUSION_MODES.RECIPROCAL_RANK,
        num_queries=1,
        llm=None,
        use_async=False,
    )
    engine = RetrieverQueryEngine(retriever=fusion)

    # Act
    nodes = engine.retrieve(QueryBundle(query_str='q'))

    # Assert
    assert nodes == []
    snapshot = stage_timing.snapshot()
    assert set(snapshot) == {
        stage_timing.STAGE_RETRIEVAL,
        stage_timing.STAGE_VECTOR_RETRIEVAL,
        stage_timing.STAGE_KEYWORD_RETRIEVAL,
    }
    # 合计覆盖两个子检索器；分项各自不超过合计（同一线程串行执行）
    assert snapshot[stage_timing.STAGE_RETRIEVAL] >= max(
        snapshot[stage_timing.STAGE_VECTOR_RETRIEVAL],
        snapshot[stage_timing.STAGE_KEYWORD_RETRIEVAL],
    )


def test_retrievers_are_unchanged_without_a_collector(monkeypatch):
    # Arrange：没有 start()，measure 不读时钟
    calls = []

    def fail_perf_counter():  # pragma: no cover - 被调用即失败
        raise AssertionError('perf_counter must not be called without a collector')

    monkeypatch.setattr(stage_timing, 'perf_counter', fail_perf_counter)
    monkeypatch.setattr(
        vector_retriever, 'invoke_knowledge_base_client',
        lambda headers, body: calls.append('vector') or [])
    monkeypatch.setattr(
        keyword_retriever, 'invoke_knowledge_base_client',
        lambda headers, body: calls.append('keyword') or [])

    # Act
    _vector_retriever().retrieve(QueryBundle(query_str='q'))
    _keyword_retriever().retrieve(QueryBundle(query_str='q'))

    # Assert：检索照常发生，但没有产生任何阶段数据
    assert calls == ['vector', 'keyword']
    assert stage_timing.snapshot() == {}
