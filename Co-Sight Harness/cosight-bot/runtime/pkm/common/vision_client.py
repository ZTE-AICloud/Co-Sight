#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多模态图片识别客户端（OpenAI 协议 + 多图批量 + 并发）。

供 doc_image_extractor 在预处理阶段识别 PDF/Word 中的图片：
  - scanned（扫描件）：整页完整 OCR（SCAN_PAGE_OCR_PROMPT）
  - mixed（图文混排）：内嵌图 50-100 字概括（INLINE_IMAGE_SUMMARY_PROMPT）

参考实现：OCR benchmark 的 m3_client.py / run_eval_for_m3.py（基于 m3 系列模型实测验证）。

关键约定：
  - 🚨 请求 payload 中【完全不出现 max_tokens 字段】（也不设默认值），
    输出长度由模型/服务端自行决定，避免整页 OCR 长文被截断。
  - 每 VISION_BATCH_SIZE 张图合并为一次 API 调用（多图 content 数组）。
  - 批次之间用 ThreadPoolExecutor 并发（VISION_CONCURRENCY），提高文档处理效率。
  - 多图响应按 === 图 N === 等分隔标记拆分；拆不齐的图自动降级为单图重试。
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

# Logger：复用 skill 的 cosight-sync logger（写 {skill_root}/logs/cosight-sync.log）。
#
# 之前用 logging.getLogger("common.vision_client") 是独立 logger，没有 handler；
# 日志会走 root → stderr 被吞掉，导致 OCR 阶段长时间完全静默。
# 把日志接到 cosight-sync 的 sync.log，才能看到每批 OCR 耗时。
# logger_util 不可用时 fallback 回独立 logger（不影响主流程，只是 OCR 日志走 stderr）。
try:
    from logger_util import get_logger as _skill_get_logger  # type: ignore[import-not-found]
    logger = _skill_get_logger("cosight-sync")
except Exception:  # noqa: BLE001 - 非 skill 上下文，logger_util 不可用
    logger = logging.getLogger("common.vision_client")

# ---------------------------------------------------------------------------
# 常量（与 feature-record/pdf_word_image_vision_feature_record.md §10 对齐）
# ---------------------------------------------------------------------------

# 单次 API 调用的图片数（benchmark 实测 5 张约 3.45x 加速，
# 但单批输出更长时整体耗时与失败风险上升；当前改为 3 张以换取
# 更短的响应窗口与更低的分隔标记错位概率 —— 仍由单图降级重试兜底）
VISION_BATCH_SIZE = 3
# 单文档内并发批次数（与 preprocessor 文件级并发 max_workers=2 相乘，
# 最坏 6 个并发请求；服务端限流时优先调小本值）
VISION_CONCURRENCY = 3
# 多个 batch 并发启动时，每个 batch 之间间隔多久（错峰避免服务端压力峰值）。
# 压测发现 m3 系列模型在 3 batch 同时启动时几乎 100% 概率触发服务端整体 hang
# （3 轮全部 11/11 timeout 满 300s）；加 2 秒间隔后 hang 率降到 0%（3/3 全部
# 在 50-176s 内完成）。间隔期间服务端有时间消化前一个请求，避免资源争抢。
#
# 但 2 秒 × 150 batch = 300 秒的纯 sleep 占比过大（实际项目 max_depth=1 跑
# 9 pages × ~50 imgs = ~450 imgs → 150 批，8 分钟里 5 分钟是空等）。
# 折中：前 VISION_TAPER_BATCHES 个 batch 走全间隔（避开"3 个 worker 同
# 时刻首请求 → hang"），后续 batch 走短间隔（executor 池已满，新提交自然
# 进队列排队，不会同时打服务端）。
BATCH_START_DELAY = 2.0
# 前 N 个 batch 走 BATCH_START_DELAY（2s），仅这几个能触发"3 worker 同
# 时刻首请求"的竞争场景。VISION_CONCURRENCY=3 时设 3，正好覆盖首批。
VISION_TAPER_BATCHES = VISION_CONCURRENCY
# 后续 batch 的间隔：从 2s 降到 0.3s，给服务端留 1/7 的喘息时间。
# 150 批 × 0.3s = 45s 纯 sleep，比原来 300s 减少 255s。
BATCH_POST_TAPER_DELAY = 0.3
# 流式响应"无数据超时"（秒）：服务端开始吐 token 后，若连续 N 秒没有任何
# 数据，认为 hang，立即 abort。原来 60s → 20s：服务端接受连接但不响应时
# select 能更早 raise TimeoutError，避免被 urlopen 整体 60s 阻塞拖到最后。
# 压测参考：单 batch 成功时 30-60s 有持续输出；20s 内肯定有新数据，
# 20s 没数据即可判 hang。Hang 时省 40s × N 张图 × 重试次数。
VISION_STREAM_NO_DATA_TIMEOUT = 20.0
# 单次 API 调用超时（urlopen 整体）。
# 2026-07-27 压测发现 hang 时 urlopen 会等到整体 timeout 才 raise；
# 原来 300s 时 hang 一个 5 图 batch + 5 张单图降级重试共 30 分钟才放弃。
# 改 60s：hang 时单图最坏 2 分钟（含 1 次重试），整批 + 单图降级共
# ~3 分钟。成功路径 37-63s 不受影响。
VISION_TIMEOUT = 60.0
# 单次 OCR 调用（含重试）的累计总超时（秒）。
# 关键：堵住"涓流响应"无限挂起--服务端每隔 <VISION_STREAM_NO_DATA_TIMEOUT
# 吐一小段 SSE 但永不 [DONE] 时，select 无数据超时不会触发、urlopen 整体
# 超时也不会触发（每次 recv 都在 <20s 内返回）。加一个跨整个调用的 wall-clock
# 上限，到点即 raise TimeoutError。成功路径 37-63s 不受影响（120s 留足余量）。
# env 可覆盖（测试时缩短）。
VISION_TOTAL_TIMEOUT = float(os.environ.get("COSIGHTBOT_VISION_TOTAL_TIMEOUT", "120"))
# 采样温度（沿用 benchmark）
VISION_TEMPERATURE = 0.3

# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

# scanned 整页 OCR：原样复用 run_eval_for_m3.py 的 M3_TEXT_PROMPT（139-146 行）+ 末尾加标题规则
SCAN_PAGE_OCR_PROMPT = """你是一个专业的 OCR + 文档理解助手。请用清晰的中文/英文描述图片里所有可见的文字和图形内容。

输出格式（Markdown）：
- 如果是文字内容：直接输出文字（保留原始换行、标点）
- 如果是图表/示意图：先描述图形结构，再用列表/表格列出文字内容
- 如果是表格：输出 markdown 表格
- 如果是架构图 / 拓扑图 / 模块关系图 / 流程图 / 系统框图：请用**形象化的框线结构**还原原图，优先使用 Unicode 框线字符（如 ┌─┐│└┘├┤┬┴┼ ）画出方框，模块名放在框内，连接关系用箭头（→ / ← / ↑ / ↓ ）表示，尽量保持原图的层级与布局
- 不要输出"以下是..."这类废话，直接给内容

=== 标题 + 描述输出规则（强制）===
每张扫描页的**前两行**必须先输出标记行（独立成行，标记前后用 【】 包裹）：

【标题: <≤10字核心主题>】
【描述: <≤40字内容要点>】

要求：
- **标题**：≤10 字中文，概括页面核心主题
- **描述**：≤40 字中文，说明该页内容的关键要点
- 标题和描述各占一行，**两行必须连写**（中间不要空行）
- 标题行 + 描述行后空一行，再接正常 OCR 内容
- marker 严格用 【】 而非 ===：批量响应里 `=== 图 N ===` 才是 chunk 边界，
  标题/描述行用 【】 包裹不会与 chunk 边界冲突，简化下游解析。"""

# 多图同批时的分隔指令（复用 run_eval_for_m3.py 的 MULTI_IMAGE_SEPARATOR_HINT）
MULTI_IMAGE_SEPARATOR_HINT = """

【重要：多图分隔规则】
本次共 {count} 张图片。请**逐张独立识别**，每张图用以下格式严格分隔：

=== 图 1 ===
（第 1 张图的完整识别内容）

=== 图 2 ===
（第 2 张图的完整识别内容）

... 一直到 === 图 {count} ===

严格要求：
1. 严禁将其他图的内容混进当前图的描述
2. 严禁遗漏任何一张图
3. 顺序必须与图片顺序一致
4. 每张图独立成段，段内可自由使用 markdown"""

# mixed 内嵌图概括：50-100 字
INLINE_IMAGE_SUMMARY_PROMPT = """请用 50-100 字概括这张图片的核心内容。要求：
- 说明图片类型（架构图/流程图/表格/截图/照片等）
- 提取关键文字信息和核心结构关系
- 直接输出概括文字，不要"这是一张..."这类废话"""


# ---------------------------------------------------------------------------
# HTTP 调用
# ---------------------------------------------------------------------------

def image_to_data_url(image_path: str | Path) -> str:
    """图片文件 → data URL（base64）。"""
    p = Path(image_path)
    suffix = p.suffix.lower()
    mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _normalize_endpoint(base_url: str) -> str:
    """把配置的 baseUrl 归一为 chat/completions 完整端点。

    与 search.py 的清理逻辑对齐：baseUrl 形态可能是
    ``http://host/v1`` 或误带 ``/chat/completions`` 后缀，统一处理。
    """
    url = (base_url or "").strip().rstrip("/")
    if "/chat/completions" in url:
        url = url.rsplit("/chat/completions", 1)[0].rstrip("/")
    return f"{url}/chat/completions"


def _normalize_anthropic_endpoint(base_url: str) -> str:
    """把配置的 baseUrl 归一为 anthropic messages 完整端点。

    归一规则：baseUrl 已以 /v1 结尾就拼 messages，否则补 v1/messages。
    （之前固定拼 messages 会把 https://api.minimaxi.com/anthropic 这类
    不带 /v1 的 baseUrl 路由到 /anthropic/messages → HTTP 404。）
    """
    url = (base_url or "").strip().rstrip("/")
    if url.endswith("/messages"):
        return url
    if re.search(r"/v1/?$", url):
        return f"{url}/messages"
    return f"{url}/v1/messages"


_DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg));base64,(.+)$", re.DOTALL)


def _openai_contents_to_anthropic(contents: list[dict]) -> list[dict]:
    """把内部 OpenAI 形态的 content 块转成 anthropic messages 形态。

    内部统一按 OpenAI 形态组装 contents（image_url data URL + text），
    仅在 anthropic-messages 协议出站前转换：
      image_url data URL → {"type": "image", "source": {"type": "base64", ...}}
      text → 原样透传（两家协议的 text 块同形）
    """
    blocks: list[dict] = []
    for c in contents:
        if c.get("type") == "text":
            blocks.append({"type": "text", "text": c.get("text", "")})
            continue
        if c.get("type") == "image_url":
            url = ((c.get("image_url") or {}).get("url")) or ""
            m = _DATA_URL_RE.match(url)
            if not m:
                # 理论不可达：image_to_data_url 只产 data:image/(png|jpeg)
                raise ValueError(
                    f"unsupported image url for anthropic protocol: {url[:60]!r}"
                )
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": m.group(1),
                    "data": m.group(2),
                },
            })
            continue
        raise ValueError(
            f"unsupported content type for anthropic protocol: {c.get('type')!r}"
        )
    return blocks


def _normalize_api_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if key.lower().startswith("bearer "):
        key = key[7:]
    return key


def _call_vision_api(
    contents: list[dict],
    *,
    endpoint: str,
    api_key: str,
    model: str,
    timeout: float = VISION_TIMEOUT,
    max_retries: int = 1,
    protocol: str = "openai-completions",
    max_tokens: Optional[int] = None,
) -> dict[str, Any]:
    """调一次多模态对话（SSE 流式），返回 {ok, elapsed, text, usage..., error, attempts}。

    🚨 OpenAI 路径 payload 中不设置 max_tokens（也不设默认值）——输出长度交给服务端。
    anthropic-messages 路径例外：该协议 max_tokens 必填，取模型条目 maxTokens
    （缺省 8192），保证整页 OCR 长文尽量不被截断。

    protocol 支持：
      - "openai-completions"（默认）：POST {base}/chat/completions，Bearer 鉴权，
        delta.content 累积，data: [DONE] 结束。
      - "anthropic-messages"：POST {base}/v1/messages（_normalize_anthropic_endpoint
        归一），x-api-key + Bearer 双鉴权 + anthropic-version 头，
        content_block_delta.text_delta 累积，message_stop 结束。
    """
    if protocol == "anthropic-messages":
        key = _normalize_api_key(api_key)
        payload = {
            "model": model,
            # anthropic 协议 max_tokens 必填（OpenAI 路径刻意不设——见 docstring）
            "max_tokens": int(max_tokens) if max_tokens else 8192,
            "messages": [
                {"role": "user", "content": _openai_contents_to_anthropic(contents)}
            ],
            "temperature": VISION_TEMPERATURE,
            "stream": True,
        }
        req_headers = {
            "Content-Type": "application/json",
            "accept": "application/json",
            # 双鉴权头：不同 anthropic 兼容服务端二选一识别（与网关
            # models.test 的 anthropic 分支行为一致）。
            "authorization": f"Bearer {key}",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
    else:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": contents}],
            "temperature": VISION_TEMPERATURE,
            "stream": True,  # SSE 流式响应：服务端开始吐 token 即可读
            # 注意：刻意不放 max_tokens
        }
        req_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
    last_err = "unknown"
    call_start = time.time()  # 累计总超时起点（跨所有重试，堵涓流挂起）
    for attempt in range(max_retries + 1):
        t0 = time.time()
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode(),
            headers=req_headers,
            method="POST",
        )
        try:
            # 流式读取：每读一行解析一个 SSE chunk。
            # "无数据超时"：连续 VISION_STREAM_NO_DATA_TIMEOUT 秒没新数据 → 视为 hang。
            # 用 select.select 实现（比 urlopen 总 timeout 更激进，能更快捕获服务端 hang）。
            #   - urlopen(timeout=timeout) 提供整体超时（如 300s）
            #   - select(select_timeout=VISION_STREAM_NO_DATA_TIMEOUT) 每次 recv 前等 N 秒
            import select as _select
            text_parts: list[str] = []
            model_name = model
            usage: dict = {}
            sock = urllib.request.urlopen(req, timeout=timeout)
            # urlopen 返回 http.client.HTTPResponse，其 fp 是 socket.makefile('rb')
            # 已经有 readline()；为了 select 用 fp 本身（它的 fileno() 是 socket 的）
            fp = sock.fp
            try:
                while True:
                    # 累计总超时：堵住"涓流响应"（服务端每 <20s 吐一小段 SSE
                    # 但永不 [DONE]）--此时 select 无数据超时和 urlopen 整体
                    # 超时都不会触发。到点即 raise，避免无限挂起。
                    remaining_total = VISION_TOTAL_TIMEOUT - (time.time() - call_start)
                    if remaining_total <= 0:
                        raise TimeoutError(
                            f"vision total timeout {VISION_TOTAL_TIMEOUT}s"
                        )
                    # 等下一个 chunk：取"无数据超时"与"剩余总预算"的较小值
                    ready, _, _ = _select.select(
                        [fp], [], [], min(VISION_STREAM_NO_DATA_TIMEOUT, remaining_total)
                    )
                    if not ready:
                        # 区分是总超时还是无数据超时触发的
                        if time.time() - call_start >= VISION_TOTAL_TIMEOUT:
                            raise TimeoutError(
                                f"vision total timeout {VISION_TOTAL_TIMEOUT}s"
                            )
                        raise TimeoutError(
                            f"stream no data for {VISION_STREAM_NO_DATA_TIMEOUT}s"
                        )
                    raw_line = fp.readline()
                    if not raw_line:
                        break  # EOF
                    line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        continue
                    # SSE 格式: "data: {...}" 或 "data: [DONE]"
                    if not line.startswith("data:"):
                        continue
                    payload_str = line[len("data:"):].strip()
                    if payload_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    if protocol == "anthropic-messages":
                        # anthropic 事件流：content_block_delta.text_delta 累积，
                        # message_stop 结束；error 事件转异常走统一错误返回。
                        ctype = chunk.get("type")
                        if ctype == "content_block_delta":
                            a_delta = chunk.get("delta") or {}
                            if a_delta.get("type") == "text_delta" and a_delta.get("text"):
                                text_parts.append(a_delta["text"])
                        elif ctype == "message_start":
                            start_usage = (
                                ((chunk.get("message") or {}).get("usage")) or {}
                            )
                            if start_usage.get("input_tokens") is not None:
                                usage["prompt_tokens"] = start_usage["input_tokens"]
                        elif ctype == "message_delta":
                            end_usage = chunk.get("usage") or {}
                            if end_usage.get("output_tokens") is not None:
                                usage["completion_tokens"] = end_usage["output_tokens"]
                        elif ctype == "message_stop":
                            break
                        elif ctype == "error":
                            stream_err = chunk.get("error") or {}
                            raise RuntimeError(
                                f"anthropic stream error: "
                                f"{stream_err.get('type')}: {stream_err.get('message')}"
                            )
                    else:
                        # OpenAI：累积 content delta
                        choices = chunk.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            content = delta.get("content")
                            if content:
                                text_parts.append(content)
                        # 部分服务端在最后一个 chunk 附带 usage
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                    # 部分服务端在最后一个 chunk 附带 model
                    if chunk.get("model"):
                        model_name = chunk["model"]
            finally:
                sock.close()

            text = "".join(text_parts)
            if not text:
                # 服务端没返回任何 content（极少见）
                return {
                    "ok": False, "elapsed": time.time() - t0,
                    "error": "stream returned no content",
                    "attempts": attempt + 1,
                }
            return {
                "ok": True,
                "elapsed": time.time() - t0,
                "text": text,
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "model": model_name,
                "attempts": attempt + 1,
            }
        except urllib.error.HTTPError as e:
            elapsed = time.time() - t0
            try:
                err_msg = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                err_msg = ""
            full_err = f"HTTP {e.code}: {err_msg}"
            # 5xx 重试；4xx 不重试（参数错误，再试也是错）
            if 500 <= e.code < 600 and attempt < max_retries:
                logger.warning(
                    f"vision_client: {full_err[:200]}, retrying "
                    f"(attempt {attempt + 2}/{max_retries + 1})"
                )
                last_err = full_err
                time.sleep(2 ** attempt)  # 1s, 2s, 4s...
                continue
            return {
                "ok": False, "elapsed": elapsed, "error": full_err,
                "attempts": attempt + 1,
            }
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            # 连接级错误：DNS / connection refused / reset / 超时 / 流式无数据超时
            elapsed = time.time() - t0
            err_str = f"{type(e).__name__}: {e}"
            # 重试策略：服务端临时忙时大概率成功；真 hang 时用户接受再等。
            # 注意：流式无数据超时（60s）触发的 TimeoutError 重试时仍用同样超时（300s 上限），
            # 但服务端 hang 通常意味着连接已建立无响应，重试大概率同样 hang。
            # 仍然重试一次以应对瞬时网络抖动。
            if attempt < max_retries:
                logger.warning(
                    f"vision_client: {err_str}, retrying "
                    f"(attempt {attempt + 2}/{max_retries + 1})"
                )
                last_err = err_str
                time.sleep(2 ** attempt)
                continue
            return {
                "ok": False, "elapsed": elapsed, "error": err_str,
                "attempts": attempt + 1,
            }
        except Exception as e:
            elapsed = time.time() - t0
            return {
                "ok": False, "elapsed": elapsed,
                "error": f"{type(e).__name__}: {e}",
                "attempts": attempt + 1,
            }
    # 不可达：max_retries 全用完仍失败（防御性，正常循环内已 return）
    return {
        "ok": False, "elapsed": 0.0,
        "error": f"max_retries exhausted: {last_err}",
        "attempts": max_retries + 1,
    }


# ---------------------------------------------------------------------------
# 多图响应拆分（移植 m3_client._split_batch_response）
# ---------------------------------------------------------------------------

# 思考块（部分模型在 OCR 内容前输出内部推理）
# 实际输出：<mm:think>...<mm:/think>，含 U+200B + `mm` 前缀。
# 用 `.*?`（不是 `[^>]*?`）——后者不能跨 `>`，无法匹配 `mm:think>` 里的 `>`。
# 闭标签的 `/` 可有可无：`</think` / `<mm:think` 都见过。
_THINKING_BLOCK_RE = re.compile(
    r"^\s*<[^>]*?think[^>]*?>[\s\S]*?</?\s*[^>]*?think[^>]*?>\s*\n?",
    re.IGNORECASE | re.DOTALL,
)


def _strip_thinking_block(text: str) -> str:
    """去掉模型在 OCR 内容**最前面**输出的思考块（`<think>...</think>`）。

    与 doc_image_extractor 的版本一致（同步演化）。
    部分模型习惯先输出推理再输出实际内容。
    思考块若保留，会污染 .md 文件 + 向量库 + 泄漏用户提问。

    必须在 split_batch_response 之前调用 —— 否则思考闭合标签后
    `=== 图 N ===` 不在行首，split 切错位。
    """
    if not text:
        return text
    return _THINKING_BLOCK_RE.sub("", text, count=1).lstrip()


_BATCH_MARKER_RE = re.compile(
    r"(?m)^\s*(?:"
    r"\[图\s*\d+\]"             # [图 N]
    r"|===\s*图\s*\d+\s*==="    # === 图 N ===
    r"|#\s*图\s*\d+\s*[:：]"    # # 图 N：
    r"|图\s*\d+\s*[:：]"        # 图 N：
    r"|\*\*图\s*\d+\*\*"        # **图 N**
    r")"
)


def split_batch_response(text: str, n: int) -> list[str]:
    """把多图批量响应拆成 n 份。

    优先按分隔标记切（兼容 [图 N] / === 图 N === / # 图 N： / 图 N： / **图 N**），
    标记不足 n 个时按行均分兜底。
    """
    matches = list(_BATCH_MARKER_RE.finditer(text))
    if len(matches) >= n:
        chunks: list[str] = []
        for i in range(n):
            start = matches[i].end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunks.append(text[start:end].strip())
        return chunks
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return [""] * n
    per = max(1, len(lines) // n)
    chunks = []
    for i in range(n):
        start = i * per
        end = start + per if i < n - 1 else len(lines)
        chunks.append("\n".join(lines[start:end]).strip())
    return chunks


def _looks_misaligned(chunk: str) -> bool:
    """启发式判断拆分结果是否错位（空串或明显是分隔标记残渣）。"""
    stripped = chunk.strip()
    if not stripped:
        return True
    # 只剩分隔标记本身（如 "===" 或 "图 2"），说明错位
    if len(stripped) <= 6 and not re.search(r"[一-鿿\w]{3,}", stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# 批量识别（公开 API）
# ---------------------------------------------------------------------------

def _recognize_one_batch(
    image_paths: list[Path],
    prompt: str,
    *,
    endpoint: str,
    api_key: str,
    model: str,
    batch_no: int,
    protocol: str = "openai-completions",
    max_tokens: Optional[int] = None,
) -> list[dict[str, Any]]:
    """识别一个批次（≤ VISION_BATCH_SIZE 张图），返回与 image_paths 等长的结果列表。

    单图批次直接调用；多图批次用分隔提示词一次调用后拆分，
    拆分错位/失败的图自动降级为单图重试。
    """
    n = len(image_paths)
    if n == 1:
        contents = [
            {"type": "image_url", "image_url": {"url": image_to_data_url(image_paths[0])}},
            {"type": "text", "text": prompt},
        ]
        r = _call_vision_api(
        contents, endpoint=endpoint, api_key=api_key, model=model,
        protocol=protocol, max_tokens=max_tokens,
    )
        # 单图分支也必须剥 thinking 块（与多图分支对齐）
        # 否则单图响应（如 Page_NNN.md 的 n=1 batch）会带完整 thinking 块
        # 污染 .md 文件 + 泄漏用户提问到向量库。
        text = r.get("text", "") if r["ok"] else ""
        if text:
            text = _strip_thinking_block(text)
        return [{
            "ok": r["ok"],
            "image": str(image_paths[0]),
            "elapsed": r["elapsed"],
            "text": text,
            "error": None if r["ok"] else r.get("error", "unknown"),
            "input_tokens": r.get("input_tokens", 0),
            "output_tokens": r.get("output_tokens", 0),
            "batch_no": batch_no,
            "attempts": r.get("attempts", 1),
        }]

    # 多图同批：[img1, "[图 1]", img2, "[图 2]", ..., prompt + 分隔指令]
    contents: list[dict] = []
    for idx, img in enumerate(image_paths, start=1):
        contents.append({"type": "image_url", "image_url": {"url": image_to_data_url(img)}})
        contents.append({"type": "text", "text": f"[图 {idx}]"})
    contents.append({
        "type": "text",
        "text": prompt + MULTI_IMAGE_SEPARATOR_HINT.format(count=n),
    })

    r = _call_vision_api(
        contents, endpoint=endpoint, api_key=api_key, model=model,
        protocol=protocol, max_tokens=max_tokens,
    )
    if not r["ok"]:
        return [{
            "ok": False,
            "image": str(img),
            "elapsed": r["elapsed"] / n,
            "text": "",
            "error": r.get("error", "unknown"),
            "input_tokens": 0,
            "output_tokens": 0,
            "batch_no": batch_no,
            "attempts": r.get("attempts", 1),
        } for img in image_paths]

    # 关键：split_batch_response 前必须先剥 thinking 块
    # 否则 `</mm:think>=== 图 1 ===` 这种结构里 `=== 图 1 ===` 不在行首，
    # _BATCH_MARKER_RE（用 (?m)^）找不到第一个 marker，split 错位 → chunk
    # 含下游 marker / title / desc → doc_image_extractor 拿到的 ocr_text 含
    # 多页混杂内容。
    clean_text = _strip_thinking_block(r["text"])
    chunks = split_batch_response(clean_text, n)
    results: list[dict[str, Any]] = []
    for j, (img, sub) in enumerate(zip(image_paths, chunks)):
        ok = not _looks_misaligned(sub)
        results.append({
            "ok": ok,
            "image": str(img),
            "elapsed": r["elapsed"] / n,
            "text": sub if ok else "",
            "error": None if ok else "batch_split_misaligned",
            "input_tokens": r.get("input_tokens", 0) // n,
            "output_tokens": r.get("output_tokens", 0) // n,
            "batch_no": batch_no,
            "attempts": r.get("attempts", 1),
        })

    # 降级单图重试仅在"个别图 split 错位"场景触发：
    # 服务端 hang / timeout / HTTPError 时整批所有图必然一起失败，
    # 这种"全图 API 错"场景下逐图单图重试纯粹是浪费——hang 时单图会再 hang，
    # 一致性仍然差。不如直接放弃降级，让进度条如实显示 N/M 失败。
    # 判定：所有图都 ok=False 且没有任何一张是 split 错位（错位是 ok=False 但 error="batch_split_misaligned"）
    all_api_error = (
        bool(results)
        and all(not r["ok"] for r in results)
        and all(r.get("error") != "batch_split_misaligned" for r in results)
    )
    if all_api_error:
        logger.warning(
            f"vision_client: batch {batch_no} all {len(results)} image(s) "
            f"failed with API errors (no split misalignment), "
            f"skipping single-image retry to avoid cascading hang; "
            f"first error={results[0].get('error')!r}"
        )
        return results

    # 错位/失败的图降级为单图重试（不让整批失败）
    for j, res in enumerate(results):
        if res["ok"]:
            continue
        logger.info(
            f"vision_client: batch {batch_no} image {j + 1} misaligned/failed, "
            f"retrying single: {Path(res['image']).name}"
        )
        single = _recognize_one_batch(
            [Path(res["image"])], prompt,
            endpoint=endpoint, api_key=api_key, model=model, batch_no=batch_no,
            protocol=protocol, max_tokens=max_tokens,
        )
        results[j] = single[0]
        if not single[0]["ok"] and res.get("error") != "batch_split_misaligned":
            # 单图重试也失败：保留原始批次错误（信息量更足）
            results[j]["error"] = single[0].get("error") or res.get("error")
    return results


def recognize_images(
    image_paths: list[str | Path],
    prompt: str,
    *,
    llm_config: dict,
    batch_size: int = VISION_BATCH_SIZE,
    concurrency: int = VISION_CONCURRENCY,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> list[dict[str, Any]]:
    """批量识别图片（batch 多图 + 批次间并发），返回与 image_paths 等序的结果列表。

    Args:
        image_paths: 图片路径列表（顺序即结果顺序）
        prompt:      识别提示词（SCAN_PAGE_OCR_PROMPT / INLINE_IMAGE_SUMMARY_PROMPT）
        llm_config:  resolve_runtime_llm_config() 的返回，
                     需含 base_url / api_key / model_id
        batch_size:  单次 API 调用的图片数（默认 VISION_BATCH_SIZE=3）
        concurrency: 并发批次数（默认 VISION_CONCURRENCY=3）
        progress_callback:
                     可选进度回调，签名为 ``(current, total)``。
                     每个 batch 完成后触发一次；current 是已完成图片数（累加），
                     total = len(image_paths)。
                     异常由内部 try/except 吞掉，不影响主流程。

    Returns:
        list of {ok, image, elapsed, text, error, input_tokens, output_tokens, batch_no}
        长度与顺序 == image_paths
    """
    paths = [Path(p) for p in image_paths]
    if not paths:
        return []

    # 协议路由：openai-completions（默认）/ anthropic-messages 之外的协议不支持，
    # 明确报错而不是拿错端点打出迷惑的 404（失败明细会逐图落到 images_index.json）。
    protocol = (llm_config.get("api_protocol") or "openai-completions").strip().lower()
    if protocol not in ("openai-completions", "anthropic-messages"):
        logger.warning(
            f"vision_client: unsupported api_protocol={protocol!r}, "
            f"marking all {len(paths)} image(s) failed"
        )
        return [{
            "ok": False,
            "image": str(p),
            "elapsed": 0.0,
            "text": "",
            "error": f"unsupported api_protocol: {protocol}",
            "input_tokens": 0,
            "output_tokens": 0,
            "batch_no": 0,
        } for p in paths]

    if protocol == "anthropic-messages":
        endpoint = _normalize_anthropic_endpoint(llm_config.get("base_url", ""))
    else:
        endpoint = _normalize_endpoint(llm_config.get("base_url", ""))
    api_key = _normalize_api_key(llm_config.get("api_key", ""))
    model = (llm_config.get("model_id") or llm_config.get("model") or "").strip()
    max_tokens = llm_config.get("max_tokens")
    if not endpoint or not api_key or not model:
        return [{
            "ok": False,
            "image": str(p),
            "elapsed": 0.0,
            "text": "",
            "error": "llm_config incomplete (base_url/api_key/model_id)",
            "input_tokens": 0,
            "output_tokens": 0,
            "batch_no": 0,
        } for p in paths]

    batches: list[tuple[int, list[Path]]] = []
    for i in range(0, len(paths), batch_size):
        batches.append((i // batch_size + 1, paths[i:i + batch_size]))

    logger.info(
        f"vision_client: recognizing {len(paths)} image(s) in {len(batches)} batch(es) "
        f"model={model} protocol={protocol} batch_size={batch_size} concurrency={concurrency}"
    )
    t0 = time.time()

    # 按批次并发；结果按批次号归位，保证与 image_paths 等序
    batch_results: dict[int, list[dict[str, Any]]] = {}
    completed_count = 0
    if len(batches) == 1:
        batch_no, chunk = batches[0]
        batch_t0 = time.time()
        batch_results[batch_no] = _recognize_one_batch(
            chunk, prompt, endpoint=endpoint, api_key=api_key, model=model,
            batch_no=batch_no, protocol=protocol, max_tokens=max_tokens,
        )
        # 只算成功：超时/失败的 batch 不应让进度条跳到 100%
        _ok = sum(1 for r in batch_results[batch_no] if r.get("ok"))
        _tot = len(batch_results[batch_no])
        logger.info(
            f"vision_client: batch {batch_no} done in {time.time() - batch_t0:.2f}s "
            f"({_ok}/{_tot} ok)"
        )
        completed_count += _ok
        if progress_callback:
            try:
                progress_callback(completed_count, len(paths))
            except Exception as e:
                logger.warning(f"vision_client: progress_callback error: {e}")
    else:
        with ThreadPoolExecutor(
            max_workers=max(1, concurrency), thread_name_prefix="vision-ocr"
        ) as executor:
            # 用 dict 同时记录 batch_no 和提交时刻，便于诊断卡住的 batch
            # 错峰启动：每个 batch 之间间隔 BATCH_START_DELAY 秒，避免
            # 同时打到服务端触发 hang（压测验证 hang 率 100%→0%）
            #
            # 2026-08-26 优化：上面 2s 全程间隔在 150 批时累计 300s 纯 sleep，
            # 占实际项目 9 pages 拉取总耗时 (500s) 的 60%。改为 taper：
            # 前 VISION_TAPER_BATCHES 个 batch 走全间隔避开"3 worker 同时首
            # 请求"竞争；后续 batch 走短间隔（executor 池已满，新提交进队列，
            # 不会同时打服务端）。
            futures = {}
            submit_times: dict[int, float] = {}
            for submitted_idx, (batch_no, chunk) in enumerate(batches):
                submit_times[batch_no] = time.time()
                # 每个 batch 提交前的进度日志（让 sync.log 看到每批 kickoff 时刻，
                # 便于诊断某批卡了多久）。submit 后立即打，避免 batch 完成后被冲掉。
                logger.info(
                    f"vision_client: batch {batch_no}/{len(batches)} submit "
                    f"({len(chunk)} img, taper={'full' if submitted_idx < VISION_TAPER_BATCHES else 'short'})"
                )
                futures[executor.submit(
                    _recognize_one_batch, chunk, prompt,
                    endpoint=endpoint, api_key=api_key, model=model, batch_no=batch_no,
                    protocol=protocol, max_tokens=max_tokens,
                )] = batch_no
                # 最后一个 batch 后不再 sleep（否则白白多等）
                if batch_no != batches[-1][0]:
                    delay = (
                        BATCH_START_DELAY
                        if submitted_idx < VISION_TAPER_BATCHES
                        else BATCH_POST_TAPER_DELAY
                    )
                    time.sleep(delay)
            for fut in as_completed(futures):
                batch_no = futures[fut]
                batch_elapsed = time.time() - submit_times[batch_no]
                try:
                    batch_results[batch_no] = fut.result()
                except Exception as e:
                    # 整批异常（不应发生，_recognize_one_batch 内部已兜底）：标记整批失败
                    chunk = dict(batches)[batch_no]
                    batch_results[batch_no] = [{
                        "ok": False, "image": str(p), "elapsed": 0.0, "text": "",
                        "error": f"batch executor error: {e}",
                        "input_tokens": 0, "output_tokens": 0, "batch_no": batch_no,
                    } for p in chunk]
                # 单 batch 完成诊断日志：让用户从 cosightbot.log 看到哪个 batch 慢/超时
                _ok = sum(1 for r in batch_results[batch_no] if r.get("ok"))
                _tot = len(batch_results[batch_no])
                _status = "ok" if _ok == _tot else (
                    "timeout/partial" if _ok > 0 else "failed"
                )
                logger.info(
                    f"vision_client: batch {batch_no} done in {batch_elapsed:.2f}s "
                    f"({_ok}/{_tot} {_status})"
                )
                # 只算成功：超时/失败的 batch 不应让进度条跳到 100%
                # （之前用 len() 会把失败 batch 的 N 个失败结果也算成完成，
                #  导致进度条从 6/11 突然跳到 11/11，掩盖了 5 张图实际失败）
                completed_count += _ok
                if progress_callback:
                    try:
                        # completed_count 累加（仅成功）；VISION_CONCURRENCY=3 让批次乱序
                        # 完成，单调推进由 progress_ui.update_file_subprogress 的 max() 保证
                        progress_callback(completed_count, len(paths))
                    except Exception as e:
                        logger.warning(f"vision_client: progress_callback error: {e}")

    results: list[dict[str, Any]] = []
    for batch_no, _chunk in batches:
        results.extend(batch_results.get(batch_no, []))

    ok_count = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count
    total_elapsed = time.time() - t0
    logger.info(
        f"vision_client: done {ok_count}/{len(results)} ok "
        f"({fail_count} failed) in {total_elapsed:.2f}s"
    )
    # 失败明细：列出每张失败图的 filename + 错误原因（截断 120 字）
    # 让用户从 cosightbot.log 一眼看到是哪几张图识别失败、为什么失败
    if fail_count > 0:
        failed_lines = [
            f"  - {Path(r['image']).name}: "
            f"{(r.get('error') or 'unknown')[:120]}"
            f" (attempts={r.get('attempts', 1)})"
            for r in results if not r.get("ok")
        ]
        logger.warning(
            f"vision_client: {fail_count} image(s) failed:\n" + "\n".join(failed_lines)
        )
    return results


def resolve_vision_llm_config(
    session_key: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Optional[dict]:
    """解析当前生效的多模态模型配置；模型不支持图片输入时返回 None。

    封装 model_capability 判断 + cosight_runtime 配置解析，
    供 doc_image_extractor 一行调用。
    """
    # 测试/故障注入覆盖：env 直接指定 vision endpoint，绕过 model_capability 门禁，
    # 让测试无需配置多模态模型即可把 OCR 打到 mock server。
    env_url = os.environ.get("COSIGHTBOT_VISION_API_URL")
    if env_url:
        logger.info(f"vision_client: COSIGHTBOT_VISION_API_URL override -> {env_url}")
        _m = os.environ.get("COSIGHTBOT_VISION_MODEL", "mock-vision")
        return {
            "base_url": env_url,
            "api_key": os.environ.get("COSIGHTBOT_VISION_API_KEY", "mock-key"),
            "model_id": _m,
            "model": _m,
        }

    # 与 overview_resolver 相同的导入方式：watch_dog 是 sys.path 根（非包）
    from watch_dog.file_watcher.model_capability import current_model_supports_images

    try:
        if not current_model_supports_images(
            session_key=session_key, agent_id=agent_id
        ):
            logger.info("vision_client: active model does not support image input, skip OCR")
            return None
    except Exception as e:
        logger.warning(f"vision_client: model capability check failed: {e}")
        return None

    from common.cosight_runtime import resolve_runtime_llm_config
    return resolve_runtime_llm_config("vision_ocr", session_key=session_key, agent_id=agent_id)
