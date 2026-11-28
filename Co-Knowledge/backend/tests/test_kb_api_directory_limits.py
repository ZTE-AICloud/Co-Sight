"""目录限额：**文件夹数只数文件夹，文件数按目录单独限制**。

历史行为是「建文件夹时数该目录下**全部**子项」——文件也算，于是装满 100 个文件的
目录永远建不了新文件夹，而报错文案写的是「文件夹个数超出限制」。现在的口径：

* 建文件夹：同层**文件夹**数 >= ``FOLDER_LIMIT`` 才拒绝，文件不参与；
* 上传 / 移动：目标目录**文件**数 + 本次数量 > ``FILE_LIMIT`` 拒绝；
* 覆盖上传（``coverFlag``）时同名旧文件被替换，不增加行数，不占额度。

不连库：``directory_store`` 的 ``connection`` 换成假实现，计数用假 cursor 喂。
"""

from contextlib import contextmanager

import pytest

from shared.errors.api import KbApiError
from knowledge_base.repository import directory as directory_store
from knowledge_base.service import directory_service, file_service
from knowledge_base.service.file_service import UploadedFile

KB = '447a9eb509e44d399790dbfd97f25360'

TARGET_FOLDER = {
    'id': 'dir-target', 'kbase_id': KB, 'title': '目标目录',
    'parent_id': 'dir-root', 'parent_path': '0-dir-root-dir-target',
    'type': directory_store.TYPE_FOLDER,
}
FILE_ROW = {
    'id': 'file-1', 'kbase_id': KB, 'title': 'a.md',
    'parent_id': 'dir-src', 'type': directory_store.TYPE_FILE,
}


class _CountingCursor:
    """按顺序吐出预设计数；顺带记录 SQL 与参数。"""

    def __init__(self, *counts):
        self._counts = list(counts)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((' '.join(sql.split()), params))

    def fetchone(self):
        return (self._counts.pop(0),)

    def fetchall(self):
        return []

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


def _patch_connection(monkeypatch, *counts):
    cursor = _CountingCursor(*counts)

    @contextmanager
    def _connection():
        yield _Connection(cursor)

    monkeypatch.setattr(directory_store, 'connection', _connection)
    return cursor


def _insert_must_not_run(*_args, **_kwargs):
    raise AssertionError('超限时不应落库')


# ----------------------------------------------------------------------
# 计数口径：type 过滤
# ----------------------------------------------------------------------


def test_count_children_folders_counts_only_folders():
    cursor = _CountingCursor(7)

    assert directory_store.count_children_folders(cursor, KB, 'dir-1') == 7

    sql, params = cursor.executed[0]
    assert 'type = %s' in sql
    assert params[1] == directory_store.TYPE_FOLDER


def test_count_children_files_filters_type_and_can_exclude_ids():
    cursor = _CountingCursor(3)

    assert directory_store.count_children_files(cursor, KB, 'dir-1', ['file-1']) == 3

    sql, params = cursor.executed[0]
    assert 'type = %s' in sql
    assert params[1] == directory_store.TYPE_FILE
    assert 'id <> ALL' in sql
    assert params[-1] == ['file-1']


# ----------------------------------------------------------------------
# 建文件夹：只数文件夹
# ----------------------------------------------------------------------


def test_create_directory_rejects_when_folder_count_reaches_limit(monkeypatch):
    monkeypatch.setattr(directory_service, 'get_kbase_for_aspect', lambda _id: {})
    _patch_connection(monkeypatch, directory_service.FOLDER_LIMIT)
    monkeypatch.setattr(directory_store, 'insert_directory', _insert_must_not_run)

    with pytest.raises(KbApiError) as caught:
        directory_service.create_directory(KB, None, '合法标题')

    assert caught.value.key == 'directory.folder.size.over.limit'


def test_create_directory_allows_when_folders_below_limit(monkeypatch):
    """99 个文件夹已经够多了；本用例只证明**文件不参与**、未到 100 就放行到落库。"""
    monkeypatch.setattr(directory_service, 'get_kbase_for_aspect', lambda _id: {})
    _patch_connection(monkeypatch, directory_service.FOLDER_LIMIT - 1)
    monkeypatch.setattr(directory_store, 'get_parent_path', lambda _cursor, _pid: '0')
    monkeypatch.setattr(directory_store, 'find_folder_by_title', lambda *_a, **_k: None)
    monkeypatch.setattr(directory_store, 'insert_directory', _insert_must_not_run)

    with pytest.raises(AssertionError, match='不应落库'):
        directory_service.create_directory(KB, None, '合法标题')


# ----------------------------------------------------------------------
# 上传：目标目录文件数
# ----------------------------------------------------------------------


def test_upload_rejects_when_directory_would_exceed_file_limit(monkeypatch):
    _patch_connection(monkeypatch, file_service.FILE_LIMIT)

    with pytest.raises(KbApiError) as caught:
        file_service._check_directory_file_count(
            KB, 'dir-1', [UploadedFile('a.md', b'x')], cover_flag=False)

    assert caught.value.key == 'directory.file.size.over.limit'
    assert caught.value.render('zh') == '目录内文件个数超出限制，最多 500 个'


def test_upload_allows_when_exactly_reaches_file_limit(monkeypatch):
    _patch_connection(monkeypatch, file_service.FILE_LIMIT - 1)

    file_service._check_directory_file_count(
        KB, 'dir-1', [UploadedFile('a.md', b'x')], cover_flag=False)


def test_upload_cover_flag_does_not_count_replaced_files(monkeypatch):
    """目录已满 500，但覆盖上传的是已有同名文件（替换 1 行）→ 仍允许。"""
    _patch_connection(monkeypatch, file_service.FILE_LIMIT, 1)

    file_service._check_directory_file_count(
        KB, 'dir-1', [UploadedFile('a.md', b'x')], cover_flag=True)


def test_upload_cover_flag_still_rejects_new_names(monkeypatch):
    """覆盖模式只豁免同名替换：目录已满时传一个新名字仍然超限。"""
    _patch_connection(monkeypatch, file_service.FILE_LIMIT, 0)

    with pytest.raises(KbApiError) as caught:
        file_service._check_directory_file_count(
            KB, 'dir-1', [UploadedFile('b.md', b'x')], cover_flag=True)

    assert caught.value.key == 'directory.file.size.over.limit'


# ----------------------------------------------------------------------
# 移动：目标目录文件数
# ----------------------------------------------------------------------


def test_move_rejects_when_target_would_exceed_file_limit(monkeypatch):
    monkeypatch.setattr(directory_service, 'get_kbase_for_aspect', lambda _id: {})
    monkeypatch.setattr(directory_store, 'get_directory',
                        lambda *_a, **_k: dict(TARGET_FOLDER))
    monkeypatch.setattr(directory_store, 'get_files_by_ids',
                        lambda *_a, **_k: [dict(FILE_ROW)])
    _patch_connection(monkeypatch, file_service.FILE_LIMIT)

    with pytest.raises(KbApiError) as caught:
        directory_service.move_files(KB, ['file-1'], 'dir-target')

    assert caught.value.key == 'directory.file.size.over.limit'


def test_move_does_not_double_count_files_already_in_target(monkeypatch):
    """同目录移动：这批 id 已在目标目录里，先从计数里排除再加回来，不重复占额度。"""
    monkeypatch.setattr(directory_service, 'get_kbase_for_aspect', lambda _id: {})
    monkeypatch.setattr(directory_store, 'get_directory',
                        lambda *_a, **_k: dict(TARGET_FOLDER))
    monkeypatch.setattr(directory_store, 'get_files_by_ids',
                        lambda *_a, **_k: [dict(FILE_ROW, parent_id='dir-target')])
    _patch_connection(monkeypatch, file_service.FILE_LIMIT - 1)

    assert directory_service.move_files(KB, ['file-1'], 'dir-target') == 1


# ----------------------------------------------------------------------
# 错误映射：限额 → 422 limit_exceeded
# ----------------------------------------------------------------------


def test_file_limit_key_maps_to_limit_exceeded():
    from shared.problem import KEY_SPECS

    spec = KEY_SPECS['directory.file.size.over.limit']
    assert (spec.status, spec.code) == (422, 'limit_exceeded')
