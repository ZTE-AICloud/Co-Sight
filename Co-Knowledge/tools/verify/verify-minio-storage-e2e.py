"""MinIO / 本地卷双后端的真实环境验收。

为什么单独有一个脚本
--------------------
``tests/test_kb_api_storage_backend.py`` 用假客户端覆盖了键规则与错误映射，但
「装了 minio SDK、连得上真实 MinIO、自动建桶、multipart/流式读写」只有真环境能验。
本脚本直接调 :class:`common.storage.backend.MinioBackend`，不经过知识库业务链，
所以可以单独在容器里跑，不会写业务表。

跑法（MinIO 已起、RKB 镜像已包含 minio SDK）::

    docker compose -f deploy/docker-compose.yml --profile minio up -d minio rag-knowledge-base
    docker exec rag-studio-rag-knowledge-base-1 \
        python3 /tmp/verify-minio-storage-e2e.py

也可以在宿主跑（``PYTHONPATH=backend/src``），但宿主必须能解析
``RKB_MINIO_ENDPOINT``（容器内默认 ``minio:9000``，宿主应改成 ``127.0.0.1:9000``
并给 minio 加端口映射）。

退出码：0 = 全部通过；1 = 有失败（逐条打印）。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / 'backend' / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from infrastructure.storage.backend import (  # noqa: E402
    LocalBackend,
    MinioBackend,
    _env,
    _truthy,
    ENV_MINIO_ACCESS_KEY,
    ENV_MINIO_BUCKET,
    ENV_MINIO_ENDPOINT,
    ENV_MINIO_PREFIX,
    ENV_MINIO_REGION,
    ENV_MINIO_SECRET_KEY,
    ENV_MINIO_SECURE,
    DEFAULT_MINIO_BUCKET,
)

FAILURES = []


def check(name, condition, detail=''):
    if condition:
        print(f'PASS  {name}')
    else:
        print(f'FAIL  {name}  {detail}')
        FAILURES.append(name)


def verify_local():
    import tempfile

    with tempfile.TemporaryDirectory(prefix='rkb-local-storage-') as tmp:
        backend = LocalBackend(tmp)
        key = f'core/ab/{uuid.uuid4().hex}'
        backend.put(key, b'local-bytes')
        check('local.put/get', backend.get(key) == b'local-bytes')
        check('local.exists', backend.exists(key))
        check('local.local_path', backend.local_path(key).is_file())
        try:
            backend.put(key, b'other', overwrite=False)
            check('local.cover=false', False, 'expected FileExistsError')
        except FileExistsError:
            check('local.cover=false', True)
        destination = Path(tmp) / 'download.bin'
        backend.get_to_file(key, destination)
        check('local.get_to_file', destination.read_bytes() == b'local-bytes')
        backend.delete(key)
        check('local.delete', not backend.exists(key))


def verify_minio():
    backend = MinioBackend(
        endpoint=_env(ENV_MINIO_ENDPOINT, 'minio:9000'),
        access_key=_env(ENV_MINIO_ACCESS_KEY),
        secret_key=_env(ENV_MINIO_SECRET_KEY),
        bucket=_env(ENV_MINIO_BUCKET, DEFAULT_MINIO_BUCKET),
        secure=_truthy(_env(ENV_MINIO_SECURE)),
        region=_env(ENV_MINIO_REGION) or None,
        prefix=_env(ENV_MINIO_PREFIX),
    )
    key = f'verify/{uuid.uuid4().hex}'
    try:
        backend.put(key, b'minio-bytes')
        check('minio.put/get', backend.get(key) == b'minio-bytes')
        check('minio.exists', backend.exists(key))
        try:
            backend.put(key, b'other', overwrite=False)
            check('minio.cover=false', False, 'expected FileExistsError')
        except FileExistsError:
            check('minio.cover=false', True)
        backend.put(key, b'minio-overwritten', overwrite=True)
        check('minio.cover=true', backend.get(key) == b'minio-overwritten')

        destination = Path('/tmp') / f'rkb-minio-{uuid.uuid4().hex}.bin'
        try:
            backend.get_to_file(key, destination)
            check('minio.get_to_file', destination.read_bytes() == b'minio-overwritten')
        finally:
            destination.unlink(missing_ok=True)

        stream = backend.open(key)
        try:
            check('minio.open', stream.read() == b'minio-overwritten')
        finally:
            stream.close()

        backend.delete(key)
        check('minio.delete', not backend.exists(key))
        check('minio.local_path', backend.local_path(key) is None)
    finally:
        backend.delete(key)


def main():
    print('--- local backend ---')
    verify_local()
    print('\n--- minio backend ---')
    try:
        verify_minio()
    except Exception as error:  # noqa: BLE001 - 验收脚本要把失败原因打全
        print(f'FAIL  minio backend raised: {error!r}')
        FAILURES.append('minio backend')

    print()
    if FAILURES:
        print(f'FAILED: {len(FAILURES)} check(s): {", ".join(FAILURES)}')
        return 1
    print('ALL CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
