"""``GET /system/llm-models``：从模型单一来源返回真实清单。

「创建知识图谱」页的「大模型」**必填下拉**唯一数据源就是这条接口 ——
清单恒空会让构建按钮永远不可用（页面死路）。因此这里返回
``GENERATION_MODELS``（经 ``RKB_FLOW_LLM_MODELS``，与画布大模型下拉**同源**）
解析出的清单。

格式对齐前端消费（``frontend/src/views/knowledgeGraphTab/CreateKnowledgeGraph.vue`` 的
``m.value || m.id`` / ``m.label || m.name || m.value``）：``[{value, label}, ...]``。

后端 ``_validate_llm`` 本就「取不到清单一律放行」（``KB_EXTRACT_LLM_LIST`` 未设），
打通不引入校验分叉。

不依赖 DB / 网络。跑法（服务目录下）::

    python -m pytest tests/test_kb_api_llm_list.py -q
"""


import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from model import env_capabilities  # noqa: E402
from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app)


def _get_llm_list(client):
    response = client.get(f'{KBASE_PREFIX}/system/llm-models')
    assert response.status_code == 200
    return response.json()


def test_llm_list_returns_0000_with_value_label_pairs(client, monkeypatch):
    """RKB_FLOW_LLM_MODELS 逐项解析成 ``{value, label}``，信封 0000。"""
    monkeypatch.setenv('RKB_FLOW_LLM_MODELS', 'deepseek-chat=DeepSeek Chat;deepseek-chat')

    payload = _get_llm_list(client)

    assert payload == [
        {'value': 'deepseek-chat', 'label': 'DeepSeek Chat'},
        {'value': 'deepseek-chat', 'label': 'deepseek-chat'},
    ]


def test_llm_list_plain_model_name_without_display(client, monkeypatch):
    """只写 ``model`` 不带 ``=`` 时，label 回落模型名本身（与 _parse_models 同语义）。"""
    monkeypatch.setenv('RKB_FLOW_LLM_MODELS', 'only-model')

    payload = _get_llm_list(client)

    assert payload == [{'value': 'only-model', 'label': 'only-model'}]


def test_llm_list_falls_back_to_default_models(client, monkeypatch):
    """env 未设时回落 runtime_config 的 DEFAULT_MODELS —— 下拉**不能空**。"""
    monkeypatch.delenv('RKB_FLOW_LLM_MODELS', raising=False)

    payload = _get_llm_list(client)

    assert isinstance(payload, list) and len(payload) > 0
    expected = [{'value': name, 'label': display}
                for name, display in env_capabilities.DEFAULT_MODELS]
    assert payload == expected


def test_llm_list_never_fails_with_0005(client, monkeypatch):
    """回归守卫：这条端点不能返回 0005。"""
    monkeypatch.setenv('RKB_FLOW_LLM_MODELS', 'm=型号')

    payload = _get_llm_list(client)

    assert isinstance(payload, list)
