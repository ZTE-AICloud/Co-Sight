"""存储后端（local / MinIO）的契约测试。

本文件覆盖两层：

* ``common.storage.backend`` —— 两个后端的 put/get/delete/覆盖语义；
* ``compat.kb_api.storage`` —— 上层门面对后端的切换（``RKB_STORAGE_BACKEND``）。

MinIO 侧用**假客户端**跑：真实 MinIO 的集成用例见
``tools/verify/verify-minio-storage-e2e.py``（需要容器）。这里保证的是
「对象键、覆盖语义、miss → FileNotFoundError、前缀、物化到本地」这些行为，
不依赖网络与容器。
"""

from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]

import pytest  # noqa: E402

from infrastructure.storage.backend import (  # noqa: E402
    LocalBackend,
    MinioBackend,
    normalize_key,
    reset_storage_backend,
    set_storage_backend,
    storage_backend,
)
from infrastructure.storage import kb_storage as storage  # noqa: E402

FILE_ID = '761c359fc9154f8aa8e27f61e8506920'


@pytest.fixture(autouse=True)
def _reset_backend():
    reset_storage_backend()
    yield
    reset_storage_backend()


# ---------------------------------------------------------------------------
# 对象键
# ---------------------------------------------------------------------------

def test_normalize_key_strips_dot_segments():
    assert normalize_key('./core//ab/abc') == 'core/ab/abc'


@pytest.mark.parametrize('key', ['../etc/passwd', 'core/../../x', '/abs/path'])
def test_normalize_key_rejects_escapes(key):
    with pytest.raises(ValueError):
        normalize_key(key)


# ---------------------------------------------------------------------------
# LocalBackend
# ---------------------------------------------------------------------------

def test_local_put_get_exists_delete(tmp_path):
    backend = LocalBackend(tmp_path)

    backend.put('core/ab/abc', b'hello')

    assert backend.get('core/ab/abc') == b'hello'
    assert backend.exists('core/ab/abc')
    assert backend.local_path('core/ab/abc') == tmp_path / 'core' / 'ab' / 'abc'

    backend.delete('core/ab/abc')
    assert not backend.exists('core/ab/abc')


def test_local_get_missing_raises_file_not_found(tmp_path):
    backend = LocalBackend(tmp_path)
    with pytest.raises(FileNotFoundError):
        backend.get('core/ab/missing')


def test_local_size(tmp_path):
    backend = LocalBackend(tmp_path)
    backend.put('core/ab/abc', b'12345')

    assert backend.size('core/ab/abc') == 5
    with pytest.raises(FileNotFoundError):
        backend.size('core/ab/missing')


def test_local_cover_semantics(tmp_path):
    backend = LocalBackend(tmp_path)
    backend.put('k', b'first')

    with pytest.raises(FileExistsError):
        backend.put('k', b'second', overwrite=False)

    assert backend.get('k') == b'first'
    backend.put('k', b'second', overwrite=True)
    assert backend.get('k') == b'second'


def test_local_put_accepts_path_source(tmp_path):
    source = tmp_path / 'source.bin'
    source.write_bytes(b'from-file')
    backend = LocalBackend(tmp_path / 'root')

    backend.put('dump/source.bin', source)

    assert (tmp_path / 'root' / 'dump' / 'source.bin').read_bytes() == b'from-file'


def test_local_get_to_file(tmp_path):
    backend = LocalBackend(tmp_path)
    backend.put('pict/ab/abc', b'image')
    destination = tmp_path / 'out' / 'image.png'

    backend.get_to_file('pict/ab/abc', destination)

    assert destination.read_bytes() == b'image'


# ---------------------------------------------------------------------------
# MinioBackend（假客户端）
# ---------------------------------------------------------------------------

class FakeS3Error(Exception):
    """``minio.error.S3Error`` 的最小替身：只保留 ``code`` 字段。"""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class FakeStat:
    def __init__(self, size):
        self.size = size


class FakeResponse:
    def __init__(self, content):
        self._content = content
        self.closed = False
        self.released = False

    def read(self, *args):
        return self._content

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class FakeMinio:
    def __init__(self):
        self.objects = {}
        self.buckets = set()

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket, location=None):
        self.buckets.add(bucket)

    def put_object(self, bucket, name, data, length, content_type=None):
        self.objects[name] = data.read(length)

    def get_object(self, bucket, name):
        if name not in self.objects:
            raise FakeS3Error('NoSuchKey')
        return FakeResponse(self.objects[name])

    def stat_object(self, bucket, name):
        if name not in self.objects:
            raise FakeS3Error('NoSuchKey')
        return FakeStat(len(self.objects[name]))

    def remove_object(self, bucket, name):
        self.objects.pop(name, None)

    def fget_object(self, bucket, name, file_path):
        if name not in self.objects:
            raise FakeS3Error('NoSuchKey')
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        Path(file_path).write_bytes(self.objects[name])


def _minio_backend(client=None, **kwargs):
    return MinioBackend(
        endpoint='minio:9000',
        access_key='ak',
        secret_key='sk',
        bucket='rag-studio-kb',
        client=client or FakeMinio(),
        **kwargs,
    )


def test_minio_put_get_exists_delete():
    backend = _minio_backend()
    backend.put('core/ab/abc', b'hello')

    assert backend.get('core/ab/abc') == b'hello'
    assert backend.exists('core/ab/abc')
    assert backend.local_path('core/ab/abc') is None

    backend.delete('core/ab/abc')
    assert not backend.exists('core/ab/abc')


def test_minio_get_missing_raises_file_not_found():
    backend = _minio_backend()
    with pytest.raises(FileNotFoundError):
        backend.get('core/ab/missing')


def test_minio_size():
    backend = _minio_backend()
    backend.put('core/ab/abc', b'12345')

    assert backend.size('core/ab/abc') == 5
    with pytest.raises(FileNotFoundError):
        backend.size('core/ab/missing')


def test_minio_cover_semantics():
    backend = _minio_backend()
    backend.put('k', b'first')

    with pytest.raises(FileExistsError):
        backend.put('k', b'second', overwrite=False)

    assert backend.get('k') == b'first'
    backend.put('k', b'second', overwrite=True)
    assert backend.get('k') == b'second'


def test_minio_prefix_is_applied():
    client = FakeMinio()
    backend = _minio_backend(client=client, prefix='tenant-a')

    backend.put('core/ab/abc', b'hello')

    assert 'tenant-a/core/ab/abc' in client.objects


def test_minio_get_to_file():
    backend = _minio_backend()
    backend.put('pict/ab/abc', b'image')

    destination = Path('/tmp') / 'minio-test-image.bin'
    try:
        backend.get_to_file('pict/ab/abc', destination)
        assert destination.read_bytes() == b'image'
    finally:
        destination.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 上层门面：切换后端
# ---------------------------------------------------------------------------

def test_facade_uses_minio_backend(monkeypatch, tmp_path):
    set_storage_backend(_minio_backend())

    saved = storage.save_core_file(b'hello', FILE_ID, cover=False)

    assert saved == storage.core_key(FILE_ID)
    assert storage.read_core_file(FILE_ID) == b'hello'
    assert storage.core_file_exists(FILE_ID)

    storage.delete_core_file(FILE_ID)
    assert not storage.core_file_exists(FILE_ID)


def test_facade_cover_semantics_on_minio():
    set_storage_backend(_minio_backend())
    storage.save_core_file(b'first', FILE_ID, cover=False)

    with pytest.raises(storage.KbApiError):
        storage.save_core_file(b'second', FILE_ID, cover=False)

    assert storage.read_core_file(FILE_ID) == b'first'


def test_materialize_ref_downloads_object_to_scratch(monkeypatch, tmp_path):
    set_storage_backend(_minio_backend())
    monkeypatch.setenv('RKB_STORAGE_TEMP_PATH', str(tmp_path))
    storage.save_core_file(b'hello', FILE_ID, cover=False)

    path, is_temp = storage.materialize_ref(storage.core_key(FILE_ID), suffix='.md')

    assert is_temp
    assert path.read_bytes() == b'hello'
    storage.cleanup_materialized(path)
    assert not path.exists()


def test_materialize_ref_keeps_local_file(monkeypatch, tmp_path):
    monkeypatch.setenv('RKB_KBASE_STORAGE_PATH', str(tmp_path))
    reset_storage_backend()
    saved = storage.save_core_file(b'hello', FILE_ID, cover=False)

    path, is_temp = storage.materialize_ref(saved, suffix='.md')

    assert not is_temp
    assert path == saved


def test_backend_name_defaults_to_local(monkeypatch):
    monkeypatch.delenv('RKB_STORAGE_BACKEND', raising=False)
    assert storage.storage_backend().name == 'local'


def test_backend_name_minio_requires_config(monkeypatch):
    monkeypatch.setenv('RKB_STORAGE_BACKEND', 'minio')
    monkeypatch.setenv('RKB_MINIO_ENDPOINT', '')
    with pytest.raises(RuntimeError):
        storage_backend()


def test_factory_builds_minio_backend_from_env(monkeypatch):
    monkeypatch.setenv('RKB_STORAGE_BACKEND', 'minio')
    monkeypatch.setenv('RKB_MINIO_ENDPOINT', 'minio:9000')
    monkeypatch.setenv('RKB_MINIO_ACCESS_KEY', 'ak')
    monkeypatch.setenv('RKB_MINIO_SECRET_KEY', 'sk')
    monkeypatch.delenv('RKB_MINIO_BUCKET', raising=False)
    monkeypatch.delenv('RKB_MINIO_PREFIX', raising=False)
    monkeypatch.setattr(MinioBackend, '_create_client', lambda self: FakeMinio())

    backend = storage_backend()

    assert backend.name == 'minio'
    assert backend.bucket == 'rag-studio-kb'
    assert backend.prefix == ''


# ---------------------------------------------------------------------------
# 文档处理模块（ingestion）的 LocalClient 走同一套后端
# ---------------------------------------------------------------------------

def test_local_client_clean_files_stay_local(tmp_path, monkeypatch):
    from ingestion.utility.local_disk import LocalClient

    monkeypatch.setenv('RKB_STORAGE_TEMP_PATH', str(tmp_path / 'scratch'))
    set_storage_backend(_minio_backend())

    source = tmp_path / 'clean.md'
    source.write_bytes(b'# clean')
    client = LocalClient(str(tmp_path))

    clean_path = client.upload_clean_file(str(source), 'admin')

    assert Path(clean_path).read_bytes() == b'# clean'
    assert str(tmp_path / 'scratch') in clean_path


# ---------------------------------------------------------------------------
# 任务链：MinIO 对象在交给算子前物化成临时文件
# ---------------------------------------------------------------------------

def test_parse_handler_materializes_minio_object(monkeypatch, tmp_path):
    from knowledge_base.task import handlers

    set_storage_backend(_minio_backend())
    monkeypatch.setenv('RKB_STORAGE_TEMP_PATH', str(tmp_path))
    storage.save_core_file(b'# hello', FILE_ID, cover=False)
    handle = {
        'fileId': 'f1', 'kbaseId': 'kb1', 'format': 'md',
        'diskPath': storage.core_key(FILE_ID),
        'fileName': 'a.md', 'fileSize': 7, 'operatorParseDTO': None,
    }

    handlers.FileParseHandler().handle(handle)

    clean_path = Path(handle['cleanPath'])
    assert clean_path.read_bytes() == b'# hello'
    assert handle['_materialized_files'] == [str(clean_path)]

    storage.cleanup_task_files(handle)
    assert not clean_path.exists()
    assert '_materialized_files' not in handle


def test_split_handler_materializes_minio_clean_object(monkeypatch, tmp_path):
    from knowledge_base.task import handlers

    backend = _minio_backend()
    set_storage_backend(backend)
    monkeypatch.setenv('RKB_STORAGE_TEMP_PATH', str(tmp_path))
    backend.put('clean/ab/abc', b'# clean')

    captured = {}

    def _text_split(operator_id, args, python_path, file_format, clean_path,
                    file_name, file_size, kbase_id, split_preview=None):
        captured['clean_path'] = clean_path
        return {'results': [], 'chunks': []}

    monkeypatch.setattr(handlers.operator_runtime, 'text_split', _text_split)
    monkeypatch.setattr(handlers, '_update_status', lambda *args, **kwargs: None)

    handle = {
        'fileId': 'f1', 'kbaseId': 'kb1', 'format': 'md',
        'cleanPath': 'clean/ab/abc', 'fileName': 'a.md', 'fileSize': 7,
        'operatorSplitDTO': {'operatorId': '', 'args': []},
    }

    handlers.FileSplitHandler().handle(handle)

    assert Path(captured['clean_path']).read_bytes() == b'# clean'
    storage.cleanup_task_files(handle)
    assert not Path(captured['clean_path']).exists()
