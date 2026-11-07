"""部署能力（画布校验要用到的「本部署有没有」）。

三样部署能力**由环境变量驱动**：

======================================  ==========================================
配置项                                  RKB 环境变量
======================================  ==========================================
``rag-flow.models``                     ``RKB_FLOW_LLM_MODELS``
``rag-flow.reasoning-models``           ``RKB_FLOW_REASONING_MODELS``
``rag-flow.reranker.model.url``         ``RKB_RERANK_URL``
======================================  ==========================================

**归属已定**：这三份清单都是
**部署属性，唯一定义点在 ``deploy/.env``**（``GENERATION_MODELS`` / ``REASONING_MODELS`` /
``RERANK_URL``），由 compose 注入到这里的环境变量。**不要在 application.yml、代码常量或
compose 里抄第二份**，见 ``contracts/model-gateway.md``「不支持动态纳管」一节。

``RKB_RERANK_URL`` 与编排层的 ``RERANK_URL`` 同名同义 —— 编排的 rerank 端点
必须与运行期用的是同一个，否则「preCheck 说能跑、运行时跑不了」。compose 里两者同源。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from model.env_capabilities import (DEFAULT_EMBEDDING_DIMENSION, DEFAULT_RERANK_MODEL,
                                    DEFAULT_RERANK_URL, ENV_EMBEDDING_MODEL,
                                    ENV_EMBEDDING_MODEL_NAME, ENV_MODELS,
                                    ENV_REASONING_MODELS, ENV_RERANK_MODEL, ENV_RERANK_URL,
                                    parse_models, parse_reasoning_models)

@dataclass(frozen=True)
class RuntimeCapabilities:
    """本部署能跑什么（画布校验的判据来源）。

    :param llm_models: ``[{'modelValue': ..., 'nameZh': ...}]``（画布下拉）
    :param reasoning_models: 推理模型清单（问题重构算子选中时给非阻塞警告）
    :param rerank_url: rerank 端点；为空表示本部署没有，``ExternalModelReranker`` 必失败
    :param rerank_models: 本部署可用的重排模型注册名。与 ``rerank_url`` 同义地成对出现：
        端点为空时这里也是空的（没有端点就没有可选的模型）；非空时画布上显式选中的
        模型必须在这个清单里
    :param embedding_models: 本部署可用的向量模型名（注册表启用的行 + ``.env`` 回落名）。
        画布上显式选中的 ``embedding`` 必须在这个清单里。**空 = 无法判定**（读不到
        注册表），此时校验一律放行 —— 与 ``available_models`` 同一条安全阀
    :param embedding_dimensions: 向量模型名（小写）→ 维度。与 ``embedding_models``
        同源，只用于「模型维度 vs 知识库物理向量表维度」的一致性校验；空 = 无法判定
    :param available_models: **探测**得到的生成端点实际可用模型名。空集 = 未探测或探测失败
        （**无法判定**），此时模型可用性判据一律放行 —— 别把它当成「一个模型都没有」。
        由 :mod:`model.probe` 在装配点填，``from_env()`` 不碰它（保持纯函数）
    :param llm_api_models: 画布模型名（小写）→ 运行时实际发出的 ``api_model``。
        注册名与 api_model 不同时（模型管理里可分开填），请求体发的是后者。
        由注册表按解析层同一套规则预计算（见 ``model.resolver.llm_routes``）；
        空 = 无注册表/回落，校验按画布名字原样比对
    :param self_hosted_models: 自带端点（``base_url`` ≠ 部署生成端点）的模型名（小写）。
        运行时打它自己的地址，而模型清单探测只探部署生成端点 —— 对它们没有判据，
        校验必须放行（否则自带端点的注册模型永远发不出去）
    """

    llm_models: tuple = field(default_factory=tuple)
    reasoning_models: tuple = field(default_factory=tuple)
    rerank_url: str = DEFAULT_RERANK_URL
    rerank_models: tuple = field(default_factory=tuple)
    embedding_models: tuple = field(default_factory=tuple)
    embedding_dimensions: dict = field(default_factory=dict)
    available_models: frozenset = field(default_factory=frozenset)
    llm_api_models: dict = field(default_factory=dict)
    self_hosted_models: frozenset = field(default_factory=frozenset)

    def has_rerank_endpoint(self) -> bool:
        return bool(self.rerank_url and self.rerank_url.strip())

    def has_probed_models(self) -> bool:
        """探测是否成功过。``False`` 表示「无法判定」，不是「没有可用模型」。"""
        return bool(self.available_models)


def from_env(env: dict | None = None) -> RuntimeCapabilities:
    """从环境变量装配部署能力（``env`` 只为测试注入）。"""
    source = os.environ if env is None else env
    rerank_url = source.get(ENV_RERANK_URL) or DEFAULT_RERANK_URL
    # 有端点才有一个可选的模型名（未配 RERANK_MODEL 时运行期就是内置常量）
    rerank_models = ((source.get(ENV_RERANK_MODEL) or DEFAULT_RERANK_MODEL),) if rerank_url else ()
    # 没有注册表时运行期就是「回落 .env」——能解析成功的只有这两个名字
    env_embedding = source.get(ENV_EMBEDDING_MODEL) or ''
    env_embedding_name = source.get(ENV_EMBEDDING_MODEL_NAME) or env_embedding
    embedding_models = tuple(
        name for name in dict.fromkeys((env_embedding, env_embedding_name)) if name)
    # 维度与模型名同源：回落路径写库用的就是 EMBEDDING_DIMENSION
    try:
        env_dimension = int(source.get('EMBEDDING_DIMENSION')
                            or DEFAULT_EMBEDDING_DIMENSION)
    except (TypeError, ValueError):
        env_dimension = DEFAULT_EMBEDDING_DIMENSION
    return RuntimeCapabilities(
        llm_models=parse_models(source.get(ENV_MODELS)),
        reasoning_models=parse_reasoning_models(source.get(ENV_REASONING_MODELS)),
        rerank_url=rerank_url,
        rerank_models=rerank_models,
        embedding_models=embedding_models,
        embedding_dimensions={name.lower(): env_dimension for name in embedding_models},
    )


def capabilities() -> RuntimeCapabilities:
    """**本部署能跑什么**（所有消费面的入口）：注册表优先，读不到回落 :func:`from_env`。

    模型清单的权威来源是 ``model_registry`` 表（模型管理页可增删改），
    ``deploy/.env`` 降级为**首次播种 + 回落**。回落的粒度是**逐项**的：
    注册表里没有 llm 行就回落 llm 那几项，没影响 rerank 项。

    延迟 import ``model_resolver``：那模块在回落路径上会反过来 import 本模块，
    模块级互相 import 会成环（与 ``kb_api``/``flow_api`` 之间那条延迟 import 同一理由）。
    它自己在进程内带 TTL 缓存，所以这里每次调用不产生一次数据库往返。
    """
    from model import resolver as model_resolver

    llm_api_models, self_hosted_models = model_resolver.llm_routes()
    return RuntimeCapabilities(
        llm_models=model_resolver.llm_models(),
        reasoning_models=model_resolver.reasoning_models(),
        rerank_url=model_resolver.rerank_url(),
        rerank_models=model_resolver.rerank_model_names(),
        embedding_models=model_resolver.embedding_model_names(),
        embedding_dimensions=model_resolver.embedding_model_dimensions(),
        llm_api_models=llm_api_models,
        self_hosted_models=self_hosted_models,
    )
