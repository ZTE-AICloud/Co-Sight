"""Query Operator 契约与注册表。

一个算子把「自然语言问题」变成「某个领域的结构化查询」并执行它。四段刻意分开，
因为它们的失败语义完全不同：

* ``retrieve`` —— 找知识，失败是「召回不足」，可以降级到全量；
* ``plan``     —— 让模型产出查询，失败是「生成失败」；
* ``validate`` —— 结构/白名单校验，失败是「不安全」或「不合法」，可以回灌重试；
* ``execute``  —— 真正跑，失败是「执行错误」。

Text2SQL 是第一个实现；NL2Graph / NL2Search 等复用同一契约与同一个注册表。
**领域数据与方言留在各自算子里**，这里只定义形状。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class OperatorContext:
    """``retrieve`` 的产出：喂给 ``plan`` 的领域上下文。"""
    text: str
    objects: list[dict[str, Any]] = field(default_factory=list)
    sources: dict[str, int] = field(default_factory=dict)
    fallback: bool = False
    truncated: bool = False


@dataclass
class QueryPlan:
    """``plan`` 的产出：待校验的查询与它的解释。"""
    query: str
    language: str
    explanation: str = ''
    confidence: Optional[float] = None
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidatedPlan:
    """``validate`` 的产出：可以执行的查询。"""
    query: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultSet:
    """``execute`` 的产出：列、行与截断标记。"""
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    byte_truncated: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class OperatorError(RuntimeError):
    """算子某一阶段的失败。``stage`` 与 ``code`` 直接进查询历史。"""

    def __init__(self, code: str, message: str, stage: str,
                 category: str = 'Operator Error'):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stage = stage
        self.category = category


@runtime_checkable
class QueryOperator(Protocol):
    """四段式算子契约。实现方只需保证这四个方法可用。"""

    name: str
    knowledge_types: tuple[str, ...]

    def retrieve(self, question: str, *, datasource_id: str,
                 params: dict[str, Any]) -> OperatorContext:
        ...

    def plan(self, question: str, context: OperatorContext, *,
             params: dict[str, Any]) -> QueryPlan:
        ...

    def validate(self, plan: QueryPlan, *,
                 params: dict[str, Any]) -> ValidatedPlan:
        ...

    def execute(self, plan: ValidatedPlan, *,
                params: dict[str, Any]) -> ResultSet:
        ...


class OperatorRegistry:
    """算子注册表：按名字注册与查找。线程安全足够简单——注册只发生在启动期。"""

    def __init__(self) -> None:
        self._operators: dict[str, QueryOperator] = {}

    def register(self, operator: QueryOperator) -> QueryOperator:
        name = getattr(operator, 'name', '')
        if not name:
            raise ValueError('operator 必须有 name')
        self._operators[name] = operator
        return operator

    def get(self, name: str) -> QueryOperator:
        try:
            return self._operators[name]
        except KeyError as error:
            raise KeyError(f'未注册的算子：{name}') from error

    def names(self) -> list[str]:
        return sorted(self._operators)

    def describe(self) -> list[dict[str, Any]]:
        return [{'name': self._operators[name].name,
                 'knowledgeTypes': list(self._operators[name].knowledge_types)}
                for name in self.names()]


registry = OperatorRegistry()
