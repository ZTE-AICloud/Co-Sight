"""自研原语层：LLM 调用链（`engine/primitives/llm.py`）。

这一层替代 llama-index 的 `CustomLLM` / `LLM.predict` 分派，重点钉住三件事：

  1. **`predict()` 对 chat 模型走 chat 路径**：`format_messages` → `messages_to_prompt`
     （`"user: X" + "\\n" + "assistant: "`）→ `complete(prompt, formatted=True)`，
     返回值取 `chat_response.message.content or ''`。重排与合成两条路都吃这个形状，
     指纹基线里有它逐字的痕迹；
  2. `stream_completion_response_to_tokens()` 取 `delta or ""` —— 只填 `text` 不填
     `delta` 会退化成"全是空串的流"（历史上的静默故障）；
  3. 非 chat 模型走 `complete()`（`_get_prompt`）。

模块目前是**死代码**（原语层的 P2 步）：适配器换基类必须与 P4 的算子换基类一起原子
落地 —— 库的 `LLMRerank`/`QueryFusionRetriever`/`RouterQueryEngine` 把 `llm` 当
pydantic 字段校验，替换早了会先炸它们（指纹对拍实测）。
"""
import pytest

from engine.primitives.llm import (
    ChatResponse,
    CompletionResponse,
    LLM,
    LLMMetadata,
    completion_response_to_chat_response,
    stream_completion_response_to_tokens,
)
from engine.primitives.templating import (
    ChatMessage,
    MessageRole,
    PromptTemplate,
    SelectorPromptTemplate,
)


class _FakeLLM(LLM):
    """记录 complete/stream_complete 收到的**最终字符串**。"""

    def __init__(self, is_chat_model=True, output_parser=None, system_prompt=None):
        super().__init__(output_parser=output_parser, system_prompt=system_prompt)
        self._is_chat_model = is_chat_model
        self.completed_prompts = []
        self.completion_text = '模型答案'
        self.deltas = ['帧1', '帧2', '', '[DONE]']  # 含空 delta，验证 `or ""` 语义

    @property
    def metadata(self):
        return LLMMetadata(context_window=8000, num_output=8000,
                           is_chat_model=self._is_chat_model, model_name='fake')

    def complete(self, prompt, formatted=False, **kwargs):
        self.completed_prompts.append(prompt)
        return CompletionResponse(text=self.completion_text)

    def stream_complete(self, prompt, formatted=False, **kwargs):
        self.completed_prompts.append(prompt)
        accumulated = ''
        for delta in self.deltas:
            accumulated += delta
            yield CompletionResponse(text=accumulated, delta=delta)


# --------------------------------------------------------------------------
# predict 分派
# --------------------------------------------------------------------------
def test_predict_chat_model_goes_through_messages_to_prompt():
    llm = _FakeLLM(is_chat_model=True)
    prompt = PromptTemplate('Q={query_str}')
    result = llm.predict(prompt, query_str='问题')

    assert result == '模型答案'
    # 关键形状：单条 user 消息 + 末尾 assistant 前缀（库的 generic messages_to_prompt）
    assert llm.completed_prompts == ['user: Q=问题\nassistant: ']


def test_predict_chat_model_returns_empty_string_when_content_none():
    llm = _FakeLLM(is_chat_model=True)
    llm.completion_text = ''
    assert llm.predict(PromptTemplate('x')) == ''


def test_predict_non_chat_model_goes_through_format():
    llm = _FakeLLM(is_chat_model=False)
    result = llm.predict(PromptTemplate('Q={query_str}'), query_str='问题')
    assert result == '模型答案'
    # 非 chat：直接 format，不经 messages_to_prompt
    assert llm.completed_prompts == ['Q=问题']


def test_predict_applies_output_parser_to_the_output():
    class _Parser:
        """库的 `BaseOutputParser` 契约：chat 路径先过 `format_messages`，
        最终输出过 `parse`（两者都要有 —— 只实现 parse 会 AttributeError）。"""

        def __init__(self):
            self.format_messages_calls = 0

        def format_messages(self, messages):
            self.format_messages_calls += 1
            return messages

        def parse(self, output):
            return f'<{output}>'

    parser = _Parser()
    llm = _FakeLLM(is_chat_model=True, output_parser=parser)
    assert llm.predict(PromptTemplate('x')) == '<模型答案>'
    assert parser.format_messages_calls == 1


def test_predict_accepts_selector_prompt_template():
    llm = _FakeLLM(is_chat_model=True)
    prompt = SelectorPromptTemplate(default_template=PromptTemplate('S={x}'))
    llm.predict(prompt, x='v')
    assert llm.completed_prompts == ['user: S=v\nassistant: ']


def test_predict_with_system_prompt_prepends_system_message():
    llm = _FakeLLM(is_chat_model=True, system_prompt='你是助手')
    llm.predict(PromptTemplate('x'))
    assert llm.completed_prompts == ['system: 你是助手\nuser: x\nassistant: ']


# --------------------------------------------------------------------------
# 流式：delta or ""
# --------------------------------------------------------------------------
def test_stream_completion_response_to_tokens_uses_delta_or_empty():
    def gen():
        yield CompletionResponse(text='abc', delta='a')
        yield CompletionResponse(text='abc', delta=None)   # 只有 text → 空串
        yield CompletionResponse(text='abc', delta='')

    assert list(stream_completion_response_to_tokens(gen())) == ['a', '', '']


def test_stream_complete_frames_carry_delta():
    llm = _FakeLLM(is_chat_model=True)
    gen = llm.stream_complete('p')
    tokens = list(stream_completion_response_to_tokens(gen))
    assert tokens == ['帧1', '帧2', '', '[DONE]']


# --------------------------------------------------------------------------
# 响应类型
# --------------------------------------------------------------------------
def test_completion_response_to_chat_response_shape():
    resp = completion_response_to_chat_response(CompletionResponse(text='答案'))
    assert isinstance(resp, ChatResponse)
    assert resp.message.role == MessageRole.ASSISTANT
    assert resp.message.content == '答案'


def test_completion_response_defaults():
    resp = CompletionResponse()
    assert resp.text == '' and resp.delta is None and resp.additional_kwargs == {}


def test_llm_metadata_defaults_match_library():
    md = LLMMetadata()
    assert md.context_window == 3900 and md.num_output == 256
    assert md.is_chat_model is False and md.model_name == 'unknown'


# --------------------------------------------------------------------------
# 消息与基类约定
# --------------------------------------------------------------------------
def test_messages_to_prompt_uses_generic_format():
    messages = [ChatMessage(MessageRole.USER, 'U')]
    assert LLM.messages_to_prompt(messages) == 'user: U\nassistant: '


def test_base_llm_hooks_are_not_implemented():
    llm = LLM()
    with pytest.raises(NotImplementedError):
        _ = llm.metadata
    with pytest.raises(NotImplementedError):
        llm.complete('p')
    with pytest.raises(NotImplementedError):
        llm.stream_complete('p')
