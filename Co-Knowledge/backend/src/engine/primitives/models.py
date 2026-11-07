"""自研编排原语：数据模型。

替代 llama-index-core 0.10.31 在编排层的这几类对象：
`Node`/`TextNode`、`NodeWithScore`、`QueryBundle`、`Response`/`StreamingResponse`、
`ToolMetadata`、`QueryEngineTool`、`SelectionResult` 族、`MetadataMode`。

**语义**：
  * `get_content()`：metadata 串非空时 `text_template.format(content, metadata_str)` 后再
    `.strip()`；为空时**直接返回 `self.text`（不 strip）**；
  * `get_metadata_str()`：按 `metadata` 的**插入顺序**遍历（不是排序），分隔符 `"\\n"`，
    每行 `"{key}: {value}"`，按 mode 剔除 excluded 键；
  * `NodeWithScore.text`：`isinstance(node, TextNode)` 不成立时抛
    `ValueError("Node must be a TextNode to get text.")`（不是 None、不是空串）；
  * 默认模板/分隔符沿用原库字面量与**原库的拼写笔误**（`metadata_seperator`）。

许可：默认模板常量与上述行为来自 llama-index-core（MIT）；本文件为独立重写实现。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generator, List, Optional

DEFAULT_TEXT_TEMPLATE = '{metadata_str}\n\n{content}'
DEFAULT_METADATA_TEMPLATE = '{key}: {value}'
DEFAULT_METADATA_SEPERATOR = '\n'  # 拼写沿用原库（原库即为 seperator）

TEXT_NODE_CLASS_NAME = 'TextNode'
NODE_WITH_SCORE_CLASS_NAME = 'NodeWithScore'


class MetadataMode(str, Enum):
    ALL = 'all'
    EMBED = 'embed'
    LLM = 'llm'
    NONE = 'none'


class Node:
    """文本节点（合并原库 `BaseNode` + `TextNode` 中本仓实际用到的部分）。

    本仓只产文本节点（`_to_nodes` / 图谱检索 / 重排合并都是 `text + metadata`），
    因此不再保留 `Document`/多模态节点等分支。
    """

    def __init__(
            self,
            text: str = '',
            metadata: Optional[Dict[str, Any]] = None,
            id_: Optional[str] = None,
            embedding: Optional[List[float]] = None,
            relationships: Optional[Dict[str, Any]] = None,
            excluded_llm_metadata_keys: Optional[List[str]] = None,
            excluded_embed_metadata_keys: Optional[List[str]] = None,
            text_template: str = DEFAULT_TEXT_TEMPLATE,
            metadata_template: str = DEFAULT_METADATA_TEMPLATE,
            metadata_seperator: str = DEFAULT_METADATA_SEPERATOR,
            start_char_idx: Optional[int] = None,
            end_char_idx: Optional[int] = None,
            **_ignored_extra: Any,
    ) -> None:
        self.id_ = id_ or str(uuid.uuid4())
        self.text = text or ''
        self.metadata: Dict[str, Any] = dict(metadata or {})
        self.embedding = embedding
        self.relationships: Dict[str, Any] = dict(relationships or {})
        self.excluded_llm_metadata_keys: List[str] = list(excluded_llm_metadata_keys or [])
        self.excluded_embed_metadata_keys: List[str] = list(excluded_embed_metadata_keys or [])
        self.text_template = text_template
        self.metadata_template = metadata_template
        self.metadata_seperator = metadata_seperator
        self.start_char_idx = start_char_idx
        self.end_char_idx = end_char_idx

    # ---- 原库同名接口 ---------------------------------------------------
    @classmethod
    def class_name(cls) -> str:
        return TEXT_NODE_CLASS_NAME

    @property
    def node_id(self) -> str:
        return self.id_

    @node_id.setter
    def node_id(self, value: str) -> None:
        self.id_ = value

    def set_content(self, value: str) -> None:
        self.text = value

    def get_metadata_str(self, mode: MetadataMode = MetadataMode.ALL) -> str:
        if mode == MetadataMode.NONE:
            return ''

        usable_metadata_keys = set(self.metadata.keys())
        if mode == MetadataMode.LLM:
            for key in self.excluded_llm_metadata_keys:
                if key in usable_metadata_keys:
                    usable_metadata_keys.remove(key)
        elif mode == MetadataMode.EMBED:
            for key in self.excluded_embed_metadata_keys:
                if key in usable_metadata_keys:
                    usable_metadata_keys.remove(key)

        # 顺序 = metadata 的插入顺序（原库用 dict.items() 直接遍历，勿改排序）
        return self.metadata_seperator.join(
            self.metadata_template.format(key=key, value=str(value))
            for key, value in self.metadata.items()
            if key in usable_metadata_keys
        )

    def get_content(self, metadata_mode: MetadataMode = MetadataMode.NONE) -> str:
        metadata_str = self.get_metadata_str(mode=metadata_mode).strip()
        if not metadata_str:
            return self.text

        return self.text_template.format(
            content=self.text, metadata_str=metadata_str
        ).strip()

    def get_text(self) -> str:
        return self.get_content(metadata_mode=MetadataMode.NONE)

    def get_embedding(self) -> Optional[List[float]]:
        return self.embedding

    # ---- 反序列化（替代 `TextNode.from_dict`） ---------------------------
    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs: Any) -> 'Node':
        payload = dict(data)
        if isinstance(kwargs, dict):
            payload.update(kwargs)
        payload.pop('class_name', None)
        # 原库走 pydantic，未声明字段默认被忽略（Extra.ignore）—— 这里保持同样口径
        return cls(**payload)

    @classmethod
    def from_json(cls, data_str: str, **kwargs: Any) -> 'Node':
        return cls.from_dict(json.loads(data_str), **kwargs)


# 对外类名：vendored 代码 import 的是 `TextNode` /（作类型注记用的）`BaseNode`。
# 本仓只产文本节点，三个名字指向同一个类。
TextNode = Node
BaseNode = Node


class NodeWithScore:
    """`NodeWithScore`：透传属性与 `text` 的 isinstance 门**保持不变**。"""

    def __init__(self, node: Node, score: Optional[float] = None) -> None:
        self.node = node
        self.score = score

    @classmethod
    def class_name(cls) -> str:
        return NODE_WITH_SCORE_CLASS_NAME

    def __str__(self) -> str:
        score_str = 'None' if self.score is None else f'{self.score: 0.3f}'
        return f'{self.node}\nScore: {score_str}\n'

    def get_score(self, raise_error: bool = False) -> float:
        if self.score is None:
            if raise_error:
                raise ValueError('Score not set.')
            return 0.0
        return self.score

    # ---- pass through to node ------------------------------------------
    @property
    def node_id(self) -> str:
        return self.node.node_id

    @property
    def id_(self) -> str:
        return self.node.id_

    @property
    def text(self) -> str:
        if isinstance(self.node, Node):
            return self.node.text
        raise ValueError('Node must be a TextNode to get text.')

    @property
    def metadata(self) -> Dict[str, Any]:
        return self.node.metadata

    @property
    def embedding(self) -> Optional[List[float]]:
        return self.node.embedding

    def get_text(self) -> str:
        if isinstance(self.node, Node):
            return self.node.get_text()
        raise ValueError('Node must be a TextNode to get text.')

    def get_content(self, metadata_mode: MetadataMode = MetadataMode.NONE) -> str:
        return self.node.get_content(metadata_mode=metadata_mode)


class RagNodeWithScore(NodeWithScore):
    """带知识库来源的节点（编排层自研扩展，非原库类型）。"""

    def __init__(self, node: Node, score: Optional[float] = None, base_name: str = '') -> None:
        super().__init__(node=node, score=score)
        self.base_name = base_name


class QueryBundle:
    """查询包。本仓只用 `query_str`（含改写算子的**原地改写**，勿改成不可变）。"""

    def __init__(self, query_str: str, **kwargs: Any) -> None:
        self.query_str = query_str
        # 这些构造参数由反序列化/外部构造传入，本仓不直接使用
        self.custom_embedding_strs = kwargs.get('custom_embedding_strs')
        self.embedding = kwargs.get('embedding')


@dataclass
class Response:
    """非流式响应（字段与语义对齐原库 dataclass）。"""

    response: Optional[str]
    source_nodes: List[NodeWithScore] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    #: 本次检索实际使用的问句（改写算子原地改写后的值）；证据面板展示用
    query_str: str = ''

    def __str__(self) -> str:
        return self.response or 'None'


@dataclass
class StreamingResponse:
    """流式响应。`app._check_response` 靠 `hasattr(response, 'response_gen')` 判别流式。

    `response_txt` / `__str__` / `get_response()` 与库同形：`__str__` 会把生成器
    **消费并记忆**（`combine_responses`（路由器多选）靠 `str(response)` 取文本）。
    """

    response_gen: Optional[Generator[str, None, None]] = None
    source_nodes: List[NodeWithScore] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    response_txt: Optional[str] = None
    #: 本次检索实际使用的问句（同 `Response.query_str`）
    query_str: str = ''

    def __str__(self) -> str:
        if self.response_txt is None and self.response_gen is not None:
            response_txt = ''
            for text in self.response_gen:
                response_txt += text
            self.response_txt = response_txt
        return self.response_txt or 'None'

    def get_response(self) -> 'Response':
        if self.response_txt is None and self.response_gen is not None:
            response_txt = ''
            for text in self.response_gen:
                response_txt += text
            self.response_txt = response_txt
        return Response(self.response_txt, self.source_nodes, self.metadata)


@dataclass
class ToolMetadata:
    """候选工具的描述（选择器 choices 的原料）。"""

    name: Optional[str] = None
    description: Optional[str] = None
    return_direct: bool = False


class QueryEngineTool:
    """`QueryEngineTool`：`from_defaults` 的回落口径与 RouterQueryEngine 的取用处一致。"""

    def __init__(self, query_engine: Any, metadata: ToolMetadata) -> None:
        self._query_engine = query_engine
        self.metadata = metadata

    @classmethod
    def from_defaults(
            cls,
            query_engine: Any,
            name: Optional[str] = None,
            description: Optional[str] = None,
            return_direct: bool = False,
            **_ignored: Any,
    ) -> 'QueryEngineTool':
        from engine.primitives.prompts import DEFAULT_DESCRIPTION, DEFAULT_NAME
        metadata = ToolMetadata(
            name=name or DEFAULT_NAME,
            description=description or DEFAULT_DESCRIPTION,
            return_direct=return_direct,
        )
        return cls(query_engine=query_engine, metadata=metadata)

    @property
    def query_engine(self) -> Any:
        return self._query_engine


@dataclass
class SingleSelection:
    index: int
    reason: str


class MultiSelection:
    """`SelectorResult`（原库别名 `SelectorResult = MultiSelection`）。"""

    def __init__(self, selections: Optional[List[SingleSelection]] = None) -> None:
        self.selections: List[SingleSelection] = list(selections or [])

    @property
    def ind(self) -> int:
        if len(self.selections) != 1:
            raise ValueError(f'There are {len(self.selections)} selections, please use .inds.')
        return self.selections[0].index

    @property
    def reason(self) -> str:
        if len(self.reasons) != 1:
            raise ValueError(f'There are {len(self.reasons)} selections, please use .reasons.')
        return self.selections[0].reason

    @property
    def inds(self) -> List[int]:
        return [x.index for x in self.selections]

    @property
    def reasons(self) -> List[str]:
        return [x.reason for x in self.selections]


SelectorResult = MultiSelection
