"""图谱库（V2 上传路径）**不入队**文件任务 —— 防止图谱文件被切分链误处理。

如果图谱链（``/graph/extract`` → ``graph_extract_v2_api.save_files`` →
``file_service.upload_files``）无条件 ``submit_task``，图谱链的 ``operatorSplitDTO``
是 null，切分 handler 把 None 交给 ``TextSplitService`` 的 ``operator_id < 0`` →
``TypeError`` → 任务重试 3 次 FAILED → 文件被标「处理失败」。

所以判据必须是 ``run_split_pipeline``（两种调用方的语义差），**不是** category：
``False`` 落盘后不入队、文件停在 ``-1``；``True`` 仍入队。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_graph_upload_no_split_task.py -q
"""

from pathlib import Path

import pytest

from knowledge_base.service import file_service  # noqa: E402
from graph.service import graph_extract_v2_api  # noqa: E402
from knowledge_base.service.file_service import UploadedFile  # noqa: E402
from knowledge_base.repository import directory as directory_store, kbase as kbase_store  # noqa: E402

KB = '447a9eb509e44d399790dbfd97f25360'
FOLDER_ROW = {'id': 'dir-1', 'kbase_id': KB, 'title': '默认文件夹',
              'type': directory_store.TYPE_FOLDER}
KB_ROW = {'id': 7, 'kbase_id': KB, 'file_count_limit': 5000,
          'embedding_model': 'qwen3-embedding'}

# 保存文件时 builder 出来的 metadata 形状
GRAPH_METADATA = {
    'kbaseId': KB, 'directoryId': 'dir-1', 'category': 10, 'splitType': 'system',
    'fileFrom': '1', 'kType': 'graph-document', 'coverFlag': False,
}

# ``/file/upload`` 那条（V1）的最小合规 metadata：算子表必须齐（split pipeline 才校验）
V1_METADATA = {
    'kbaseId': KB, 'directoryId': 'dir-1', 'kType': 'document', 'splitType': 'system',
    'splitOperator': {'md': {'operatorId': -1, 'args': []}},
}


class _FakeCursor:
    """只记录 SQL。``update_file_status`` 会先探一行（查不到 = NPE），给它回一行。"""

    def __init__(self, log):
        self._log = log
        self._sql = ''

    def execute(self, sql, params=None):
        self._sql = ' '.join(sql.split())
        self._log.append((self._sql, params))

    def fetchone(self):
        if self._sql.startswith('SELECT id FROM kb_directory'):
            return ('row-exists',)
        return None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, log):
        self._log = log

    def cursor(self):
        return _FakeCursor(self._log)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _QueueProbe:
    """代替 ``FileTaskQueue``：只记录 ``submit_task`` 的 handle。

    单测既不连库也不起 worker（真队列的 ``submit_task`` 会写 ``t_tasks``）。
    """

    def __init__(self):
        self.handles = []

    def submit_task(self, handle):
        self.handles.append(handle)
        return 'task-%d' % len(self.handles)


@pytest.fixture()
def fakes(monkeypatch):
    """把上传链的读写点全部换成假实现 —— 真逻辑（``upload_files``/``_save_one``）照跑。

    ``insert_directory`` / ``update_file_status`` 用**包装真函数**的方式钉住调用
    （保留参数顺序与 SQL 形状），不重写。
    """
    monkeypatch.setattr(directory_store, 'connection', lambda: _FakeConn([]))
    monkeypatch.setattr(directory_store, 'get_directory', lambda *a, **k: dict(FOLDER_ROW))
    monkeypatch.setattr(directory_store, 'count_files', lambda _k: 0)
    monkeypatch.setattr(kbase_store, 'select_kbase_by_id', lambda _k: dict(KB_ROW))
    monkeypatch.setattr(file_service, '_custom_operator_formats', lambda: set())
    monkeypatch.setattr(file_service.storage, 'save_core_file',
                        lambda content, file_id, cover=False: Path('/fake/core/%s' % file_id))

    inserts, status_writes = [], []
    real_insert = directory_store.insert_directory
    real_status = directory_store.update_file_status

    def _insert(cursor, kbase_id, parent_id, parent_path, title, dir_type, status,
                **kwargs):
        inserts.append({'title': title, 'type': dir_type, 'status': status,
                        'id': kwargs.get('directory_id'),
                        'file_from': kwargs.get('file_from')})
        return real_insert(cursor, kbase_id, parent_id, parent_path, title, dir_type,
                           status, **kwargs)

    def _status(cursor, file_id, status, fail_reason=None):
        status_writes.append((file_id, status, fail_reason))
        return real_status(cursor, file_id, status, fail_reason)

    monkeypatch.setattr(directory_store, 'insert_directory', _insert)
    monkeypatch.setattr(directory_store, 'update_file_status', _status)

    return {'inserts': inserts, 'status_writes': status_writes, 'queue': _QueueProbe()}


def _upload(fakes, metadata, *, run_split_pipeline, files=None):
    return file_service.upload_files(
        files or [UploadedFile('a.md', b'graph source')], dict(metadata), KB, 'emp-1',
        queue=fakes['queue'], run_split_pipeline=run_split_pipeline)


# ----------------------------------------------------------------------
# 枚举值先钉死：测试里的 -1/0/2 就是下面三个枚举成员
# ----------------------------------------------------------------------


def test_status_constants_match_file_upload_status_enum():
    """``FileUploadStatusEnum``：FILE_INIT=0 / FILE_UPLOAD_CLOUD_DISK=-1 / FAILURE=2。"""
    assert file_service.STATUS_INIT == 0
    assert file_service.STATUS_UPLOAD_CLOUD_DISK == -1
    assert file_service.STATUS_UPLOAD_FAILURE == 2


# ----------------------------------------------------------------------
# 不变量：run_split_pipeline=False（唯一调用方 = 抽图建库）不入队，停在 -1
# ----------------------------------------------------------------------


def test_v2_upload_does_not_enqueue_and_stops_at_cloud_disk(fakes):
    """不入队：队列为空；状态序列只有 V2 的两步 —— 建行 0 → 落盘 -1，没有别的。
    """
    result = _upload(fakes, GRAPH_METADATA, run_split_pipeline=False)

    assert fakes['queue'].handles == []                       # 没有任务
    assert len(fakes['inserts']) == 1
    assert fakes['inserts'][0]['status'] == file_service.STATUS_INIT           # 0
    assert fakes['inserts'][0]['type'] == directory_store.TYPE_FILE
    assert fakes['inserts'][0]['file_from'] == '1'                           # 本地上传

    file_id = result['a.md']
    # 唯一的 status 写入就是落盘成功那次；没有 STATUS_FAILURE(2)
    assert fakes['status_writes'] == [
        (file_id, file_service.STATUS_UPLOAD_CLOUD_DISK, None)]               # -1


def test_v2_flag_not_category_is_the_criterion(fakes):
    """判据是 ``run_split_pipeline`` 而不是 category：非图谱 category 走抽图语义同样不入队。

    如果实现改成「category != 10 才入队」，本用例会红 —— 判据只能是
    ``run_split_pipeline``，不能混入 category。
    """
    metadata = {**GRAPH_METADATA, 'category': 1, 'kType': 'document'}

    result = _upload(fakes, metadata, run_split_pipeline=False)

    assert fakes['queue'].handles == []
    assert fakes['status_writes'][-1][1] == file_service.STATUS_UPLOAD_CLOUD_DISK
    assert list(result) == ['a.md']


def test_v2_upload_disk_failure_marks_failed_and_does_not_enqueue(fakes, monkeypatch):
    """落盘失败 → 状态 2 + ``RetCode.file.save.error``，该文件不进返回结果，也不入队。"""

    def _boom(_content, _file_id, cover=False):
        raise OSError('disk full')

    monkeypatch.setattr(file_service.storage, 'save_core_file', _boom)

    result = _upload(fakes, GRAPH_METADATA, run_split_pipeline=False)

    assert result == {}
    assert fakes['queue'].handles == []
    file_id = fakes['inserts'][0]['id']
    assert fakes['status_writes'][-1] == (
        file_id, file_service.STATUS_UPLOAD_FAILURE, 'RetCode.file.save.error')


# ----------------------------------------------------------------------
# 阳性对照：run_split_pipeline=True（``/file/upload``）仍然入队（行为不变）
# ----------------------------------------------------------------------


def test_v1_upload_still_enqueues_split_task(fakes):
    """V1 落盘后入队，handle 带 ``operatorSplitDTO``（来源 = metadata 的算子表）。"""
    result = _upload(fakes, V1_METADATA, run_split_pipeline=True)

    assert len(fakes['queue'].handles) == 1
    handle = fakes['queue'].handles[0]
    assert handle['fileId'] == result['a.md']
    assert handle['operatorSplitDTO'] == {'operatorId': -1, 'args': []}
    assert handle['modelName'] == KB_ROW['embedding_model']
    assert fakes['status_writes'][-1][1] == file_service.STATUS_UPLOAD_CLOUD_DISK


def test_v1_default_runs_split_pipeline(fakes):
    """不传 ``run_split_pipeline``（= ``/file/upload`` 路由的调法）仍然入队。"""
    file_service.upload_files([UploadedFile('a.md', b'doc')], dict(V1_METADATA), KB,
                              'emp-1', queue=fakes['queue'])

    assert len(fakes['queue'].handles) == 1


def test_v1_with_graph_category_still_enqueues(fakes):
    """V1 + category=10 也照样入队 —— ``submitTask`` **无条件**
    （图谱文件走的是 V2，不是靠 V1 里加判断躲开的）。"""
    metadata = {**V1_METADATA, 'category': 10, 'kType': 'graph-document'}

    _upload(fakes, metadata, run_split_pipeline=True)

    assert len(fakes['queue'].handles) == 1


# ----------------------------------------------------------------------
# 调用点：``save_files`` 必须按 V2 语义调（漏传 run_split_pipeline 会重新入队）
# ----------------------------------------------------------------------


def test_graph_extract_v2_save_files_disables_split_pipeline(monkeypatch):
    """``GraphServiceImpl.saveFile`` → ``ImportKbFileServiceV2.uploadFile`` 的调用口径。

    这里只钉「调用点传了 ``run_split_pipeline=False``」——``upload_files`` 的入队行为由上面几
    条覆盖；两边都钉住，任何人单改一处都会红。
    """
    captured = {}

    def _fake_upload(files, metadata, kbase_id, emp_no, **kwargs):
        captured.update(files=files, metadata=metadata, kbase_id=kbase_id,
                        emp_no=emp_no, run_split_pipeline=kwargs.get('run_split_pipeline'))
        return {item.filename: 'fid' for item in files}

    monkeypatch.setattr(graph_extract_v2_api.directory_service,
                        'query_or_create_directory',
                        lambda kb_id, title: '%s:%s' % (kb_id, title))
    monkeypatch.setattr(graph_extract_v2_api.file_service, 'upload_files', _fake_upload)

    files = [UploadedFile('a.md', b'x')]
    graph_extract_v2_api.save_files({'kbId': KB}, files, '默认文件夹', 'emp-1')

    assert captured['run_split_pipeline'] is False
    assert captured['files'] == files
    assert captured['kbase_id'] == KB
    assert captured['emp_no'] == 'emp-1'
    assert captured['metadata']['directoryId'] == '%s:默认文件夹' % KB
    assert captured['metadata']['category'] == 10
    assert captured['metadata']['kType'] == 'graph-document'
    assert captured['metadata']['splitType'] == 'system'
    # 图谱链的 metadata 本来就没有算子表 —— 这正是「入队必炸」的源头
    assert 'splitOperator' not in captured['metadata']


# ----------------------------------------------------------------------
# 覆盖上传：属性行必须挂在已有文件行 id 上（10-26 FK 后的回归）
# ----------------------------------------------------------------------


def test_cover_upload_keeps_properties_on_the_existing_row(fakes, monkeypatch):
    """覆盖上传时属性写到**已有行 id**，不是新生成的 identifier uuid。

    ``metadata`` 不带 ``appendFileId`` 时 ``identifier_id`` 是新 uuid，
    与按文件名找到的旧行 id 不等，写入会抛 ``ForeignKeyViolation``
    （``kb_directory_property.file_id`` 不在 kb_directory）。
    """
    existing = {'id': 'existing-file-id', 'title': 'a.md'}
    monkeypatch.setattr(file_service, '_find_existing_file', lambda *a, **k: dict(existing))
    monkeypatch.setattr(file_service, '_purge_old_file', lambda *a, **k: None)

    props = []
    monkeypatch.setattr(directory_store, 'create_property',
                        lambda cursor, kbase_id, file_id, name, value:
                        props.append((file_id, name)))
    monkeypatch.setattr(directory_store, 'update_property',
                        lambda cursor, kbase_id, file_id, name, value:
                        props.append((file_id, name)))
    monkeypatch.setattr(directory_store, 'upsert_property',
                        lambda cursor, kbase_id, file_id, name, value:
                        props.append((file_id, name)))

    result = _upload(fakes, {**GRAPH_METADATA, 'coverFlag': True}, run_split_pipeline=False)

    assert result == {'a.md': 'existing-file-id'}
    assert fakes['inserts'] == []                       # 覆盖不插新行
    assert {file_id for file_id, _ in props} == {'existing-file-id'}
    # 覆盖走 upsert：K_TYPE 与 FILE_SIZE 都写，不再 INSERT 撞唯一键
    assert {name for _, name in props} >= {'KType', 'file_size'}
