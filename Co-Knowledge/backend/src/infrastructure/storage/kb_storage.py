"""上传文件的落盘（与运行期容器共用同一个卷）。

路径规则：

* 正文文件：``<root>/core/<fileId 前 4 位>/<fileId>``
* 预览/解析临时文件：``<root>/tmp_preview/<UUID32>``

``<root>`` 取 ``RKB_KBASE_STORAGE_PATH``（compose 里等于运行期的 ``STORAGE_MAIN_PATH``）。
**必须与另两个容器挂到同一路径**：库里存的是绝对路径，挂错位置就是「文件找不到」，
而且是在检索/下载时才暴露。

**不要用 RKB 自己的 ``STORAGE_MAIN_PATH``**：那个指向 ``/data/rkb``，是 RKB 的插件与
日志目录根，与知识库文件是两回事。

## 本地卷 / MinIO 双后端

本模块的函数名保持不变，但正文文件、资产包可以经
:mod:`common.storage.backend` 落到 MinIO（``RKB_STORAGE_BACKEND=minio``）。
对象键与本地布局逐段一致（``core/...``、``dump/...``）。

``tmp_preview`` 与 ``clean`` 属于**进程内中间件**，在 MinIO 模式下仍写本地
scratch（``RKB_STORAGE_TEMP_PATH``）—— 解析/切片算子需要真实文件路径。

算子包（``operator/``、``operator_zip/``）与名称锁（``.locks``）**始终留在本地卷**：
前者的绝对路径已经进库，后者依赖 ``fcntl.flock``。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional, Tuple

from shared.errors.api import KbApiError
from infrastructure.logging.logutil import log
from infrastructure.storage import keys
from infrastructure.storage.backend import (
    local_root,
    normalize_key,
    scratch_root,
    storage_backend,
)

DEFAULT_STORAGE_ROOT = '/data/kb'

CORE_DIR = 'core'
TMP_PREVIEW_DIR = 'tmp_preview'


def storage_root() -> Path:
    """存储根。未设**或留空**时回落默认值（与 ``db.get_kbase_db_name`` 同一口径）。

    ⚠️ MinIO 模式下它仍然返回**本地卷根**：算子包、名称锁和 scratch 都在那里。
    持久文件的实际去处由 :func:`storage_backend` 决定。
    """
    return local_root()


def core_key(file_id: str) -> str:
    """正文文件的对象键：``core/<前 4 位>/<uuid>``。"""
    return keys.core_key(file_id)


def core_file_path(file_id: str) -> Path:
    """核心文件路径：``<root>/core/<前 4 位>/<uuid>``。

    前 4 位做子目录是为了避免单目录下文件过多 —— **不能改成别的分片规则**，
    否则按库里已有路径找旧文件会落空。

    只对本地后端有意义；MinIO 模式请用 :func:`core_key` / :func:`read_core_file`。
    """
    return storage_root() / core_key(file_id)


def save_core_file(content: bytes, file_id: str, cover: bool) -> Path | str:
    """把字节写到正文文件，返回**存储引用**。

    * 本地后端：返回绝对 ``Path``。
    * MinIO 后端：返回对象键字符串（后续由 :func:`materialize_ref` 物化）。

    覆盖语义与 ``LocalDiskUtil.saveCoreDirFile`` 一致：目标已存在且 ``cover=False`` 时**抛错**
    （而不是静默覆盖）—— 这是「同名文件必须显式选择覆盖」的落点。
    """
    key = core_key(file_id)
    try:
        storage_backend().put(key, content, overwrite=cover)
    except FileExistsError as error:
        raise KbApiError('file.save.error') from error
    local_path = storage_backend().local_path(key)
    reference = local_path if local_path is not None else key
    log.info('saved file %s (%d bytes, cover=%s)', reference, len(content), cover)
    return reference


def read_core_file(file_id: str) -> bytes:
    """读正文文件。文件不存在时抛 ``FileNotFoundError``（调用方按业务错误映射）。"""
    return storage_backend().get(core_key(file_id))


def core_file_exists(file_id: str) -> bool:
    return storage_backend().exists(core_key(file_id))


def delete_core_file(file_id: str) -> None:
    """``deleteCoreDirFile``：删正文文件；不存在不报错（删除入口到处在用）。"""
    key = core_key(file_id)
    try:
        storage_backend().delete(key)
        log.info('deleted file %s', key)
    except FileNotFoundError:
        log.warning('file %s not found when deleting', key)


def tmp_preview_dir(tmp_id: str) -> Path:
    """``<root>/tmp_preview/<UUID32>`` —— 预览/解析的中间产物。

    MinIO 模式下这里指向本地 scratch（``RKB_STORAGE_TEMP_PATH``），不是桶。
    """
    return scratch_root() / TMP_PREVIEW_DIR / keys.validate_component(tmp_id, 'tmp id')


def save_tmp_file(content: bytes) -> Path:
    """保存预览临时文件：``<root>/tmp_preview/<UUID32>``，返回绝对路径。

    预览链先把上传的文件写到这儿，再把**这个路径**交给文档处理模块（同一进程，读得到）。
    """
    path = tmp_preview_dir(uuid.uuid4().hex)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def delete_file_quietly(path) -> None:
    """``FileUtil.deleteFile``：删临时文件，失败不报错。"""
    try:
        Path(path).unlink()
    except (FileNotFoundError, IsADirectoryError, TypeError):
        pass


def materialize_ref(reference, suffix: str = '') -> Tuple[Path, bool]:
    """把存储引用变成**本地真实文件**，供算子/解析链使用。

    :param reference: ``save_core_file`` 的返回值（本地绝对路径或对象键），
        也可以是任务 handle 里的 ``diskPath`` / ``cleanPath``。
    :param suffix: 物化文件名后缀（如 ``.md``），只影响临时文件名。
    :return: ``(本地路径, 是否为临时文件)``。**临时文件由调用方负责清理**
        （任务链用 :func:`cleanup_task_files`）。

    本地绝对路径直接返回，``is_temp=False`` —— 不会误删原文件；文件是否存在交给下游
    （保持改造前「盘上缺文件由算子报错」的行为）。
    """
    if reference is None or not str(reference).strip():
        raise FileNotFoundError('empty storage reference')

    candidate = Path(str(reference))
    if candidate.is_absolute():
        # 本地引用直接返回，存在性交给下游（盘上缺文件时由解析/切片算子报错，
        # 而不是在 handler 里提前变成另一种错误）。
        return candidate, False

    key = normalize_key(str(reference))
    backend = storage_backend()
    local_path = backend.local_path(key)
    if local_path is not None and local_path.is_file():
        return local_path, False

    target = scratch_root() / 'materialized' / f'{uuid.uuid4().hex}{suffix or ""}'
    target.parent.mkdir(parents=True, exist_ok=True)
    backend.get_to_file(key, target)
    return target, True


def cleanup_materialized(path) -> None:
    """删除 :func:`materialize_ref` 产生的临时文件（失败不报错）。"""
    if not path:
        return
    try:
        Path(path).unlink()
    except (FileNotFoundError, IsADirectoryError, TypeError, OSError):
        pass


def cleanup_task_files(file_handle: Optional[dict]) -> None:
    """任务链收尾：清掉 handler 记录在 handle 上的物化临时文件。"""
    if not file_handle:
        return
    for path in file_handle.pop('_materialized_files', []) or []:
        cleanup_materialized(path)
