"""首次启动播种：把部署里已配置的模型写进注册表，让升级后**看到的东西一模一样**。

**为什么必须播种**：模型清单的权威来源是注册表。
不播种的话，升级完成的那一刻所有下拉都是空的 —— 对一个已经建好知识库/画布的部署来说，
这是**故障**。播种让「注册表里的内容 == ``.env`` 里能看到的」成为可断言的性质
（见 ``tests/test_model_registry_seed.py``）。

播三样，**按 kind 各自独立判空**（某一类已经有行就不碰它，避免把用户后来的增删覆盖掉）：

============================  ==========================================================
kind                          来源
============================  ==========================================================
llm                           ``RKB_FLOW_LLM_MODELS``（= compose 注入的 ``GENERATION_MODELS``）
                              ``is_reasoning`` 取自 ``RKB_FLOW_REASONING_MODELS``
embedding                     ``EMBEDDING_MODEL`` / ``EMBEDDING_MODEL_NAME`` / ``EMBEDDING_DIMENSION``
                              + 端点 ``MODEL_GATEWAY_URL`` + ``MODEL_GATEWAY_EMBEDDINGS_PATH``
rerank                        ``RERANK_URL`` / ``RERANK_MODEL``（当前默认留空 → 不播）
============================  ==========================================================

**环境变量的读取口径**（与 ``workflow/runtime_config.py`` 一致）：
优先 RKB 侧的名字（``RKB_FLOW_*``，compose 注入的就是它们），再退回 ``.env`` 的原名，
这样「只在宿主 ``.env`` 里改了、容器没接到」这个老陷阱不会在播种时静默丢模型。
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlsplit

from model.models import (
    MODEL_KIND_EMBEDDING,
    MODEL_KIND_LLM,
    MODEL_KIND_RERANK,
    SOURCE_ENV,
    ModelRecord,
    new_model_id,
)

# RKB 侧优先，其次 .env 原名 —— 两边都读的理由见模块 docstring
_ENV_LLM_MODELS = ('RKB_FLOW_LLM_MODELS', 'GENERATION_MODELS')
_ENV_REASONING_MODELS = ('RKB_FLOW_REASONING_MODELS', 'REASONING_MODELS')
_ENV_RERANK_URL = ('RKB_RERANK_URL', 'RERANK_URL')
_ENV_RERANK_MODEL = ('RERANK_MODEL',)

DEFAULT_EMBEDDING_DIMENSION = 1024


def _env(source: dict, names: tuple, default: str = '') -> str:
    for name in names:
        value = (source.get(name) or '').strip()
        if value:
            return value
    return default


def parse_llm_models(raw: str) -> list:
    """``模型名=显示名;模型名=显示名`` → ``[(name, display), ...]``。

    与 ``runtime_config._parse_models`` **同一套格式**（它就是既有单一来源的解析器），
    但这里不复用它：那边的空串会回落到 ``DEFAULT_MODELS`` 硬编码副本，
    而播种需要的是「没配就是不播」，回落会把一份代码里的旧清单固化进数据库。
    """
    models = []
    for chunk in (raw or '').split(';'):
        chunk = chunk.strip()
        if not chunk:
            continue
        value, display = (chunk.split('=', 1) if '=' in chunk else (chunk, chunk))
        value, display = value.strip(), display.strip()
        if value:
            models.append((value, display or value))
    return models


def split_endpoint_url(url: str) -> tuple:
    """把「整个端点 URL」拆成 ``(base_url, path)``。

    ``RERANK_URL`` 这类变量记的是**完整 URL**（``编排层`` 直接 ``requests.post``
    它），而注册表按 base + path 建模。已知形态是 ``.../rerank``，就按它拆：

    * 以 ``/rerank`` 结尾 → ``('https://h/v1', '/rerank')``（理想形态，path 与默认值相同）
    * 其余情况 → ``(url, url)``，即把**绝对 URL 当路径**（见 ``models.endpoint_for``），
      这样无论对方怎么配都不会拼出一个错的地址
    """
    value = (url or '').strip()
    if not value:
        return '', ''
    if value.endswith('/rerank'):
        return value[: -len('/rerank')], '/rerank'
    return value, value


def _is_placeholder_url(url: str) -> bool:
    """``*.example.com`` / ``*.example.org`` 是文档占位符，不是真实端点。"""
    host = (urlsplit(url or '').hostname or '').lower()
    return (host == 'example.com' or host.endswith('.example.com')
            or host == 'example.org' or host.endswith('.example.org'))


def build_llm_records(env: dict) -> list:
    """从环境变量造 llm 行。"""
    raw = _env(env, _ENV_LLM_MODELS)
    models = parse_llm_models(raw)
    if not models:
        return []
    base_url = _env(env, ('GENERATION_GATEWAY_URL',))
    # 没配端点或仍是文档占位符时**不播**：否则下拉里会出现一个点谁谁 404 的死条目。
    if not base_url or _is_placeholder_url(base_url):
        return []
    models_path = _env(env, ('GENERATION_MODELS_PATH',))
    # ⚠️ **key 必须一起播**：不播的话，注册表里这一行的 key 是空的，而解析层命中注册表后
    # 就**不会**再去看 ``GENERATION_API_KEY`` —— 运行期请求会静默少掉 Authorization，
    # LiteLLM 回 401。连接测试对种子行报「无法判定」正是这个症状的前哨。
    # 播种的意义就是「升级后行为一字不变」，key 也是行为的一部分。
    api_key = _env(env, ('GENERATION_API_KEY',))
    reasoning = {name for name in
                 (item.strip() for item in _env(env, _ENV_REASONING_MODELS).split(',')) if name}
    records = []
    for index, (name, display) in enumerate(models):
        records.append(ModelRecord(
            model_id=new_model_id(), model_kind=MODEL_KIND_LLM,
            model_name=name, display_name=display,
            base_url=base_url or '',
            chat_path='', models_path=models_path, api_key=api_key,
            is_reasoning=name in reasoning,
            # 第一条即默认（``GENERATION_MODEL`` 就是指向它的，历史行为）
            is_default=(index == 0),
            source=SOURCE_ENV,
            remark='seeded from deploy/.env',
        ))
    return records


def build_embedding_records(env: dict) -> list:
    """从环境变量造 embedding 行（当前端点那一个模型）。"""
    api_model = _env(env, ('EMBEDDING_MODEL',))
    if not api_model:
        return []
    base_url = _env(env, ('MODEL_GATEWAY_URL',))
    if not base_url or _is_placeholder_url(base_url):
        return []
    embeddings_path = _env(env, ('MODEL_GATEWAY_EMBEDDINGS_PATH',))
    raw_dimension = _env(env, ('EMBEDDING_DIMENSION',)) or str(DEFAULT_EMBEDDING_DIMENSION)
    try:
        dimension = int(raw_dimension)
    except ValueError:
        dimension = DEFAULT_EMBEDDING_DIMENSION
    return [ModelRecord(
        model_id=new_model_id(), model_kind=MODEL_KIND_EMBEDDING,
        # ⚠️ 两个命名空间别合并：EMBEDDING_MODEL_NAME 是库里的登记名，
        # EMBEDDING_MODEL 是端点认的仓库名。前者**没被 compose 注入**（老陷阱），
        # 缺席时退回后者 —— 与旧 kb_embedding 里那一行（两个字段同值）一致。
        model_name=_env(env, ('EMBEDDING_MODEL_NAME',)) or api_model,
        display_name=_env(env, ('EMBEDDING_MODEL_NAME',)) or api_model,
        api_model=api_model,
        base_url=base_url or '',
        embeddings_path=embeddings_path,
        dimension=dimension,
        api_key=_env(env, ('MODEL_GATEWAY_API_KEY',)),
        is_default=True, source=SOURCE_ENV,
        remark='seeded from deploy/.env',
    )]


def build_rerank_records(env: dict) -> list:
    """从环境变量造 rerank 行。``RERANK_URL`` 留空（默认）= 本部署没有重排能力 = 不播。"""
    url = _env(env, _ENV_RERANK_URL)
    if not url:
        return []
    base_url, path = split_endpoint_url(url)
    model_name = _env(env, _ENV_RERANK_MODEL) or 'bge-reranker-large'
    return [ModelRecord(
        model_id=new_model_id(), model_kind=MODEL_KIND_RERANK,
        model_name=model_name, display_name=model_name,
        api_model=model_name, base_url=base_url,
        # 拆分失败时 path 是绝对 URL（见 split_endpoint_url），endpoint_for 会原样使用
        rerank_path='' if path == '/rerank' else path,
        is_default=True, source=SOURCE_ENV,
        remark='seeded from deploy/.env',
    )]


def build_seed_records(env: dict) -> list:
    """全部待播记录（纯函数，单测直接喂 dict）。"""
    records = build_llm_records(env)
    records.extend(build_embedding_records(env))
    records.extend(build_rerank_records(env))
    return records


def seed_if_empty(store, env: Optional[dict] = None) -> int:
    """按 kind 判空后播种；返回写入行数。

    **按 kind 独立判空**：某一类已经有行就整类不动（增删过一条不该让整类被重写）。

    某一类被**清空**时下次启动会重新播种 —— 这不是「把用户删掉的复活」，而是与解析层的
    ``.env`` 回落**保持一致**：注册表里没有 llm 行时，解析层本来就回落到 ``.env``，
    画布下拉与 ``getLlmList`` 里照样是那三个模型。与其让管理页显示空的、别处显示三个，
    不如把行显式种回来 —— **管理页显示的**与**实际生效的**必须是一回事。
    """
    source = os.environ if env is None else env
    existing_kinds = {r.model_kind for r in store.list_records()}
    written = 0
    for record in build_seed_records(source):
        if record.model_kind in existing_kinds:
            continue
        if not (record.base_url or '').strip():
            # 没有端点的行种进去就是个死条目（点谁谁 404），不如不种
            from infrastructure.logging.logutil import log

            log.warning('skip seeding %s/%s: no endpoint configured',
                        record.model_kind, record.model_name)
            continue
        store.insert(record)
        written += 1
    return written
