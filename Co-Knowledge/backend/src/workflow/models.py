"""flow_api 的数据模型（dataclass，不可变）。

刻意不用 Pydantic：这些对象在 store 与 service 之间传递，没有独立的校验需求
（校验发生在入口与 ``validation.py``），而 dataclass 的构造开销更低、语义更明确。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# publish_type 的取值（web 列表页按它渲染）
PUBLISH_TYPE_UNPUBLISHED = 0
PUBLISH_TYPE_PUBLISHED = 1
PUBLISH_TYPE_MODIFIED_AFTER_PUBLISH = 2

# 从未发布过的草稿的版本号
FIRST_VERSION = 1

FLOW_TYPE_WORKFLOW = 'workflow'

# 列表页分页参数
MAX_PAGE_SIZE = 1000
DEFAULT_PAGE_SIZE = 10


@dataclass(frozen=True)
class WorkflowRecord:
    """工作流元数据（``flow_workflow`` / 内存 store 的一行）。"""

    workflow_id: str
    name: str
    description: Optional[str] = None
    template: Optional[str] = None
    knowledge_type: Optional[str] = None
    publish_type: int = PUBLISH_TYPE_UNPUBLISHED
    status: int = 1
    bound_info: Optional[dict] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class FlowDraft:
    """画布草稿（``flow_draft``），每工作流一份。``version`` = 最后一次发布的版本号。"""

    workflow_id: str
    node_config: list = field(default_factory=list)
    other_node_config: list = field(default_factory=list)
    version: int = FIRST_VERSION
    flow_type: str = FLOW_TYPE_WORKFLOW
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class FlowPublished:
    """发布快照（``flow_release``），**不可变**，运行期只读这里。"""

    workflow_id: str
    version: int
    node_config: list = field(default_factory=list)
    other_node_config: list = field(default_factory=list)
    created_by: Optional[str] = None
    created_at: Optional[str] = None


@dataclass(frozen=True)
class FlowCanvasInput:
    """保存/校验请求里的画布（``FlowConfigSaveDTO`` 的等价物）。

    ``version`` 收下但**不使用**：草稿保存忽略前端回传的版本号（见 service 注释）。
    """

    flow_type: Optional[str] = None
    version: Optional[int] = None
    node_config_dto_list: list = field(default_factory=list)
    other_node_config_list: list = field(default_factory=list)

    @staticmethod
    def from_payload(payload: Any) -> 'FlowCanvasInput':
        if not isinstance(payload, dict):
            return FlowCanvasInput()
        node_config = payload.get('nodeConfigDTOList')
        other_config = payload.get('otherNodeConfigList')
        return FlowCanvasInput(
            flow_type=payload.get('flowType'),
            version=payload.get('version'),
            node_config_dto_list=node_config if isinstance(node_config, list) else [],
            other_node_config_list=other_config if isinstance(other_config, list) else [],
        )
