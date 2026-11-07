"""``GET /system/rerank-models``：画布重排模型下拉的**唯一**数据源。

要钉住三件事：

1. 只列**启用**的 rerank 行，``isDefault`` 标出运行期会用到的那一行；
2. 注册表读不到 / 没有行时回落 ``.env``（``RERANK_URL`` + ``RERANK_MODEL``），
   与 ``model_resolver.rerank_model()`` 完全同源；
3. 没有端点时返回空列表 —— 与 ``rerank_url() == ''`` 同义，下拉不能凭空给出
   「看起来能用」的模型。

不依赖 DB / 网络：用 ``InMemoryModelStore`` 替掉 ``_make_store``（与
``tests/test_model_resolver.py`` 同一手法）。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_rerank_models.py -q
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api
from model.models import ModelRecord, new_model_id
from model.repository import InMemoryModelStore
from model import resolver as model_resolver

RERANK_URL = 'http://rerank.local:9997/v1/rerank'


@pytest.fixture()
def client():
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app)


@pytest.fixture()
def registry(monkeypatch):
    """把注册表换成内存实现；退出时清缓存，避免跨用例串味。"""
    def use(records):
        monkeypatch.setattr(model_resolver, '_make_store',
                            lambda: InMemoryModelStore(records))
        model_resolver.invalidate()
        return records

    yield use
    model_resolver.invalidate()


def _rerank(name, display=None, default=False, enabled=True):
    return ModelRecord(
        model_id=new_model_id(), model_kind='rerank', model_name=name,
        display_name=display or '', base_url='http://rerank.local:9997',
        rerank_path='/v1/rerank', is_default=default, enabled=enabled)


def _get(client):
    response = client.get(f'{KBASE_PREFIX}/system/rerank-models')
    assert response.status_code == 200
    return response.json()


def test_lists_enabled_models_with_labels_and_the_default_flag(client, registry):
    registry([
        _rerank('qwen-rerank', 'Qwen3-Reranker-4B', default=False),
        _rerank('bge-rerank', 'BGE Reranker', default=True),
        _rerank('retired', 'Retired', enabled=False),
    ])

    # 默认行排最前（与 store 的 ORDER BY 一致），禁用的行不出现
    assert _get(client) == [
        {'value': 'bge-rerank', 'label': 'BGE Reranker', 'isDefault': True},
        {'value': 'qwen-rerank', 'label': 'Qwen3-Reranker-4B', 'isDefault': False},
    ]


def test_without_a_default_row_the_first_enabled_row_is_flagged(client, registry):
    """与 ``_pick`` 同义：没有 ``is_default`` 时运行期用的是第一条启用行。"""
    registry([_rerank('first', default=False), _rerank('second', default=False)])

    payload = _get(client)

    assert [item['value'] for item in payload] == ['first', 'second']
    assert [item['isDefault'] for item in payload] == [True, False]


def test_env_fallback_when_the_registry_has_no_rerank_rows(client, registry, monkeypatch):
    # 端点回落读的是 RKB_RERANK_URL（RuntimeCapabilities 的来源），与 rerank_url() 同源
    monkeypatch.setenv('RKB_RERANK_URL', RERANK_URL)
    monkeypatch.setenv('RERANK_MODEL', 'env-reranker')
    registry([])

    assert _get(client) == [
        {'value': 'env-reranker', 'label': 'env-reranker', 'isDefault': True}]


def test_empty_list_when_the_deployment_has_no_rerank_endpoint(client, registry, monkeypatch):
    monkeypatch.setenv('RERANK_URL', '')
    monkeypatch.setenv('RKB_RERANK_URL', '')
    monkeypatch.delenv('RERANK_MODEL', raising=False)
    registry([])

    assert _get(client) == []
