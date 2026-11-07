"""kb_api 文件落盘的测试（B2 基础件）。

这些路径规则不是「实现细节」：库里存的是**绝对路径**，分片规则或根目录一旦对不上，
表现就是「文件找不到」，而且要到下载或检索时才暴露。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_storage.py -q
"""

from pathlib import Path

import pytest

from infrastructure.storage import kb_storage as storage  # noqa: E402
from infrastructure.storage.backend import ENV_LOCAL_ROOT  # noqa: E402
from shared.errors.api import KbApiError  # noqa: E402

FILE_ID = '761c359fc9154f8aa8e27f61e8506920'


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_LOCAL_ROOT, str(tmp_path))
    return tmp_path


def test_core_path_shards_on_first_four_chars():
    """``<root>/core/<前 4 位>/<uuid>`` —— 与 ``LocalDiskUtil.generateCoreFilePath`` 一致。

    实测线上布局：``/data/kb/core/761c/761c359fc9154f8aa8e27f61e8506920``。
    """
    path = storage.core_file_path(FILE_ID)

    assert path.name == FILE_ID
    assert path.parent.name == FILE_ID[:4]
    assert path.parent.parent.name == 'core'


def test_save_then_read_then_delete(tmp_path):
    saved = storage.save_core_file(b'hello', FILE_ID, cover=False)

    assert saved.read_bytes() == b'hello'
    assert saved == storage.core_file_path(FILE_ID)

    storage.delete_core_file(FILE_ID)
    assert not saved.exists()


def test_second_save_without_cover_is_rejected(tmp_path):
    """已存在且 ``cover=False`` 必须抛错，**不能静默覆盖**。

    上传链的「同名文件要不要覆盖」由调用方决定（``metadata.coverFlag``），
    这一层是那个决定的落点。
    """
    storage.save_core_file(b'first', FILE_ID, cover=False)

    with pytest.raises(KbApiError) as excinfo:
        storage.save_core_file(b'second', FILE_ID, cover=False)

    assert excinfo.value.render('zh') == '文件保存失败'
    assert storage.core_file_path(FILE_ID).read_bytes() == b'first'


def test_cover_true_overwrites(tmp_path):
    storage.save_core_file(b'first', FILE_ID, cover=False)
    storage.save_core_file(b'second', FILE_ID, cover=True)

    assert storage.core_file_path(FILE_ID).read_bytes() == b'second'


def test_delete_missing_file_is_not_an_error(tmp_path):
    """删除在多个入口被调用，文件已不在不该把整条链带崩。"""
    storage.delete_core_file('deadbeefdeadbeefdeadbeefdeadbeef')


def test_storage_root_ignores_blank_env(monkeypatch):
    """留空回落默认值 —— 与 ``RKB_DB_NAME`` 同一口径（见 db.py 的说明）。"""
    monkeypatch.setenv(ENV_LOCAL_ROOT, '   ')

    assert storage.storage_root() == Path(storage.DEFAULT_STORAGE_ROOT)


def test_tmp_preview_path():
    assert storage.tmp_preview_dir('abc').parts[-2:] == ('tmp_preview', 'abc')
