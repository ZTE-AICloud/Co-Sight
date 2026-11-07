"""少数纯本地的兼容端点（asset / dataset* / zaetask / code-kbase / qa / user / permission）。

其中只有这几条返回 0000：

======================  ==================================================
``GET /zaetask/getMetrics``       评测指标下拉框 —— **纯静态枚举** + i18n 标签
``GET /zaetask/getDatasetSize``   评测集大小限制 —— application.yml 里的两个常量
``GET /dataset/file/health``      探测外部的 dataset-manager（没有对端 → 恒 ``error``）
======================  ==================================================

其余端点继续回兜底的 ``0005 + msg=null``。
"""

from __future__ import annotations

import os
from typing import Optional

from shared.errors.api import KbApiError
from shared.i18n.messages import render
from infrastructure.logging.logutil import log

# **顺序就是前端下拉框的渲染顺序**。标签把 value 当 i18n 键；
# 只有 zh 有译文，其余语言**回落成键名本身**（``faithfulness`` 这种原值），
# 所以这里直接用 render（找不到就回键名）。
METRIC_VALUES = (
    'faithfulness',
    'answer_relevancy',
    'answer_similarity',
    'answer_correctness',
    'context_precision',
    'context_recall',
    'answer_recall',
    'answer_precision',
)

# ``evaluation.size.file`` / ``evaluation.size.flow``（application.yml，没有 env 覆盖）
DATASET_SIZE_FILE = 100
DATASET_SIZE_FLOW = 100


def metrics(language: str) -> list[dict]:
    """``GET /zaetask/getMetrics``：``[{desc, label, value}, ...]``（键序固定）。"""
    return [{'desc': None, 'label': render(value, language), 'value': value}
            for value in METRIC_VALUES]


def dataset_size() -> dict:
    """``GET /zaetask/getDatasetSize``：``{file, flow, kbase}``，各带 ``{max, min}``。

    ⚠️ ``kbase`` 与 ``flow`` **取值恒等**；键序是 ``file, flow, kbase``。
    """
    return {
        'file': {'max': DATASET_SIZE_FILE, 'min': 1},
        'flow': {'max': DATASET_SIZE_FLOW, 'min': 1},
        'kbase': {'max': DATASET_SIZE_FLOW, 'min': 1},
    }


def dataset_manager_health() -> str:
    """``GET /dataset/file/health``：``normal`` / ``error``。

    默认恒 ``error``（前端据此把数据集相关入口置灰）。
    要用真探活时设 ``DATASET_MANAGER_URL``（形如 ``http://host:port/xxx``），
    探不通仍然是 ``error``。
    """
    base: Optional[str] = (os.environ.get('DATASET_MANAGER_URL') or '').strip()
    if not base:
        return 'error'
    try:
        import json
        import urllib.request

        payload = json.dumps({'pageNo': 1, 'pageSize': 1}).encode()
        request = urllib.request.Request(base.rstrip('/') + '/version/list', data=payload,
                                         method='POST',
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=5) as response:
            response.read()
        return 'normal'
    except Exception as error:                                     # noqa: BLE001
        log.warning('dataset-manager health check failed: %s', error)
        return 'error'


# ----------------------------------------------------------------------
# 固定失败响应
#
# 这几条端点固定返回失败，且**必须带对应的码与文案**：前端拿不到 msg
# 就弹通用的「网络异常，请稍后重试」。
# ----------------------------------------------------------------------


def llm_list() -> list[dict]:
    """``GET /zaetask/getLlmList`` → 0000 + ``[{value, label}, ...]``。

    「创建知识图谱」与「分块优化」页的「大模型」**必填下拉**唯一数据源就是这条，
    清单恒空 = 构建按钮永远不可用（页面死路）。数据来自模型单一来源：
    ``model_registry`` 表（模型管理页可增删），``.env`` 负责播种与回落 ——
    取法见 ``runtime_config.capabilities()``，拿到的是同一份 ``llm_models``。

    格式对齐前端消费（两个页面都吃 ``{value, label}``；画布的 ``modelValue/nameZh``
    是另一套字段，别混）。后端 ``_validate_llm`` 对取不到的清单一律放行，无校验分叉。
    """
    # 延迟 import：与 flow_api/service.py 里 kb_api 的延迟 import 同一约定 ——
    # 两个接口族不在导入期互相牵连（模块级 import 会把整个 flow_api 拖进 kb_api 的
    # import 图，flow_api 里那些反向的延迟 kb_api import 一旦被"清理"成模块级就环了）
    from workflow import runtime_config

    models = runtime_config.capabilities().llm_models
    return [{'value': name, 'label': display} for name, display in models]


def embedding_list() -> list[dict]:
    """``GET /zaetask/getEmbeddingList`` → 0000 + ``[{value, label}, ...]``。

    清单直接来自可增删的 embedding 模型注册表；取法与 ``/embedding/all``
    **同一个函数**，别在这里另起一套口径。

    **仓内没有任何组件在用它**：前端只有一个 api 包装层
    （``frontend/src/api/knowledgeBase.js`` 的 ``getEmbeddingOptionsApi``），
    建库/建图谱那几个下拉走的是 ``/embedding/all``。保留该端点是为了让那层包装可用。

    字段口径与 ``getLlmList`` **一致**（``{value, label}``），别在这里另起一套。
    """
    # 清单**不在** RuntimeCapabilities 里（那是画布校验用的能力快照，只有
    # llm / reasoning / rerank 三样），所以这里直接问解析层
    from knowledge_base.service.kbase_service import list_embedding_model_names

    return [{'value': name, 'label': name} for name in list_embedding_model_names()]


def rerank_list() -> list[dict]:
    """``GET /system/rerank-models`` → ``[{value, label, isDefault}, ...]``。

    画布 ``ExternalModelReranker`` 的「重排模型」下拉用这一条。数据源与运行期解析
    **完全同源**（``model_registry`` 的 rerank 行，读不到回落 ``RERANK_URL`` /
    ``RERANK_MODEL``）—— 下拉里能选的，就是运行期真的能用的。

    ``isDefault`` 让前端能把「跟随部署默认」渲染成具体模型名；没有默认行时
    解析层会挑第一条启用行（与 :func:`core.gateway.model_resolver._pick` 同义）。
    """
    from model import resolver as model_resolver

    return model_resolver.rerank_model_options()


def workflow_list() -> None:
    """``GET /zaetask/getWorkflowList`` → 0005「获取知识检索列表失败」。"""
    raise KbApiError('RetCode.zae.get.workflow.fail')


def query_task_list() -> None:
    """``GET /zaetask/queryTaskList`` → 0005 **无文案**（``msg=null``）。"""
    raise KbApiError(None)
