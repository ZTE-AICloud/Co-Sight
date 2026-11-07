"""`/query` 检索证据序列化（`core/rag/retrieval_evidence.py`）。

钉住的是「前端能看懂、且不污染提示词」的字段契约：
  * `|*xxx#|` 标记必须剥干净；
  * 文件名优先用 Node 上的 `source_name`（metadata.source 在适配器里被 sourceDocId 覆盖）；
  * 图谱/文档按 base 前缀区分；
  * 空节点、None、异常 metadata 一律跳过而不抛。
"""
import json

from engine.common import const, stage_timing
from engine.primitives.models import RagNodeWithScore, TextNode
from engine.retrieval_evidence import (
    build_retrieval_evidence,
    prepare_retrieval_frame,
    summarize_source_nodes,
)


def _node(text='切片正文', metadata=None, source_name=None, score=0.9,
          base_name='doc_7'):
    node = TextNode(text=text, metadata=metadata or {})
    if source_name is not None:
        node.source_name = source_name
    return RagNodeWithScore(node=node, score=score, base_name=base_name)


def _search_metadata(source='|*source#|file-id|*source#|', base='doc_7'):
    return {
        'source': source,
        'knowledge_name': f'{const.base_format}{base}{const.base_format}',
        'node_id': f'{const.node_id_format}chunk-1{const.node_id_format}',
        'chunk_index': f'{const.chunk_index_format}3{const.chunk_index_format}',
        'content_expand': '',
    }


def test_build_strips_markers_and_prefers_source_name():
    node = _node(
        text=f'{const.expand_format}切片正文{const.expand_format}',
        metadata=_search_metadata(),
        source_name='doc.md',
    )

    evidence = build_retrieval_evidence([node], query_str='改写后的问题')

    assert evidence['query'] == '改写后的问题'
    assert evidence['stats'] == {'count': 1, 'total': 1, 'sources': 1,
                                 'knowledgeBases': 1}
    item = evidence['items'][0]
    assert item == {
        'index': 1,
        'kind': 'document',
        'kb': 'doc_7',
        'source': 'doc.md',
        'sourceId': 'file-id',
        'chunkId': 'chunk-1',
        'chunkIndex': '3',
        'score': 0.9,
        'label': '',
        'text': '切片正文',
        'truncated': False,
    }


def test_graph_node_uses_base_prefix_and_chunk_order():
    metadata = {
        'source': f'{const.source_format}g.md{const.source_format}',
        'knowledge_name': f'{const.base_format}graph_kb_1|#|dev{const.base_format}',
        'chunk_order': '5',
        'label': '故障',
    }
    node = _node(text=f'{const.expand_format}Entity[Level 0]: 风机{const.expand_format}',
                 metadata=metadata, score=0.0, base_name='graph_kb_1|#|dev')

    item = build_retrieval_evidence([node])['items'][0]

    assert item['kind'] == 'graph'
    assert item['kb'] == 'graph_kb_1'
    assert item['source'] == 'g.md'
    assert item['chunkIndex'] == '5'
    assert item['label'] == '故障'
    assert item['score'] == 0.0


def test_metadata_source_is_fallback_when_no_source_name():
    node = _node(
        text='正文',
        metadata={'source': f'{const.source_format}fallback.md{const.source_format}'},
        source_name='',
        base_name='doc_7',
    )

    item = build_retrieval_evidence([node])['items'][0]

    assert item['source'] == 'fallback.md'
    assert item['sourceId'] == ''


def test_text_is_truncated_and_flagged():
    node = _node(text='x' * 30)

    item = build_retrieval_evidence([node], max_text_chars=10)['items'][0]

    assert item['text'] == 'x' * 10
    assert item['truncated'] is True


def test_items_are_capped_but_total_keeps_full_count():
    nodes = [_node(text=f'片段{i}', source_name=f'{i}.md') for i in range(5)]

    evidence = build_retrieval_evidence(nodes, max_items=2)

    assert evidence['stats'] == {'count': 2, 'total': 5, 'sources': 2,
                                 'knowledgeBases': 1}
    assert [item['index'] for item in evidence['items']] == [1, 2]


def test_empty_and_malformed_nodes_are_skipped():
    no_node = type('NoNode', (), {'score': 1.0, 'base_name': 'doc_7'})()
    empty_text = _node(text='', metadata={}, source_name='', base_name='')
    bad_metadata = _node(text='正文', metadata=None)
    bad_metadata.node.metadata = 'not-a-dict'

    evidence = build_retrieval_evidence([None, no_node, empty_text, bad_metadata])

    # 只有最后一条有正文；metadata 不是 dict 也不能抛
    assert evidence['stats']['count'] == 1
    assert evidence['items'][0]['text'] == '正文'


def test_stats_dedupe_sources_and_knowledge_bases():
    nodes = [
        _node(text='a', source_name='doc.md', base_name='doc_1'),
        _node(text='b', source_name='doc.md', base_name='doc_1'),
        _node(text='c', source_name='other.md', base_name='graph_2'),
    ]

    stats = build_retrieval_evidence(nodes)['stats']

    assert stats['count'] == 3
    assert stats['sources'] == 2
    assert stats['knowledgeBases'] == 2


def test_summarize_source_nodes_counts_all_nodes_not_the_20_item_cap():
    # Arrange：25 个节点，build_retrieval_evidence 默认只展示 20 条
    nodes = [
        _node(text=f'片段{i}', source_name=f'{i}.md', score=float(i),
              base_name='doc_1' if i % 2 else 'doc_2')
        for i in range(25)
    ]

    # Act
    summary = summarize_source_nodes(nodes)

    # Assert：统计按全部节点，不受 20 条截断
    assert summary == {
        'hit_count': 25,
        'source_count': 25,
        'kb_count': 2,
        'top_score': 24.0,
    }


def test_summarize_source_nodes_handles_empty_and_non_finite_scores():
    assert summarize_source_nodes(None) == {
        'hit_count': 0, 'source_count': 0, 'kb_count': 0, 'top_score': None}
    assert summarize_source_nodes([]) == {
        'hit_count': 0, 'source_count': 0, 'kb_count': 0, 'top_score': None}

    nodes = [_node(text='a', source_name='a.md', score=float('nan')),
             _node(text='b', source_name='b.md', score=2.5)]
    summary = summarize_source_nodes(nodes)
    assert summary['hit_count'] == 2
    assert summary['top_score'] == 2.5


def test_prepare_frame_is_the_retrieval_event_data():
    evidence = build_retrieval_evidence([_node(source_name='doc.md')])

    frame = prepare_retrieval_frame('dlg-1', evidence)
    parsed = json.loads(frame)

    assert parsed == {'conversation_id': 'dlg-1', 'evidence': evidence}


def test_timings_are_mapped_to_the_contract_and_rounded():
    evidence = build_retrieval_evidence(
        [_node(source_name='doc.md')],
        timings={
            stage_timing.STAGE_UNDERSTANDING: 362.14,
            stage_timing.STAGE_RETRIEVAL: 93.04,
            stage_timing.STAGE_RERANK: 3391.26,
        },
    )

    assert evidence['timings'] == {
        'understandingMs': 362.1,
        'retrievalMs': 93.0,
        'rerankMs': 3391.3,
    }


def test_split_retrieval_timings_keep_total_and_per_retriever_values():
    # 混合检索：合计 150.0 + 向量 100.0 + 关键字 48.0 同时输出。
    # 展示层自己决定用分项还是合计，服务端不做取舍。
    evidence = build_retrieval_evidence(
        [_node(source_name='doc.md')],
        timings={
            stage_timing.STAGE_RETRIEVAL: 150.04,
            stage_timing.STAGE_VECTOR_RETRIEVAL: 100.06,
            stage_timing.STAGE_KEYWORD_RETRIEVAL: 48.02,
        },
    )

    assert evidence['timings'] == {
        'retrievalMs': 150.0,
        'vectorRetrievalMs': 100.1,
        'keywordRetrievalMs': 48.0,
    }


def test_graph_retrieval_timing_is_mapped():
    # 图谱工作流没有向量/关键字分项，单独一段 graphRetrievalMs 让面板能标成「图谱检索」
    evidence = build_retrieval_evidence(
        [_node(source_name='graph.md')],
        timings={
            stage_timing.STAGE_RETRIEVAL: 300.0,
            stage_timing.STAGE_GRAPH_RETRIEVAL: 299.94,
        },
    )

    assert evidence['timings'] == {
        'retrievalMs': 300.0,
        'graphRetrievalMs': 299.9,
    }


def test_partial_timings_only_include_measured_stages():
    evidence = build_retrieval_evidence(
        [_node(source_name='doc.md')],
        timings={stage_timing.STAGE_RETRIEVAL: 12.0},
    )

    assert evidence['timings'] == {'retrievalMs': 12.0}


def test_zero_timing_is_kept_but_missing_stage_is_absent():
    evidence = build_retrieval_evidence(
        [_node(source_name='doc.md')],
        timings={stage_timing.STAGE_UNDERSTANDING: 0},
    )

    # 0 表示阶段跑了、很快；没有配置重排则不能出现 rerankMs
    assert evidence['timings'] == {'understandingMs': 0.0}
    assert 'rerankMs' not in evidence['timings']


def test_invalid_timings_are_ignored():
    evidence = build_retrieval_evidence(
        [_node(source_name='doc.md')],
        timings={
            stage_timing.STAGE_UNDERSTANDING: True,
            stage_timing.STAGE_RETRIEVAL: '12.5',
            stage_timing.STAGE_VECTOR_RETRIEVAL: -1.0,
            stage_timing.STAGE_KEYWORD_RETRIEVAL: float('inf'),
            stage_timing.STAGE_RERANK: float('nan'),
            'unknown': 1.0,
        },
    )

    assert 'timings' not in evidence


def test_timings_key_is_absent_when_not_supplied_or_empty():
    assert 'timings' not in build_retrieval_evidence([_node(source_name='doc.md')])
    assert 'timings' not in build_retrieval_evidence(
        [_node(source_name='doc.md')], timings={})
    # 形状不对（不是 Mapping）时同样安静地忽略，不能让证据序列化失败
    assert 'timings' not in build_retrieval_evidence(
        [_node(source_name='doc.md')], timings='not-a-mapping')


def test_prepare_frame_carries_timings_inside_evidence():
    evidence = build_retrieval_evidence(
        [_node(source_name='doc.md')],
        timings={stage_timing.STAGE_RETRIEVAL: 8.0},
    )

    parsed = json.loads(prepare_retrieval_frame('dlg-1', evidence))

    assert parsed['evidence']['timings'] == {'retrievalMs': 8.0}
