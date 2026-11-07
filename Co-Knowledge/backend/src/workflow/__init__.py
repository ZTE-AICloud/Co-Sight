"""检索编排域。

工作流元数据、画布草稿、发布快照与运行时配置都在这一层；对外只暴露
:func:`register_flow_api` 与几个 provider 协议/默认实现。

本包**不依赖 ``app.py``**：只 import ``fastapi`` / ``pydantic`` 与基础设施层
（DB 访问在 repository 内延迟 import），因此可以被单测直接加载。
"""

from workflow.kbase_provider import EmptyKbaseOptionProvider, KbaseOptionProvider
from model.probe import ModelProbe, probe_available_models
from workflow.router import build_router, register_flow_api
from workflow.runtime_config import (RuntimeCapabilities,
                                            capabilities as capabilities_from_registry,
                                            from_env)
from workflow.service import FlowService
from workflow.repository import FlowStore, InMemoryFlowStore, create_default_store

__all__ = [
    'register_flow_api',
    'build_router',
    'FlowService',
    'FlowStore',
    'InMemoryFlowStore',
    'create_default_store',
    'RuntimeCapabilities',
    'from_env',
    # 消费面**一律走这个**（注册表优先、回落 from_env）；from_env 只留给回落与单测
    'capabilities_from_registry',
    'ModelProbe',
    'probe_available_models',
    'KbaseOptionProvider',
    'EmptyKbaseOptionProvider',
]
