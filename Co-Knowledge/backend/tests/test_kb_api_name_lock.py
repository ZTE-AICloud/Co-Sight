"""建库名称锁的测试（B2）。

锁本身不难写，难的是**锁键与锁文件名必须按同一规则算** —— 两处对同一个名字用两把不同的
锁，等于没锁，而且不会报错，只会在并发建库时偶发地出现两个同名库。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_name_lock.py -q
"""

import base64
import threading
import time

import pytest

from knowledge_base import name_lock  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(name_lock.ENV_LOCK_DIR, str(tmp_path / 'locks'))
    return tmp_path / 'locks'


def test_lock_key_matches_java():
    """``(orgId ?? "") + ":" + (name ?? "")``。"""
    assert name_lock.build_lock_key('org1', 'kb') == 'org1:kb'
    assert name_lock.build_lock_key(None, 'kb') == ':kb'
    assert name_lock.build_lock_key('org1', None) == 'org1:'
    assert name_lock.build_lock_key(None, None) == ':'


def test_lock_file_name_is_base64url_without_padding():
    """``lock_<base64url(orgId + "_" + name)>.lock``（base64url 不带 ``=`` 填充）。"""
    expected = base64.urlsafe_b64encode(b'org1_kb').rstrip(b'=').decode()
    assert name_lock.build_lock_file_name('org1', 'kb') == f'lock_{expected}.lock'


def test_lock_file_name_handles_chinese_and_none():
    """中文名要按 UTF-8 编码后再 base64。"""
    expected = base64.urlsafe_b64encode('_知识库'.encode('utf-8')).rstrip(b'=').decode()

    assert name_lock.build_lock_file_name(None, '知识库') == f'lock_{expected}.lock'


def test_acquire_creates_then_keeps_the_lock_file():
    """拿到锁会建出锁文件；释放后**保留**（有意为之，见模块注释）。"""
    with name_lock.acquire('org1', 'kb'):
        path = name_lock.lock_dir() / name_lock.build_lock_file_name('org1', 'kb')
        assert path.exists()

    assert path.exists()


def test_second_acquire_times_out_while_first_holds():
    """同名并发：第二个拿不到，抛 NameLockAcquireException 而不是静默继续。"""
    errors = []
    started = threading.Event()

    def holder():
        with name_lock.acquire('org1', 'kb'):
            started.set()
            time.sleep(0.5)

    thread = threading.Thread(target=holder)
    thread.start()
    started.wait(timeout=2)

    with pytest.raises(name_lock.NameLockAcquireException):
        with name_lock.acquire('org1', 'kb', timeout_ms=100):
            errors.append('should not reach')

    thread.join(timeout=2)
    assert errors == []


def test_different_names_do_not_block_each_other():
    with name_lock.acquire('org1', 'kb-a'):
        with name_lock.acquire('org1', 'kb-b', timeout_ms=200):
            pass


def test_lock_is_released_after_exception():
    with pytest.raises(RuntimeError):
        with name_lock.acquire('org1', 'kb'):
            raise RuntimeError('boom')

    # 上一把已释放，这次应能立刻拿到
    with name_lock.acquire('org1', 'kb', timeout_ms=200):
        pass
