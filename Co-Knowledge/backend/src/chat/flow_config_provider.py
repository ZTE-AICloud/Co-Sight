"""编排配置的来源。

画布存在后端的两张表：

  * `rag_flow_config`   —— 草稿（画布页面在编辑的那份）
  * `rag_flow_published` —— 发布快照（**运行时只读这份**）

所以这里按 scope 走两个端点：
  scope='dev'     → `GET /flow?appId=`（草稿，只给调试用）
  其它（默认）     → `GET /flow/published?appId=`（已发布快照）

拿到的画布 blob 交给 `translator.canvas_to_rag_config()` 翻成运行时配置。
"""
from typing import Dict, List

from pydantic import ValidationError

from chat.gateways import rkb_transport
from engine.common.exception.rag_exception import RagException
from engine.config.rag_config_bean import ConfigBean, RagConfig
from engine.logutil import logger
from chat.translator import canvas_to_rag_config

# 草稿只在调试时用；scope 取 'dev'
_DEV_SCOPE = 'dev'


def get_workflow_config(workflow_id: str, scope: str = '') -> Dict:
    """取某条工作流的运行时配置。取不到就**显式失败**，不返回空配置。

    返回空配置会让下游跑到「没有算子」的状态：检索为空、合成器无输入，
    最终给用户一个看似正常、其实什么都没查的回答。
    """
    try:
        response = rkb_transport.get_flow_config(workflow_id, scope)
    except Exception as e:
        logger.error('fetch workflow config failed: %s', str(e))
        raise RagException(-1, 'request-knowledgebase-failed')

    if response.status_code < 200 or response.status_code >= 300:
        logger.error('knowledge-base returned HTTP %s for workflow %s', response.status_code, workflow_id)
        # 404/409/5xx 在旧契约里都落进「已发布工作流不存在」这一个键，保持不改
        raise RagException(-1, 'published-workflow-not-found', workflow_id)

    try:
        payload = response.json()
    except ValueError:
        # HTTP 200 但正文不是 JSON：最常见的是请求其实打到了代理/网关（返回 HTML 错误页），
        # 不是合法 JSON。不在这里挡，JSONDecodeError 会一路冒到 app 层变成 "Unknown error"，
        # 排查时看不到任何线索（容器 no_proxy 没配好时就是这个现象）。
        logger.error('knowledge-base returned a non-JSON body (HTTP %s, content-type=%s): %s',
                     response.status_code, response.headers.get('Content-Type'), response.text[:200])
        raise RagException(-1, 'request-knowledgebase-failed')

    if not isinstance(payload, dict):
        logger.error('knowledge-base returned an unexpected JSON shape (%s): %s',
                     type(payload).__name__, str(payload)[:200])
        raise RagException(-1, 'request-knowledgebase-failed')

    canvas = payload
    config = canvas_to_rag_config(
        workflow_id,
        canvas.get('nodeConfigDTOList'),
        canvas.get('otherNodeConfigList'),
    )
    _validate_contract(workflow_id, config)
    _check_config(workflow_id, config)
    logger.info('workflow %s loaded from %s (version=%s), operators=%d',
                workflow_id, 'draft' if scope == _DEV_SCOPE else 'published',
                canvas.get('version'), _operator_count(config))
    return config


def _operator_count(config: Dict) -> int:
    return sum(len(config.get(key) or []) for key in
               ('pre-retriever', 'retriever', 'post-retriever', 'response-synthesizer'))


def _validate_contract(workflow_id: str, config: Dict) -> None:
    """按 `core/config/rag_config_bean.py` 的契约模型校验翻译结果。

    为什么值得单独一步：翻译是「画布 blob（外部输入）→ 运行时配置」的唯一入口，
    而下游（`RagContext` → 算子实例化）是 vendored 的领域代码，它默认配置形状是对的。
    形状错了要一路走到 `importlib`/`getattr` 才炸，报错点离原因很远；这里挡下来，
    错误里直接带上是哪个字段。

    校验失败**显式失败**，不降级：少一段算子就会得到「看起来正常、其实没检索」的回答。
    """
    try:
        parsed = RagConfig.model_validate(config)
    except ValidationError as e:
        # pydantic 的错误详情可能很长（每个字段一条），截断后再拼进消息里
        detail = '; '.join('%s: %s' % ('.'.join(str(loc) for loc in err['loc']), err['msg'])
                           for err in e.errors()[:5])
        logger.error('workflow %s config does not match the RagConfig contract: %s', workflow_id, detail)
        raise RagException(-1, 'workflow-config-invalid', workflow_id, detail)

    # 契约本身管不到的：别名/类型对、但值是空的。`package`/`operator` 为空串时，
    # 下游会在 `importlib.import_module('')` / `getattr(module, '')` 才炸，错误里没有任何线索。
    empty = _slots_with_empty_package_or_operator(parsed)
    if empty:
        logger.error('workflow %s has operators without package/operator: %s', workflow_id, empty)
        raise RagException(-1, 'workflow-config-invalid', workflow_id,
                           'empty package/operator at %s' % ', '.join(empty))


def _slots_with_empty_package_or_operator(parsed: RagConfig) -> List[str]:
    """列出 package/operator 为空的槽位（形如 `retriever[0]`）。

    `query_engine` 可能是未校验的默认值 `{}`（pydantic 不校验默认值），
    那种情况交给 `_check_config` 报「没有编排引擎」，这里只挑出**形状是算子**的项。
    """
    slots = [('query-engine', parsed.query_engine)]
    for stage in ('pre-retriever', 'retriever', 'post-retriever', 'response-synthesizer'):
        for index, operator in enumerate(getattr(parsed, stage.replace('-', '_'))):
            slots.append(('%s[%d]' % (stage, index), operator))
    return [name for name, operator in slots
            if isinstance(operator, ConfigBean) and (not operator.package or not operator.operator)]


def _check_config(workflow_id: str, config: Dict) -> None:
    """配置自检。这些都属于「继续跑下去只会得到空结果」的情况，直接失败。"""
    if not (config.get('query-engine') or {}).get('operator'):
        logger.error('workflow %s has no query engine after translation', workflow_id)
        raise RagException(-1, 'workflow-has-no-operator', workflow_id)
    if _operator_count(config) == 0:
        logger.error('workflow %s has no operator after translation', workflow_id)
        raise RagException(-1, 'workflow-has-no-operator', workflow_id)
