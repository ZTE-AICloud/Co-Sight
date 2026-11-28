"""Text2SQL 接口层（``{RKB_PREFIX}/text2sql``）。

纯 REST：成功体就是资源/动作结果本身；错误是 RFC 9457 problem+json。
DB 与外部库调用都可能阻塞，统一走线程池。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request, Response
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from starlette.concurrency import run_in_threadpool

from infrastructure.http import kb_responses as responses
from infrastructure.http.identity import current_user, language
from infrastructure.logging.logutil import log
from shared.errors.api import KbApiError
from shared.problem import (INTERNAL_ERROR, ApiError, generic_detail,
                            problem_body)
from text_to_sql.errors import Text2SqlError, Text2SqlValidationError
from text_to_sql.query_service import (Text2SqlQueryService,
                                      get_query_service)
from text_to_sql.service import Text2SqlService


async def _dispatch(request: Request, fn, *, with_body: bool = False):
    raw = await request.body() if with_body else b''
    return await run_in_threadpool(_dispatch_sync, request, raw, fn, with_body)


def _dispatch_sync(request: Request, raw: bytes, fn, with_body: bool):
    lang = language(request)
    try:
        if with_body:
            payload = responses.parse_json_body(raw, required=True)
            result = fn(payload)
        else:
            result = fn()
        if isinstance(result, Response):
            return result
        if result is None:
            return responses.no_content()
        return responses.success(result)
    except Text2SqlError as error:
        return responses.error(error, lang, request=request)
    except KbApiError as error:
        return responses.error(error, lang, request=request)
    except ValueError as error:
        log.warning('text_to_sql api malformed body: %s', error)
        return responses.error(Text2SqlError('请求体格式不正确'), lang, request=request)
    except Exception:
        log.exception('text_to_sql api unexpected error')
        return responses.server_error(lang, request=request)


def _problem_payload(error: ApiError, lang: str, request: Request) -> dict:
    """SSE ``event: error`` 的帧体：与普通 problem+json 响应同形。"""
    spec = error.problem_spec()
    return problem_body(spec, error.problem_detail(lang),
                        instance=request.url.path)


def _positive_int(value, default: int, field: str) -> int:
    if value is None or value == '':
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise Text2SqlValidationError(f'{field} 必须是整数') from error
    if parsed < 1:
        raise Text2SqlValidationError(f'{field} 必须大于 0')
    return parsed


def build_router(service: Text2SqlService,
                 query_service: Text2SqlQueryService | None = None) -> APIRouter:
    """构造端点（不绑定前缀；由 ``register_text_to_sql_api`` 挂载）。"""
    router = APIRouter()
    queries = query_service or get_query_service()

    @router.get('/datasources')
    async def list_datasources(request: Request):
        return await _dispatch(request, service.list_datasources)

    @router.post('/datasources')
    async def create_datasource(request: Request):
        def run(payload):
            _require_admin(request)
            data = service.create_datasource(payload)
            return responses.created(data, location=f"/datasources/{data['id']}")

        return await _dispatch(request, run, with_body=True)

    @router.post('/datasources/connection-test')
    async def test_connection_payload(request: Request):
        def run(payload):
            # 连的是尚未保存的地址：同样由服务端发起连接，必须限管理员。
            _require_admin(request)
            return service.test_connection_payload(payload)

        return await _dispatch(request, run, with_body=True)

    @router.get('/datasources/{datasource_id}')
    async def get_datasource(request: Request, datasource_id: str):
        return await _dispatch(request,
                               lambda: service.get_datasource(datasource_id))

    @router.patch('/datasources/{datasource_id}')
    async def update_datasource(request: Request, datasource_id: str):
        def run(payload):
            _require_admin(request)
            return service.update_datasource(datasource_id, payload)

        return await _dispatch(request, run, with_body=True)

    @router.delete('/datasources/{datasource_id}')
    async def delete_datasource(request: Request, datasource_id: str):
        def run():
            _require_admin(request)
            service.delete_datasource(datasource_id)
            return None

        return await _dispatch(request, run)

    @router.post('/datasources/{datasource_id}/connection-test')
    async def test_connection(request: Request, datasource_id: str):
        def run():
            _require_admin(request)
            return service.test_connection(datasource_id)

        return await _dispatch(request, run)

    @router.post('/datasources/{datasource_id}/scan')
    async def scan_datasource(request: Request, datasource_id: str):
        def run():
            _require_admin(request)
            return service.scan(datasource_id)

        return await _dispatch(request, run)

    @router.post('/datasources/{datasource_id}/assist')
    async def assist(request: Request, datasource_id: str):
        """AI 辅助：只返回建议，不落库；采纳仍走各 PATCH 接口。"""

        def run(payload):
            _require_admin(request)
            return service.assist(datasource_id, payload)

        return await _dispatch(request, run, with_body=True)

    @router.post('/datasources/{datasource_id}/assist/stream')
    async def assist_stream(request: Request, datasource_id: str):
        """AI 辅助的 SSE 版：``stage`` 帧上报进度（采集/样本/生成批次），
        ``result`` 帧是完整建议体。语义与同步 ``/assist`` 一致。"""
        lang = language(request)
        raw = await request.body()
        try:
            payload = responses.parse_json_body(raw, required=True)
        except ValueError as error:
            log.warning('text_to_sql api malformed body: %s', error)
            return responses.error(Text2SqlError('请求体格式不正确'), lang,
                                   request=request)
        _require_admin(request)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(kind: str, data) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (kind, data))
            except RuntimeError:
                log.warning('text_to_sql assist stream loop closed; drop %s', kind)

        def work():
            try:
                for kind, data in service.assist_events(datasource_id, payload):
                    emit(kind, data)
            except Text2SqlError as error:
                emit('error', _problem_payload(error, lang, request))
            except KbApiError as error:
                emit('error', _problem_payload(error, lang, request))
            except ValueError:
                emit('error', _problem_payload(
                    Text2SqlError('请求体格式不正确'), lang, request))
            except Exception:
                log.exception('text_to_sql assist stream failed')
                emit('error', problem_body(
                    INTERNAL_ERROR, generic_detail(INTERNAL_ERROR, lang),
                    instance=request.url.path))
            finally:
                emit('_close', None)

        async def frames():
            task = asyncio.create_task(run_in_threadpool(work))
            try:
                while True:
                    kind, data = await queue.get()
                    if kind == '_close':
                        break
                    yield ServerSentEvent(
                        event=kind,
                        data=json.dumps(data, ensure_ascii=False, default=str))
                yield ServerSentEvent(event='done', data='{}')
            finally:
                if not task.done():
                    task.cancel()

        return EventSourceResponse(frames(), ping=15)

    @router.get('/datasources/{datasource_id}/tables')
    async def list_tables(request: Request, datasource_id: str):
        return await _dispatch(request,
                               lambda: service.list_tables(datasource_id))

    @router.patch('/datasources/{datasource_id}/tables/{table_id}')
    async def update_table(request: Request, datasource_id: str, table_id: str):
        return await _dispatch(
            request,
            lambda payload: service.update_table(datasource_id, table_id, payload),
            with_body=True)

    @router.patch('/datasources/{datasource_id}/columns/{column_id}')
    async def update_column(request: Request, datasource_id: str, column_id: str):
        return await _dispatch(
            request,
            lambda payload: service.update_column(datasource_id, column_id, payload),
            with_body=True)

    # ------------------------------------------------------------------
    # 关联
    # ------------------------------------------------------------------
    @router.get('/datasources/{datasource_id}/relations')
    async def list_relations(request: Request, datasource_id: str):
        return await _dispatch(request,
                               lambda: service.list_relations(datasource_id))

    @router.post('/datasources/{datasource_id}/relations')
    async def create_relation(request: Request, datasource_id: str):
        def run(payload):
            data = service.create_relation(datasource_id, payload)
            return responses.created(data)

        return await _dispatch(request, run, with_body=True)

    @router.patch('/datasources/{datasource_id}/relations/{relation_id}')
    async def update_relation(request: Request, datasource_id: str, relation_id: str):
        return await _dispatch(
            request,
            lambda payload: service.update_relation(datasource_id, relation_id, payload),
            with_body=True)

    @router.delete('/datasources/{datasource_id}/relations/{relation_id}')
    async def delete_relation(request: Request, datasource_id: str, relation_id: str):
        return await _dispatch(
            request, lambda: service.delete_relation(datasource_id, relation_id))

    @router.post('/datasources/{datasource_id}/relations/{relation_id}/verification')
    async def verify_relation(request: Request, datasource_id: str, relation_id: str):
        actor = current_user(request)

        def run(payload):
            _require_admin(request)
            return service.verify_relation(datasource_id, relation_id, payload, actor)

        return await _dispatch(request, run, with_body=True)

    # ------------------------------------------------------------------
    # 枚举
    # ------------------------------------------------------------------
    @router.get('/datasources/{datasource_id}/values')
    async def list_values(request: Request, datasource_id: str):
        column_id = request.query_params.get('columnId') or None
        return await _dispatch(
            request, lambda: service.list_values(datasource_id, column_id))

    @router.post('/datasources/{datasource_id}/values')
    async def create_value(request: Request, datasource_id: str):
        def run(payload):
            data = service.create_value(datasource_id, payload)
            return responses.created(data)

        return await _dispatch(request, run, with_body=True)

    @router.patch('/datasources/{datasource_id}/values/{value_id}')
    async def update_value(request: Request, datasource_id: str, value_id: str):
        return await _dispatch(
            request,
            lambda payload: service.update_value(datasource_id, value_id, payload),
            with_body=True)

    @router.delete('/datasources/{datasource_id}/values/{value_id}')
    async def delete_value(request: Request, datasource_id: str, value_id: str):
        return await _dispatch(
            request, lambda: service.delete_value(datasource_id, value_id))

    # ------------------------------------------------------------------
    # 指标
    # ------------------------------------------------------------------
    @router.get('/datasources/{datasource_id}/metrics')
    async def list_metrics(request: Request, datasource_id: str):
        return await _dispatch(request, lambda: service.list_metrics(datasource_id))

    @router.post('/datasources/{datasource_id}/metrics')
    async def create_metric(request: Request, datasource_id: str):
        def run(payload):
            data = service.create_metric(datasource_id, payload)
            return responses.created(data)

        return await _dispatch(request, run, with_body=True)

    @router.patch('/datasources/{datasource_id}/metrics/{metric_id}')
    async def update_metric(request: Request, datasource_id: str, metric_id: str):
        return await _dispatch(
            request,
            lambda payload: service.update_metric(datasource_id, metric_id, payload),
            with_body=True)

    @router.delete('/datasources/{datasource_id}/metrics/{metric_id}')
    async def delete_metric(request: Request, datasource_id: str, metric_id: str):
        return await _dispatch(
            request, lambda: service.delete_metric(datasource_id, metric_id))

    @router.post('/datasources/{datasource_id}/metrics/{metric_id}/status')
    async def set_metric_status(request: Request, datasource_id: str, metric_id: str):
        actor = current_user(request)

        def run(payload):
            _require_admin(request)
            return service.set_metric_status(datasource_id, metric_id, payload, actor)

        return await _dispatch(request, run, with_body=True)

    # ------------------------------------------------------------------
    # 配置版本 / 发布
    # ------------------------------------------------------------------
    @router.post('/datasources/{datasource_id}/versions')
    async def create_version(request: Request, datasource_id: str):
        actor = current_user(request)

        def run(payload):
            data = service.create_version(datasource_id, payload, actor)
            if data.get('created'):
                return responses.created(data)
            return responses.success(data)

        return await _dispatch(request, run, with_body=True)

    @router.get('/datasources/{datasource_id}/versions')
    async def list_versions(request: Request, datasource_id: str):
        return await _dispatch(request, lambda: service.list_versions(datasource_id))

    @router.get('/datasources/{datasource_id}/versions/{version_id}')
    async def get_version(request: Request, datasource_id: str, version_id: str):
        return await _dispatch(
            request, lambda: service.get_version(datasource_id, version_id))

    @router.post('/datasources/{datasource_id}/versions/{version_id}/build')
    async def build_version(request: Request, datasource_id: str, version_id: str):
        def run():
            return service.start_build(datasource_id, version_id)

        return await _dispatch(request, run)

    @router.post('/datasources/{datasource_id}/publication')
    async def publish_version(request: Request, datasource_id: str):
        actor = current_user(request)

        def run(payload):
            _require_admin(request)
            return responses.created(service.publish(datasource_id, payload, actor))

        return await _dispatch(request, run, with_body=True)

    @router.post('/datasources/{datasource_id}/versions/cleanup')
    async def cleanup_versions(request: Request, datasource_id: str):
        def run(payload):
            _require_admin(request)
            keep = payload.get('keep', 3)
            return service.cleanup_versions(datasource_id, keep)

        return await _dispatch(request, run, with_body=True)

    @router.get('/datasources/{datasource_id}/publications')
    async def list_publications(request: Request, datasource_id: str):
        return await _dispatch(
            request, lambda: service.list_publications(datasource_id))

    # ------------------------------------------------------------------
    # 查询工作台：运行时查询 / 历史 / 反馈
    # ------------------------------------------------------------------
    @router.post('/datasources/{datasource_id}/query')
    async def run_query(request: Request, datasource_id: str):
        actor = current_user(request)

        def run(payload):
            return queries.run_query(datasource_id, payload, actor)

        return await _dispatch(request, run, with_body=True)

    @router.post('/datasources/{datasource_id}/query/stream')
    async def run_query_stream(request: Request, datasource_id: str):
        """查询的 SSE 版：``stage`` 帧上报阶段，``result`` 帧是完整响应体。

        与同步 ``/query`` 只差传输方式：语义、落库、响应字段完全一致。
        首字节前的失败（鉴权/请求体）仍是真实状态码 + problem+json；进入流式后
        的失败变成终态 ``event: error``（HTTP 已是 200，不能改状态）。
        """
        actor = current_user(request)
        lang = language(request)
        raw = await request.body()
        try:
            payload = responses.parse_json_body(raw, required=True)
        except ValueError as error:
            log.warning('text_to_sql api malformed body: %s', error)
            return responses.error(Text2SqlError('请求体格式不正确'), lang,
                                   request=request)

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(kind: str, data) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (kind, data))
            except RuntimeError:
                # 事件循环已关闭（客户端断开 + 进程收尾）：查询照常落库，事件丢弃。
                log.warning('text_to_sql query stream loop closed; drop %s', kind)

        def on_stage(stage: str, status: str,
                     ms: int | None = None) -> None:
            emit('stage', {'id': stage, 'status': status, 'ms': ms})

        def work():
            try:
                return 'result', queries.run_query(
                    datasource_id, payload, actor, on_stage=on_stage)
            except Text2SqlError as error:
                return 'error', _problem_payload(error, lang, request)
            except KbApiError as error:
                return 'error', _problem_payload(error, lang, request)
            except ValueError:
                return 'error', _problem_payload(
                    Text2SqlError('请求体格式不正确'), lang, request)
            except Exception:
                log.exception('text_to_sql query stream failed')
                return 'error', problem_body(
                    INTERNAL_ERROR, generic_detail(INTERNAL_ERROR, lang),
                    instance=request.url.path)
            finally:
                emit('_close', None)

        async def frames():
            task = asyncio.create_task(run_in_threadpool(work))
            try:
                while True:
                    kind, data = await queue.get()
                    if kind == '_close':
                        break
                    yield ServerSentEvent(
                        event=kind,
                        data=json.dumps(data, ensure_ascii=False, default=str))
                outcome, body = await task
                if outcome == 'result':
                    yield ServerSentEvent(
                        event='result',
                        data=json.dumps(body, ensure_ascii=False, default=str))
                    yield ServerSentEvent(event='done', data='{}')
                else:
                    yield ServerSentEvent(
                        event='error',
                        data=json.dumps(body, ensure_ascii=False, default=str))
            finally:
                if not task.done():
                    task.cancel()

        return EventSourceResponse(frames(), ping=15)

    @router.get('/runs')
    async def list_runs(request: Request):
        actor = current_user(request)
        params = request.query_params

        def run():
            page = _positive_int(params.get('page'), 1, 'page')
            size = _positive_int(params.get('size'), 20, 'size')
            status = params.get('status') or None
            if status and status.upper() not in {
                    'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'}:
                raise Text2SqlValidationError('status 取值不合法')
            return queries.list_runs(
                actor, datasource_id=params.get('datasourceId') or None,
                status=status, page=page, size=size)

        return await _dispatch(request, run)

    @router.delete('/runs')
    async def clear_runs(request: Request):
        actor = current_user(request)
        datasource_id = request.query_params.get('datasourceId') or None

        def run():
            queries.clear_runs(actor, datasource_id)
            return None

        return await _dispatch(request, run)

    @router.get('/runs/{run_id}')
    async def get_run(request: Request, run_id: str):
        actor = current_user(request)
        return await _dispatch(request, lambda: queries.get_run(run_id, actor))

    @router.delete('/runs/{run_id}')
    async def delete_run(request: Request, run_id: str):
        actor = current_user(request)

        def run():
            queries.delete_run(run_id, actor)
            return None

        return await _dispatch(request, run)

    @router.post('/runs/{run_id}/feedback')
    async def create_feedback(request: Request, run_id: str):
        actor = current_user(request)

        def run(payload):
            data = queries.create_feedback(run_id, payload, actor)
            return responses.created(data)

        return await _dispatch(request, run, with_body=True)

    @router.get('/feedback')
    async def list_feedback(request: Request):
        datasource_id = request.query_params.get('datasourceId')

        def run():
            if not datasource_id:
                raise Text2SqlValidationError('datasourceId 不能为空')
            return queries.list_feedback(datasource_id)

        return await _dispatch(request, run)

    # ------------------------------------------------------------------
    # 常用查询 / 用户草稿
    # ------------------------------------------------------------------
    @router.get('/favorites')
    async def list_favorites(request: Request):
        actor = current_user(request)
        return await _dispatch(request, lambda: queries.list_favorites(actor))

    @router.post('/favorites')
    async def create_favorite(request: Request):
        actor = current_user(request)

        def run(payload):
            data = queries.create_favorite(payload, actor)
            return responses.created(data)

        return await _dispatch(request, run, with_body=True)

    @router.patch('/favorites/{favorite_id}')
    async def update_favorite(request: Request, favorite_id: str):
        actor = current_user(request)

        def run(payload):
            return queries.update_favorite(favorite_id, payload, actor)

        return await _dispatch(request, run, with_body=True)

    @router.delete('/favorites/{favorite_id}')
    async def delete_favorite(request: Request, favorite_id: str):
        actor = current_user(request)

        def run():
            queries.delete_favorite(favorite_id, actor)
            return None

        return await _dispatch(request, run)

    @router.get('/workspace')
    async def get_workspace(request: Request):
        actor = current_user(request)
        return await _dispatch(request, lambda: queries.get_workspace(actor))

    @router.put('/workspace')
    async def save_workspace(request: Request):
        actor = current_user(request)

        def run(payload):
            return queries.save_workspace(payload, actor)

        return await _dispatch(request, run, with_body=True)

    return router


def _require_admin(request: Request) -> None:
    """审批类操作（关联核对、指标审核）只允许管理员（本地账号模式）。"""
    principal = getattr(request.state, 'auth_user', None)
    if principal is not None and getattr(principal, 'role', 'user') != 'admin':
        raise Text2SqlError('需要管理员权限', status=403,
                            problem_code='text2sql.forbidden')
