"""建库/建图前的向量模型校验。

背景：图谱记录若写 ``stella-large-zh-v3-1792d``，而向量表实际是 ``vector(1024)``
（写路径回落到 .env 的 Qwen3）—— 记录与数据分家，直到用户点「发送」才炸成 502。
这里钉住的是**入库那一刻**的判据。
"""

import contextlib

import pytest

from knowledge_base.service import embedding_dimension
from knowledge_base.service import kbase_write_service as write
from model import resolver as model_resolver
from shared.errors.api import KbApiError


def _known(monkeypatch, verdict):
    monkeypatch.setattr(model_resolver, 'is_writable_embedding_model', lambda name: verdict)


def test_empty_model_follows_the_deployment_default(monkeypatch):
    """空值 = 跟随部署默认，不该去问注册表（问了也可能被判 False）。"""
    def explode(_name):
        raise AssertionError('空值不应触发模型校验')

    monkeypatch.setattr(model_resolver, 'is_writable_embedding_model', explode)

    embedding_dimension.ensure_known_embedding_model(None)
    embedding_dimension.ensure_known_embedding_model('   ')


def test_unknown_model_is_rejected_as_a_bad_request(monkeypatch):
    _known(monkeypatch, False)

    with pytest.raises(KbApiError) as excinfo:
        embedding_dimension.ensure_known_embedding_model('stella-large-zh-v3-1792d')

    assert excinfo.value.key == 'kbase.embedding.model.invalid'
    assert excinfo.value.code == '0004'
    assert 'stella-large-zh-v3-1792d' in excinfo.value.render('zh')


def test_known_model_passes(monkeypatch):
    _known(monkeypatch, True)

    embedding_dimension.ensure_known_embedding_model('Qwen3-Embedding-0.6B')


def test_unjudgeable_model_passes(monkeypatch):
    """读不到注册表 = 无法判定，不能把用户挡在建库之外。"""
    _known(monkeypatch, None)

    embedding_dimension.ensure_known_embedding_model('whatever')


def test_create_kbase_rejects_the_bad_model_before_touching_the_store(monkeypatch):
    """校验必须在 ``insert_kbase`` **之前** —— 否则库里留下一行脏记录。"""
    _known(monkeypatch, False)
    monkeypatch.setattr(write.name_lock, 'acquire',
                        lambda org_id, name: contextlib.nullcontext())
    monkeypatch.setattr(write.kbase_store, 'find_kbases_by_name', lambda name, org_id: [])

    def must_not_insert(**kwargs):
        raise AssertionError('校验没拦住，insert_kbase 被调用了')

    monkeypatch.setattr(write.kbase_store, 'insert_kbase', must_not_insert)

    with pytest.raises(KbApiError) as excinfo:
        write.create_kbase(
            {'name': 'probe_bad_model', 'props': {'embeddingModel': 'stella-large-zh-v3-1792d'}},
            'admin', None, '')

    assert excinfo.value.key == 'kbase.embedding.model.invalid'
