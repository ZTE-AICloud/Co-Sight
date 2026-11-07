"""知识库文件域的存储后端：本地共享卷 / MinIO（S3 兼容）。

为什么要这一层
--------------
文件域不能只换一个「客户端」：
解析/切片/抽图算子要的是**真实文件系统路径**，所以对象存储负责「持久文件」，
进程内处理仍然要落到本地 scratch。

两个后端
--------
* ``local``（默认）：文件落在 ``RKB_KBASE_STORAGE_PATH``（默认 ``/data/kb``）。
* ``minio``：持久文件按对象键写进桶；``LocalClient`` 的清洗中间件仍写本地 scratch，
  算子通过 :func:`infrastructure.storage.kb_storage.materialize_ref` 把对象下载成临时文件后再执行。

配置（全部环境变量，未配置时保持本地后端）
------------------------------------------
=============================  ==========================================
``RKB_STORAGE_BACKEND``        ``local`` | ``minio``（默认 ``local``）
``RKB_KBASE_STORAGE_PATH``     本地卷根（两个后端都用于算子包/锁/scratch）
``RKB_STORAGE_TEMP_PATH``      本地 scratch 根（MinIO 模式建议显式指定）
``RKB_MINIO_ENDPOINT``         ``minio:9000``（不含 scheme）
``RKB_MINIO_ACCESS_KEY``       访问密钥
``RKB_MINIO_SECRET_KEY``       密钥
``RKB_MINIO_BUCKET``           桶名（默认 ``rag-studio-kb``）
``RKB_MINIO_SECURE``           ``true`` 时用 HTTPS
``RKB_MINIO_REGION``           可选
``RKB_MINIO_PREFIX``           可选对象前缀（多环境/多租户隔离）
=============================  ==========================================

⚠️ MinIO 模式下本地卷**仍然必须挂载**：算子包（``operator_path`` 是库里的绝对路径）、
名称锁（``fcntl.flock``）和解析临时文件都依赖它。对象存储只接管持久文件。
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator, Optional, Protocol, Union

log = logging.getLogger(__name__)

BACKEND_LOCAL = 'local'
BACKEND_MINIO = 'minio'

ENV_BACKEND = 'RKB_STORAGE_BACKEND'
ENV_LOCAL_ROOT = 'RKB_KBASE_STORAGE_PATH'
ENV_TEMP_ROOT = 'RKB_STORAGE_TEMP_PATH'
ENV_MINIO_ENDPOINT = 'RKB_MINIO_ENDPOINT'
ENV_MINIO_ACCESS_KEY = 'RKB_MINIO_ACCESS_KEY'
ENV_MINIO_SECRET_KEY = 'RKB_MINIO_SECRET_KEY'
ENV_MINIO_BUCKET = 'RKB_MINIO_BUCKET'
ENV_MINIO_SECURE = 'RKB_MINIO_SECURE'
ENV_MINIO_REGION = 'RKB_MINIO_REGION'
ENV_MINIO_PREFIX = 'RKB_MINIO_PREFIX'

DEFAULT_LOCAL_ROOT = '/data/kb'
DEFAULT_MINIO_BUCKET = 'rag-studio-kb'
DEFAULT_CONTENT_TYPE = 'application/octet-stream'

_TRUTHY = {'1', 'true', 'yes', 'on'}

Source = Union[bytes, bytearray, memoryview, str, os.PathLike, BinaryIO]


class StorageBackend(Protocol):
    """后端契约。键一律是相对 POSIX 路径（见 :mod:`common.storage.keys`）。"""

    name: str

    def put(self, key: str, source: Source, *, overwrite: bool = True,
            content_type: Optional[str] = None) -> None:
        ...

    def get(self, key: str) -> bytes:
        ...

    def open(self, key: str) -> BinaryIO:
        ...

    def exists(self, key: str) -> bool:
        ...

    def size(self, key: str) -> int:
        """对象字节数；不存在时抛 ``FileNotFoundError``。"""
        ...

    def delete(self, key: str) -> None:
        ...

    def get_to_file(self, key: str, destination) -> None:
        ...

    def local_path(self, key: str) -> Optional[Path]:
        """本地后端返回落盘路径；对象存储返回 ``None``。"""


def normalize_key(key: str) -> str:
    """把键规范成相对 POSIX 路径；拒绝绝对路径与 ``..`` 逃逸。"""
    raw = str(key or '').replace('\\', '/')
    if raw.startswith('/'):
        raise ValueError(f'storage key must be relative: {key!r}')
    parts = []
    for part in raw.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            raise ValueError(f'storage key escapes root: {key!r}')
        parts.append(part)
    if not parts:
        raise ValueError('storage key is empty')
    return '/'.join(parts)


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or '').strip() or default


def _truthy(value) -> bool:
    return str(value or '').strip().lower() in _TRUTHY


def backend_name() -> str:
    """当前后端名；非法值在启动/首次使用时显式报错，不静默回落。"""
    name = _env(ENV_BACKEND, BACKEND_LOCAL).lower()
    if name not in (BACKEND_LOCAL, BACKEND_MINIO):
        raise RuntimeError(
            f'unsupported {ENV_BACKEND}={name!r}; expected {BACKEND_LOCAL!r} or {BACKEND_MINIO!r}')
    return name


def local_root() -> Path:
    """本地卷根（``RKB_KBASE_STORAGE_PATH``，留空回落 ``/data/kb``）。"""
    return Path(_env(ENV_LOCAL_ROOT, DEFAULT_LOCAL_ROOT))


def scratch_root() -> Path:
    """进程内 scratch 根。

    * 本地后端：**始终**是卷根 —— 保持 ``tmp_preview`` / ``clean`` 的路径，
      ``RKB_STORAGE_TEMP_PATH`` 不生效（避免升级后本地布局漂移）。
    * MinIO：``RKB_STORAGE_TEMP_PATH``；未配置时回落 ``<本地卷根>/tmp``。
      compose 里建议显式指到 ``rkb-storage``（``/data/rkb/tmp``）。
    """
    # 用**实际生效的后端**判断（测试会注入显式后端，环境变量可能没同步设）。
    if storage_backend().name == BACKEND_LOCAL:
        return local_root()
    configured = _env(ENV_TEMP_ROOT)
    return Path(configured) if configured else local_root() / 'tmp'


@contextmanager
def open_source(source: Source) -> Iterator[tuple[BinaryIO, int]]:
    """把 ``bytes`` / 文件路径 / 文件对象统一成 ``(stream, length)``。

    MinIO 的 ``put_object`` 必须知道长度；文件路径用 ``fstat`` 取，文件对象用
    ``seek/tell`` 取。不支持 seek 的流（极少）退化成整段读入内存。
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
        yield io.BytesIO(data), len(data)
        return

    if isinstance(source, (str, os.PathLike)):
        path = os.fspath(source)
        with open(path, 'rb') as handle:
            yield handle, os.fstat(handle.fileno()).st_size
        return

    handle = source
    try:
        position = handle.tell()
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        handle.seek(position)
        yield handle, end - position
    except (AttributeError, OSError, io.UnsupportedOperation):
        data = handle.read()
        yield io.BytesIO(data), len(data)


# ---------------------------------------------------------------------------
# 本地共享卷
# ---------------------------------------------------------------------------


class LocalBackend:
    """本地文件系统后端。路径规则与 ``LocalClient`` 一致。"""

    name = BACKEND_LOCAL

    def __init__(self, root):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / normalize_key(key)

    def put(self, key: str, source: Source, *, overwrite: bool = True,
            content_type: Optional[str] = None) -> None:
        path = self._path(key)
        if path.exists() and not overwrite:
            raise FileExistsError(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        # 先写临时文件再 rename：避免并发读拿到半截文件（覆盖上传时尤其重要）。
        tmp = path.with_name(f'.{path.name}.tmp-{uuid.uuid4().hex}')
        try:
            with open_source(source) as (stream, _length):
                with open(tmp, 'wb') as output:
                    shutil.copyfileobj(stream, output)
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def open(self, key: str) -> BinaryIO:
        return open(self._path(key), 'rb')

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def get_to_file(self, key: str, destination) -> None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(key), destination)

    def local_path(self, key: str) -> Optional[Path]:
        return self._path(key)


# ---------------------------------------------------------------------------
# MinIO / S3 兼容
# ---------------------------------------------------------------------------


def _error_code(error) -> str:
    code = getattr(error, 'code', None)
    if code:
        return str(code)
    response = getattr(error, 'response', None)
    if getattr(response, 'status', None) == 404:
        return 'NoSuchKey'
    return ''


def _is_missing(error) -> bool:
    return _error_code(error) in {
        'NoSuchKey', 'NoSuchObject', 'NoSuchBucket', 'NotFound', 'NoSuchVersion',
    }


class _MinioObjectReader:
    """把 ``get_object`` 的响应包成带 ``close`` 的只读流（释放连接）。"""

    def __init__(self, response):
        self._response = response

    def read(self, size: int = -1):
        return self._response.read(size)

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._response.release_conn()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class MinioBackend:
    """MinIO（S3 兼容）后端。``client`` 参数只给测试注入假客户端用。"""

    name = BACKEND_MINIO

    def __init__(self, endpoint: str, access_key: str = '', secret_key: str = '',
                 bucket: str = DEFAULT_MINIO_BUCKET, secure: bool = False,
                 region: Optional[str] = None, prefix: str = '', client=None):
        if not endpoint:
            raise RuntimeError(
                f'{ENV_MINIO_ENDPOINT} is required when {ENV_BACKEND}=minio')
        if not bucket:
            raise RuntimeError(f'{ENV_MINIO_BUCKET} must not be empty')
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.secure = secure
        self.region = region or None
        self.prefix = _normalize_prefix(prefix)
        self._client = client if client is not None else self._create_client()
        self._bucket_ready = False
        self._bucket_lock = threading.Lock()

    def _create_client(self):
        try:
            from minio import Minio
        except ImportError as error:  # pragma: no cover - 依赖缺失时给可执行的提示
            raise RuntimeError(
                'MinIO backend selected but the "minio" package is not installed. '
                'Install it (minio==7.2.15) or set RKB_STORAGE_BACKEND=local.') from error
        return Minio(
            self.endpoint,
            access_key=self.access_key or None,
            secret_key=self.secret_key or None,
            secure=self.secure,
            region=self.region,
        )

    def _object_name(self, key: str) -> str:
        normalized = normalize_key(key)
        return f'{self.prefix}/{normalized}' if self.prefix else normalized

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        with self._bucket_lock:
            if self._bucket_ready:
                return
            if not self._client.bucket_exists(self.bucket):
                try:
                    self._client.make_bucket(self.bucket, location=self.region)
                except Exception as error:  # noqa: BLE001 - 并发建桶时把「已存在」当成功
                    if _error_code(error) not in ('BucketAlreadyOwnedByYou', 'BucketAlreadyExists'):
                        raise
            self._bucket_ready = True

    def put(self, key: str, source: Source, *, overwrite: bool = True,
            content_type: Optional[str] = None) -> None:
        if not overwrite and self.exists(key):
            raise FileExistsError(self._object_name(key))
        self._ensure_bucket()
        with open_source(source) as (stream, length):
            self._client.put_object(
                self.bucket, self._object_name(key), stream, length,
                content_type=content_type or DEFAULT_CONTENT_TYPE)

    def get(self, key: str) -> bytes:
        self._ensure_bucket()
        response = None
        try:
            response = self._client.get_object(self.bucket, self._object_name(key))
            return response.read()
        except Exception as error:  # noqa: BLE001 - 按 S3 错误码分类
            if _is_missing(error):
                raise FileNotFoundError(self._object_name(key)) from error
            raise
        finally:
            if response is not None:
                try:
                    response.close()
                finally:
                    response.release_conn()

    def open(self, key: str) -> BinaryIO:
        self._ensure_bucket()
        try:
            response = self._client.get_object(self.bucket, self._object_name(key))
        except Exception as error:  # noqa: BLE001
            if _is_missing(error):
                raise FileNotFoundError(self._object_name(key)) from error
            raise
        return _MinioObjectReader(response)  # type: ignore[return-value]

    def exists(self, key: str) -> bool:
        self._ensure_bucket()
        try:
            self._client.stat_object(self.bucket, self._object_name(key))
            return True
        except Exception as error:  # noqa: BLE001
            if _is_missing(error):
                return False
            raise

    def size(self, key: str) -> int:
        self._ensure_bucket()
        try:
            stat = self._client.stat_object(self.bucket, self._object_name(key))
            return int(stat.size)
        except Exception as error:  # noqa: BLE001
            if _is_missing(error):
                raise FileNotFoundError(self._object_name(key)) from error
            raise

    def delete(self, key: str) -> None:
        self._ensure_bucket()
        try:
            self._client.remove_object(self.bucket, self._object_name(key))
        except Exception as error:  # noqa: BLE001 - 删除幂等
            if _is_missing(error):
                return
            raise

    def get_to_file(self, key: str, destination) -> None:
        self._ensure_bucket()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.fget_object(self.bucket, self._object_name(key), str(destination))
        except Exception as error:  # noqa: BLE001
            if _is_missing(error):
                raise FileNotFoundError(self._object_name(key)) from error
            raise

    def local_path(self, key: str) -> Optional[Path]:
        return None


def _normalize_prefix(prefix: str) -> str:
    raw = str(prefix or '').replace('\\', '/').strip('/')
    return normalize_key(raw) if raw else ''


# ---------------------------------------------------------------------------
# 单例与测试注入
# ---------------------------------------------------------------------------

_backend_lock = threading.Lock()
_backend_instance: Optional[StorageBackend] = None
_backend_signature = None
_explicit_backend: Optional[StorageBackend] = None


def _signature():
    return (
        backend_name(),
        _env(ENV_LOCAL_ROOT),
        _env(ENV_TEMP_ROOT),
        _env(ENV_MINIO_ENDPOINT),
        _env(ENV_MINIO_ACCESS_KEY),
        _env(ENV_MINIO_SECRET_KEY),
        _env(ENV_MINIO_BUCKET),
        _env(ENV_MINIO_SECURE),
        _env(ENV_MINIO_REGION),
        _env(ENV_MINIO_PREFIX),
    )


def storage_backend() -> StorageBackend:
    """按环境变量返回单例后端；配置变化时重建（测试/热切换友好）。"""
    global _backend_instance, _backend_signature

    if _explicit_backend is not None:
        return _explicit_backend

    signature = _signature()
    with _backend_lock:
        if _backend_instance is not None and signature == _backend_signature:
            return _backend_instance
        if signature[0] == BACKEND_MINIO:
            _backend_instance = MinioBackend(
                endpoint=_env(ENV_MINIO_ENDPOINT),
                access_key=_env(ENV_MINIO_ACCESS_KEY),
                secret_key=_env(ENV_MINIO_SECRET_KEY),
                bucket=_env(ENV_MINIO_BUCKET, DEFAULT_MINIO_BUCKET),
                secure=_truthy(_env(ENV_MINIO_SECURE)),
                region=_env(ENV_MINIO_REGION) or None,
                prefix=_env(ENV_MINIO_PREFIX),
            )
        else:
            _backend_instance = LocalBackend(local_root())
        _backend_signature = signature
        log.info('kb file storage backend: %s', _backend_instance.name)
        return _backend_instance


def set_storage_backend(backend: Optional[StorageBackend]) -> None:
    """显式指定后端（测试用；传 ``None`` 恢复按环境变量选择）。"""
    global _explicit_backend
    _explicit_backend = backend


def reset_storage_backend() -> None:
    """清空缓存单例与显式注入（测试的 autouse fixture 用）。"""
    global _backend_instance, _backend_signature, _explicit_backend
    with _backend_lock:
        _backend_instance = None
        _backend_signature = None
        _explicit_backend = None
