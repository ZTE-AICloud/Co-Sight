"""Knowledge-base request helpers: multipart files and list query parsing."""

from __future__ import annotations

import json

from fastapi import UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile

from shared.errors.api import KbMalformedRequestError
from knowledge_base.service import file_service
from infrastructure.http.rkb_support import int_list, order_list


def search_dto(query) -> dict:
    """``GET /knowledge-bases`` query parameters -> the ``KbaseQueryDTO`` shape."""
    return {
        'currentPage': int(query.get('page', 1)),
        'pageSize': int(query.get('size', 10)),
        'keyword': query.get('keyword') or '',
        'categories': int_list(query.get('categories')),
        'embeddingModel': query.get('embeddingModel'),
        'orderList': order_list(query.getlist('sort')),
    }


async def form_text(form, name: str):
    """Read one form field as text; missing -> ``None`` (distinct from empty)."""
    if name not in form:
        return None
    value = form.get(name)
    if isinstance(value, str):
        return value
    return (await value.read()).decode('utf-8')


async def form_files(form, name: str):
    """Read one form field as a list of uploaded files; missing -> ``None``."""
    if name not in form:
        return None
    items = form.getlist(name)
    # Starlette's UploadFile is the concrete type returned by form(); FastAPI's
    # is a subclass, so isinstance against FastAPI's class filters everything out.
    return [file_service.UploadedFile(item.filename or '', await item.read())
            for item in items if isinstance(item, StarletteUploadFile)]


async def read_upload(files: list[UploadFile], metadata: str | None):
    """Read FastAPI uploads into memory and decode the metadata JSON."""
    from knowledge_base.service.file_service import UploadedFile

    uploaded = [UploadedFile(item.filename or '', await item.read()) for item in files]
    if metadata is None or not metadata.strip():
        return uploaded, {}
    try:
        parsed = json.loads(metadata)
    except ValueError as error:
        raise KbMalformedRequestError() from error
    if not isinstance(parsed, dict):
        raise KbMalformedRequestError()
    return uploaded, parsed
