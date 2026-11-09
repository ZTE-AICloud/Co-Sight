#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""动态 overview 检索引擎。

MVP 链路：
  Q0 → 四路探针（section 向量 / skeleton FTS / body FTS）→ 候选块
     → 文本还原 → rerank → S(d) → 60K 证据包 → A0/Q1 → 第二跳
     → Global Re-Elbow → Tier 1/2 → 渲染。
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from common.logging_setup import log_event, preview_items, preview_text
from common.text_tokenize import tokenize
from watch_dog.file_watcher.embedding_model import batch_rerank_scores
from watch_dog.file_watcher.section_index import SCHEMA_VERSION, SectionIndex

from .a0 import call_a0
from .models import Candidate, DocScore, EvidencePack, HopRecord, QueryPack
from .query_rewrite import rewrite_query
from .utils import estimate_tokens, normalize_scores, truncate

logger = logging.getLogger("dynamic_overview.engine")

# 初始值来自页面方案；437/51W 评测期用环境变量做校准实验（见 EXP-008）。
# 2026-10-20 H1 校准（500 题 Tier1 recall 81.13%，p95 23.04s）。
TAU_NOISE = float(os.environ.get("COSIGHTBOT_DYNAMIC_TAU", "0.10"))
S_CHUNK_THRESHOLD = float(os.environ.get("COSIGHTBOT_DYNAMIC_HIT_THRESHOLD", "0.40"))
TIER1_LIMIT = int(os.environ.get("COSIGHTBOT_DYNAMIC_TIER1_LIMIT", "100"))
TIER2_LIMIT = int(os.environ.get("COSIGHTBOT_DYNAMIC_TIER2_LIMIT", "150"))
RERANK_BLOCK_LIMIT = int(os.environ.get("COSIGHTBOT_DYNAMIC_RERANK_BLOCKS", "1200"))
RERANK_PER_DOC = int(os.environ.get("COSIGHTBOT_DYNAMIC_RERANK_PER_DOC", "5"))
SEMANTIC_TOP_K = int(os.environ.get("COSIGHTBOT_DYNAMIC_SEMANTIC_TOP_K", "1000"))
SKELETON_FTS_TOP_K = int(os.environ.get("COSIGHTBOT_DYNAMIC_SKELETON_TOP_K", "500"))
BODY_FTS_TOP_K = int(os.environ.get("COSIGHTBOT_DYNAMIC_BODY_TOP_K", "800"))
SCORE_MODE = os.environ.get("COSIGHTBOT_DYNAMIC_SCORE_MODE", "hybrid").lower()
HYBRID_WEIGHT = float(os.environ.get("COSIGHTBOT_DYNAMIC_HYBRID_WEIGHT", "1.0"))
HOP2_NEW_DOCS_ONLY = os.environ.get("COSIGHTBOT_DYNAMIC_HOP2_NEW_DOCS_ONLY", "1") != "0"
HOP2_RERANK_BLOCKS = int(os.environ.get("COSIGHTBOT_DYNAMIC_HOP2_RERANK_BLOCKS", "400"))
HOP2_MAX_QUESTIONS = int(os.environ.get("COSIGHTBOT_DYNAMIC_HOP2_MAX_QUESTIONS", "1"))
# FULL_HIT 仍可能带 gaps；开启后无论 gaps 是否为空都跳过第二跳，用于压 p95。
HOP2_SKIP_FULL_HIT = os.environ.get("COSIGHTBOT_DYNAMIC_HOP2_SKIP_FULL_HIT", "0") != "0"
# Q0 query rewrite：复用当前 LLM 做检索词/问句扩展，默认关闭。
QUERY_REWRITE_ENABLED = os.environ.get("COSIGHTBOT_DYNAMIC_QUERY_REWRITE", "0") != "0"
QUERY_REWRITE_TIMEOUT = float(os.environ.get("COSIGHTBOT_DYNAMIC_QUERY_REWRITE_TIMEOUT", "30"))
QUERY_REWRITE_MAX_QUESTIONS = int(os.environ.get("COSIGHTBOT_DYNAMIC_QUERY_REWRITE_MAX_QUESTIONS", "1"))
MAX_QUESTIONS = 4
OUTPUT_TOKEN_LIMIT = int(os.environ.get("COSIGHTBOT_DYNAMIC_OUTPUT_TOKENS", "35000"))
EVIDENCE_TOKEN_LIMIT = int(os.environ.get("COSIGHTBOT_DYNAMIC_EVIDENCE_TOKENS", "30000"))


class DynamicIndexError(RuntimeError):
    def __init__(self, message: str, error_code: str = "DYNAMIC_INDEX_MISSING"):
        super().__init__(message)
        self.error_code = error_code


@dataclass
class RouteContext:
    route: dict
    index: SectionIndex
    pre_dir: Path
    lan_dir: Path
    local_to_global: dict[str, str]
    local_rel: dict[str, str]
    doc_count: int
    prefix: str
    route_index: int = 0
    _line_cache: dict[str, list[str]] = field(default_factory=dict)

    def global_id(self, local_id: str) -> str:
        return self.local_to_global.get(local_id, local_id)

    def rel_path(self, local_id: str) -> str:
        return self.local_rel.get(local_id, "")

    def read_lines(self, rel_path: str, start: int, end: int) -> str:
        if not rel_path:
            return ""
        lines = self._line_cache.get(rel_path)
        if lines is None:
            try:
                lines = (self.pre_dir / rel_path).read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                lines = []
            self._line_cache[rel_path] = lines
        if not lines:
            return ""
        start = max(1, int(start))
        end = min(len(lines), int(end))
        if end < start:
            return ""
        return "\n".join(lines[start - 1:end])


def _section_columns() -> list[str]:
    return [
        "doc_key", "section_id", "header_path", "level", "start_line",
        "end_line", "char_count", "first_sentence", "table_sig",
    ]


def _filter_in(column: str, values: list[str]) -> str:
    escaped = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
    return f"{column} IN ({escaped})"


def _fetch_rows(table, filter_expr: str, columns: list[str]) -> list[dict]:
    """LanceDB 批量过滤；只取指定列，避免把 section 向量整列读进内存。"""
    try:
        return table.to_lance().to_table(filter=filter_expr, columns=columns).to_pylist()
    except Exception:
        return []


def _fetch_rows_with_columns(table, filter_expr: str, columns: list[str]) -> list[dict]:
    try:
        return table.to_lance().to_table(filter=filter_expr, columns=columns).to_pylist()
    except Exception:
        return _fetch_rows(table, filter_expr, columns)


class DynamicOverviewEngine:
    def __init__(
        self,
        routes: list[dict],
        *,
        context_window: int = 256_000,
        debug: bool = False,
    ):
        self.context_window = max(32_000, int(context_window or 256_000))
        self.debug = debug
        self.contexts: list[RouteContext] = []
        self.static_routes: list[dict] = []
        self._static_doc_count = 0
        self._build_contexts(routes)

    # ------------------------------------------------------------------
    # 路由上下文
    # ------------------------------------------------------------------
    def _build_contexts(self, routes: list[dict]) -> None:
        log_event(
            logger, "engine:context:start", routes=len(routes),
            labels=preview_items([r.get("label") for r in routes], 8),
        )
        for route in routes:
            if route.get("kind") != "agent":
                self.static_routes.append(route)
                continue
            lan_dir = Path(route["lan_dir"])
            version = None
            status_file = lan_dir / ".section_index_status.json"
            if status_file.exists():
                try:
                    status = json.loads(status_file.read_text(encoding="utf-8"))
                    if status.get("status") == "building":
                        stale_after = float(os.environ.get(
                            "COSIGHTBOT_SECTION_BUILD_STALE_SECONDS", "43200"
                        ))
                        age = time.time() - status_file.stat().st_mtime
                        if age <= stale_after:
                            raise DynamicIndexError(
                                f"section index is building for route {route.get('label')}",
                                "INDEX_BUILDING",
                            )
                        log_event(
                            logger, "index:building:stale", level=logging.WARNING,
                            route=route.get("label"), age_seconds=round(age, 1),
                        )
                except DynamicIndexError:
                    raise
                except Exception:
                    pass
            if not (
                (lan_dir / "section_skeleton.lance").is_dir()
                and (lan_dir / "fts" / "body").is_dir()
                and (lan_dir / "fts" / "skeleton").is_dir()
            ):
                raise DynamicIndexError(
                    f"dynamic index missing for route {route.get('label')}: {lan_dir}",
                    "DYNAMIC_INDEX_MISSING",
                )
            index = SectionIndex(lan_dir)
            # schema v1 的 doc_key=rel_path，与稳定 ID 节点表不兼容；必须让
            # 调用方重建，不能静默返回空候选。
            try:
                meta = {
                    row["key"]: row["value"]
                    for row in index.meta_table.to_arrow().to_pylist()
                }
                version = meta.get("schema_version")
                legacy = 0
                if index.doc_table.count_rows():
                    legacy = index.doc_table.to_lance().to_table(
                        filter="doc_key = rel_path", limit=1
                    ).num_rows
                if legacy or (version and version != str(SCHEMA_VERSION)):
                    raise DynamicIndexError(
                        f"section index schema upgrade required for route "
                        f"{route.get('label')} (version={version or 'legacy'})",
                        "DYNAMIC_INDEX_MISSING",
                    )
            except DynamicIndexError:
                raise
            except Exception:
                pass
            local_rel = self._load_local_rel(lan_dir)
            local_to_global, prefix, doc_count = self._load_id_map(route)
            self.contexts.append(RouteContext(
                route=route,
                index=index,
                pre_dir=Path(route["pre_dir"]),
                lan_dir=lan_dir,
                local_to_global=local_to_global,
                local_rel=local_rel,
                doc_count=doc_count,
                prefix=prefix,
                route_index=len(self.contexts),
            ))
            log_event(
                logger, "engine:route", label=route.get("label"),
                kind=route.get("kind"), doc_count=doc_count, prefix=prefix,
                lan_dir=str(lan_dir), pre_dir=str(route.get("pre_dir")),
                schema_version=version,
            )
        for route in self.static_routes:
            try:
                _, _, count = self._load_id_map(route)
                self._static_doc_count += count
            except Exception:
                pass
        log_event(
            logger, "engine:context:done", agent_routes=len(self.contexts),
            static_routes=len(self.static_routes), doc_count=self.total_doc_count,
        )
        if not self.contexts:
            raise DynamicIndexError("no dynamic-capable agent route", "NO_DYNAMIC_ROUTE")

    @staticmethod
    def _load_local_rel(lan_dir: Path) -> dict[str, str]:
        path = lan_dir / "node_index.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        out: dict[str, str] = {}
        for node_id, rel_path in (data or {}).items():
            if re.fullmatch(r"F\d{3,}", str(node_id)) and isinstance(rel_path, str):
                out[str(node_id)] = rel_path
        return out

    @staticmethod
    def _load_id_map(route: dict) -> tuple[dict[str, str], str, int]:
        # 复用 resolver 的路由前缀逻辑，避免两套全局 ID 规则漂移。
        from common import overview_resolver as resolver
        prefixes = resolver._assign_route_prefixes([route])
        global_index, remaps = resolver._build_global_node_index([route])
        local_to_global = dict(remaps[0][1]) if remaps else {}
        doc_count = resolver._count_doc_nodes(global_index)
        return local_to_global, prefixes[0], doc_count

    @property
    def total_doc_count(self) -> int:
        return sum(ctx.doc_count for ctx in self.contexts) + self._static_doc_count

    # ------------------------------------------------------------------
    # Q0 / Q1
    # ------------------------------------------------------------------
    @staticmethod
    def build_query_pack(
        questions: list[str],
        *,
        entities: list[str] | None = None,
        constraints: list[str] | None = None,
        identifiers: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> QueryPack:
        questions = [q.strip() for q in (questions or []) if q and q.strip()]
        if not questions:
            raise ValueError("--question is required")
        entities = [x.strip() for x in (entities or []) if x and x.strip()]
        constraints = [x.strip() for x in (constraints or []) if x and x.strip()]
        identifiers = [x.strip() for x in (identifiers or []) if x and x.strip()]
        exclude = [x.strip() for x in (exclude or []) if x and x.strip()]

        # 槽位里的关键项若未出现在问题中，追加一条完整问句（Q0.questions）。
        joined = " ".join(questions)
        extras = [
            x for x in [*entities, *constraints, *identifiers]
            if x.lower() not in joined.lower()
        ]
        if extras:
            questions.append("；".join(extras))

        terms: list[str] = []
        seen: set[str] = set()
        for raw in [*identifiers, *entities, *constraints]:
            key = raw.lower()
            if key not in seen:
                seen.add(key)
                terms.append(raw)
        for question in questions:
            for token in tokenize(question):
                key = token.lower()
                if key not in seen:
                    seen.add(key)
                    terms.append(token)
        excluded = {x.lower() for x in exclude}
        terms = [t for t in terms if t.lower() not in excluded]
        return QueryPack(
            questions=questions[:MAX_QUESTIONS],
            terms=terms,
            entities=entities,
            constraints=constraints,
            identifiers=identifiers,
            exclude=exclude,
        )

    # ------------------------------------------------------------------
    # 四路探针
    # ------------------------------------------------------------------
    def _rewrite_query(self, q: QueryPack) -> tuple[QueryPack, dict]:
        """Q0 扩展开关打开时调用；失败回退原 QueryPack。"""
        started = time.perf_counter()
        log_event(
            logger, "q0:rewrite:start",
            questions=len(q.questions), question_preview=preview_items(q.questions, 2),
            terms=len(q.terms), terms_preview=preview_items(q.terms, 8),
            timeout_s=QUERY_REWRITE_TIMEOUT, max_extra_questions=QUERY_REWRITE_MAX_QUESTIONS,
        )
        try:
            rewritten = rewrite_query(q, timeout=QUERY_REWRITE_TIMEOUT)
        except Exception as exc:
            elapsed = round((time.perf_counter() - started) * 1000, 1)
            log_event(logger, "q0:rewrite:error", level=logging.WARNING,
                      error=f"{type(exc).__name__}: {exc}", duration_ms=elapsed)
            return q, {"applied": False, "error": f"{type(exc).__name__}: {exc}",
                       "elapsed_ms": elapsed}
        if rewritten is None:
            return q, {"applied": False,
                       "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}
        max_questions = len(q.questions) + max(0, QUERY_REWRITE_MAX_QUESTIONS)
        questions = rewritten.questions[:max_questions]
        terms = rewritten.terms
        pack = QueryPack(
            questions=questions,
            terms=terms,
            entities=q.entities,
            constraints=q.constraints,
            identifiers=q.identifiers,
            exclude=q.exclude,
        )
        return pack, {
            "applied": True,
            "added_terms": max(0, len(terms) - len(q.terms)),
            "added_questions": max(0, len(questions) - len(q.questions)),
            "new_terms": terms[len(q.terms):],
            "new_questions": questions[len(q.questions):],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def _run_hop(
        self,
        q: QueryPack,
        hop: int,
        known_doc_ids: set[str] | None = None,
        rerank_block_limit: int | None = None,
    ) -> tuple[list[Candidate], dict[str, DocScore], dict]:
        started = time.perf_counter()
        log_event(
            logger, "hop:start",
            hop=hop, questions=len(q.questions), question_preview=preview_items(q.questions, 2),
            terms=len(q.terms), terms_preview=preview_items(q.terms, 12),
            known_docs=len(known_doc_ids) if known_doc_ids else 0,
            block_limit=rerank_block_limit if rerank_block_limit is not None else RERANK_BLOCK_LIMIT,
            routes=len(self.contexts), context_window=self.context_window,
        )
        rewrite_meta: dict | None = None
        if hop == 0 and QUERY_REWRITE_ENABLED:
            q, rewrite_meta = self._rewrite_query(q)
        semantic_candidates: list[Candidate] = []
        skeleton_candidates: list[Candidate] = []
        body_candidates: list[Candidate] = []
        timings: dict[str, float] = {}
        for ctx in self.contexts:
            t0 = time.perf_counter()
            semantic_candidates.extend(self._probe_semantic(ctx, q))
            timings["semantic"] = timings.get("semantic", 0.0) + (time.perf_counter() - t0)
            t0 = time.perf_counter()
            skeleton_candidates.extend(self._probe_skeleton_fts(ctx, q))
            timings["skeleton_fts"] = timings.get("skeleton_fts", 0.0) + (time.perf_counter() - t0)
            t0 = time.perf_counter()
            body_candidates.extend(self._probe_body_fts(ctx, q))
            timings["body_fts"] = timings.get("body_fts", 0.0) + (time.perf_counter() - t0)
        all_candidates = [
            *semantic_candidates, *skeleton_candidates, *body_candidates,
        ]
        log_event(
            logger, "hop:probe:done", hop=hop,
            semantic=len(semantic_candidates),
            skeleton_fts=len(skeleton_candidates),
            body_fts=len(body_candidates),
            raw=len(all_candidates),
            raw_docs=len({c.doc_id for c in all_candidates}),
            timings_ms={k: round(v * 1000, 1) for k, v in timings.items()},
        )
        merged = self._merge_candidates(all_candidates)
        selected = self._select_for_rerank(
            merged, q, known_doc_ids=known_doc_ids,
            block_limit=rerank_block_limit,
        )
        rerank_used = self._rerank(selected, q.questions)
        docs = self._aggregate_docs(selected, q)
        if docs:
            scores = [d.score for d in docs.values()]
            top_docs = sorted(docs.values(), key=lambda d: d.score, reverse=True)[:5]
            log_event(
                logger, "hop:docs:done", hop=hop, docs=len(docs),
                score_min=round(min(scores), 4), score_max=round(max(scores), 4),
                top_titles=preview_items([d.title for d in top_docs], 5),
            )
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        log_event(
            logger, f"hop:{hop}:done",
            questions=len(q.questions), terms=len(q.terms),
            raw_candidates=len(all_candidates), merged=len(merged),
            selected=len(selected), docs=len(docs), rerank=rerank_used,
            duration_ms=elapsed, timings={k: round(v * 1000, 1) for k, v in timings.items()},
        )
        diag = {
            "hop": hop,
            "raw_candidates": len(all_candidates),
            "merged_candidates": len(merged),
            "selected_candidates": len(selected),
            "docs": len(docs),
            "rerank": rerank_used,
            "elapsed_ms": elapsed,
            "timings_ms": {k: round(v * 1000, 1) for k, v in timings.items()},
            "probe_counts": {
                "semantic": len(semantic_candidates),
                "skeleton_fts": len(skeleton_candidates),
                "body_fts": len(body_candidates),
            },
        }
        if rewrite_meta is not None:
            diag["q0_rewrite"] = rewrite_meta
        if self.debug:
            diag["probe_docs"] = {
                "semantic": sorted({c.doc_id for c in semantic_candidates}),
                "skeleton_fts": sorted({c.doc_id for c in skeleton_candidates}),
                "body_fts": sorted({c.doc_id for c in body_candidates}),
                "merged": sorted({c.doc_id for c in merged}),
                "selected": sorted({c.doc_id for c in selected}),
            }
        return selected, docs, diag

    def _probe_semantic(self, ctx: RouteContext, q: QueryPack) -> list[Candidate]:
        questions = [x for x in q.questions[:MAX_QUESTIONS] if x]
        if not questions:
            return []
        log_event(
            logger, "probe:semantic:start",
            route=ctx.route.get("label"), questions=len(questions),
            question_preview=preview_items(questions, 2),
            top_k=SEMANTIC_TOP_K, structural_rank=200,
        )
        embedding = ctx.index._get_embedding()
        try:
            vectors = embedding._get_text_embeddings(questions)
        except Exception as exc:
            log_event(
                logger, "probe:semantic:error", level=logging.ERROR,
                route=ctx.route.get("label"), questions=len(questions),
                error=f"{type(exc).__name__}: {exc}",
            )
            raise DynamicIndexError(
                f"embedding failed: {type(exc).__name__}: {exc}", "EMBEDDING_FAILED"
            ) from exc
        rows: list[dict] = []
        for vector in vectors:
            rows.extend(ctx.index.search_sections(vector, top_k=SEMANTIC_TOP_K))
        # 路 1 取 Top 200 作为结构语义；路 3 取更大 Top-K 作为正文语义。
        out: list[Candidate] = []
        best: dict[str, tuple[float, dict]] = {}
        for row in rows:
            distance = float(row.get("_distance", 1.0))
            score = max(0.0, 1.0 - distance)
            section_id = str(row.get("section_id") or "")
            if not section_id:
                continue
            old = best.get(section_id)
            if old is None or score > old[0]:
                best[section_id] = (score, row)
        ordered = sorted(best.values(), key=lambda item: item[0], reverse=True)
        for rank, (score, row) in enumerate(ordered):
            local_doc = str(row.get("doc_key") or "")
            rel_path = ctx.rel_path(local_doc)
            if not rel_path:
                continue
            candidate = Candidate(
                route_index=ctx.route_index,
                doc_id=ctx.global_id(local_doc),
                local_doc_id=local_doc,
                rel_path=rel_path,
                section_id=str(row.get("section_id")),
                start_line=int(row.get("start_line") or 1),
                end_line=int(row.get("end_line") or 1),
                header_path=str(row.get("header_path") or ""),
                first_sentence=str(row.get("first_sentence") or ""),
                structural=rank < 200,
                source_scores={"semantic_struct" if rank < 200 else "semantic_body": score},
                fallback_score=score,
            )
            out.append(candidate)
        log_event(
            logger, "probe:semantic:done",
            route=ctx.route.get("label"), rows=len(rows), sections=len(best),
            candidates=len(out), docs=len({c.doc_id for c in out}),
            structural=sum(1 for c in out if c.structural),
            top_score=round(max((c.fallback_score for c in out), default=0.0), 4),
        )
        return out

    def _probe_skeleton_fts(self, ctx: RouteContext, q: QueryPack) -> list[Candidate]:
        terms = q.positive_terms()
        if not terms:
            return []
        log_event(
            logger, "probe:skeleton:start",
            route=ctx.route.get("label"), terms=len(terms),
            terms_preview=preview_items(terms, 12), top_k=SKELETON_FTS_TOP_K,
            conjunction=False,
        )
        # OR 语义：自然语言问题通常包含多个词，AND 会漏掉只覆盖部分词的文档；
        # BM25 仍会按命中词数与词权重排序。
        hits = ctx.index.fts_skeleton.search(
            terms, top_k=SKELETON_FTS_TOP_K, conjunction=False
        )
        fallback_used = False
        if not hits and len(terms) > 1:
            fallback_used = True
            for term in terms[:8]:
                hits.extend(ctx.index.fts_skeleton.search([term], top_k=50))
            log_event(logger, "probe:skeleton:fallback", route=ctx.route.get("label"),
                      per_term_top_k=50, terms_used=min(8, len(terms)))
        if not hits:
            log_event(logger, "probe:skeleton:empty", route=ctx.route.get("label"))
            return []
        best: dict[str, tuple[float, dict]] = {}
        for hit in hits:
            section_id = str(hit.get("section_id") or "")
            score = float(hit.get("score") or 0.0)
            if section_id and (section_id not in best or score > best[section_id][0]):
                best[section_id] = (score, hit)
        max_score = max((v[0] for v in best.values()), default=0.0) or 1.0
        section_rows = self._fetch_sections(ctx, list(best))
        out: list[Candidate] = []
        rejected_section = 0
        rejected_exact = 0
        rejected_path = 0
        for section_id, (score, hit) in best.items():
            row = section_rows.get(section_id)
            if not row:
                rejected_section += 1
                continue
            text_for_match = " ".join([
                str(row.get("header_path") or ""),
                str(row.get("first_sentence") or ""),
                str(row.get("table_sig") or ""),
                str(hit.get("rel_path") or ""),
            ])
            if not self._exact_match(text_for_match, terms):
                rejected_exact += 1
                continue
            local_doc = str(row.get("doc_key") or hit.get("doc_id") or "")
            rel_path = str(hit.get("rel_path") or ctx.rel_path(local_doc))
            if not rel_path:
                rejected_path += 1
                continue
            out.append(Candidate(
                route_index=ctx.route_index,
                doc_id=ctx.global_id(local_doc),
                local_doc_id=local_doc,
                rel_path=rel_path,
                section_id=section_id,
                start_line=int(row.get("start_line") or 1),
                end_line=int(row.get("end_line") or 1),
                header_path=str(row.get("header_path") or ""),
                first_sentence=str(row.get("first_sentence") or ""),
                structural=True,
                source_scores={"skeleton_fts": min(1.0, score / max_score)},
                fallback_score=min(1.0, score / max_score),
            ))
        log_event(
            logger, "probe:skeleton:done",
            route=ctx.route.get("label"), hits=len(hits), sections=len(best),
            candidates=len(out), docs=len({c.doc_id for c in out}),
            fallback=fallback_used, rejected_section=rejected_section,
            rejected_exact=rejected_exact, rejected_path=rejected_path,
            top_score=round(max((c.fallback_score for c in out), default=0.0), 4),
        )
        return out

    def _probe_body_fts(self, ctx: RouteContext, q: QueryPack) -> list[Candidate]:
        terms = q.positive_terms()
        if not terms:
            return []
        log_event(
            logger, "probe:body:start",
            route=ctx.route.get("label"), terms=len(terms),
            terms_preview=preview_items(terms, 12), top_k=BODY_FTS_TOP_K,
            conjunction=False,
        )
        hits = ctx.index.fts_body.search(
            terms, top_k=BODY_FTS_TOP_K, conjunction=False
        )
        fallback_used = False
        if not hits and len(terms) > 1:
            fallback_used = True
            for term in terms[:8]:
                hits.extend(ctx.index.fts_body.search([term], top_k=80))
            log_event(logger, "probe:body:fallback", route=ctx.route.get("label"),
                      per_term_top_k=80, terms_used=min(8, len(terms)))
        if not hits:
            log_event(logger, "probe:body:empty", route=ctx.route.get("label"))
            return []
        best: dict[str, tuple[float, dict]] = {}
        for hit in hits:
            key = str(hit.get("chunk_id") or hit.get("section_id") or "")
            score = float(hit.get("score") or 0.0)
            if key and (key not in best or score > best[key][0]):
                best[key] = (score, hit)
        max_score = max((v[0] for v in best.values()), default=0.0) or 1.0
        pointers = self._fetch_pointer_lines(
            ctx, [str(h.get("chunk_id")) for _, h in best.values() if h.get("chunk_id")]
        )
        sections = self._fetch_sections(
            ctx, [str(h.get("section_id")) for _, h in best.values() if h.get("section_id")]
        )
        out: list[Candidate] = []
        rejected_path = 0
        for _, (score, hit) in best.items():
            local_doc = str(hit.get("doc_id") or "")
            rel_path = ctx.rel_path(local_doc)
            if not rel_path:
                rejected_path += 1
                continue
            chunk_id = str(hit.get("chunk_id") or "")
            section_id = str(hit.get("section_id") or "")
            section = sections.get(section_id) or {}
            out.append(Candidate(
                route_index=ctx.route_index,
                doc_id=ctx.global_id(local_doc),
                local_doc_id=local_doc,
                rel_path=rel_path,
                section_id=section_id,
                chunk_id=chunk_id,
                start_line=int(hit.get("start_line") or 1),
                end_line=int(hit.get("end_line") or 1),
                header_line=int(pointers.get(chunk_id, 0)),
                header_path=str(section.get("header_path") or ""),
                first_sentence=str(section.get("first_sentence") or ""),
                structural=False,
                source_scores={"body_fts": min(1.0, score / max_score)},
                fallback_score=min(1.0, score / max_score),
            ))
        log_event(
            logger, "probe:body:done",
            route=ctx.route.get("label"), hits=len(hits), chunks=len(best),
            candidates=len(out), docs=len({c.doc_id for c in out}),
            fallback=fallback_used, rejected_path=rejected_path,
            top_score=round(max((c.fallback_score for c in out), default=0.0), 4),
        )
        return out

    def _fetch_sections(self, ctx: RouteContext, section_ids: list[str]) -> dict[str, dict]:
        if not section_ids:
            return {}
        rows = _fetch_rows_with_columns(
            ctx.index.section_table,
            _filter_in("section_id", section_ids[:400]),
            _section_columns(),
        )
        out = {str(r.get("section_id")): r for r in rows if r.get("section_id")}
        missing = [sid for sid in section_ids[:400] if sid not in out]
        for sid in missing[:50]:
            rows = _fetch_rows_with_columns(
                ctx.index.section_table, f"section_id = '{sid.replace(chr(39), chr(39)*2)}'",
                _section_columns(),
            )
            for row in rows:
                out[str(row.get("section_id"))] = row
        log_event(
            logger, "fetch:sections", level=logging.DEBUG,
            requested=len(section_ids), found=len(out),
            missing=len(section_ids[:400]) - len(out),
        )
        return out

    def _fetch_pointer_lines(self, ctx: RouteContext, chunk_ids: list[str]) -> dict[str, int]:
        if not chunk_ids:
            return {}
        rows = _fetch_rows_with_columns(
            ctx.index.pointer_table,
            _filter_in("chunk_id", chunk_ids[:400]),
            ["chunk_id", "header_line"],
        )
        out = {
            str(r.get("chunk_id")): int(r.get("header_line") or 0)
            for r in rows if r.get("chunk_id")
        }
        for chunk_id in chunk_ids[:400]:
            if chunk_id in out:
                continue
            rows = _fetch_rows_with_columns(
                ctx.index.pointer_table,
                f"chunk_id = '{chunk_id.replace(chr(39), chr(39)*2)}'",
                ["chunk_id", "header_line"],
            )
            for row in rows:
                out[str(row.get("chunk_id"))] = int(row.get("header_line") or 0)
        log_event(
            logger, "fetch:pointers", level=logging.DEBUG,
            requested=len(chunk_ids), found=len(out),
            missing=len(chunk_ids[:400]) - len(out),
        )
        return out

    @staticmethod
    def _exact_match(text: str, terms: list[str]) -> bool:
        lowered = (text or "").lower()
        return any(term.lower() in lowered for term in terms if term)

    # ------------------------------------------------------------------
    # 候选合并 / 还原 / rerank
    # ------------------------------------------------------------------
    def _merge_candidates(self, candidates: list[Candidate]) -> list[Candidate]:
        merged: dict[tuple, Candidate] = {}
        log_event(
            logger, "merge:start", candidates=len(candidates),
            docs=len({c.doc_id for c in candidates}),
            sections=len({(c.doc_id, c.section_id) for c in candidates if c.section_id}),
        )
        for candidate in candidates:
            existing = merged.get(candidate.key)
            if existing is None:
                merged[candidate.key] = candidate
                continue
            for source, score in candidate.source_scores.items():
                existing.source_scores[source] = max(
                    existing.source_scores.get(source, 0.0), score
                )
            existing.structural = existing.structural or candidate.structural
            existing.first_sentence = existing.first_sentence or candidate.first_sentence
            existing.header_path = existing.header_path or candidate.header_path
            existing.header_line = existing.header_line or candidate.header_line
            existing.fallback_score = max(existing.fallback_score, candidate.fallback_score)
        result = list(merged.values())
        log_event(
            logger, "merge:done", input_candidates=len(candidates),
            merged_candidates=len(result), merged_docs=len({c.doc_id for c in result}),
            collapsed=len(candidates) - len(result),
        )
        return result

    def _select_for_rerank(
        self,
        candidates: list[Candidate],
        q: QueryPack,
        known_doc_ids: set[str] | None = None,
        block_limit: int | None = None,
    ) -> list[Candidate]:
        limit = max(1, int(block_limit or RERANK_BLOCK_LIMIT))
        input_count = len(candidates)
        input_docs = len({c.doc_id for c in candidates})
        log_event(
            logger, "select:start", candidates=input_count, docs=input_docs,
            known_docs=len(known_doc_ids) if known_doc_ids else 0,
            block_limit=limit, per_doc=RERANK_PER_DOC,
        )
        # 第二跳只对首跳未出现的新文档做 rerank；首跳文档已有分数，
        # 重复 rerank 会把 hop1 从十几秒放大到几十秒。
        if known_doc_ids:
            new_candidates = [
                c for c in candidates if c.doc_id not in known_doc_ids
            ]
            if new_candidates:
                candidates = new_candidates
        known_filtered = input_count - len(candidates)
        by_doc: dict[str, list[Candidate]] = {}
        for candidate in candidates:
            by_doc.setdefault(candidate.doc_id, []).append(candidate)
        selected: list[Candidate] = []
        leftovers: list[Candidate] = []
        for items in by_doc.values():
            items.sort(key=lambda c: c.fallback_score, reverse=True)
            selected.extend(items[:RERANK_PER_DOC])
            leftovers.extend(items[RERANK_PER_DOC:])
        if len(selected) < limit:
            leftovers.sort(key=lambda c: c.fallback_score, reverse=True)
            selected.extend(leftovers[:limit - len(selected)])
        selected.sort(key=lambda c: c.fallback_score, reverse=True)
        selected = selected[:limit]
        self._restore_texts(selected)
        # 正文字面路要求“FTS 命中 + 原文精确子串校验”同时成立。
        terms = [t.lower() for t in q.positive_terms() if t]
        body_exact_dropped = 0
        if terms:
            before_exact = len(selected)
            selected = [
                c for c in selected
                if not ("body_fts" in c.source_scores and not any(t in c.text.lower() for t in terms))
            ]
            body_exact_dropped = before_exact - len(selected)
        log_event(
            logger, "select:done", input_candidates=input_count,
            input_docs=input_docs, known_filtered=known_filtered,
            selected=len(selected),
            selected_docs=len({c.doc_id for c in selected}),
            dropped=input_count - known_filtered - len(selected),
            body_exact_checked=bool(terms), body_exact_dropped=body_exact_dropped,
        )
        return selected

    def _restore_texts(self, candidates: list[Candidate]) -> None:
        contexts = self.contexts
        total_chars = 0
        empty = 0
        for candidate in candidates:
            ctx = contexts[candidate.route_index]
            text = ctx.read_lines(
                candidate.rel_path, candidate.start_line, candidate.end_line
            )
            if candidate.header_line and candidate.header_line < candidate.start_line:
                header = ctx.read_lines(
                    candidate.rel_path, candidate.header_line, candidate.header_line
                )
                if header:
                    text = header + "\n" + text
            if candidate.header_path:
                text = f"{candidate.header_path}\n{text}"
            candidate.text = truncate(text, 3000)
            total_chars += len(candidate.text)
            if not candidate.text:
                empty += 1
        log_event(
            logger, "restore:done", candidates=len(candidates),
            chars=total_chars, empty=empty, max_chars_per_candidate=3000,
        )

    @staticmethod
    def _fallback_score(candidate: Candidate) -> float:
        return max(candidate.source_scores.values(), default=candidate.fallback_score)

    def _rerank(self, candidates: list[Candidate], questions: list[str]) -> bool:
        if not candidates:
            return False
        questions = [q for q in questions[:MAX_QUESTIONS] if q]
        if not questions:
            return False
        texts = [candidate.text for candidate in candidates]
        log_event(
            logger, "rerank:start", blocks=len(candidates), questions=len(questions),
            question_preview=preview_items(questions, 2),
            text_chars=sum(len(t) for t in texts), score_mode=SCORE_MODE,
            hybrid_weight=HYBRID_WEIGHT,
        )
        max_scores = [0.0] * len(candidates)
        used = False
        for qi, question in enumerate(questions, 1):
            scores = batch_rerank_scores(question, texts)
            if scores is None:
                log_event(logger, "rerank:unavailable", level=logging.WARNING,
                          blocks=len(texts), question_index=qi,
                          question_preview=preview_text(question, 160))
                return False
            scores = normalize_scores(scores)
            used = True
            log_event(
                logger, "rerank:question", level=logging.DEBUG,
                question_index=qi, question_preview=preview_text(question, 160),
                blocks=len(scores), score_min=round(min(scores), 4),
                score_max=round(max(scores), 4),
            )
            for i, score in enumerate(scores[:len(max_scores)]):
                max_scores[i] = max(max_scores[i], score)
        hybrid_count = 0
        for candidate, score in zip(candidates, max_scores):
            candidate.rerank_score = float(score)
            candidate.fallback_score = self._fallback_score(candidate)
            if SCORE_MODE == "hybrid":
                # 自然语言问题里 BM25/向量精确命中是强信号；避免 rerank 把
                # 精确匹配但语义泛化的文档压到 Tier 1 之外。
                before = candidate.rerank_score
                candidate.rerank_score = max(
                    candidate.rerank_score,
                    HYBRID_WEIGHT * candidate.fallback_score,
                )
                if candidate.rerank_score > before:
                    hybrid_count += 1
        log_event(
            logger, "rerank:done", blocks=len(candidates),
            questions=len(questions), used=used,
            score_min=round(min(max_scores, default=0.0), 4),
            score_max=round(max(max_scores, default=0.0), 4),
            hybrid_count=hybrid_count,
        )
        return used

    # ------------------------------------------------------------------
    # 文档聚合 / S(d)
    # ------------------------------------------------------------------
    def _aggregate_docs(
        self, candidates: list[Candidate], q: QueryPack
    ) -> dict[str, DocScore]:
        terms = q.positive_terms()
        term_count = max(1, len(terms))
        rerank_used = any(c.rerank_score > 0 for c in candidates)
        log_event(
            logger, "aggregate:start", candidates=len(candidates),
            docs=len({c.doc_id for c in candidates}), terms=len(terms),
            term_count=term_count, rerank_used=rerank_used,
            hit_threshold=S_CHUNK_THRESHOLD,
        )
        grouped: dict[str, list[Candidate]] = {}
        for candidate in candidates:
            grouped.setdefault(candidate.doc_id, []).append(candidate)
        docs: dict[str, DocScore] = {}
        for doc_id, items in grouped.items():
            first = items[0]
            title = Path(first.rel_path).stem
            # 结构分
            structural = [c for c in items if c.structural]
            section_ids = {c.section_id for c in structural}
            n_file = 1 if structural else 0
            n_section = len(section_ids)
            n_first = sum(
                1 for c in structural
                if c.first_sentence and self._exact_match(c.first_sentence, terms)
            )
            raw = 1.5 * n_file + 1.2 * n_section + 1.0 * n_first
            s_struct = 1.0 - math.exp(-raw / term_count)
            # 正文分
            if rerank_used:
                effective = [c.rerank_score for c in items if c.rerank_score >= S_CHUNK_THRESHOLD]
            else:
                effective = [c.score for c in items if c.score > 0]
            effective.sort(reverse=True)
            s_body = 0.0
            if effective:
                s_body = 0.6 * effective[0]
                s_body += 0.4 * sum(
                    effective[k - 1] / k for k in range(2, min(6, len(effective)) + 1)
                )
            # 覆盖度
            haystack = " ".join([first.rel_path, *[c.text[:1200] for c in items[:3]]]).lower()
            covered = [t for t in terms if t.lower() in haystack]
            boost = min(2.0, 1.0 + 0.15 * max(0, len(covered) - 1))
            score = (0.7 * s_body + 0.3 * s_struct) * boost
            if any(x.lower() in first.rel_path.lower() for x in q.exclude if x):
                score *= 0.3
            docs[doc_id] = DocScore(
                route_index=first.route_index,
                doc_id=doc_id,
                local_doc_id=first.local_doc_id,
                rel_path=first.rel_path,
                title=title,
                candidates=sorted(items, key=lambda c: c.score, reverse=True),
                score=score,
                s_body=s_body,
                s_struct=s_struct,
                hit_count=len(effective),
                structural_section_ids=section_ids,
                structural_first_hits=n_first,
                coverage_terms=covered,
                char_count=sum(c.char_count for c in items),
            )
        if docs:
            scores = [d.score for d in docs.values()]
            log_event(
                logger, "aggregate:done", docs=len(docs),
                score_min=round(min(scores), 4), score_max=round(max(scores), 4),
                rerank_used=rerank_used,
            )
        return docs

    @staticmethod
    def _merge_docs(*groups: dict[str, DocScore], q: QueryPack) -> dict[str, DocScore]:
        """合并多跳文档集合：候选去重后按并集 terms 重新计算 S(d)。"""
        log_event(
            logger, "merge_docs:start", groups=len(groups),
            group_docs=[len(g) for g in groups],
            terms=len(q.positive_terms()),
        )
        merged: dict[str, DocScore] = {}
        for group in groups:
            for doc_id, doc in group.items():
                if doc_id not in merged:
                    merged[doc_id] = doc
                    continue
                existing = merged[doc_id]
                seen = {c.key for c in existing.candidates}
                existing.candidates.extend(c for c in doc.candidates if c.key not in seen)
                existing.structural_section_ids |= doc.structural_section_ids
                existing.structural_first_hits += doc.structural_first_hits
                existing.coverage_terms = list(set(existing.coverage_terms) | set(doc.coverage_terms))
        terms = q.positive_terms()
        term_count = max(1, len(terms))
        for doc in merged.values():
            rerank_used = any(c.rerank_score > 0 for c in doc.candidates)
            if rerank_used:
                effective = [
                    c.rerank_score for c in doc.candidates
                    if c.rerank_score >= S_CHUNK_THRESHOLD
                ]
            else:
                effective = [c.score for c in doc.candidates if c.score > 0]
            effective.sort(reverse=True)
            s_body = 0.0
            if effective:
                s_body = 0.6 * effective[0]
                s_body += 0.4 * sum(
                    effective[k - 1] / k for k in range(2, min(6, len(effective)) + 1)
                )
            raw = 1.5 * (1 if doc.structural_section_ids else 0)
            raw += 1.2 * len(doc.structural_section_ids)
            raw += 1.0 * doc.structural_first_hits
            s_struct = 1.0 - math.exp(-raw / term_count)
            covered = [
                t for t in terms
                if t.lower() in " ".join(
                    [doc.rel_path, *[c.text[:1200] for c in doc.candidates[:3]]]
                ).lower()
            ]
            boost = min(2.0, 1.0 + 0.15 * max(0, len(covered) - 1))
            doc.s_body = s_body
            doc.s_struct = s_struct
            doc.coverage_terms = covered
            doc.hit_count = len(effective)
            doc.score = (0.7 * s_body + 0.3 * s_struct) * boost
            doc.candidates.sort(key=lambda c: c.score, reverse=True)
        log_event(
            logger, "merge_docs:done", merged_docs=len(merged),
            docs_with_candidates=sum(1 for d in merged.values() if d.candidates),
            score_max=round(max((d.score for d in merged.values()), default=0.0), 4),
        )
        return merged

    # ------------------------------------------------------------------
    # 证据包 / A0
    # ------------------------------------------------------------------
    def _directory_map(self, docs: dict[str, DocScore], limit: int = 25) -> str:
        counts: dict[str, int] = {}
        samples: dict[str, list[str]] = {}
        for doc in docs.values():
            parts = Path(doc.rel_path).parts
            key = "/".join(parts[:2]) if len(parts) > 1 else (parts[0] if parts else "(root)")
            counts[key] = counts.get(key, 0) + 1
            samples.setdefault(key, [])
            if len(samples[key]) < 2:
                samples[key].append(doc.title)
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
        lines = [f"- {key}/ ({count} 篇) 例: {', '.join(samples[key])}" for key, count in ranked]
        if len(counts) > limit:
            lines.append(f"- …另有 {len(counts) - limit} 个目录未展开")
        return "\n".join(lines) or "(无命中目录)"

    def _build_evidence_pack(self, docs: dict[str, DocScore]) -> EvidencePack:
        budget = min(int(self.context_window * 0.30), EVIDENCE_TOKEN_LIMIT)
        ordered = sorted(docs.values(), key=lambda d: d.score, reverse=True)[:25]
        log_event(
            logger, "evidence:start", docs=len(docs), ordered=len(ordered),
            budget=budget, context_window=self.context_window,
            evidence_limit=EVIDENCE_TOKEN_LIMIT,
        )
        if not ordered:
            return EvidencePack("", 0, [])
        # 批量取骨架 sections
        section_rows: dict[str, list[dict]] = {}
        for ctx_index, ctx in enumerate(self.contexts):
            doc_keys = [d.local_doc_id for d in ordered if d.route_index == ctx_index]
            if not doc_keys:
                continue
            rows = _fetch_rows_with_columns(
                ctx.index.section_table,
                _filter_in("doc_key", doc_keys),
                _section_columns(),
            )
            for row in rows:
                section_rows.setdefault(str(row.get("doc_key")), []).append(row)
        parts: list[str] = []
        used_tokens = 0
        used_doc_ids: list[str] = []

        def add(text: str) -> bool:
            nonlocal used_tokens
            tokens = estimate_tokens(text)
            if used_tokens + tokens > budget:
                return False
            parts.append(text)
            used_tokens += tokens
            return True

        for doc in ordered:
            ctx = self.contexts[doc.route_index]
            header = (
                f"\n### [{doc.doc_id}] {doc.title}  "
                f"(score={doc.score:.3f}, hits={doc.hit_count})\n"
                f"path: {doc.rel_path}\n"
            )
            if not add(header):
                break
            used_doc_ids.append(doc.doc_id)
            # 静态骨架
            rows = section_rows.get(doc.local_doc_id, [])
            rows.sort(key=lambda r: int(r.get("start_line") or 0))
            skeleton_lines = []
            for row in rows[:40]:
                skeleton_lines.append(
                    f"- {row.get('header_path') or '(root)'} "
                    f"(L{row.get('start_line')}-{row.get('end_line')}) "
                    f"{truncate(str(row.get('first_sentence') or ''), 160)}"
                )
            add("".join(line + "\n" for line in skeleton_lines))
            # Top 3 命中块
            for candidate in doc.candidates[:3]:
                block = (
                    f"--- 命中 {candidate.section_id} L{candidate.start_line}-"
                    f"{candidate.end_line} ---\n"
                    f"{truncate(candidate.text, 1200)}\n"
                )
                if not add(block):
                    break

        # 第二阶段：高优膨胀
        for doc in ordered:
            ctx = self.contexts[doc.route_index]
            try:
                full = (ctx.pre_dir / doc.rel_path).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                continue
            full_tokens = estimate_tokens(full)
            if full_tokens <= 5000:
                add(f"\n### 全文 [{doc.doc_id}]\n{truncate(full, budget * 4)}\n")
            else:
                seen_sections: set[str] = set()
                for candidate in doc.candidates:
                    if candidate.section_id in seen_sections:
                        continue
                    seen_sections.add(candidate.section_id)
                    add(
                        f"\n### 命中章节 [{doc.doc_id}] {candidate.header_path}\n"
                        f"{truncate(candidate.text, 1600)}\n"
                    )
        text = "".join(parts)
        log_event(
            logger, "evidence:done", docs=len(used_doc_ids),
            tokens=used_tokens, budget=budget, chars=len(text),
            doc_preview=preview_items(used_doc_ids, 10),
            text_preview=preview_text(text, 160),
        )
        return EvidencePack(text, used_tokens, used_doc_ids)

    # ------------------------------------------------------------------
    # Tier / 渲染
    # ------------------------------------------------------------------
    @staticmethod
    def _apply_tiers(docs: dict[str, DocScore]) -> tuple[list[DocScore], list[DocScore], dict]:
        log_event(
            logger, "tier:start", docs=len(docs), tau_noise=TAU_NOISE,
            tier1_limit=TIER1_LIMIT, tier2_limit=TIER2_LIMIT,
        )

        def finish(tier1: list[DocScore], tier2: list[DocScore], diag: dict, reason: str):
            for doc in tier1:
                doc.tier = 1
            for doc in tier2:
                doc.tier = 2
            selected = [*tier1, *tier2]
            scores = [d.score for d in selected]
            log_event(
                logger, "tier:done", reason=reason, tier1=len(tier1), tier2=len(tier2),
                score_min=round(min(scores), 4) if scores else None,
                score_max=round(max(scores), 4) if scores else None,
                **diag,
            )
            return tier1, tier2, diag

        ordered = sorted(docs.values(), key=lambda d: d.score, reverse=True)
        filtered = [d for d in ordered if d.score >= TAU_NOISE]
        tau_fallback = False
        if not filtered and ordered:
            filtered = ordered[: min(10, len(ordered))]
            tau_fallback = True
        if len(filtered) < 10:
            return finish(filtered[:TIER1_LIMIT], [], {
                "elbow_cut": len(filtered),
                "filtered": len(filtered),
                "tau_fallback": tau_fallback,
            }, "small_candidate_set")
        scores = np.asarray([d.score for d in filtered], dtype=np.float64)
        if float(scores.max() - scores.min()) < 1e-9:
            return finish(filtered[:TIER1_LIMIT], filtered[TIER1_LIMIT:TIER1_LIMIT + TIER2_LIMIT], {
                "elbow_cut": TIER1_LIMIT,
                "filtered": len(filtered),
                "tau_fallback": tau_fallback,
            }, "flat_score_curve")
        x = np.arange(len(scores), dtype=np.float64) / max(1, len(scores) - 1)
        y = (scores - scores[-1]) / max(1e-9, scores[0] - scores[-1])
        distance = y - (1.0 - x)
        knee = int(np.argmax(distance))
        if distance[knee] < 0.05:
            cut = min(TIER1_LIMIT, len(filtered))
            reason = "no_elbow_cap"
        else:
            cut = min(max(1, knee + 1), TIER1_LIMIT)
            reason = "elbow"
        tier1 = filtered[:cut]
        tier2 = filtered[cut:cut + TIER2_LIMIT]
        return finish(tier1, tier2, {
            "elbow_cut": cut,
            "filtered": len(filtered),
            "knee_distance": round(float(distance[knee]), 4),
            "tau_fallback": tau_fallback,
        }, reason)

    def _render(
        self,
        q_orig: QueryPack,
        tier1: list[DocScore],
        tier2: list[DocScore],
        hop_records: list[HopRecord],
        *,
        degraded: bool,
        degraded_reason: str,
        a0_meta: dict,
        stats: dict,
    ) -> str:
        def render(max_sections: int, include_tier2: bool) -> str:
            lines: list[str] = ["# 知识库动态检索概览"]
            lines.append(f'> 🎯 检索问题："{q_orig.primary_question}"')
            lines.append("> 🔄 迭代分母收敛记录：")
            for rec in hop_records:
                qtext = " / ".join(rec.questions[:2])
                lines.append(
                    f'>   - 第 {rec.hop + 1} 跳 (Q{rec.hop}: "{qtext}") '
                    f"→ 召回 {rec.docs} 篇（新增 {rec.new_docs} 篇）"
                )
            candidate_pool = stats.get("candidate_pool", len(tier1) + len(tier2))
            shown_tier2 = len(tier2) if include_tier2 else stats['tier2']
            lines.append(
                f"> 📊 候选池统计：全库共 {stats['doc_count']} 篇，"
                f"候选池 {candidate_pool} 篇；"
                f"本次展示 Tier 1 {len(tier1)} 篇、Tier 2 {shown_tier2} 篇"
            )
            if degraded:
                lines.append(f"> ⚠️ 降级说明：{degraded_reason}")
            if a0_meta.get("hit_quality"):
                lines.append(f"> 🧠 A0 判定：{a0_meta['hit_quality']}")
            lines.append("")
            lines.append(f"## 一、Tier 1 候选池（共 {len(tier1)} 篇，"
                         "按原始问题挑选 3–10 篇精读，不必全读）")
            groups: dict[str, list[DocScore]] = {}
            for doc in tier1:
                parents = Path(doc.rel_path).parts[:-1]
                key = "/".join(parents) if parents else "(root)"
                groups.setdefault(key, []).append(doc)
            for group_key in sorted(groups):
                lines.append(f"├── [DIR] {group_key}/")
                for doc in sorted(groups[group_key], key=lambda d: d.score, reverse=True):
                    lines.append(
                        f"│   ├── [{doc.doc_id}] {doc.title}  "
                        f"(命中 {doc.hit_count} 处 | 综合分: {doc.score:.3f})"
                    )
                    shown = 0
                    for candidate in doc.candidates:
                        if shown >= max_sections:
                            break
                        marker = " 🔥" if candidate.score >= S_CHUNK_THRESHOLD else ""
                        block_hint = (
                            f"[命中 L{candidate.start_line}-L{candidate.end_line} | "
                            f"{max(0, candidate.end_line - candidate.start_line + 1)}行]"
                        )
                        lines.append(
                            f"│   │   ├── `{candidate.header_path or '(root)'}` "
                            f"(L{candidate.start_line}-L{candidate.end_line})"
                            f"{marker}{block_hint}"
                        )
                        shown += 1
                    if not doc.candidates:
                        lines.append("│   │   └── (无命中块，建议 read-doc 查看)")
            if include_tier2 and tier2:
                lines.append("")
                lines.append(f"## 二、Tier 2 边缘候选（共 {len(tier2)} 篇，"
                             "仅列命中位置，按需 read-doc，不必逐篇展开）")
                for doc in tier2:
                    hit_lines = ", ".join(
                        f"L{c.start_line}-L{c.end_line}" for c in doc.candidates[:3]
                    )
                    lines.append(
                        f"- [{doc.doc_id}] {doc.title} (score={doc.score:.3f}"
                        + (f"; 命中 {hit_lines}" if hit_lines else "") + ")"
                    )
            lines.append("")
            lines.append("## 三、覆盖披露")
            lines.append(
                f"- 查询词：{', '.join(q_orig.positive_terms()[:30]) or '(none)'}"
            )
            if a0_meta.get("unresolved_knowledge_gaps"):
                lines.append(
                    "- 未决缺口：" + "；".join(a0_meta["unresolved_knowledge_gaps"][:8])
                )
            if stats.get("candidate_pool") is not None:
                lines.append(
                    f"- 候选池：{stats['candidate_pool']} 篇（score ≥ TAU_NOISE）；"
                    f"未展示 {stats.get('omitted_candidates', 0)} 篇。"
                )
            if stats.get("tier1_truncated"):
                lines.append(
                    "- 说明：Tier 1 已按上限截断；更多候选未展开，"
                    "可用更具体的问题重新 resolve。"
                )
            if stats.get("tier2_truncated"):
                lines.append(
                    "- 说明：Tier 2 也已按上限截断；未展示的候选见上面的数量披露。"
                )
            lines.append(
                "- 选择建议：先根据原始问题、标题、命中行号和综合分从候选池中选 "
                "3–10 篇 read-doc 精读；**不要求逐篇读完 Tier 1**。"
            )
            lines.append(
                "- 说明：Tier 1 已列出候选文档及命中行号；"
                "Tier 2 为边缘候选，未逐篇展开。"
            )
            return "\n".join(lines)

        text = render(6, True)
        tokens = estimate_tokens(text)
        log_event(logger, "render:stage", attempt=1, max_sections=6,
                  include_tier2=True, chars=len(text), tokens=tokens,
                  limit=OUTPUT_TOKEN_LIMIT)
        if tokens <= OUTPUT_TOKEN_LIMIT:
            log_event(logger, "render:done", stage=1, chars=len(text), tokens=tokens,
                      text_preview=preview_text(text, 180))
            return text
        text = render(3, False)
        tokens = estimate_tokens(text)
        log_event(logger, "render:stage", attempt=2, max_sections=3,
                  include_tier2=False, chars=len(text), tokens=tokens,
                  limit=OUTPUT_TOKEN_LIMIT)
        if tokens <= OUTPUT_TOKEN_LIMIT:
            log_event(logger, "render:done", stage=2, chars=len(text), tokens=tokens,
                      text_preview=preview_text(text, 180))
            return text
        text = render(1, False)
        tokens = estimate_tokens(text)
        if tokens > OUTPUT_TOKEN_LIMIT:
            text += "\n\n> ⚠️ 输出已按 35K token 上限截断，Tier 2 未展开。"
        log_event(logger, "render:done", stage=3, chars=len(text), tokens=tokens,
                  truncated=tokens > OUTPUT_TOKEN_LIMIT,
                  text_preview=preview_text(text, 180))
        return text

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def run(self, q_orig: QueryPack) -> dict:
        started = time.perf_counter()
        log_event(
            logger, "resolve:start", question_preview=preview_items(q_orig.questions, 2),
            questions=len(q_orig.questions), terms=len(q_orig.terms),
            terms_preview=preview_items(q_orig.terms, 12),
            routes=len(self.contexts), static_routes=len(self.static_routes),
            doc_count=self.total_doc_count, context_window=self.context_window,
        )
        hop_records: list[HopRecord] = []
        selected0, docs0, diag0 = self._run_hop(q_orig, 0)
        hop_records.append(HopRecord(
            hop=0, questions=q_orig.questions, terms=q_orig.terms,
            docs=len(docs0), new_docs=len(docs0), candidates=len(selected0),
            rerank=diag0["rerank"], elapsed_ms=diag0["elapsed_ms"],
        ))
        all_docs = docs0
        degraded = False
        degraded_reason = ""
        a0_meta: dict = {}
        a0_tokens = 0
        hop_diags = [diag0]

        # 证据包 + A0
        directory_map = self._directory_map(docs0)
        evidence = self._build_evidence_pack(docs0)
        a0_timeout = float(os.environ.get("COSIGHTBOT_DYNAMIC_A0_TIMEOUT", "120"))
        log_event(
            logger, "a0:input", docs=len(docs0), evidence_docs=len(evidence.doc_ids),
            evidence_chars=len(evidence.text), evidence_tokens=evidence.tokens,
            directory_map_chars=len(directory_map), doc_count=self.total_doc_count,
            timeout_s=a0_timeout,
        )
        a0_payload, a0_error, a0_elapsed, a0_tokens = call_a0(
            q_orig, evidence.text,
            doc_count=self.total_doc_count,
            directory_map=directory_map,
            timeout=a0_timeout,
        )
        if a0_payload is None:
            degraded = True
            degraded_reason = a0_error or "A0 failed"
            log_event(logger, "degraded:a0", level=logging.WARNING, reason=degraded_reason)
        else:
            a0_meta = a0_payload
            q1 = a0_payload.get("next_queries_Q1") or {}
            q1_questions = [x for x in q1.get("sub_questions", []) if x]
            seen = {t.lower() for t in q_orig.positive_terms()}
            q1_terms = [
                t for t in q1.get("key_terms", [])
                if t and t.lower() not in seen and t.lower() not in {
                    x.lower() for x in q_orig.exclude
                }
            ]
            stop = (
                a0_payload.get("hit_quality") == "FULL_HIT"
                and (HOP2_SKIP_FULL_HIT or not a0_payload.get("unresolved_knowledge_gaps"))
            )
            log_event(
                logger, "a0:decision", quality=a0_payload.get("hit_quality"),
                gaps=len(a0_payload.get("unresolved_knowledge_gaps") or []),
                q1_questions=len(q1_questions), q1_terms=len(q1_terms),
                hop2_skip_full_hit=HOP2_SKIP_FULL_HIT,
                hop2_max_questions=HOP2_MAX_QUESTIONS,
                hop2_new_docs_only=HOP2_NEW_DOCS_ONLY,
                hop2_rerank_blocks=HOP2_RERANK_BLOCKS,
                stop=stop,
                q1_questions_preview=preview_items(q1_questions, 2),
                q1_terms_preview=preview_items(q1_terms, 12),
            )
            if stop:
                log_event(logger, "hop:1:stop", reason="FULL_HIT",
                          quality=a0_payload.get("hit_quality"),
                          gaps=len(a0_payload.get("unresolved_knowledge_gaps") or []))
            elif not q1_questions and not q1_terms:
                log_event(logger, "hop:1:stop", reason="empty_Q1")
            else:
                q1_pack = QueryPack(
                    questions=(
                        q1_questions[:max(1, HOP2_MAX_QUESTIONS)]
                        or [q_orig.primary_question]
                    ),
                    terms=q1_terms,
                    entities=q_orig.entities,
                    constraints=q_orig.constraints,
                    identifiers=q_orig.identifiers,
                    exclude=q_orig.exclude,
                )
                try:
                    selected1, docs1, diag1 = self._run_hop(
                        q1_pack, 1,
                        known_doc_ids=set(docs0) if HOP2_NEW_DOCS_ONLY else None,
                        rerank_block_limit=HOP2_RERANK_BLOCKS,
                    )
                    new_docs = len(set(docs1) - set(docs0))
                    hop_records.append(HopRecord(
                        hop=1, questions=q1_pack.questions, terms=q1_pack.terms,
                        docs=len(docs1), new_docs=new_docs,
                        candidates=len(selected1), rerank=diag1["rerank"],
                        elapsed_ms=diag1["elapsed_ms"],
                        a0_quality=a0_payload.get("hit_quality", ""),
                    ))
                    hop_diags.append(diag1)
                    all_docs = self._merge_docs(docs0, docs1, q=QueryPack(
                        questions=[*q_orig.questions, *q1_pack.questions],
                        terms=list(dict.fromkeys([*q_orig.terms, *q1_terms])),
                        entities=q_orig.entities, constraints=q_orig.constraints,
                        identifiers=q_orig.identifiers, exclude=q_orig.exclude,
                    ))
                except DynamicIndexError:
                    raise
                except Exception as exc:
                    degraded = True
                    degraded_reason = f"hop2 failed: {type(exc).__name__}: {exc}"
                    log_event(logger, "degraded:hop2", level=logging.ERROR,
                              error=degraded_reason, exc_info=True)

        tier1, tier2, tier_diag = self._apply_tiers(all_docs)
        candidate_pool = int(tier_diag.get("filtered", len(tier1) + len(tier2)))
        stats = {
            "doc_count": self.total_doc_count,
            "tier1": len(tier1),
            "tier2": len(tier2),
            "candidate_pool": candidate_pool,
            "tier1_truncated": candidate_pool > len(tier1),
            "tier2_truncated": candidate_pool > len(tier1) + len(tier2),
            "omitted_candidates": max(0, candidate_pool - len(tier1) - len(tier2)),
            "hops": len(hop_records),
            "terms": q_orig.positive_terms(),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "a0_tokens": a0_tokens,
            "rerank": any(d.get("rerank") for d in hop_diags),
        }
        log_event(
            logger, "resolve:tiers", doc_count=stats["doc_count"],
            tier1=stats["tier1"], tier2=stats["tier2"],
            candidate_pool=stats["candidate_pool"],
            tier1_truncated=stats["tier1_truncated"],
            tier2_truncated=stats["tier2_truncated"],
            omitted_candidates=stats["omitted_candidates"],
            hops=stats["hops"], degraded=degraded,
            degraded_reason=degraded_reason or None,
        )
        merged = self._render(
            q_orig, tier1, tier2, hop_records,
            degraded=degraded, degraded_reason=degraded_reason,
            a0_meta=a0_meta, stats=stats,
        )
        log_event(
            logger, "resolve:rendered", merged_chars=len(merged),
            merged_tokens=estimate_tokens(merged),
            merged_preview=preview_text(merged, 200),
            tier1=stats["tier1"], tier2=stats["tier2"],
        )
        diagnostics = {
            "hops": hop_diags,
            "tier": tier_diag,
            "a0": {
                "quality": a0_meta.get("hit_quality"),
                "gaps": a0_meta.get("unresolved_knowledge_gaps", []),
                "intermediate_result_A": truncate(
                    a0_meta.get("intermediate_result_A", ""), 1200
                ),
                "error": a0_error if a0_payload is None else "",
                "elapsed_ms": a0_elapsed,
                "evidence_tokens": evidence.tokens,
                "evidence_docs": evidence.doc_ids[:10],
            },
            "selected_docs": [
                {
                    "doc_id": d.doc_id, "rel_path": d.rel_path,
                    "score": round(d.score, 4), "tier": d.tier,
                    "hits": d.hit_count,
                }
                for d in [*tier1, *tier2]
            ] if self.debug else [],
        }
        log_event(
            logger, "resolve:done",
            doc_count=stats["doc_count"], tier1=stats["tier1"],
            tier2=stats["tier2"], candidate_pool=stats["candidate_pool"],
            tier1_truncated=stats["tier1_truncated"],
            tier2_truncated=stats["tier2_truncated"],
            omitted_candidates=stats["omitted_candidates"],
            hops=stats["hops"], degraded=degraded,
            degraded_reason=degraded_reason or None,
            elapsed_ms=stats["elapsed_ms"], a0_tokens=stats["a0_tokens"],
            merged_chars=len(merged), merged_preview=preview_text(merged, 160),
        )
        return {
            "ready": True,
            "merged_overview": merged,
            "stats": stats,
            "degraded": degraded,
            "degraded_reason": degraded_reason or None,
            "error_code": None,
            "diagnostics": diagnostics,
        }
