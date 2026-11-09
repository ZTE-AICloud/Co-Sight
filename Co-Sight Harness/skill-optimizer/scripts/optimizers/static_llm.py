"""static_llm.py — /skill_optimize 的 LLM HTTP 调用封装。

走 Anthropic Messages 协议（POST {base_url}/v1/messages），
默认 base_url 取自 config/optimize-user-config.yaml 的 llm_api.model.* 段，
也支持环境变量覆盖（SKILLX_OPT_MODEL / SKILLX_OPT_BASE_URL / SKILLX_OPT_API_KEY）。

提供能力：
- call_llm_api() 单次调用 + 3 次重试 + 指数退避
- parse_json_response() JSON 解析（带正则兜底）
- load_llm_config() 统一读 model 段

设计原则：
- 不知道具体业务 schema（不假设评分结构，由 prompt 模板决定）
- 重试只针对 transient 错误（超时/429/5xx），业务错误不重试
- 解析失败时返回原始文本，调用方自己处理
"""
from __future__ import annotations

import json

try:
    import json_repair  # P1-7 兜底：LLM 输出 JSON 截断/单引号未转义时用 json_repair 修复
except ImportError:
    json_repair = None  # type: ignore[assignment]
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("static_llm")


def _dump_llm_debug(
    debug_label: Optional[str],
    user_prompt: str,
    system_prompt: str,
    raw_response: str,
    exception: Optional[str] = None,
    duration_sec: Optional[float] = None,
    http_status: Optional[int] = None,
    retries: int = 0,
    parsed_result: Optional[str] = None,
) -> None:
    """debug_label 非 None 时把 LLM 调用的完整输入/输出落盘到 _debug/。

    失败仅 warning，不阻断主链路。复用 tools._dump_llm_call（如果 tools 可导入），
    否则跳过（罕见边缘情况，主链路走 subagent 路径更为常见）。
    """
    if debug_label is None:
        return
    try:
        from tools import _dump_llm_call
        _dump_llm_call(
            label=debug_label,
            system_prompt=system_prompt or "",
            user_prompt=user_prompt or "",
            raw_response=raw_response or "",
            parsed_result=parsed_result,
            exception=exception,
            duration_sec=duration_sec,
            http_status=http_status,
            retries=retries,
        )
    except Exception:
        pass  # 落盘失败不阻断主链路

# 默认重试配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 2.0  # 秒
DEFAULT_TIMEOUT = 120  # 秒


@dataclass
class LLMConfig:
    """从 optimize-user-config.yaml 的 ll_api.model 段读取的 LLM 配置。"""

    name: str
    base_url: str
    api_key: str
    max_tokens: int = 4096
    temperature: float = 0.3
    #  B 方案:evaluator 单独温度(默认 0.0 绝对确定);optimizer 仍用 temperature
    # 避免 evaluator LLM 噪声盖过真信号(R1→R2 7.5→7.4 这种真变化 vs 6.0→7.5 这种噪声)
    eval_temperature: float = 0.0
    # 每次 call 的唯一标识,传给 LLM API 的 user_id metadata,用于跨 call 追踪
    request_id: str = ""

    @classmethod
    def from_yaml(cls, config_path: Path) -> "LLMConfig":
        """从 optimize-user-config.yaml 读 llm_api 段。

        找不到本文件的 llm_api.model 时，fallback 到
        config/evolve-user-config.yaml 的 model 段（共享同一个 ccr 实例）。
        """
        import yaml

        # 1. 优先读 optimize-user-config.yaml
        llm: dict = {}
        if config_path.exists():
            try:
                with open(config_path) as f:
                    cfg = yaml.safe_load(f) or {}
                llm = (cfg.get("llm_api") or {}).get("model") or {}
            except (OSError, yaml.YAMLError):
                llm = {}

        # 2. fallback 到 evolve-user-config.yaml 的 model 段
        if not llm.get("api_key"):
            evolve_cfg = config_path.parent / "evolve-user-config.yaml"
            if evolve_cfg.exists():
                try:
                    with open(evolve_cfg) as f:
                        cfg = yaml.safe_load(f) or {}
                    m = cfg.get("model") or {}
                    llm = {**m, **llm}  # 本文件覆盖 fallback
                except (OSError, yaml.YAMLError):
                    pass

        if not llm.get("api_key"):
            raise ValueError(
                f"未找到有效的 LLM api_key。请在 {config_path} 的 llm_api.model 段"
                f"或 {config_path.parent / 'evolve-user-config.yaml'} 的 model 段补充"
            )

        return cls(
            name=llm.get("name", "MiniMax-M3"),
            base_url=llm.get("base_url", "https://api.minimaxi.com/anthropic"),
            api_key=llm.get("api_key", ""),
            max_tokens=int(llm.get("max_tokens", 4096)),
            temperature=float(llm.get("temperature", 0.3)),
            eval_temperature=float(llm.get("eval_temperature", 0.0)),
        )

    def with_env_override(self) -> "LLMConfig":
        """环境变量覆盖（最高优先级）。"""
        return LLMConfig(
            name=os.environ.get("SKILLX_OPT_MODEL", self.name),
            base_url=os.environ.get("SKILLX_OPT_BASE_URL", self.base_url),
            api_key=os.environ.get("SKILLX_OPT_API_KEY", self.api_key),
            max_tokens=int(os.environ.get("SKILLX_OPT_MAX_TOKENS", self.max_tokens)),
            temperature=float(os.environ.get("SKILLX_OPT_TEMPERATURE", self.temperature)),
            eval_temperature=float(os.environ.get(
                "SKILLX_OPT_EVAL_TEMPERATURE", self.eval_temperature,
            )),
        )


def call_llm_api(
    prompt: str,
    system: str = "",
    config: Optional[LLMConfig] = None,
    response_format_json: bool = True,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: int = DEFAULT_TIMEOUT,
    temperature: Optional[float] = None,
    nonce: Optional[str] = None,
    debug_label: Optional[str] = None,
) -> str:
    """调用 LLM API（Anthropic Messages 协议），返回文本响应。

    Args:
        prompt: 用户消息
        system: 系统提示词
        config: LLMConfig，未传则从默认配置加载
        response_format_json: 是否在 system 中要求 JSON 输出
        max_retries: 最大重试次数（transient 错误）
        timeout: 单次 HTTP 超时（秒）
        temperature: 覆盖 config.temperature(evaluator 走 eval_temperature 默认 0.0)
        nonce: 唯一标识(写入 user_id metadata,防 LLM API 端跨 call 缓存命中)
        debug_label: 不为 None 时将完整输入/输出落盘到 _debug/agent_{debug_label}_*.txt

    Returns:
        LLM 响应文本（不含 thinking 等内部字段）

    Raises:
        RuntimeError: 重试耗尽仍失败
        ValueError: prompt 为空或 config 无效
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt 不能为空")
    if config is None:
        config = LLMConfig.from_yaml(
            Path(__file__).resolve().parents[2] / "config" / "optimize-user-config.yaml"
        ).with_env_override()
    if not config.api_key:
        raise ValueError("LLM api_key 未配置")

    url = config.base_url.rstrip("/") + "/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
    }

    # 在 system 中追加 JSON 输出要求（Anthropic 原生无 response_format）
    full_system = system
    if response_format_json:
        full_system = (
            (system + "\n\n" if system else "")
            + "【输出格式约束】必须输出严格的 JSON 对象，不要使用 ```json 包裹，"
            "不要输出任何解释性文字。JSON 顶层不要包含 markdown。"
        )

    # 决定本次调用的 temperature（ B 方案：evaluator 走低温）
    use_temperature = temperature if temperature is not None else config.temperature

    body: dict = {
        "model": config.name,
        "max_tokens": config.max_tokens,
        "temperature": use_temperature,
        "system": full_system,
        "messages": [{"role": "user", "content": prompt}],
    }
    #  B 方案：写入 metadata.user_id（Anthropic 原生支持）便于追踪 + 防缓存
    if nonce:
        body["metadata"] = {"user_id": nonce}

    last_err: Optional[Exception] = None
    last_raw: str = ""
    last_http_status: Optional[int] = None
    _t0 = time.monotonic()
    for attempt in range(1, max_retries + 1):
        try:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                last_raw = resp.read().decode("utf-8")
                last_http_status = resp.status
            result = _extract_text_from_anthropic(last_raw)
            _dump_llm_debug(
                debug_label, prompt, full_system, last_raw, None,
                duration_sec=time.monotonic() - _t0,
                http_status=last_http_status, retries=attempt - 1,
            )
            return result
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            last_raw = err_body
            last_http_status = e.code
            last_err = RuntimeError(f"HTTP {e.code}: {err_body}")
            # 429/5xx 重试，4xx 业务错误不重试
            if e.code in (429, 500, 502, 503, 504):
                if attempt < max_retries:
                    delay = DEFAULT_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM 调用 transient 错误 (HTTP %s)，%ss 后重试 [%d/%d]",
                        e.code, delay, attempt, max_retries,
                    )
                    time.sleep(delay)
                    continue
            _dump_llm_debug(
                debug_label, prompt, full_system, last_raw, str(last_err) if last_err else None,
                duration_sec=time.monotonic() - _t0,
                http_status=last_http_status, retries=attempt - 1,
            )
            raise last_err
        except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead) as e:
            last_raw = ""
            last_http_status = None
            last_err = RuntimeError(f"网络错误: {e}")
            if attempt < max_retries:
                delay = DEFAULT_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "LLM 调用网络错误，%ss 后重试 [%d/%d]: %s",
                    delay, attempt, max_retries, e,
                )
                time.sleep(delay)
                continue
            _dump_llm_debug(
                debug_label, prompt, full_system, "", str(last_err),
                duration_sec=time.monotonic() - _t0,
                http_status=None, retries=attempt - 1,
            )
            raise last_err

    _dump_llm_debug(
        debug_label, prompt, full_system, last_raw, str(last_err) if last_err else "重试耗尽",
        duration_sec=time.monotonic() - _t0,
        http_status=last_http_status, retries=max_retries,
    )
    raise last_err or RuntimeError("LLM 调用重试耗尽")


def _extract_text_from_anthropic(raw: str) -> str:
    """从 Anthropic Messages API 响应中提取文本 content。"""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Anthropic 响应非 JSON: {raw[:200]}") from e

    content = payload.get("content", [])
    if not isinstance(content, list):
        raise RuntimeError(f"Anthropic 响应 content 字段异常: {content}")

    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    if not parts:
        raise RuntimeError(f"Anthropic 响应无 text content: {content}")
    return "".join(parts)


# JSON 解析（含正则兜底）
_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _clean_json_text(text: str) -> str:
    """清洗 LLM 输出的脏 JSON。

    - 删除 // 行注释（不在 JSON 字符串内的注释）
    - 清理 trailing comma（, 后跟空白和 }/]）
    """
    out: list[str] = []
    i = 0
    in_string = False
    escape = False
    while i < len(text):
        ch = text[i]
        if escape:
            out.append(ch)
            escape = False
            i += 1
            continue
        if ch == "\\" and in_string:
            out.append(ch)
            escape = True
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            i += 1
            continue
        if not in_string and ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
            # 跳过 // 到行尾
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    cleaned = "".join(out)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    return cleaned


def _find_balanced_json_objects(text: str) -> list[str]:
    """栈平衡找所有完整闭合的 JSON 对象 {...} 块（按出现顺序）。

    用字符串状态机避开字符串内的 {/} 干扰，返回每个完整闭合的块。
    覆盖 LLM 输出"主 JSON + 末尾说明 + 辅助 JSON 块"的场景。
    """
    blocks: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                blocks.append(text[start:i + 1])
                start = -1
    return blocks


def parse_json_response(text: str) -> dict[str, Any]:
    """解析 LLM 输出的 JSON 文本。

    处理策略（按顺序尝试，前一步成功即返回）：
    1. 直接 json.loads（clean JSON）
    2. 剥离 ```markdown``` 包裹 + 清洗（删 // 注释 + trailing comma）+ json.loads
    3. 栈平衡找所有完整 {..} 块，逐个清洗 + json.loads（覆盖多 JSON 块场景）
    4. json_repair 兜底修复截断/未转义引号/未闭合括号
    5. 全部失败则抛 ValueError

    返回 dict（不是 list），如果是 list 会包成 {"items": [...]}
    """
    if not text or not text.strip():
        raise ValueError("LLM 响应为空")

    # 1. 直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        return {"items": obj}
    except json.JSONDecodeError:
        pass

    # 2. 剥离 markdown 包裹 + 清洗
    stripped = text.strip()
    if stripped.startswith("```"):
        # 去掉首尾 ```
        lines = stripped.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines)
    cleaned = _clean_json_text(stripped)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
        return {"items": obj}
    except json.JSONDecodeError:
        pass

    # 2.5 json_repair 优先（修复 LLM 输出的小结构问题：未闭合引号、缺 fields）
    # 重要：先尝试 json_repair，因为它能修复结构性的小损坏（LLM 偶尔会输出
    # 漏 fields 的 finding object,导致 python json 严格解析失败，但 json_repair 可补全）
    if json_repair is not None:
        try:
            obj = json_repair.loads(text)
            if isinstance(obj, dict):
                return obj
            return {"items": obj}
        except Exception as e:
            logger.debug("json_repair 尝试 1 失败: %s", e)

    # 3. 栈平衡找完整 {..} 块（覆盖多 JSON 块场景）
    for block in _find_balanced_json_objects(text):
        try:
            obj = json.loads(_clean_json_text(block))
            if isinstance(obj, dict):
                return obj
            return {"items": obj}
        except json.JSONDecodeError:
            continue

    # 4. 兜底重试 json_repair（万一 step 2.5 已被 logger.debug 略过）
    if json_repair is not None:
        try:
            obj = json_repair.loads(text)
            if isinstance(obj, dict):
                return obj
            return {"items": obj}
        except Exception as e:
            logger.debug("json_repair 兜底失败: %s", e)
    raise ValueError(f"无法从 LLM 响应解析 JSON: {text[:300]}")


# 便捷函数：调用并直接解析 JSON
def call_llm_json(
    prompt: str,
    system: str = "",
    config: Optional[LLMConfig] = None,
    temperature: Optional[float] = None,
    nonce: Optional[str] = None,
    debug_label: Optional[str] = None,
) -> dict[str, Any]:
    """调用 LLM 并直接返回解析后的 JSON dict。"""
    raw = call_llm_api(
        prompt=prompt, system=system, config=config,
        response_format_json=True, temperature=temperature, nonce=nonce,
        debug_label=debug_label,
    )
    return parse_json_response(raw)


# ─────────────────────────────────────────────────────────────────────
# Agent loop + tool_use 支持（.12+）
# ─────────────────────────────────────────────────────────────────────
# Co-sight Pro 自实现的 agent loop，不依赖 cosight。
# 基于 Anthropic Messages API 原生 tool_use 协议：
# - body 带 tools 字段声明可用工具
# - 响应 stop_reason="tool_use" 时执行 tool，本地拿 tool_result
# - 循环直到 stop_reason="end_turn"


def call_llm_with_tools(
    messages: list[dict],
    tools: list[dict],
    system: str = "",
    config: Optional[LLMConfig] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    nonce: Optional[str] = None,
    timeout: int = 180,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict[str, Any]:
    """调用 Anthropic Messages API 带 tools 参数（单次调用，不循环）。

    返回原始 response payload dict（含 stop_reason / content / usage 等）。

    Args:
        messages: Anthropic Messages 格式的对话历史（不含 system）
        tools: Anthropic tool schema 列表（每个含 name/description/input_schema）
        system: 系统提示词
        config: LLMConfig
        max_tokens: 覆盖 config.max_tokens（agent loop 需要更大输出预算）
        temperature: 覆盖 config.temperature
        nonce: 唯一标识（防 LLM API 端跨 call 缓存）
        timeout: 单次 HTTP 超时（agent loop 通常需要更长）
        max_retries: 429/5xx 重试次数
    """
    if config is None:
        config = LLMConfig.from_yaml(
            Path(__file__).resolve().parents[2] / "config" / "optimize-user-config.yaml"
        ).with_env_override()
    if not config.api_key:
        raise ValueError("LLM api_key 未配置")

    url = config.base_url.rstrip("/") + "/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
    }

    use_temperature = temperature if temperature is not None else config.temperature
    use_max_tokens = max_tokens if max_tokens is not None else config.max_tokens

    body: dict = {
        "model": config.name,
        "max_tokens": use_max_tokens,
        "temperature": use_temperature,
        "system": system,
        "messages": messages,
        "tools": tools,
    }
    if nonce:
        body["metadata"] = {"user_id": nonce}

    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            last_err = RuntimeError(f"HTTP {e.code}: {err_body}")
            if e.code in (429, 500, 502, 503, 504):
                if attempt < max_retries:
                    delay = DEFAULT_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "LLM(tool_use) transient 错误 HTTP %s，%ss 后重试 [%d/%d]",
                        e.code, delay, attempt, max_retries,
                    )
                    time.sleep(delay)
                    continue
            raise last_err
        except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead) as e:
            last_err = RuntimeError(f"网络错误: {e}")
            if attempt < max_retries:
                delay = DEFAULT_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "LLM(tool_use) 网络错误，%ss 后重试 [%d/%d]: %s",
                    delay, attempt, max_retries, e,
                )
                time.sleep(delay)
                continue
            raise last_err

    raise last_err or RuntimeError("LLM(tool_use) 重试耗尽")


def agent_loop(
    system: str,
    user_prompt: str,
    tools_schema: list[dict],
    tool_executor: "Callable[[str, dict], str]",
    config: Optional[LLMConfig] = None,
    max_iterations: int = 30,
    max_tokens_per_call: int = 8192,
    nonce: Optional[str] = None,
    verbose: bool = False,
) -> tuple[str, list[dict]]:
    """Co-sight Pro 原生 agent loop（不依赖 cosight）。

    流程：
    1. 用 tools schema 调用 LLM
    2. 若 stop_reason="end_turn" → 返回最终文本
    3. 若 stop_reason="tool_use" → 解析 content 里所有 tool_use 块
       → 调 tool_executor(name, input) 拿到 tool_result
       → 追加 tool_result 到 messages 重新调 LLM
    4. 循环直到 end_turn 或达到 max_iterations

    Args:
        system: 系统提示词
        user_prompt: 用户初始指令
        tools_schema: Anthropic 格式的工具 schema 列表
        tool_executor: 工具执行回调 (name, input) -> result_text
        config: LLMConfig
        max_iterations: 最大迭代次数（防 LLM 死循环）
        max_tokens_per_call: 每次调用的 max_tokens（agent 需要更大输出预算）
        nonce: 防 LLM API 端缓存
        verbose: 是否打印每轮 tool_use/tool_result 日志

    Returns:
        (final_text, full_messages) — 最终文本 + 完整 messages 轨迹
    """
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    for iteration in range(1, max_iterations + 1):
        if verbose:
            logger.info("[agent_loop] iter=%d 调 LLM, messages=%d 条", iteration, len(messages))

        resp = call_llm_with_tools(
            messages=messages,
            tools=tools_schema,
            system=system,
            config=config,
            max_tokens=max_tokens_per_call,
            nonce=nonce,
        )

        stop_reason = resp.get("stop_reason", "")
        content = resp.get("content", [])

        # 收集本轮的 text 块（作为 fallback 最终输出）
        text_parts: list[str] = []
        tool_use_blocks: list[dict] = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_use_blocks.append(block)

        if stop_reason == "end_turn" or not tool_use_blocks:
            final_text = "\n".join(text_parts) if text_parts else ""
            if verbose:
                logger.info(
                    "[agent_loop] 结束 at iter=%d, stop_reason=%s, text_len=%d",
                    iteration, stop_reason, len(final_text),
                )
            return final_text, messages

        # 把 assistant 的 content（text + tool_use）追加
        messages.append({"role": "assistant", "content": content})

        # 执行每个 tool_use
        tool_result_blocks: list[dict] = []
        for tu in tool_use_blocks:
            tool_name = tu.get("name", "")
            tool_input = tu.get("input", {}) or {}
            tool_id = tu.get("id", "")
            if verbose:
                logger.info(
                    "[agent_loop] iter=%d 调 tool: %s(%s)",
                    iteration, tool_name, list(tool_input.keys()),
                )
            try:
                result_text = tool_executor(tool_name, tool_input)
            except Exception as e:
                result_text = f"tool 执行异常: {type(e).__name__}: {e}"
            if verbose:
                logger.info(
                    "[agent_loop] iter=%d tool 返回 %d 字符",
                    iteration, len(result_text),
                )
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_result_blocks})

    logger.warning("[agent_loop] 达到 max_iterations=%d, 强制返回", max_iterations)
    return "", messages
