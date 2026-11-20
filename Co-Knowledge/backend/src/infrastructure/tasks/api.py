"""统一任务管理 HTTP 面：列表、详情、统计、取消、重试、优先级。

挂载在对外前缀下（``/api/co-knowledge/v1/tasks``）。必须在该前缀的兜底路由
之前注册，否则会被 ``/{unknown_path:path}`` 吃掉。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from infrastructure.http.rkb_support import dispatch
from infrastructure.tasks import management


def build_router() -> APIRouter:
    router = APIRouter()

    # 静态路径必须在 /tasks/{task_id} 之前注册。
    @router.get('/tasks/stats')
    async def task_stats(request: Request):
        return await dispatch(request, lambda _payload: management.stats())

    @router.get('/tasks/groups')
    async def task_groups(request: Request, task_type: str | None = None,
                          status: str | None = None, lane: str | None = None,
                          kbase_id: str | None = None, keyword: str | None = None,
                          page: int = 1, size: int = 20):
        return await dispatch(
            request,
            lambda _payload: management.list_task_groups(
                task_type=task_type, status=status, lane=lane,
                kbase_id=kbase_id, keyword=keyword, page=page, size=size),
        )

    @router.get('/tasks')
    async def task_list(request: Request, task_type: str | None = None,
                        status: str | None = None, lane: str | None = None,
                        kbase_id: str | None = None, keyword: str | None = None,
                        page: int = 1, size: int = 20):
        return await dispatch(
            request,
            lambda _payload: management.list_tasks(
                task_type=task_type, status=status, lane=lane,
                kbase_id=kbase_id, keyword=keyword, page=page, size=size),
        )

    @router.get('/tasks/{task_id}')
    async def task_detail(request: Request, task_id: str):
        return await dispatch(
            request, lambda _payload: management.get_task(task_id))

    @router.post('/tasks/{task_id}/cancel')
    async def task_cancel(request: Request, task_id: str):
        return await dispatch(
            request,
            lambda payload: management.cancel_task(
                task_id, (payload or {}).get('reason')),
            with_body=True,
        )

    @router.post('/tasks/{task_id}/retry')
    async def task_retry(request: Request, task_id: str):
        return await dispatch(
            request, lambda _payload: management.retry_task(task_id))

    @router.patch('/tasks/{task_id}')
    async def task_patch(request: Request, task_id: str):
        return await dispatch(
            request,
            lambda payload: management.set_priority(
                task_id, (payload or {}).get('priority')),
            with_body=True, body_required=True,
        )

    return router


def register_task_api(app, prefix: str) -> None:
    app.include_router(build_router(), prefix=prefix)
