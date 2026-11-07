"""检索编排（去重/RRF/降级）与问答边界（无上下文/空内容/截断）的单测。"""

from __future__ import annotations

import pytest
import requests

from agent import answer as answer_mod
from agent import search as search_mod
from agent.auth import AgentPrincipal
from agent.errors import AgentApiError
from agent.schemas import AnswerRequest, SearchRequest

PRINCIPAL = AgentPrincipal('ragk_test', 'demo',
                           frozenset({'kb:search', 'kb:answer'}), (), 0)


def _hit(chunk='1', score=0.5, kb='kb-1', text='hello', node='n1'):
    return {'knowledge_base_id': kb, 'node_id': node, 'chunk_id': chunk,
            'document_id': 'f1', 'source': 'a.md', 'score': score,
            'text': text, 'metadata': {'chunk_index': 1}}


def _search_data(results=None, warnings=None):
    return {'query': 'q', 'mode': 'vector', 'results': results or [],
            'degraded': False, 'warnings': warnings or []}


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def test_dedupe_ranked_keeps_best_score_per_key():
    hits = [_hit(score=0.2), _hit(score=0.9), _hit(chunk='2', score=0.4)]
    ordered = search_mod._dedupe_ranked(hits)
    assert [hit['score'] for hit in ordered] == [0.9, 0.4]


def test_hybrid_rrf_does_not_inflate_duplicate_hits():
    vector_hits = [_hit(score=0.9), _hit(score=0.8)]      # 同一 chunk 的重复行
    keyword_hits = [_hit(score=0.3)]
    results = search_mod._hybrid_results(vector_hits, keyword_hits, top_k=5)
    # 去重后两路各 1 条，rank 1 → 1/61 + 1/61
    assert results[0]['score'] == pytest.approx(2 / 61)
    assert results[0]['scores'] == {'vector': 0.9, 'keyword': 0.3}


def test_dedupe_key_fallbacks():
    assert search_mod._dedupe_key(_hit()) == ('kb-1', 'chunk', '1')
    no_chunk = _hit(chunk=None)
    assert search_mod._dedupe_key(no_chunk) == ('kb-1', 'node', 'n1')
    no_node = _hit(chunk=None, node=None)
    assert search_mod._dedupe_key(no_node)[:2] == ('kb-1', 'text')


def test_search_vector_mode_formats_citations(monkeypatch):
    monkeypatch.setattr(search_mod, 'resolve_kbases',
                        lambda principal, ids: ([{'kbase_id': 'kb-1', 'name': 'demo'}], True))
    monkeypatch.setattr(search_mod, '_vector_path',
                        lambda *args, **kwargs: ([_hit(score=0.7)], [], 1, 0))
    monkeypatch.setattr(search_mod, '_keyword_path',
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('not called')))

    data = search_mod.search(PRINCIPAL, SearchRequest(query='q', mode='vector', top_k=3))
    assert data['mode'] == 'vector'
    assert data['degraded'] is False
    assert data['results'][0]['citation_id'] == 'S1'
    assert data['results'][0]['knowledge_base_name'] == 'demo'


def test_search_auto_degrades_to_vector_when_keyword_fails(monkeypatch):
    monkeypatch.setattr(search_mod, 'resolve_kbases',
                        lambda principal, ids: ([{'kbase_id': 'kb-1', 'name': 'demo'}], True))
    monkeypatch.setattr(search_mod, '_vector_path',
                        lambda *args, **kwargs: ([_hit(score=0.7)], [], 1, 0))
    monkeypatch.setattr(search_mod, '_keyword_path',
                        lambda *args, **kwargs: ([], [{'code': 'keyword_path_failed',
                                                       'message': 'boom'}], 0, 1))

    data = search_mod.search(PRINCIPAL, SearchRequest(query='q', mode='auto', top_k=3))
    assert data['mode'] == 'vector'
    assert data['degraded'] is True
    assert data['warnings'][0]['code'] == 'keyword_path_failed'


def test_search_auto_hybrid_when_both_paths_ok(monkeypatch):
    monkeypatch.setattr(search_mod, 'resolve_kbases',
                        lambda principal, ids: ([{'kbase_id': 'kb-1', 'name': 'demo'}], True))
    monkeypatch.setattr(search_mod, '_vector_path',
                        lambda *args, **kwargs: ([_hit(score=0.7)], [], 1, 0))
    monkeypatch.setattr(search_mod, '_keyword_path',
                        lambda *args, **kwargs: ([_hit(score=0.3)], [], 1, 0))

    data = search_mod.search(PRINCIPAL, SearchRequest(query='q', mode='auto', top_k=3))
    assert data['mode'] == 'hybrid'
    assert data['degraded'] is False
    assert data['results'][0]['score'] == pytest.approx(2 / 61)


def test_search_auto_raises_when_both_paths_fail(monkeypatch):
    monkeypatch.setattr(search_mod, 'resolve_kbases',
                        lambda principal, ids: ([{'kbase_id': 'kb-1', 'name': 'demo'}], False))
    monkeypatch.setattr(search_mod, '_vector_path',
                        lambda *args, **kwargs: ([], [], 0, 1))
    monkeypatch.setattr(search_mod, '_keyword_path',
                        lambda *args, **kwargs: ([], [], 0, 1))

    with pytest.raises(AgentApiError) as exc:
        search_mod.search(PRINCIPAL, SearchRequest(query='q', mode='auto'))
    assert exc.value.code == 'retrieval_failed'


def test_keyword_path_strict_raises_on_store_error(monkeypatch):
    monkeypatch.setattr(search_mod.store_retrieval, 'keyword_hits',
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('es down')))
    with pytest.raises(AgentApiError) as exc:
        search_mod._keyword_path([{'kbase_id': 'kb-1'}], 'q', 3, strict=True)
    assert exc.value.code == 'retrieval_failed'


# ---------------------------------------------------------------------------
# answer
# ---------------------------------------------------------------------------

class _Endpoint:
    url = 'http://generation.local/chat'
    api_model = 'test-model'
    model_name = 'test-model'
    origin = 'registry'
    timeout = 30
    max_tokens = 128
    temperature = 0.1
    thinking_payload = None

    def headers(self):
        return {'Content-Type': 'application/json'}


class _ThinkingOffEndpoint(_Endpoint):
    thinking_payload = {'chat_template_kwargs': {'thinking': False}}


class _CustomThinkingEndpoint(_Endpoint):
    thinking_payload = {'thinking': {'type': 'disabled'}, 'reasoning_effort': 'none'}


class _RegistryEndpoint(_Endpoint):
    """注册表行：行内没有思考配置，部署级 effort 不应再兜底进来。"""
    origin = 'registry'


class _Response:
    def __init__(self, status_code=200, content='ok [S1]', finish_reason='stop'):
        self.status_code = status_code
        self.text = '{}'
        self._content = content
        self._finish_reason = finish_reason

    def json(self):
        return {
            'choices': [{'message': {'content': self._content},
                         'finish_reason': self._finish_reason}],
            'usage': {'total_tokens': 3},
        }


def _patch_answer_success(monkeypatch, response=None, endpoint=None):
    monkeypatch.setattr(answer_mod, '_ensure_llm_configured', lambda: None)
    monkeypatch.setattr(answer_mod.model_resolver, 'resolve',
                        lambda kind, model: endpoint or _Endpoint())
    monkeypatch.setattr(answer_mod.requests, 'post',
                        lambda *args, **kwargs: response or _Response())


def test_answer_no_results_short_circuits(monkeypatch):
    monkeypatch.setattr(answer_mod, 'search', lambda principal, request: _search_data([]))
    monkeypatch.setattr(answer_mod.requests, 'post',
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('no call')))

    data = answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))
    assert data['no_results'] is True
    assert data['reason'] == 'no_context'
    assert data['answer'] is None


def test_answer_success_and_citation(monkeypatch):
    monkeypatch.setattr(answer_mod, 'search',
                        lambda principal, request: _search_data([{
                            'citation_id': 'S1', 'knowledge_base_id': 'kb-1',
                            'knowledge_base_name': 'demo', 'chunk_id': '1',
                            'document_id': 'f1', 'source': 'a.md', 'score': 0.5,
                            'scores': None, 'text': 'hello', 'metadata': None}]))
    _patch_answer_success(monkeypatch)

    data = answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))
    assert data['answer'] == 'ok [S1]'
    assert data['citations'][0]['citation_id'] == 'S1'
    assert data['usage'] == {'total_tokens': 3}
    assert data['warnings'] == []


def test_answer_sends_thinking_off_when_the_model_has_it(monkeypatch):
    monkeypatch.setattr(answer_mod, 'search',
                        lambda principal, request: _search_data([{
                            'citation_id': 'S1', 'knowledge_base_id': 'kb-1',
                            'knowledge_base_name': 'demo', 'chunk_id': '1',
                            'document_id': 'f1', 'source': 'a.md', 'score': 0.5,
                            'scores': None, 'text': 'hello', 'metadata': None}]))
    seen = {}
    _patch_answer_success(monkeypatch, endpoint=_ThinkingOffEndpoint())

    def fake_post(*args, **kwargs):
        seen.update(kwargs.get('json') or {})
        return _Response()

    monkeypatch.setattr(answer_mod.requests, 'post', fake_post)

    answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))

    assert seen['chat_template_kwargs'] == {'thinking': False}


def test_answer_merges_generic_thinking_payload(monkeypatch):
    monkeypatch.setattr(answer_mod, 'search',
                        lambda principal, request: _search_data([{
                            'citation_id': 'S1', 'knowledge_base_id': 'kb-1',
                            'knowledge_base_name': 'demo', 'chunk_id': '1',
                            'document_id': 'f1', 'source': 'a.md', 'score': 0.5,
                            'scores': None, 'text': 'hello', 'metadata': None}]))
    seen = {}
    _patch_answer_success(monkeypatch, endpoint=_CustomThinkingEndpoint())

    def fake_post(*args, **kwargs):
        seen.update(kwargs.get('json') or {})
        return _Response()

    monkeypatch.setattr(answer_mod.requests, 'post', fake_post)
    monkeypatch.setattr(answer_mod.config, 'reasoning_effort', lambda: 'low')

    answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))

    assert seen['thinking'] == {'type': 'disabled'}
    assert seen['reasoning_effort'] == 'none'


def test_answer_ignores_global_effort_for_registry_model(monkeypatch):
    """注册表行是权威：行内没配 effort 时，不能拿 RKB_AGENT_REASONING_EFFORT 兜底。"""
    monkeypatch.setattr(answer_mod, 'search',
                        lambda principal, request: _search_data([{
                            'citation_id': 'S1', 'knowledge_base_id': 'kb-1',
                            'knowledge_base_name': 'demo', 'chunk_id': '1',
                            'document_id': 'f1', 'source': 'a.md', 'score': 0.5,
                            'scores': None, 'text': 'hello', 'metadata': None}]))
    seen = {}
    _patch_answer_success(monkeypatch, endpoint=_RegistryEndpoint())

    def fake_post(*args, **kwargs):
        seen.update(kwargs.get('json') or {})
        return _Response()

    monkeypatch.setattr(answer_mod.requests, 'post', fake_post)
    monkeypatch.setattr(answer_mod.config, 'reasoning_effort', lambda: 'low')

    answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))

    assert 'reasoning_effort' not in seen


def test_answer_flags_unknown_and_missing_citations(monkeypatch):
    monkeypatch.setattr(answer_mod, 'search',
                        lambda principal, request: _search_data([{
                            'citation_id': 'S1', 'knowledge_base_id': 'kb-1',
                            'knowledge_base_name': 'demo', 'chunk_id': '1',
                            'document_id': 'f1', 'source': 'a.md', 'score': 0.5,
                            'scores': None, 'text': 'hello', 'metadata': None}]))
    _patch_answer_success(monkeypatch, _Response(content='ok [S9]'))
    data = answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))
    codes = {item['code'] for item in data['warnings']}
    assert 'unknown_citation' in codes

    _patch_answer_success(monkeypatch, _Response(content='ok'))
    data = answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))
    assert any(item['code'] == 'no_citations_in_answer' for item in data['warnings'])


def test_answer_empty_and_truncated_content(monkeypatch):
    monkeypatch.setattr(answer_mod, 'search', lambda principal, request: _search_data([{
        'citation_id': 'S1', 'knowledge_base_id': 'kb-1', 'knowledge_base_name': 'demo',
        'chunk_id': '1', 'document_id': 'f1', 'source': 'a.md', 'score': 0.5,
        'scores': None, 'text': 'hello', 'metadata': None}]))

    _patch_answer_success(monkeypatch, _Response(content=''))
    with pytest.raises(AgentApiError) as exc:
        answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))
    assert exc.value.code == 'answer_failed'

    _patch_answer_success(monkeypatch, _Response(content='', finish_reason='length'))
    with pytest.raises(AgentApiError) as exc:
        answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))
    assert 'truncated' in exc.value.message


def test_answer_upstream_errors(monkeypatch):
    monkeypatch.setattr(answer_mod, 'search', lambda principal, request: _search_data([{
        'citation_id': 'S1', 'knowledge_base_id': 'kb-1', 'knowledge_base_name': 'demo',
        'chunk_id': '1', 'document_id': 'f1', 'source': 'a.md', 'score': 0.5,
        'scores': None, 'text': 'hello', 'metadata': None}]))
    _patch_answer_success(monkeypatch, _Response(status_code=500))
    with pytest.raises(AgentApiError) as exc:
        answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))
    assert exc.value.code == 'answer_failed'

    def _boom(*args, **kwargs):
        raise requests.RequestException('down')

    monkeypatch.setattr(answer_mod.requests, 'post', _boom)
    with pytest.raises(AgentApiError) as exc:
        answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))
    assert exc.value.code == 'answer_failed'


def test_ensure_llm_configured_fails_closed(monkeypatch):
    monkeypatch.delenv('GENERATION_GATEWAY_URL', raising=False)
    monkeypatch.setattr(answer_mod.model_resolver, 'records', lambda kind=None: [])
    with pytest.raises(AgentApiError) as exc:
        answer_mod._ensure_llm_configured()
    assert exc.value.http_status == 503
    assert exc.value.code == 'answer_unavailable'


def test_answer_disabled(monkeypatch):
    monkeypatch.setattr(answer_mod.config, 'answer_enabled', lambda: False)
    with pytest.raises(AgentApiError) as exc:
        answer_mod.answer(PRINCIPAL, AnswerRequest(question='q'))
    assert exc.value.code == 'answer_unavailable'
