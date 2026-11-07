"""embedding 调用必须跟随**请求的模型**解析端点。

默认 embedding 行从 0.6B 换成 4B 后，图谱检索整条 502：``get_embedding_info``
只在 body 里写了模型名、没给 ``LlmProxyClient.embeddings`` 传 ``model=``，
解析器便取默认行（4B 端点）去承接 0.6B 的请求 → 网关回 404
``The model `Qwen3-Embedding-0.6B` does not exist``。
"""

from model import llm_gateway


class _Response:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


class _FakeClient:
    def __init__(self):
        self.calls = []

    def embeddings(self, **kwargs):
        self.calls.append(kwargs)
        dimension = 2560 if kwargs.get('model') == 'Qwen3-Embedding-4B' else 1024
        return _Response({'data': [{'embedding': [0.0] * dimension}]})


class _Headers:
    transaction_id = 'trace-1'
    language_option = 'zh-CN'
    client_ip = '127.0.0.1'


def test_get_embedding_info_resolves_the_requested_model(monkeypatch):
    # Arrange
    fake = _FakeClient()
    monkeypatch.setattr(llm_gateway, 'llm_proxy_client', fake)

    # Act
    embedding = llm_gateway.get_embedding_info(
        'query', 'Qwen3-Embedding-0.6B', _Headers())

    # Assert：端点选择与 body 里的模型名必须是同一个
    assert len(embedding) == 1024
    assert fake.calls[0]['model'] == 'Qwen3-Embedding-0.6B'
    assert fake.calls[0]['body']['model'] == 'Qwen3-Embedding-0.6B'


def test_get_embedding_dimension_resolves_the_requested_model(monkeypatch):
    # Arrange
    fake = _FakeClient()
    monkeypatch.setattr(llm_gateway, 'llm_proxy_client', fake)

    # Act
    dimension = llm_gateway.get_embedding_dimension('Qwen3-Embedding-4B')

    # Assert
    assert dimension == 2560
    assert fake.calls[0]['model'] == 'Qwen3-Embedding-4B'
