import os

from requests import Response

from shared.errors.exception import EMException
from model.llm_proxy_client import LlmProxyClient
from infrastructure.logging.logutil import log
from infrastructure.http.client import build_headers, check_status_code

llm_proxy_client = LlmProxyClient()


def get_embedding_info(user_request: str, model: str, request_headers):
    try:
        input_data = [user_request] if os.environ.get('DEPLOY_SCENE') == 'esm' else user_request
        # ``model=`` 同时决定**端点**与请求体里的模型名。漏传时 resolver 会取默认
        # embedding 行（模型管理页可改），于是「用 A 模型的名字打 B 模型的端点」——
        # 网关回 404 ``The model ... does not exist``，图谱检索整条 502。
        response: Response = llm_proxy_client.embeddings(body={'input': input_data, 'model': model},
                                                         headers=build_headers(request_headers),
                                                         model=model)
        check_status_code(response.status_code, 'model-adapter')
        embedding_data = response.json().get('data')
        return embedding_data[0].get('embedding')
    except EMException as e:
        log.warning(e)
        raise e
    except Exception as e:
        log.warning(e)
        raise EMException(err_code='request-embedding-failed')


def get_embedding_dimension(model_name: str):
    """探测某 embedding 模型的向量维度（打一次 ``input=['hello']``）。

    **失败显式报错**：不能回落硬编码 ``1792`` —— 那个数字来自
    ``stella-large-zh-v3-1792d``（在本部署里**一个向量表都没有**，见
    ``document2seed/kb_query_service.py`` 的注释）。否则端点不可达 / 模型名打错 /
    没配 key，都会被登记成一个**看起来像真的**维度，然后建表、写入、检索一路错下去，
    错因却指向别处。维度是校验基准，猜一个数就是静默用错维度 —— 契约明确禁止。

    调用方 ``POST /models/setting`` 会把它翻成一个明确的错误响应，而不是 200 + 假维度。
    """
    try:
        # 同 ``get_embedding_info``：端点必须跟随被测量的模型，而不是默认行。
        response: Response = llm_proxy_client.embeddings(
            body={'input': ['hello'], 'model': model_name}, model=model_name)
        embedding_data = response.json().get('data')
        dimension = len(embedding_data[0].get('embedding'))
    except Exception as e:
        log.warning('could not determine embedding dimension for %s: %s', model_name, e)
        raise EMException(err_code='request-embedding-failed')
    if not dimension:
        raise EMException(err_code='request-embedding-failed')
    return dimension


def query_llm_service_list(request_headers, service_name: str = None):
    return _query_service_list(request_headers, service_name, 'v2/query', 'document2seed-model-query-failed')


def query_embedding_service_list(request_headers, service_name: str = None):
    return _query_service_list(request_headers, service_name, 'v2/embeddings/query',
                               'document2seed-embedding-query-failed')


def _query_service_list(request_headers, service_name: str, url: str, err_code: str):
    try:
        body = _build_query_body(request_headers, service_name)
        response: Response = _call_modeladapter_query(url, body, request_headers)
        check_status_code(response.status_code, 'model-adapter')
        response_json = response.json() or {}
        if response_json.get('code') != 10001:
            raise EMException(err_code, response_json.get('message', ''))
        return response_json.get('result') or []
    except EMException:
        raise
    except Exception as e:
        log.warning(e)
        raise EMException(err_code, str(e))


def _build_query_body(request_headers, service_name: str):
    body = {}
    if service_name:
        body['service_name'] = service_name
    username = getattr(request_headers, 'username', None)
    tenant_id = getattr(request_headers, 'tenant_id', None)
    if username:
        body['userName'] = username
    if tenant_id:
        body['tenantId'] = tenant_id
    return body


def _call_modeladapter_query(url: str, body: dict, request_headers) -> Response:
    """模型目录查询。

    `LlmProxyClient` 的两个方法一定存在（它们从 `.env` 合成，见
    `llm_proxy_client.py`），不需要回落分支。

    :param url: `'v2/query'`（LLM 目录）或 `'v2/embeddings/query'`（embedding 目录）——
        保留这个参数是为了让调用点的形状不变
    """
    if url == 'v2/embeddings/query':
        return llm_proxy_client.query_embedding_services(body=body, headers=build_headers(request_headers))
    return llm_proxy_client.query_llm_services(body=body, headers=build_headers(request_headers))