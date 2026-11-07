"""`/query` 的 RagException tag → RFC 9457 问题规格。"""
from __future__ import annotations

from chat.query_errors import query_problem


def test_known_tags_map_to_real_statuses_and_stable_codes():
    assert query_problem('required_param_missing', ('question',), 'zh')[0].status == 422
    assert query_problem('published-workflow-not-found', ('wf',), 'zh')[0].code == \
        'published_workflow_not_found'
    assert query_problem('request-knowledge-graph-failed', (), 'en')[0].status == 502
    assert query_problem('no-llm-available', (), 'en')[0].status == 503


def test_unknown_tag_is_a_500_without_leaking_the_tag():
    spec, detail = query_problem('some-new-tag', (), 'en')

    assert spec.status == 500
    assert spec.code == 'internal_error'
    assert 'some-new-tag' not in detail


def test_detail_follows_language_and_keeps_i18n_placeholders():
    _, zh = query_problem('bad-status-code', ('知识库服务',), 'zh')
    _, en = query_problem('bad-status-code', ('知识库服务',), 'en')

    assert zh == '请求知识库服务失败，请稍后重试。'
    assert en == 'Request service 知识库服务 failed, please try again.'
