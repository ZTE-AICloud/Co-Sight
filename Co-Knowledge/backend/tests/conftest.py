"""flow_api 测试夹具。

不依赖 DB / 网络 / ``app.py``：画布存储用 ``InMemoryFlowStore``，知识库下拉用桩
provider，编排能力用构造的 ``RuntimeCapabilities``。因此本目录的测试在任何有
``fastapi``/``pytest`` 的环境里都能跑。

跑法（服务目录下）::

    python -m pytest tests -q
"""

import os
import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = SERVICE_ROOT / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fastapi import FastAPI  # noqa: E402  (必须在 sys.path 处理之后)
from fastapi.testclient import TestClient  # noqa: E402

from workflow import register_flow_api  # noqa: E402
from shared.prefixes import RKB_PREFIX as KB_SERVICE_PREFIX  # noqa: E402
from workflow.kbase_provider import KbaseOptionProvider  # noqa: E402
from workflow.runtime_config import RuntimeCapabilities  # noqa: E402
from workflow.repository import InMemoryFlowStore  # noqa: E402
from graph.service import lifecycle as _graph_lifecycle  # noqa: E402
from knowledge_base import graph_bridge  # noqa: E402

graph_bridge.install(_graph_lifecycle)

from knowledge_base.service import kbase_service as _kbase_service  # noqa: E402
from retrieval.repository.kbase_lookup import set_kbase_row_provider  # noqa: E402

set_kbase_row_provider(_kbase_service.get_kbase_row)


@pytest.fixture(autouse=True, scope='session')
def _test_secret_key():
    """给 api_key 加密一个固定的测试密钥，避免用例在 /data/rkb 下生成密钥文件。"""
    os.environ.setdefault('RKB_SECRET_KEY', 'unit-test-only-secret-key')
    from model import crypto

    crypto.reset_cache()
    yield


@pytest.fixture(autouse=True)
def _disable_query_trace(monkeypatch):
    """默认关闭 trace 入库：TestClient 会执行 background，不能让它连真实 DB。"""
    monkeypatch.setenv('RKB_QUERY_TRACE_ENABLED', 'false')
    yield

# 前缀**从单一来源导入**，不在这里复制字面量：测试里各写一份字面量会让改前缀
# 牵动一批用例。
# KB_SERVICE_PREFIX = 对外契约前缀（compat/prefixes.RKB_PREFIX）；只有这一条前缀
assert KB_SERVICE_PREFIX.startswith('/api/')

QUERY_ENGINE_NODE = {
    'componentType': 'QUERY_ENGINE',
    'variables': {'queryengine': {'operator': 'SequentialQueryEngine'}},
}
EDGES_NODE = {'componentType': 'EDGES', 'variables': {}}

RUNNABLE_RETRIEVER = {
    'package': 'core.rag.retriever.vector_retriever',
    'operator': 'VectorRetriever',
}


class FakeKbaseOptionProvider(KbaseOptionProvider):
    """桩：固定三条知识库，**分组按对外契约的语义给**（``running`` = 已发布 ``7``）。

    特意让 ``dev`` 里留一条 ``status='0'``：对外契约的 ``0`` 是「待发布」，
    而 RKB 早年按自己的 ``kb_info.state=0``（处理成功）规则重新分组 —— 这条数据
    就是那个「待发布被显示成运行中」回归的哨兵（见 ``kbase_provider`` 模块头）。
    """

    def list_options(self, embedding_model=None):
        running = [
            {'kbasePkId': 'kb-1', 'name': 'demo-kb', 'tableName': 'kb-1', 'dbTableName': 'data_kb-1',
             'type': 'document', 'assetId': 'kb-1', 'status': '7',
             'embeddingModel': 'bge-base-zh-v1.5'},
        ]
        dev = [
            {'kbasePkId': 'kb-2', 'name': 'dev-kb', 'tableName': 'kb-2', 'dbTableName': 'data_kb-2',
             'type': 'document', 'assetId': 'kb-2', 'status': '0',
             'embeddingModel': 'bge-base-zh-v1.5'},
            {'kbasePkId': 'graph-3', 'name': 'graph-kb', 'tableName': 'graph-3',
             'dbTableName': 'graph-3', 'type': 'document', 'assetId': 'graph-3',
             'status': '5', 'embeddingModel': 'bge-base-zh-v1.5'},
        ]
        if embedding_model:
            keep = lambda kb: kb['embeddingModel'] == embedding_model  # noqa: E731
            running = [kb for kb in running if keep(kb)]
            dev = [kb for kb in dev if keep(kb)]
        return {'running': running, 'dev': dev}


def make_canvas(kbase_name=None, package='core.rag.retriever.vector_retriever', engine='SequentialQueryEngine',
                extra_node=None, empty_stage=None):
    """造一份最小可用画布（一个节点 + QUERY_ENGINE 伪节点）。

    :param kbase_name: 检索器 kwargs 里绑定的知识库名（含或不含 ``|#|dev`` 都行）
    """
    kwargs = {}
    if kbase_name is not None:
        kwargs['knowledge_info_list'] = [{'knowledge_base_name': kbase_name}]
    node = {
        'componentType': 'retriever',
        'variables': {
            'retriever': [{**RUNNABLE_RETRIEVER, 'package': package, 'kwargs': kwargs}],
        },
    }
    if empty_stage:
        node['variables'][empty_stage] = []
    nodes = [node]
    if extra_node:
        nodes.append(extra_node)
    return {
        'flowType': 'workflow',
        'version': 99,  # 前端可能回传任意版本号；后端必须忽略它
        'nodeConfigDTOList': nodes,
        'otherNodeConfigList': [
            {'componentType': 'QUERY_ENGINE', 'variables': {'queryengine': {'operator': engine}}},
            EDGES_NODE,
        ],
    }


@pytest.fixture()
def store():
    return InMemoryFlowStore()


@pytest.fixture()
def capabilities():
    # 默认：本部署**没有** rerank 端点
    return RuntimeCapabilities(
        llm_models=(('deepseek-chat', 'DeepSeek Chat'), ('qwen3-32b', 'Qwen3 32B')),
        reasoning_models=('deepseek-chat', 'deepseek-r1', 'qwq-32b'),
        rerank_url='',
    )


@pytest.fixture()
def kbase_provider():
    return FakeKbaseOptionProvider()


@pytest.fixture()
def api(store, capabilities, kbase_provider):
    app = FastAPI()
    register_flow_api(app, store=store, capabilities=capabilities, kbase_provider=kbase_provider)
    return app


@pytest.fixture()
def client(api):
    return TestClient(api)


def unwrap(response):
    """返回 ``(code, payload)``：成功统一 ``'0000'``，失败返回 problem 的 ``code``。

    响应是纯 JSON / RFC 9457，没有 ``{code,bo,other}`` 信封。
    保留这个二值接口，是为了让 flow 测试里大量 ``code, bo = unwrap(r)`` 的写法
    继续可读。
    """
    if 200 <= response.status_code < 300:
        payload = response.json() if response.content else None
        return '0000', payload
    body = response.json()
    return body.get('code', 'http_error'), None


#: 建流请求里的绑定知识库。形状 = 建流弹窗 ``getSelectdKbList()`` 的产出：
#: ``{分组: [知识库选项, ...]}``，选项直接来自 ``GET /workflows/knowledge-bases``
#: （分组键是前端 ``KB_PUBLISH_STATUS.RUNNING`` = ``'running'``）。
BOUND_KB = {
    'kbasePkId': 'kb-1', 'name': 'demo-kb', 'tableName': 'doc_kb-1',
    'dbTableName': 'doc_kb-1_vector', 'type': 'document', 'assetId': 'kb-1',
    'status': 'running', 'embeddingModel': 'bge-base-zh-v1.5',
}
DEFAULT_BOUND_INFO = {'running': [BOUND_KB]}


def create_workflow(client, workflow_id, name='wf', prefix=KB_SERVICE_PREFIX, user='admin',
                    template='Sequential', bound_info=DEFAULT_BOUND_INFO, **extra):
    """建工作流并返回接口的 bo（失败时直接让测试挂掉，附上响应体）。

    ``template`` 与 ``boundInfo`` 默认给上：建流即播种默认画布，两者缺一都会
    被显式拒（见 ``template_loader``）—— 与建流弹窗的必填项一致。
    """
    payload = {
        'workFlowId': workflow_id, 'name': name,
        'template': template, 'boundInfo': bound_info,
        **extra,
    }
    response = client.post(f'{prefix}/workflows', json=payload, headers={'X-Emp-No': user})
    code, bo = unwrap(response)
    assert code == '0000', response.json()
    return bo
