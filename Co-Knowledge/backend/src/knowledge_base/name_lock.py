"""建库时的名称锁。

两级锁：

* 进程内：``threading.Lock``，串行化同进程内的同名建库；
* 跨进程：``fcntl.flock`` 非阻塞轮询，直到超时。

锁键为 ``orgId + ":" + name``，文件名为
``lock_<base64url(orgId + "_" + name)>.lock``，保证同一部署内算出的名字一致。

⚠️ **跨容器锁不住**：锁文件在各自容器的本地目录，不是共享卷。本服务按单副本部署
（见根 README「部署注意」），这种互斥只在单实例内有效。
"""

from __future__ import annotations

import base64
import errno
import fcntl
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from infrastructure.logging.logutil import log

ENV_LOCK_DIR = 'RKB_KBASE_LOCK_DIR'
DEFAULT_TIMEOUT_MS = 10000
DEFAULT_RETRY_INTERVAL_MS = 100


class NameLockAcquireException(Exception):
    """拿不到锁（超时/中断）。Service 层转成业务错误「知识库名称检查繁忙，请稍后重试」。"""


# 进程内的同名锁：key -> Lock。**不清理**（条目本身很小，清理反而要额外同步）
_jvm_locks: dict[str, threading.Lock] = {}
_jvm_locks_guard = threading.Lock()


def lock_dir() -> Path:
    """锁文件目录。默认放在共享卷下的 ``.locks`` 子目录，便于排查。

    与 ``storage.storage_root()`` 同一套「留空回落默认值」的口径。

    ⚠️ 锁始终是**本地文件锁**（``fcntl.flock``），不能搬到 MinIO。选
    ``RKB_STORAGE_BACKEND=minio`` 时本地卷仍必须挂载。
    """
    from infrastructure.storage import kb_storage as storage

    configured = (os.environ.get(ENV_LOCK_DIR) or '').strip()
    return Path(configured) if configured else storage.storage_root() / '.locks'


def build_lock_key(org_id: Optional[str], name: Optional[str]) -> str:
    """``(orgId ?? "") + ":" + (name ?? "")``。"""
    return '%s:%s' % (org_id or '', name or '')


def build_lock_file_name(org_id: Optional[str], name: Optional[str]) -> str:
    """``"lock_" + base64url_nopadding(orgId + "_" + name) + ".lock"``。"""
    raw = ('%s_%s' % (org_id or '', name or '')).encode('utf-8')
    encoded = base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')
    return 'lock_%s.lock' % encoded


def _jvm_lock(key: str) -> threading.Lock:
    with _jvm_locks_guard:
        lock = _jvm_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _jvm_locks[key] = lock
        return lock


@contextmanager
def acquire(org_id: Optional[str], name: Optional[str],
            timeout_ms: int = DEFAULT_TIMEOUT_MS,
            retry_interval_ms: int = DEFAULT_RETRY_INTERVAL_MS):
    """拿锁，用完自动释放。拿不到抛 :class:`NameLockAcquireException`。"""
    key = build_lock_key(org_id, name)
    jvm_lock = _jvm_lock(key)
    deadline = time.monotonic() + timeout_ms / 1000.0

    if not jvm_lock.acquire(timeout=timeout_ms / 1000.0):
        raise NameLockAcquireException('jvm lock timeout for %s' % key)

    lock_path = lock_dir() / build_lock_file_name(org_id, name)
    handle = None
    try:
        lock_dir().mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, 'a+b')
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NameLockAcquireException('file lock timeout for %s' % key)
                time.sleep(min(retry_interval_ms / 1000.0, remaining))
        yield
    finally:
        # 每步独立 catch：释放失败只告警不抛
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                log.warning('unlock flock failed for %s', lock_path, exc_info=True)
            try:
                handle.close()
            except OSError:
                log.warning('close lock file failed for %s', lock_path, exc_info=True)
            # ⚠️ **这里不删锁文件**。持锁者 unlink 会引出下面的 unlink 竞态，
            # 而「持锁者 unlink + 后来者另开新 inode」是经典的 unlink 竞态：
            # A 持锁 → B 打开同路径阻塞 → A unlink 并释放 → C 新建文件拿到新 inode 立刻获锁，
            # 于是 B 与 C 同时以为自己持锁。锁文件名不在任何对外契约里（纯实现细节），
            # 保留文件是严格更安全的选择。目录会在容器重建时自然清空。
        try:
            jvm_lock.release()
        except RuntimeError:
            log.warning('release jvm lock failed for %s', key, exc_info=True)
