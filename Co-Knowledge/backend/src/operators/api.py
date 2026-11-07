"""Operator registry HTTP API: CRUD, templates, publishing and visibility."""
from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile

from shared.errors.api import KbApiError, KbValidationError
from infrastructure.http import kb_responses as responses
from infrastructure.http.identity import current_user, language
from shared.prefixes import RKB_PREFIX
from infrastructure.http.rkb_support import (dispatch, missing_param, org_id,
                                              path_long, stream_download)

from operators.service import operator_service


KBASE_PREFIX = RKB_PREFIX


def _require_admin(request: Request) -> None:
    """算子导入等同于在服务端执行代码，本地账号模式下只允许管理员。

    ``AUTH_MODE=gateway`` / ``none`` 没有本地会话（``request.state.auth_user`` 为空），
    此时由前置网关或部署边界负责；``local`` 模式下 ``role != 'admin'`` 一律拒绝。
    """
    principal = getattr(request.state, 'auth_user', None)
    if principal is not None and getattr(principal, 'role', 'user') != 'admin':
        raise KbApiError(None, status=403, problem_code='forbidden')


def operator_query(query) -> dict:
    return {
        'currentPage': int(query.get('page', 1)),
        'pageSize': int(query.get('size', 20)),
        'keyword': query.get('keyword') or '',
        'module': query.get('module') or '',
        'visibleRange': query.get('visibility'),
        'format': query.get('format'),
    }


def set_operator_visibility(operator_id: int, payload: dict, request: Request):
    public = payload.get('public')
    if not isinstance(public, bool):
        raise KbValidationError('RetCode.illegalArgument')
    target = (operator_service.VISIBLE_PUBLIC if public
              else operator_service.VISIBLE_PRIVATE)
    return operator_service.flip_public(operator_id, current_user(request), target)


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get('/operators')
    async def list_operators(request: Request):
        query = request.query_params
        return await dispatch(
            request,
            lambda _payload: operator_service.list_operators(
                operator_query(query), current_user(request), org_id(request)))

    @router.post('/operators')
    async def operator_import(request: Request, file: UploadFile = File(...)):
        _require_admin(request)
        # 先把整包读进内存再分发：``dispatch`` 是同步执行的，读文件是 await 的
        content = await file.read()
        filename = file.filename or ''
        return await dispatch(
            request,
            lambda _payload: operator_service.import_operator(
                filename, content, current_user(request), org_id(request),
                language(request)),
            ok_status=201,
            location=lambda result: (
                f'{KBASE_PREFIX}/operators/{result.get("id")}'
                if isinstance(result, dict) and result.get('id') else None))

    @router.get('/operators/types')
    async def operator_types():
        return responses.success(operator_service.operator_types())

    @router.get('/operators/template')
    async def operator_template_download(request: Request):
        operator_type = request.query_params.get('type') or request.query_params.get(
            'operatorType')
        if operator_type is None:
            return missing_param('type', request)
        return await stream_download(
            request, lambda: operator_service.operator_template_download(operator_type))

    @router.get('/operators/available')
    async def operator_available(request: Request):
        """按文件格式批量取「已发布算子 + 系统算子」（建库快速配置用）。"""
        module = request.query_params.get('module')
        if module is None:
            return missing_param('module', request)
        formats = request.query_params.getlist('format')
        if not formats:
            return missing_param('format', request)
        return await dispatch(
            request,
            lambda _payload: operator_service.support(
                {'module': module, 'formats': formats,
                 'keyword': request.query_params.get('keyword')},
                current_user(request), org_id(request)))

    @router.get('/operators/supported')
    async def operator_supported(request: Request):
        module = request.query_params.get('module')
        if module is None:
            return missing_param('module', request)
        return await dispatch(
            request,
            lambda _payload: operator_service.rag_workflow_supported(
                module, org_id(request)))

    @router.get('/operators/{operator_id}')
    async def operator_detail(request: Request, operator_id: str):
        return await dispatch(request, lambda _payload: operator_service.get_operator(
            path_long(operator_id)))

    @router.delete('/operators/{operator_id}')
    async def operator_delete(request: Request, operator_id: str):
        return await dispatch(request, lambda _payload: operator_service.delete_operator(
            path_long(operator_id), org_id(request)), ok_status=204)

    @router.post('/operators/{operator_id}/publish')
    async def operator_publish(request: Request, operator_id: str):
        return await dispatch(request, lambda _payload: operator_service.flip_publish(
            path_long(operator_id), current_user(request), operator_service.PUBLISH),
            ok_status=204)

    @router.delete('/operators/{operator_id}/publish')
    async def operator_un_publish(request: Request, operator_id: str):
        return await dispatch(request, lambda _payload: operator_service.flip_publish(
            path_long(operator_id), current_user(request), operator_service.UN_PUBLISH),
            ok_status=204)

    @router.put('/operators/{operator_id}/visibility')
    async def operator_visibility(request: Request, operator_id: str):
        # 路径变量先于请求体绑定。
        numeric_id = path_long(operator_id)
        return await dispatch(
            request,
            lambda payload: set_operator_visibility(numeric_id, payload, request),
            with_body=True, body_required=True, ok_status=204)

    @router.get('/operators/{operator_id}/export')
    async def operator_export(request: Request, operator_id: str):
        return await stream_download(
            request, lambda: operator_service.export_operator(
                path_long(operator_id), org_id(request)))

    # ------------------------------------------------------------------
    return router
