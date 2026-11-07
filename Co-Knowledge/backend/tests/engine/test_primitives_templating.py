"""自研原语层：prompt 模板族（`engine/primitives/templating.py`）。

语义全部对照 llama-index-core 0.10.31 的 `prompts/base.py` 与
`base/llms/generic_utils.messages_to_prompt`，重点钉住三件容易被"顺手改进"的事：

  1. `format()` 对 **list 实参**不做任何加工 —— `{context_str}` 收到 list 时会落成
     list 的 repr（带转义 `\\n`）。这是有意保持的行为（非流式合成路径就这么发），
     **不许"修好"**；
  2. `partial_format()` 返回**副本**（原模板不受影响），固定值进 `kwargs` 参与后续 format；
  3. `messages_to_prompt()` 的形状：`"{role}: {content}"` 逐条 + 末尾 `"assistant: "`，
     `"\\n".join`（所以内容以换行结尾时会出现 `\\n\\nassistant: `）。

默认 prompt 文本的**长度**也在此钉住（753/188/324/17/111）——文本是从 wheel 里
程序化抽取的，长度是它没有被手改过的第一道哨兵。
"""
import pytest

from engine.primitives.prompts import (
    DEFAULT_CHOICE_SELECT_PROMPT_TMPL,
    DEFAULT_DESCRIPTION,
    DEFAULT_NAME,
    DEFAULT_SINGLE_SELECT_PROMPT_TMPL,
    DEFAULT_TEXT_QA_PROMPT_TMPL,
)
from engine.primitives.templating import (
    BasePromptTemplate,
    ChatMessage,
    MessageRole,
    PromptTemplate,
    PromptType,
    SelectorPromptTemplate,
    get_template_vars,
    messages_to_prompt,
    prompt_to_messages,
)


class _UpperParser:
    """最小 output_parser：库的 `SelectionOutputParser.format` 就是"追加一段转义文本"。"""

    def format(self, prompt: str) -> str:
        return prompt + '\n\n<追加的格式说明> {{escaped}}'


# --------------------------------------------------------------------------
# 默认文本（程序化抽取的哨兵）
# --------------------------------------------------------------------------
def test_default_prompt_lengths_are_pinned():
    assert len(DEFAULT_CHOICE_SELECT_PROMPT_TMPL) == 753
    assert len(DEFAULT_TEXT_QA_PROMPT_TMPL) == 188
    assert len(DEFAULT_SINGLE_SELECT_PROMPT_TMPL) == 324
    assert DEFAULT_NAME == 'query_engine_tool'
    assert len(DEFAULT_DESCRIPTION) == 111


def test_get_template_vars_matches_formatter_semantics():
    assert get_template_vars('a {x} b {y} c') == ['x', 'y']
    assert get_template_vars('无变量') == []


# --------------------------------------------------------------------------
# PromptTemplate
# --------------------------------------------------------------------------
def test_format_substitutes_vars_and_fixed_kwargs():
    prompt = PromptTemplate('Q={query_str} C={context_str}', prompt_type=PromptType.QUESTION_ANSWER)
    text = prompt.format(query_str='问题', context_str='上下文')
    assert text == 'Q=问题 C=上下文'
    assert prompt.metadata['prompt_type'] == PromptType.QUESTION_ANSWER


def test_format_renders_list_argument_as_list_repr():
    """**不许"修好"的既有行为**：非流式合成把 truncate 的返回值（list）直接塞进
    `{context_str}`，于是报文里是 `['...']` 这种 list 的 repr。"""
    prompt = PromptTemplate('C={context_str}')
    text = prompt.format(context_str=['第一行\n第二行'])
    assert text == "C=['第一行\\n第二行']"


def test_partial_format_returns_copy_and_merges_fixed_kwargs():
    prompt = PromptTemplate('Q={query_str} C={context_str}')
    partial = prompt.partial_format(query_str='固定问题')
    assert prompt.kwargs == {}          # 原模板不受影响
    assert partial.kwargs == {'query_str': '固定问题'}
    assert partial.format(context_str='ctx') == 'Q=固定问题 C=ctx'


def test_format_applies_output_parser_after_substitution():
    prompt = PromptTemplate('T={x}', output_parser=_UpperParser())
    assert prompt.format(x='v') == 'T=v\n\n<追加的格式说明> {{escaped}}'


def test_format_messages_wraps_single_user_message():
    prompt = PromptTemplate('Q={query_str}')
    messages = prompt.format_messages(query_str='问题')
    assert len(messages) == 1
    assert messages[0].role == MessageRole.USER
    assert messages[0].content == 'Q=问题'


def test_get_template_returns_raw_template():
    prompt = PromptTemplate('原样 {x}')
    assert prompt.get_template() == '原样 {x}'


# --------------------------------------------------------------------------
# SelectorPromptTemplate
# --------------------------------------------------------------------------
def test_selector_prompt_template_selects_default_and_delegates():
    inner = PromptTemplate('INNER {x}', prompt_type=PromptType.QUESTION_ANSWER)
    outer = SelectorPromptTemplate(default_template=inner, conditionals=None)
    assert outer.select() is inner
    assert outer.format(x='v') == 'INNER v'
    assert outer.get_template() == 'INNER {x}'


def test_selector_partial_format_propagates_to_default_template():
    outer = SelectorPromptTemplate(default_template=PromptTemplate('Q={q} C={c}'))
    partial = outer.partial_format(q='固定')
    assert partial.kwargs == {'q': '固定'}
    assert partial.format(c='ctx') == 'Q=固定 C=ctx'
    assert outer.default_template.kwargs == {}   # 原模板不受影响


def test_selector_partial_format_returns_selector_type():
    outer = SelectorPromptTemplate(default_template=PromptTemplate('x'))
    assert isinstance(outer.partial_format(), SelectorPromptTemplate)
    assert isinstance(outer.partial_format(), BasePromptTemplate)


# --------------------------------------------------------------------------
# 消息与 messages_to_prompt
# --------------------------------------------------------------------------
def test_prompt_to_messages_uses_user_role():
    msgs = prompt_to_messages('内容')
    assert msgs[0].role == MessageRole.USER and msgs[0].content == '内容'


def test_messages_to_prompt_shape_with_and_without_trailing_newline():
    # 正文不以换行结尾：`user: X\nassistant: `
    assert messages_to_prompt([ChatMessage(MessageRole.USER, 'X')]) == 'user: X\nassistant: '
    # 正文以换行结尾（重排/合成的模板都以 \n 收尾）：出现 `\n\nassistant: `（指纹里就是这个形状）
    assert messages_to_prompt([ChatMessage(MessageRole.USER, 'Answer:\n')]) == \
        'user: Answer:\n\nassistant: '


def test_messages_to_prompt_includes_system_and_additional_kwargs():
    msgs = [ChatMessage(MessageRole.SYSTEM, 'S'),
            ChatMessage(MessageRole.USER, 'U', additional_kwargs={'k': 'v'})]
    assert messages_to_prompt(msgs) == "system: S\nuser: U\n{'k': 'v'}\nassistant: "


# --------------------------------------------------------------------------
# 其它
# --------------------------------------------------------------------------
def test_prompt_type_values_match_library():
    # 值必须与库一致：openai_llm.stream() 按 metadata['prompt_type'] 分派
    assert PromptType.QUESTION_ANSWER.value == 'text_qa'
    assert PromptType.SINGLE_SELECT.value == 'single_select'
    assert PromptType.CHOICE_SELECT.value == 'choice_select'


@pytest.mark.parametrize('cls', [PromptTemplate])
def test_base_is_abstract(cls):
    with pytest.raises(TypeError):
        BasePromptTemplate()  # 抽象类不可实例化
