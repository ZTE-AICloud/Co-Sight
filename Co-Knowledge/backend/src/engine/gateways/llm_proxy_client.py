"""模型侧网关。

提供三件事：

  * 生成 → OpenAI 兼容端点（compose 里是 model-gateway，由 .env 指到真实端点）
  * 重排 → 模型注册表 / 部署配置（默认没有）
  * 可用模型列表 → 配置（`GENERATION_MODEL`）

保留同名函数是为了让 vendored 的算子（`check_exec_result` / `invoke_rerank_client` /
`query_rerank_model`）一行都不用改。
"""
from infrastructure.http import egress
from engine.common.exception.rag_exception import RagException
from engine.settings import Config
from engine.logutil import logger

BGE_RERANKER_LARGE = 'bge-reranker-large'


def check_exec_result(result):
    """只有 `code == '-1'` 才算失败。

    OpenAI 兼容响应里没有 `code` 字段，所以这里对生成调用是 no-op —— 生成侧的
    失败判定在 `openai_llm._extract_content()` 里（空内容会显式抛错）。
    """
    if str((result or {}).get('code', '')) == '-1':
        raise RagException(-1, 'request-llm-gateway-failed')


def query_rerank_model(username: str) -> str:
    """可用的重排模型名。

    来源是模型注册表 / 部署级配置 `Config['rerank_model']`（环境变量 RERANK_MODEL，
    默认 ''）：

      * 未配（默认）→ 常量 `BGE_RERANKER_LARGE`；
      * 配了 → 请求体里的 `model` 用它。重排端点若校验模型名（Cohere/Jina 系）必须配。

    参数 `username` 保留只是不动 vendored 调用点（`external_model_reranker._invoke_rerank`
    传的是 `escape(headers.username)`），本函数并不使用它。
    """
    from engine.gateways import model_bridge

    # 注册表里的默认重排模型优先，然后才是部署级配置，最后回落常量
    return model_bridge.rerank_model_name() or Config.get('rerank_model', '') or BGE_RERANKER_LARGE


def invoke_rerank_client(model: str, question: str, knowledge_infos: list, score: int,
                         strict_model: bool = False):
    """调重排端点。

    两种失败刻意分开处理：
      * **压根没配端点**（注册表里没有启用的重排模型，且 `RERANK_URL` 为空）→ 抛错。
        这是部署配置缺失，不是临时抖动，退化成「按原顺序返回」会让用户以为重排生效了。
        发布环节也会拦这种画布（阶段1）。
      * **配了但调用失败** → 记日志并退回原顺序（可用性优先）。

    端点来源是**模型注册表**（模型管理页可注册重排端点，回落 `RERANK_URL`）——
    「在管理页加一个重排端点」就能让画布上的 `ExternalModelReranker` 从「必被拒」
    变成「可发布、可运行」，不需要重建容器。

    ``strict_model``：画布上**显式选**了重排模型时为 ``True``。此时注册表里查不到
    这个名字就不能退到 ``.env`` 的默认模型 —— 那会「选了 A、实际跑 B」，且完全静默。
    调用方没显式选（走部署默认）时保持 ``False``，维持原有回落语义。

    另外：≤1 条候选不需要重排，直接返回。
    """
    if len(knowledge_infos) <= 1:
        return knowledge_infos

    from engine.gateways import model_bridge

    endpoint = model_bridge.resolve_rerank(model)
    if (strict_model and model and endpoint.origin == 'env'
            and (endpoint.api_model or '').strip().lower() != model.strip().lower()):
        logger.error('rerank model %r is not configured in the registry; the env endpoint '
                     'serves %r instead', model, endpoint.api_model)
        raise RagException(-2, 'rerank-model-not-configured', model)
    rerank_url = endpoint.url
    if not rerank_url:
        logger.error('rerank endpoint is not configured (no enabled rerank model in the '
                     'registry and RERANK_URL is empty) but workflow uses %s', model)
        raise RagException(-2, 'rerank-endpoint-not-configured')

    try:
        # 请求体里的 model 用**解析出来的**那个：算子里传的是画布上选的 name，
        # 而端点认的可能是另一个（注册表的 api_model），拿错名字会被端点 400/404
        body = {'model': endpoint.api_model or model, 'query': question,
                'documents': list(knowledge_infos)}
        response = egress.post(rerank_url, json=body, headers=endpoint.headers(), timeout=60)
        if response.status_code < 200 or response.status_code >= 300:
            raise RagException(-2, 'bad-status-code', 'rerank')
        entity = response.json()
        results = entity.get('results') or entity.get('data')
        if not isinstance(results, list):
            logger.warning('rerank response has no usable results, fallback to original order: %s',
                           str(entity)[:300])
            return knowledge_infos
        # 只保留得分高于阈值的候选，按重排后的顺序返回
        selected = [(item.get('index'), item.get('relevance_score')) for item in results]
        selected = [(idx, s) for idx, s in selected if idx is not None and s is not None and s > score]
        selected.sort(key=lambda pair: pair[1], reverse=True)
        if not selected:
            logger.warning('rerank filtered out every candidate (threshold=%s), keep original order', score)
            return knowledge_infos
        return [knowledge_infos[idx] for idx, _ in selected if 0 <= idx < len(knowledge_infos)]
    except RagException:
        raise
    except Exception as e:
        logger.warning('rerank failed, reason is {}'.format(str(e)))
        logger.exception(e)
        return knowledge_infos


def invoke_query_llm_info():
    """本部署默认可用的生成模型名（模型注册表优先，回落部署配置）。"""
    from engine.gateways import model_bridge

    model = model_bridge.default_llm_model() or Config.get('generation_model', '')
    if not model:
        raise RagException(-1, 'no-llm-available')
    return model
