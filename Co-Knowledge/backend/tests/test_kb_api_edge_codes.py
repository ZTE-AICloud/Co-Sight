"""三处「路径变量/可选参数」错误码的对照测试。

* ``GET /file/size_limit/{category}``：``category`` 是 ``@PathVariable Integer``。
  非数字 → 类型不匹配 → **0001**（不是 0004）；枚举认不出、或认得出但 yml 里
  没配档位的 category（0/2/3/4/5）→ 服务层取到 null → **0001**
  （不是 0000 + ``number: null``）。
* ``GET /operator/exportByName``：``operatorName``/``path`` **没有注解**，
  无注解参数按可选处理 → 缺参不是 0004。
  缺 ``operatorName`` → 查库为空 → 0005「算子未找到」；
  命中但缺 ``path`` → ``path.equals(...)`` NPE → **0001**。
* 算子路径变量 ``{operatorId}`` 全是 ``@PathVariable Long``：非数字 → **0001**。

不连库：store 的查询函数按用例替换；算子路径那组在 ``_path_long`` 就抛，
到不了服务层。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_edge_codes.py -q
"""


import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.errors.api import KbServerError  # noqa: E402
from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api  # noqa: E402
from knowledge_base.service import file_service  # noqa: E402
from operators.service import operator_service
from operators.repository import operator_store  # noqa: E402

ZH = {'Accept-Language': 'zh-CN'}


@pytest.fixture()
def client():
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_operator_formats(monkeypatch):
    """size_limit 要读「自定义算子支持格式」表 —— 单测不连库。"""
    monkeypatch.setattr(file_service, '_custom_operator_formats', lambda: set())


# ----------------------------------------------------------------------
# GET /file/size_limit/{category}
# ----------------------------------------------------------------------


@pytest.mark.parametrize('category', [0, 2, 3, 4, 5, 99])
def test_size_limit_without_a_configured_bucket_is_server_error(monkeypatch, category):
    """两类都落同一处 NPE：枚举不认识的（0/5/99）、认得出但 yml 没档位的（2/3/4）。

    ``...getMaxSizeMap().get(limitType)`` 拿到 null 再 ``.intValue()`` → **0001**，
    **不是** 0000 + ``number: null``。
    """
    monkeypatch.setenv('MEM_LIMIT', '8')

    with pytest.raises(KbServerError):
        file_service.file_size_limit(category)


@pytest.mark.parametrize('category,number', [(1, 1), (10, 50)])
def test_size_limit_configured_buckets_stay_ok(monkeypatch, category, number):
    """1（普通库）与 10（图谱库）有档位，照常 0000；MEM_LIMIT=8 时
    ``outer-document`` 被压成 1，graph-document 不受压缩影响。"""
    monkeypatch.setenv('MEM_LIMIT', '8')

    assert file_service.file_size_limit(category)['number'] == number


def test_size_limit_route_non_numeric_category_is_0001(client):
    response = client.get(f'{KBASE_PREFIX}/system/file-size-limits', params={'category': 'abc'})

    assert response.status_code == 400
    assert response.json()['code'] == 'malformed_request'


def test_size_limit_route_unconfigured_category_is_0001(client, monkeypatch):
    monkeypatch.setenv('MEM_LIMIT', '8')

    response = client.get(f'{KBASE_PREFIX}/system/file-size-limits', params={'category': '0'})

    assert response.status_code == 500
    assert response.json()['code'] == 'internal_error'


def test_size_limit_route_configured_category_is_0000(client, monkeypatch):
    monkeypatch.setenv('MEM_LIMIT', '8')

    response = client.get(f'{KBASE_PREFIX}/system/file-size-limits', params={'category': '1'})
    body = response.json()

    assert response.status_code == 200
    assert body['number'] == 1
    assert body['maxSizeMap']['txt'] == 2.5


OPERATOR_ROW = {'id': 3, 'name': 'my-op', 'module': 'rag_operator',
                'operator_zip_path': '/nonexistent/my-op.zip'}


def test_export_by_name_service_raises_server_error_for_missing_position(monkeypatch):
    """服务层直接钉一次类型（路由层 0001 的来源）。"""
    monkeypatch.setattr(operator_store, 'select_by_name', lambda _name: [dict(OPERATOR_ROW)])
    monkeypatch.setattr(operator_store, 'list_props_by_operator_id', lambda _oid: {})

    with pytest.raises(KbServerError):
        operator_service.export_operator_by_name('my-op', None, '')


# ----------------------------------------------------------------------
# 算子 zip 文件缺失：盘上文件不在 → 0005 可读业务错误；路径为 NULL → 0001（NPE）
# ----------------------------------------------------------------------


def test_export_by_id_missing_zip_file_is_business_error(client, monkeypatch):
    """库里路径在、盘上文件缺失 → **0005 +「文件(夹)不存在」**（不是 0001）。

    缺文件不能回 0001 通用文案：通用文案劝用户「稍后重试」，
    而缺文件重试永远无用、只会掩盖数据问题。这里沿
    ``file_service.doc_download_file`` 的处理模式回可读业务错误。
    """
    monkeypatch.setattr(operator_store, 'select_by_org_id',
                        lambda _oid, _org: dict(OPERATOR_ROW))

    response = client.get(f'{KBASE_PREFIX}/operators/3/export', headers=ZH)
    body = response.json()

    assert response.status_code == 404
    assert body['code'] == 'file_not_found'
    assert body['detail'] == '文件(夹)不存在'


def test_export_by_id_null_zip_path_is_still_server_error(client, monkeypatch):
    """``operator_zip_path`` 为 NULL → 触发空指针 → **0001**（这一支不动）。

    阳性对照的下界：证明上面那条 0005 只覆盖「路径在、文件不在」，没有把整个
    ``_stream_stored_zip`` 的失败面一起改掉。
    """
    row = dict(OPERATOR_ROW, operator_zip_path=None)
    monkeypatch.setattr(operator_store, 'select_by_org_id', lambda _oid, _org: row)

    response = client.get(f'{KBASE_PREFIX}/operators/3/export', headers=ZH)
    body = response.json()

    assert response.status_code == 500
    assert body['code'] == 'internal_error'


# ----------------------------------------------------------------------
# 算子路径变量：非数字 → 0001（类型不匹配）
# ----------------------------------------------------------------------

# (method, path)：覆盖八条路径变量为 Long 的路由。
OPERATOR_PATH_ROUTES = [
    ('get', '/operators/abc'),
    ('delete', '/operators/abc'),
    ('get', '/operators/abc/export'),
    ('post', '/operators/abc/publish'),
    ('delete', '/operators/abc/publish'),
    ('put', '/operators/abc/visibility'),
]


@pytest.mark.parametrize('method,path', OPERATOR_PATH_ROUTES)
def test_operator_non_numeric_id_is_server_error(client, method, path):
    response = client.request(method.upper(), f'{KBASE_PREFIX}{path}', headers=ZH)
    body = response.json()

    assert response.status_code == 400
    assert body['code'] == 'malformed_request'
