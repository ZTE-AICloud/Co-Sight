"""``/file-tasks/*`` 的测试。

这一族用的是**第二套信封**（``{success,data,timestamp}`` 而不是 kb 信封），
且读的是进程内队列的状态 —— 所以测的重点是「哪些数据来自内存、哪些来自库」
以及三套分支（正常 / 查不到 / 出错）的形态差异。跑法::

    python -m pytest tests/test_kb_api_file_tasks.py -q
"""

from datetime import datetime

import pytest

from knowledge_base.service import file_task_service  # noqa: E402
from knowledge_base.task import handlers  # noqa: E402
from knowledge_base.task.wrapper import (  # noqa: E402
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    FileTask,
)


# ----------------------------------------------------------------------
# LocalDateTime 的序列化
# ----------------------------------------------------------------------


def test_iso_local_datetime_omits_fraction_when_whole_second():
    """整数秒**不带**小数点 —— ``ISO_LOCAL_DATE_TIME`` 的小数位是按需最少的。

    写死 9 位（或 6 位）都会错：``...41.05`` 这种两位小数必须原样保留。
    """
    assert file_task_service.iso_local_datetime(
        datetime(2026, 10, 12, 9, 21, 41)) == '2026-10-12T09:21:41'


@pytest.mark.parametrize('micro, expected', [
    (500000, '.5'),          # 0.5 秒 → "5"，尾随零去掉
    (50000, '.05'),          # 线上实测过这个（``...41.05``）
    (324607, '.324607'),
    (100000, '.1'),
])
def test_iso_local_datetime_strips_trailing_zeros(micro, expected):
    value = datetime(2026, 10, 12, 9, 21, 41, micro)
    assert file_task_service.iso_local_datetime(value) == '2026-10-12T09:21:41' + expected


def test_iso_local_datetime_passes_none_through():
    assert file_task_service.iso_local_datetime(None) is None


def test_to_millis_truncates_below_millisecond():
    """从库恢复的任务时间要截到毫秒 —— 库里的时间字段只精确到毫秒。"""
    from knowledge_base.task.queue import _to_millis

    truncated = _to_millis(datetime(2026, 10, 12, 9, 21, 45, 398338))
    assert truncated == datetime(2026, 10, 12, 9, 21, 45, 398000)
    assert _to_millis(None) is None


# ----------------------------------------------------------------------
# buildTaskInfo
# ----------------------------------------------------------------------


def _task(**overrides):
    task = FileTask(task_id='t1', file_handle={'fileId': 'f1', 'fileName': 'a.md'},
                    create_time=datetime(2026, 10, 12, 9, 0, 0))
    for key, value in overrides.items():
        setattr(task, key, value)
    return task


def test_build_task_info_keeps_null_fields():
    """值为 null 时**键也要在** —— 前端按固定字段集取值，少键会变成 undefined。"""
    info = file_task_service.build_task_info(_task())

    assert info['taskId'] == 't1'
    assert info['fileId'] == 'f1'
    assert info['fileName'] == 'a.md'
    assert info['status'] == STATUS_PENDING
    assert info['statusDescription'] == '待处理'
    assert info['startTime'] is None
    assert info['endTime'] is None
    assert info['errorMessage'] is None


def test_build_task_info_omits_duration_until_both_times_present():
    """``durationMillis`` / ``durationSeconds`` 是**键根本不出现**，不是写 null。"""
    no_start = file_task_service.build_task_info(_task(end_time=datetime(2026, 10, 12, 9, 1)))
    assert 'durationMillis' not in no_start
    assert 'durationSeconds' not in no_start

    both = file_task_service.build_task_info(_task(
        start_time=datetime(2026, 10, 12, 9, 0, 0), end_time=datetime(2026, 10, 12, 9, 0, 0, 199000)))
    assert both['durationMillis'] == 199
    assert both['durationSeconds'] == 0.199


def test_status_descriptions_match_task_status_enum():
    """五个状态的中文描述必须与 ``TaskStatus`` 对应（入库的是枚举名，展示用这个）。"""
    assert file_task_service.STATUS_DESCRIPTIONS == {
        'PENDING': '待处理', 'RUNNING': '执行中', 'RETRY': '重试中',
        'COMPLETED': '已完成', 'FAILED': '失败',
    }


def test_db_restored_task_has_file_id_but_no_file_name():
    """从库恢复的任务**只有 fileId**（来自 ``related_identifier_id``），没有 fileName。"""
    # 照 ``_load_task_from_db`` 的构造方式来（``max_retry_count=0`` 是那条路径显式传的）
    restored = FileTask(task_id='t2', file_handle={'fileId': 'f2'},
                        status=STATUS_COMPLETED, max_retry_count=0)
    info = file_task_service.build_task_info(restored)

    assert info['fileId'] == 'f2'
    assert info['fileName'] is None
    assert info['maxRetryCount'] == 0      # 从库恢复时固定 0
    assert info['startTime'] is None
    assert info['errorMessage'] is None


# ----------------------------------------------------------------------
# 异常文案
# ----------------------------------------------------------------------


def test_error_text_maps_empty_message_to_none():
    """异常可以没有消息，那时是 **null** 不是空串。

    线上 ``/file-tasks/failed`` 里那句 ``Error: null`` 就是这么来的。
    """
    assert file_task_service.error_text(Exception()) is None
    assert file_task_service.error_text(Exception('boom')) == 'boom'


def test_failure_message_renders_null_for_message_less_exception():
    task = _task(retry_count=3, max_retry_count=3)
    assert task.failure_message(Exception()) == 'Task failed after 3 retries. Error: null'
    assert task.failure_message(ValueError('x')) == 'Task failed after 3 retries. Error: x'


# ----------------------------------------------------------------------
# 第二套信封
# ----------------------------------------------------------------------


class _FakeQueue:
    def __init__(self, tasks, counts):
        self._tasks = tasks
        self._counts = counts

    def statistics(self):
        return self._counts

    def get_task(self, task_id):
        return self._tasks.get(task_id)

    def failed_tasks(self):
        return [t for t in self._tasks.values() if t.status == STATUS_FAILED]


@pytest.fixture
def fake_runtime(monkeypatch):
    counts = {'pendingCount': 1, 'runningCount': 0, 'completedCount': 7,
              'failedCount': 1, 'retryCount': 0, 'queueSize': 1,
              'queueCapacity': 2000, 'shutdown': False}
    tasks = {
        'hit': _task(task_id='hit', status=STATUS_RUNNING),
        'bad': _task(task_id='bad', status=STATUS_FAILED),
    }
    queue = _FakeQueue(tasks, counts)
    monkeypatch.setattr(file_task_service.runtime, 'get_queue', lambda: queue)
    return queue


def test_statistics_passes_queue_counts_through(fake_runtime):
    """统计**整份**来自队列 —— 只有 ``completedCount`` 是队列内部去查库算出来的。"""
    stats = file_task_service.statistics()

    assert stats['completedCount'] == 7
    assert stats['pendingCount'] == 1
    assert stats['queueCapacity'] == 2000
    assert set(stats) == {'pendingCount', 'runningCount', 'completedCount', 'failedCount',
                          'retryCount', 'queueSize', 'queueCapacity', 'shutdown'}


def test_task_detail_returns_none_when_missing(fake_runtime):
    assert file_task_service.task_detail('nope') is None
    assert file_task_service.task_detail('hit')['status'] == STATUS_RUNNING


def test_failed_tasks_only_lists_failed(fake_runtime):
    failed = file_task_service.failed_tasks()
    assert [item['taskId'] for item in failed] == ['bad']


# ----------------------------------------------------------------------
# F3：切分 handler 的 operatorId 类型归一
#
# 前端默认的 ``operatorId: ''``（``useSplitInfo.ts`` 的
# ``fileOperatorDefaultData()``）进了后台任务后会撞上 ``'' > 0`` →
# ``TypeError: '>' not supported between instances of 'str' and 'int'``
# —— 重试 3 次后 FAILED、文件 status=2。handler 拿到的永远是整数或 null；
# 这里按同一规则归一（见 ``_normalized_operator_id``）。
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw, expected', [
    (None, None), ('', None), ('  ', None),      # 空串/全空白串（wrapper）→ null
    ('3', 3), (' 3 ', 3), (3, 3),                # 数字串可强转（前后空白会被 trim）
    (1.5, 1),                                    # ACCEPT_FLOAT_AS_INT：截断
    (-1, -1), (0, 0),
])
def test_normalized_operator_id_matches_jackson_binding(raw, expected):
    assert handlers._normalized_operator_id(raw) == expected


@pytest.mark.parametrize('raw', [True, 'abc', {}, [1]])
def test_normalized_operator_id_rejects_unbindable_values(raw):
    """布尔/非数字串/对象/数组都是**绑定失败** —— 同规则抛 ValueError。"""
    with pytest.raises(ValueError):
        handlers._normalized_operator_id(raw)


class _SplitProbe:
    """收集 text_split 实参与状态写入 —— F3 的现场在 handler，不是纯函数。"""

    def __init__(self):
        self.calls = []
        self.statuses = []

    def text_split(self, operator_id, args, python_path, file_format, clean_path,
                   file_name, file_size, kbase_id, split_preview=None):
        self.calls.append({'operator_id': operator_id, 'args': args,
                           'python_path': python_path})
        return {'results': [], 'chunks': []}


@pytest.fixture()
def split_probe(monkeypatch):
    probe = _SplitProbe()
    monkeypatch.setattr(handlers.operator_runtime, 'text_split', probe.text_split)
    monkeypatch.setattr(
        handlers, '_update_status',
        lambda file_id, status, fail_reason=None: probe.statuses.append(
            (file_id, status, fail_reason)))
    monkeypatch.setattr(handlers, '_operator_python_path',
                        lambda operator_id: '/opt/op/%s.py' % operator_id)
    return probe


def _split_handle(operator_dto):
    return {'fileId': 'f1', 'kbaseId': 'kb1', 'format': 'md', 'cleanPath': '/tmp/a.md',
            'fileName': 'a.md', 'fileSize': 3, 'operatorSplitDTO': operator_dto}


def test_split_handler_survives_empty_operator_id(split_probe):
    """``operatorId=''`` 归一成 None → 默认参数分支（否则 TypeError，任务 3 次重试后 FAILED）。"""
    handle = _split_handle({'operatorId': '', 'args': []})

    handlers.FileSplitHandler().handle(handle)          # 不归一化这里会直接抛 TypeError

    call = split_probe.calls[0]
    assert call['operator_id'] is None
    assert [arg['argName'] for arg in call['args']] == ['emp_no', 'kbase_id']
    assert call['python_path'] is None                  # 不再走 operatorId > 0 分支
    assert split_probe.statuses[-1] == ('f1', handlers.STATUS_SPLIT_DONE, None)
    assert handle['splitResult'] == {'results': [], 'chunks': []}


def test_split_handler_accepts_numeric_string_operator_id(split_probe):
    """``"3"`` 绑定成 3 → 走 ``operatorId > 0`` 分支（取库里的 pythonPath）。"""
    handle = _split_handle({'operatorId': '3', 'args': []})

    handlers.FileSplitHandler().handle(handle)

    call = split_probe.calls[0]
    assert call['operator_id'] == 3
    assert call['python_path'] == '/opt/op/3.py'
    assert call['args'] == []                           # >0 分支不注入默认参数


# ----------------------------------------------------------------------
# 解析无内容 → 独立 fail_reason（不再是泛化的「切分算子执行失败」）
# ----------------------------------------------------------------------


def test_split_handler_persists_parse_empty_key(split_probe, monkeypatch):
    """``text_split`` 回「解析无内容」时，落库的是**独立键**，不是兜底的 split.error。

    现场：GoAccess 的 report.html（JS 渲染页，静态 DOM 无正文）在文档处理模块
    解析出 0 条文本。旧行为是静默 return → 下游读 corpus_file.txt 报
    FileNotFoundError → ``_post`` 兜底成 ``RetCode.operator.split.error``，
    用户看到「切分算子执行失败，请检查算子是否存在问题」——与真实原因无关。

    ⚠️ 这条用例的必要性：``test_kb_api_message_keys.py`` 是**静态扫描**，只保证
    「新键在 MESSAGES 里」，覆盖不到「chain 异常 → ``_fail_reason`` → 落库」这条链。
    上下游任何一端改回兜底键，只有这里会红。
    """
    from shared.errors.api import KbApiError

    def _raise(*args, **kwargs):
        raise KbApiError('RetCode.operator.split.empty')

    monkeypatch.setattr(handlers.operator_runtime, 'text_split', _raise)

    handle = _split_handle({'operatorId': '', 'args': []})
    with pytest.raises(KbApiError):
        handlers.FileSplitHandler().handle(handle)

    assert split_probe.statuses[-1] == ('f1', handlers.STATUS_FAILURE,
                                        'RetCode.operator.split.empty')
    # 兜底键**不得**再出现（出现即说明映射链断了）
    assert all(reason != 'RetCode.operator.split.error'
               for _fid, _status, reason in split_probe.statuses)


class _RaisingRuntime:
    """替身：``_runtime()`` 的返回物，被调时抛指定异常。

    合并前这两个用例是**假造 HTTP 响应**走真实的 ``_post`` 拆信封逻辑；进程内之后
    没有信封了，改为让 ``ingestion.runtime`` 抛异常，走的仍是真实的
    ``_invoke`` → ``_envelope_of`` → ``SPLIT_ERROR_MESSAGES`` 这条链 —— 所以
    「映射表写没写」「兜底键在不在」照样测得出来。
    """

    def __init__(self, error):
        self._error = error

    def __getattr__(self, name):          # text_split / file_parse / ...
        def _raise(*args, **kwargs):
            raise self._error
        return _raise


def _patch_runtime(monkeypatch, error):
    from knowledge_base.task import operator_runtime
    monkeypatch.setattr(operator_runtime, '_runtime', lambda: _RaisingRuntime(error))


def test_inprocess_maps_parse_empty_message_to_key(monkeypatch):
    """``ParseEmptyError``（带 code/bo/message 的异常）→ ``KbApiError`` 同键。

    走的是**真实的** ``_envelope_of`` 分支 2，而不是直接构造 KbApiError ——
    否则 ``SPLIT_ERROR_MESSAGES`` 写没写都测不出来。
    """
    from shared.errors.api import KbApiError
    from knowledge_base.task import operator_runtime

    class _ParseEmptyError(Exception):
        code = '0001'
        bo = None
        message = 'RetCode.operator.split.empty'

    _patch_runtime(monkeypatch, _ParseEmptyError('x'))
    with pytest.raises(KbApiError) as caught:
        operator_runtime.text_split(-2, [], None, 'html', '/tmp/a.html', 'a.html', 1, 'kb1')

    assert caught.value.key == 'RetCode.operator.split.empty'
    assert caught.value.code == '0001'


def test_inprocess_maps_parse_corrupt_message_to_key(monkeypatch):
    """``ParseCorruptError`` → ``RetCode.operator.split.corrupt``，不落算子兜底键。

    截断的 docx 在沙箱里抛 ``PackageNotFoundError``；若不映射这个错误，
    界面会显示「切分算子执行失败，请检查算子是否存在问题」。
    """
    from shared.errors.api import KbApiError
    from knowledge_base.task import operator_runtime

    class _ParseCorruptError(Exception):
        code = '0001'
        bo = None
        message = 'RetCode.operator.split.corrupt'

    _patch_runtime(monkeypatch, _ParseCorruptError('x'))
    with pytest.raises(KbApiError) as caught:
        operator_runtime.text_split(-2, [], None, 'docx', '/tmp/a.docx', 'a.docx', 1, 'kb1')

    assert caught.value.key == 'RetCode.operator.split.corrupt'
    assert caught.value.code == '0001'


def test_inprocess_unmapped_message_still_falls_back(monkeypatch):
    """没进映射表的 msg 仍走兜底键 —— 防「把兜底键删了」导致的空文案。"""
    from shared.errors.api import KbApiError
    from knowledge_base.task import operator_runtime

    _patch_runtime(monkeypatch, Exception('某个没见过的失败'))
    with pytest.raises(KbApiError) as caught:
        operator_runtime.text_split(-2, [], None, 'html', '/tmp/a.html', 'a.html', 1, 'kb1')

    assert caught.value.key == 'RetCode.operator.split.error'
    # 分支 3：没有 code/bo/message 的裸异常走 0001（原 pretty_error_response 的兜底码）
    assert caught.value.code == '0001'


def test_inprocess_sensitive_exception_uses_i18n_message(monkeypatch):
    """``SensitiveMsgException`` → 取 ``get_i18n_message('zh_CN')``（分支 1），但**落兜底键**。

    原 handler 先 ``except SensitiveMsgException`` 走 ``pretty_i18n_error_response``，
    取值方式与普通异常不同（拿 i18n 文案而不是 ``err.message``），所以要单测一条守住优先级。

    ⚠️ **落的是兜底键，不是 ``RetCode.sensitive.check.failed``** —— 因为
    ``SPLIT_ERROR_MESSAGES`` 里那条叫 ``SENSITIVE_ERROR_CODE``，与文档处理模块实际
    发出的 msg 对不上（该文件顶部的注释登记了这三条陈旧映射）。这是**既有缺口**，
    本用例把它钉成事实：改动映射表时应同步改这里。
    """
    from parsing.exception import SensitiveMsgException

    from shared.errors.api import KbApiError
    from knowledge_base.task import operator_runtime

    error = SensitiveMsgException(
        code='0006', bo=None,
        message_dict={'zh_CN': 'RetCode.sensitive.check.failed', 'en_US': 'sensitive'})
    _patch_runtime(monkeypatch, error)

    with pytest.raises(KbApiError) as caught:
        operator_runtime.text_split(-2, [], None, 'html', '/tmp/a.html', 'a.html', 1, 'kb1')

    assert caught.value.key == 'RetCode.operator.split.error'   # 兜底（映射表未命中）
    assert caught.value.code == '0006'                          # 码取自 SensitiveMsgException


# ----------------------------------------------------------------------
# 大文件忙等：映射真键 + 延迟重投
# ----------------------------------------------------------------------


def test_inprocess_maps_large_file_busy_to_its_own_key(monkeypatch):
    """``OperatorBusyError`` 的 message 是**全键** ``RetCode.file.size.more``。

    映射表里只写短名 ``FILE_SIZE_MORE`` 会命中不了、落到 ``RetCode.operator.split.error``
    —— 界面于是提示「请检查算子是否存在问题」，把排队问题说成算子问题。
    """
    from shared.errors.api import KbApiError
    from knowledge_base.task import operator_runtime

    class _Busy(Exception):
        code = '0001'
        bo = None
        message = 'RetCode.file.size.more'

    _patch_runtime(monkeypatch, _Busy('x'))
    with pytest.raises(KbApiError) as caught:
        operator_runtime.text_split(-2, [], None, 'pdf', '/tmp/a.pdf', 'a.pdf', 1, 'kb1')

    assert caught.value.key == 'RetCode.file.size.more'


def test_large_file_busy_key_has_a_localized_message():
    """落库键必须有文案；否则界面直接显示 ``RetCode.file.size.more`` 裸键。"""
    from shared.i18n.messages import render

    assert '大文件' in render('RetCode.file.size.more', 'zh')
    assert render('RetCode.file.size.more', 'en')


class _ResubmitQueue:
    def __init__(self):
        self.tasks = []

    def resubmit_task(self, task):
        self.tasks.append(task)
        return True


def test_busy_error_waits_before_retry(monkeypatch):
    from shared.errors.api import KbApiError
    from knowledge_base.task import executor

    slept = []
    monkeypatch.setattr(executor.time, 'sleep', lambda seconds: slept.append(seconds))
    task = FileTask(task_id='t1', file_handle={'fileId': 'f1'})
    queue = _ResubmitQueue()

    executor.FileTaskExecutor()._retry_task(
        queue, task, KbApiError('RetCode.file.size.more'))

    assert slept == [executor.BUSY_RETRY_DELAY_SECONDS]
    assert queue.tasks == [task]


def test_other_errors_retry_without_delay(monkeypatch):
    from shared.errors.api import KbApiError
    from knowledge_base.task import executor

    slept = []
    monkeypatch.setattr(executor.time, 'sleep', lambda seconds: slept.append(seconds))
    task = FileTask(task_id='t1', file_handle={'fileId': 'f1'})

    executor.FileTaskExecutor()._retry_task(
        _ResubmitQueue(), task, KbApiError('RetCode.operator.split.error'))

    assert slept == []


def test_large_file_keeps_the_real_error(monkeypatch):
    """大文件闸门内的真实失败（正文为空等）不能被折成「另一个大文件在处理」。

    旧实现两个 except 分支都 raise ``RetCode.file.size.more``，界面于是提示
    「当前已有大文件正在处理，请稍后重试」—— 用户会一直重试，永远看不到
    「文件没有可提取文本」这种真正的原因。
    """
    from ingestion import runtime as ingestion_runtime
    from shared.errors.api import KbApiError
    from knowledge_base.task import operator_runtime

    class _Empty(Exception):
        code = '0001'
        bo = None
        message = 'RetCode.operator.split.empty'

    def _boom(_info):
        raise _Empty('x')

    monkeypatch.setattr(ingestion_runtime.TextSplitService, 'text_split_entry', _boom)

    with pytest.raises(KbApiError) as caught:
        operator_runtime.text_split(
            -1, [], None, 'pdf', '/tmp/a.pdf', 'a.pdf',
            ingestion_runtime.LARGE_FILE_SIZE_LIMIT + 1, 'kb1')

    assert caught.value.key == 'RetCode.operator.split.empty'
