#!/usr/bin/env python3
"""验证 RKB 的启动生命周期：**import 不起后台线程，后台任务只在 lifespan 里启动**。

## 为什么需要这个脚本

源实现里 6 个常驻线程（语料队列消费者、每日清理、每 5 分钟清 file_track 的调度器…）
是在 ``src/app.py`` 的**模块级** ``threading.Thread(...).start()`` 启动的，而
``main.py`` 的 ``from app import app`` 在 ``if __name__`` 守卫**之外**。

这是数据正确性问题：沙箱执行算子走 multiprocessing 的
spawn/forkserver，子进程会 ``runpy.run_path(入口脚本)`` 重新执行入口模块的顶层语句
（CPython ``multiprocessing/spawn.py`` 的 ``_fixup_main_from_path``；forkserver 默认
``_preload_modules = ['__main__']`` 同理）。于是**每个沙箱子进程都会再起一份这些线程**：
重复消费语料队列、删掉正在被读取的文件、重复跑定时清理。

**当前 startup 不起任何常驻线程**，只做认证中间件与存储后端装配
（无 IO 的配置自检）。

**现有测试一条都覆盖不到这个性质**（``tests/`` 刻意不 import ``app.py``，
且全部是裸 ``TestClient(app)`` 构造 —— 不触发 lifespan），所以单独立此脚本。

## 判据

  A. 独立进程里 ``import app`` 之后，**除主线程外没有别的线程**
  B. 正在运行的服务**确实执行过 lifespan**（uvicorn 在 lifespan 完成后打印
     ``Application startup complete.``；应用自身的日志走 LOG_DIR 文件，不在
     docker logs 里，所以不能用应用日志行）

## 用法

宿主机上跑（需要 docker CLI）：

    python3 tools/verify/verify-startup-lifecycle.py [容器名]

容器名默认 ``rag-studio-rag-knowledge-base-1``，可用环境变量 ``RKB_CONTAINER`` 覆盖。
退出码 0 = 两段都过。
"""

import json
import os
import subprocess
import sys

CONTAINER = (
    (sys.argv[1] if len(sys.argv) > 1 else None)
    or os.environ.get('RKB_CONTAINER')
    or 'rag-studio-rag-knowledge-base-1'
)

#: 当前 startup 不起任何常驻线程。
EXPECTED_THREADS: list[str] = []

#: uvicorn/Starlette 在 lifespan 成功后打印的行（在 docker logs 里）
STARTUP_LOG_MARKER = 'Application startup complete.'

bad = 0


def section(title):
    print(f'--- {title}')


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def check_a_import_starts_nothing():
    """import app 不得起任何后台线程。"""
    global bad
    section('A. import app 的后台线程数')
    probe = (
        'import threading, json;'
        'import app;'
        'names = [t.name for t in threading.enumerate()]'
        ';print(json.dumps(names))'
    )
    result = run(['docker', 'exec', CONTAINER, 'python3', '-c', probe])
    if result.returncode != 0:
        print(f'  FAIL 探针失败（import app 就报错了？）:\n{result.stderr.strip()[-600:]}')
        bad += 1
        return

    try:
        names = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(f'  FAIL 探针输出无法解析: {result.stdout.strip()[:300]!r}')
        bad += 1
        return

    extra = [n for n in names if n != 'MainThread']
    if extra:
        print(f'  FAIL import app 起了 {len(extra)} 个额外线程: {extra}')
        print('       后台任务必须在 lifespan 里启，不能在模块级 —— 否则沙箱子进程会各起一份。')
        bad += 1
    else:
        print('  ok   import app 之后只有 MainThread（后台任务未随 import 启动）')


def check_b_running_service_has_them():
    """正在跑的服务必须执行过 lifespan；有具名线程时逐个核对。"""
    global bad
    section('B. 运行中的服务已执行 lifespan')
    result = run(['docker', 'logs', CONTAINER])
    # docker logs 把 stderr 也并到 stderr，这里两路都收
    logs = (result.stdout or '') + (result.stderr or '')

    lines = [ln for ln in logs.splitlines() if STARTUP_LOG_MARKER in ln]
    if not lines:
        print(f'  FAIL 日志里找不到启动行（{STARTUP_LOG_MARKER}）—— 服务可能没起来，')
        print('       或 lifespan 没跑（例如用了 uvicorn app:app 但 lifespan 未注册）。')
        bad += 1
        return

    if not EXPECTED_THREADS:
        print('  ok   lifespan 已执行；当前无启动期常驻线程（见模块注释）')
        return

    startup_line = lines[-1]
    missing = [name for name in EXPECTED_THREADS if name not in startup_line]
    if missing:
        print(f'  FAIL 启动行里缺线程: {missing}')
        print(f'       实际启动行: {startup_line.strip()[-300:]}')
        bad += 1
    else:
        print(f'  ok   {len(EXPECTED_THREADS)} 个后台线程都在: {EXPECTED_THREADS}')


def main():
    print(f'容器: {CONTAINER}')
    check_a_import_starts_nothing()
    check_b_running_service_has_them()
    print()
    if bad:
        print(f'FAIL {bad} 项未通过')
    else:
        print('ok  启动生命周期符合预期（import 无副作用 / lifespan 正常执行）')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
