import os

# 监听地址/端口可由环境变量覆盖。
# 容器内必须绑 0.0.0.0，否则 compose 网络内其他服务访问不到。
HOST = os.environ.get('KNOWLEDGE_BASE_HOST', '0.0.0.0')
PORT = int(os.environ.get('KNOWLEDGE_BASE_PORT', '8091'))

if __name__ == '__main__':
    # ``uvicorn`` / ``app`` 的 import **必须留在守卫内**。
    #
    # multiprocessing 的 spawn / forkserver 子进程会执行入口模块
    # （``spawn.prepare`` → ``_fixup_main_from_path`` → ``runpy.run_path(main.py,
    # run_name='__mp_main__')``）—— 这是 **prepare 阶段**的行为，把
    # ``'__main__'`` 从 forkserver 的 preload 里摘掉**拦不住它**。
    #
    # 顶层 ``from app import app`` 会让**每一个算子沙箱子进程**都把整个
    # FastAPI 应用重新导入一遍：建 DB 连接池、装日志 handler……
    # ``CompressedRotatingFileHandler.__init__ → _backup_remains → rotate →
    # os.remove`` 会撞上「日志文件已被别的进程转走」→ FileNotFoundError →
    # 子进程以 exitcode=1 死掉 → 文件任务报 ``RetCode.operator.split.error``。
    #
    # 加上守卫后子进程不再导入应用，这条崩溃路径连触发机会都没有；
    # 子进程启动也快了一大截。
    import uvicorn

    from app import app

    uvicorn.run(app=app, host=HOST, port=PORT)
