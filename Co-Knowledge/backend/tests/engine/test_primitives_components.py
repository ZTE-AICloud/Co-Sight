"""自研原语层：组件（`primitives/components/*`）。

两组用例：

  * **差分用例**（标记 `baseline_differential`，默认被 `pytest.ini` **deselect** ——
    库已摘除后它们只在基线镜像里显式跑：`pytest -m baseline_differential`）：
    同样的输入，本实现与库组件的输出**完全一致** —— choices 文本、batch 文本、
    两类解析、四个融合函数、选择器的真实 prompt（用打桩 LLM 抓）。
  * **常驻用例**：不依赖库的行为锚点（引擎装配与委托、响应装配、"Empty Response" 哨兵）。

差分用例在库可用时提供对齐证据；库摘掉后同一份断言自动退场，
不会留下"只测自己"的空转断言。
"""

import pytest

from engine.primitives.components import fusion as our_fusion
from engine.primitives.components import query_engine as our_qe
from engine.primitives.components import rerank as our_rerank
from engine.primitives.components import selector as our_selector
from engine.primitives.components import summarizer as our_summ
from engine.primitives.interfaces import (
    RagNodePostprocessor,
    RagQueryEngine,
    RagRetriever,
)
from engine.primitives.models import (
    Node,
    NodeWithScore,
    QueryBundle,
    QueryEngineTool,
    Response,
    StreamingResponse,
    ToolMetadata,
)

NO_LIB = '差分用例：库已摘除'


def _nodes(texts_scores):
    return [NodeWithScore(node=Node(text=t, metadata={'source': 'a.docx'}), score=s)
            for t, s in texts_scores]


# ==========================================================================
# 差分：choices / batch / 解析
# ==========================================================================
@pytest.mark.baseline_differential
def test_choices_text_matches_library():
    pytest.importorskip('llama_index', reason=NO_LIB)
    from llama_index.core.selectors.llm_selectors import _build_choices_text as lib_build
    from llama_index.core.tools import ToolMetadata as LibToolMetadata

    descriptions = ['第一个候选\n描述换行', '第二个候选', '', '带  多余   空格']
    ours = our_selector._build_choices_text(
        [ToolMetadata(name=f'r{i}', description=d) for i, d in enumerate(descriptions)])
    theirs = lib_build(
        [LibToolMetadata(name=f'r{i}', description=d) for i, d in enumerate(descriptions)])
    assert ours == theirs


@pytest.mark.baseline_differential
def test_selection_parser_matches_library():
    pytest.importorskip('llama_index', reason=NO_LIB)
    from llama_index.core.output_parsers.selection import SelectionOutputParser as LibParser

    ours, theirs = our_selector.SelectionOutputParser(), LibParser()
    samples = [
        '[{"choice": 2, "reason": "固定理由"}]',
        '前置说明\n[{"choice": 1, "reason": "带前言"}]\n后置',
        '{choice: 3, reason: yaml 兜底}',
        '{"choice": "1", "reason": "字符串编号"}',
    ]
    for sample in samples:
        a = ours.parse(sample).parsed_output
        b = theirs.parse(sample).parsed_output
        assert [(x.choice, x.reason) for x in a] == [(x.choice, x.reason) for x in b], sample

    with pytest.raises(ValueError) as ours_err:
        ours.parse('完全不是结构化输出')
    with pytest.raises(ValueError) as theirs_err:
        theirs.parse('完全不是结构化输出')
    assert str(ours_err.value) == str(theirs_err.value)


@pytest.mark.baseline_differential
def test_selection_parser_format_matches_library():
    pytest.importorskip('llama_index', reason=NO_LIB)
    from llama_index.core.output_parsers.selection import SelectionOutputParser as LibParser

    assert (our_selector.SelectionOutputParser().format('模板 {x}')
            == LibParser().format('模板 {x}'))


@pytest.mark.baseline_differential
def test_batch_and_parse_helpers_match_library():
    pytest.importorskip('llama_index', reason=NO_LIB)
    from llama_index.core.indices.utils import (
        default_format_node_batch_fn as lib_format,
        default_parse_choice_select_answer_fn as lib_parse,
    )

    nodes = _nodes([('正文一', 0.9), ('正文二', 0.5)])
    assert our_rerank.default_format_node_batch_fn([n.node for n in nodes]) == \
        lib_format([n.node for n in nodes])

    samples = [
        ('Doc: 1, Relevance: 9\nDoc: 3, Relevance: 4', 3),
        ('Doc: 9, Relevance: 9\nDoc: 3, Relevance: 4', 3),   # 越界行丢弃
        ('坏行没有逗号\nDoc: 2, Relevance: 3.5', 3),
        ('', 3),
    ]
    for answer, num in samples:
        assert our_rerank.default_parse_choice_select_answer_fn(answer, num) == \
            lib_parse(answer, num)


# ==========================================================================
# 差分：融合（四个函数都在纯函数形态下对比）
# ==========================================================================
def _fusion_results():
    # 键的第二元是 retriever 下标：必须落在 retriever 数量（2）之内，否则权重索引越界
    return {
        ('q', 0): _nodes([('甲', 0.9), ('乙', 0.2)]),
        ('q', 1): _nodes([('乙', 0.8), ('丙', 0.4)]),
        ('q2', 0): _nodes([('甲', 0.5), ('丁', 0.1)]),
        ('q2', 1): [],
    }


@pytest.mark.baseline_differential
def test_fusion_functions_match_library():
    pytest.importorskip('llama_index', reason=NO_LIB)
    from llama_index.core.retrievers import BaseRetriever as LibRetriever
    from llama_index.core.retrievers.fusion_retriever import (
        FUSION_MODES as LibModes,
        QueryFusionRetriever as LibFusion,
    )
    from llama_index.core.schema import NodeWithScore as LibNWS, TextNode as LibTextNode

    ours = our_fusion.QueryFusionRetriever(
        retrievers=[_DummyRetriever(), _DummyRetriever()], retriever_weights=[1.0, 2.0],
        num_queries=2, similarity_top_k=10, mode=our_fusion.FUSION_MODES.SIMPLE,
        use_async=False)

    class _LibRetriever(LibRetriever):
        def _retrieve(self, query_bundle):  # pragma: no cover - 融合差分直接喂 results
            return []

    # 库侧必须显式给 llm：`llm=None` 会走 `Settings.llm` → 解析到 `llama_index.llms.openai`
    # （本镜像没装那个包）。MockLLM 是 core 自带的，融合差分用不到 LLM（num_queries 直接喂）。
    from llama_index.core.llms import MockLLM

    theirs = LibFusion(
        retrievers=[_LibRetriever(), _LibRetriever()], llm=MockLLM(),
        retriever_weights=[1.0, 2.0],
        num_queries=2, similarity_top_k=10, mode=LibModes.SIMPLE, use_async=False)

    # 权重归一化（构造期完成）也必须一致
    assert ours._retriever_weights == theirs._retriever_weights

    def texts_and_scores(nodes):
        return [(n.node.get_content(),
                 None if n.score is None else round(n.score, 9)) for n in nodes]

    def lib_results():
        out = {}
        for key, nodes in _fusion_results().items():
            out[key] = [LibNWS(node=LibTextNode(text=n.node.text, metadata=dict(n.node.metadata)),
                               score=n.score) for n in nodes]
        return out

    cases = [
        ('reciprocal', ours._reciprocal_rerank_fusion, theirs._reciprocal_rerank_fusion, {}),
        ('relative', ours._relative_score_fusion, theirs._relative_score_fusion, {}),
        ('dist_based', ours._relative_score_fusion, theirs._relative_score_fusion,
         {'dist_based': True}),
        ('simple', ours._simple_fusion, theirs._simple_fusion, {}),
    ]
    for name, ours_fn, theirs_fn, kwargs in cases:
        out_ours = ours_fn(_fusion_results(), **kwargs)
        out_theirs = theirs_fn(lib_results(), **kwargs)
        assert texts_and_scores(out_ours) == texts_and_scores(out_theirs), name


class _DummyRetriever(RagRetriever):
    def _retrieve(self, query_bundle):  # pragma: no cover - 融合差分直接喂 results
        return []


# ==========================================================================
# 常驻：引擎装配与委托
# ==========================================================================
class _FakeRetriever(RagRetriever):
    def __init__(self, nodes):
        self._nodes = nodes
        self.calls = 0

    def _retrieve(self, query_bundle):
        self.calls += 1
        return list(self._nodes)


class _FakePostprocessor(RagNodePostprocessor):
    def __init__(self):
        self.seen = []

    def _postprocess_nodes(self, nodes, query_bundle=None):
        self.seen.append(query_bundle.query_str if query_bundle else None)
        return nodes[:1]


class _FakeTransform:
    def run(self, query_bundle, metadata=None):
        query_bundle.query_str = f'改写({query_bundle.query_str})'
        return query_bundle


class _FakeEngine(RagQueryEngine):
    def __init__(self, response_text='答案'):
        self.queried = []
        self.response_text = response_text

    def _query(self, query_bundle):
        self.queried.append(query_bundle.query_str)
        return Response(self.response_text)

    def synthesize(self, query_bundle, nodes, additional_source_nodes=None):
        return Response(self.response_text)


class _FakeSynthesizer:
    def __init__(self):
        self.calls = []

    def synthesize(self, query=None, nodes=None, additional_source_nodes=None, **kwargs):
        self.calls.append((query.query_str, len(nodes)))
        return Response('合成结果', source_nodes=list(nodes))


def test_retriever_query_engine_retrieve_then_postprocess_then_synthesize():
    retriever = _FakeRetriever(_nodes([('甲', 0.9), ('乙', 0.2)]))
    post = _FakePostprocessor()
    synth = _FakeSynthesizer()
    engine = our_qe.RetrieverQueryEngine(retriever=retriever, response_synthesizer=synth,
                                         node_postprocessors=[post])

    resp = engine.query('问题')
    assert retriever.calls == 1
    assert post.seen == ['问题']
    assert synth.calls == [('问题', 1)]           # 后处理器把节点裁到 1 条
    assert resp.response == '合成结果'


def test_transform_query_engine_applies_transform_before_delegating():
    inner = _FakeEngine()
    engine = our_qe.TransformQueryEngine(query_engine=inner, query_transform=_FakeTransform())
    engine._query(QueryBundle(query_str='原问题'))
    assert inner.queried == ['改写(原问题)']


def test_router_query_engine_single_selection_delegates_and_annotates_metadata():
    class _FakeSelector:
        def select(self, choices, query):
            from engine.primitives.models import SelectorResult, SingleSelection
            return SelectorResult(selections=[SingleSelection(index=1, reason='选了第二个')])

    engine_a, engine_b = _FakeEngine('A'), _FakeEngine('B')
    tools = [QueryEngineTool(engine_a, ToolMetadata(name='a', description='候选A')),
             QueryEngineTool(engine_b, ToolMetadata(name='b', description='候选B'))]
    router = our_qe.RouterQueryEngine(selector=_FakeSelector(), query_engine_tools=tools,
                                      llm=None, summarizer=object())

    resp = router._query(QueryBundle(query_str='问题'))
    assert resp.response == 'B'
    assert engine_a.queried == [] and engine_b.queried == ['问题']
    # 与库一致：selector_result 挂在响应 metadata 上
    assert 'selector_result' in resp.metadata


# ==========================================================================
# 常驻：合成器
# ==========================================================================
def test_prepare_response_output_shapes():
    synth = our_summ.SimpleSummarize(llm=_StubLLM(), streaming=False)
    node = NodeWithScore(node=Node(text='正文', metadata={'source': 'a.docx'}), score=0.5)

    resp = synth._prepare_response_output('文本', [node])
    assert isinstance(resp, Response) and resp.response == '文本'
    assert resp.source_nodes == [node]
    assert resp.metadata == {node.node_id: {'source': 'a.docx'}}

    gen = (x for x in ['甲', '乙'])
    sresp = synth._prepare_response_output(gen, [node])
    assert isinstance(sresp, StreamingResponse)
    assert hasattr(sresp, 'response_gen')


def test_empty_response_sentinel_is_preserved():
    # app._streamer 靠这个字面量识别"无 token"的哨兵帧
    assert list(our_summ.empty_response_generator()) == ['Empty Response']

    synth = our_summ.SimpleSummarize(llm=_StubLLM(canned=''), streaming=False)
    assert synth.get_response('q', ['块']) == 'Empty Response'


class _StubLLM:
    """最小 LLM 桩：predict/stream/complete 都可用；metadata 供 PromptHelper 装配。"""

    def __init__(self, canned='固定答案'):
        self.canned = canned
        self.sent = []
        from engine.primitives.llm import LLMMetadata

        self.metadata = LLMMetadata(context_window=8000, num_output=100)

    def predict(self, prompt, **kwargs):
        self.sent.append(prompt.format(**{k: (v if isinstance(v, str) else str(v))
                                          for k, v in kwargs.items()}))
        return self.canned

    def stream(self, prompt, **kwargs):
        yield self.canned
