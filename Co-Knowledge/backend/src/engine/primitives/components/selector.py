"""自研编排原语：选择器（LLMSingleSelector 的对位实现）。

替代 llama-index-core 0.10.31 的 `selectors/llm_selectors.py`（`LLMSingleSelector` +
两个**下划线私有函数** `_build_choices_text` / `_structured_output_to_selector_result`）
+ `output_parsers/selection.py`（`SelectionOutputParser`/`Answer`/`StructuredOutput`）
+ `output_parsers/utils._marshal_llm_to_json`。

**四处语义**：
  * choices 文本：`"({n}) " + description 折叠换行为单行`，`"\\n\\n"` 连接；
  * `FORMAT_STR` 与其转义（`{`→`{{`）：它会被追加到模板尾部再走 `.format()`；
  * 解析链：`_marshal_llm_to_json`（先去转义、再按首个 `[`/`{` 定边界）→ `json.loads`
    → **yaml 兜底** → 空值抛 `ValueError("Failed to convert output to JSON: ...")`
    → `_filter_dict` 递归收敛到 `{choice, reason}`；
  * 0 基换算：`choice - 1`。
"""
from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from engine.primitives.interfaces import RagSelector
from engine.primitives.models import (
    QueryBundle,
    SelectorResult,
    SingleSelection,
    ToolMetadata,
)
from engine.primitives.prompts import DEFAULT_SINGLE_SELECT_PROMPT_TMPL
from engine.primitives.templating import PromptTemplate, PromptType

with contextlib.suppress(ImportError):
    import yaml


class OutputParserException(ValueError):
    """与库同名：解析失败时抛出（库继承自 Exception，本仓按 ValueError 归口）。"""


FORMAT_STR = """The output should be ONLY JSON formatted as a JSON instance.

Here is an example:
[
    {
        choice: 1,
        reason: "<insert reason for choice>"
    },
    ...
]
"""


def _escape_curly_braces(input_string: str) -> str:
    return input_string.replace('{', '{{').replace('}', '}}')


def _marshal_llm_to_json(output: str) -> str:
    """库实现：去掉 `{{`/`}}` 转义后，按首个 `[` 或 `{` 与最后一个 `]` 或 `}` 取子串。"""
    output = output.strip().replace('{{', '{').replace('}}', '}')
    left_square = output.find('[')
    left_brace = output.find('{')
    if left_square < left_brace and left_square != -1:
        left = left_square
        right = output.rfind(']')
    else:
        left = left_brace
        right = output.rfind('}')
    return output[left:right + 1]


@dataclass
class Answer:
    choice: int
    reason: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Answer':
        # 库经 dataclasses_json 解码（按类型注记强转）；数值字符串同样被接受
        return cls(choice=int(data['choice']), reason=str(data['reason']))


@dataclass
class StructuredOutput:
    raw_output: str
    parsed_output: Any


class SelectionOutputParser:
    """选择器输出解析器（对应库 `selectors` 用的 `SelectionOutputParser`）。"""

    REQUIRED_KEYS = frozenset(Answer.__annotations__)

    def _filter_dict(self, json_dict: Dict[str, Any]) -> Dict[str, Any]:
        output_dict = json_dict
        for key, val in json_dict.items():
            if key in self.REQUIRED_KEYS:
                continue
            elif isinstance(val, dict):
                output_dict = self._filter_dict(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        output_dict = self._filter_dict(item)
        return output_dict

    def _format_output(self, output: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        output_json = []
        for json_dict in output:
            valid = True
            for key in self.REQUIRED_KEYS:
                if key not in json_dict:
                    valid = False
                    break
            if not valid:
                json_dict = self._filter_dict(json_dict)
            output_json.append(json_dict)
        return output_json

    def parse(self, output: str) -> StructuredOutput:
        json_string = _marshal_llm_to_json(output)
        try:
            json_obj = json.loads(json_string)
        except json.JSONDecodeError as e_json:
            try:
                json_obj = yaml.safe_load(json_string)
            except NameError as exc:
                raise ImportError('Please pip install PyYAML.') from exc
            except yaml.YAMLError as e_yaml:
                raise OutputParserException(
                    f'Got invalid JSON object. Error: {e_json} {e_yaml}. '
                    f'Got JSON string: {json_string}'
                ) from e_yaml

        if isinstance(json_obj, dict):
            json_obj = [json_obj]

        if not json_obj:
            raise ValueError(f'Failed to convert output to JSON: {output!r}')

        json_output = self._format_output(json_obj)
        answers = [Answer.from_dict(json_dict) for json_dict in json_output]
        return StructuredOutput(raw_output=output, parsed_output=answers)

    def format(self, prompt_template: str) -> str:
        return prompt_template + '\n\n' + _escape_curly_braces(FORMAT_STR)


def _build_choices_text(choices: Sequence[ToolMetadata]) -> str:
    """库实现：`"({i+1}) " + 折叠换行的描述`，`"\\n\\n"` 连接（1 基编号）。"""
    texts: List[str] = []
    for ind, choice in enumerate(choices):
        text = ' '.join((choice.description or '').splitlines())
        text = f'({ind + 1}) {text}'
        texts.append(text)
    return '\n\n'.join(texts)


def _structured_output_to_selector_result(output: Any) -> SelectorResult:
    """库实现：把 `StructuredOutput.parsed_output`（Answer 列表）换算成 0 基选择。"""
    answers = output.parsed_output
    selections = [
        SingleSelection(index=answer.choice - 1, reason=answer.reason)
        for answer in answers
    ]
    return SelectorResult(selections=selections)


class SingleSelector(RagSelector):
    """`LLMSingleSelector` 的对位实现。"""

    def __init__(self, llm: Any, prompt: PromptTemplate) -> None:
        self._llm = llm
        self._prompt = prompt
        if self._prompt.output_parser is None:
            raise ValueError('Prompt should have output parser.')

    @classmethod
    def from_defaults(
            cls,
            llm: Optional[Any] = None,
            prompt_template_str: Optional[str] = None,
            output_parser: Optional[Any] = None,
    ) -> 'SingleSelector':
        # 与库一致：空串同样回落到默认模板（`or` 的语义，不是 `is None` 判断）
        prompt_template_str = prompt_template_str or DEFAULT_SINGLE_SELECT_PROMPT_TMPL
        output_parser = output_parser or SelectionOutputParser()
        prompt = PromptTemplate(
            template=prompt_template_str,
            prompt_type=PromptType.SINGLE_SELECT,
            output_parser=output_parser,
        )
        return cls(llm=llm, prompt=prompt)

    def _select(self, choices: Sequence[ToolMetadata], query: QueryBundle) -> SelectorResult:
        choices_text = _build_choices_text(choices)
        prediction = self._llm.predict(
            prompt=self._prompt,
            num_choices=len(choices),
            context_list=choices_text,
            query_str=query.query_str,
        )
        parse = self._prompt.output_parser.parse(prediction)
        return _structured_output_to_selector_result(parse)
