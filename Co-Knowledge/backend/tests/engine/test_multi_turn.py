"""多轮追问的两处行为约束：①零检索兜底用改写后的问题；②非流式+有命中补记历史。

改写算子（`query_rewrite`）每个请求都在跑，追问会被补全
（「那它的缺点呢？」→「向量检索的缺点是什么？」），检索拿到的也是改写后的问句。但：

  * 零检索兜底分支若用 `user_request.question`（用户原话），
    模型会反问「您说的'它'指什么？」；
  * 非流式 + 上一轮**有检索命中**时没有任何一处写 `chat_memory`，下一轮改写算子
    拿不到 `get_last_question(conversation_id)`，多轮同样断。

这里钉住的契约（全程 monkeypatch `requests.post`，不碰网络、不碰检索）：

  1. 零检索分支把 `QueryBundle.query_str`（已改写）传给 `generate_answer()` /
     `generate_answer_stream()`，流式/非流式两条路都如此，且历史里记的 question
     与本次实际问模型的问句一致（下一轮 last_question 才带实体）；
  2. 非流式 + 有节点合成成功后，`chat_memory` 里有 (改写后 question, contexts, answer)；
  3. 反例哨兵：重排算子形状的 `predict()`（内部走 `complete()`）**不写**历史 ——
     保存点如果放进 `complete()`，重排提示词会污染缓存。
"""
import json

import pytest
from engine.primitives.models import QueryBundle
from engine.common.beans.rag_request import RagRequest
from engine.common.beans.rag_request_headers import RagRequestHeaders
from engine.cache import chat_memory
from engine.custom_llm import openai_llm
from engine.custom_llm.openai_llm import OpenAICompatLLM
from engine.response_synthesizer.simple_summarizer import RagSimpleSummarizer

CONVERSATION_ID = 'd-multi-turn-1'
RAW_FOLLOW_UP = '那它的缺点呢？'          # 用户原话（带代词）
REWRITTEN_QUESTION = '向量检索的缺点是什么？'  # query_rewrite 的产出
ANSWER_TEXT = '向量检索的缺点是：召回依赖向量质量，对语义漂移敏感。'


class _FakeStreamResponse:
    """`requests.post(..., stream=True)` 的最小替身（`_chat_stream` 那条路）。"""

    def __init__(self, frames, status_code=200):
        self.status_code = status_code
        self.text = 'upstream body'
        self.encoding = None
        self._frames = list(frames)

    def iter_lines(self, decode_unicode=False, **kwargs):
        codec = self.encoding or 'ISO-8859-1'
        for frame in self._frames:
            yield frame.encode('utf-8').decode(codec) if decode_unicode else frame.encode('utf-8')

    def close(self):
        pass


class _FakeJsonResponse:
    """非流式 `requests.post` 的替身（`_chat` 那条路）。"""

    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)
        self._payload = payload

    def json(self):
        return self._payload


def _install_fake_post(monkeypatch, payload=None, frames=()):
    captured = []

    def fake_post(url, json=None, headers=None, timeout=None, stream=False, **kwargs):
        call = {'body': json, 'stream': stream}
        call['response'] = (_FakeStreamResponse(frames) if stream
                            else _FakeJsonResponse(payload if payload is not None else {}))
        captured.append(call)
        return call['response']

    monkeypatch.setattr(openai_llm.egress, 'post', fake_post)
    return captured


def _frame(payload):
    return 'data: ' + (payload if isinstance(payload, str)
                       else json.dumps(payload, ensure_ascii=False))


def _answer_payload(content=ANSWER_TEXT):
    return {'choices': [{'message': {'content': content}, 'finish_reason': 'stop'}]}


def _config_info(streaming):
    return {
        'headers': RagRequestHeaders(language_option='zh', deepsearch=False),
        # 用户原话是「那它的缺点呢？」——改写后的问句只存在于传给 synthesize 的 QueryBundle
        'user_request': RagRequest(question=RAW_FOLLOW_UP, conversation_id=CONVERSATION_ID,
                                   stream=streaming),
        'generator-config': [{'llm': 'deepseek-chat'}],
    }


@pytest.fixture(autouse=True)
def _clean_caches(monkeypatch):
    monkeypatch.setenv('GENERATION_GATEWAY_URL', 'http://gateway.test/v1')
    monkeypatch.setenv('GENERATION_MODEL', 'deepseek-chat')
    chat_memory.user_chat_question_cache.clear()
    yield
    chat_memory.user_chat_question_cache.clear()


# ---------------------------------------------------------------------------
# ① 零检索兜底用改写后的问句（流式 / 非流式两条路）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('query', [
    REWRITTEN_QUESTION,                          # str 形态
    QueryBundle(query_str=REWRITTEN_QUESTION),   # 真实现场的形态（改写算子原地改写的 bundle）
])
def test_zero_retrieval_non_streaming_uses_rewritten_query(monkeypatch, query):
    """非流式零检索：兜底提示词必须是改写后的问句，不是用户原话。"""
    captured = _install_fake_post(monkeypatch, payload=_answer_payload())
    summarizer = RagSimpleSummarizer(streaming=False, config_info=_config_info(streaming=False))

    response = summarizer.synthesize(query, [])

    prompt = captured[-1]['body']['messages'][-1]['content']
    assert REWRITTEN_QUESTION in prompt, '改写后的问句必须进兜底提示词'
    assert RAW_FOLLOW_UP not in prompt, '用户原话（带代词）不能再进兜底提示词'
    payload = json.loads(response.response)
    assert payload['conversation_id'] == CONVERSATION_ID
    assert payload['answer'] == ANSWER_TEXT
    # 历史里也记改写后的问句：下一轮 query_rewrite 取 last_question 时才有实体
    assert chat_memory.get_last_question(CONVERSATION_ID) == REWRITTEN_QUESTION


def test_zero_retrieval_streaming_uses_rewritten_query(monkeypatch):
    """流式零检索：同一契约（`generate_answer_stream` 那条路）。"""
    captured = _install_fake_post(monkeypatch, frames=[
        _frame({'choices': [{'index': 0, 'delta': {'content': '召回依赖'}}]}),
        _frame({'choices': [{'index': 0, 'delta': {'content': '向量质量。'}}]}),
        _frame('[DONE]'),
    ])
    summarizer = RagSimpleSummarizer(streaming=True, config_info=_config_info(streaming=True))

    response = summarizer.synthesize(QueryBundle(query_str=REWRITTEN_QUESTION), [])
    deltas = list(response.response_gen)

    prompt = captured[-1]['body']['messages'][-1]['content']
    assert REWRITTEN_QUESTION in prompt, '改写后的问句必须进兜底提示词'
    assert RAW_FOLLOW_UP not in prompt
    contents = [json.loads(d)['output']['content'] for d in deltas if d != '[DONE]']
    assert ''.join(contents) == '召回依赖向量质量。'
    assert deltas[-1] == '[DONE]'
    assert chat_memory.get_last_question(CONVERSATION_ID) == REWRITTEN_QUESTION


# ---------------------------------------------------------------------------
# ② 非流式 + 有节点：合成成功后补记会话历史
# ---------------------------------------------------------------------------

def test_non_streaming_with_nodes_saves_chat_history(monkeypatch):
    """非流式 + 有检索命中：合成成功后必须留下 (question, contexts, answer)。

    缺这一步时，下一轮 `get_last_question()` 为空 → 改写算子拿不到 last_question。
    """
    from engine.primitives.models import NodeWithScore, TextNode

    _install_fake_post(monkeypatch, payload=_answer_payload())
    summarizer = RagSimpleSummarizer(streaming=False, config_info=_config_info(streaming=False))
    node = NodeWithScore(node=TextNode(text='来源:片段一\n知识库要用工作流配置索引。'))

    response = summarizer.synthesize(QueryBundle(query_str=REWRITTEN_QUESTION), [node])

    assert response.response == ANSWER_TEXT
    history = chat_memory.get_chat_history(CONVERSATION_ID)
    assert history is not None, '非流式有命中的合成成功后必须写会话历史'
    assert history.question == REWRITTEN_QUESTION  # 与流式路径同一口径：记改写后问句
    assert history.contexts == ['来源:片段一\n知识库要用工作流配置索引。']  # `|#|` 内部标记已剥掉
    assert history.answer == ANSWER_TEXT


def test_rerank_shaped_predict_does_not_write_chat_history(monkeypatch):
    """反例哨兵：重排算子形状的 `predict()`（内部走 `complete()`）不写会话历史。

    保存点如果在 `complete()` 里，重排提示词会被当成「上一轮问题」写进缓存 ——
    等价于把多轮断掉。这条钉住保存点只能在合成侧（`save_synthesis_history`）。
    """
    from engine.primitives.templating import PromptTemplate
    from engine.primitives.templating import PromptType

    _install_fake_post(monkeypatch, payload=_answer_payload(content='选项1'))
    llm = OpenAICompatLLM(context_window=10240, config_info=_config_info(streaming=False))

    rerank_prompt = PromptTemplate('候选节点：{context_str}\n问题：{query_str}',
                                   prompt_type=PromptType.CHOICE_SELECT)
    llm.predict(rerank_prompt, context_str='节点一', query_str=RAW_FOLLOW_UP)

    assert chat_memory.get_chat_history(CONVERSATION_ID) is None
