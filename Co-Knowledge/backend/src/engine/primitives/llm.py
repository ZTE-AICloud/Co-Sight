"""自研编排原语：LLM 调用链与响应类型。

替代 llama-index-core 0.10.31 的 `llms/custom.py`（`CustomLLM`）、`llms/llm.py`
（`LLM.predict` / `_get_prompt` / `_get_messages` / `_extend_messages` /
`stream_completion_response_to_tokens`）、`base/llms/types.py`（`CompletionResponse` /
`ChatResponse` / `LLMMetadata`）、`base/llms/generic_utils`（`messages_to_prompt` 等）。

**分派语义**：
  * `predict()`：`is_chat_model=True`（本仓适配器恒真）→ **走 chat 路径**
    （`_get_messages` → `format_messages` → `chat()` → `messages_to_prompt()`
    → `complete(..., formatted=True)`），返回值取 `chat_response.message.content or ''`；
  * `stream()`：基类实现是 chat 分发，但本仓适配器**覆盖**了它（自己拼 prompt），
    这里的实现只在未来新增适配器时兜底；
  * `stream_completion_response_to_tokens()`：`r.delta or ""` —— `delta` 必须每帧都设，
    只填 `text` 会得到一条"全是空串"的流。

**刻意不做**：callback/instrumentation 事件（全仓零订阅者）、异步 `a*` 变体、
`predict_and_call` / 工具调用、structured_predict / output_cls。
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Sequence

from engine.primitives.templating import (
    BasePromptTemplate,
    ChatMessage,
    MessageRole,
    messages_to_prompt,
)
from engine.logutil import logger

TokenGen = Iterator[str]


class CompletionResponse:
    """`complete()` / `stream_complete()` 的返回类型。"""

    def __init__(
            self,
            text: str = '',
            delta: Optional[str] = None,
            additional_kwargs: Optional[Dict[str, Any]] = None,
            raw: Optional[Any] = None,
    ) -> None:
        self.text = text
        self.delta = delta
        self.additional_kwargs = additional_kwargs or {}
        self.raw = raw

    def __repr__(self) -> str:
        return f'CompletionResponse(text={self.text!r}, delta={self.delta!r})'


class ChatResponse:
    """`chat()` 的返回类型（只用 `.message.content`）。"""

    def __init__(self, message: ChatMessage, raw: Optional[Any] = None) -> None:
        self.message = message
        self.raw = raw


class LLMMetadata:
    """LLM 元数据（本仓用到四项；`context_window` 参与合成截断的算术）。"""

    def __init__(
            self,
            context_window: int = 3900,
            num_output: int = 256,
            is_chat_model: bool = False,
            is_function_calling_model: bool = False,
            model_name: str = 'unknown',
    ) -> None:
        self.context_window = context_window
        self.num_output = num_output
        self.is_chat_model = is_chat_model
        self.is_function_calling_model = is_function_calling_model
        self.model_name = model_name


def completion_response_to_chat_response(completion_response: CompletionResponse) -> ChatResponse:
    return ChatResponse(
        message=ChatMessage(
            role=MessageRole.ASSISTANT,
            content=completion_response.text,
            additional_kwargs=completion_response.additional_kwargs,
        ),
        raw=completion_response.raw,
    )


def stream_completion_response_to_tokens(
        completion_response_gen: Iterator[CompletionResponse],
) -> TokenGen:
    """库实现全文：`for response in gen: yield response.delta or ""`。"""
    def gen() -> TokenGen:
        for response in completion_response_gen:
            yield response.delta or ''

    return gen()


class LLM:
    """LLM 基类（对应库的 `CustomLLM`）。子类需实现 `metadata` / `complete` / `stream_complete`。"""

    def __init__(
            self,
            system_prompt: Optional[str] = None,
            query_wrapper_prompt: Optional[Any] = None,
            output_parser: Optional[Any] = None,
            **kwargs: Any,
    ) -> None:
        # 与库一致：接受并忽略未知 kwargs（原库经 pydantic 收 Field 定义之外的 **kwargs）
        self.system_prompt = system_prompt
        self.query_wrapper_prompt = query_wrapper_prompt
        self.output_parser = output_parser
        self._kwargs = kwargs

    # ---- 子类实现面 ------------------------------------------------------
    @property
    def metadata(self) -> LLMMetadata:
        raise NotImplementedError

    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        raise NotImplementedError

    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> Iterator[CompletionResponse]:
        raise NotImplementedError

    # ---- chat 桥接（与 CustomLLM.chat 同形） ------------------------------
    def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        prompt = self.messages_to_prompt(messages)
        completion_response = self.complete(prompt, formatted=True, **kwargs)
        return completion_response_to_chat_response(completion_response)

    @staticmethod
    def messages_to_prompt(messages: Sequence[ChatMessage]) -> str:
        return messages_to_prompt(messages)

    # ---- 高层入口 --------------------------------------------------------
    def predict(self, prompt: BasePromptTemplate, **prompt_args: Any) -> str:
        """库 `LLM.predict` 的分派：chat 模型走 `chat()`，否则走 `complete()`。"""
        self._log_template_data(prompt, **prompt_args)

        if self.metadata.is_chat_model:
            messages = self._get_messages(prompt, **prompt_args)
            chat_response = self.chat(messages)
            output = chat_response.message.content or ''
        else:
            formatted_prompt = self._get_prompt(prompt, **prompt_args)
            response = self.complete(formatted_prompt, formatted=True)
            output = response.text
        return self._parse_output(output)

    def stream(self, prompt: BasePromptTemplate, **prompt_args: Any) -> TokenGen:
        """基类流式（chat 分发）。本仓适配器覆盖了自己的实现；此处仅作兜底。"""
        self._log_template_data(prompt, **prompt_args)

        if self.metadata.is_chat_model:
            # 库在此走 stream_chat → messages_to_prompt；本仓适配器覆盖了 stream()，
            # 这条兜底路径因此不可达（真需要时先补 stream_chat 的实现与用例）。
            raise NotImplementedError('stream_chat is not implemented for this LLM.')

        formatted_prompt = self._get_prompt(prompt, **prompt_args)
        stream_response = self.stream_complete(formatted_prompt, formatted=True)
        return stream_completion_response_to_tokens(stream_response)

    # ---- 内部工具（与库同名，适配器直接调用） -----------------------------
    def _get_prompt(self, prompt: BasePromptTemplate, **prompt_args: Any) -> str:
        formatted_prompt = prompt.format(llm=self, **prompt_args)
        if self.output_parser is not None:
            formatted_prompt = self.output_parser.format(formatted_prompt)
        return self._extend_prompt(formatted_prompt)

    def _get_messages(self, prompt: BasePromptTemplate, **prompt_args: Any) -> List[ChatMessage]:
        messages = prompt.format_messages(llm=self, **prompt_args)
        if self.output_parser is not None:
            messages = self.output_parser.format_messages(messages)
        return self._extend_messages(messages)

    def _extend_prompt(self, formatted_prompt: str) -> str:
        if self.system_prompt:
            raise NotImplementedError('system_prompt 仅支持 chat 路径（与库分支一致）。')
        return formatted_prompt

    def _extend_messages(self, messages: List[ChatMessage]) -> List[ChatMessage]:
        if self.system_prompt:
            messages = [ChatMessage(role=MessageRole.SYSTEM, content=self.system_prompt), *messages]
        return messages

    def _parse_output(self, output: str) -> str:
        if self.output_parser is not None:
            return str(self.output_parser.parse(output))
        return output

    def _log_template_data(self, prompt: BasePromptTemplate, **prompt_args: Any) -> None:
        """库版本走 callback_manager（本仓零订阅者）；这里只留 debug 日志。"""
        try:
            template_vars = {k: v for k, v in {**prompt.kwargs, **prompt_args}.items()
                             if k in prompt.template_vars}
            logger.debug(f'LLM template vars: {sorted(template_vars)}')
        except Exception:  # noqa: BLE001 —— 日志失败绝不影响调用
            pass
