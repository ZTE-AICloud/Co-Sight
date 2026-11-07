"""画布 → 运行时配置的翻译测试。

这是本服务自己写的那部分，其余都是 vendor 的领域代码，所以测试重点是：
  * 四个环节的键名映射对不对（写错会静默得到空算子列表）
  * 执行顺序怎么定：有连线用拓扑序，连不全/成环时退回固定环节顺序
  * 运行时 id 与 edges 的重新编号（默认配置是 1..N + 相邻对）
"""
from typing import Dict

import pytest


from chat.translator import canvas_to_rag_config


def operator(package, name, **kwargs):
    return {'id': 1, 'package': package, 'operator': name, 'kwargs': kwargs}


def node(node_id, stage_key, *operators):
    return {
        'nodeId': node_id,
        'componentType': stage_key.upper(),
        'variables': {stage_key: list(operators)},
    }


def engine(operator_name='SequentialQueryEngine'):
    return {
        'componentType': 'QUERY_ENGINE',
        'variables': {'queryengine': {'id': 0, 'package': 'core.rag.query_engine.sequential_query_engine',
                                      'operator': operator_name, 'kwargs': {}}},
    }


def edges(*pairs):
    return {'componentType': 'EDGES', 'variables': {'edges': [{'source': s, 'target': t} for s, t in pairs]}}


CANVAS = [
    node('n1', 'preretriever', operator('core.rag.pre_retriever.query_transform.query_rewrite', 'LLMQueryRewriter')),
    node('n2', 'retriever', operator('core.rag.retriever.vector_retriever', 'VectorRetriever')),
    node('n3', 'postretriever', operator('core.rag.post_retriever.llm_reranker', 'LLMReranker')),
    node('n4', 'responsesynthesizer',
         operator('core.rag.response_synthesizer.simple_summarizer', 'RagSimpleSummarizer')),
]


def test_stage_keys_map_to_runtime_config_sections():
    config = canvas_to_rag_config('wf-1', CANVAS, [engine(), edges(('n1', 'n2'), ('n2', 'n3'), ('n3', 'n4'))])

    assert [op['operator'] for op in config['pre-retriever']] == ['LLMQueryRewriter']
    assert [op['operator'] for op in config['retriever']] == ['VectorRetriever']
    assert [op['operator'] for op in config['post-retriever']] == ['LLMReranker']
    assert [op['operator'] for op in config['response-synthesizer']] == ['RagSimpleSummarizer']


def test_operator_order_follows_canvas_edges_not_stage_order():
    """把「检索」「合成」在画布上的连线颠倒，运行时的顺序必须跟着颠倒 ——
    否则用户画的执行顺序与真正跑的顺序不一致，而且是静默的。"""
    canvas = [
        node('n1', 'responsesynthesizer',
             operator('core.rag.response_synthesizer.simple_summarizer', 'RagSimpleSummarizer')),
        node('n2', 'retriever', operator('core.rag.retriever.vector_retriever', 'VectorRetriever')),
    ]
    config = canvas_to_rag_config('wf-1', canvas, [engine(), edges(('n1', 'n2'))])

    assert config['workflow']['edges'] == [[1, 2]]
    assert config['response-synthesizer'][0]['id'] == 1
    assert config['retriever'][0]['id'] == 2


def test_missing_edges_fall_back_to_fixed_stage_order():
    """没有连线（或连线不成单链）时退回固定环节顺序：pre → retriever → post → synthesizer。"""
    config = canvas_to_rag_config('wf-1', CANVAS, [engine()])

    ids = {
        'pre-retriever': config['pre-retriever'][0]['id'],
        'retriever': config['retriever'][0]['id'],
        'post-retriever': config['post-retriever'][0]['id'],
        'response-synthesizer': config['response-synthesizer'][0]['id'],
    }
    assert ids == {'pre-retriever': 1, 'retriever': 2, 'post-retriever': 3, 'response-synthesizer': 4}
    assert config['workflow']['edges'] == [[1, 2], [2, 3], [3, 4]]


def test_cyclic_edges_fall_back_instead_of_hanging():
    """成环时不能死循环，也不能给出一个乱序 —— 退回固定顺序并告警。"""
    config = canvas_to_rag_config('wf-1', CANVAS[:2], [engine(), edges(('n1', 'n2'), ('n2', 'n1'))])

    assert config['pre-retriever'][0]['id'] == 1
    assert config['retriever'][0]['id'] == 2


def test_edges_referencing_unknown_nodes_fall_back():
    config = canvas_to_rag_config('wf-1', CANVAS[:2], [engine(), edges(('n1', 'ghost'))])

    assert config['workflow']['edges'] == [[1, 2]]


def test_query_engine_is_translated_with_id_zero():
    config = canvas_to_rag_config('wf-1', CANVAS, [engine('BlendedQueryEngine')])

    assert config['query-engine']['id'] == 0
    assert config['query-engine']['operator'] == 'BlendedQueryEngine'


def test_kwargs_are_passed_through_untouched():
    canvas = [node('n1', 'retriever', operator(
        'core.rag.retriever.vector_retriever', 'VectorRetriever',
        strategy=0, knowledge_info_list=[{'knowledge_base_name': ['doc_7'], 'top_k': 8}]))]
    config = canvas_to_rag_config('wf-1', canvas, [engine()])

    assert config['retriever'][0]['kwargs']['knowledge_info_list'][0]['knowledge_base_name'] == ['doc_7']


def test_empty_canvas_yields_empty_config_not_exception():
    """空画布不在这里抛错 —— 由调用方（flow_config_provider）判空并给业务错误，
    这样「没有算子」只有一个判定点，不会两处各判一套。"""
    config = canvas_to_rag_config('wf-1', [], [])

    assert config['query-engine'] == {}
    assert config['retriever'] == []
    assert config['workflow']['edges'] == []


def test_branched_canvas_keeps_its_branches():
    """分叉画布（条件检索）的运行期边必须保住分支，**不能**串成一条链。

    运行期 `RagContext.get_chain_all_nodes(检索器)` 沿边找「它后面挂的是谁」，
    据此把后检索与合成器配给这一路。串成一条链时第一条分支会连到第二条分支的合成器上，
    另一条分支则拿不到自己的后检索 —— 用户画了两条路，跑出来是一条半。
    """
    canvas = [
        node('pre', 'preretriever',
             operator('core.rag.pre_retriever.query_selector.query_routing', 'LLMSemanticRouting')),
        node('ret_a', 'retriever', operator('core.rag.retriever.keyword_retriever', 'KeywordRetriever')),
        node('ret_b', 'retriever', operator('core.rag.retriever.vector_retriever', 'VectorRetriever')),
        node('post_a', 'postretriever', operator('core.rag.post_retriever.llm_reranker', 'LLMReranker')),
        node('post_b', 'postretriever', operator('core.rag.post_retriever.llm_reranker', 'LLMReranker')),
        node('syn_a', 'responsesynthesizer',
             operator('core.rag.response_synthesizer.simple_summarizer', 'RagSimpleSummarizer')),
        node('syn_b', 'responsesynthesizer',
             operator('core.rag.response_synthesizer.simple_summarizer', 'RagSimpleSummarizer')),
    ]
    config = canvas_to_rag_config('wf-branch', canvas, [engine('ConditionalQueryEngine'), edges(
        ('pre', 'ret_a'), ('pre', 'ret_b'), ('ret_a', 'post_a'), ('post_a', 'syn_a'),
        ('ret_b', 'post_b'), ('post_b', 'syn_b'))])

    # id 按拓扑序编：pre=1、ret_a=2、ret_b=3、post_a=4、post_b=5、syn_a=6、syn_b=7
    assert config['workflow']['edges'] == [[1, 2], [1, 3], [2, 4], [3, 5], [4, 6], [5, 7]]
    # 两条分支各自成链，互不串门（各拿各的后检索与合成器）
    assert _chain(config['workflow']['edges'], 2) == [4, 6]
    assert _chain(config['workflow']['edges'], 3) == [5, 7]


@pytest.mark.parametrize('stray_ops', [[], [operator('core.rag.retriever.vector_retriever', 'VectorRetriever')]])
def test_stray_node_does_not_flatten_the_branches(stray_ops):
    """画布上多一个**没连线**的节点，不能让整张画布退回单链。

    用户在条件检索的画布上拖一个节点进来（配没配算子都可能）就点保存，是常态操作。
    这种画布有**两个起点**，一旦定序函数把它当成「结构不可信」而退回固定环节序，
    两条分支就会被串成一条 —— 用户画了两条路、跑出来一条半，而且保存、发布、
    precheck 全都不报错。
    """
    canvas = [
        node('pre', 'preretriever',
             operator('core.rag.pre_retriever.query_selector.query_routing', 'LLMSemanticRouting')),
        node('ret_a', 'retriever', operator('core.rag.retriever.keyword_retriever', 'KeywordRetriever')),
        node('ret_b', 'retriever', operator('core.rag.retriever.vector_retriever', 'VectorRetriever')),
        node('syn_a', 'responsesynthesizer',
             operator('core.rag.response_synthesizer.simple_summarizer', 'RagSimpleSummarizer')),
        node('syn_b', 'responsesynthesizer',
             operator('core.rag.response_synthesizer.simple_summarizer', 'RagSimpleSummarizer')),
    ] + ([{'nodeId': 'stray', 'componentType': 'RETRIEVER', 'variables': None}] if not stray_ops
         else [node('stray', 'retriever', *stray_ops)])
    config = canvas_to_rag_config('wf-stray', canvas, [engine('ConditionalQueryEngine'), edges(
        ('pre', 'ret_a'), ('pre', 'ret_b'), ('ret_a', 'syn_a'), ('ret_b', 'syn_b'))])

    found: Dict[str, list] = {}
    for stage in ('pre-retriever', 'retriever', 'post-retriever', 'response-synthesizer'):
        for entry in config[stage]:
            found.setdefault(entry['operator'], []).append(entry['id'])
    edges_out = config['workflow']['edges']
    routing = found['LLMSemanticRouting'][0]
    reachable = _descendants(edges_out, routing)

    # ① 分支还在：从链头能走到两条检索，它们各连各的合成器、互不串门
    branches = [operator_id for operator_id in reachable
                if operator_id in found['KeywordRetriever'] + found['VectorRetriever']]
    assert len(branches) == 2, f'链上应当有两条检索路径，实际 {branches}'
    first, second = (_chain(edges_out, branch) for branch in branches)
    assert first and second and first != second
    assert not set(first) & set(second)

    # ② 孤立节点既不抢链头也不进链：运行期 `get_workflow_nodes()` 取「无入边节点里编号
    #    最小的」当起点，孤立节点抢到它就会把整条链带偏（其余算子全成不可达）
    roots = set(operator_id for ids in found.values() for operator_id in ids) - \
        {target for _, target in edges_out}
    assert min(roots) == routing
    if stray_ops:
        stray = (set(found['VectorRetriever']) - set(branches)).pop()
        assert stray not in reachable and stray > routing


def test_nodes_without_operators_are_bridged_not_chained():
    """没有算子的节点不出现在运行期的边里，跨过它接上游/下游。

    模板里的 ``QUERY`` / ``RESPONSE`` 就是这种节点（它们也躺在 ``nodeConfigDTOList`` 里，
    只是 ``variables`` 为 null）；链头（上游没有算子）与链尾（下游没有算子）自然没有边。
    """
    canvas = [
        {'nodeId': 'query', 'componentType': 'QUERY', 'variables': None},
        node('n1', 'retriever', operator('core.rag.retriever.vector_retriever', 'VectorRetriever')),
        {'nodeId': 'mid', 'componentType': 'RETRIEVER', 'variables': None},
        node('n2', 'responsesynthesizer',
             operator('core.rag.response_synthesizer.simple_summarizer', 'RagSimpleSummarizer')),
        {'nodeId': 'response', 'componentType': 'RESPONSE', 'variables': None},
    ]
    other = [engine(), edges(('query', 'n1'), ('n1', 'mid'), ('mid', 'n2'), ('n2', 'response'))]

    config = canvas_to_rag_config('wf-pseudo', canvas, other)

    assert config['workflow']['edges'] == [[1, 2]]


def _descendants(edges, start):
    """沿边能到达的全部算子（所有分支；`get_workflow_nodes()` 的 BFS 同语义）。"""
    seen, queue = [], [start]
    while queue:
        current = queue.pop(0)
        for source, target in edges:
            if source == current and target not in seen:
                seen.append(target)
                queue.append(target)
    return seen


def _chain(edges, start):
    """模拟运行期 `RagContext._scan_next_node`：每步取**第一条**出边，不回头。"""
    found = []

    def scan(current):
        for source, target in edges:
            if source == current and target not in found:
                found.append(target)
                scan(target)
                break

    scan(start)
    return found


def test_node_with_multiple_operators_is_chained_in_canvas_order():
    canvas = [node(
        'n1', 'retriever',
        operator('core.rag.retriever.vector_retriever', 'VectorRetriever'),
        operator('core.rag.retriever.keyword_retriever', 'KeywordRetriever'),
    )]
    config = canvas_to_rag_config('wf-1', canvas, [engine()])

    assert [op['operator'] for op in config['retriever']] == ['VectorRetriever', 'KeywordRetriever']
    assert config['workflow']['edges'] == [[1, 2]]
