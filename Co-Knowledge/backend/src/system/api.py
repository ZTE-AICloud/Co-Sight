"""System/deployment endpoints: health and read-only capability information."""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from infrastructure.http.rkb_support import dispatch, path_long
from knowledge_base.service import file_service, kbase_service
from system import service as surviving_endpoints


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get('/health', response_class=PlainTextResponse)
    async def health():
        return 'ok'

    # ------------------------------------------------------------------
    # 系统域（只读的部署/能力信息）
    #
    # `/environment`、`/kbase/ais` 合并为 `/system/info`；
    # `/embedding/all`、`/zaetask/getLlmList`、`/workflow/app/model` 收敛为
    # `/system/embedding-models` 与 `/system/llm-models`；
    # `/system/rerank-models` 是画布重排模型下拉（注册表同源）；
    # 两条 `/file/size_limit[/{category}]` 合并为一条带 `category` 查询参数的端点。
    # ------------------------------------------------------------------

    @router.get('/system/info')
    async def system_info(request: Request):
        return await dispatch(request, lambda _payload: {
            'deployedBy': kbase_service.deployed_by(),
            'ais': kbase_service.is_ais_environment(os.environ.get('DEPLOY_PLAT_TYPE')),
        })

    @router.get('/system/embedding-models')
    async def embedding_models(request: Request):
        return await dispatch(request, lambda _payload: kbase_service.list_embedding_models())

    @router.get('/system/llm-models')
    async def llm_models(request: Request):
        return await dispatch(
            request, lambda _payload: surviving_endpoints.llm_list())

    @router.get('/system/rerank-models')
    async def rerank_models(request: Request):
        return await dispatch(
            request, lambda _payload: surviving_endpoints.rerank_list())

    @router.get('/system/file-size-limits')
    async def file_size_limits(request: Request, category: str = '1'):
        return await dispatch(
            request, lambda _payload: file_service.file_size_limit(path_long(category)))
    return router
