"""画布校验：结构校验 / 可运行性校验 / preCheck 警告 / 导出文件名。

**保存与发布的门槛刻意不同**（设计约束）：

* 保存草稿只拒**结构性错误**（空画布 / 没有 QUERY_ENGINE / 超 5MB）；
* preCheck 把这些之外的运行期风险作为 ``{success:false, message}`` 返回，由前端弹二次确认；
* 发布把**全部警告升级为硬拒**。

前端的保存流程是「preCheck success=false → 弹二次确认 → 用户确认后照样保存」，
保存要是硬拒，用户连一个半成品草稿都存不下来，画布等于不可用。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from workflow import canvas as canvas_util
from workflow.errors import FlowError
from workflow.messages import render
from workflow.models import FlowCanvasInput
from workflow.runtime_config import RuntimeCapabilities

# vendor 清单：本栈真的能实例化的算子包。
#
# **包名必须带 ``core.rag.`` 前缀**，与另外三处对齐（改这里时要一起改）：
#   * 本服务维护的可运行算子包清单（权威清单）；
#   * 画布前端（``modules/retriever/Drawer.vue`` 等）写进画布的 ``package``；
#   *编排层``default_packages_info.operator_packages``（运行时真实导入的包名）。
# 少了前缀会让**每一个从画布保存下来的算子都判成「不可运行」** —— 保存没事，
# 发布会被硬拒。这类「只差一个前缀」的漂移由
# ``tests/test_flow_api_templates.py`` 的「模板算子全在清单里」钉住。
RUNNABLE_OPERATOR_PACKAGES = frozenset({
    'core.rag.pre_retriever.query_transform.query_rewrite',
    'core.rag.pre_retriever.query_selector.query_routing',
    'core.rag.retriever.vector_retriever',
    'core.rag.retriever.keyword_retriever',
    'core.rag.retriever.fusion_retriever',
    # 图谱检索：只有它接收图谱知识库（`template_loader` 把图谱库单独填进它的
    # `kwargs.knowledge_base_name`，普通检索器不碰图谱库 —— 填进去是静默空命中）
    'core.rag.retriever.knowledgegraph_retriever',
    'core.rag.post_retriever.external_model_reranker',
    'core.rag.post_retriever.llm_reranker',
    'core.rag.response_synthesizer.simple_summarizer',
})

OPERATOR_EXTERNAL_MODEL_RERANKER = 'ExternalModelReranker'
RERANK_OPERATOR_NAMES = frozenset({OPERATOR_EXTERNAL_MODEL_RERANKER})
OPERATOR_LLM_RERANKER = 'LLMReranker'
OPERATOR_LLM_QUERY_REWRITER = 'LLMQueryRewriter'
KEY_KWARGS = 'kwargs'
KEY_LLM = 'llm'
KEY_MODEL = 'model'
#: 检索器 ``kwargs`` 里的向量模型名（普通检索器与图谱检索器同名同义）
KEY_EMBEDDING = 'embedding'

# preCheck 多条警告合并成一句时用的分隔符
MESSAGE_SEPARATOR = '；'


def supported_engines() -> str:
    """可执行引擎的展示名（稳定顺序，喂给 ``engine.unsupported`` 的 ``{1}``）。"""
    return ', '.join(sorted(canvas_util.ENGINE_OPERATORS))


def serialized_size(canvas: FlowCanvasInput) -> int:
    """画布序列化后的字节数（估算上限用）。序列化失败返回 0（交给后续校验/DB 报错）。"""
    try:
        payload = {
            'flowType': canvas.flow_type,
            'version': canvas.version,
            'nodeConfigDTOList': canvas.node_config_dto_list,
            'otherNodeConfigList': canvas.other_node_config_list,
        }
        return len(json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8'))
    except (TypeError, ValueError):
        return 0


def check_structure(canvas: FlowCanvasInput, language: str) -> None:
    """结构性校验：这些错误下画布连「一条编排」都算不上 → 抛业务异常（0005）。"""
    if not canvas.node_config_dto_list:
        raise FlowError('canvas.empty')
    if serialized_size(canvas) > canvas_util.MAX_CANVAS_BYTES:
        limit_mb = str(canvas_util.MAX_CANVAS_BYTES // 1024 // 1024)
        raise FlowError('canvas.too.large', limit_mb)
    engine = canvas_util.find_engine_operator(canvas.other_node_config_list)
    if not engine or not engine.strip():
        raise FlowError('canvas.no.engine')


def find_unrunnable_operators(canvas: FlowCanvasInput) -> list[str]:
    """找出运行时跑不了的算子（按 package 判定，名字相同但包不在 vendor 清单里也算）。

    用 set 去重 + ``sorted`` 保持稳定顺序，
    避免同一算子重复报。
    """
    result = set()
    for operator in canvas_util.iter_operators(canvas.node_config_dto_list):
        package_name = operator.get('package')
        package_name = '' if package_name is None else str(package_name)
        if package_name not in RUNNABLE_OPERATOR_PACKAGES:
            operator_name = operator.get('operator')
            result.add(package_name if operator_name is None else str(operator_name))
    return sorted(result)


def uses_external_model_reranker_without_endpoint(canvas: FlowCanvasInput,
                                                  capabilities: RuntimeCapabilities) -> bool:
    """画布里用了外部重排模型算子，而本部署没配 rerank 端点 —— 这条编排跑起来必失败。

    「判据是部署能力而不是算子名单」（约定）：该算子是 vendor 了的，
    只在**没配 rerank 端点**时才必然失败。将来接了 rerank 端点，画布不用改、这里也不用改。
    """
    if capabilities.has_rerank_endpoint():
        return False
    names = canvas_util.find_operator_names(canvas.node_config_dto_list)
    return bool(RERANK_OPERATOR_NAMES & set(names))


def find_unavailable_rerank_models(canvas: FlowCanvasInput,
                                   capabilities: RuntimeCapabilities) -> list[str]:
    """画布上显式选中的重排模型，但本部署没有（去重、稳定排序）。

    只检查外部重排模型算子（``ExternalModelReranker``）的 ``kwargs.model``：
    空值 = 「跟随部署默认」，
    运行期走原有的注册表默认行回落，不算不可用。

    ``capabilities.rerank_models`` 为空 = 本部署没有重排能力 —— 那是
    :func:`uses_external_model_reranker_without_endpoint` 的判据（报另一条文案），
    这里返回空，免得同一张画布弹出两条同因警告。

    比对不区分大小写，与 :func:`find_unavailable_models` 同口径。
    """
    available = {name.strip().lower() for name in capabilities.rerank_models if name}
    if not available:
        return []
    missing: set[str] = set()
    for operator in canvas_util.iter_operators(canvas.node_config_dto_list):
        operator_name = operator.get('operator')
        if ('' if operator_name is None else str(operator_name)) not in RERANK_OPERATOR_NAMES:
            continue
        kwargs = operator.get(KEY_KWARGS)
        if not isinstance(kwargs, dict):
            continue
        declared = kwargs.get(KEY_MODEL)
        if not isinstance(declared, str) or not declared.strip():
            continue
        if declared.strip().lower() not in available:
            missing.add(declared.strip())
    return sorted(missing)


def find_unavailable_embedding_models(canvas: FlowCanvasInput,
                                      capabilities: RuntimeCapabilities) -> list[str]:
    """画布检索器声明了、但本部署解析不到的向量模型名（去重、稳定排序）。

    只检查算子的 ``kwargs.embedding``：空值 = 跟随部署默认（运行期取注册表默认行），
    不算不可用。

    ``capabilities.embedding_models`` 为空 = **无法判定**（注册表读不到），一律放行 ——
    与 :func:`find_unavailable_models` 同一条安全阀，不能把「查不到」当成「都没有」。

    比对不区分大小写。命中注册表行时运行时打该行自己的端点；没命中则回落 ``.env``
    端点并在请求体里带**画布写的名字**，所以那个名字是否可用取决于 ``.env`` 配的模型 ——
    清单由 ``model.resolver.embedding_model_names`` 按同一套语义算出。
    """
    available = {name.strip().lower() for name in capabilities.embedding_models if name}
    if not available:
        return []
    missing: set[str] = set()
    for operator in canvas_util.iter_operators(canvas.node_config_dto_list):
        kwargs = operator.get(KEY_KWARGS)
        if not isinstance(kwargs, dict):
            continue
        declared = kwargs.get(KEY_EMBEDDING)
        if not isinstance(declared, str) or not declared.strip():
            continue
        if declared.strip().lower() not in available:
            missing.add(declared.strip())
    return sorted(missing)


def find_embedding_dimension_mismatches(canvas: FlowCanvasInput,
                                        capabilities: RuntimeCapabilities,
                                        kbase_dimensions: Optional[dict] = None) -> list[str]:
    """检索器选的向量模型与绑定知识库的**物理向量表维度**对不上（稳定排序）。

    名字能解析（:func:`find_unavailable_embedding_models` 放行）**不代表能用**：
    维度不同时查询向量写不进/比不动，结果是空命中或运行期报错 ——
    图谱检索 502 就是这条链的下游。

    ``kbase_dimensions`` 是 ``{画布基名: 物理维度}``（由 FlowService 从 ``vector(N)``
    读出来）。**任何一侧为空都放行**：拿不到维度 = 无法判定，与探测那条安全阀同一原则。
    维度来自同一张表的 ``vector(N)``，所以不会因为“模型名对但注册表维度没填”而误判。
    """
    dimensions = {name: int(value) for name, value in (kbase_dimensions or {}).items() if value}
    if not dimensions:
        return []
    model_dimensions = capabilities.embedding_dimensions or {}
    if not model_dimensions:
        return []
    bound = canvas_util.collect_bound_kbase_names(canvas.node_config_dto_list)
    if not bound:
        return []

    mismatches: set[str] = set()
    for operator in canvas_util.iter_operators(canvas.node_config_dto_list):
        kwargs = operator.get(KEY_KWARGS)
        if not isinstance(kwargs, dict):
            continue
        declared = kwargs.get(KEY_EMBEDDING)
        if not isinstance(declared, str) or not declared.strip():
            continue
        model = declared.strip()
        model_dimension = model_dimensions.get(model.lower())
        if not model_dimension:
            continue
        for name in bound:
            kbase_dimension = dimensions.get(name)
            if kbase_dimension and kbase_dimension != int(model_dimension):
                mismatches.add(
                    f'{name} (kbase={kbase_dimension}d, model={model} {int(model_dimension)}d)')
    return sorted(mismatches)


def find_reasoning_model_in_query_rewriter(canvas: FlowCanvasInput,
                                           capabilities: RuntimeCapabilities) -> str | None:
    """找出问题重构（``LLMQueryRewriter``）里用到的推理模型名，没有则返回 None。

    比较不区分大小写。
    """
    reasoning_models = capabilities.reasoning_models
    if not reasoning_models:
        return None
    lowered = {model.lower() for model in reasoning_models}
    for operator in canvas_util.iter_operators(canvas.node_config_dto_list):
        operator_name = operator.get('operator')
        if OPERATOR_LLM_QUERY_REWRITER != ('' if operator_name is None else str(operator_name)):
            continue
        kwargs = operator.get(KEY_KWARGS)
        if not isinstance(kwargs, dict):
            continue
        llm = kwargs.get(KEY_LLM)
        if not isinstance(llm, str) or not llm:
            continue
        if llm.lower() in lowered:
            return llm
    return None


def find_unavailable_models(canvas: FlowCanvasInput,
                            capabilities: RuntimeCapabilities) -> list[str]:
    """画布各算子声明了、但生成端点那儿没有的模型名（去重、稳定排序）。

    **只在探测成功时才有判据**：``capabilities.available_models`` 为空表示「无法判定」
    （没探测、探测失败、或没配端点），此时一律返回空 —— **不能把「无法判定」当成
    「所有模型都不可用」**，否则生成端点抖一下就把用户挡在发布之外。
    取舍见 :mod:`model.probe`。

    比对**不区分大小写**（与上游 ``equalsIgnoreCase`` 及本模块其它模型比对一致）。
    另外容忍 provider 前缀：网关报 ``deepseek/deepseek-chat`` 而画布写
    ``deepseek-chat``（或反之）时算同一个 —— 宁可漏报，不误报。

    注册表里有两种名字不能按「画布写的那个名字」判：

    * **自带端点的注册模型**（``self_hosted_models``）：运行时打它自己的 ``base_url``，
      探测只探部署生成端点 —— 没有判据，直接放行（否则候选端点永远发不出去）。
    * **注册名 ≠ api_model**（``llm_api_models``）：请求体发的是 api_model，
      按它比对才和运行时一致。
    """
    available = capabilities.available_models
    if not available:
        return []

    normalized = {_normalize_model_name(m) for m in available}
    missing: set[str] = set()
    for operator in canvas_util.iter_operators(canvas.node_config_dto_list):
        kwargs = operator.get(KEY_KWARGS)
        if not isinstance(kwargs, dict):
            continue
        declared = kwargs.get(KEY_LLM)
        if not isinstance(declared, str) or not declared.strip():
            continue
        name = declared.strip()
        key = name.lower()
        if key in capabilities.self_hosted_models:
            continue
        effective = capabilities.llm_api_models.get(key, name)
        if _normalize_model_name(effective) not in normalized:
            missing.add(name)
    return sorted(missing)


def _normalize_model_name(name: str) -> str:
    """小写 + 去掉 provider 前缀（``a/b/c`` → ``c``）。

    只用于**比对**，不回写画布 —— 用户填什么名字，运行时就用什么名字。
    """
    text = (name or '').strip().lower()
    if '/' in text:
        text = text.rsplit('/', 1)[1]
    return text


def find_empty_stages(canvas: FlowCanvasInput) -> list[str]:
    """找出「一个算子都没配」的环节（只告警不拦：运行时会跳过该环节）。"""
    empty: list[str] = []
    for node in canvas_util.node_list(canvas.node_config_dto_list):
        variables = node.get('variables')
        if not isinstance(variables, dict):
            continue
        for stage_key in canvas_util.STAGE_KEYS:
            stage = variables.get(stage_key)
            if isinstance(stage, list) and not stage:
                empty.append(stage_key)
    return empty


def check_runnable(canvas: FlowCanvasInput, capabilities: RuntimeCapabilities,
                   kbase_dimensions: Optional[dict] = None) -> None:
    """可运行性校验：发布时的硬门槛（保存时只作为警告）。"""
    engine = canvas_util.find_engine_operator(canvas.other_node_config_list)
    if engine not in canvas_util.ENGINE_OPERATORS:
        raise FlowError('engine.unsupported', '' if engine is None else engine,
                        supported_engines())
    unrunnable = find_unrunnable_operators(canvas)
    if unrunnable:
        raise FlowError('operator.unsupported', ', '.join(unrunnable))
    if uses_external_model_reranker_without_endpoint(canvas, capabilities):
        raise FlowError('rerank.endpoint.missing', OPERATOR_LLM_RERANKER)
    unavailable_rerank = find_unavailable_rerank_models(canvas, capabilities)
    if unavailable_rerank:
        raise FlowError('rerank.model.unavailable', ', '.join(unavailable_rerank))
    unavailable_embedding = find_unavailable_embedding_models(canvas, capabilities)
    if unavailable_embedding:
        raise FlowError('embedding.model.unavailable', ', '.join(unavailable_embedding))
    dimension_mismatches = find_embedding_dimension_mismatches(
        canvas, capabilities, kbase_dimensions)
    if dimension_mismatches:
        raise FlowError('embedding.dimension.mismatch', '; '.join(dimension_mismatches))
    unavailable = find_unavailable_models(canvas, capabilities)
    if unavailable:
        raise FlowError('model.unavailable', ', '.join(unavailable))


def precheck_warnings(canvas: FlowCanvasInput, language: str,
                      capabilities: RuntimeCapabilities,
                      kbase_dimensions: Optional[dict] = None) -> list[str]:
    """preCheck 的运行期风险清单（**已翻译**的整句，按固定合并顺序）。

    顺序固定为：引擎 → 算子 → rerank 端点 → 空环节 → 推理模型。
    前端不看顺序，但保持顺序能让两边的日志逐行对得上。
    """
    warnings: list[str] = []
    engine = canvas_util.find_engine_operator(canvas.other_node_config_list)
    if engine not in canvas_util.ENGINE_OPERATORS:
        warnings.append(render('engine.unsupported', language,
                               '' if engine is None else engine, supported_engines()))
    unrunnable = find_unrunnable_operators(canvas)
    if unrunnable:
        warnings.append(render('operator.unsupported', language, ', '.join(unrunnable)))
    if uses_external_model_reranker_without_endpoint(canvas, capabilities):
        warnings.append(render('rerank.endpoint.missing', language, OPERATOR_LLM_RERANKER))
    empty_stages = find_empty_stages(canvas)
    if empty_stages:
        warnings.append(render('empty.stage', language, ', '.join(empty_stages)))
    reasoning_model = find_reasoning_model_in_query_rewriter(canvas, capabilities)
    if reasoning_model is not None:
        warnings.append(render('reasoning.model.recommend', language, reasoning_model))
    # 第 6 条只在本服务的 workflow 端点上生效（见 frontend/nginx.conf 的
    # /api/co-knowledge/v1/workflows），没有生成端点配置可探。前 5 条顺序固定；本条殿后，
    # 顺序断言见 tests/test_flow_api_canvas.py。
    unavailable = find_unavailable_models(canvas, capabilities)
    if unavailable:
        warnings.append(render('model.unavailable', language, ', '.join(unavailable)))
    # 新增项同样殿后（前 5 条的顺序保持不变）
    unavailable_rerank = find_unavailable_rerank_models(canvas, capabilities)
    if unavailable_rerank:
        warnings.append(render('rerank.model.unavailable', language,
                               ', '.join(unavailable_rerank)))
    # 向量模型：名字写错时运行期会回落 .env，而 .env 的端点不一定服务它 ——
    # 图谱检索 502 就是这条。发布门槛同样硬拒（见 check_runnable）。
    unavailable_embedding = find_unavailable_embedding_models(canvas, capabilities)
    if unavailable_embedding:
        warnings.append(render('embedding.model.unavailable', language,
                               ', '.join(unavailable_embedding)))
    # 维度不一致：名字能解析、库也能查，但两边维度对不上 —— 检索结果必然为空。
    dimension_mismatches = find_embedding_dimension_mismatches(
        canvas, capabilities, kbase_dimensions)
    if dimension_mismatches:
        warnings.append(render('embedding.dimension.mismatch', language,
                               '; '.join(dimension_mismatches)))
    return warnings


def join_warnings(warnings: list[str]) -> str:
    """多条警告合并成一句话（前端 `res.message` 直接弹这个字符串）。"""
    return MESSAGE_SEPARATOR.join(warnings)


def safe_file_name(app_id: Any) -> str:
    """导出文件名清洗：只留 ASCII 安全字符。

    前端 ``download()`` 会把没有 charset 的文件名再过一次 ``decodeURIComponent()``，
    出现 ``%`` 会直接抛错；同时这也能挡住把 ``"``、CR/LF 这类字符塞进响应头
    （header 注入）。
    """
    raw = '' if app_id is None else str(app_id)
    sanitized = ''.join(ch if (ch.isascii() and (ch.isalnum() or ch in '._-')) else '_' for ch in raw)
    if not sanitized.strip():
        sanitized = 'rag_workflow'
    return sanitized[:100] + '.json'
