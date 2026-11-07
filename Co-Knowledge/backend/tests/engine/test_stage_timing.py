"""`engine.common.stage_timing` 的收集口径。

这里钉住的是「阶段耗时」的数据语义，而不是某个具体引擎：

* 没有请求收集器时必须是零副作用；
* 同一阶段多次执行累加（Router 多选）、不同阶段分开；
* 非有限/负数/bool 一律拒绝；0 是合法值（阶段跑了，只是很快）；
* 异常路径也要记录（重排器内部降级时，真实耗时不能丢）；
* reset 之后不能把上一次请求的数字带进下一次。
"""
import contextvars
import threading

import pytest

from engine.common import stage_timing


@pytest.fixture(autouse=True)
def _clean_collector():
    """每个用例从「没有活动收集器」开始，结束后也不留 contextvar。"""
    stage_timing._STAGES.set(None)
    yield
    stage_timing._STAGES.set(None)


def _fake_clock(monkeypatch, *values):
    """按顺序返回 perf_counter 值；调用次数超出即失败，避免漏测/多测。"""
    remaining = iter(values)

    def fake_perf_counter():
        try:
            return next(remaining)
        except StopIteration as error:  # pragma: no cover - 断言保护
            raise AssertionError('perf_counter called more times than expected') from error

    monkeypatch.setattr(stage_timing, 'perf_counter', fake_perf_counter)


def test_without_collector_record_and_measure_are_noops():
    # Act：没有 start()，measure 直接放行，record 不产生任何数据
    with stage_timing.measure(stage_timing.STAGE_RETRIEVAL):
        pass
    stage_timing.record(stage_timing.STAGE_RERANK, 12.5)

    # Assert
    assert stage_timing.snapshot() == {}


def test_measure_records_elapsed_time_in_milliseconds(monkeypatch):
    # Arrange
    stage_timing.start()
    _fake_clock(monkeypatch, 10.0, 10.25)

    # Act
    with stage_timing.measure(stage_timing.STAGE_RETRIEVAL):
        pass

    # Assert
    assert stage_timing.snapshot() == {stage_timing.STAGE_RETRIEVAL: 250.0}


def test_repeated_stage_executions_are_summed(monkeypatch):
    # Arrange：Router 多选会顺序执行多个子引擎，同阶段应累加
    stage_timing.start()
    _fake_clock(monkeypatch, 0.0, 0.1, 0.2, 0.35)

    # Act
    with stage_timing.measure(stage_timing.STAGE_RETRIEVAL):
        pass
    with stage_timing.measure(stage_timing.STAGE_RETRIEVAL):
        pass

    # Assert
    assert stage_timing.snapshot() == {stage_timing.STAGE_RETRIEVAL: 250.0}


def test_stages_are_independent_and_snapshot_has_fixed_order():
    # Arrange
    stage_timing.start()

    # Act：故意乱序记录
    stage_timing.record(stage_timing.STAGE_RERANK, 3.0)
    stage_timing.record(stage_timing.STAGE_RETRIEVAL, 2.0)
    stage_timing.record(stage_timing.STAGE_UNDERSTANDING, 1.0)
    snapshot = stage_timing.snapshot()

    # Assert：数值独立；顺序稳定为 understanding → retrieval → rerank
    assert snapshot == {
        stage_timing.STAGE_UNDERSTANDING: 1.0,
        stage_timing.STAGE_RETRIEVAL: 2.0,
        stage_timing.STAGE_RERANK: 3.0,
    }
    assert list(snapshot) == [
        stage_timing.STAGE_UNDERSTANDING,
        stage_timing.STAGE_RETRIEVAL,
        stage_timing.STAGE_RERANK,
    ]


def test_snapshot_returns_a_copy():
    # Arrange
    stage_timing.start()
    stage_timing.record(stage_timing.STAGE_RETRIEVAL, 5.0)

    # Act
    first = stage_timing.snapshot()
    first[stage_timing.STAGE_RETRIEVAL] = 999.0

    # Assert
    assert stage_timing.snapshot()[stage_timing.STAGE_RETRIEVAL] == 5.0


def test_reset_restores_previous_collector():
    # Arrange：外层请求有自己的收集器
    outer_token = stage_timing.start()
    stage_timing.record(stage_timing.STAGE_RETRIEVAL, 10.0)

    # Act：内层 start/reset 不应污染外层
    inner_token = stage_timing.start()
    stage_timing.record(stage_timing.STAGE_RETRIEVAL, 20.0)
    stage_timing.reset(inner_token)

    # Assert
    assert stage_timing.snapshot() == {stage_timing.STAGE_RETRIEVAL: 10.0}

    stage_timing.reset(outer_token)
    assert stage_timing.snapshot() == {}


@pytest.mark.parametrize('bad_value', [
    float('nan'),
    float('inf'),
    float('-inf'),
    -1,
    -0.1,
    True,
    False,
    '12.5',
    None,
])
def test_invalid_values_are_ignored(bad_value):
    # Arrange
    stage_timing.start()

    # Act
    stage_timing.record(stage_timing.STAGE_RERANK, bad_value)

    # Assert
    assert stage_timing.snapshot() == {}


def test_zero_is_a_valid_measurement():
    # Arrange
    stage_timing.start()

    # Act
    stage_timing.record(stage_timing.STAGE_UNDERSTANDING, 0)

    # Assert：0 表示「阶段跑了，只是很快」，不能和「没跑」混为一谈
    assert stage_timing.snapshot() == {stage_timing.STAGE_UNDERSTANDING: 0.0}


def test_values_are_rounded_to_one_decimal():
    # Arrange
    stage_timing.start()
    stage_timing.record(stage_timing.STAGE_RETRIEVAL, 12.3456)

    # Assert
    assert stage_timing.snapshot() == {stage_timing.STAGE_RETRIEVAL: 12.3}


def test_measure_records_time_when_body_raises(monkeypatch):
    # Arrange：重排器内部失败会降级继续，真实耗时仍应记录
    stage_timing.start()
    _fake_clock(monkeypatch, 1.0, 1.4)

    # Act / Assert
    with pytest.raises(RuntimeError):
        with stage_timing.measure(stage_timing.STAGE_RERANK):
            raise RuntimeError('rerank fallback')
    assert stage_timing.snapshot() == {stage_timing.STAGE_RERANK: 400.0}


def test_copied_contexts_sharing_the_dict_accumulate_without_loss():
    """contextvar 复制到子线程时共享同一个 dict；写入用锁，累加不能丢。"""
    # Arrange
    stage_timing.start()
    per_thread = 500
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        for _ in range(per_thread):
            stage_timing.record(stage_timing.STAGE_RETRIEVAL, 1.0)

    context_one = contextvars.copy_context()
    context_two = contextvars.copy_context()

    # Act
    threads = [
        threading.Thread(target=context_one.run, args=(worker,)),
        threading.Thread(target=context_two.run, args=(worker,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Assert
    assert stage_timing.snapshot() == {
        stage_timing.STAGE_RETRIEVAL: float(per_thread * 2)
    }
