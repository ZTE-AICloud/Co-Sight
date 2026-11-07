"""模型端点的调用 —— 通过 **`.env` 寻址**。

## 寻址方式

embedding 端点用 `.env` 的 `MODEL_GATEWAY_URL`（远端）。所有走本模块的路径
（原生 `/knowledge_bases/retrieve`、图谱检索、向量写入、document2seed）共用这一组变量，
与 `model/gateway.py`（检索那条路）一致。

## 方法形状刻意保持不变

调用点分别是 `RemoteEmbedding` / `llmgateway_service` / `document2seed.llm_service`，
它们都按 `client.embeddings(body=..., headers=...)` 这样用。所以本模块**保持类名、
方法名与「返回一个 `requests.Response`」的契约**，只换内部实现 —— 调用点零改动。

## 那对 `query_*_services` 为什么是「合成的」

它们提供**模型目录查询**（`v2/query` / `v2/embeddings/query`）。「模型清单」只有
单一来源 —— **模型注册表**（模型管理页可增删，回落 `.env` 的 `GENERATION_MODELS`，
见 `core/gateway/model_resolver.py`）。
所以这里直接**从那份清单合成**同形状的响应，消费方（`document2seed` 的模型名校验）
拿到的语义不变、且真源更统一。

⚠️ 这两个方法返回的仍然是一个**真的 `requests.Response` 对象**（见 `_synthetic_response`），
不是 `dict` —— 消费方按 HTTP 客户端用它们，换形状会静默改掉调用点的错误分支。
"""

from __future__ import annotations

import json
import os

from requests import Response, models

from infrastructure.http import egress

DEFAULT_GATEWAY_URL = 'http://model-gateway:8000'
DEFAULT_EMBEDDINGS_PATH = '/embeddings'
DEFAULT_COMPLETIONS_PATH = '/chat/completions'
DEFAULT_TIMEOUT_SECONDS = 60


def _env(name: str, default: str = '') -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def embeddings_url(model_name: str | None = None) -> str:
    """embedding 端点。``model_name`` 给了就问注册表（模型管理页可注册自建端点）。"""
    from model.resolver import resolve

    return resolve('embedding', model_name, operation='embeddings').url


def completions_url(model_name: str | None = None) -> str:
    """生成端点。``model_name`` 给了就问注册表，否则用该类的默认模型。"""
    from model.resolver import resolve

    return resolve('llm', model_name, operation='chat').url


def _headers(headers, endpoint=None) -> dict:
    """合并鉴权头。``endpoint`` 是解析结果时用它的 key（每行可以有自己的 key）。"""
    merged = dict(headers or {})
    api_key = endpoint.api_key if endpoint is not None else _env('MODEL_GATEWAY_API_KEY')
    if api_key:
        merged.setdefault('Authorization', 'Bearer ' + api_key)
    return merged


def _llm_service_names() -> list:
    """生成模型清单 —— **与画布下拉、getLlmList 同源**（模型注册表，回落 ``.env``）。

    统一问 ``model_resolver``，与其余四个消费面吃到同一份数据，
    不要在这里另解析 ``GENERATION_MODELS``。
    """
    from model.resolver import llm_models

    return [name for name, _display in llm_models()]


def _embedding_service_names() -> list:
    """embedding 清单 —— 注册表优先，读不到时回落 ``.env``（两个变量同值，都收入）。"""
    from model.resolver import embedding_models

    names = embedding_models()
    if names:
        return names
    fallback = []
    for key in ('EMBEDDING_MODEL_NAME', 'EMBEDDING_MODEL'):
        value = _env(key)
        if value and value not in fallback:
            fallback.append(value)
    return fallback


def _synthetic_response(payload: dict) -> Response:
    """构造 `requests.Response` 替身。

    消费方只读 `.status_code` 与 `.json()`（`check_status_code` + `response.json().get(...)`），
    所以只要把这两处做对。用 `requests.models.Response` 本体而不是自定义类，
    是为了让 `check_status_code` / `raise_for_status` 这些既有调用照常工作。
    """
    response = models.Response()
    response.status_code = 200
    response.headers['Content-Type'] = 'application/json'
    # 与「查到目录」同形状：code 10001 + result[].service_name
    response._content = json.dumps(
        {'code': 10001,
         'result': [{'service_name': name} for name in payload.get('service_names') or []]},
        ensure_ascii=False).encode('utf-8')
    return response


class LlmProxyClient:
    """模型端点的薄客户端（方法形状与改造前一致，见模块文档）。

    ``model`` 关键字（可选）用来点名注册表里的某一个模型 —— 不传就是该类的默认模型，
    也就是改造前的行为。调用点**不必**传它，形状仍与改造前一致。
    """

    def embeddings(self, **kwargs) -> Response:
        from model.resolver import resolve

        endpoint = resolve('embedding', kwargs.get('model'), operation='embeddings')
        return egress.post(endpoint.url,
                             json=kwargs.get('body'),
                             headers=_headers(kwargs.get('headers'), endpoint),
                             timeout=kwargs.get('timeout') or DEFAULT_TIMEOUT_SECONDS)

    def completions(self, **kwargs) -> Response:
        """通用代理：body 完全由调用方给，本方法不合并每模型思考配置。

        仓内目前没有调用方（编排/Agent 各自构造并合并 overrides）。将来若接入，
        必须调用 ``model_resolver.effective_generation_overrides(endpoint)``
        再 merge 进 body，否则这里会成为唯一不生效的路径。
        """
        from model.resolver import resolve

        endpoint = resolve('llm', kwargs.get('model'), operation='chat')
        return egress.post(endpoint.url,
                             json=kwargs.get('body'),
                             headers=_headers(kwargs.get('headers'), endpoint),
                             timeout=kwargs.get('timeout') or DEFAULT_TIMEOUT_SECONDS)

    def query_llm_services(self, **kwargs) -> Response:
        return _synthetic_response({'service_names': _llm_service_names()})

    def query_embedding_services(self, **kwargs) -> Response:
        return _synthetic_response({'service_names': _embedding_service_names()})
