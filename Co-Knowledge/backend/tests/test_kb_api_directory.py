"""目录域的权限切面与错误形状约束。

* ``POST /directory`` 必须先确认库存在，否则会写出孤儿行；
* 四条读端点（``GET /directory/{id}``、``children``、``descendants``、
  ``queryFilesByType``）在库不存在时必须返回业务错误，不是 0000；
* ``POST /directory/delete/{id}`` 的响应是 ``bo:null``
  （被删列表只用于操作日志）；
* 更新/删除/下载在「库不存在」时报「知识库不存在」（先库后对象），
  不能错报「目录/文件不存在」。

不连库：``kbase_store`` / ``directory_store`` 的查询函数全部替换成假实现，
``connection`` 在「不该碰库」的用例里故意设成一碰就炸。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_directory.py -q
"""


import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.errors.api import KbApiError  # noqa: E402
from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api  # noqa: E402
from knowledge_base.service import directory_service, file_service  # noqa: E402
from knowledge_base.service import kbase_write_service  # noqa: E402
from knowledge_base.repository import directory as directory_store, kbase as kbase_store  # noqa: E402

ZH = {'Accept-Language': 'zh-CN'}

KBASE_ID = '447a9eb509e44d399790dbfd97f25360'
# 32 个 0 的形状：全数字 → 切面走「算子分支」→
# PermissionDenied。非数字 uuid → 直接 KBASE_NOT_EXIST。
MISSING_UUID = '11111111-1111-1111-1111-111111111111'
MISSING_NUMERIC = '999999'

KBASE_ROW = {'id': 7, 'kbase_id': KBASE_ID, 'name': 'demo-kb'}

FOLDER_ROW = {
    'id': 'dir-1', 'kbase_id': KBASE_ID, 'title': '目录一', 'parent_id': None,
    'parent_path': '0', 'can_spread': 'Y', 'type': directory_store.TYPE_FOLDER,
    'created_by': 'admin', 'created_date': None, 'last_updated_by': None,
    'last_updated_date': None, 'status': None, 'file_from': None, 'fail_reason': None,
}


@pytest.fixture()
def client():
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app)


@pytest.fixture()
def no_db(monkeypatch):
    """一碰 ``directory_store.connection()`` 就炸 —— 用来证明「没落行/没读库」。"""
    def _boom():
        raise AssertionError('本用例不该访问数据库（库不存在的检查应在一切落库之前）')

    monkeypatch.setattr(directory_store, 'connection', _boom)


def _missing_kbase(monkeypatch, kbase_id):
    monkeypatch.setattr(kbase_store, 'select_kbase_by_id', lambda _k: None)


def _existing_kbase(monkeypatch):
    monkeypatch.setattr(kbase_store, 'select_kbase_by_id', lambda _k: dict(KBASE_ROW))


# ----------------------------------------------------------------------
# 建目录：假库必须被拒，且**不落行**
# ----------------------------------------------------------------------


def test_create_directory_missing_kbase_is_rejected_without_touching_db(monkeypatch, no_db):
    """库不存在 → 0005「知识库不存在」，且**连数据库连接都不开**。

    这条路径必须先查库再 INSERT —— 否则真库上会造出孤儿行。
    切面在控制器方法**之前**跑（``DirectoryController.createDirectory`` 挂着
    ``@NaePermissionCheck``），所以库检查先于标题校验、更先于落库。
    """
    _missing_kbase(monkeypatch, MISSING_UUID)

    with pytest.raises(KbApiError) as caught:
        directory_service.create_directory(MISSING_UUID, None, '合法标题')

    assert caught.value.code == '0005'
    assert caught.value.key == 'kbase.not.exist'
    assert caught.value.render('zh') == '知识库不存在'


def test_create_directory_missing_numeric_kbase_is_permission_denied(monkeypatch, no_db):
    """库不存在 + id 是纯数字 → 切面走算子分支 → ``permission.denied``（与 ``GET /kbase/{id}`` 一致）。"""
    _missing_kbase(monkeypatch, MISSING_NUMERIC)

    with pytest.raises(KbApiError) as caught:
        directory_service.create_directory(MISSING_NUMERIC, None, '合法标题')

    assert caught.value.code == '0005'
    assert caught.value.render('zh') == '没有权限或已被删除'


def test_create_directory_checks_kbase_before_title(monkeypatch, no_db):
    """库里不存在 + 标题也不合规 → 报**库**的那条（顺序：切面 → 标题 → 落库）。"""
    _missing_kbase(monkeypatch, MISSING_UUID)

    with pytest.raises(KbApiError) as caught:
        directory_service.create_directory(MISSING_UUID, None, 'x')   # 标题只有 1 个字符

    assert caught.value.key == 'kbase.not.exist'


def test_create_directory_with_existing_kbase_still_validates_title(monkeypatch, no_db):
    """库存在、标题不合规 → 仍然是标题校验错误（别把库检查提前成「唯一校验」）。"""
    _existing_kbase(monkeypatch)

    with pytest.raises(KbApiError) as caught:
        directory_service.create_directory(KBASE_ID, None, 'x')

    assert caught.value.key == 'directory.title.validation'
    assert caught.value.render('zh') == '标题长度必须在2-30之间，且必须包含非空格的字符'


def test_create_directory_route_reports_kbase_not_exist(monkeypatch, no_db, client):
    """走真实路由再钉一遍（信封、msgId 一起对）。"""
    _missing_kbase(monkeypatch, MISSING_UUID)

    response = client.post(f'{KBASE_PREFIX}/knowledge-bases/{MISSING_UUID}/directories',
                           json={'title': '合法标题'}, headers=ZH)
    body = response.json()

    assert response.status_code == 404
    assert body['code'] == 'knowledge_base_not_found'
    assert body['detail'] == '知识库不存在'


# ----------------------------------------------------------------------
# 存量读端点：库不存在时 → 0005（不是 0000）
# ----------------------------------------------------------------------

READ_ENDPOINTS = [
    ('/directories', {}),
    ('/directories/dir-1', {}),
]


@pytest.mark.parametrize('path,extra', READ_ENDPOINTS)
@pytest.mark.parametrize('kbase_id,message', [
    (MISSING_UUID, '知识库不存在'),
    (MISSING_NUMERIC, '没有权限或已被删除'),
])
def test_read_endpoints_reject_missing_kbase(client, monkeypatch, path, extra,
                                             kbase_id, message):
    _missing_kbase(monkeypatch, kbase_id)

    response = client.get(f'{KBASE_PREFIX}/knowledge-bases/{kbase_id}{path}', params=extra,
                          headers=ZH)
    body = response.json()

    assert response.status_code in (403, 404)
    assert body['detail'] == message


def test_existing_kbase_missing_directory_still_returns_empty_vo(client, monkeypatch):
    """反向保护：**库在、目录不在 → 0000 + 空 VO**（别改坏）。

    空 VO 就是全字段 null。
    """
    _existing_kbase(monkeypatch)
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: None)

    response = client.get(f'{KBASE_PREFIX}/knowledge-bases/{KBASE_ID}/directories/dir-x')
    body = response.json()

    assert response.status_code == 200
    # 与 ``_base_vo({})`` 同字段集、全 null（字段全集按固定声明序）
    expected = directory_service._base_vo({})
    assert set(body) == set(expected)
    assert all(value is None for value in body.values())


def test_delete_directory_service_returns_none(monkeypatch):
    """服务层同样返回 None（路由把 None 装成 ``bo:null``）。"""
    _existing_kbase(monkeypatch)
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: dict(FOLDER_ROW))
    monkeypatch.setattr(directory_store, 'get_descendants', lambda *_a, **_k: [])
    monkeypatch.setattr(kbase_write_service, '_delete_one_directory', lambda *args: None)

    assert directory_service.delete_directory(KBASE_ID, 'dir-1', lambda key: key) is None


# ----------------------------------------------------------------------
# 先库后对象（delete / downloadFile）
#
# 目录改名（``POST /directory/{id}``）零调用，路由不存在；
# ``directory_service.update_directory`` 保留给删除路径复用错误矩阵。
# ----------------------------------------------------------------------


def test_download_file_missing_kbase_reports_kbase_not_exist(client, monkeypatch):
    """``GET /file/doc/downloadFile``：库不存在 → 「知识库不存在」（不能错报文件不存在）。"""
    _missing_kbase(monkeypatch, MISSING_UUID)

    response = client.get(f'{KBASE_PREFIX}/knowledge-bases/{MISSING_UUID}/documents/f-1/content',
                          headers=ZH)
    body = response.json()

    assert response.status_code == 404
    assert body['detail'] == '知识库不存在'


def test_download_file_existing_kbase_missing_file(client, monkeypatch):
    """库在、文件不在 → 0005「文件(夹)不存在」（这条文案保持不变）。"""
    _existing_kbase(monkeypatch)
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: None)

    response = client.get(f'{KBASE_PREFIX}/knowledge-bases/{KBASE_ID}/documents/f-x/content',
                          headers=ZH)
    body = response.json()

    assert response.status_code == 404
    assert body['code'] == 'file_not_found'
    assert body['detail'] == '文件(夹)不存在'


def test_download_file_service_keys(monkeypatch):
    """服务层再钉一遍键名（路由层的文案是从键渲染的，键错了文案对不上）。"""
    _missing_kbase(monkeypatch, MISSING_UUID)
    with pytest.raises(KbApiError) as caught:
        file_service.doc_download_file(MISSING_UUID, 'f-1')
    assert caught.value.key == 'kbase.not.exist'

    _existing_kbase(monkeypatch)
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: None)
    with pytest.raises(KbApiError) as caught:
        file_service.doc_download_file(KBASE_ID, 'f-x')
    assert caught.value.key == 'file.not.exist'


def test_upsert_property_uses_on_conflict():
    """覆盖上传复用同一个 file_id：属性写入必须是 upsert，否则撞唯一键。"""
    from knowledge_base.repository import directory as directory_repository

    class _Cursor:
        def __init__(self):
            self.sql = ''
            self.params = ()

        def execute(self, sql, params):
            self.sql = sql
            self.params = params

    cursor = _Cursor()
    directory_repository.upsert_property(cursor, 'kb-1', 'file-1', 'KType', 'graph-document')

    assert 'ON CONFLICT (file_id, prop_name) DO UPDATE' in cursor.sql
    assert cursor.params[1:] == ('file-1', 'kb-1', 'KType', 'graph-document')
