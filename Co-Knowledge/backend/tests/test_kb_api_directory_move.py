"""0.1.7 目录管理的后端契约：批量移动文档、删除目录但保留文档。

这两个能力是原型 v0.1.7 新增的交互：
- `PATCH /knowledge-bases/{id}/documents` 把文档移到目标目录；
- `DELETE /knowledge-bases/{id}/directories/{dir}` 只移除目录，文档移到 Default。

都不连库：目录/文件仓储与连接全部替换成假实现，断言服务层的校验顺序与 SQL 参数。
"""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.errors.api import KbApiError, KbValidationError
from shared.prefixes import RKB_PREFIX
from http_api import register_rkb_api
from knowledge_base.service import directory_service
from knowledge_base.repository import directory as directory_store

KBASE_ID = '447a9eb509e44d399790dbfd97f25360'
TARGET_FOLDER = {
    'id': 'dir-target', 'kbase_id': KBASE_ID, 'title': '目标目录',
    'parent_id': 'dir-root', 'parent_path': '0-dir-root-dir-target',
    'type': directory_store.TYPE_FOLDER,
}
FILE_ROW = {
    'id': 'file-1', 'kbase_id': KBASE_ID, 'title': 'a.md',
    'parent_id': 'dir-src', 'type': directory_store.TYPE_FILE,
}


class _Cursor:
    def __init__(self, conflicts=None):
        self.conflicts = conflicts or []
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((' '.join(sql.split()), params))

    def fetchall(self):
        return self.conflicts

    def fetchone(self):
        return (1,)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_connection(monkeypatch, conflicts=None):
    cursor = _Cursor(conflicts)

    @contextmanager
    def _connection():
        yield _Connection(cursor)

    monkeypatch.setattr(directory_store, 'connection', _connection)
    return cursor


@pytest.fixture()
def kbase_ok(monkeypatch):
    monkeypatch.setattr(directory_service, 'get_kbase_for_aspect', lambda _id: {})


def test_move_files_rejects_unknown_target_folder(monkeypatch, kbase_ok):
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: None)

    with pytest.raises(KbApiError) as caught:
        directory_service.move_files(KBASE_ID, ['file-1'], 'dir-missing')

    assert caught.value.key == 'directory.not.exist'


def test_move_files_rejects_missing_files(monkeypatch, kbase_ok):
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: dict(TARGET_FOLDER))
    monkeypatch.setattr(directory_store, 'get_files_by_ids', lambda *_a, **_k: [])

    with pytest.raises(KbApiError) as caught:
        directory_service.move_files(KBASE_ID, ['file-1'], 'dir-target')

    assert caught.value.key == 'file.not.exist'


def test_move_files_rejects_empty_ids(monkeypatch, kbase_ok):
    with pytest.raises(KbValidationError):
        directory_service.move_files(KBASE_ID, [], 'dir-target')


def test_move_files_rejects_same_name_in_target(monkeypatch, kbase_ok):
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: dict(TARGET_FOLDER))
    monkeypatch.setattr(directory_store, 'get_files_by_ids', lambda *_a, **_k: [dict(FILE_ROW)])
    _patch_connection(monkeypatch, conflicts=[('a.md',)])

    with pytest.raises(KbApiError) as caught:
        directory_service.move_files(KBASE_ID, ['file-1'], 'dir-target')

    assert caught.value.key == 'file.upload.rename'
    assert caught.value.code == '0005'


def test_move_files_rejects_duplicate_names_among_selection(monkeypatch, kbase_ok):
    rows = [
        {**FILE_ROW, 'id': 'file-1', 'parent_id': 'dir-a'},
        {**FILE_ROW, 'id': 'file-2', 'parent_id': 'dir-b'},
    ]
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: dict(TARGET_FOLDER))
    monkeypatch.setattr(directory_store, 'get_files_by_ids', lambda *_a, **_k: rows)
    _patch_connection(monkeypatch)

    with pytest.raises(KbApiError) as caught:
        directory_service.move_files(KBASE_ID, ['file-1', 'file-2'], 'dir-target')

    assert caught.value.key == 'file.upload.rename'


def test_move_files_updates_parent_and_path(monkeypatch, kbase_ok):
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: dict(TARGET_FOLDER))
    monkeypatch.setattr(directory_store, 'get_files_by_ids', lambda *_a, **_k: [dict(FILE_ROW)])
    cursor = _patch_connection(monkeypatch)

    moved = directory_service.move_files(KBASE_ID, ['file-1'], 'dir-target', 'admin')

    assert moved == 1
    update = [item for item in cursor.executed if item[0].startswith('UPDATE kb_directory')][-1]
    assert 'parent_id = %s' in update[0]
    assert update[1][0] == 'dir-target'
    # 文件的 parent_path 取目标目录自己的 parent_path（上传时的口径）。
    assert update[1][1] == TARGET_FOLDER['parent_path']
    assert update[1][2] == 'admin'
    assert update[1][3] == KBASE_ID
    assert update[1][4] == ['file-1']


def test_delete_directory_keep_files_moves_documents_to_default(monkeypatch, kbase_ok):
    folder = {
        'id': 'dir-src', 'kbase_id': KBASE_ID, 'title': '旧目录',
        'parent_id': 'dir-root', 'parent_path': '0-dir-root-dir-src',
        'type': directory_store.TYPE_FOLDER,
    }
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: dict(folder))
    monkeypatch.setattr(directory_store, 'get_descendants', lambda *_a, **_k: [
        {**FILE_ROW},
        {'id': 'dir-sub', 'type': directory_store.TYPE_FOLDER},
    ])
    monkeypatch.setattr(directory_store, 'get_children', lambda *_a, **_k: [
        {'id': 'dir-root', 'title': 'Default', 'parent_path': '0',
         'type': directory_store.TYPE_FOLDER},
    ])
    deleted = []
    monkeypatch.setattr(directory_store, 'delete_folders',
                        lambda _cursor, ids: deleted.extend(ids))
    cursor = _patch_connection(monkeypatch)

    directory_service.delete_directory_keep_files(KBASE_ID, 'dir-src', 'admin')

    update = [item for item in cursor.executed if item[0].startswith('UPDATE kb_directory')][-1]
    assert update[1][0] == 'dir-root'
    assert update[1][1] == '0'
    assert update[1][4] == ['file-1']
    assert deleted == ['dir-sub', 'dir-src']


def test_delete_directory_keep_files_rejects_duplicate_names_in_tree(monkeypatch, kbase_ok):
    folder = {
        'id': 'dir-src', 'kbase_id': KBASE_ID, 'title': '旧目录',
        'parent_id': 'dir-root', 'parent_path': '0-dir-root-dir-src',
        'type': directory_store.TYPE_FOLDER,
    }
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: dict(folder))
    monkeypatch.setattr(directory_store, 'get_descendants', lambda *_a, **_k: [
        {**FILE_ROW, 'id': 'file-1'},
        {**FILE_ROW, 'id': 'file-2'},
    ])
    monkeypatch.setattr(directory_store, 'get_children', lambda *_a, **_k: [
        {'id': 'dir-root', 'title': 'Default', 'parent_path': '0',
         'type': directory_store.TYPE_FOLDER},
    ])
    _patch_connection(monkeypatch)

    with pytest.raises(KbApiError) as caught:
        directory_service.delete_directory_keep_files(KBASE_ID, 'dir-src')

    assert caught.value.key == 'file.upload.rename'


def test_delete_directory_keep_files_rejects_default_folder(monkeypatch, kbase_ok):
    monkeypatch.setattr(directory_store, 'get_directory', lambda *_a, **_k: {
        'id': 'dir-root', 'kbase_id': KBASE_ID, 'title': 'Default',
        'parent_id': None, 'type': directory_store.TYPE_FOLDER,
    })

    with pytest.raises(KbApiError) as caught:
        directory_service.delete_directory_keep_files(KBASE_ID, 'dir-root')

    assert caught.value.key == 'directory.not.exist'


# ----------------------------------------------------------------------
# 路由：方法与状态码
# ----------------------------------------------------------------------


@pytest.fixture()
def client():
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app)


def test_move_documents_route(client, monkeypatch):
    monkeypatch.setattr(directory_service, 'move_files',
                        lambda kbase_id, ids, parent_id, emp_no='': len(ids))

    response = client.patch(f'{RKB_PREFIX}/knowledge-bases/{KBASE_ID}/documents',
                            json={'ids': ['file-1', 'file-2'], 'parentId': 'dir-target'})

    assert response.status_code == 200
    assert response.json() == {'moved': 2}


def test_delete_directory_route_keeps_documents(client, monkeypatch):
    calls = []
    monkeypatch.setattr(directory_service, 'delete_directory_keep_files',
                        lambda *args: calls.append(args))

    response = client.delete(f'{RKB_PREFIX}/knowledge-bases/{KBASE_ID}/directories/dir-src')

    assert response.status_code == 204
    assert calls
