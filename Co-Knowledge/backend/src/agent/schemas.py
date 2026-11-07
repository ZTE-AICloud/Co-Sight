"""Agent API 的请求/响应模型（FastAPI OpenAPI 的来源）。

与仓库里 kb_api 的「手写 binding」不同，新接口用 Pydantic 声明式绑定：
OpenAPI 可以自动生成，Agent 平台能直接导入。成功体就是资源本身；错误体是 RFC 9457
``Problem``（``application/problem+json``）。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent import config

SearchMode = Literal['auto', 'hybrid', 'vector', 'keyword']


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')


def _normalize_kb_ids(value):
    if value is None or not isinstance(value, list):
        return value
    ids: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return value                     # 交给 Pydantic 报类型错误
        item = item.strip()
        if item and item not in ids:
            ids.append(item)
    limit = config.max_kbs()
    if len(ids) > limit:
        raise ValueError(f'at most {limit} knowledge_base_ids are allowed')
    return ids


class SearchRequest(_StrictRequest):
    query: str = Field(min_length=1, max_length=2000,
                       description='Natural-language query')
    knowledge_base_ids: Optional[list[str]] = Field(
        default=None,
        description='Document knowledge base IDs; omitted/empty = all accessible')
    mode: SearchMode = Field(default='auto', description='auto|hybrid|vector|keyword')
    top_k: int = Field(default=8, ge=1,
                       description='Number of results; upper bound is configurable (default 20)')
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0,
                                   description='Vector-only cosine threshold')

    @field_validator('knowledge_base_ids', mode='before')
    @classmethod
    def _normalize_ids(cls, value):
        return _normalize_kb_ids(value)

    @field_validator('top_k')
    @classmethod
    def _check_top_k(cls, value: int) -> int:
        limit = config.max_top_k()
        if value > limit:
            raise ValueError(f'top_k must be <= {limit}')
        return value


class AnswerRequest(_StrictRequest):
    question: str = Field(min_length=1, max_length=2000)
    knowledge_base_ids: Optional[list[str]] = Field(
        default=None,
        description='Document knowledge base IDs; omitted/empty = all accessible')
    mode: SearchMode = Field(default='auto', description='Retrieval mode used before generation')
    top_k: int = Field(default=8, ge=1,
                       description='Number of sources; upper bound is configurable (default 20)')
    model: Optional[str] = Field(default=None, max_length=255,
                                 description='Optional registered LLM name')

    @field_validator('knowledge_base_ids', mode='before')
    @classmethod
    def _normalize_ids(cls, value):
        return _normalize_kb_ids(value)

    @field_validator('top_k')
    @classmethod
    def _check_top_k(cls, value: int) -> int:
        limit = config.max_top_k()
        if value > limit:
            raise ValueError(f'top_k must be <= {limit}')
        return value


class KnowledgeBaseInfo(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    type: Optional[str] = None
    embedding_model: Optional[str] = None
    status: Optional[str] = None
    created_date: Optional[str] = None


class SearchResult(BaseModel):
    citation_id: str
    knowledge_base_id: str
    knowledge_base_name: Optional[str] = None
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    source: Optional[str] = None
    score: float
    scores: Optional[dict[str, float]] = None
    text: str
    metadata: Optional[dict[str, Any]] = None


class WarningItem(BaseModel):
    code: str
    message: str
    knowledge_base_id: Optional[str] = None


class SearchData(BaseModel):
    query: str
    mode: str
    results: list[SearchResult]
    degraded: bool = False
    warnings: list[WarningItem] = Field(default_factory=list)


class Citation(BaseModel):
    citation_id: str
    knowledge_base_id: str
    document_id: Optional[str] = None
    source: Optional[str] = None
    chunk_id: Optional[str] = None
    text: str


class AnswerData(BaseModel):
    answer: Optional[str] = None
    citations: list[Citation] = Field(default_factory=list)
    model: Optional[str] = None
    usage: Optional[dict[str, Any]] = None
    no_results: bool = False
    reason: Optional[str] = None
    warnings: list[WarningItem] = Field(default_factory=list)


class WorkflowBoundKnowledgeBase(BaseModel):
    """工作流列表回显的绑定库（与画布下拉同一份字段）。"""

    name: Optional[str] = None
    type: Optional[str] = None
    status: Optional[Any] = None
    assetId: Optional[str] = None
    kbasePkId: Optional[Any] = None
    tableName: Optional[str] = None
    dbTableName: Optional[str] = None
    embeddingModel: Optional[str] = None


class WorkflowInfo(BaseModel):
    """工作流元数据（字段名与 ``/workflows`` 管理接口一致）。"""

    workFlowId: str
    name: str
    description: Optional[str] = None
    template: Optional[str] = None
    knowledgeType: Optional[str] = None
    publishType: int = 0
    status: Optional[int] = None
    createdBy: Optional[str] = None
    createdDate: Optional[str] = None
    lastUpdatedDate: Optional[str] = None
    kbPkIds: list[WorkflowBoundKnowledgeBase] = Field(default_factory=list)
    graphKbPkIds: list[WorkflowBoundKnowledgeBase] = Field(default_factory=list)


class WorkflowPage(BaseModel):
    items: list[WorkflowInfo]
    total: int
    page: int
    pageSize: int


class ChatHistoryItem(BaseModel):
    """一轮历史问答（与 ``/query`` 的 ``chat_history`` 元素同形）。"""

    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(default='')


class WorkflowQueryRequest(_StrictRequest):
    """``POST /agent/query`` 的请求体（只暴露外部需要的字段）。"""

    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str = Field(min_length=1, max_length=255)
    workflow_id: str = Field(min_length=1, max_length=255,
                             description='Published workflow ID')
    stream: bool = Field(default=False, description='Return SSE when true')
    include_retrieval: bool = Field(default=False)
    chat_history: Optional[list[ChatHistoryItem]] = None

    def to_rag_request(self):
        """转成编排运行时的 ``RagRequest``（延迟 import，保持 agent 包轻量）。"""
        from engine.common.beans.rag_request import RagRequest

        values = {
            'question': self.question,
            'conversation_id': self.conversation_id,
            'workflow_id': self.workflow_id,
            'stream': self.stream,
            'include_retrieval': self.include_retrieval,
        }
        # ``RagRequest.chat_history`` 声明为 ``list``（默认 None 只允许省略，
        # 显式传 None 会被 Pydantic 判成类型错误）；有历史时才带上。
        if self.chat_history:
            values['chat_history'] = [item.model_dump() for item in self.chat_history]
        return RagRequest(**values)


class WorkflowQueryAnswer(BaseModel):
    """非流式回答体（Agent 面精简形状；仅用于 OpenAPI）。"""

    conversation_id: str
    answer: Optional[str] = None
    retrieval: Optional[dict[str, Any]] = None


class Problem(BaseModel):
    """RFC 9457 ``application/problem+json``（只用于 OpenAPI 文档）。"""

    model_config = ConfigDict(extra='allow')

    type: str
    title: str
    status: int
    detail: str
    code: str
    instance: Optional[str] = None
