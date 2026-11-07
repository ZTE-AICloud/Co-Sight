"""向量化目标的解析：**注册表优先，回落 ``.env`` 默认模型**。

这条链路上有两个「两个命名空间」的陷阱，测试就是用来钉它们的：

* ``model_name``（注册名，``kb_kbase.embedding_model`` 里记的）vs ``model_code``
  （发给端点的 ``model`` 字段）—— 拿错会让网关 404，报错点在网关调用处、看不出是名字的问题；
* ``dimension``（校验基准）—— 拿错会让写入 ``vector(N)`` 列失败，或更糟：静默用错维度。

不存在 ``kb_embedding`` 表，回落目标只有 ``.env`` 的默认模型
（``EMBEDDING_MODEL`` / ``EMBEDDING_DIMENSION``）。

不依赖 DB / 网络：``model_resolver._make_store`` 换成内存 store。
跑法::

    python -m pytest tests/test_model_embedding_resolution.py -q
"""


import pytest

from model import gateway as model_gateway  # noqa: E402
from model.models import ModelRecord, new_model_id  # noqa: E402
from model.repository import InMemoryModelStore  # noqa: E402
from model import resolver as model_resolver  # noqa: E402

ENV = {
    'MODEL_GATEWAY_URL': 'https://env-embed',
    'MODEL_GATEWAY_EMBEDDINGS_PATH': '/v1/embeddings',
    'MODEL_GATEWAY_API_KEY': 'sk-env',
    'EMBEDDING_MODEL': 'Qwen3-Embedding-0.6B',
    'EMBEDDING_DIMENSION': '1024',
}


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    model_resolver.invalidate()
    yield
    model_resolver.invalidate()


def _use_registry(monkeypatch, records):
    store = InMemoryModelStore(records)
    monkeypatch.setattr(model_resolver, '_make_store', lambda: store)
    return store


def _registry_embedding(model_name='self-hosted-embed', **kwargs):
    base = dict(model_id=new_model_id(), model_kind='embedding', model_name=model_name,
                api_model='BAAI/bge-m3', base_url='http://my-embed:9000/v1',
                embeddings_path='', api_key='sk-mine', dimension=1024)
    base.update(kwargs)
    return ModelRecord(**base)


# ---------------------------------------------------------------------------
# 回落：注册表没有 → .env 默认模型
# ---------------------------------------------------------------------------
def test_empty_registry_falls_back_to_the_env_default(monkeypatch):
    _use_registry(monkeypatch, [])

    target = model_gateway.resolve_model('bge-base-zh-v1.5')
    assert target.origin == 'env'
    assert target.api_model == 'Qwen3-Embedding-0.6B', '回落目标是 .env 的 EMBEDDING_MODEL'
    assert target.dimension == 1024, '维度按 .env 的 EMBEDDING_DIMENSION，不是旧表的 768'
    assert target.url == 'https://env-embed/v1/embeddings'


def test_unreadable_registry_also_falls_back(monkeypatch):
    def explode():
        raise RuntimeError('db down')

    monkeypatch.setattr(model_resolver, '_make_store', explode)

    target = model_gateway.resolve_model(None)
    assert target.origin == 'env'
    assert target.api_model == 'Qwen3-Embedding-0.6B'
    assert target.dimension == 1024


def test_unknown_model_falls_back_to_the_env_default(monkeypatch):
    _use_registry(monkeypatch, [])
    target = model_gateway.resolve_model('no-such-model')
    assert target.api_model == 'Qwen3-Embedding-0.6B'
    assert target.dimension == 1024


# ---------------------------------------------------------------------------
# 注册表接管
# ---------------------------------------------------------------------------
def test_registry_row_supplies_endpoint_model_and_dimension(monkeypatch):
    _use_registry(monkeypatch, [_registry_embedding()])

    target = model_gateway.resolve_model('self-hosted-embed')
    assert target.origin == 'registry'
    assert target.url == 'http://my-embed:9000/v1/embeddings', '默认路径补在自建 base 上'
    assert target.api_model == 'BAAI/bge-m3', '发给端点的是 api_model'
    assert target.model_name == 'self-hosted-embed', '排障用注册名'
    assert target.api_key == 'sk-mine'
    assert target.dimension == 1024


def test_registry_row_without_a_dimension_falls_back_instead_of_guessing(monkeypatch):
    """维度缺失时**不许猜**：猜错就是「静默用错维度」，比报错难查得多。"""
    _use_registry(monkeypatch, [_registry_embedding(dimension=None)])

    target = model_gateway.resolve_model('self-hosted-embed')
    assert target.origin == 'env'
    assert target.dimension == 1024, '退回 .env 的默认维度'


def test_registry_row_endpoint_actually_used_by_embed_many(monkeypatch):
    _use_registry(monkeypatch, [_registry_embedding()])
    seen = {}

    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {'data': [{'index': 0, 'embedding': [0.0] * 1024}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return _Response()

    monkeypatch.setattr(model_gateway.egress, 'post', fake_post)
    model_gateway.embed_many(['你好'], 'self-hosted-embed')

    assert seen['url'] == 'http://my-embed:9000/v1/embeddings'
    assert seen['json'] == {'input': ['你好'], 'model': 'BAAI/bge-m3'}
    assert seen['headers']['Authorization'] == 'Bearer sk-mine'


def test_unknown_model_does_not_borrow_another_registry_row(monkeypatch):
    """注册表里有别的 embedding 模型，也不能拿来顶替一个没注册的名字。"""
    _use_registry(monkeypatch, [_registry_embedding()])
    target = model_gateway.resolve_model('bge-base-zh-v1.5')
    assert target.origin == 'env'
    assert target.dimension == 1024
    assert target.api_model == 'Qwen3-Embedding-0.6B'
