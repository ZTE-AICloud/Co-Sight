"""问题改写：前端随请求带的 ``chat_history``（多轮）路径。

模板里 `multi_chat_limit=0` 时这条路径会被**关掉**，多轮只靠进程内
`chat_memory` 的 last_question —— 刷新页面或服务重启就断。当前行为：

* 新画布播种 8 轮；
* 旧画布里的 0 按「使用默认 8 轮」处理（`get_args`）；
* 前端会把最近的问答对放进 `chat_history` 一起发。

本文件钉住三件事：limit 归一化、历史被真正喂进改写提示词、没有历史时仍回落
last_question（不能因为新路径把旧行为弄坏）。
"""
from __future__ import annotations

import pytest

from engine.common.beans.rag_request import RagRequest
from engine.common.const import default_max_multi_chat_limit
from engine.cache import chat_memory
from engine.pre_retriever.query_transform import query_rewrite as qr
from engine.primitives.models import QueryBundle

CONVERSATION_ID = 'd-rewrite-history'
RAW = '那它的缺点呢？'
REWRITTEN = '向量检索的缺点是什么？'


class _DummyLLM:
    """`LLMQueryRewriter.__init__` 只需要一个对象；本文件不碰真实网关。"""


@pytest.fixture(autouse=True)
def _clean_caches():
    chat_memory.user_chat_question_cache.clear()
    chat_memory.user_chat_question_history_cache.clear()
    yield
    chat_memory.user_chat_question_cache.clear()
    chat_memory.user_chat_question_history_cache.clear()


@pytest.fixture
def make_rewriter(monkeypatch):
    monkeypatch.setattr(qr, 'get_custom_llm', lambda llm, config: _DummyLLM())

    def make(chat_history, limit=0):
        config = {
            'llm': '',
            'multi_chat_limit': limit,
            'user_request': RagRequest(
                question=RAW, conversation_id=CONVERSATION_ID,
                # Pydantic v2 会校验显式传入的 None；生产里缺省值是 None（不校验），
                # 测试里用空列表表示「请求没带历史」。
                chat_history=chat_history if chat_history is not None else []),
        }
        return qr.LLMQueryRewriter(config), config

    return make


def _install_ask(rewriter, *, same_sequence=True, rewritten=REWRITTEN):
    """替换 LLM 调用：第一次（相关性判定）给「相关/不相关」，第二次（改写）给 JSON。"""
    prompts = []

    def fake_ask(prompt):
        prompts.append(prompt)
        # 相关性判定那条 prompt 以「是否相关」结尾；没有 chat_history 时不会走到它，
        # 所以不能按「第几次调用」判断。
        if '是否相关' in prompt:
            return '相关' if same_sequence else '不相关'
        return '{"question": "%s"}' % rewritten

    rewriter.ask_llm_get_content = fake_ask
    return prompts


def _pairs(count):
    return [{'question': f'历史问题{i}', 'answer': f'历史答案{i}'} for i in range(count)]


def test_zero_limit_uses_default_and_enables_multi_turn(make_rewriter):
    """旧画布的 0 不再等于「关闭」，而是使用默认 8 轮。"""
    rewriter, config = make_rewriter(_pairs(10), limit=0)
    prompts = _install_ask(rewriter)

    bundle = rewriter._run(QueryBundle(query_str=RAW), {})

    assert config['user_request'].kwargs['is_multi_chat'] is True
    assert bundle.query_str == REWRITTEN
    rewrite_prompt = prompts[-1]
    # 只带最近 8 轮（历史问题2..9）
    assert '历史问题9' in rewrite_prompt
    assert '历史问题2' in rewrite_prompt
    assert '历史问题1' not in rewrite_prompt
    assert chat_memory.get_chat_question_history(CONVERSATION_ID) == [REWRITTEN]


def test_positive_limit_is_honored(make_rewriter):
    """画布上显式写 >0 的上限仍然生效（不能被默认值盖掉）。"""
    rewriter, config = make_rewriter(_pairs(10), limit=2)
    prompts = _install_ask(rewriter)

    rewriter._run(QueryBundle(query_str=RAW), {})

    rewrite_prompt = prompts[-1]
    assert '历史问题9' in rewrite_prompt and '历史问题8' in rewrite_prompt
    assert '历史问题7' not in rewrite_prompt


def test_unrelated_history_does_not_mark_multi_turn(make_rewriter):
    """相关性判定为「不相关」时不打 is_multi_chat，但改写仍要正常完成。"""
    rewriter, config = make_rewriter(_pairs(3), limit=8)
    _install_ask(rewriter, same_sequence=False)

    bundle = rewriter._run(QueryBundle(query_str=RAW), {})

    assert 'is_multi_chat' not in config['user_request'].kwargs
    assert bundle.query_str == REWRITTEN


def test_without_request_history_falls_back_to_chat_memory(make_rewriter):
    """没有 chat_history 的旧客户端仍走 last_question，行为不变。"""
    chat_memory.save_chat_history(
        CONVERSATION_ID, chat_memory.ChatHistory('上一轮改写后的问题', ['ctx'], '上一轮答案'))
    rewriter, config = make_rewriter(None, limit=8)
    prompts = _install_ask(rewriter)

    bundle = rewriter._run(QueryBundle(query_str=RAW), {})

    assert '上一轮改写后的问题' in prompts[-1]
    assert 'is_multi_chat' not in config['user_request'].kwargs
    assert bundle.query_str == REWRITTEN


def test_get_args_returns_default_for_legacy_zero(make_rewriter):
    rewriter, _ = make_rewriter([{'question': 'q', 'answer': 'a'}], limit=0)
    history, limit = rewriter.get_args()

    assert limit == default_max_multi_chat_limit
    assert history == [{'question': 'q', 'answer': 'a'}]


def test_rewrite_llm_uses_aux_thinking_profile(monkeypatch):
    """改写是短输出：默认传 thinking_profile=aux（关闭/最低思考）。"""
    seen = {}

    def capture(llm, config):
        seen.update(config)
        return _DummyLLM()

    monkeypatch.setattr(qr, 'get_custom_llm', capture)
    qr.LLMQueryRewriter({'llm': 'deepseek-chat'})

    assert seen['thinking_profile'] == 'aux'
    assert seen['llm'] == 'deepseek-chat'
