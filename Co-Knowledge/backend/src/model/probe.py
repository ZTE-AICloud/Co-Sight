"""生成端点「有哪些模型真的可用」的探测（``GET {GENERATION_GATEWAY_URL}{MODELS_PATH}``）。

**为什么需要**：画布「大模型」下拉来自 ``deploy/.env`` 的 ``GENERATION_MODELS``（部署属性），
而模型真正能不能跑由生成端点决定。两者漂移时用户的体验是「画布选完、发布成功、跑起来
才发现模型不存在」。探测把这条错误提前到 preCheck / publish。

**与 :mod:`workflow.kbase_provider` 相反：探测失败不抛错，返回 ``None``。**

那条链路（知识库下拉）失败必须显式抛 —— 静默返回空会让下拉变空，看起来像「一个库都没建」。
这条恰恰相反，理由是**两种判错的代价不对称**：

* 探测是**尽力而为**的。并非所有 OpenAI 兼容实现都提供 ``/models``（端点版本千差万别），
  端点也可能只是抖了一下、或这个部署没配 ``GENERATION_API_KEY``。这些都不足以断定
  「模型不可用」。
* 探测结果接的是 **publish 的硬门槛**（``validation.check_runnable``）。误判的代价是
  **把用户挡在发布之外**，比漏判严重得多。

所以约定：拿到清单 → 返回 ``frozenset``；**任何失败 → 返回 ``None``（判据一律放行）**。

**路径可配**（``GENERATION_MODELS_PATH``），因为两种实现路径不同：

===================================  ==========================  ================================
实现                                  真实路径                    说明
===================================  ==========================  ================================
LiteLLM 代理（本部署的生成端点）        ``{base}/models``           base 自带 ``/v1``
Infinity（compose 里的 embedding 容器）  ``/models``                **base 不带 ``/v1``**，``/v1/models`` → 404
===================================  ==========================  ================================

这与 ``contracts/model-gateway.md`` 已记录的 ``/embeddings`` vs ``/v1/embeddings`` 是同一个坑。

**带 TTL 的惰性缓存**：preCheck 是用户点保存时的**同步**请求，每次都实时打会让端点抖动时
每次保存都卡满超时；而缓存太旧又会漏掉新上线的模型。取 60 秒（默认值，见
:data:`CACHE_TTL_SECONDS`）：同一次保存流程内不重复打，端点恢复后最多一分钟重新可见。
**探测失败不写缓存** —— 否则一次抖动会持续一分钟。
"""

from __future__ import annotations

import os
import time
from typing import Callable, Optional

from infrastructure.http import egress
from infrastructure.logging.logutil import log

ENV_GATEWAY_URL = 'GENERATION_GATEWAY_URL'
ENV_API_KEY = 'GENERATION_API_KEY'
ENV_MODELS_PATH = 'GENERATION_MODELS_PATH'

#: ``resolve(..., operation=...)`` 的操作名（只在本模块用一次，抽出来免得写错）
_OP_MODELS = 'models'

DEFAULT_MODELS_PATH = '/models'
# 探测是 preCheck 同步路径上的一次附加调用，超时要短：宁可「无法判定」也不要拖慢保存弹窗
DEFAULT_TIMEOUT_SECONDS = 3.0
CACHE_TTL_SECONDS = 60.0


def probe_available_models(gateway_url: str,
                           api_key: Optional[str] = None,
                           models_path: str = DEFAULT_MODELS_PATH,
                           timeout: float = DEFAULT_TIMEOUT_SECONDS,
                           http_get: Optional[Callable] = None) -> Optional[frozenset[str]]:
    """打一次生成端点，返回它声明的模型名集合；**任何失败返回 ``None``**。

    :param gateway_url: 生成端点 base（含 ``/v1`` 之类的版本段，按实现而定）
    :param api_key: 非空时作为 ``Authorization: Bearer`` 发出。实测 LiteLLM 不带 key 会 401
    :param models_path: 拼在 base 后面的路径，允许不含前导 ``/``
    :param http_get: 注入的 HTTP 客户端，签名同 ``requests.get``（单测用）
    """
    base = (gateway_url or '').strip()
    if not base:
        # 没配端点不是「模型不可用」，是「本部署没有生成能力」—— 那由别的检查管（见契约）
        log.warning('model probe skipped: %s is empty', ENV_GATEWAY_URL)
        return None

    url = _join_url(base, models_path)
    headers = {}
    key = (api_key or '').strip()
    if key:
        headers['Authorization'] = f'Bearer {key}'

    http_get = http_get or egress.get
    try:
        response = http_get(url, headers=headers, timeout=timeout)
    except Exception as exc:  # 连接被拒 / DNS / 超时 / 被代理接走 —— 一律「无法判定」
        log.warning('model probe failed to reach %s: %s: %s', url, type(exc).__name__, exc)
        return None

    status = getattr(response, 'status_code', None)
    if status != 200:
        # 401 是常见且正常的（部署没配 key）；不算错误，只说明「无法判定」
        log.warning('model probe got HTTP %s from %s; treating model list as unknown', status, url)
        return None

    try:
        body = response.json()
    except ValueError as exc:
        # 被公司代理接走时会返回一页 HTML → 这里拿不到 JSON。症状是「探测永远无法判定」
        log.warning('model probe got non-JSON body from %s: %s', url, exc)
        return None

    models = _extract_model_ids(body)
    if models is None:
        log.warning('model probe got unexpected payload shape from %s: %s', url, str(body)[:200])
        return None

    log.info('model probe: %d model(s) available at %s: %s', len(models), url, sorted(models))
    return frozenset(models)


def _join_url(base: str, models_path: str) -> str:
    """拼 ``base`` 与 ``path``，两边各容一个 ``/``，不重复也不遗漏。"""
    path = (models_path or DEFAULT_MODELS_PATH).strip()
    if not path.startswith('/'):
        path = '/' + path
    return base.rstrip('/') + path


def _extract_model_ids(body) -> Optional[list[str]]:
    """从 OpenAI 兼容的 ``/models`` 响应里取模型名。

    标准形状是 ``{"data": [{"id": "..."}], "object": "list"}``；也容忍
    ``{"data": ["..."]}``（少数实现直接给字符串）。形状不符返回 ``None``。
    """
    if not isinstance(body, dict):
        return None
    data = body.get('data')
    if not isinstance(data, list):
        return None

    ids: list[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get('id')
        elif isinstance(item, str):
            model_id = item
        else:
            continue
        if isinstance(model_id, str) and model_id.strip():
            ids.append(model_id.strip())
    return ids


class ModelProbe:
    """带 TTL 缓存的探测器（RKB 进程内持一个实例）。

    :param gateway_url: 缺省取环境变量 ``GENERATION_GATEWAY_URL``
    :param api_key: 缺省取 ``GENERATION_API_KEY``
    :param models_path: 缺省取 ``GENERATION_MODELS_PATH``，再缺省用 :data:`DEFAULT_MODELS_PATH`
    :param ttl: 缓存有效期（秒）
    :param clock: 取当前时间的函数，单测用来跳过等待
    :param http_get: 注入的 HTTP 客户端，单测用
    """

    def __init__(self,
                 gateway_url: Optional[str] = None,
                 api_key: Optional[str] = None,
                 models_path: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 ttl: float = CACHE_TTL_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 http_get: Optional[Callable] = None,
                 env: Optional[dict] = None):
        source = os.environ if env is None else env
        self._gateway_url = gateway_url if gateway_url is not None else source.get(ENV_GATEWAY_URL, '')
        self._api_key = api_key if api_key is not None else source.get(ENV_API_KEY, '')
        self._models_path = models_path if models_path is not None else \
            (source.get(ENV_MODELS_PATH) or DEFAULT_MODELS_PATH)
        self._timeout = timeout
        self._ttl = ttl
        self._clock = clock
        self._http_get = http_get
        self._cached: Optional[frozenset[str]] = None
        self._cached_at: Optional[float] = None

    def _endpoint(self) -> tuple:
        """``(gateway_url, api_key, models_path)``。

        显式传了 URL（单测、以及将来要探非默认端点的地方）就用传进来的；
        否则**每次现问解析层** —— 生成端点可以由模型管理页改，
        固定成 import 期那份环境变量就等于「加了模型要重启才探测得到」。
        """
        if (self._gateway_url or '').strip():
            return self._gateway_url, self._api_key, self._models_path
        from model.resolver import resolve

        endpoint = resolve('llm', operation=_OP_MODELS)
        return (endpoint.base_url, endpoint.api_key,
                endpoint.path or self._models_path or DEFAULT_MODELS_PATH)

    def available(self) -> Optional[frozenset[str]]:
        """本部署可用的模型名集合；``None`` = 无法判定（调用方必须放行）。"""
        now = self._clock()
        if self._cached is not None and self._cached_at is not None and now - self._cached_at < self._ttl:
            return self._cached

        gateway_url, api_key, models_path = self._endpoint()
        probed = probe_available_models(gateway_url, api_key, models_path,
                                        self._timeout, self._http_get)
        if probed is None:
            # 失败不写缓存：否则一次抖动会持续一整个 TTL，明明恢复了还在放行/误判
            return None
        self._cached, self._cached_at = probed, now
        return probed

    def clear_cache(self) -> None:
        """丢弃缓存（单测与配置变更后使用）。"""
        self._cached, self._cached_at = None, None
