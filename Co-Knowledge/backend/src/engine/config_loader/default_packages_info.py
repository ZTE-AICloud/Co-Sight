"""内置算子/引擎的包映射。

清单是写死的：只列出本服务 vendor 进来的算子。**不含自定义算子** —— 自定义算子包
由 runtime 从 rag-extend 加载，本服务没有对应的加载链。

这份清单与 ``workflow/validation.py`` 的可运行算子包清单是同一套东西，
两侧必须一起改 —— 一边加了、另一边没加，就会出现「画布上能选、运行时找不到」。
"""

# 三个编排引擎对应三种工作流模板（`flow_api/templates/{zh,en}_{模板}.json` 的
# QUERY_ENGINE 伪节点里写的 operator/package，必须完全一致）：
#   顺序检索 → SequentialQueryEngine、混合检索 → BlendedQueryEngine、条件检索 → ConditionalQueryEngine
# 少登记一个的表现是「画布建得出来、发布也不报错，第一次提问才 500（import 不到引擎）」。
query_engine_packages = {
    'SequentialQueryEngine': 'core.rag.query_engine.sequential_query_engine',
    'BlendedQueryEngine': 'core.rag.query_engine.blended_query_engine',
    'ConditionalQueryEngine': 'core.rag.query_engine.conditional_query_engine',
}

operator_packages = {
    # pre-retriever
    'LLMQueryRewriter': 'core.rag.pre_retriever.query_transform.query_rewrite',
    # 类名是 LLMSemanticRouting（不是 LLMQueryRouter）—— 按运行时真实类名登记，
    # 否则「目录里能选、import 时找不到类」
    'LLMSemanticRouting': 'core.rag.pre_retriever.query_selector.query_routing',
    # retriever
    'VectorRetriever': 'core.rag.retriever.vector_retriever',
    'KeywordRetriever': 'core.rag.retriever.keyword_retriever',
    'FusionRetriever': 'core.rag.retriever.fusion_retriever',
    'KnowledgeGraphRetriever': 'core.rag.retriever.knowledgegraph_retriever',
    # post-retriever
    'LLMReranker': 'core.rag.post_retriever.llm_reranker',
    # 外部重排模型（模型由注册表决定）
    'ExternalModelReranker': 'core.rag.post_retriever.external_model_reranker',
    # response synthesizer
    'RagSimpleSummarizer': 'core.rag.response_synthesizer.simple_summarizer',
}


# ---------------------------------------------------------------------------
# 遗留包名 → 可导入模块名的翻译
#
# 上面两张表里的值是 `core.rag.*` 形状 —— 它们**不是随便起的名字**，而是三处对齐
# 的契约（见 `workflow/validation.py` 的模块注释）：
#   1. 本文件（运行时真实导入）；
#   2. `workflow/validation.py` 的可运行算子包清单（权威清单）；
#   3. 画布前端写进画布 JSON 的 `package` 字段。
# `workflow/validation.find_unavailable_operators` 是**按字符串**判定「能不能跑」的，
# 所以改这里的值 = 让库里所有已保存/已发布的画布被判成「不可运行」（发布被硬拒）。
#
# 本服务里这些模块的真实位置是 `engine.*`，所以只在**导入边界**翻译一次：
# 登记值保持原样，导入前过一遍 :func:`to_importable`。
# ---------------------------------------------------------------------------

#: Logical IDs are persisted in canvases/templates.  Only this boundary maps
#: them to the physical runtime package; the IDs themselves never change.
_LOGICAL_PREFIX = 'core.rag.'
_PHYSICAL_PREFIX = 'engine.'


def to_importable(package: str) -> str:
    """Map a persisted logical operator ID to its physical module.

    ``'core.rag.retriever.vector_retriever'`` → ``'engine.retriever.vector_retriever'``

    Idempotent: an already-physical package (or a custom operator package) is
    returned unchanged.
    """
    if not package:
        return package
    if package.startswith(_LOGICAL_PREFIX):
        return _PHYSICAL_PREFIX + package[len(_LOGICAL_PREFIX):]
    return package
