"""模型注册与管理（LLM / Embedding / Reranker 三类，OpenAI 兼容端点）。

对外：``{RKB_PREFIX}/models`` 的增删改查 + 连接测试（``router.py``）。
对内：``model_registry`` 表是「本部署有哪些模型」的权威来源，
``src/core/gateway/model_resolver.py`` 据此解析运行期端点，各消费面
（画布下拉、``getLlmList``、``/embedding/all``、preCheck、编排）都从它派生。

契约面（**改之前先读**）：``contracts/model-gateway.md`` 的「模型清单与动态纳管」一节 ——
那里记着本功能的翻案依据，以及**仍然不做**的三件事（多租户可见性、tag 运营选型、
动态推理服务注册中心）。
"""

from __future__ import annotations

from model.router import register_model_api

__all__ = ['register_model_api']
