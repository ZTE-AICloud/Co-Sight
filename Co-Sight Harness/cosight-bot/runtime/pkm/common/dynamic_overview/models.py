#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态 overview 引擎的数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QueryPack:
    """一跳检索的查询包：questions 走向量，terms 走 BM25。"""

    questions: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    @property
    def primary_question(self) -> str:
        return self.questions[0] if self.questions else ""

    def positive_terms(self) -> list[str]:
        """去重且保持顺序的正向 terms（不含 exclude）。"""
        seen: set[str] = set()
        out: list[str] = []
        for term in [*self.identifiers, *self.entities, *self.constraints, *self.terms]:
            term = (term or "").strip()
            if term and term.lower() not in seen:
                seen.add(term.lower())
                out.append(term)
        return out


@dataclass
class Candidate:
    """一个可回读原文的候选块（section 或 chunk）。"""

    route_index: int
    doc_id: str                 # 全局 ID（f<prefix><local>）
    local_doc_id: str           # 路由内 ID（F###）
    rel_path: str
    section_id: str
    start_line: int
    end_line: int
    chunk_id: str = ""
    header_line: int = 0
    header_path: str = ""
    first_sentence: str = ""
    text: str = ""
    structural: bool = False    # 是否来自结构探针（路 1/2）
    source_scores: dict[str, float] = field(default_factory=dict)
    rerank_score: float = 0.0
    fallback_score: float = 0.0

    @property
    def key(self) -> tuple[str, str, int, int]:
        # Prefer section_id so a body chunk and the skeleton section covering the
        # same line span collapse into one candidate during merge.
        return (self.doc_id, self.section_id or self.chunk_id, self.start_line, self.end_line)

    @property
    def score(self) -> float:
        return self.rerank_score if self.rerank_score > 0 else self.fallback_score

    @property
    def char_count(self) -> int:
        return max(0, self.end_line - self.start_line + 1)


@dataclass
class DocScore:
    """文档级聚合结果。"""

    route_index: int
    doc_id: str
    local_doc_id: str
    rel_path: str
    title: str
    candidates: list[Candidate] = field(default_factory=list)
    score: float = 0.0
    s_body: float = 0.0
    s_struct: float = 0.0
    hit_count: int = 0
    tier: int = 1
    structural_section_ids: set[str] = field(default_factory=set)
    structural_first_hits: int = 0
    coverage_terms: list[str] = field(default_factory=list)
    char_count: int = 0

    @property
    def primary_candidate(self) -> Candidate | None:
        return max(self.candidates, key=lambda c: c.score) if self.candidates else None


@dataclass
class HopRecord:
    hop: int
    questions: list[str]
    terms: list[str]
    docs: int
    new_docs: int
    candidates: int
    rerank: bool
    elapsed_ms: float
    a0_quality: str = ""
    a0_error: str = ""


@dataclass
class EvidencePack:
    text: str
    tokens: int
    doc_ids: list[str] = field(default_factory=list)
