"""建流模板 → 运行时配置：本服务能真的跑起来那三种工作流吗。

`flow_api/templates/{语言}_{模板}.json` 由建流接口播种进画布，用户点「发布」之后
才会在本服务里执行。所以模板必须能真正跑起来：模板声明的引擎要能
import 得到、算子要能实例化、连线要能翻译成运行期的边 —— 任何一条断了，症状都是
「画布建得出来、发布也成功，第一次提问 500」。

单测以 RKB 仓里的模板文件为**输入**（不跨服务调接口，只读同一棵工作树里的数据文件），
模板换了测试就会跟着报 —— 这正是要的：模板是跨服务契约，不是某一侧的内部数据。
"""
import json
import pathlib

import pytest


from engine.config_loader import default_packages_info
from chat.translator import canvas_to_rag_config

#: 模板名 → 引擎（与 RKB 侧 `flow_api/canvas.py` 的 ENGINE_OPERATORS 同一套）
TEMPLATES = {
    'Sequential': ('SequentialQueryEngine', 'core.rag.query_engine.sequential_query_engine'),
    'Blended': ('BlendedQueryEngine', 'core.rag.query_engine.blended_query_engine'),
    'Conditional': ('ConditionalQueryEngine', 'core.rag.query_engine.conditional_query_engine'),
}


def _templates_dir() -> pathlib.Path:
    """`src/workflow/templates` 的绝对路径（与本包同服务，见模块文档）。

    模板与本包同仓同服务，所以这里**硬失败**：找不到 = 仓库不完整。
    「静默少跑」是最不该有的失效模式 —— 模板整体丢失会表现为一片绿。
    """
    # 本文件在 <服务根>/backend/tests/engine/ 下，
    # parents[2] = <服务根>，模板目录就在 src/workflow/templates。
    directory = pathlib.Path(__file__).resolve().parents[2] / 'src' / 'workflow' / 'templates'
    if not directory.is_dir():
        raise AssertionError(f'模板目录不存在：{directory}（仓库不完整？）')
    return directory


def _load(template, language='zh'):
    directory = _templates_dir()
    canvas = json.loads((directory / f'{language}_{template}.json').read_text(encoding='utf-8'))
    return canvas_to_rag_config(f'wf_{template}', canvas['nodeConfigDTOList'],
                                canvas['otherNodeConfigList'])


@pytest.mark.parametrize('template', list(TEMPLATES))
def test_template_engine_is_registered_in_this_service(template):
    """模板声明的引擎必须登记在 `default_packages_info.query_engine_packages` 里。

    这是**跨服务的哨兵**：RKB 放行了某个模板、把引擎写进画布，而本服务没登记，
    运行到 `importlib` 才炸（`instance_query_engine` 找不到包）。
    """
    expected_operator, expected_package = TEMPLATES[template]
    config = _load(template)

    assert config['query-engine']['operator'] == expected_operator
    assert config['query-engine']['package'] == expected_package
    assert default_packages_info.query_engine_packages.get(expected_operator) == expected_package


@pytest.mark.parametrize('template', list(TEMPLATES))
def test_template_translates_into_a_runnable_config(template):
    """翻译出来的四段都要有算子，且引擎不是空的（否则运行期直接报「没有编排引擎」）。"""
    config = _load(template)

    assert config['query-engine']['operator']
    for stage in ('pre-retriever', 'retriever', 'post-retriever', 'response-synthesizer'):
        assert config[stage], f'{template} 的 {stage} 段是空的'
        for operator in config[stage]:
            assert operator['package'] in default_packages_info.operator_packages.values(), \
                f"{operator['operator']} 不在运行时算子清单里"
            assert operator['id'] > 0


def test_blended_template_keeps_three_retrieval_paths():
    """混合检索 = 关键词 + 向量 → 融合。三条路径都要在运行期配置里，顺序按画布。

    `BlendedQueryEngine` 是把同一条画布上的其它检索器挂到 `FusionRetriever` 上跑
    （`operator_bean.retrievers`）—— 少一条路径不报错，只是融合结果里少一路。
    """
    config = _load('Blended')
    operators = [operator['operator'] for operator in config['retriever']]

    assert set(operators) == {'KeywordRetriever', 'VectorRetriever', 'FusionRetriever'}
    # 融合器在画布上位于两条路的下游，翻译后必须仍然排在它们**后面**
    # （`BlendedQueryEngine` 把它拿来当主检索器，前面那两条是它的输入）
    assert operators[-1] == 'FusionRetriever'


def test_conditional_template_wires_each_branch_to_its_own_synthesizer():
    """条件检索的两条分支各自带后检索 + 合成器，翻译后必须各连各的。

    引擎用 `get_chain_all_nodes(检索器)` 沿边找自己那一路的后检索与合成器；
    两条分支串成一条链时，第一条分支会连到第二条分支的合成器上，另一条分支则
    拿不到自己的后检索 —— 用户画了两条路，跑出来是一条半。
    """
    config = _load('Conditional')
    edges = config['workflow']['edges']

    retrievers = [operator['id'] for operator in config['retriever']]
    assert len(retrievers) == 2, '条件检索是两条分支'
    synthesizers = {operator['id'] for operator in config['response-synthesizer']}
    post_retrievers = {operator['id'] for operator in config['post-retriever']}

    reached = [_chain(edges, retriever) for retriever in retrievers]
    for chain in reached:
        assert len(set(chain) & synthesizers) == 1, '一路检索应当只挂一个合成器'
        assert set(chain) & post_retrievers, '一路检索应当挂上自己的后检索算子'
    assert reached[0] != reached[1], '两条分支不能共用同一套后检索/合成器'
    # 分支之间不串门：一条链上不该出现另一条分支的检索器
    for retriever, chain in zip(retrievers, reached):
        assert not (set(chain) & (set(retrievers) - {retriever}))


def test_engine_sets_match_between_the_backend_and_this_service():
    """两侧的引擎集合必须**相等**：RKB 放行的引擎 = 本服务登记的引擎。

    只看模板能覆盖到的引擎是不够的 —— 模板没用到、却没登记（发布成功、一问 500），
    或登记了、后端却拒（画布存不下去）都会漏。这里直接把 RKB 的
    `compat/flow_api/canvas.py` 读进来比集合（纯 stdlib 模块，`importlib` 按文件路径加载）。
    """
    directory = _templates_dir()
    import importlib.util

    canvas_py = directory.parent / 'canvas.py'
    spec = importlib.util.spec_from_file_location('rkb_flow_canvas', canvas_py)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    backend = set(module.ENGINE_OPERATORS)
    runtime = set(default_packages_info.query_engine_packages)
    assert backend == runtime, (
        f'两侧不一致：仅后端放行 {backend - runtime}；仅运行时登记 {runtime - backend}')


def test_conditional_template_survives_a_stray_node():
    """在条件检索的**真实模板**上拖进一个没连线的节点，翻译后分支必须原样还在。

    `_load` 读的是仓里的模板文件；这里给它追加一个孤立节点（用户在画布上拖进来、
    没连线就保存的常态），再走一遍翻译 —— 定序一旦因为「不止一个起点」而退回固定
    环节序，两条分支就会被串成一条链，而这个退化在保存、发布、precheck 上都不报错。
    """
    directory = _templates_dir()
    canvas = json.loads((directory / 'zh_Conditional.json').read_text(encoding='utf-8'))
    for stray in ({'nodeId': 'stray-empty', 'componentType': 'RETRIEVER', 'variables': None},
                  {'nodeId': 'stray-configured', 'componentType': 'RETRIEVER',
                   'variables': {'retriever': [{'id': 1, 'operator': 'VectorRetriever',
                                                'package': 'core.rag.retriever.vector_retriever',
                                                'kwargs': {}}]}}):
        nodes = canvas['nodeConfigDTOList'] + [stray]
        config = canvas_to_rag_config('wf_stray', nodes, canvas['otherNodeConfigList'])
        edges = config['workflow']['edges']
        # 只取**在边里出现过**的检索器（孤立节点不在任何边上，运行期也够不着它）
        connected = {node for edge in edges for node in edge}
        retrievers = [operator['id'] for operator in config['retriever']
                      if operator['id'] in connected]
        synthesizers = {operator['id'] for operator in config['response-synthesizer']}
        assert len(retrievers) == 2, f'{stray["nodeId"]}: 主链上应当还剩两条检索路径'

        chains = [_chain(edges, retriever) for retriever in retrievers]
        assert all(chain for chain in chains), f'{stray["nodeId"]}: 检索器背后丢了后检索/合成器'
        assert len({tuple(sorted(set(chain) & synthesizers)) for chain in chains}) == 2, \
            f'{stray["nodeId"]}: 两条分支共用或丢了合成器（分支被摊平）'


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
