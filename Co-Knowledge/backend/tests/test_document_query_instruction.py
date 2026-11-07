"""文档检索查询 instruction 的单测。"""

from model import gateway
from model.query_instruction import (DEFAULT_QWEN3_INSTRUCTION,
                                     apply_query_instruction, instruction_for)


def test_qwen3_gets_default_instruction(monkeypatch):
    monkeypatch.delenv('EMBEDDING_QUERY_INSTRUCTION', raising=False)
    assert instruction_for('Qwen3-Embedding-0.6B') == DEFAULT_QWEN3_INSTRUCTION


def test_other_models_get_no_instruction_by_default(monkeypatch):
    monkeypatch.delenv('EMBEDDING_QUERY_INSTRUCTION', raising=False)
    assert instruction_for('BAAI/bge-base-zh-v1.5') == ''


def test_env_override_and_empty_switch(monkeypatch):
    monkeypatch.setenv('EMBEDDING_QUERY_INSTRUCTION', 'CUSTOM ')
    assert instruction_for('BAAI/bge-base-zh-v1.5') == 'CUSTOM '
    monkeypatch.setenv('EMBEDDING_QUERY_INSTRUCTION', '')
    assert instruction_for('Qwen3-Embedding-0.6B') == ''


def test_apply_is_idempotent():
    text = DEFAULT_QWEN3_INSTRUCTION + 'query'
    assert apply_query_instruction(text, 'Qwen3-Embedding-0.6B') == text


def test_embed_query_prepends_instruction(monkeypatch):
    # Arrange
    captured = {}

    def fake_embed_many(texts, requested_model):
        captured['texts'] = texts
        return [[0.0] * 1024]

    monkeypatch.setattr(gateway, 'embed_many', fake_embed_many)
    monkeypatch.setattr(
        gateway, 'resolve_model',
        lambda _model: gateway.EmbeddingTarget(
            api_model='Qwen3-Embedding-0.6B', dimension=1024, url='x',
            model_name='Qwen3-Embedding-0.6B'))
    monkeypatch.delenv('EMBEDDING_QUERY_INSTRUCTION', raising=False)

    # Act
    gateway.embed_query('who directed the film?', 'Qwen3-Embedding-0.6B')

    # Assert
    assert captured['texts'][0] == (
        DEFAULT_QWEN3_INSTRUCTION + 'who directed the film?')


def test_embed_does_not_prepend_instruction(monkeypatch):
    # Arrange
    captured = {}

    def fake_embed_many(texts, requested_model):
        captured['texts'] = texts
        return [[0.0] * 1024]

    monkeypatch.setattr(gateway, 'embed_many', fake_embed_many)

    # Act
    gateway.embed('chunk text', 'Qwen3-Embedding-0.6B')

    # Assert：切片入库路径不能被 instruction 污染
    assert captured['texts'] == ['chunk text']
