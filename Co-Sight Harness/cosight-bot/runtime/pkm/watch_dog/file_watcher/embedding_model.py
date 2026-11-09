#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立的 Embedding 和 Rerank 模型

仅依赖 requests + llama_index.core。
"""
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import logging
import os
import time
import requests
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle

logger = logging.getLogger("file_watcher")

# API Configuration for Embedding and Rerank
# 端点/密钥只从环境变量读取（安装目录 .env 由安装器注入，见 design prod-outside §4.3）。
# 不再提供任何硬编码默认：未配置时向量入库由 handler.ingest_one_md 整体跳过，
# 查询侧（rerank）按"服务不可用"降级处理。
EMBEDDING_API_URL = os.environ.get("COSIGHTBOT_EMBEDDING_API_URL")
EMBEDDING_API_KEY = os.environ.get("COSIGHTBOT_EMBEDDING_API_KEY")
RERANK_API_URL = os.environ.get("COSIGHTBOT_RERANK_API_URL")
# OpenAI embeddings 协议兼容：设置后请求体带 model 字段（标准 OpenAI /v1/embeddings
# 语义）；不设置则保持 BGE 风格请求体（无 model 字段）。
EMBEDDING_MODEL = os.environ.get("COSIGHTBOT_EMBEDDING_MODEL")


def embedding_configured() -> bool:
    """向量入库是否已配置（COSIGHTBOT_EMBEDDING_API_URL 存在）。

    读取时实时查环境变量（而非模块级常量），保证测试 monkeypatch env 后生效。
    未配置时入库路径应整体跳过 insert_nodes，不发起任何网络连接。
    """
    return bool(os.environ.get("COSIGHTBOT_EMBEDDING_API_URL"))

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64

# Embedding 请求超时（双参：connect/read），env 可覆盖。
# 原来 timeout=300 单值，模型 hang 时会拖满 300s；改 (connect=3, read=60)
# 并由上层 P0 超时层（per-file / task-hard）兜底，避免长卡。
EMBED_CONNECT_TIMEOUT = float(os.environ.get("COSIGHTBOT_EMBEDDING_CONNECT_TIMEOUT", "3"))
EMBED_READ_TIMEOUT = float(os.environ.get("COSIGHTBOT_EMBEDDING_READ_TIMEOUT", "60"))

# 重试策略（env 可覆盖）：可重试错误（429/5xx/网关返回的无效响应）指数退避；
# 超时/连接错误（服务端容量问题）原地重试 EMBED_TIMEOUT_RETRIES 次后批次拆半
# 递归；其余 4xx（请求内容问题，如毒 chunk 超限）盲重试无意义，直接进逐条探针。
EMBED_MAX_ATTEMPTS = max(1, int(os.environ.get("COSIGHTBOT_EMBEDDING_MAX_ATTEMPTS", "4")))
EMBED_RETRY_BACKOFF: Tuple[float, ...] = tuple(
    float(x)
    for x in os.environ.get("COSIGHTBOT_EMBEDDING_RETRY_BACKOFF", "2,5,15").split(",")
    if x.strip()
)

# 单条输入字符数硬上限（env 可覆盖）：llama_index 会把 file_path 等元数据拼进
# 待 embed 文本，超长输入被服务端 400 拒绝（确定性失败，重试无用）。BGE 官方
# 语义本就是 max_tokens 截断，该服务端选择了拒绝而非截断，因此在客户端截。
# 截断只影响向量计算，chunk 原文完整入 LanceDB。
EMBED_MAX_INPUT_CHARS = max(
    1000, int(os.environ.get("COSIGHTBOT_EMBEDDING_MAX_INPUT_CHARS", "7800"))
)

# 单次请求的最大文本条数（env 可覆盖）。BGE 网关对超大批次会挂起且不返回
# 任何响应（实测：400 字文本 256 条正常、300 条挂起；7800 字长文本 100 条 4s、
# 200 条挂起），只能等 read timeout 兜底。统一在客户端分批，所有调用方受益。
EMBED_MAX_BATCH_TEXTS = max(
    1, int(os.environ.get("COSIGHTBOT_EMBEDDING_MAX_BATCH_TEXTS", "100"))
)

# 超时/连接错误的同尺寸重试次数（env 可覆盖）。超时说明是服务端容量问题，
# 同尺寸盲重试大概率全挂（20260922 故障日志：4 次 attempt 全超时），默认只
# 原地重试 1 次防瞬时抖动，仍失败则批次拆半递归（100→50→25→…→逐条）。
EMBED_TIMEOUT_RETRIES = max(
    0, int(os.environ.get("COSIGHTBOT_EMBEDDING_TIMEOUT_RETRIES", "1"))
)


class EmbeddingServiceError(RuntimeError):
    """Embedding 服务不可用或返回了无效结果。"""


def _is_retryable_embedding_error(exc: Exception) -> bool:
    """判断 embedding 请求失败是否值得退避重试。

    可重试：429、5xx、超时、连接错误、响应结构无效（网关/LB 抽风返回错误页
    是常见形态）。不可重试：其余 4xx（如 400——多为批次中某条文本超限/非法，
    整批重试多少次都一样）。
    """
    if isinstance(exc, EmbeddingServiceError):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = exc.response.status_code if exc.response is not None else 0
        return status == 429 or status >= 500
    return isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))


def _describe_text(text: str) -> str:
    """毒 chunk 诊断摘要：长度 + md5 前缀 + 内容预览（换行压平）。"""
    digest = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:8]
    preview = text[:60].replace("\n", "\\n")
    return f"len={len(text)} md5={digest} preview={preview!r}"


def _probe_poison_texts(
    texts: List[str], headers: dict
) -> Tuple[Optional[List[List[float]]], str]:
    """整批被 4xx 拒绝后逐条探针定位。

    - 全部单条成功：批次本身被网关误拒（压力下偶发），返回逐条向量——
      内容与整批请求完全等价，无损恢复，不是兜底伪造。
    - 存在单条失败：返回 (None, 诊断串)，指出毒 chunk 的序号/长度/预览。

    仅在失败路径触发；单条请求的语义与整批一致，只是多几次 RTT。
    """
    embeddings: List[List[float]] = []
    failures: List[str] = []
    for i, text in enumerate(texts):
        try:
            probe_payload = {"input": text}
            if EMBEDDING_MODEL:
                probe_payload["model"] = EMBEDDING_MODEL
            response = requests.post(
                EMBEDDING_API_URL, headers=headers, json=probe_payload,
                timeout=(EMBED_CONNECT_TIMEOUT, EMBED_READ_TIMEOUT), proxies=None,
            )
            response.raise_for_status()
            embeddings.append(
                OnlineBGEEmbedding._parse_embeddings(response.json(), expected_count=1)[0]
            )
        except Exception as e:
            failures.append(f"text[{i}] ({_describe_text(text)}): {e}")
            embeddings.append([])
    if failures:
        return None, "; poison text(s): " + " | ".join(failures)
    logger.warning(
        "Embedding API rejected the batch but per-text probe all succeeded "
        "(%d texts) — 网关误拒整批，使用逐条结果继续。", len(texts)
    )
    return embeddings, ""


def _truncate_text(text: str) -> str:
    """单条输入超 EMBED_MAX_INPUT_CHARS 时截断（loud warning，可定位来源）。"""
    if len(text) <= EMBED_MAX_INPUT_CHARS:
        return text
    digest = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:8]
    logger.warning(
        f"Embedding input truncated: {len(text)} -> {EMBED_MAX_INPUT_CHARS} chars "
        f"(md5={digest} preview={text[:60].replace(chr(10), ' ')!r})；"
        f"chunk 原文完整入库，仅向量按截断后文本计算"
    )
    return text[:EMBED_MAX_INPUT_CHARS]


def _truncate_payload(payload: dict) -> dict:
    """对 payload["input"]（str 或 list[str]）逐条应用输入上限。"""
    inp = payload.get("input")
    if isinstance(inp, str):
        truncated = _truncate_text(inp)
        if truncated is not inp:
            return {**payload, "input": truncated}
        return payload
    if isinstance(inp, list):
        new_list = [_truncate_text(t) if isinstance(t, str) else t for t in inp]
        return {**payload, "input": new_list}
    return payload


def _request_embeddings(payload: dict, expected_count: Optional[int]) -> List[List[float]]:
    """POST embedding API：分类重试（退避） + 4xx 整批失败逐条探针。返回向量列表。

    重试仍是对同一批次的整体重试（非逐条）；最坏 attempts × read_timeout +
    退避总和，由上层 per-file / task-hard 超时兜底，不会长卡。
    """
    if not EMBEDDING_API_URL:
        raise EmbeddingServiceError(
            "Embedding API 未配置（缺少 COSIGHTBOT_EMBEDDING_API_URL），跳过向量请求"
        )
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {EMBEDDING_API_KEY}"}
    # OpenAI embeddings 协议兼容：注入 model 字段（COSIGHTBOT_EMBEDDING_MODEL 设置时）
    if EMBEDDING_MODEL and "model" not in payload:
        payload = {**payload, "model": EMBEDDING_MODEL}
    payload = _truncate_payload(payload)
    last_exc: Optional[Exception] = None
    attempt = 0
    timeout_retries_left = EMBED_TIMEOUT_RETRIES
    for attempt in range(1, EMBED_MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                EMBEDDING_API_URL, headers=headers, json=payload,
                timeout=(EMBED_CONNECT_TIMEOUT, EMBED_READ_TIMEOUT), proxies=None,
            )
            response.raise_for_status()
            return OnlineBGEEmbedding._parse_embeddings(response.json(), expected_count=expected_count)
        except Exception as e:
            last_exc = e
            if not _is_retryable_embedding_error(e) or attempt >= EMBED_MAX_ATTEMPTS:
                break
            if isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
                if timeout_retries_left <= 0:
                    break  # 容量问题不再同尺寸盲重试，下方拆半
                timeout_retries_left -= 1
            wait = EMBED_RETRY_BACKOFF[min(attempt - 1, len(EMBED_RETRY_BACKOFF) - 1)]
            logger.warning(
                f"Embedding API attempt {attempt}/{EMBED_MAX_ATTEMPTS} failed "
                f"({type(e).__name__}: {e}); retrying in {wait}s"
            )
            time.sleep(wait)

    texts = payload.get("input")

    # 失败收尾（超时/连接错误）：服务端容量问题，批次拆半递归（100→50→…→1）。
    # 拆到单条仍超时则走末尾统一异常上抛（触发上层熔断），不静默。
    if (
        isinstance(last_exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))
        and isinstance(texts, list)
        and len(texts) > 1
    ):
        mid = len(texts) // 2
        logger.warning(
            f"Embedding API timed out on batch of {len(texts)} texts; "
            f"splitting into {mid} + {len(texts) - mid} and retrying"
        )
        return _request_embeddings(
            {"input": texts[:mid]}, expected_count=mid
        ) + _request_embeddings(
            {"input": texts[mid:]}, expected_count=len(texts) - mid
        )

    # 失败收尾（4xx）：batch 输入的逐条探针定位毒 chunk（或确认是网关误拒）。
    # 探针全部成功则无损返回逐条结果；否则诊断信息随异常抛出，不静默跳过。
    if (
        isinstance(last_exc, requests.exceptions.HTTPError)
        and last_exc.response is not None
        and 400 <= last_exc.response.status_code < 500
        and last_exc.response.status_code != 429
        and isinstance(texts, list)
        and len(texts) > 1
    ):
        probed, diagnosis = _probe_poison_texts(texts, headers)
        if probed is not None:
            return probed
        raise EmbeddingServiceError(
            f"Embedding API rejected the batch (HTTP {last_exc.response.status_code}){diagnosis}"
        ) from last_exc
    raise EmbeddingServiceError(
        f"Embedding API failed after {attempt} attempt(s): {last_exc}"
    ) from last_exc


class OnlineBGEEmbedding(BaseEmbedding):
    """在线 BGE Embedding 模型，调用远程 API 生成向量。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(embed_batch_size=4, **kwargs)

    @staticmethod
    def _parse_embeddings(payload: Any, expected_count: Optional[int] = None) -> List[List[float]]:
        """校验 Embedding API 响应，禁止用伪造向量继续建库。"""
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise EmbeddingServiceError("Embedding API returned an invalid response")

        embeddings = []
        for item in payload["data"]:
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise EmbeddingServiceError("Embedding API returned an invalid embedding item")
            vector = item["embedding"]
            if not vector or not all(isinstance(value, (int, float)) for value in vector):
                raise EmbeddingServiceError("Embedding API returned an empty or invalid vector")
            embeddings.append(vector)

        if expected_count is not None and len(embeddings) != expected_count:
            raise EmbeddingServiceError(
                f"Embedding API returned {len(embeddings)} vectors for {expected_count} texts"
            )
        if not embeddings:
            raise EmbeddingServiceError("Embedding API returned no vectors")
        return embeddings

    def _get_query_embedding(self, query: str) -> List[float]:
        return self._get_text_embedding(query)

    def _get_text_embedding(self, text: str) -> List[float]:
        try:
            logger.debug(f"Embedding API: Calling for text length {len(text)}")
            return _request_embeddings({"input": text}, expected_count=1)[0]
        except EmbeddingServiceError:
            raise
        except Exception as e:
            logger.error(f"Embedding API failed: {e}")
            raise EmbeddingServiceError(f"Embedding API failed: {e}") from e

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        try:
            logger.debug(f"Embedding API: Calling batch for {len(texts)} texts")
            if len(texts) <= EMBED_MAX_BATCH_TEXTS:
                return _request_embeddings({"input": texts}, expected_count=len(texts))
            # 超大批次按 EMBED_MAX_BATCH_TEXTS 切片依次请求，避免网关挂起。
            vectors: List[List[float]] = []
            for i in range(0, len(texts), EMBED_MAX_BATCH_TEXTS):
                sub = texts[i:i + EMBED_MAX_BATCH_TEXTS]
                vectors.extend(
                    _request_embeddings({"input": sub}, expected_count=len(sub))
                )
                logger.debug(
                    f"Embedding API: sub-batch progress {len(vectors)}/{len(texts)}"
                )
            return vectors
        except EmbeddingServiceError:
            raise
        except Exception as e:
            logger.error(f"Batch Embedding API failed: {e}")
            raise EmbeddingServiceError(f"Batch Embedding API failed: {e}") from e

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return self._get_text_embedding(text)


class OnlineBGERerank(BaseNodePostprocessor):
    """在线 BGE Rerank 模型，调用远程 API 对节点重新排序。"""

    top_n: int = 20

    def _postprocess_nodes(self, nodes: List[NodeWithScore], query_bundle: Optional[QueryBundle] = None) -> List[NodeWithScore]:
        if query_bundle is None or not nodes:
            return nodes
        if not RERANK_API_URL:
            logger.info("Rerank API 未配置（缺少 COSIGHTBOT_RERANK_API_URL），跳过重排")
            return nodes[:self.top_n]

        query = query_bundle.query_str
        texts = [node.get_content() for node in nodes]
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {EMBEDDING_API_KEY}"}
        payload = {"query": query, "documents": texts,
                   "model": os.environ.get("COSIGHTBOT_RERANK_MODEL", "reranker")}

        try:
            logger.debug(f"Rerank API: Calling for {len(nodes)} nodes")
            response = requests.post(RERANK_API_URL, headers=headers, json=payload, timeout=300, proxies=None)
            res_json = response.json()
            results = res_json.get("results", []) if isinstance(res_json, dict) else res_json

            if not isinstance(results, list):
                logger.debug(f"Rerank API returned unexpected format: {type(results)}")
                return nodes[:self.top_n]

            new_nodes = []
            for item in results:
                if isinstance(item, dict):
                    idx = item.get("index")
                    score = item.get("relevance_score") or item.get("score")
                    if idx is not None and score is not None:
                        node = nodes[idx]
                        node.score = score
                        new_nodes.append(node)

            logger.debug(f"Reranked {len(new_nodes)} nodes.")
            return new_nodes[:self.top_n] if new_nodes else nodes[:self.top_n]
        except Exception as e:
            logger.error(f"Rerank API failed: {e}")
            return nodes[:self.top_n]


def batch_rerank_scores(
    query: str, documents: List[str], timeout: float = 120.0
) -> Optional[List[float]]:
    """对一批文本做 rerank，返回与 ``documents`` 对齐的分数。

    - 未配置 ``COSIGHTBOT_RERANK_API_URL``、请求失败或响应格式非法 → None
      （调用方按 rerank=false 降级，保留向量/BM25 分数）；
    - 返回值顺序与输入严格对齐；服务端未返回的条目记 0。
    """
    url = os.environ.get("COSIGHTBOT_RERANK_API_URL")
    if not url or not documents:
        return None
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.environ.get('COSIGHTBOT_EMBEDDING_API_KEY', '')}",
    }
    # 服务端对超大批次会读超时；按小批分片请求，结果按全局偏移对齐。
    max_batch = max(1, int(os.environ.get("COSIGHTBOT_RERANK_MAX_BATCH", "200")))
    scores = [0.0] * len(documents)
    matched_total = 0
    for offset in range(0, len(documents), max_batch):
        batch = documents[offset:offset + max_batch]
        payload = {
            "query": query,
            "documents": batch,
            "model": os.environ.get("COSIGHTBOT_RERANK_MODEL", "reranker"),
        }
        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=timeout, proxies=None
            )
            response.raise_for_status()
            res_json = response.json()
            results = (
                res_json.get("results", []) if isinstance(res_json, dict) else res_json
            )
            if not isinstance(results, list):
                return None
            matched_batch = 0
            for item in results:
                if not isinstance(item, dict):
                    continue
                idx = item.get("index")
                score = item.get("relevance_score", item.get("score"))
                if (
                    isinstance(idx, int)
                    and 0 <= idx < len(batch)
                    and score is not None
                ):
                    scores[offset + idx] = float(score)
                    matched_batch += 1
            if not matched_batch:
                return None
            matched_total += matched_batch
            logger.debug(
                f"Rerank API: batch {offset}-{offset + len(batch)} "
                f"of {len(documents)} ok"
            )
        except Exception as e:
            logger.warning(
                f"Rerank API failed at batch {offset}-{offset + len(batch)} "
                f"of {len(documents)}: {type(e).__name__}: {e}"
            )
            return None
    return scores if matched_total else None
