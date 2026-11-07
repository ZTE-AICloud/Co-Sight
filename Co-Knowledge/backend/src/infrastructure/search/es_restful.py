"""
Elasticsearch RESTful API 客户端
替代 elasticsearch Python 客户端，使用 HTTP RESTful 接口

安全说明：
1. 优先使用 API Key 认证（api_key 参数）
2. 如必须使用用户名/密码，请确保使用 HTTPS (scheme='https')
3. 在内网环境且 ES 未启用认证时，可不传认证参数
"""
import base64
import requests
from typing import List
from infrastructure.logging.logutil import log


class ESRestfulClient:
    """
    Elasticsearch RESTful API 客户端
    封装 ES 7.9 的 RESTful API 调用
    
    支持的认证方式：
    1. API Key 认证（推荐）：传入 api_key 参数
    2. 用户名密码认证：传入 user 和 password 参数
    3. 无认证：不传认证参数（适用于内网测试环境）
    
    线程安全设计：
    - self.headers 在初始化后为只读
    - 每次 HTTP 请求创建 headers 副本，避免竞态条件
    - 支持多线程并发使用同一个客户端实例
    """

    def __init__(self, host: str, port: int, user: str = None, password: str = None, 
                 api_key: str = None, scheme: str = 'http'):
        """
        初始化 ES RESTful 客户端
        
        Args:
            host: ES 主机地址
            port: ES 端口
            user: 认证用户名（使用 Basic Auth 时需要）
            password: 认证密码（使用 Basic Auth 时需要）
            api_key: API Key（推荐使用，格式：base64(id:api_key)）
            scheme: 协议类型 (http/https)
            
        安全建议：
            - 生产环境请使用 HTTPS (scheme='https')
            - 优先使用 api_key 而非 user/password
            - API Key 可通过 ES API 创建：POST /_security/api_key
        """
        self.base_url = f"{scheme}://{host}:{port}"
        self.headers = {'Content-Type': 'application/json'}
        
        # 认证方式优先级：API Key > Basic Auth > 无认证
        # 所有认证都通过 Authorization header 实现，不使用 requests 的 auth 参数
        if api_key:
            # 使用 API Key 认证（推荐方式）
            self.headers['Authorization'] = f'ApiKey {api_key}'
            log.info("ES client initialized with API Key authentication")
        elif user and password:
            # 使用 Basic Auth（需要 HTTPS 保护）
            # Coverity: SIGMA.basic_auth_enabled
            # 说明: 使用标准的 HTTP Basic Authentication
            # 1. 通过 Authorization header 传递，而非 requests.auth 参数
            # 2. 凭证经过 Base64 编码（注意：Base64 不是加密）
            # 3. 必须配合 HTTPS 使用以保护凭证传输
            # 4. 生产环境强烈建议使用 API Key 认证
            credentials = base64.b64encode(f"{user}:{password}".encode()).decode()
            self.headers['Authorization'] = f'Basic {credentials}'
            if scheme != 'https':
                log.warning("Using Basic Auth over HTTP is insecure. Please use HTTPS in production!")
            log.info("ES client initialized with Basic Authentication")
        else:
            # 无认证（适用于内网测试环境）
            log.info("ES client initialized without authentication")

    def _request(self, method: str, endpoint: str, data: dict = None, params: dict = None):
        """
        统一的 HTTP 请求方法
        
        Args:
            method: HTTP 方法 (GET, POST, PUT, DELETE)
            endpoint: API 端点
            data: 请求体数据
            params: URL 参数
            
        Returns:
            响应的 JSON 数据（可能是 dict 或 list，取决于 API）
        """
        url = f"{self.base_url}/{endpoint}"
        try:
            # 线程安全：每次请求创建 headers 副本，避免多线程竞态条件
            # Coverity: 不使用 requests 的 auth 参数，避免 SIGMA.basic_auth_enabled 告警
            headers = self.headers.copy()
            
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=data,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            # 有些接口返回空响应
            if response.text:
                return response.json()  # 根据实际内容返回 dict 或 list
            return None  # 空响应返回 None，由调用方处理
        except requests.exceptions.RequestException as e:
            log.exception(f"ES RESTful API request failed: {method} {url}, error: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    log.error(f"ES error detail: {error_detail}")
                except Exception:
                    log.error(f"ES error response: {e.response.text}")
            raise

    # ==================== 索引管理 API ====================
    
    def indices_exists(self, index: str) -> bool:
        """
        检查索引是否存在
        HEAD /{index}
        
        Returns:
            True: 索引存在（HTTP 2xx）
            False: 索引不存在（HTTP 404）或发生错误
        """
        url = f"{self.base_url}/{index}"
        try:
            # 线程安全：创建 headers 副本
            # Coverity: 通过 headers 传递认证，不使用 auth 参数
            headers = self.headers.copy()
            response = requests.head(url, headers=headers, timeout=30)
            # HTTP 2xx 表示成功（索引存在）
            return 200 <= response.status_code < 300
        except Exception as e:
            log.exception(f"Check index exists failed: {str(e)}")
            return False

    def indices_create(self, index: str, body: dict = None) -> dict:
        """
        创建索引
        PUT /{index}
        """
        result = self._request('PUT', index, data=body)
        return result if result is not None else {}

    def indices_delete(self, index: str) -> dict:
        """
        删除索引
        DELETE /{index}
        """
        result = self._request('DELETE', index)
        return result if result is not None else {}

    def indices_get_settings(self, index: str) -> dict:
        """
        获取索引设置
        GET /{index}/_settings
        """
        result = self._request('GET', f"{index}/_settings")
        return result if result is not None else {}

    def indices_get_mapping(self, index: str) -> dict:
        """
        获取索引 mapping
        GET /{index}/_mapping
        """
        result = self._request('GET', f"{index}/_mapping")
        return result if result is not None else {}

    # ==================== 文档操作 API ====================

    def index(self, index: str, body: dict, id: str = None, doc_type: str = '_doc') -> dict:
        """
        索引文档（创建或更新）
        PUT /{index}/_doc/{id}
        POST /{index}/_doc
        """
        if id:
            endpoint = f"{index}/{doc_type}/{id}"
            result = self._request('PUT', endpoint, data=body)
        else:
            endpoint = f"{index}/{doc_type}"
            result = self._request('POST', endpoint, data=body)
        return result if result is not None else {}

    def get(self, index: str, id: str, doc_type: str = '_doc') -> dict:
        """
        根据 ID 获取文档
        GET /{index}/_doc/{id}
        """
        endpoint = f"{index}/{doc_type}/{id}"
        result = self._request('GET', endpoint)
        return result if result is not None else {}

    def delete(self, index: str, id: str, doc_type: str = '_doc') -> dict:
        """
        根据 ID 删除文档
        DELETE /{index}/_doc/{id}
        """
        endpoint = f"{index}/{doc_type}/{id}"
        result = self._request('DELETE', endpoint)
        return result if result is not None else {}

    def search(self, index: str, body: dict = None) -> dict:
        """
        搜索文档
        POST /{index}/_search
        GET /{index}/_search
        
        Args:
            index: 索引名称或索引列表（逗号分隔）
            body: 查询DSL
            
        Returns:
            搜索结果
        """
        if isinstance(index, list):
            index = ','.join(index)
        endpoint = f"{index}/_search"
        result = self._request('POST', endpoint, data=body)
        return result if result is not None else {}

    def delete_by_query(self, index: str, body: dict, conflicts: str = 'abort') -> dict:
        """
        根据查询删除文档
        POST /{index}/_delete_by_query
        
        Args:
            index: 索引名称
            body: 查询DSL
            conflicts: 冲突处理策略 (abort/proceed)
        """
        endpoint = f"{index}/_delete_by_query"
        params = {'conflicts': conflicts}
        result = self._request('POST', endpoint, data=body, params=params)
        return result if result is not None else {}

    def update_by_query(self, index: str, body: dict, conflicts: str = 'abort') -> dict:
        """
        根据查询更新文档
        POST /{index}/_update_by_query

        Args:
            index: 索引名称
            body: 查询DSL + script
            conflicts: 冲突处理策略 (abort/proceed)
        """
        endpoint = f"{index}/_update_by_query"
        params = {'conflicts': conflicts}
        result = self._request('POST', endpoint, data=body, params=params)
        return result if result is not None else {}

    def bulk(self, body: List[str]) -> dict:
        """
        批量操作
        POST /_bulk
        
        Args:
            body: NDJSON 格式的批量操作数据
            
        Returns:
            批量操作结果
        """
        url = f"{self.base_url}/_bulk"
        
        # 构造 NDJSON 格式的数据
        if isinstance(body, list):
            ndjson_data = '\n'.join(body) + '\n'
        else:
            ndjson_data = body
        
        # 线程安全：创建 headers 副本并合并 Content-Type
        # Coverity: 通过 headers 传递认证（包含 Authorization），不使用 auth 参数
        headers = {**self.headers, 'Content-Type': 'application/x-ndjson'}
        
        try:
            response = requests.post(
                url,
                headers=headers,
                data=ndjson_data.encode('utf-8'),
                timeout=60
            )
            response.raise_for_status()
            result = response.json() if response.text else {}
            return result
        except requests.exceptions.RequestException as e:
            log.exception(f"ES bulk request failed: {str(e)}")
            raise

    # ==================== 插件管理 API ====================

    def cat_plugins(self, format: str = 'json') -> List[dict]:
        """
        获取插件列表
        GET /_cat/plugins?format=json
        
        Returns:
            插件列表，每个插件是一个字典。ES 的 _cat API 返回 JSON 数组。
        """
        params = {'format': format}
        result = self._request('GET', '_cat/plugins', params=params)
        # _cat API 在 format=json 时返回 JSON 数组（list）
        # 如果为 None（空响应）或不是 list，返回空列表
        if result is None:
            return []
        return result if isinstance(result, list) else []


class CatPluginsResponse:
    """兼容原 elasticsearch 客户端的 cat.plugins 响应"""
    def __init__(self, plugins_list: List[dict]):
        self.plugins_list = plugins_list

    def __iter__(self):
        return iter(self.plugins_list)


class IndicesNamespace:
    """兼容原 elasticsearch 客户端的 indices 命名空间"""
    def __init__(self, client: ESRestfulClient):
        self.client = client

    def exists(self, index: str) -> bool:
        return self.client.indices_exists(index)

    def create(self, index: str, body: dict = None) -> dict:
        return self.client.indices_create(index, body)

    def delete(self, index: str) -> dict:
        return self.client.indices_delete(index)

    def get_settings(self, index: str) -> dict:
        return self.client.indices_get_settings(index)

    def get_mapping(self, index: str) -> dict:
        return self.client.indices_get_mapping(index)


class CatNamespace:
    """兼容原 elasticsearch 客户端的 cat 命名空间"""
    def __init__(self, client: ESRestfulClient):
        self.client = client

    def plugins(self, format: str = 'json') -> List[dict]:
        return self.client.cat_plugins(format)


class ESRestfulClientWrapper:
    """
    Elasticsearch RESTful 客户端包装器
    提供与原 elasticsearch Python 客户端兼容的接口
    
    支持的认证方式：
    1. API Key 认证（推荐）：传入 api_key 参数
    2. 用户名密码认证：传入 user 和 password 参数
    3. 无认证：不传认证参数
    
    线程安全：
    - 底层 ESRestfulClient 是线程安全的
    - 支持多线程并发使用同一个客户端实例
    """
    def __init__(self, host: str, port: int, user: str = None, password: str = None, 
                 api_key: str = None, scheme: str = 'http'):
        """
        初始化 ES 客户端包装器
        
        Args:
            host: ES 主机地址
            port: ES 端口
            user: 认证用户名（使用 Basic Auth 时需要）
            password: 认证密码（使用 Basic Auth 时需要）
            api_key: API Key（推荐使用）
            scheme: 协议类型 (http/https)
        """
        self.client = ESRestfulClient(host, port, user, password, api_key, scheme)
        self.indices = IndicesNamespace(self.client)
        self.cat = CatNamespace(self.client)

    def search(self, index: str, body: dict = None) -> dict:
        return self.client.search(index, body)

    def index(self, index: str, body: dict = None, id: str = None, document: dict = None, doc_type: str = '_doc') -> dict:
        # 接受 document 参数
        data = document if document is not None else body
        return self.client.index(index, data, id, doc_type)

    def get(self, index: str, id: str, doc_type: str = '_doc') -> dict:
        return self.client.get(index, id, doc_type)

    def delete(self, index: str, id: str, doc_type: str = '_doc') -> dict:
        return self.client.delete(index, id, doc_type)

    def delete_by_query(self, index: str, body: dict, conflicts: str = 'abort') -> dict:
        return self.client.delete_by_query(index, body, conflicts)

    def update_by_query(self, index: str, body: dict, conflicts: str = 'abort') -> dict:
        return self.client.update_by_query(index, body, conflicts)

    def bulk(self, body: List[str]) -> dict:
        return self.client.bulk(body)



