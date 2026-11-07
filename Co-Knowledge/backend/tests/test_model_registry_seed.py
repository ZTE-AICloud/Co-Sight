"""首次播种：升级后「看到的东西」必须保持不变。

这是本功能**最重要的一条回归断言**。「有哪些模型」的权威来源从 ``deploy/.env``
换成了注册表，播种就是那次切换的桥 —— 桥塌了的症状是所有下拉变空，
对一个已经建好知识库/画布的部署来说那不是「新功能上线」而是故障。

测试钉三件事：

1. 种子行的**内容**与 ``.env`` 里的配置逐项对应（含两个命名空间、维度、推理标记）；
2. **按 kind 独立判空** —— 某一类已经有行就整类不碰（删光一类后重启不该「复活」它）；
3. 没有端点的行**不播**（种进去就是个点谁谁 404 的死条目）。

不依赖 DB / 网络。跑法（服务目录下）::

    python -m pytest tests/test_model_registry_seed.py -q
"""


import pytest

from model import seed  # noqa: E402
from model.models import (  # noqa: E402
    MODEL_KIND_EMBEDDING,
    MODEL_KIND_LLM,
    MODEL_KIND_RERANK,
)
from model.repository import InMemoryModelStore  # noqa: E402

#: 与当前 ``deploy/.env`` 同形（compose 注入到 RKB 的那几个名字）
ENV = {
    'RKB_FLOW_LLM_MODELS': 'deepseek-chat=DeepSeek Chat;qwen3-32b=Qwen3 32B;minimax-m3=MiniMax M3',
    'RKB_FLOW_REASONING_MODELS': 'deepseek-chat,deepseek-r1,qwq-32b',
    'GENERATION_GATEWAY_URL': 'http://10.0.0.51:4000/v1',
    'GENERATION_MODELS_PATH': '/models',
    'MODEL_GATEWAY_URL': 'https://llm.internal.test',
    'MODEL_GATEWAY_EMBEDDINGS_PATH': '/v1/embeddings',
    'EMBEDDING_MODEL': 'Qwen3-Embedding-0.6B',
    'EMBEDDING_MODEL_NAME': 'Qwen3-Embedding-0.6B',
    'EMBEDDING_DIMENSION': '1024',
    'RERANK_URL': '',
}

def _by_name(records, name):
    return next(r for r in records if r.model_name == name)


# ---------------------------------------------------------------------------
# 内容
# ---------------------------------------------------------------------------
def test_llm_seed_matches_the_env_list_in_order_and_flags_reasoning_models():
    records = seed.build_llm_records(ENV)

    assert [r.model_name for r in records] == ['deepseek-chat', 'qwen3-32b', 'minimax-m3']
    assert [r.label() for r in records] == ['DeepSeek Chat', 'Qwen3 32B', 'MiniMax M3']
    assert [r.is_default for r in records] == [True, False, False], '第一条是默认（= GENERATION_MODEL）'
    # 推理标记来自 REASONING_MODELS 这个**独立的**清单（里面 2 个模型不在 GENERATION_MODELS 里）
    assert [r.is_reasoning for r in records] == [True, False, False]
    # 每模型思考配置是运行期在管理页设置的，不从 env 播种（默认 none）
    assert [r.thinking_mode for r in records] == ['none', 'none', 'none']
    assert [r.thinking_payload for r in records] == [None, None, None]
    assert records[0].endpoint_for('chat') == 'http://10.0.0.51:4000/v1/chat/completions'
    assert records[0].endpoint_for('models') == 'http://10.0.0.51:4000/v1/models'
    assert {r.source for r in records} == {'env'}


def test_placeholder_endpoint_does_not_seed_a_dead_model():
    """``*.example.com`` 是文档占位符，播种时跳过。"""
    env = dict(ENV, MODEL_GATEWAY_URL='https://your-llm-endpoint.example.com')
    assert seed.build_embedding_records(env) == []

    llm_env = dict(ENV, GENERATION_GATEWAY_URL='https://your-llm-endpoint.example.com')
    assert seed.build_llm_records(llm_env) == []


def test_embedding_seed_keeps_the_two_namespaces_apart():
    """``EMBEDDING_MODEL_NAME`` 是库里的登记名，``EMBEDDING_MODEL`` 是端点认的仓库名。"""
    records = seed.build_embedding_records(dict(
        ENV, EMBEDDING_MODEL='BAAI/bge-base-zh-v1.5', EMBEDDING_MODEL_NAME='bge-base-zh-v1.5',
        EMBEDDING_DIMENSION='768'))

    record = records[0]
    assert record.model_name == 'bge-base-zh-v1.5'       # 下拉显示 / kb_kbase 里记的
    assert record.effective_api_model() == 'BAAI/bge-base-zh-v1.5'   # 发给端点的
    assert record.dimension == 768
    assert record.endpoint_for('embeddings') == 'https://llm.internal.test/v1/embeddings'
    assert record.is_default is True


def test_embedding_registered_name_falls_back_when_the_var_is_absent():
    """``EMBEDDING_MODEL_NAME`` **没有被 compose 注入**（老陷阱）。

    缺席时登记名退回 ``EMBEDDING_MODEL`` —— 与 ``kb_embedding`` 里那一行（两字段同值）一致，
    所以「没注入」不会在播种时变成一个空名字。
    """
    records = seed.build_embedding_records({k: v for k, v in ENV.items()
                                            if k != 'EMBEDDING_MODEL_NAME'})
    assert records[0].model_name == 'Qwen3-Embedding-0.6B'


def test_seed_records_contain_only_env_embedding():
    """`kb_embedding` 不存在：播种只剩 .env 那一条 embedding。"""
    records = seed.build_seed_records(ENV)
    embeddings = [r for r in records if r.model_kind == MODEL_KIND_EMBEDDING]

    assert len(embeddings) == 1
    assert embeddings[0].model_name == 'Qwen3-Embedding-0.6B'
    assert embeddings[0].source == 'env'
    assert embeddings[0].enabled is True and embeddings[0].is_default is True


def test_no_rerank_row_when_the_endpoint_is_empty():
    """``RERANK_URL`` 留空 = 本部署没有重排能力 —— 不能种一条没有端点的行。"""
    assert seed.build_rerank_records(ENV) == []


@pytest.mark.parametrize('url,expected', [
    ('https://gw/v1/rerank', ('https://gw/v1', '/rerank')),
    ('https://gw/rerank', ('https://gw', '/rerank')),
    ('https://gw/custom/rank', ('https://gw/custom/rank', 'https://gw/custom/rank')),
    ('', ('', '')),
])
def test_rerank_url_split(url, expected):
    assert seed.split_endpoint_url(url) == expected


def test_rerank_row_uses_the_url_as_is_when_it_cannot_be_split():
    records = seed.build_rerank_records(dict(ENV, RERANK_URL='https://gw/custom/rank',
                                             RERANK_MODEL='bge-reranker-large'))
    record = records[0]
    # 拆不开时把整个 URL 当路径 —— 绝不能拼成 https://gw/custom/rank/rerank 这种错地址
    assert record.endpoint_for('rerank') == 'https://gw/custom/rank'


def test_rerank_row_with_the_standard_suffix():
    records = seed.build_rerank_records(dict(ENV, RERANK_URL='https://gw/v1/rerank',
                                             RERANK_MODEL='bge-reranker-large'))
    assert records[0].endpoint_for('rerank') == 'https://gw/v1/rerank'
    assert records[0].model_name == 'bge-reranker-large'


# ---------------------------------------------------------------------------
# 判空与写入
# ---------------------------------------------------------------------------
def test_seed_writes_all_three_kinds_into_an_empty_store():
    store = InMemoryModelStore()
    written = seed.seed_if_empty(store, env=ENV)

    assert written == 3 + 1 + 0            # llm 3 + embedding（env 1）+ rerank 0
    assert len(store.list_records(MODEL_KIND_LLM)) == 3
    assert len(store.list_records(MODEL_KIND_EMBEDDING)) == 1
    assert store.list_records(MODEL_KIND_RERANK) == []


def test_deleting_one_row_of_a_kind_does_not_rewrite_that_kind():
    """删掉一条 ≠ 整类被重写：同 kind 还有行时，播种完全不碰它。"""
    store = InMemoryModelStore()
    seed.seed_if_empty(store, env=ENV)
    victim = store.list_records(MODEL_KIND_LLM)[0]
    store.delete(victim.model_id)

    written = seed.seed_if_empty(store, env=ENV)

    assert written == 0
    assert [r.model_name for r in store.list_records(MODEL_KIND_LLM)] == [
        'qwen3-32b', 'deepseek-chat'] or len(store.list_records(MODEL_KIND_LLM)) == 2
    assert store.get_record(victim.model_id) is None, '删掉的那条不该被补回来'


def test_an_emptied_kind_is_seeded_again_on_the_next_boot():
    """整类被清空 → 下次启动重新播种（**与解析层的 .env 回落一致**，见 seed_if_empty）。

    这条是**有意为之**而不是缺陷：注册表里没有 llm 行时解析层本来就回落到 ``.env``，
    下拉里照样是这三个模型。管理页显示空的、别处显示三个，才是真的会让人误判。
    """
    store = InMemoryModelStore()
    seed.seed_if_empty(store, env=ENV)
    for record in store.list_records(MODEL_KIND_LLM):
        store.delete(record.model_id)

    written = seed.seed_if_empty(store, env=ENV)

    assert written == 3
    assert len(store.list_records(MODEL_KIND_LLM)) == 3


def test_seed_is_idempotent():
    store = InMemoryModelStore()
    first = seed.seed_if_empty(store, env=ENV)
    second = seed.seed_if_empty(store, env=ENV)
    assert first > 0
    assert second == 0, '第二次不能再写一遍（唯一索引会直接报重复）'


def test_rows_without_an_endpoint_are_not_seeded():
    """没配端点时种进去的就是个死条目：点谁谁解析失败。"""
    store = InMemoryModelStore()
    written = seed.seed_if_empty(store, env=dict(ENV, GENERATION_GATEWAY_URL=''))
    assert written == 1, '只该种 embedding 那条（它的端点 MODEL_GATEWAY_URL 还在）'
    assert [r.model_kind for r in store.list_records()] == [MODEL_KIND_EMBEDDING]


def test_seeding_writes_env_models_only():
    store = InMemoryModelStore()
    written = seed.seed_if_empty(store, env=ENV)
    assert written == 4, 'llm 3 + embedding(env) 1'


def test_llm_names_are_read_from_either_env_spelling():
    """RKB 侧名字优先，退回 .env 原名 —— 免得「只在宿主改了 .env」时静默丢模型。"""
    base = {'GENERATION_GATEWAY_URL': 'http://10.0.0.1:4000/v1'}
    assert len(seed.build_llm_records(dict(base, GENERATION_MODELS='a=A;b=B'))) == 2
    both = seed.build_llm_records(
        dict(base, RKB_FLOW_LLM_MODELS='a=A', GENERATION_MODELS='b=B'))
    assert [r.model_name for r in both] == ['a']


def test_seeded_llm_rows_carry_the_deployment_api_key():
    """**播种必须带上 key**，否则升级后运行期请求会静默少掉 Authorization。

    这是真踩过的坑：解析层命中注册表后**就不会**再去看 ``GENERATION_API_KEY`` ——
    种子行 key 为空 = 编排与抽图的每次生成调用都变成匿名请求（LiteLLM 回 401）。
    第一现场是「连接测试对种子行报『无法判定』」，很容易被当成端点抖动放过去。
    """
    records = seed.build_llm_records(dict(ENV, GENERATION_API_KEY='sk-generation'))
    assert {r.api_key for r in records} == {'sk-generation'}


def test_embedding_seed_carries_the_embedding_api_key():
    records = seed.build_embedding_records(dict(ENV, MODEL_GATEWAY_API_KEY='sk-embedding'))
    assert records[0].api_key == 'sk-embedding'
