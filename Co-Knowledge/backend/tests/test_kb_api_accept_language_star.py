"""``Accept-Language: *``（取**基础包**）+ 基础包缺席键的归宿。

一句话主题：**``*`` 请求落到 base 包时，那几条「base 里没有的键」不能按
归一化结果（zh）渲染** —— 查不到键会在构造业务异常 *之前* 抛
``NoSuchMessageException``，归宿由「异常在哪个 catch 被接住」决定：

=================================  ===========================================
端点 / 触发                        base（``*``）归宿
=================================  ===========================================
``POST /graph/import``（desc.json     不按业务异常处理，落到外层兜底，
的 id 格式非法）                      包成 **0005 + Retcode.graph.import.fail**
=================================  ===========================================

``*;q=0.9`` 与 ``*`` 同格（q 值剥离后的主标签仍是 ``*``）。

**影响面**：``/graph/import`` 在 ``Accept-Language`` 主标签为 ``*`` 时的错误码/文案；
其余语言档、其余端点全部不变（本文件逐格钉住）。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_accept_language_star.py -q
"""

import io
import zipfile

import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402

from infrastructure.http.identity import base_bundle, language  # noqa: E402
from shared.i18n.messages import (  # noqa: E402
    BASE_ABSENT_KEYS,
    is_base_absent,
    normalize_language,
    render,
)
from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app, raise_server_exceptions=False)


def _request(accept_language):
    headers = [] if accept_language is None else [
        (b'accept-language', accept_language.encode('utf-8'))]
    return Request({'type': 'http', 'method': 'GET', 'path': '/', 'root_path': '',
                    'headers': headers})


def _bad_id_zip():
    """desc.json 里的 ``id`` 不是 ``graph_`` + 32 位十六进制（校验在落库之前）。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('desc.json', '{"name":"probe5-kb","desc":"d",'
                                      '"embedding":"bge-large-zh","id":"bad-id"}')
        archive.writestr('entities.jsonl', '')
        archive.writestr('edges.jsonl', '')
    return buffer.getvalue()


def _post_import(client, header, payload):
    return client.post(f'{KBASE_PREFIX}/graph-imports',
                       headers={'Accept-Language': header},
                       files={'file': ('t.zip', payload, 'application/zip')})


# ----------------------------------------------------------------------
# identity.base_bundle：只有主标签**恰好是** ``*`` 才是基础包
# ----------------------------------------------------------------------


@pytest.mark.parametrize('header', ['*', '*;q=0.9'])
def test_base_bundle_true(header):
    assert base_bundle(_request(header)) is True
    # 归一化把 ``*`` 映成 zh —— 这正是「单靠 language 分不开这一支」的原因
    assert language(_request(header)) == 'zh'


@pytest.mark.parametrize('header', ['zh-CN', 'zh-CN,*;q=0.9', 'en-US, *;q=0.5',
                                    'en-US', 'zh', None])
def test_base_bundle_false(header):
    assert base_bundle(_request(header)) is False


def test_normalize_language_star_still_zh():
    """没动归一化（打击面控制）：``*`` 仍是 zh，base 与否由新标志位单独携带。"""
    assert normalize_language('*') == 'zh'


# ----------------------------------------------------------------------
# 消息表：base 缺席键的登记（事实集合）+ 非抛推测
# ----------------------------------------------------------------------


def test_base_absent_keys_registry():
    """只存在于 zh_CN / en_US（或只在 zh_CN）的键 —— 出处见 messages.py。"""
    assert BASE_ABSENT_KEYS >= {
        'graph.import.id.format.invalid.prefix',
        'graph.import.id.format.invalid.length',
        'graph.import.id.format.invalid.char',
        'RetCode.operator.arg.visibleRange.incorrect',
    }


def test_is_base_absent_is_a_pure_fact_lookup():
    assert is_base_absent('graph.import.id.format.invalid.prefix') is True
    assert is_base_absent('kbase.not.exist') is False        # base 里有
    assert is_base_absent('no.such.key') is False            # 未知键不抛


def test_render_does_not_throw_for_base_absent_keys():
    """``render`` 刻意保持「查不到就回落」的行为，不因登记变成地雷。"""
    assert render('RetCode.operator.arg.visibleRange.incorrect', 'zh') != (
        'RetCode.operator.arg.visibleRange.incorrect')


# ----------------------------------------------------------------------
# 图导入：``*`` → 0005 + Retcode.graph.import.fail（被外层 catch(Exception) 包住）
# ----------------------------------------------------------------------


@pytest.mark.parametrize('header', ['*', '*;q=0.9'])
def test_graph_import_bad_id_base_bundle_wrapped_into_import_fail(client, header):
    response = _post_import(client, header, _bad_id_zip())
    assert response.status_code == 422
    assert response.json()['code'] == 'import_failed'


def test_graph_import_bad_id_other_languages_unchanged(client):
    zh = _post_import(client, 'zh-CN', _bad_id_zip())
    assert zh.status_code == 422 and zh.json()['code'] == 'validation_failed'
    assert 'graph_' in zh.json()['detail']
    for header in ('en-US', 'zh'):
        response = _post_import(client, header, _bad_id_zip())
        assert response.status_code == 422
        assert response.json()['code'] == 'validation_failed'
        assert 'graph_' in response.json()['detail']


def test_graph_import_absent_header_is_en(client):
    response = client.post(f'{KBASE_PREFIX}/graph-imports',
                           files={'file': ('t.zip', _bad_id_zip(), 'application/zip')})
    assert response.status_code == 422
    assert 'graph_' in response.json()['detail']


def test_base_bundle_wrap_is_key_scoped(client):
    """包装只对 **base 缺席** 的键生效：``entities.file.required`` 的键
    （``RetCode.graph.import.entities.file.required``）在 base 里，
    ``*`` 下照常回它自己的中文文案，不该被包成 import.fail。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('desc.json', '{"name":"probe5-kb","desc":"d",'
                                      '"embedding":"bge-large-zh"}')
        archive.writestr('edges.jsonl', '')
    response = _post_import(client, '*', buffer.getvalue())
    body = response.json()
    assert response.status_code == 422
    assert body['code'] == 'validation_failed'
    assert body['detail'] == render('graph.import.entities.file.required', 'zh')
