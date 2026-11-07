"""Retrieval endpoints: the REST entry point over the retrieval service."""
from __future__ import annotations

from fastapi import APIRouter, Request

from infrastructure.http.rkb_support import dispatch
from retrieval.service import retrieve_service


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post('/retrieval')
    async def retrieve(request: Request):
        # retrieve_service 自己保证「失败返回 []」；这里只管装信封
        return await dispatch(
            request, lambda payload: retrieve_service.retrieve(payload), with_body=True,
            body_required=True)


    # ------------------------------------------------------------------
    # 内容域：目录 / 文档 / 切片
    return router
