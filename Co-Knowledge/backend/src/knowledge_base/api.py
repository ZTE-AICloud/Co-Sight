"""Knowledge-base HTTP API: collection, metadata, directories, documents, chunks."""
from __future__ import annotations

import io

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from infrastructure.http import kb_responses as responses
from shared.errors.api import (KbApiError, KbStoreError, KbValidationError)
from infrastructure.http.identity import current_user, language
from shared.prefixes import RKB_PREFIX
from infrastructure.http.rkb_support import (dispatch, dispatch_sync, int_list,
                                              localize, org_id)
from knowledge_base.http_support import read_upload, search_dto

from knowledge_base.service import (chunk_service, directory_service, file_retry_service,
                                    file_service, kbase_service, kbase_v2_service,
                                    kbase_write_service)
from infrastructure.logging.logutil import log


KBASE_PREFIX = RKB_PREFIX

def add_chunk(kbase_id: str, payload: dict):
    document_id = payload.get('documentId')
    if not document_id:
        raise KbValidationError('RetCode.illegalArgument')
    return chunk_service.add_chunk(kbase_id, document_id, payload)


def lookup_directory_detail(kbase_id: str, directory_id: str, localize_error) -> dict:
    from knowledge_base.service.kbase_service import get_kbase_for_aspect
    from knowledge_base.repository import directory as directory_store

    get_kbase_for_aspect(kbase_id)
    row = directory_store.get_directory(directory_id, kbase_id)
    if row is None:
        return directory_service._base_vo({})
    return directory_service.assemble([row], localize_error)[0]


def build_router() -> APIRouter:
    router = APIRouter()

    # 知识库集合
    #
    # `GET` 用查询参数做筛选、分页、排序，不把只读操作伪装成 POST。
    # `POST` 同时承担文档库与图谱库建库，
    # 用 `?type=graph` 区分（两条建库链的副作用不同，不能只靠 body 猜）。
    # ------------------------------------------------------------------

    @router.get('/knowledge-bases')
    async def list_kbases(request: Request):
        query = request.query_params
        return await dispatch(
            request,
            lambda _payload: kbase_service.search_kbases(
                search_dto(query), org_id(request), language(request)))

    @router.get('/knowledge-bases/stats')
    async def kbase_stats(request: Request):
        # ⚠️ 必须注册在 `/knowledge-bases/{kbase_id}` **之前**：FastAPI 按注册顺序匹配，
        # 排在详情端点后面时 `stats` 会被当成 kbase_id，前端拿到一条 0005/详情错误。
        query = request.query_params
        return await dispatch(
            request,
            lambda _payload: kbase_service.get_kbase_stats(
                {'categories': int_list(query.get('categories'))}, org_id(request)))

    @router.post('/knowledge-bases')
    async def create_kbase(request: Request, kind: str = Query('document', alias='type')):
        normalized = (kind or 'document').strip().lower()
        is_graph = normalized in ('graph', 'knowledge_graph', 'knowledge-graph', '10')
        service = kbase_v2_service if is_graph else kbase_write_service
        return await dispatch(
            request,
            lambda payload: service.create_kbase(
                payload, current_user(request), org_id(request), language(request)),
            with_body=True, body_required=True, ok_status=201,
            location=lambda result: (
                f'{KBASE_PREFIX}/knowledge-bases/{result.get("id")}'
                if isinstance(result, dict) and result.get('id') else None),
        )

    # ------------------------------------------------------------------
    # 单个知识库
    #
    # 图谱库详情 `GET /{id}/graph` 返回 `{schemaInfo, data, fileInfo}` 复合体，
    # 与文档库的 `GET /{id}` 形状不同，保留为子资源而不是硬塞进同一个 VO。
    # 删除前置的「是否为空」不再单开端点：列表行自带 `currentFileCount`，
    # DELETE 自身也会以 0005 拒绝非空库。
    # ------------------------------------------------------------------

    @router.get('/knowledge-bases/{kbase_id}/graph')
    async def kbase_graph_detail(request: Request, kbase_id: str):
        return await dispatch(
            request, lambda _payload: kbase_v2_service.get_kbase_detail(kbase_id))

    @router.get('/knowledge-bases/{kbase_id}')
    async def kbase_detail(request: Request, kbase_id: str):
        return await dispatch(
            request, lambda _payload: kbase_service.get_kbase_detail(kbase_id))

    @router.patch('/knowledge-bases/{kbase_id}')
    async def update_kbase(request: Request, kbase_id: str):
        return await dispatch(
            request,
            lambda payload: kbase_v2_service.update_kbase(
                kbase_id, payload, org_id(request), current_user(request)),
            with_body=True, body_required=True,
        )

    @router.delete('/knowledge-bases/{kbase_id}')
    async def delete_kbase(request: Request, kbase_id: str):
        # 图谱库的删除会委托 v2；v2 的前置绑定检查需要真实用户，不能传空串。
        return await dispatch(
            request,
            lambda _payload: kbase_write_service.delete_kbase(
                kbase_id, current_user(request)),
            ok_status=204)

    # ------------------------------------------------------------------
    # 检索域
    #
    # 向量/关键词/混合检索可以跨多个知识库（`bases` 是列表），所以它是顶层操作，
    # 不嵌套在某个知识库下。图谱检索是同一族的另一种策略：
    # `POST /retrieval/graph`（在 app.py 注册，路径常量见 shared/prefixes.py）。
    # 编排问答是 `POST /query`（SSE，同样在 app.py 注册）。
    # ------------------------------------------------------------------
    return router


def build_content_router() -> APIRouter:
    router = APIRouter()

    @router.get('/knowledge-bases/{kbase_id}/directories')
    async def directory_descendants(request: Request, kbase_id: str,
                                    parentId: str | None = None, type: str | None = None,
                                    sort: bool = False):
        return await dispatch(request, lambda _payload: directory_service.list_descendants(
            kbase_id, parentId, type, sort, localize(request)))

    @router.post('/knowledge-bases/{kbase_id}/directories')
    async def create_directory(request: Request, kbase_id: str):
        # `parentId` 从 body 取。
        return await dispatch(
            request,
            lambda payload: directory_service.create_directory(
                kbase_id,
                payload.get('parentId'),
                payload.get('title'), current_user(request)),
            with_body=True, body_required=True, ok_status=201,
            location=lambda result: (
                f'{KBASE_PREFIX}/knowledge-bases/{kbase_id}/directories/'
                f'{result.get("id")}'
                if isinstance(result, dict) and result.get('id') else None),
        )

    @router.get('/knowledge-bases/{kbase_id}/directories/{directory_id}')
    async def directory_detail(request: Request, kbase_id: str, directory_id: str):
        return await dispatch(request, lambda _payload: lookup_directory_detail(
            kbase_id, directory_id, localize(request)))

    @router.patch('/knowledge-bases/{kbase_id}/directories/{directory_id}')
    async def update_directory(request: Request, kbase_id: str, directory_id: str):
        return await dispatch(
            request,
            lambda payload: directory_service.update_directory(
                kbase_id, directory_id, payload.get('title')),
            with_body=True, body_required=True)

    @router.delete('/knowledge-bases/{kbase_id}/directories/{directory_id}')
    async def delete_directory(request: Request, kbase_id: str, directory_id: str):
        # 删除目录时保留文档（移到 Default），不递归删除内容。
        return await dispatch(
            request,
            lambda _payload: directory_service.delete_directory_keep_files(
                kbase_id, directory_id, current_user(request)),
            ok_status=204)

    # ---- 文档（上传 / 分页 / 删除 / 下载 / 单文档切片）----

    @router.get('/knowledge-bases/{kbase_id}/documents')
    async def documents_page(request: Request, kbase_id: str,
                             keyword: str | None = None, page: int = 1, size: int = 50):
        return await dispatch(
            request,
            lambda _payload: directory_service.search_all_files_page(
                kbase_id, keyword, page, size, localize(request)),
        )

    @router.post('/knowledge-bases/{kbase_id}/documents')
    async def upload_document(request: Request, kbase_id: str,
                              files: list[UploadFile] = File(...),
                              metadata: str = Form('')):
        uploaded, meta = await read_upload(files, metadata)
        # 路径里的 kbase_id 是唯一事实来源：覆盖 metadata 里可能存在的同名键。
        meta = {**meta, 'kbaseId': kbase_id}
        return await run_in_threadpool(
            dispatch_sync, request, None,
            lambda _payload: file_service.upload_files(
                uploaded, meta, kbase_id, current_user(request)))

    @router.post('/knowledge-bases/{kbase_id}/documents/{document_id}/retry')
    async def retry_document(request: Request, kbase_id: str, document_id: str):
        """重新解析一篇失败文档（异步，202）。只允许 ``status = 2`` 的文档。"""
        return await dispatch(
            request,
            lambda _payload: file_retry_service.retry_file(
                kbase_id, document_id, current_user(request), org_id(request)),
            ok_status=202)

    @router.patch('/knowledge-bases/{kbase_id}/documents')
    async def move_documents(request: Request, kbase_id: str):
        # 0.1.7：批量移动到目标目录。只改 kb_directory 的 parent_id/parent_path，
        # 切片、关系、磁盘文件都不动。
        return await dispatch(
            request,
            lambda payload: {'moved': directory_service.move_files(
                kbase_id, payload.get('ids') or [], payload.get('parentId'),
                current_user(request))},
            with_body=True, body_required=True)

    @router.delete('/knowledge-bases/{kbase_id}/documents/{document_id}')
    async def delete_document(request: Request, kbase_id: str, document_id: str):
        return await dispatch(
            request, lambda _payload: file_service.delete_files(kbase_id, [document_id]),
            ok_status=204)

    @router.get('/knowledge-bases/{kbase_id}/documents/{document_id}/content')
    async def download_document(request: Request, kbase_id: str, document_id: str):
        """回上传的原文件流。"""
        try:
            content = await run_in_threadpool(
                file_service.doc_download_file, kbase_id, document_id)
        except KbApiError as kb_error:
            return responses.error(kb_error, language(request), request=request)
        except KbStoreError as store_error:
            log.error('document download store error [%s]: %s',
                      store_error.kind, store_error.detail)
            return responses.store_error(store_error, language(request), request=request)
        except Exception:
            log.exception('document download unexpected error')
            return responses.server_error(language(request), request=request)
        return StreamingResponse(io.BytesIO(content), media_type='application/octet-stream',
                                 headers={'Content-Length': str(len(content))})

    @router.get('/knowledge-bases/{kbase_id}/documents/{document_id}/chunks')
    async def document_chunks(request: Request, kbase_id: str, document_id: str,
                              keyword: str | None = None, page: int = 1, size: int = 10,
                              order: str | None = None):
        # ``order=asc``：文档预览要按原文顺序拼正文（切片表默认倒序）。
        # ``chunkIdAsc`` 是既有 DAO 里的同义开关，一并接受；不传时保持倒序，
        # 切片管理页的分页顺序不变。
        flag = (order or request.query_params.get('chunkIdAsc') or '').strip().lower()
        chunk_id_asc = flag in ('asc', 'ascending', '1', 'true', 'yes')
        return await dispatch(
            request, lambda _payload: chunk_service.search_chunk_from_file(
                kbase_id, document_id, keyword, page, size, chunk_id_asc))

    # ---- 切片 ----

    @router.get('/knowledge-bases/{kbase_id}/chunks')
    async def chunk_list(request: Request, kbase_id: str, keyword: str | None = None,
                         page: int = 1, size: int = 20):
        return await dispatch(
            request, lambda _payload: chunk_service.get_chunk_list(
                kbase_id, None, keyword, page, size))

    @router.post('/knowledge-bases/{kbase_id}/chunks')
    async def chunk_add(request: Request, kbase_id: str):
        """手工切片（评测导入链也走这条，见 `tools/rag-metrics/rkb_client.py`）。"""
        return await dispatch(
            request,
            lambda payload: add_chunk(kbase_id, payload),
            with_body=True, body_required=True, ok_status=201,
            location=f'{KBASE_PREFIX}/knowledge-bases/{kbase_id}/chunks')

    # ------------------------------------------------------------------
    # 算子域
    #
    # 静态子路径（types / template / available / supported）必须排在
    # `/{operator_id}` 之前 —— 否则 "types" 会被当成算子 id。
    # 发布状态是布尔属性，用 `POST/DELETE /{id}/publish`；
    # 可见性是布尔属性，用 `PUT /{id}/visibility`。
    # ------------------------------------------------------------------
    return router
