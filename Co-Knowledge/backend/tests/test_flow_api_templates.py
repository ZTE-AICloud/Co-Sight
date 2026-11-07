"""默认画布模板：建流播种的行为与守卫。

这一组测试钉住三件容易悄悄坏掉的事：

1. **播种回填**：绑定知识库要落进检索器与合成器，否则运行时检索不到东西、
   或静默退回默认 prompt（不报错，只是不生效）；
2. **包名前缀**：画布上的算子包名必须与本服务 / 前端 /编排层一致
   （都带 ``core.rag.``）—— 差一个前缀会让**每个**从画布存下的算子都判成
   「不可运行」，且只在发布时才暴露；
3. **连线自洽**：前端 ``importGraph()`` 是按 ``outputVariables[].targetNode``
   重建连线的，指向不存在的节点就画不出线（看起来就是「没有默认连线」）。
"""

import json

import pytest

from workflow import canvas as canvas_util
from workflow import template_loader, validation
from workflow.errors import FlowError
from workflow.models import FlowCanvasInput

from conftest import KB_SERVICE_PREFIX, create_workflow

#: 本版本可建的三个基础模板（前端只暴露这三个）
TEMPLATES = ('Sequential', 'Blended', 'Conditional')

#: Blended 的两个服务端变体（按绑定库自动选择，前端不感知）
GRAPH_TEMPLATES = ('Blended_graph', 'Blended_normal_graph')

#: 模板 → 编排引擎（`otherNodeConfigList` 里的 QUERY_ENGINE 伪节点）+ 引擎的包名。
#: 三个引擎都要在编排层的 `default_packages_info.query_engine_packages` 里，
#: 由 `services/rag-engine/tests/test_flow_templates.py` 从那一侧反向钉住
#: （模板声明的引擎必须在运行期登记；两侧引擎集合必须相同）。
ENGINE_OF_TEMPLATE = {
    'Sequential': ('SequentialQueryEngine', 'core.rag.query_engine.sequential_query_engine'),
    'Blended': ('BlendedQueryEngine', 'core.rag.query_engine.blended_query_engine'),
    'Conditional': ('ConditionalQueryEngine', 'core.rag.query_engine.conditional_query_engine'),
    # 图谱变体沿用 Blended 引擎（同一个引擎，只是检索节点不同）
    'Blended_graph': ('BlendedQueryEngine', 'core.rag.query_engine.blended_query_engine'),
    'Blended_normal_graph': ('BlendedQueryEngine', 'core.rag.query_engine.blended_query_engine'),
}


def _load(name, language):
    """读模板：基础模板走公开入口，服务端变体走内部读取器。"""
    if name in GRAPH_TEMPLATES:
        return template_loader._read_template(name, language)
    return template_loader.load_template(name, language)


def bound(*names, embedding='bge-base-zh-v1.5', **extra):
    """造 ``boundInfo``（形状 = 建流弹窗 ``getSelectdKbList()`` 的产出）。"""
    return {'running': [
        {'tableName': name, 'embeddingModel': embedding, **extra} for name in names]}


# ----------------------------------------------------------------------
# 模板文件本身
# ----------------------------------------------------------------------

@pytest.mark.parametrize('template', TEMPLATES + GRAPH_TEMPLATES)
@pytest.mark.parametrize('language', ['zh', 'en'])
def test_template_is_loadable_for_both_languages(template, language):
    canvas = _load(template, language)

    assert canvas['flowType'] == 'workflow'
    assert {node['componentType'] for node in canvas['nodeConfigDTOList']} == {
        'QUERY', 'PRE_RETRIEVER', 'RETRIEVER', 'POST_RETRIEVER', 'RESPONSE_SYNTHESIZER', 'RESPONSE'}
    assert [other['componentType'] for other in canvas['otherNodeConfigList']] == ['QUERY_ENGINE', 'EDGES']


@pytest.mark.parametrize('template', TEMPLATES + GRAPH_TEMPLATES)
@pytest.mark.parametrize('language', ['zh', 'en'])
def test_template_operators_are_all_runnable(template, language):
    """模板用到的算子必须都在「可运行清单」里。

    这是 **前缀漂移的哨兵**：``RUNNABLE_OPERATOR_PACKAGES`` 少写 ``core.rag.``
    时，播种出来的画布每个算子都会被判成不可运行 —— 保存没事，发布才炸。
    """
    canvas = _load(template, language)
    packages = {operator['package'] for operator in _iter_operators(canvas['nodeConfigDTOList'])}

    assert packages, '模板里应当至少有一个算子'
    assert packages <= validation.RUNNABLE_OPERATOR_PACKAGES


@pytest.mark.parametrize('template', TEMPLATES + GRAPH_TEMPLATES)
@pytest.mark.parametrize('language', ['zh', 'en'])
def test_template_declares_a_vendored_engine(template, language):
    """模板声明的编排引擎必须是本栈真能跑的那几个（包名与算子名都要对得上）。

    「引擎登记了、模板里写错一个字母」不会在建流时报错，也不会在发布时——
    只会在用户第一次提问时 500。
    """
    canvas = _load(template, language)
    engine = _find_other(canvas, 'QUERY_ENGINE')['variables']['queryengine']
    expected_operator, expected_package = ENGINE_OF_TEMPLATE[template]

    assert engine['operator'] == expected_operator
    assert engine['package'] == expected_package
    assert engine['operator'] in canvas_util.ENGINE_OPERATORS


@pytest.mark.parametrize('template', TEMPLATES + GRAPH_TEMPLATES)
@pytest.mark.parametrize('language', ['zh', 'en'])
def test_template_edges_point_at_existing_nodes(template, language):
    """连线两端都必须落在真实存在的节点上（否则前端画不出线）。"""
    canvas = _load(template, language)
    nodes = canvas['nodeConfigDTOList']
    node_ids = {node['nodeId'] for node in nodes}

    # 前端按 outputVariables[].targetNode 重建连线
    for node in nodes:
        for output in node.get('outputVariables') or []:
            assert output['targetNode'] in node_ids, f'{node["componentType"]} 指向了不存在的节点'
        for source in node.get('inputVariables') or []:
            assert source['sourceNode'] in node_ids, f'{node["componentType"]} 的入边来自不存在的节点'

    # EDGES 伪节点里的边同样要自洽
    for edge in _find_other(canvas, 'EDGES')['variables']['edges']:
        assert edge['source'] in node_ids and edge['target'] in node_ids


@pytest.mark.parametrize('template', TEMPLATES + GRAPH_TEMPLATES)
def test_template_has_no_hardcoded_embedding(template):
    """向量模型不能写死在模板里：写死会让「换个部署就得改画布」。

    模板里留空，播种时由绑定知识库的 ``embeddingModel`` 填上；填不上会**报错**
    （不能让请求不带 model —— 不带会落到默认值 text2vec-base-chinese，
    与库里实际写入的向量对不上，检索静默为空）。
    """
    for language in ('zh', 'en'):
        canvas = _load(template, language)
        for operator in _iter_operators(canvas['nodeConfigDTOList']):
            kwargs = operator.get('kwargs') or {}
            assert kwargs.get('embedding', '') == ''


@pytest.mark.parametrize('template', TEMPLATES + GRAPH_TEMPLATES)
def test_template_keeps_both_variable_copies_identical(template):
    """节点里两份 variables（``variables`` 与 ``data.variables``）必须完全相同。

    一份是**服务端**的（播种写它、编排层读它），一份是**画布**的（前端节点组件
    显示它、`exportGraph()` 保存时按它回写顶层）。两份不同 = 画布上看到的与真正跑的
    不是一回事，而且**保存一次就把播种结果冲掉**（模板本身就是两份相同的；
    只改其中一份会把「绑定好的知识库」冲成空）。
    """
    for language in ('zh', 'en'):
        canvas = _load(template, language)
        for node in canvas['nodeConfigDTOList']:
            data_variables = (node.get('data') or {}).get('variables')
            assert json.dumps(node.get('variables'), sort_keys=True, ensure_ascii=False) == \
                json.dumps(data_variables, sort_keys=True, ensure_ascii=False), \
                f'{node["componentType"]} 的两份 variables 不一致'


# ----------------------------------------------------------------------
# 模板选择
# ----------------------------------------------------------------------

@pytest.mark.parametrize('template', ['Sequential_sql', 'NoSuch', 'blended', 'Sequential_blended'])
def test_unsupported_template_is_rejected(template):
    """未迁的模板显式报错 —— 播种一份「存得下、发不出」的画布比报错更糟。

    大小写敏感是有意的：模板名直接决定读哪个 JSON 文件，前端只送三个精确值
    （``frontend/.../CreateWorkflow.vue`` 的 ``availableTemplates``），这里不做模糊匹配。
    """
    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas(template, 'zh', bound('doc_a'))

    assert excinfo.value.key == 'template.unsupported'


@pytest.mark.parametrize('template', TEMPLATES)
def test_normal_only_bindings_keep_the_base_template(template):
    """只有普通库时，三个基础模板各用自己那份 JSON（不额外套后缀）。"""
    for language in ('zh', 'en'):
        node_config, other = template_loader.build_default_canvas(
            template, language, bound('doc_a'))
        engine = _find_other({'otherNodeConfigList': other}, 'QUERY_ENGINE')['variables']['queryengine']
        assert engine['operator'] == ENGINE_OF_TEMPLATE[template][0]
        assert node_config, '播种不能是空画布'


@pytest.mark.parametrize('template', [None, ''])
def test_missing_template_is_rejected_with_its_own_message(template):
    """没选模板与选了不支持的模板，报的是两句话（空串插进「不支持模板 {0}」会印出双空格）。"""
    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas(template, 'zh', bound('doc_a'))

    assert excinfo.value.key == 'template.not.null'


def test_template_without_nodes_is_rejected(monkeypatch):
    """合法 JSON 但里面没有节点 → 报错，**不能**照播一份空画布。

    照播的话症状和本次要修的 bug 一模一样（前端退回「开始/结束」两个孤点），
    而且要等到发布才报 ``canvas.empty`` —— 报错点离原因太远。
    """
    monkeypatch.setattr(template_loader, 'load_template',
                        lambda template, language: {'flowType': 'workflow', 'nodeConfigDTOList': []})

    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas('Sequential', 'zh', bound('doc_a'))

    assert excinfo.value.key == 'template.not.found'


def test_missing_kbase_is_rejected():
    """一个知识库都没绑 → 显式报错（建流弹窗把知识库做成必填，后端也守一道）。"""
    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas('Sequential', 'zh', None)

    assert excinfo.value.key == 'canvas.no.kbase'


def test_template_is_checked_before_kbase():
    """两个都不对时，报更该先解决的那个（模板比绑定更根本）。"""
    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas('Sequential_sql', 'zh', None)

    assert excinfo.value.key == 'template.unsupported'


# ----------------------------------------------------------------------
# 绑定校验：这几种组合会让检索**静默失效**，必须建流时就拒
# ----------------------------------------------------------------------

def test_mixed_embedding_models_are_rejected():
    """混选不同向量模型的库 → 拒绝。

    检索请求只带一个 ``model``，检索层用它对**所有**库做检索；维度对不上的库查不到，
    而检索层把异常吞成空列表 —— 表现是「答得不准」而不是报错。
    因此必须硬拒（``MULTI_KBASE_EMBEDDING_MODEL``）。
    """
    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas('Sequential', 'zh', {'running': [
            {'tableName': 'doc_a', 'embeddingModel': 'bge-base-zh-v1.5'},
            {'tableName': 'doc_b', 'embeddingModel': 'bge-large-zh-v1.5'},
        ]})

    assert excinfo.value.key == 'kbase.embedding.multi'


def test_same_model_on_many_kbases_is_fine():
    """同一个模型绑多个库是正常用法，不能误伤。"""
    node_config, _ = template_loader.build_default_canvas(
        'Sequential', 'zh', bound('doc_a', 'doc_b', 'doc_c'))

    retriever = _find_stage(node_config, 'retriever')[0]['kwargs']
    assert retriever['embedding'] == 'bge-base-zh-v1.5'
    assert retriever['knowledge_info_list'][0]['knowledge_base_name'] == [
        'doc_a', 'doc_b', 'doc_c']


def test_missing_embedding_model_is_rejected():
    """取不到向量模型 → 拒绝（不能留空，见 ``test_template_has_no_hardcoded_embedding``）。"""
    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas(
            'Sequential', 'zh', {'running': [{'tableName': 'doc_a'}]})

    assert excinfo.value.key == 'kbase.embedding.unknown'


@pytest.mark.parametrize('template', ['Sequential', 'Conditional'])
def test_graph_kbase_is_rejected_for_templates_without_a_graph_retriever(template):
    """顺序/条件模板里没有图谱检索节点 → 绑图谱库显式失败。

    静默丢弃图谱库会让「我明明绑了图谱库」变成一个查不出来的谜。Blended 不在这条
    用例里：它按绑定自动切换成带 ``KnowledgeGraphRetriever`` 的变体（见下一组）。
    """
    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas(
            template, 'zh', bound('graph_0f28f086c3cd4e55a16b19784609951e'))

    assert excinfo.value.key == 'kbase.graph.unsupported'


def test_blended_graph_only_uses_graph_variant():
    """只绑图谱库 → 自动选 ``Blended_graph``：图谱检索器收库名，普通检索器不在画布上。"""
    node_config, other = template_loader.build_default_canvas('Blended', 'zh', bound(GRAPH_KB))

    operators = {op['operator'] for op in _iter_operators(node_config)}
    assert GRAPH_OPERATOR in operators
    assert 'VectorRetriever' not in operators and 'KeywordRetriever' not in operators

    graph = _operator_named(node_config, GRAPH_OPERATOR)
    assert graph['kwargs']['knowledge_base_name'] == [GRAPH_KB]
    assert graph['kwargs']['embedding'] == 'bge-base-zh-v1.5'

    for operator in _all_stage_operators(node_config, 'responsesynthesizer'):
        assert operator['kwargs']['generator-config'][0]['knowledge_base_name'] == [GRAPH_KB]

    engine = _find_other({'otherNodeConfigList': other}, 'QUERY_ENGINE')['variables']['queryengine']
    assert engine['operator'] == 'BlendedQueryEngine'


def test_blended_mixed_bindings_use_normal_graph_variant():
    """普通库 + 图谱库 → 自动选 ``Blended_normal_graph``：两边各进各的检索器。"""
    node_config, _ = template_loader.build_default_canvas(
        'Blended', 'zh', bound('doc_a', GRAPH_KB))

    operators = {op['operator'] for op in _iter_operators(node_config)}
    assert {'VectorRetriever', 'KeywordRetriever', GRAPH_OPERATOR} <= operators

    assert _operator_named(node_config, GRAPH_OPERATOR)['kwargs']['knowledge_base_name'] == [GRAPH_KB]
    assert _operator_named(node_config, 'VectorRetriever')['kwargs']['knowledge_info_list'][0][
        'knowledge_base_name'] == ['doc_a']
    assert _operator_named(node_config, 'KeywordRetriever')['kwargs']['knowledge_base_name'] == [
        'doc_a']

    for operator in _all_stage_operators(node_config, 'responsesynthesizer'):
        assert operator['kwargs']['generator-config'][0]['knowledge_base_name'] == [
            'doc_a', GRAPH_KB]


def test_blended_normal_only_stays_on_the_base_template():
    """只有普通库 → 仍是基础 ``Blended``（不因为多了图谱分支就改变既有行为）。"""
    node_config, _ = template_loader.build_default_canvas(
        'Blended', 'zh', bound('doc_a'))

    operators = {op['operator'] for op in _iter_operators(node_config)}
    assert GRAPH_OPERATOR not in operators
    assert _operator_named(node_config, 'VectorRetriever')['kwargs']['knowledge_info_list'][0][
        'knowledge_base_name'] == ['doc_a']


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_blended_graph_variants_pass_the_publish_gate(language, capabilities):
    """真实图谱变体播种出的画布必须能过发布硬门槛（不能只在手工插节点时能过）。"""
    for names in (GRAPH_KB,):
        node_config, other_node_config = template_loader.build_default_canvas(
            'Blended', language, bound(*names))
        canvas = FlowCanvasInput(node_config_dto_list=node_config,
                                 other_node_config_list=other_node_config)
        validation.check_runnable(canvas, capabilities)
        assert validation.precheck_warnings(canvas, language, capabilities) == []

    node_config, other_node_config = template_loader.build_default_canvas(
        'Blended', language, bound('doc_a', GRAPH_KB))
    canvas = FlowCanvasInput(node_config_dto_list=node_config,
                             other_node_config_list=other_node_config)
    validation.check_runnable(canvas, capabilities)
    assert validation.precheck_warnings(canvas, language, capabilities) == []


def test_struct_knowledge_kbase_is_rejected():
    """结构化（数据库）库 → 拒绝：它要走未迁的 ``Sequential_sql``（SqlRetriever/SqlExecutor）。"""
    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas('Sequential', 'zh', bound(
            'doc_a', type='struct_knowledge'))

    assert excinfo.value.key == 'kbase.struct.unsupported'


def test_malformed_bound_info_is_a_business_error_not_a_500():
    """畸形 ``boundInfo``（分组里塞字符串）→ 可读的业务错误，而不是 0001 服务器错误。"""
    for bad in ({'running': ['doc_a']}, {'running': [None, 42]}, {'running': 'oops'}):
        with pytest.raises(FlowError) as excinfo:
            template_loader.build_default_canvas('Sequential', 'zh', bad)

        assert excinfo.value.key == 'canvas.no.kbase'

    # 数组里混一个坏元素、但有能用的条目 → 正常播种
    node_config, _ = template_loader.build_default_canvas(
        'Sequential', 'zh', {'running': ['oops', {'tableName': 'doc_a',
                                                  'embeddingModel': 'bge-base-zh-v1.5'}]})
    assert _find_stage(node_config, 'retriever')[0]['kwargs']['embedding'] == 'bge-base-zh-v1.5'


# ----------------------------------------------------------------------
# 图谱库的去向：只能进 KnowledgeGraphRetriever
#
# 上面两个哨兵（`test_graph_kbase_is_rejected*`）钉的是「模板里没有图谱检索节点时拒」。
# 这一组钉的是另一半：**画布上真有图谱检索节点时**图谱库要落进它、普通库不要落进它。
# 之所以两个方向都要钉死：本服务是拿库名拼 `data_<库名>` 查表的，图谱库的名字是
# `graph_<uuid>` —— 图谱库进普通检索器、或普通库进图谱检索器，都是查不到的表，
# 结果都是「HTTP 200、答得不对」，**不报错**。
# ----------------------------------------------------------------------

GRAPH_OPERATOR = 'KnowledgeGraphRetriever'
GRAPH_PACKAGE = 'core.rag.retriever.knowledgegraph_retriever'
GRAPH_KB = 'graph_0f28f086c3cd4e55a16b19784609951e'


def _graph_retriever_node(knowledge_base_name):
    """一个图谱检索节点，形状照前端 ``retriever/Drawer.vue`` 的 ``KnowledgeGraphRetriever``。

    :param knowledge_base_name: 该字段的值；传 ``None`` 表示**整个字段不写**。
    ``variables`` 与 ``data.variables`` 各构造一份**独立**副本（与真实模板一致）。
    """
    def operator():
        kwargs = {'top_k': 30, 'depth': 1, 'score': 0, 'embedding': ''}
        if knowledge_base_name is not None:
            kwargs['knowledge_base_name'] = knowledge_base_name
        return {'operator': GRAPH_OPERATOR, 'package': GRAPH_PACKAGE, 'kwargs': kwargs}

    return {
        'nodeId': 'node_graph_retriever',
        'componentType': 'RETRIEVER',
        'variables': {'retriever': [operator()]},
        'data': {'variables': {'retriever': [operator()]}},
    }


def _seed_graph_retriever(monkeypatch, knowledge_base_name):
    """让 ``build_default_canvas`` 读到「画布上多一个图谱检索节点」的模板。

    Sequential/Conditional 模板里没有图谱节点（Blended 会按绑定切到图谱变体，不需要
    这里的手工插桩），所以在这里手工插一个 —— 插的是**读出来的对象树**，
    模板文件本身不动。
    """
    load_template = template_loader.load_template

    def with_graph_retriever(template, language):
        canvas = load_template(template, language)
        canvas['nodeConfigDTOList'].append(_graph_retriever_node(knowledge_base_name))
        return canvas

    monkeypatch.setattr(template_loader, 'load_template', with_graph_retriever)


@pytest.mark.parametrize('template', ['Sequential'])
def test_graph_kbase_is_filled_into_the_graph_retriever(template, monkeypatch):
    """图谱库被填进图谱检索器的 ``kwargs.knowledge_base_name``，普通库**不进**它。

    同时钉住普通那条路没被带歪：普通库照旧进向量/关键词检索器（不进图谱检索器），
    合成器照旧吃**全部**库（图谱库也要有 per-KB prompt）。
    """
    _seed_graph_retriever(monkeypatch, knowledge_base_name=[])
    node_config, _ = template_loader.build_default_canvas(
        template, 'zh', bound('doc_a', GRAPH_KB))

    graph = _operator_named(node_config, GRAPH_OPERATOR)
    assert graph['kwargs']['knowledge_base_name'] == [GRAPH_KB]
    assert graph['kwargs']['embedding'] == 'bge-base-zh-v1.5'

    # 两条路各走各的：图谱检索器只收图谱库，普通检索器只收普通库
    for operator in _all_stage_operators(node_config, 'retriever'):
        if operator['operator'] == 'FusionRetriever':
            continue                    # 融合器只合并下游结果，本身没有绑定字段
        expected = [GRAPH_KB] if operator['operator'] == GRAPH_OPERATOR else ['doc_a']
        assert _knowledge_base_names(operator) == expected, operator['operator']

    for operator in _all_stage_operators(node_config, 'responsesynthesizer'):
        assert operator['kwargs']['generator-config'][0]['knowledge_base_name'] == [
            'doc_a', GRAPH_KB]

    # 两份 variables 都要填（只填一份 = 用户打开画布再保存就把绑定丢了）
    graph_node = _node_named(node_config, 'node_graph_retriever')
    assert graph_node['data']['variables']['retriever'][0]['kwargs']['knowledge_base_name'] == [GRAPH_KB]
    assert json.dumps(graph_node['variables'], sort_keys=True, ensure_ascii=False) == \
        json.dumps(graph_node['data']['variables'], sort_keys=True, ensure_ascii=False)


def test_graph_only_binding_is_seeded_when_a_graph_node_exists(monkeypatch):
    """只绑图谱库也能播种（`Blended_graph` 那条路的形状）：库名进图谱检索器与合成器。

    普通检索器这时没有库可绑，库名列表是**空的** —— 空的不是「图谱库漏进来了」。
    """
    _seed_graph_retriever(monkeypatch, knowledge_base_name=[])
    node_config, _ = template_loader.build_default_canvas('Sequential', 'zh', bound(GRAPH_KB))

    assert _operator_named(node_config, GRAPH_OPERATOR)['kwargs']['knowledge_base_name'] == [GRAPH_KB]
    assert _knowledge_base_names(_operator_named(node_config, 'VectorRetriever')) == []
    for operator in _all_stage_operators(node_config, 'responsesynthesizer'):
        assert operator['kwargs']['generator-config'][0]['knowledge_base_name'] == [GRAPH_KB]


@pytest.mark.parametrize('knowledge_base_name', [GRAPH_KB, None])
def test_graph_node_that_cannot_receive_the_names_is_still_rejected(knowledge_base_name, monkeypatch):
    """「有图谱节点」不等于「能接收」：字段不是列表形状时照样显式失败。

    字符串形态前端也认（``processKnowledgeGraphRetriever`` 会把字符串拆成数组），
    但播种时写不进去 = 静默丢库，正是这条检查要拦的。判据与回填代码用同一个函数。
    """
    _seed_graph_retriever(monkeypatch, knowledge_base_name=knowledge_base_name)

    with pytest.raises(FlowError) as excinfo:
        template_loader.build_default_canvas('Sequential', 'zh', bound(GRAPH_KB))

    assert excinfo.value.key == 'kbase.graph.unsupported'


def test_canvas_with_graph_retriever_passes_the_publish_gate(monkeypatch, capabilities):
    """带图谱检索算子的画布不能被判成「算子不可执行」—— 新包名的前缀漂移哨兵。

    ``RUNNABLE_OPERATOR_PACKAGES`` 与前端 ``Drawer.vue`` 写进画布的包名
    （``core.rag.retriever.knowledgegraph_retriever``）差一个字，用户画得出来、
    却发布不了，且只在发布那一刻才暴露。
    """
    _seed_graph_retriever(monkeypatch, knowledge_base_name=[])
    node_config, other_node_config = template_loader.build_default_canvas(
        'Sequential', 'zh', bound('doc_a', GRAPH_KB))
    canvas = FlowCanvasInput(node_config_dto_list=node_config,
                             other_node_config_list=other_node_config)

    assert validation.find_unrunnable_operators(canvas) == []
    validation.check_runnable(canvas, capabilities)
    assert validation.precheck_warnings(canvas, 'zh', capabilities) == []


# ----------------------------------------------------------------------
# 播种结果
# ----------------------------------------------------------------------

@pytest.mark.parametrize('template', TEMPLATES)
def test_build_fills_knowledge_binding_in_both_stages(template):
    """绑定回填三处：检索器的库名与向量模型、合成器的 per-KB 配置。"""
    names = ['doc_a', 'doc_b']
    node_config, _ = template_loader.build_default_canvas(template, 'zh', bound(*names))

    # 混合/条件检索有多条检索路径（融合 / 关键词 / 向量），逐条看它们的库名写没写上
    for operator in _all_stage_operators(node_config, 'retriever'):
        if operator['operator'] == 'FusionRetriever':
            # 融合器只负责合并下游检索器的结果，本身没有绑定字段
            continue
        assert _knowledge_base_names(operator) == names, operator['operator']

    synthesizers = _all_stage_operators(node_config, 'responsesynthesizer')
    assert synthesizers, '模板里应当有合成器'
    for operator in synthesizers:
        assert operator['kwargs']['generator-config'][0]['knowledge_base_name'] == names


@pytest.mark.parametrize('template', TEMPLATES)
def test_build_fills_both_variable_copies(template):
    """两份 variables 都要回填 —— 只填一份时「打开画布再保存」会把绑定冲掉。

    `exportGraph()` 回写的是 ``data.variables``，而播种只写
    ``variables`` 时，用户保存一次就会得到「检索器没绑知识库、向量模型是模板里那个旧值」
    的画布：保存不报错、发布不报错，问答只是查不到东西。
    """
    node_config, _ = template_loader.build_default_canvas(
        template, 'zh', bound('doc_a'))

    for node in node_config:
        data_variables = (node.get('data') or {}).get('variables')
        assert json.dumps(node.get('variables'), sort_keys=True, ensure_ascii=False) == \
            json.dumps(data_variables, sort_keys=True, ensure_ascii=False), \
            f'{node["componentType"]} 的两份 variables 回填后不一致'

    # 回填确实发生在两份里，而不是「两份都是空的」
    assert _all_stage_operators(node_config, 'retriever'), '模板里应当有检索器'
    assert _find_stage(node_config, 'retriever'), '顶层那份也要能取到'


def test_blended_seeds_all_three_retrieval_paths():
    """混合检索 = 关键词 + 向量 → 融合：三条检索路径都要可用。

    融合器（``FusionRetriever``）自己没有绑定字段，靠运行期 ``update_retrievers``
    把同一条画布上的其它检索器挂进去 —— 所以**关键词与向量那两条必须把库名写上**，
    否则融合出来的结果里少一路，而且不报错。
    """
    node_config, _ = template_loader.build_default_canvas(
        'Blended', 'zh', bound('doc_a', 'doc_b'))

    by_name = {op['operator']: op for op in _all_stage_operators(node_config, 'retriever')}
    assert set(by_name) == {'FusionRetriever', 'KeywordRetriever', 'VectorRetriever'}
    assert _knowledge_base_names(by_name['KeywordRetriever']) == [
        'doc_a', 'doc_b']
    assert _knowledge_base_names(by_name['VectorRetriever']) == [
        'doc_a', 'doc_b']
    assert by_name['VectorRetriever']['kwargs']['embedding'] == 'bge-base-zh-v1.5'


def test_conditional_seeds_both_branches():
    """条件检索的两条分支各自带一套后检索 + 合成器，两套都要绑库。"""
    node_config, _ = template_loader.build_default_canvas(
        'Conditional', 'zh', bound('doc_a'))

    synthesizers = _all_stage_operators(node_config, 'responsesynthesizer')
    assert len(synthesizers) == 2, '条件检索是两条分支，每条各有一个合成器'
    for operator in synthesizers:
        assert operator['kwargs']['generator-config'][0]['knowledge_base_name'] == ['doc_a']


def test_build_leaves_llm_empty():
    """``llm`` 留空：运行期回落到部署的 GENERATION_MODEL（部署属性，不该写进画布）。"""
    node_config, _ = template_loader.build_default_canvas('Sequential', 'zh', bound('doc_a'))

    for stage in ('preretriever', 'responsesynthesizer'):
        for operator in _find_stage(node_config, stage):
            kwargs = operator.get('kwargs') or {}
            assert kwargs.get('llm', '') == ''
            for config in kwargs.get('generator-config') or []:
                assert config.get('llm', '') == ''


def test_build_does_not_mutate_the_loaded_template():
    """连续两次播种互不影响（每次都是模板的一份深拷贝）。"""
    bound_info = bound('doc_a')
    first, _ = template_loader.build_default_canvas('Sequential', 'zh', bound_info)
    first[0]['variables'] = '被改坏了'

    second, _ = template_loader.build_default_canvas('Sequential', 'zh', bound_info)
    assert second[0]['variables'] != '被改坏了'


@pytest.mark.parametrize('template', TEMPLATES)
def test_built_canvas_passes_publish_gate(template, capabilities):
    """播种出来的画布必须能过发布的硬门槛 —— 否则「建了就能用」是假的。

    本部署没有 rerank 端点（``capabilities`` 的默认值），所以模板里的后检索算子
    必须是 ``LLMReranker`` 而不是 ``ExternalModelReranker``。
    """
    node_config, other_node_config = template_loader.build_default_canvas(
        template, 'zh', bound('doc_a'))

    validation.check_runnable(
        FlowCanvasInput(node_config_dto_list=node_config,
                        other_node_config_list=other_node_config),
        capabilities,
    )


@pytest.mark.parametrize('template', TEMPLATES)
def test_built_canvas_has_no_precheck_warnings(template, capabilities):
    """干净画布不该在 preCheck 里给用户一堆警告。"""
    node_config, other_node_config = template_loader.build_default_canvas(
        template, 'zh', bound('doc_a'))

    warnings = validation.precheck_warnings(
        FlowCanvasInput(node_config_dto_list=node_config,
                        other_node_config_list=other_node_config),
        'zh', capabilities,
    )
    assert warnings == []


# ----------------------------------------------------------------------
# 端点契约
# ----------------------------------------------------------------------

def test_create_rejects_unsupported_template_with_business_error(client):
    response = client.post(f'{KB_SERVICE_PREFIX}/workflows',
                           json={'workFlowId': 'wf_sql', 'name': 'x', 'template': 'Sequential_sql',
                                 'boundInfo': bound('doc_a')},
                           headers={'X-Emp-No': 'admin'})
    assert response.status_code == 422
    body = response.json()
    assert body['code'] == 'unsupported_template'
    assert body['detail'] == ('Template Sequential_sql is not supported in this version '
                              '(choose Sequential, Blended or Conditional)')


def test_create_writes_nothing_when_template_is_unsupported(client, store):
    """模板不支持时**什么都不该写**（否则留下一个打不开画布的孤儿工作流）。"""
    client.post(f'{KB_SERVICE_PREFIX}/workflows',
                json={'workFlowId': 'wf_orphan', 'name': 'x', 'template': 'Sequential_sql',
                      'boundInfo': bound('doc_a')},
                headers={'X-Emp-No': 'admin'})

    assert store.get_workflow('wf_orphan') is None
    assert store.get_draft('wf_orphan') is None


@pytest.mark.parametrize('template', TEMPLATES)
def test_create_accepts_every_supported_template(client, template):
    """三个模板都要建得出来，且画布上带的是对应引擎与四条连线。"""
    workflow_id = f'wf_{template.lower()}'
    create_workflow(client, workflow_id, template=template)

    _, bo = _kb_bo(client.get(f'{KB_SERVICE_PREFIX}/workflows/{workflow_id}/flow'))
    assert bo['template'] == template
    engine = _find_other(bo, 'QUERY_ENGINE')['variables']['queryengine']['operator']
    assert engine == ENGINE_OF_TEMPLATE[template][0]
    edges = _find_other(bo, 'EDGES')['variables']['edges']
    assert edges, '画布必须有连线（没有连线就是那个「只有开始/结束」的老问题）'


def test_created_workflow_keeps_its_template(client):
    create_workflow(client, 'wf_tpl')
    _, bo = _kb_bo(client.get(f'{KB_SERVICE_PREFIX}/workflows/wf_tpl/flow'))
    assert bo['template'] == 'Sequential'


def test_language_selects_the_template_variant():
    """中文/英文是两套模板（算子里的提示词不同）。

    语言在**建流那一刻**定下来并落进画布 —— 之后 GET /flow 换 ``language-option``
    不会再重渲染已存的画布（画布是用户数据，不是每次请求现拼的视图）。
    """
    zh, _ = template_loader.build_default_canvas('Sequential', 'zh-CN', bound('doc_a'))
    en, _ = template_loader.build_default_canvas('Sequential', 'en-US', bound('doc_a'))

    zh_prompt = _find_stage(zh, 'preretriever')[0]['kwargs']['prompt']
    en_prompt = _find_stage(en, 'preretriever')[0]['kwargs']['prompt']

    assert zh_prompt != en_prompt
    assert '问题补全' in zh_prompt          # 中文模板确实是中文
    assert 'question completion' in en_prompt


# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------

def _kb_bo(response):
    if 200 <= response.status_code < 300:
        return '0000', response.json()
    body = response.json()
    return body['code'], None


def _iter_operators(node_config):
    for node in node_config:
        for value in (node.get('variables') or {}).values():
            if isinstance(value, list):
                yield from value


def _find_other(canvas, component_type):
    return next(o for o in canvas['otherNodeConfigList'] if o['componentType'] == component_type)


def _find_stage(node_config, stage_key):
    """取第一个定义了该环节的节点里的算子列表。"""
    for node in node_config:
        variables = node.get('variables') or {}
        if isinstance(variables.get(stage_key), list):
            return variables[stage_key]
    return []


def _node_named(node_config, node_id):
    return next(node for node in node_config if node.get('nodeId') == node_id)


def _operator_named(node_config, operator):
    """按算子名找画布上的算子（扫的是服务端那份 ``variables``，即播种写入的那份）。"""
    for candidate in _iter_operators(node_config):
        if candidate.get('operator') == operator:
            return candidate
    raise AssertionError(f'画布上没有 {operator} 算子')


def _all_stage_operators(node_config, stage_key):
    """**所有**节点里该环节的算子（条件检索就是同环节两个分支各一个）。"""
    result = []
    for node in node_config:
        variables = node.get('variables') or {}
        stage = variables.get(stage_key)
        if isinstance(stage, list):
            result.extend(stage)
    return result


def _knowledge_base_names(operator):
    """从检索器算子里读出绑定的库名：关键词检索放在 kwargs 顶层，向量检索在列表中。"""
    kwargs = operator.get('kwargs') or {}
    if isinstance(kwargs.get('knowledge_base_name'), list):
        return kwargs['knowledge_base_name']
    for info in kwargs.get('knowledge_info_list') or []:
        if isinstance(info.get('knowledge_base_name'), list):
            return info['knowledge_base_name']
    return []
