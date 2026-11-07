"""LLM 适配器的真流式回归：`stream_complete()` / `generate_answer_stream()`。

这一层之前是「假流式」（`stream_complete` 只 yield 一帧完整结果、`generate_answer_stream`
yield 一整个 JSON 串）。改成真 SSE 后，下面每一条都是**行为契约**：

  1. 帧序列：`<think>` → 推理文本 → `</think>` → 正文 → `[DONE]`；
  2. **每帧 `delta` 必须是非空字符串** —— llama-index 的
     `stream_completion_response_to_tokens()` 取的是 `r.delta or ""`，只填 `text`
     会得到一条「全是空串」的流（HTTP 200、看起来完全正常、前端一个字都收不到）。
     这是本次改动最容易被改回去的坑，所以既直接断言 `delta`，也走一遍 llama-index
     自己的转换函数；
  3. 敏感词滑窗：不足一个窗口整帧不发、跨 chunk 断词要能拼起来屏蔽（等长 `*`）、
     流结束时窗口里的残余尾巴不能丢；
  4. 词表走 `get_sensitive_words()` 懒加载 —— 直读 `sensitive_words_cache` 在冷启动
     会拿到 `[]`，滑窗被**静默跳过**（不报错，但合规上等于没屏蔽）；
  5. `[DONE]` / 异常分支的收尾。

全程 monkeypatch `requests.post`，喂手写帧序列，不碰网络。
"""
import json

import pytest


from engine.primitives.llm import stream_completion_response_to_tokens

import engine.settings as config
import engine.i18n as i18n
from model.models import ModelRecord, new_model_id
from model.repository import InMemoryModelStore
from model import resolver as model_resolver
from engine.common.beans.rag_request import RagRequest
from engine.common.beans.rag_request_headers import RagRequestHeaders
from engine.common.exception.rag_exception import RagException
from engine.cache import chat_memory
from engine.config_loader import black_list_loader
from engine.custom_llm import openai_llm
from engine.custom_llm.openai_llm import (
    REDACTED_THINKING_CLOSE, REDACTED_THINKING_OPEN, OpenAICompatLLM, prepare_text_data)

CONVERSATION_ID = 'd-llm-stream-1'
FAIL_TEXT = i18n.get_i18n_safe('zh', 'request-llm-failed')


# ---------------------------------------------------------------------------
# 假上游：手写帧序列，不碰网络
# ---------------------------------------------------------------------------

class _FakeStreamResponse:
    """`requests.post(..., stream=True)` 返回值的最小替身。

    `iter_lines(decode_unicode=True)` 模仿 requests 的真实行为：`text/event-stream`
    不带 charset 时按 **ISO-8859-1** 解码 —— 所以中文只有被测代码显式把 `encoding`
    指回 utf-8 之后才是对的（否则拿到乱码，这里的断言会红）。
    """

    def __init__(self, frames, status_code=200):
        self.status_code = status_code
        self.text = 'upstream body'
        self.encoding = None  # requests 由 content-type 推导；text/* → ISO-8859-1
        self._frames = list(frames)
        self.closed = False

    def iter_lines(self, decode_unicode=False, **kwargs):
        codec = self.encoding or 'ISO-8859-1'
        for frame in self._frames:
            if isinstance(frame, Exception):
                raise frame
            yield frame.encode('utf-8').decode(codec) if decode_unicode else frame.encode('utf-8')

    def close(self):
        self.closed = True


class _FakeJsonResponse:
    """非流式 `requests.post` 的替身（`_chat` 那条路）。"""

    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self.text = json.dumps(payload)
        self._payload = payload

    def json(self):
        return self._payload


def _install_fake_post(monkeypatch, frames=(), status_code=200, payload=None):
    """换掉 `requests.post`，记录每次调用（url/body/stream/...），返回记录列表。"""
    captured = []

    def fake_post(url, json=None, headers=None, timeout=None, stream=False, **kwargs):
        call = {'url': url, 'body': json, 'headers': headers, 'timeout': timeout, 'stream': stream}
        call['response'] = (_FakeStreamResponse(frames, status_code=status_code) if stream
                            else _FakeJsonResponse(payload if payload is not None else {},
                                                   status_code=status_code))
        captured.append(call)
        return call['response']

    monkeypatch.setattr(openai_llm.egress, 'post', fake_post)
    return captured


def _frame(delta_or_payload):
    """一帧 SSE 文本。dict → `delta` 帧；字符串（如 `[DONE]`）→ 原样载荷。"""
    if isinstance(delta_or_payload, str):
        payload = delta_or_payload
    else:
        payload = json.dumps({'choices': [{'index': 0, 'delta': delta_or_payload}]},
                             ensure_ascii=False)
    return 'data: ' + payload


def _content(delta):
    return json.loads(delta)['output']['content']


def _texts(deltas):
    """delta 序列 → 可读文本：JSON 帧取 `output.content`，结束帧 `[DONE]` 原样。"""
    return [d if d == '[DONE]' else _content(d) for d in deltas]


@pytest.fixture(autouse=True)
def isolated_black_list(monkeypatch):
    """每个用例都从「没有黑名单、没有预热缓存」的干净状态开始。"""
    monkeypatch.setitem(config.Config, 'black_list_dir', '')
    black_list_loader.sensitive_words_cache.clear()
    yield
    black_list_loader.sensitive_words_cache.clear()


@pytest.fixture(autouse=True)
def isolated_model_registry(monkeypatch):
    """解析层有模块级缓存；注册表用例前后都要失效，避免跨用例串味。"""
    monkeypatch.delenv('GENERATION_CHAT_TEMPLATE_KWARGS', raising=False)
    model_resolver.invalidate()
    yield
    model_resolver.invalidate()


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setenv('GENERATION_GATEWAY_URL', 'http://gateway.test/v1')
    monkeypatch.setenv('GENERATION_MODEL', 'deepseek-chat')
    chat_memory.user_chat_question_cache.clear()
    user_request = RagRequest(question='知识库怎么用？', conversation_id=CONVERSATION_ID, stream=True)
    return OpenAICompatLLM(context_window=10240, config_info={
        'user_request': user_request,
        'headers': RagRequestHeaders(language_option='zh'),
        'llm': 'deepseek-chat',
    })


def _use_registry(monkeypatch, records):
    store = InMemoryModelStore(records)
    monkeypatch.setattr(model_resolver, '_make_store', lambda: store)
    model_resolver.invalidate()


def _registry_llm(thinking_off=True, model_name='deepseek-chat', **kwargs):
    base = dict(
        model_id=new_model_id(), model_kind='llm', model_name=model_name,
        base_url='http://registry.test/v1', is_default=True,
        thinking_mode='custom' if thinking_off else 'none',
        thinking_payload=({'chat_template_kwargs': {'thinking': False}}
                          if thinking_off else None))
    base.update(kwargs)
    return ModelRecord(**base)


def _use_vocabulary(llm, monkeypatch, tmp_path, content, name='politics'):
    """挂一个真实词表目录（`*.txt`，`|#|` 分隔），让算子声明它。"""
    (tmp_path / (name + '.txt')).write_text(content, encoding='utf-8')
    monkeypatch.setitem(config.Config, 'black_list_dir', str(tmp_path))
    llm.config_info['black_vocabulary'] = name


# ---------------------------------------------------------------------------
# 1/2. 正常链 + delta 非空
# ---------------------------------------------------------------------------

def test_reasoning_then_content_is_wrapped_with_think_markers(llm, monkeypatch):
    """推理模型的实际帧序：若干 reasoning_content → 若干 content → [DONE]。"""
    _install_fake_post(monkeypatch, [
        _frame({'reasoning_content': '先想'}),
        _frame({'reasoning_content': '再想'}),
        _frame({'content': '正文'}),
        _frame({'content': '继续'}),
        _frame('[DONE]'),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == [REDACTED_THINKING_OPEN, '先想', '再想', REDACTED_THINKING_CLOSE,
                     '正文', '继续', '[DONE]']
    # 顺序也要对：<think> 在最前、</think> 之后才是正文
    joined = ''.join(t for t in texts if t != '[DONE]')
    assert joined == '<think>先想再想</think>正文继续'


def test_every_frame_carries_a_non_empty_delta(llm, monkeypatch):
    """钉住潜伏 bug：`CompletionResponse` 不设 `delta` 时，llama-index 会产出全空流。

    `stream_completion_response_to_tokens()` 的实现就是 `r.delta or ""` ——
    只设 `text` 的话，HTTP 200、帧数正常、每个 token 都是空串，前端一片空白。
    """
    _install_fake_post(monkeypatch, [
        _frame({'reasoning_content': '推理'}),
        _frame({'content': '答'}),
        _frame('[DONE]'),
    ])

    responses = list(llm.stream_complete('问题'))
    assert responses, '至少要产出帧'
    for response in responses:
        assert isinstance(response.delta, str), 'delta 必须是 str（llama-index 取 `r.delta or ""`）'
        assert response.delta, 'delta 不能是空串/None —— 那就是「假成功、零输出」的流'

    # 再走一遍 llama-index 自己的转换（就是 `r.delta or ""` 那行）：
    # token 必须能还原出正文，而不是一串空串
    tokens = list(stream_completion_response_to_tokens(llm.stream_complete('问题')))
    assert all(isinstance(token, str) and token for token in tokens)
    assert tokens[-1] == '[DONE]'
    assert ''.join(_content(t) for t in tokens if t != '[DONE]') == '<think>推理</think>答'


def test_blank_and_comment_lines_are_skipped(llm, monkeypatch):
    """SSE 允许空行作分隔、`:` 开头作注释（心跳）；即使上游不发，也必须能跳过。"""
    _install_fake_post(monkeypatch, ['', ': heartbeat', _frame({'content': '正文'}), '',
                                     _frame('[DONE]'), ''])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['正文', '[DONE]']


def test_content_containing_done_literal_does_not_end_the_stream(llm, monkeypatch):
    """正文里出现 "[DONE]" 不能当结束帧（否则答案被静默截断）。

    判据必须是整帧相等，不能用子串判断 `'[DONE]' in data`；
    否则正文里出现该字面量会截断答案。
    """
    _install_fake_post(monkeypatch, [
        _frame({'content': '前[DONE]后'}),
        _frame({'content': '继续'}),
        _frame('[DONE]'),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['前[DONE]后', '继续', '[DONE]']


# ---------------------------------------------------------------------------
# 3. 敏感词滑窗
# ---------------------------------------------------------------------------

def test_frames_below_window_size_are_buffered_not_emitted(llm, monkeypatch, tmp_path):
    """单帧不足一个窗口 → 一帧都不发（等后续 chunk 拼齐再判定）。"""
    _use_vocabulary(llm, monkeypatch, tmp_path, '敏感词ABC|#|词乙')  # max_kw_len=6 → window=6
    _install_fake_post(monkeypatch, [
        _frame({'content': '短'}), _frame({'content': '句'}), _frame({'content': '。'}),
        _frame('[DONE]'),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    # 三帧被窗口吞掉、在 [DONE] 处合成一帧冲出 —— 而不是逐帧直发
    assert texts == ['短句。', '[DONE]']


def test_keyword_split_across_chunks_is_masked(llm, monkeypatch, tmp_path):
    """跨 chunk 断词：'敏感' + '词ABC' 拼起来正好是完整词，必须等长屏蔽。"""
    _use_vocabulary(llm, monkeypatch, tmp_path, '敏感词ABC|#|词乙')
    _install_fake_post(monkeypatch, [
        _frame({'content': '敏感'}),
        _frame({'content': '词ABC'}),
        _frame('[DONE]'),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['******', '[DONE]']
    assert '敏感词ABC' not in ''.join(texts)


def test_tail_residue_is_flushed_at_done(llm, monkeypatch, tmp_path):
    """窗口里的残留尾巴（< 一个窗口）在 [DONE] 时冲出 —— 正文尾巴不能丢。"""
    _use_vocabulary(llm, monkeypatch, tmp_path, '敏感词ABC|#|词乙')
    _install_fake_post(monkeypatch, [
        _frame({'content': '敏感'}), _frame({'content': '词ABC'}), _frame({'content': '记录'}),
        _frame('[DONE]'),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['******', '记录', '[DONE]']


def test_tail_residue_is_flushed_even_without_done_frame(llm, monkeypatch, tmp_path):
    """连接没等到 `[DONE]` 就断了：尾巴照样冲、再补一个结束帧。"""
    _use_vocabulary(llm, monkeypatch, tmp_path, '敏感词ABC|#|词乙')
    _install_fake_post(monkeypatch, [
        _frame({'content': '敏感'}), _frame({'content': '词ABC'}), _frame({'content': '记录'}),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['******', '记录', '[DONE]']


def test_reasoning_content_is_not_filtered_by_the_window(llm, monkeypatch, tmp_path):
    """已知限制：推理内容不走敏感词滑窗，正文走。

    不是缺陷 —— 但把行为钉下来，防止有人「顺手」给推理也加个窗口、
    或反过来把正文的窗口摘掉。
    """
    _use_vocabulary(llm, monkeypatch, tmp_path, '敏感词ABC|#|词乙')
    _install_fake_post(monkeypatch, [
        _frame({'reasoning_content': '敏感词ABC'}),
        _frame({'content': '敏感词ABC'}),
        _frame('[DONE]'),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['<think>', '敏感词ABC', '</think>', '******', '[DONE]']


# ---------------------------------------------------------------------------
# 4. native_thinking_in_content
# ---------------------------------------------------------------------------

def test_native_thinking_in_content_disables_reasoning_wrapping(llm, monkeypatch):
    """模型自己往 content 里写 `<think>`：整条 reasoning 解析路径关闭，不重复包。"""
    _install_fake_post(monkeypatch, [
        _frame({'content': '<think>模型自己写的思考'}),
        _frame({'reasoning_content': '外部推理'}),
        _frame({'content': '正文</think>'}),
        _frame('[DONE]'),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['<think>模型自己写的思考', '正文</think>', '[DONE]']
    assert '外部推理' not in ''.join(texts), '已关闭的路径不该再吐出推理帧'
    assert ''.join(texts).count('<think>') == 1, '不能重复包一层 <think>'


# ---------------------------------------------------------------------------
# 5. 结束 / 异常分支
# ---------------------------------------------------------------------------

def test_upstream_exception_yields_failure_text_then_done(llm, monkeypatch):
    """上游中途抛：收尾必须是失败文案 + `[DONE]`，调用方不会拿到半截流。"""
    captured = _install_fake_post(monkeypatch, [
        _frame({'content': '开头'}),
        RuntimeError('connection reset by peer'),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['开头', FAIL_TEXT, '[DONE]']
    assert captured[-1]['response'].closed, '流没读完也要把连接关掉（finally）'


def test_non_2xx_raises_rag_exception_and_maps_to_failure_frame(llm, monkeypatch):
    """非 2xx 是错误，不是空流：`_chat_stream` 抛 RagException，上层翻成失败帧。"""
    _install_fake_post(monkeypatch, [], status_code=502)

    with pytest.raises(RagException) as excinfo:
        next(llm._chat_stream([{'role': 'user', 'content': '问题'}]))
    assert excinfo.value.get_error_tag() == 'request-model-gateway-failed'

    texts = _texts([r.delta for r in llm.stream_complete('问题')])
    assert texts == [FAIL_TEXT, '[DONE]']


def test_malformed_frame_falls_into_failure_branch(llm, monkeypatch):
    """半截/坏帧不能假装正常结束：走失败分支，日志里也看得到。"""
    _install_fake_post(monkeypatch, ['data: {"choices": ['])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == [FAIL_TEXT, '[DONE]']


def test_stream_history_is_saved_for_multiturn(llm, monkeypatch):
    """`finally` 里写会话历史（多轮改写依赖它），答不上来时也写。"""
    _install_fake_post(monkeypatch, [_frame({'reasoning_content': '推理'}),
                                     _frame({'content': '答案'}), _frame('[DONE]')])

    list(llm.stream_complete('问题', question='知识库怎么用？', related_context=['片段一']))

    history = chat_memory.get_chat_history(CONVERSATION_ID)
    assert history.question == '知识库怎么用？'
    assert history.contexts == ['片段一']
    # 历史里是裸答案：`<think>` 标记只出现在 delta 里，不进历史
    assert history.answer == '推理答案'


# ---------------------------------------------------------------------------
# 6. 冷启动：懒加载的黑名单
# ---------------------------------------------------------------------------

def test_cold_start_black_list_is_loaded_on_first_call(tmp_path, monkeypatch):
    """没有启动预热线程：第一次 `get_sensitive_words()` 就必须拿到词（懒加载）。"""
    (tmp_path / 'politics.txt').write_text('甲|#|乙丙', encoding='utf-8')
    monkeypatch.setitem(config.Config, 'black_list_dir', str(tmp_path))
    black_list_loader.sensitive_words_cache.clear()

    assert black_list_loader.get_sensitive_words('politics') == ['乙丙', '甲']


def test_cold_start_masking_works_on_the_very_first_stream(llm, monkeypatch, tmp_path):
    """词表在、但没预热过：第一次流式也必须屏蔽。

    直读 `sensitive_words_cache` 的写法在这里会拿到 `[]` → 滑窗整条被跳过 →
    正文原样吐出来（不报错，静默失效）。这条钉住那个坑。
    """
    _use_vocabulary(llm, monkeypatch, tmp_path, '乙丙')
    _install_fake_post(monkeypatch, [
        _frame({'content': '这里出现乙丙'}),
        _frame('[DONE]'),
    ])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['这里出现**', '[DONE]']


# ---------------------------------------------------------------------------
# 7. 复用与两条路（`stream()` 覆盖 / `generate_answer_stream` / `_chat` 不动）
# ---------------------------------------------------------------------------

def test_stream_override_formats_prompt_without_chat_dispatch(llm, monkeypatch):
    """`stream()` 必须自己拼 prompt 再 `stream_complete()`。

    `metadata.is_chat_model=True` 会让基类绕道 `stream_chat()`；这里断言真正发出去的
    prompt 就是 `{query_str}`/`{context_str}` 已替换过的模板（summarizer 的实际入参形态）。
    """
    from engine.primitives.templating import PromptTemplate
    from engine.primitives.templating import PromptType

    captured = _install_fake_post(monkeypatch, [_frame({'content': '答案'}), _frame('[DONE]')])
    template = PromptTemplate('问题：{query_str}\n上下文：{context_str}',
                              prompt_type=PromptType.QUESTION_ANSWER)
    prompt = template.partial_format(query_str='知识库怎么用？')  # summarizer 就是这么调的

    tokens = list(llm.stream(prompt, context_str=['|#|kb_a:片段一', '|#|kb_b:片段二']))

    assert captured[-1]['body']['messages'][-1]['content'] == \
        '问题：知识库怎么用？\n上下文：kb_a:片段一\nkb_b:片段二'
    assert captured[-1]['body']['stream'] is True
    assert ''.join(_content(t) for t in tokens if t != '[DONE]') == '答案'
    history = chat_memory.get_chat_history(CONVERSATION_ID)
    assert history.question == '知识库怎么用？'
    assert history.contexts == ['kb_a:片段一', 'kb_b:片段二']


def test_stream_override_with_non_qa_prompt_uses_the_template(llm, monkeypatch):
    """非 QA 模板（没有 prompt_type）走 `_get_prompt`，同样能流式。"""
    from engine.primitives.templating import PromptTemplate

    captured = _install_fake_post(monkeypatch, [_frame({'content': 'ok'}), _frame('[DONE]')])
    tokens = list(llm.stream(PromptTemplate('请回答：{topic}'), topic='天气'))

    assert captured[-1]['body']['messages'][-1]['content'] == '请回答：天气'
    assert ''.join(_content(t) for t in tokens if t != '[DONE]') == 'ok'


def test_summarizer_streaming_path_yields_app_frames(monkeypatch):
    """整条链路（不含网络）：真 `RagSimpleSummarizer` → llama-index → `llm.stream()` → 帧。

    这条是 `stream()` 覆盖存在的理由：summarizer 走的是 `LLM.stream()`，基类会因为
    `is_chat_model=True` 绕道 chat（另一条 prompt 拼装路径）；这里断言发出去的 prompt
    是 `{query_str}`/`{context_str}` 已替换过的模板，最终 token 是 app 要的形状。
    """
    from engine.primitives.models import NodeWithScore, TextNode

    from engine.response_synthesizer.simple_summarizer import RagSimpleSummarizer

    monkeypatch.setenv('GENERATION_GATEWAY_URL', 'http://gateway.test/v1')
    captured = _install_fake_post(monkeypatch, [
        _frame({'reasoning_content': '想一下'}), _frame({'content': '答案'}), _frame('[DONE]')])

    summarizer = RagSimpleSummarizer(streaming=True, config_info={
        'headers': RagRequestHeaders(language_option='zh', deepsearch=False),
        'user_request': RagRequest(question='知识库怎么用？', conversation_id=CONVERSATION_ID, stream=True),
        'generator-config': [{'llm': 'deepseek-chat'}],
    })
    node = NodeWithScore(node=TextNode(text='来源:片段一\n知识库要用工作流配置索引。'))

    response = summarizer.synthesize('知识库怎么用？', [node])
    texts = _texts(list(response.response_gen))

    assert texts == ['<think>', '想一下', '</think>', '答案', '[DONE]']
    prompt = captured[-1]['body']['messages'][-1]['content']
    assert '知识库怎么用？' in prompt
    assert '知识库要用工作流配置索引。' in prompt
    assert '{context_str}' not in prompt and '{query_str}' not in prompt


def test_generate_answer_stream_is_incremental(llm, monkeypatch):
    """空检索兜底也必须真流式：多个 `output` 帧，而不是一整个 JSON 串。"""
    captured = _install_fake_post(monkeypatch, [
        _frame({'reasoning_content': '推理'}),
        _frame({'content': '答'}),
        _frame({'content': '案'}),
        _frame('[DONE]'),
    ])

    deltas = list(llm.generate_answer_stream())
    texts = _texts(deltas)

    assert texts == ['<think>', '推理', '</think>', '答', '案', '[DONE]']
    assert len([d for d in deltas if d != '[DONE]']) > 1, '一帧一整个 JSON 就是假流式'
    for delta in deltas[:-1]:
        parsed = json.loads(delta)
        assert parsed['conversation_id'] == CONVERSATION_ID
        assert parsed['output']['type'] == 'text'
    assert captured[-1]['body']['stream'] is True
    assert '知识库怎么用？' in captured[-1]['body']['messages'][-1]['content']
    assert chat_memory.get_chat_history(CONVERSATION_ID).answer == '推理答案'


def test_generate_answer_stream_failure_still_ends_with_done(llm, monkeypatch):
    _install_fake_post(monkeypatch, [RuntimeError('boom')])

    texts = _texts(list(llm.generate_answer_stream()))

    assert texts == [FAIL_TEXT, '[DONE]']


def test_non_streaming_path_keeps_stream_false(llm, monkeypatch):
    """回归哨兵：改写/重排/非流式合成仍走 `_chat`（`stream: false` + 一次性读取）。"""
    captured = _install_fake_post(monkeypatch, payload={
        'choices': [{'message': {'content': '裸文本'}, 'finish_reason': 'stop'}]})

    result = llm.ask_llm('问题')

    assert result.json()['choices'][0]['message']['content'] == '裸文本'
    assert captured[-1]['body']['stream'] is False
    assert captured[-1]['stream'] is False


def test_stream_request_uses_utf8_and_eventsource(llm, monkeypatch):
    """请求侧：`stream=True` 直连、SSE 解码必须是 UTF-8（否则中文乱码）。"""
    captured = _install_fake_post(monkeypatch, [_frame({'content': '中文'}), _frame('[DONE]')])

    texts = _texts([r.delta for r in llm.stream_complete('问题')])

    assert texts == ['中文', '[DONE]']
    assert captured[-1]['stream'] is True
    assert captured[-1]['url'] == 'http://gateway.test/v1/chat/completions'
    assert captured[-1]['response'].encoding == 'utf-8'


def test_prepare_text_data_shape_is_stable():
    """帧载荷形状是下游（`app._streamer`）的契约，不能悄悄改。"""
    parsed = json.loads(prepare_text_data('d1', '正文'))

    assert parsed == {'conversation_id': 'd1', 'output': {'type': 'text', 'content': '正文'}}


# ---------------------------------------------------------------------------
# 6. reasoning_effort：按部署配置透传（deepseek-chat 的截断修复）
# ---------------------------------------------------------------------------

def test_chat_sends_reasoning_effort_when_configured(llm, monkeypatch):
    """配置了 `GENERATION_REASONING_EFFORT=none` 时，非流式请求必须带上该字段。

    背景：deepseek-chat 默认先输出 reasoning_content；重排/改写这种短输出会把
    max_tokens(8192) 烧在思考上，content 为空 → `llm-empty-content-truncated`，
    实测重排 63s 后才回落到前 N 条。
    """
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setitem(config.Config, 'generation_reasoning_effort', 'none')

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['body']['reasoning_effort'] == 'none'


def test_chat_omits_reasoning_effort_when_empty(llm, monkeypatch):
    """留空 = 不发送该字段（严格网关可能不认它）。"""
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setitem(config.Config, 'generation_reasoning_effort', '')

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert 'reasoning_effort' not in captured[-1]['body']


def test_stream_sends_reasoning_effort_when_configured(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, [_frame({'content': 'x'}), _frame('[DONE]')])
    monkeypatch.setitem(config.Config, 'generation_reasoning_effort', 'none')

    list(llm.stream_complete('问题'))

    assert captured[-1]['body']['reasoning_effort'] == 'none'


def test_chat_ignores_global_reasoning_effort_for_registry_endpoint(llm, monkeypatch):
    """注册表行是权威：行内 none 也要压住部署级 effort。"""
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setitem(config.Config, 'generation_reasoning_effort', 'none')
    _use_registry(monkeypatch, [_registry_llm(
        thinking_off=False, thinking_mode='none')])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert 'reasoning_effort' not in captured[-1]['body']


def test_chat_uses_registry_reasoning_effort_over_global(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setitem(config.Config, 'generation_reasoning_effort', 'none')
    _use_registry(monkeypatch, [_registry_llm(
        thinking_off=False, thinking_mode='custom',
        thinking_payload={'reasoning_effort': 'high'})])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['body']['reasoning_effort'] == 'high'


def test_stream_ignores_global_reasoning_effort_for_registry_endpoint(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, [_frame({'content': 'x'}), _frame('[DONE]')])
    monkeypatch.setitem(config.Config, 'generation_reasoning_effort', 'none')
    _use_registry(monkeypatch, [_registry_llm(
        thinking_off=False, thinking_mode='none')])

    list(llm.stream_complete('问题'))

    assert 'reasoning_effort' not in captured[-1]['body']


# ---------------------------------------------------------------------------
# 7. chat_template_kwargs：关闭推理模型的 thinking（deepseek-chat）
#
# 顶层 `reasoning_effort=none` 仍会思考；只有
# `chat_template_kwargs={"thinking": false}` 真正关闭（reasoning_tokens=0）。
# 算子级优先，部署级 `GENERATION_CHAT_TEMPLATE_KWARGS`
# 兜底；两者都不给 = 不发送该字段。
# ---------------------------------------------------------------------------

def test_chat_sends_operator_chat_template_kwargs(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    llm.config_info['chat_template_kwargs'] = {'thinking': False}

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': False}


def test_chat_template_kwargs_env_fallback(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{"thinking": false}')

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': False}


def test_operator_chat_template_kwargs_wins_over_env(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{"thinking": true}')
    llm.config_info['chat_template_kwargs'] = {'thinking': False}

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': False}


def test_chat_template_kwargs_omitted_by_default(llm, monkeypatch):
    """空 = 不发送（严格网关可能不认该字段）。"""
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.delenv('GENERATION_CHAT_TEMPLATE_KWARGS', raising=False)

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert 'chat_template_kwargs' not in captured[-1]['body']


def test_invalid_chat_template_kwargs_env_is_ignored(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{not-json')

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert 'chat_template_kwargs' not in captured[-1]['body']


def test_stream_sends_chat_template_kwargs(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, [_frame({'content': 'x'}), _frame('[DONE]')])
    llm.config_info['chat_template_kwargs'] = {'thinking': False}

    list(llm.stream_complete('问题'))

    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': False}


# ---------------------------------------------------------------------------
# 8. 注册表每模型开关
# ---------------------------------------------------------------------------

def test_chat_sends_registry_thinking_off(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    _use_registry(monkeypatch, [_registry_llm(thinking_off=True)])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['url'] == 'http://registry.test/v1/chat/completions'
    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': False}


def test_stream_sends_registry_thinking_off(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, [_frame({'content': 'x'}), _frame('[DONE]')])
    _use_registry(monkeypatch, [_registry_llm(thinking_off=True)])

    list(llm.stream_complete('问题'))

    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': False}


def test_registry_false_suppresses_the_global_env(llm, monkeypatch):
    """行内 false 是权威：不能被部署级变量重新打开。"""
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{"thinking": true}')
    _use_registry(monkeypatch, [_registry_llm(thinking_off=False)])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert 'chat_template_kwargs' not in captured[-1]['body']


def test_unregistered_model_uses_the_registry_default(llm, monkeypatch):
    """点名的模型没注册（典型：``.env`` 还留着占位名）→ 用注册表默认行，不碰 .env。"""
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{"thinking": false}')
    _use_registry(monkeypatch, [_registry_llm(model_name='other-model')])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['url'] == 'http://registry.test/v1/chat/completions'
    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': False}


def test_unregistered_model_uses_the_global_env_when_no_llm_is_enabled(llm, monkeypatch):
    """注册表里一条启用行都没有时，仍然回落 .env。"""
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setenv('GENERATION_CHAT_TEMPLATE_KWARGS', '{"thinking": false}')
    _use_registry(monkeypatch, [_registry_llm(model_name='other-model', enabled=False)])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['url'] == 'http://gateway.test/v1/chat/completions'
    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': False}


def test_operator_kwargs_wins_over_the_registry_switch(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    llm.config_info['chat_template_kwargs'] = {'thinking': True}
    _use_registry(monkeypatch, [_registry_llm(thinking_off=True)])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': True}


def test_registry_custom_payload_merges_arbitrary_keys(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    _use_registry(monkeypatch, [_registry_llm(
        thinking_off=False, thinking_mode='custom',
        thinking_payload={'thinking': {'type': 'disabled'},
                          'reasoning_effort': 'none'})])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    body = captured[-1]['body']
    assert body['thinking'] == {'type': 'disabled'}
    assert body['reasoning_effort'] == 'none'


def test_model_reasoning_effort_beats_global_config(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    monkeypatch.setitem(config.Config, 'generation_reasoning_effort', 'low')
    _use_registry(monkeypatch, [_registry_llm(
        thinking_off=False, thinking_mode='custom',
        thinking_payload={'reasoning_effort': 'none'})])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['body']['reasoning_effort'] == 'none'


def test_operator_reasoning_effort_wins_over_registry(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    llm.config_info['reasoning_effort'] = 'high'
    _use_registry(monkeypatch, [_registry_llm(
        thinking_off=False, thinking_mode='custom',
        thinking_payload={'reasoning_effort': 'none'})])

    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['body']['reasoning_effort'] == 'high'


def test_stream_merges_registry_custom_payload(llm, monkeypatch):
    captured = _install_fake_post(monkeypatch, [_frame({'content': 'x'}), _frame('[DONE]')])
    _use_registry(monkeypatch, [_registry_llm(
        thinking_off=False, thinking_mode='custom',
        thinking_payload={'thinking': {'type': 'disabled'}})])

    list(llm.stream_complete('问题'))

    assert captured[-1]['body']['thinking'] == {'type': 'disabled'}


def test_aux_profile_forces_off_while_answer_keeps_default(llm, monkeypatch):
    """改写/重排（aux）自动关思考；回答（answer）保留模型的默认/配置。"""
    _use_registry(monkeypatch, [_registry_llm(
        thinking_off=False, thinking_mode='none', model_name='deepseek-chat')])

    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    llm._chat([{'role': 'user', 'content': 'hi'}])
    assert 'chat_template_kwargs' not in captured[-1]['body']

    llm.config_info['thinking_profile'] = 'aux'
    llm._chat([{'role': 'user', 'content': 'hi'}])
    assert captured[-1]['body']['chat_template_kwargs'] == {'thinking': False}


def test_aux_profile_still_lets_operator_override(llm, monkeypatch):
    llm.config_info['thinking_profile'] = 'aux'
    llm.config_info['thinking_payload'] = {'reasoning_effort': 'high'}
    _use_registry(monkeypatch, [_registry_llm(
        thinking_off=False, thinking_mode='none', model_name='deepseek-chat')])

    captured = _install_fake_post(monkeypatch, payload={'choices': [{
        'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    llm._chat([{'role': 'user', 'content': 'hi'}])

    assert captured[-1]['body']['reasoning_effort'] == 'high'
