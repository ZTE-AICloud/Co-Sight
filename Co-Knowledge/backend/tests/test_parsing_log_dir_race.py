"""并发解析时建日志目录是竞态：先 exists 再 makedirs，后到者会 FileExistsError。

场景：两个 .docx 同时上传、同时解析，
日志里::

    RuntimeError: [Errno 17] File exists: '/tmp/rkb-logs'

解析子进程导入 ``logutil`` 时各自建日志目录：两个进程都看到目录不存在，
一个 mkdir 成功，另一个抛 FileExistsError —— 这一份文档当次直接失败
（外层表现为「解析失败」，重试才轮到真正的解析错误）。

这里钉住：目录已存在时 ``get_file_handler`` 不能抛错。
"""

import os

from parsing.common import logutil


def test_log_dir_created_concurrently_does_not_raise(tmp_path, monkeypatch):
    logs_dir = tmp_path / 'rkb-logs'
    monkeypatch.setenv('LOG_DIR', str(logs_dir))

    # 模拟竞态：exists() 判定不存在，但 makedirs 时已被另一个进程建好。
    real_makedirs = os.makedirs

    def _makedirs(path, mode=0o777, exist_ok=False):
        if not exist_ok:
            raise FileExistsError(17, 'File exists', str(path))
        return real_makedirs(path, mode, exist_ok=True)

    monkeypatch.setattr(logutil.os, 'makedirs', _makedirs)

    handler = logutil.get_file_handler('race-test')
    try:
        assert list(logs_dir.glob('rkb-*.log'))
    finally:
        handler.close()
