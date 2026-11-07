"""运行期端点解析：**模型名 + 类型 → 该打到哪个地址、用哪把 key、走哪条路径**。

这是「不停机新增模型」成立的**技术支点**。改造前每套调用栈各自读环境变量
（``GENERATION_GATEWAY_URL`` / ``MODEL_GATEWAY_URL`` / ``RERANK_URL``），
容器里那份环境变量在启动时就固定了 —— 新模型只能靠重建容器生效。现在：

* 注册表（``model_registry`` 表）是权威来源；
* 模型管理 API 与解析层**在同一个进程**里，写完直接 :func:`invalidate` 掉缓存 →
  下一次调用立刻用上新模型，不需要等 TTL、更不需要重启；
* 缓存只为兜住「同一请求里重复解析」与「库抖动」，不是正确性的依赖。

**回落语义（重要）**：解析顺序是「按名字命中 → 注册表默认行 → ``.env``」，
其中**只有 llm** 会走「默认行」这一步：UI 注册了生成模型、``.env`` 还留着占位名时，
用注册表默认行，避免打到一条死端点。embedding / rerank 名字对不上时**不借**别的行，
直接按名字回落 ``.env`` —— 静默换模型会让向量维度与库里的表对不上。
注册表里一条启用行都没有、或读库本身失败时，三类都回落到 ``.env``（改造前的行为），
保证「注册表为空 == 与改造前的输出字节级一致」，是升级不炸、回滚干净的前提
（见 ``tests/test_model_resolver.py`` 与 ``tests/test_model_embedding_resolution.py``）。

与 ``model/probe.py`` 的差异（那边的「失败不缓存」在这里**不适用**）：
探测接的是 publish 的硬门槛，一次抖动不该持续影响一分钟；而这里失败只是「回落 .env」，
本身就是安全态，缓存住反而避免每次调用都去撞一个坏掉的库。
"""

from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import dataclass
from typing import Optional

from infrastructure.logging.logutil import log
from model import env_capabilities

#: 缓存有效期（秒）。写路径会主动失效，所以这个值只影响跨进程/异常场景的收敛速度。
CACHE_TTL_SECONDS = 30.0

_OP_CHAT = 'chat'
_OP_EMBEDDINGS = 'embeddings'
_OP_MODELS = 'models'
_OP_RERANK = 'rerank'

_ENV_GENERATION_BASE = 'GENERATION_GATEWAY_URL'
_ENV_GENERATION_MODEL = 'GENERATION_MODEL'
_ENV_GENERATION_KEY = 'GENERATION_API_KEY'
_ENV_GENERATION_MODELS_PATH = 'GENERATION_MODELS_PATH'
_ENV_GENERATION_MAX_TOKENS = 'GENERATION_MAX_TOKENS'
_ENV_GENERATION_TEMPERATURE = 'GENERATION_TEMPERATURE'
_ENV_GENERATION_TIMEOUT = 'GENERATION_TIMEOUT'

_ENV_EMBEDDING_BASE = 'MODEL_GATEWAY_URL'
_ENV_EMBEDDING_PATH = 'MODEL_GATEWAY_EMBEDDINGS_PATH'
_ENV_EMBEDDING_KEY = 'MODEL_GATEWAY_API_KEY'
_ENV_EMBEDDING_MODEL = env_capabilities.ENV_EMBEDDING_MODEL
_ENV_EMBEDDING_DIMENSION = 'EMBEDDING_DIMENSION'
_ENV_EMBEDDING_MODEL_NAME = env_capabilities.ENV_EMBEDDING_MODEL_NAME

_ENV_RERANK_URL = 'RERANK_URL'
_ENV_RERANK_MODEL = 'RERANK_MODEL'

DEFAULT_GENERATION_BASE = 'http://model-gateway:8000/v1'
DEFAULT_GENERATION_MODEL = 'deepseek-chat'
DEFAULT_GENERATION_MAX_TOKENS = 2048
DEFAULT_GENERATION_TEMPERATURE = 0.01
DEFAULT_GENERATION_TIMEOUT = 120
DEFAULT_EMBEDDING_BASE = 'http://model-gateway:8000'
DEFAULT_EMBEDDING_PATH = '/embeddings'
DEFAULT_EMBEDDING_MODEL = 'BAAI/bge-base-zh-v1.5'
DEFAULT_EMBEDDING_DIMENSION = env_capabilities.DEFAULT_EMBEDDING_DIMENSION
DEFAULT_RERANK_MODEL = 'bge-reranker-large'

# 缓存：``records`` 为 None 表示「读不到」（回落 .env）。``loaded`` 区分「还没读过」。
_cache: dict = {'records': None, 'at': 0.0, 'loaded': False}


def _env(name: str, default: str = '') -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


@dataclass(frozen=True)
class ResolvedEndpoint:
    """一次调用的全部连接参数。

    ``url`` 是**可以直接 requests.post 的完整地址**（base + path 已拼好）——
    调用方不该再去理解 base/path 的区分，那是注册表内部的事。
    """

    kind: str
    model_name: str
    api_model: str
    url: str
    api_key: str = ''
    timeout: Optional[int] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    dimension: Optional[int] = None
    #: 每模型思考配置意图；``thinking_payload`` 是已解析的请求片段。
    thinking_mode: str = 'none'
    thinking_preset: str = ''
    thinking_payload: Optional[dict] = None
    #: ``url`` 的组成部分，单独留一份给**需要分开用**的调用方 —— 模型清单探测
    #: （``GET {base}{path}``）就是这类：它要的不是拼好的 URL 而是两段。
    #: 调用点用 ``url`` 就好，别自己拼。
    base_url: str = ''
    path: str = ''
    #: ``registry``（来自注册表）/ ``env``（回落）。
    #: **排障用的**：症状是「改了模型没生效」时，先看这里是不是 env。
    origin: str = 'env'
    #: 注册表行的来源（``env`` 播种 / ``user`` 管理页新增）；
    #: 回落时同样是 ``env``。抽图链路用它区分「注册表新增的端点」与
    #: 「``.env`` 播种、必须钉在原网关的模型」，见 ``graph_extract_api``。
    source: str = 'env'

    def headers(self) -> dict:
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        return headers


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------
def invalidate() -> None:
    """让下一次解析重新读注册表。**模型管理接口写完就调它**（同进程，立即生效）。"""
    _cache['at'] = 0.0
    _cache['loaded'] = False


def _make_store():
    """建注册表 store（延迟 import，单测环境不需要 psycopg2）。

    单独抽成函数是为了给单测一个**注入点**：替换它就能用内存 store 跑通
    「缓存 → 解析 → 回落」的完整路径，而不是把 ``_load_records`` 整个打桩
    （打桩会连缓存与回落逻辑一起跳过，等于没测）。
    """
    from model.repository_pg import PgModelStore

    return PgModelStore()


def _load_records() -> Optional[list]:
    """注册表全部行；读不到返回 ``None``（= 回落 .env 的信号，**不是**「一个模型都没有」）。

    ``None`` 与 ``[]`` 的区别是**刻意**的，与 ``model_probe`` 那条注释同一个道理：
    读库失败时若当成「注册表是空的」，行为与回落一致；但若当成「没有任何模型」，
    就会把用户的下拉清空 —— 而真实原因可能只是库抖了一下。
    """
    now = time.monotonic()
    if _cache['loaded'] and (now - _cache['at']) < CACHE_TTL_SECONDS:
        return _cache['records']
    try:
        records = _make_store().list_records()
    except Exception:
        log.warning('model registry unavailable; falling back to environment config',
                    exc_info=True)
        records = None
    _cache['records'] = records
    _cache['at'] = now
    _cache['loaded'] = True
    return records


def records(kind: Optional[str] = None) -> Optional[list]:
    """注册表里的行（按 kind 过滤）；读不到返回 ``None``。"""
    rows = _load_records()
    if rows is None:
        return None
    return [r for r in rows if kind is None or r.model_kind == kind]


def _pick(rows: list, model_name: Optional[str]):
    """选一条：给了名字就按名字（含 api_model 兜底），否则取默认，再否则第一条启用的。"""
    enabled = [r for r in rows if r.enabled]
    wanted = (model_name or '').strip()
    if wanted:
        for record in enabled:
            if record.model_name == wanted or record.effective_api_model() == wanted:
                return record
        return None
    for record in enabled:
        if record.is_default:
            return record
    return enabled[0] if enabled else None


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def resolve(kind: str, model_name: Optional[str] = None,
            operation: Optional[str] = None,
            thinking_profile: str = 'answer') -> ResolvedEndpoint:
    """解析一个可调用的端点。**永不抛错** —— 最差也会给出一份 ``.env`` 的回落。

    调用方拿到的是可直接发的 URL，不需要知道它来自注册表还是环境变量；
    需要知道的时候看 :attr:`ResolvedEndpoint.origin`。

    ``thinking_profile``：``answer``（默认，用每模型配置）或 ``aux``
    （改写/重排/路由，自动用关闭/最低思考的预置）。
    """
    rows = _load_records()
    if rows is not None:
        kind_rows = [r for r in rows if r.model_kind == kind]
        record = _pick(kind_rows, model_name)
        if record is None and model_name:
            if kind == 'llm':
                # 生成模型：请求名不在注册表里（典型：UI 刚注册模型，``.env`` 还留着
                # 占位名）→ 先用注册表默认行，只有一条启用行都没有时才真正回落 .env。
                record = _pick(kind_rows, None)
                if record is not None:
                    log.warning(
                        'model %s/%s not found in registry; using default registry model %s',
                        kind, model_name, record.model_name)
                else:
                    log.info(
                        'model %s/%s not found in registry and no enabled llm model; '
                        'falling back to env config', kind, model_name)
            else:
                # embedding / rerank 不借别的行：静默换模型会让向量维度与库里的表对不上。
                # **必须是 warning 并写明回落地址**：占位/错误的 .env 会让这条请求
                # 打到一个不存在的端点，而症状只是一句通用的 502。
                endpoint = _from_env(kind, model_name, operation)
                log.warning('model %s/%s not found in registry; falling back to env endpoint %s',
                            kind, model_name, endpoint.url)
                return endpoint
        if record is not None:
            op = operation or _default_operation(kind)
            url = record.endpoint_for(op)
            if url:
                thinking_payload = None
                if kind == 'llm':
                    # 延迟 import：core 层不主动依赖 compat；解析到注册表行时它一定可导入。
                    from model import thinking_presets
                    thinking_payload = thinking_presets.resolve_payload(
                        record.thinking_mode, record.thinking_preset,
                        record.thinking_payload, record.effective_api_model(),
                        record.model_name, record.base_url,
                        profile=thinking_profile)
                return ResolvedEndpoint(
                    kind=kind, model_name=record.model_name,
                    api_model=record.effective_api_model(), url=url,
                    api_key=record.api_key,
                    timeout=record.timeout, max_tokens=record.max_tokens,
                    temperature=record.temperature, dimension=record.dimension,
                    thinking_mode=record.thinking_mode,
                    thinking_preset=record.thinking_preset,
                    thinking_payload=thinking_payload,
                    base_url=record.base_url, path=record.path_for(op),
                    origin='registry', source=record.source)
    return _from_env(kind, model_name, operation)


def _default_operation(kind: str) -> str:
    return {'llm': _OP_CHAT, 'embedding': _OP_EMBEDDINGS, 'rerank': _OP_RERANK}.get(
        kind, _OP_CHAT)


def effective_generation_overrides(endpoint) -> Optional[dict]:
    """这次生成要合并进请求体的思考片段；``None`` = 不发送。

    * 注册表端点：``resolve()`` 已经按行内意图（auto/preset/custom）解析好，
      直接返回 ``thinking_payload``；**不再读全局 env**（行内是权威）。
    * env 回落端点：``_from_env`` 已把 ``GENERATION_CHAT_TEMPLATE_KWARGS``
      包成 ``{'chat_template_kwargs': ...}``。

    返回副本，避免调用方改动端点对象里的共享 dict。
    """
    payload = getattr(endpoint, 'thinking_payload', None)
    if isinstance(payload, dict) and payload:
        return copy.deepcopy(payload)
    return None


def _env_thinking_payload() -> Optional[dict]:
    """``GENERATION_CHAT_TEMPLATE_KWARGS`` 的值是 chat_template_kwargs 的内容，
    不是完整请求片段；这里包一层。"""
    raw = os.environ.get('GENERATION_CHAT_TEMPLATE_KWARGS', '').strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        log.warning('invalid GENERATION_CHAT_TEMPLATE_KWARGS: %s', raw[:200])
        return None
    return {'chat_template_kwargs': value} if isinstance(value, dict) else None


def _from_env(kind: str, model_name: Optional[str],
              operation: Optional[str]) -> ResolvedEndpoint:
    """回落路径的默认值 —— 别在这里顺手「改进」。"""
    if kind == 'embedding':
        base = _env(_ENV_EMBEDDING_BASE, DEFAULT_EMBEDDING_BASE)
        path = _env(_ENV_EMBEDDING_PATH, DEFAULT_EMBEDDING_PATH)
        try:
            dimension = int(_env(_ENV_EMBEDDING_DIMENSION, str(DEFAULT_EMBEDDING_DIMENSION)))
        except ValueError:
            dimension = DEFAULT_EMBEDDING_DIMENSION
        return ResolvedEndpoint(
            kind=kind,
            model_name=(model_name or '').strip() or _env(
                _ENV_EMBEDDING_MODEL_NAME, _env(_ENV_EMBEDDING_MODEL, DEFAULT_EMBEDDING_MODEL)),
            api_model=_env(_ENV_EMBEDDING_MODEL, DEFAULT_EMBEDDING_MODEL),
            url=base.rstrip('/') + path,
            api_key=_env(_ENV_EMBEDDING_KEY),
            dimension=dimension, base_url=base, path=path, origin='env')

    if kind == 'rerank':
        url = _env(_ENV_RERANK_URL)
        return ResolvedEndpoint(
            kind=kind,
            model_name=(model_name or '').strip() or _env(_ENV_RERANK_MODEL, DEFAULT_RERANK_MODEL),
            api_model=_env(_ENV_RERANK_MODEL, DEFAULT_RERANK_MODEL),
            # 空串 = 本部署没有重排端点。**不要**把它变成「看起来配了」——
            # 调用方据此显式报 rerank-endpoint-not-configured（契约的硬约定）
            url=url, base_url=url, path='',
            origin='env')

    base = _env(_ENV_GENERATION_BASE, DEFAULT_GENERATION_BASE)
    if operation == _OP_MODELS:
        path = _env(_ENV_GENERATION_MODELS_PATH, '/models')
    else:
        path = '/chat/completions'
    if not path.startswith('/'):
        path = '/' + path
    return ResolvedEndpoint(
        kind='llm',
        model_name=(model_name or '').strip() or _env(_ENV_GENERATION_MODEL, DEFAULT_GENERATION_MODEL),
        api_model=(model_name or '').strip() or _env(_ENV_GENERATION_MODEL, DEFAULT_GENERATION_MODEL),
        url=base.rstrip('/') + path,
        api_key=_env(_ENV_GENERATION_KEY),
        timeout=_int_env(_ENV_GENERATION_TIMEOUT, DEFAULT_GENERATION_TIMEOUT),
        max_tokens=_int_env(_ENV_GENERATION_MAX_TOKENS, DEFAULT_GENERATION_MAX_TOKENS),
        temperature=_float_env(_ENV_GENERATION_TEMPERATURE, DEFAULT_GENERATION_TEMPERATURE),
        thinking_payload=_env_thinking_payload(),
        base_url=base, path=path, origin='env')


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# 消费面（画布下拉 / getLlmList / 能力校验）用的一组派生值
# ---------------------------------------------------------------------------
def llm_models() -> tuple:
    """``((model_name, display), ...)`` —— 注册表启用的 llm，读不到则回落到 ``.env`` 那份。

    **形状与 ``runtime_config._parse_models`` 一致**（``(modelValue, nameZh)``），
    因为下游的 ``RuntimeCapabilities.llm_models`` 就是这个形状。
    """
    rows = records('llm')
    if rows:
        enabled = [r for r in rows if r.enabled]
        if enabled:
            return tuple((r.model_name, r.label()) for r in enabled)
    return env_capabilities.parse_models(os.environ.get(env_capabilities.ENV_MODELS))


def generation_base_url() -> str:
    """部署生成端点的 base（``.env`` 的 ``GENERATION_GATEWAY_URL``，缺省内置默认）。

    模型清单探测（:mod:`model.probe`）探的就是它 —— 校验「画布模型在不在端点上」
    必须拿同一个地址做比较，否则会拿别的网关的清单去判。
    """
    return _env(_ENV_GENERATION_BASE, DEFAULT_GENERATION_BASE)


def llm_routes() -> tuple[dict, frozenset]:
    """画布上的 llm 名字 → 运行时真正会发出的 ``api_model``，以及「自带端点」的名字。

    返回 ``(api_models, self_hosted)``，两个容器的键都是**小写**名字（注册名或
    ``api_model``）：

    * ``api_models``：名字 → ``effective_api_model()``。画布存的是注册名、而请求体发的是
      api_model（``openai_llm.py:_endpoint``），校验必须按后者比对。
    * ``self_hosted``：该行有**自己的** ``base_url`` 且 ≠ 部署生成端点。运行时打它自己的
      地址，而清单探测只探部署生成端点 —— 对它**没有判据**，校验要放行（宁可漏报不误报）。

    匹配语义与 :func:`resolve` 的 ``_pick`` 一致：只算启用的行、按行序首次命中
    （注册名或 api_model 任一相同）。不做这个对齐就会出现「校验说没有、运行时却能跑」
    （或者反过来）。读不到注册表 → ``({}, frozenset())``，校验回落成「按画布名字原样比」。
    """
    rows = records('llm')
    if rows is None:
        return {}, frozenset()
    gateway = generation_base_url().rstrip('/').lower()
    api_models: dict[str, str] = {}
    self_hosted: set[str] = set()
    for record in rows:
        if not record.enabled:
            continue
        own_base = (record.base_url or '').rstrip('/').lower()
        served_by_gateway = (not own_base) or own_base == gateway
        api_model = record.effective_api_model()
        for name in {record.model_name, api_model}:
            key = (name or '').strip().lower()
            if not key or key in api_models:
                # 首条命中的行说了算（与 _pick 同义），后面的行不再覆盖
                continue
            api_models[key] = api_model
            if not served_by_gateway:
                self_hosted.add(key)
    return api_models, frozenset(self_hosted)


def reasoning_models() -> tuple:
    """注册表里标了 ``is_reasoning`` 的模型；没有则回落 ``.env`` 的 ``REASONING_MODELS``。"""
    rows = records('llm')
    if rows:
        flagged = tuple(r.model_name for r in rows if r.enabled and r.is_reasoning)
        if flagged:
            return flagged
    return env_capabilities.parse_reasoning_models(
        os.environ.get(env_capabilities.ENV_REASONING_MODELS))


def rerank_url() -> str:
    """默认重排端点的完整 URL；空串 = 本部署没有重排能力（契约要求调用方显式失败）。"""
    rows = records('rerank')
    if rows is not None:
        record = _pick([r for r in rows if r.enabled], None)
        if record is not None:
            return record.endpoint_for(_OP_RERANK)
    return env_capabilities.rerank_url()


def rerank_model() -> str:
    """默认重排模型的 ``model`` 字段（端点若校验模型名就必须对）。"""
    rows = records('rerank')
    if rows is not None:
        record = _pick([r for r in rows if r.enabled], None)
        if record is not None:
            return record.effective_api_model()
    return _env(_ENV_RERANK_MODEL, DEFAULT_RERANK_MODEL)


def rerank_model_options() -> list:
    """重排模型下拉：``[{'value', 'label', 'isDefault'}, ...]``。

    数据源与 :func:`rerank_model` 完全同源（注册表启用的 rerank 行，读不到回落
    ``.env``），只是把「展示名」和「哪一行是默认」一起带出来 —— 画布上让用户
    **显式选一个模型**时，需要同时知道 ``value``（存进画布）与默认项（用来渲染
    「跟随部署默认」）。``value`` 用的是**注册名**而不是 ``api_model``：
    ``resolve('rerank', value)`` 两者都认，但注册名在注册表里唯一。

    读不到注册表且没有 ``RERANK_URL`` 时返回 ``[]`` —— 空列表 = 本部署没有重排
    能力，与 :func:`rerank_url` 的空串同义。
    """
    rows = records('rerank')
    if rows is not None:
        enabled = [r for r in rows if r.enabled]
        if enabled:
            default = _pick(enabled, None)
            return [{'value': r.model_name, 'label': r.label(), 'isDefault': r is default}
                    for r in enabled]
    if not env_capabilities.rerank_url():
        return []
    model = _env(_ENV_RERANK_MODEL, DEFAULT_RERANK_MODEL)
    return [{'value': model, 'label': model, 'isDefault': True}]


def rerank_model_names() -> tuple:
    """启用的重排模型注册名（画布校验用；与 :func:`rerank_model_options` 同源）。"""
    return tuple(option['value'] for option in rerank_model_options())


def embedding_model_names() -> tuple:
    """画布校验用的向量模型名：注册名 + ``api_model`` + ``.env`` 回落名。

    与 :func:`resolve` 的判定逐条对齐 —— 只列**运行时真能解析成功**的名字：

    * 命中注册表行：``_pick`` 认注册名与 ``api_model`` 两者，所以两个都算；
    * 没命中：回落 ``.env`` 的 ``MODEL_GATEWAY_URL``，请求体仍带**画布写的名字**，
      因此只有 ``.env`` 里那个模型名是可靠的（别的一律赌端点碰巧也服务它）。

    读不到注册表（``records() is None``）→ ``()``：**无法判定**，校验必须放行。
    注册表可读但没有启用的 embedding 行 → 只剩 ``.env`` 那两个名字（运行时就是走回落）。
    """
    rows = records('embedding')
    if rows is None:
        return ()
    names: list[str] = []
    for record in rows:
        if not record.enabled:
            continue
        for name in (record.model_name, record.effective_api_model()):
            if name and name not in names:
                names.append(name)
    for name in (_env(_ENV_EMBEDDING_MODEL, ''), _env(_ENV_EMBEDDING_MODEL_NAME, '')):
        if name and name not in names:
            names.append(name)
    return tuple(names)


def embedding_model_dimensions() -> dict:
    """模型名（小写）→ 向量维度（画布校验用；与 :func:`embedding_model_names` 同源）。

    只收**注册表行填了 ``dimension``** 的；没填的行不进判据（宁可不出现在这里，
    也不能当成「维度为 0」）。``.env`` 的两个模型名按 ``EMBEDDING_DIMENSION`` 登记 ——
    回落路径写库用的就是这个维度（见 ``model.gateway._env_default_model``）。

    读不到注册表（``records() is None``）→ ``{}``：**无法判定**，校验放行。
    """
    rows = records('embedding')
    if rows is None:
        return {}
    dimensions: dict = {}
    for record in rows:
        if not record.enabled or not record.dimension:
            continue
        for name in (record.model_name, record.effective_api_model()):
            if name:
                dimensions.setdefault(name.strip().lower(), int(record.dimension))
    env_dimension = _int_env(_ENV_EMBEDDING_DIMENSION, DEFAULT_EMBEDDING_DIMENSION)
    for name in (_env(_ENV_EMBEDDING_MODEL, ''), _env(_ENV_EMBEDDING_MODEL_NAME, '')):
        if name:
            dimensions.setdefault(name.strip().lower(), env_dimension)
    return dimensions


def is_writable_embedding_model(model_name: str) -> Optional[bool]:
    """建库/建图用：这个名字是否**会被原样用于写入**（三态）。

    比 :func:`embedding_model_names` 更严 —— 必须**带维度**：注册表行没填
    ``dimension`` 时，写路径（``model.gateway.resolve_model``）会静默换成 ``.env``
    的默认模型，而 ``kb_kbase.embedding_model`` 留下的仍是请求的名字 → 账实不符
    （实际部署里出现过这种记录）。

    * ``True``：命中注册表启用行（注册名或 api_model）或 ``.env`` 默认名；
    * ``False``：确定解析不到；
    * ``None``：**无法判定**（读不到注册表 / 本部署一个可写的模型名都没有）→ 放行。
    """
    if records('embedding') is None:
        return None
    dimensions = embedding_model_dimensions()
    if not dimensions:
        return None
    return (model_name or '').strip().lower() in dimensions


def embedding_models() -> list:
    """启用的 embedding **注册名**列表（建库下拉 ``/embedding/all`` 的数据源）。

    读不到注册表时返回 ``None``（由调用方决定是否放行/回落 ``.env``）——
    又是 ``None`` 与 ``[]`` 的区别：前者是「说不准」，后者是「一个都没有」。
    （`kb_embedding` 表已不存在，不再有按表回落。）
    """
    rows = records('embedding')
    if rows is None:
        return None
    return [r.model_name for r in rows if r.enabled]
