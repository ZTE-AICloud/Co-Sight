"""编排侧取「该打哪个模型端点」的**唯一入口**（模型注册表 → 回落部署配置）。

## 为什么要有这么一个中间层

端点解析的真身在 ``model/resolver.py``（注册表优先、回落 ``.env``，带进程内缓存
与写后失效）。但这一层必须能在**只加载 engine 依赖**的环境里独立导入：
``engine`` 的配置契约单元测试只把服务根放进 ``PYTHONPATH``，直接 ``import model.*``
会引入 psycopg2 等运行期依赖。

于是这里做一次**显式的能力探测**，把「有没有注册表层」这件事收敛成一个开关：

* 导入得到 → 全部走注册表（生产路径：``src/app.py`` 会把 ``src`` 放进 ``sys.path``）；
* 导入不到 → 回落到 ``Config``（仅用部署配置的行为）。

**回落的判定只做一次、且会记一条日志** —— 每次调用都试着 import 再静默吞掉
ImportError，就会把「部署里少了 src 的 path」这种真问题伪装成「模型没生效」。

## 回落路径与部署配置一致

``_ConfigEndpoint`` 里的每个默认值都与 ``engine/settings.py`` 的 ``Config`` 对齐，
宁可看起来啰嗦也不要合并 —— 它是「注册表不可用时行为不变」这条保证的实现。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from engine.settings import Config
from engine.logutil import logger

BGE_RERANKER_LARGE = 'bge-reranker-large'

try:  # 见模块 docstring：这一层必须能在只加载 engine 依赖的环境里导入
    from model import resolver as _resolver

    REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover - 只有在脱离服务源码树的探针里才走这里
    _resolver = None
    REGISTRY_AVAILABLE = False
    logger.warning('model registry layer is not importable; falling back to deployment config')

#: 只在回落路径用到的默认值（与 engine/settings.py 的 Config 逐项对齐）
_DEFAULT_BASE_URL = 'http://model-gateway:8000/v1'
_DEFAULT_MODEL = 'deepseek-chat'
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_TEMPERATURE = 0.01
_DEFAULT_TIMEOUT = 120


@dataclass(frozen=True)
class ConfigEndpoint:
    """回落端点：字段名与 :class:`core.gateway.model_resolver.ResolvedEndpoint` 一致。"""

    model_name: str
    api_model: str
    url: str
    api_key: str = ''
    timeout: int = _DEFAULT_TIMEOUT
    max_tokens: int = _DEFAULT_MAX_TOKENS
    temperature: float = _DEFAULT_TEMPERATURE
    dimension: int = 0
    #: 与 ResolvedEndpoint 同形；回落端点没有每模型开关，恒为 none。
    thinking_mode: str = 'none'
    thinking_preset: str = ''
    thinking_payload: Optional[dict] = None
    origin: str = 'env'

    def headers(self) -> dict:
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        return headers


def _env_thinking_payload() -> Optional[dict]:
    """``GENERATION_CHAT_TEMPLATE_KWARGS`` 历史上是 chat_template_kwargs 的值，
    不是完整请求片段；这里包一层，保持旧行为。"""
    raw = os.environ.get('GENERATION_CHAT_TEMPLATE_KWARGS', '').strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        logger.warning('invalid GENERATION_CHAT_TEMPLATE_KWARGS: %s', raw[:200])
        return None
    return {'chat_template_kwargs': value} if isinstance(value, dict) else None


def _config_llm_endpoint(model_name: str = '') -> ConfigEndpoint:
    base_url = (Config.get('generation_base_url') or '').rstrip('/') or _DEFAULT_BASE_URL
    name = (model_name or '').strip() or (Config.get('generation_model') or _DEFAULT_MODEL)
    return ConfigEndpoint(
        model_name=name,
        api_model=name,
        url=base_url + '/chat/completions',
        api_key=Config.get('generation_api_key', '') or '',
        timeout=int(Config.get('generation_timeout') or _DEFAULT_TIMEOUT),
        max_tokens=int(Config.get('generation_max_tokens') or _DEFAULT_MAX_TOKENS),
        temperature=float(Config.get('generation_temperature') or _DEFAULT_TEMPERATURE),
        thinking_payload=_env_thinking_payload(),
    )


def resolve_llm(model_name: str = '', thinking_profile: str = 'answer'):
    """生成端点。``model_name`` 是画布/算子点的那个模型（空 = 用默认）。

    ``thinking_profile='aux'`` 时，注册表行会解析成关闭/最低思考的预置
    （改写、重排、路由等短输出场景）；默认 ``answer`` 用每模型配置。
    """
    if not REGISTRY_AVAILABLE:
        return _config_llm_endpoint(model_name)
    return _resolver.resolve(
        'llm', model_name or None, operation='chat',
        thinking_profile=thinking_profile)


def effective_generation_overrides(endpoint) -> Optional[dict]:
    """这次生成要合并进请求体的思考片段；``None`` = 不发送。

    注册表层可用时完全交给 resolver（注册表行权威、env 只做回落）。
    **注册表层导入不到时这份 env 解析是必要的重复**：本文件必须能在只有
    只加载 engine 依赖的环境里独立工作（见模块 docstring），不能反向依赖
    ``core.gateway.model_resolver``。
    """
    if REGISTRY_AVAILABLE:
        return _resolver.effective_generation_overrides(endpoint)
    return endpoint.thinking_payload if isinstance(
        getattr(endpoint, 'thinking_payload', None), dict) else None


def resolve_rerank(model_name: str = ''):
    """重排端点。``url`` 为空表示本部署没有重排能力（调用方必须显式失败）。"""
    if not REGISTRY_AVAILABLE:
        name = (model_name or '').strip() or rerank_model_name()
        return ConfigEndpoint(model_name=name, api_model=name,
                              url=Config.get('rerank_url', '') or '')
    return _resolver.resolve('rerank', model_name or None, operation='rerank')


def rerank_model_name() -> str:
    """默认重排模型的 ``model`` 字段（端点若校验模型名就必须对）。

    回落时的语义与 `engine/settings.py` 的 ``Config`` 约定一致：``RERANK_MODEL`` 未设 → 空串，
    由调用方回落到常量 ``bge-reranker-large``。
    """
    if REGISTRY_AVAILABLE:
        return _resolver.rerank_model() or ''
    return Config.get('rerank_model', '') or ''


def default_llm_model() -> str:
    """本部署默认的生成模型名（``invoke_query_llm_info`` 用）。"""
    if not REGISTRY_AVAILABLE:
        return Config.get('generation_model', '') or ''
    return _resolver.resolve('llm').api_model or ''
