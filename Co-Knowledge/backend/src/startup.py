"""服务启动装配（FastAPI lifespan）。

为什么不在 ``app.py`` 模块级执行：沙箱执行用户算子走 multiprocessing 的
spawn/forkserver，子进程会重新执行入口模块的顶层语句；模块级副作用会在每个
子进程重复一次。放进 lifespan 后只有真正启动服务才执行。
"""

import os
from contextlib import asynccontextmanager

from infrastructure.logging.logutil import log

_started = False


def start_background():
    """幂等启动：认证中间件类属性 + 文件存储后端启动期自检。"""
    global _started
    if _started:
        log.warning('start_background 已被调用过，忽略重复启动')
        return
    _started = True

    # 认证中间件只做类属性赋值（无 IO），但必须在有任何请求之前完成。
    from auth.middleware import AuthMiddleware
    from infrastructure.fs import paths

    # 内置公开路径（/health、/auth/status|login|logout）在中间件里写死；
    # filterfree 只是运维额外加的前缀白名单，保持为空。
    AuthMiddleware.filterfree = []
    AuthMiddleware.set_log_path(os.environ.get('LOG_DIR') or paths.get_log_dir())

    # AUTH_MODE 拼错（例如遗留的 jwt）必须阻止启动，而不是静默变成无鉴权。
    # 本地账号：首次启动播种 admin（异常只记日志，不阻断服务启动）。
    from auth import bootstrap, service as auth_service

    auth_service.validate_auth_mode()
    bootstrap.ensure_initial_admin()

    # 默认算子：新装库的 operator 表为空时，「新建知识图谱」的算子下拉没有内容。
    # 与 admin 播种同策略：失败只记日志，不阻断服务启动。
    from operators import bootstrap as operator_bootstrap

    operator_bootstrap.ensure_default_operators()

    # 文件域后端：显式构造一次，把「选了 minio 但 SDK 没装 / 端点没配」这类配置
    # 错误暴露在启动期，而不是第一次上传时。
    from infrastructure.storage.backend import backend_name, storage_backend

    log.info('知识库文件存储后端: %s', backend_name())
    storage_backend()


def stop_background():
    global _started
    _started = False


@asynccontextmanager
async def build_lifespan(app):
    start_background()
    try:
        # Agent 接口（可选）：MCP 的 StreamableHTTPSessionManager 必须在这个
        # lifespan 里 run()。延迟 import：没开 agent api 时也不该拉起 FastMCP 对象。
        from agent.mount import agent_lifespan

        async with agent_lifespan(app):
            yield
    finally:
        stop_background()
