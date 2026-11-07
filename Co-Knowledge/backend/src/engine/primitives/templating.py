"""自研编排原语：prompt 模板族与消息类型。

替代 llama-index-core 0.10.31 的 `prompts/base.py`（`PromptTemplate` /
`SelectorPromptTemplate` / `BasePromptTemplate`）、`prompts/utils.get_template_vars`、
`base/llms/types.py` 的消息类型、`base/llms/generic_utils.messages_to_prompt`。

**语义**：
  * `format()`：`all_kwargs = {**self.kwargs, **kwargs}` → 变量映射 →
     `self.template.format(**mapped)`（`{context_str}` 收到 **list** 时会落成 list 的 repr，
    这是既定行为）→ 有 output_parser 时再 `output_parser.format(prompt)`；
  * `format_messages()`：`prompt_to_messages(format(...))` = 单条 `user` 消息；
  * `SelectorPromptTemplate`：`select(llm)` 选默认模板，`partial_format` 逐层下传；
  * `messages_to_prompt()`：`"{role}: {content}"` 逐条 + 末尾 `"assistant: "`，`"\\n".join`。

许可：行为与默认模板来自 llama-index-core（MIT）；本文件为独立重写实现。
"""
from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from enum import Enum
from string import Formatter
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


class MessageRole(str, Enum):
    SYSTEM = 'system'
    USER = 'user'
    ASSISTANT = 'assistant'
    FUNCTION = 'function'
    TOOL = 'tool'
    CHATBOT = 'chatbot'
    MODEL = 'model'


class ChatMessage:
    def __init__(self, role: MessageRole, content: str,
                 additional_kwargs: Optional[Dict[str, Any]] = None) -> None:
        self.role = role
        self.content = content
        self.additional_kwargs = additional_kwargs or {}


class PromptType(str, Enum):
    """与库同名同值（只保留本仓实际会用到的成员，值必须完全一致）。"""

    SUMMARY = 'summary'
    QUESTION_ANSWER = 'text_qa'
    REFINE = 'refine'
    SINGLE_SELECT = 'single_select'
    MULTI_SELECT = 'multi_select'
    CHOICE_SELECT = 'choice_select'
    CUSTOM = 'custom'


def get_template_vars(template_str: str) -> List[str]:
    """提取 `{var}` 变量名（库用 `string.Formatter().parse`，口径必须一致）。"""
    variables: List[str] = []
    formatter = Formatter()
    for _, variable_name, _, _ in formatter.parse(template_str):
        if variable_name:
            variables.append(variable_name)
    return variables


def prompt_to_messages(prompt: str) -> List[ChatMessage]:
    return [ChatMessage(role=MessageRole.USER, content=prompt)]


def messages_to_prompt(messages: Sequence[ChatMessage]) -> str:
    """库的 generic 实现：`"{role}: {content}"` 逐条 + 末尾 `"assistant: "`。"""
    string_messages = []
    for message in messages:
        string_message = f'{message.role.value}: {message.content}'
        if message.additional_kwargs:
            string_message += f'\n{message.additional_kwargs}'
        string_messages.append(string_message)
    string_messages.append(f'{MessageRole.ASSISTANT.value}: ')
    return '\n'.join(string_messages)


class BasePromptTemplate(ABC):
    def __init__(
            self,
            metadata: Optional[Dict[str, Any]] = None,
            template_vars: Optional[List[str]] = None,
            kwargs: Optional[Dict[str, Any]] = None,
            output_parser: Optional[Any] = None,
            template_var_mappings: Optional[Dict[str, Any]] = None,
            function_mappings: Optional[Dict[str, Callable]] = None,
    ) -> None:
        self.metadata: Dict[str, Any] = dict(metadata or {})
        self.template_vars: List[str] = list(template_vars or [])
        self.kwargs: Dict[str, Any] = dict(kwargs or {})
        self.output_parser = output_parser
        self.template_var_mappings: Dict[str, Any] = dict(template_var_mappings or {})
        self.function_mappings: Dict[str, Callable] = dict(function_mappings or {})

    # ---- 变量映射（与库同序：先 function 后 template） --------------------
    def _map_template_vars(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        template_var_mappings = self.template_var_mappings or {}
        return {template_var_mappings.get(k, k): v for k, v in kwargs.items()}

    def _map_function_vars(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        function_mappings = self.function_mappings or {}
        new_kwargs: Dict[str, Any] = {}
        for k, v in function_mappings.items():
            new_kwargs[k] = v(**kwargs)
        for k, v in kwargs.items():
            if k not in new_kwargs:
                new_kwargs[k] = v
        return new_kwargs

    def _map_all_vars(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return self._map_template_vars(self._map_function_vars(kwargs))

    @abstractmethod
    def partial_format(self, **kwargs: Any) -> 'BasePromptTemplate':
        ...

    @abstractmethod
    def format(self, llm: Optional[Any] = None, **kwargs: Any) -> str:
        ...

    @abstractmethod
    def format_messages(self, llm: Optional[Any] = None, **kwargs: Any) -> List[ChatMessage]:
        ...

    @abstractmethod
    def get_template(self, llm: Optional[Any] = None) -> str:
        ...


class PromptTemplate(BasePromptTemplate):
    def __init__(
            self,
            template: str,
            prompt_type: str = PromptType.CUSTOM,
            output_parser: Optional[Any] = None,
            metadata: Optional[Dict[str, Any]] = None,
            template_var_mappings: Optional[Dict[str, Any]] = None,
            function_mappings: Optional[Dict[str, Callable]] = None,
            **kwargs: Any,
    ) -> None:
        if metadata is None:
            metadata = {}
        metadata['prompt_type'] = prompt_type
        super().__init__(
            metadata=metadata,
            template_vars=get_template_vars(template),
            kwargs=kwargs,
            output_parser=output_parser,
            template_var_mappings=template_var_mappings,
            function_mappings=function_mappings,
        )
        self.template = template

    def partial_format(self, **kwargs: Any) -> 'PromptTemplate':
        # 库的写法：deepcopy 前先把 output_parser 摘掉（deepcopy 对它不友好）
        output_parser = self.output_parser
        self.output_parser = None
        try:
            prompt = copy.deepcopy(self)
        finally:
            self.output_parser = output_parser
        prompt.output_parser = output_parser
        prompt.kwargs.update(kwargs)
        return prompt

    def format(
            self,
            llm: Optional[Any] = None,
            completion_to_prompt: Optional[Callable[[str], str]] = None,
            **kwargs: Any,
    ) -> str:
        del llm  # 与库一致：未使用
        all_kwargs = {**self.kwargs, **kwargs}
        mapped_all_kwargs = self._map_all_vars(all_kwargs)
        prompt = self.template.format(**mapped_all_kwargs)

        if self.output_parser is not None:
            prompt = self.output_parser.format(prompt)

        if completion_to_prompt is not None:
            prompt = completion_to_prompt(prompt)

        return prompt

    def format_messages(self, llm: Optional[Any] = None, **kwargs: Any) -> List[ChatMessage]:
        del llm
        return prompt_to_messages(self.format(**kwargs))

    def get_template(self, llm: Optional[Any] = None) -> str:
        return self.template


class SelectorPromptTemplate(BasePromptTemplate):
    """按 llm 条件选择模板；本仓只用到 `default_template`（conditionals 恒为 None）。"""

    def __init__(
            self,
            default_template: BasePromptTemplate,
            conditionals: Optional[List[Tuple[Callable[[Any], bool], BasePromptTemplate]]] = None,
    ) -> None:
        super().__init__(
            metadata=default_template.metadata,
            template_vars=default_template.template_vars,
            kwargs=default_template.kwargs,
            output_parser=default_template.output_parser,
        )
        self.default_template = default_template
        self.conditionals = conditionals

    def select(self, llm: Optional[Any] = None) -> BasePromptTemplate:
        self.default_template.output_parser = self.output_parser
        if llm is None:
            return self.default_template
        if self.conditionals is not None:
            for condition, prompt in self.conditionals:
                if condition(llm):
                    prompt.output_parser = self.output_parser
                    return prompt
        return self.default_template

    def partial_format(self, **kwargs: Any) -> 'SelectorPromptTemplate':
        default_template = self.default_template.partial_format(**kwargs)
        if self.conditionals is None:
            conditionals = None
        else:
            conditionals = [(condition, prompt.partial_format(**kwargs))
                            for condition, prompt in self.conditionals]
        return SelectorPromptTemplate(default_template=default_template, conditionals=conditionals)

    def format(self, llm: Optional[Any] = None, **kwargs: Any) -> str:
        return self.select(llm=llm).format(**kwargs)

    def format_messages(self, llm: Optional[Any] = None, **kwargs: Any) -> List[ChatMessage]:
        return self.select(llm=llm).format_messages(**kwargs)

    def get_template(self, llm: Optional[Any] = None) -> str:
        return self.select(llm=llm).get_template(llm=llm)


class SingleSelectPrompt(PromptTemplate):
    """选择器用的 prompt：模板 + 输出解析器（`SINGLE_SELECT` 类型）。"""

    def __init__(self, template: str, output_parser: Any, prompt_type: str = PromptType.SINGLE_SELECT,
                 **kwargs: Any) -> None:
        super().__init__(template=template, prompt_type=prompt_type,
                         output_parser=output_parser, **kwargs)
