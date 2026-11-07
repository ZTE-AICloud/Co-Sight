"""Shared HTTP plumbing for the RKB prefix.

Everything here is prefix-level policy rather than domain behaviour: request
dispatch, the problem+json exception ladder, multipart/file helpers, and the
query-parameter parsers shared by more than one domain API module.
"""
from __future__ import annotations

import io

from fastapi import Request
from fastapi.exception_handlers import (
    http_exception_handler as fastapi_http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared.prefixes import RKB_PREFIX
from infrastructure.http import content_type
from infrastructure.http import kb_responses as responses
from shared.errors.api import (KbApiError, KbMalformedRequestError,
                                  KbMediaTypeError, KbStoreError,
                                  KbValidationError)
from infrastructure.http.identity import language
from shared.problem import (MALFORMED_REQUEST, NOT_FOUND, VALIDATION_FAILED,
                            generic_detail, owns_problem_path, problem_response,
                            spec_for_status)
from infrastructure.logging.logutil import log

HEADER_ORG_ID = 'x-org-id'


def csv_query(request: Request, name: str) -> list[str]:
    """读取 ``?ids=a,b`` 与 ``?ids=a&ids=b`` 两种形态。"""
    items: list[str] = []
    for value in request.query_params.getlist(name):
        items.extend(part.strip() for part in value.split(',') if part.strip())
    return items


def int_list(raw: str | None) -> list[int] | None:
    values = [part.strip() for part in (raw or '').split(',') if part.strip()]
    return [int(value) for value in values] if values else None


def order_list(values: list[str]) -> list[dict]:
    """``sort=createdDate:desc`` → ``[{'key', 'ascending'}]``。"""
    orders = []
    for value in values:
        key, _, direction = value.partition(':')
        key = key.strip()
        if key:
            orders.append({'key': key, 'ascending': direction.strip().lower() != 'desc'})
    return orders


async def stream_download(request: Request, build):
    """下载类端点：内容与文件名由业务层给，出错时**回信封**而不是文件流。

    出错时（比如模板不存在）走的是异常处理器，
    也就是 HTTP 200 + 错误信封 —— 所以这里也不能回 404。

    异常阶梯与 :func:`dispatch_sync` 一致，**兜底必须是 Exception**：
    漏掉一类异常会让 FastAPI 回一个 ``text/plain`` 的 500，前端那边 blob 分支就炸了。

    ⚠️ 这是刻意行为：库里 ``operator_zip_path`` 指向的文件在磁盘上不存在时
    （有历史遗留的算子就是这个状态），**不能回空 body 的 200**
    （响应头已发出之后才抛，异常处理器够不着），否则前端拿到一个 0 字节的下载、
    没有任何提示。这里选择回**业务错误信封** ——
    同样是 200、同样走前端的 JSON 分支，但文案可读。

    该分支不能回 0001（「服务器内部错误，请稍后重试」）：缺文件
    是**永久性数据问题、重试无用**，通用文案反而误导；对同类「盘上文件缺失」统一改为
    **0005「文件(夹)不存在」**（抛点在 ``operator_service._stream_stored_zip``）。
    仅改 OSError 那一支；``operator_zip_path`` 为 NULL 仍是 0001，未动。
    """
    try:
        content, filename = await run_in_threadpool(build)
    except KbValidationError as validation_error:
        return responses.error(validation_error, language(request), request=request)
    except KbApiError as kb_error:
        return responses.error(kb_error, language(request), request=request)
    except KbStoreError as store_error:
        log.error('kb api store error [%s]: %s', store_error.kind, store_error.detail)
        return responses.store_error(store_error, language(request), request=request)
    except Exception:
        log.exception('kb api download failed')
        return responses.server_error(language(request), request=request)
    return StreamingResponse(
        io.BytesIO(content), media_type='application/octet-stream',
        headers={'Content-Disposition': 'form-data; name="attachment"; filename="%s"' % filename,
                 'Content-Length': str(len(content))})


def missing_param(name: str, request: Request):
    """必填 query 参数缺失。

    文案固定是 ``RetCode.illegalArgument``（**默认语言**，不随请求语言变）。
    这里必须自己判：FastAPI 的必填参数会先抛 422，那条响应根本不是 kb 信封。

    ⚠️ 上面那句「默认语言」在本仓当前部署下等于英文 —— 但绑定分支同样按
    请求 locale 取文案，而请求 locale 由 ``Accept-Language`` 决定
    （见 identity.language），所以最终还是随语言的。这里照走 ``language(request)``。
    """
    log.info('kb api missing required parameter: %s', name)
    return responses.error(KbMalformedRequestError('RetCode.illegalArgument'),
                           language(request), request=request)


def localize(request: Request):
    """文案本地化函数：``错误键 -> 文案``（找不到就用键名，便于排障）。"""
    from shared.i18n.messages import render

    lang = language(request)
    return lambda key: render(key, lang)


def not_found(request: Request):
    """未知路径 → 404 ``not_found`` problem（不再回 200 + 0005）。"""

    lang = language(request)
    return problem_response(NOT_FOUND, generic_detail(NOT_FOUND, lang),
                            instance=request.url.path)


async def validation_handler(request: Request, exc: RequestValidationError):
    """FastAPI 参数绑定/校验失败 → 400 或 422 problem+json。

    分类规则（按 ``loc`` 的第一段）：

    * ``query`` / ``path`` / ``header``：**绑定**失败（缺参、类型对不上）→ 400
      ``malformed_request``；
    * ``body``：字段语义校验 → 422 ``validation_failed``；
    * multipart 端点被非 multipart Content-Type 调用 → 400 ``malformed_request``
      （读体阶段解析失败）。

    **只接管 RKB 前缀**：``/mcp``、``/health`` 走各自的协议行为；
    ``/query``、``/retrieval/graph`` 与 ``/agent`` 和其余端点一样由这里出 422 problem。
    """
    if not owns_problem_path(request.url.path):
        return await request_validation_exception_handler(request, exc)

    lang = language(request)
    errors = exc.errors()
    log.info('kb api request validation failed: %s', errors[:3])

    if multipart_content_type_missing(request, exc) or multipart_without_files(request, exc):
        return problem_response(
            MALFORMED_REQUEST,
            generic_detail(MALFORMED_REQUEST, lang),
            instance=request.url.path,
        )

    locations = {tuple(error.get('loc') or ())[:1] for error in errors}
    binding_only = bool(locations) and locations <= {
        ('query',), ('path',), ('header',)}
    spec = MALFORMED_REQUEST if binding_only else VALIDATION_FAILED
    # 只保留定位信息，不把请求值/内部异常原文回给客户端
    details = [
        {
            'loc': list(error.get('loc') or []),
            'type': error.get('type'),
            'message': error.get('msg'),
        }
        for error in errors
    ]
    return problem_response(
        spec,
        generic_detail(spec, lang),
        instance=request.url.path,
        extensions={'errors': details},
    )


# 声明了 multipart 体部件（FastAPI 的 ``File(...)``/``Form(...)``）的端点 —— 这些端点
# 在「非 multipart 的 Content-Type」下，部件解析器
# 在参数绑定阶段就抛错 → 0001。不能落到 FastAPI 的 422→0004
# （或 text/plain 被中间件拦成 415）。
#
# ⚠️ 手工 ``request.form()`` 的两条**不在**集合里，各有各的处理：
# * ``/graph/extract`` —— 端点内显式挡非 multipart → 0001（那里没有 422 可拦）；
# * ``/graph/extract/{kb_id}`` —— 非 multipart 时先绑普通参数（data 等）→ 0004，
#   这是正确归宿，不需要任何改动。
MULTIPART_BODY_PATHS = frozenset(
    RKB_PREFIX + path
    for path in (
        '/operators',
        '/graph-schemas/import',
        '/graph-imports',
    ))


def is_multipart_body_path(path: str) -> bool:
    """``POST /knowledge-bases/{id}/documents`` 的路径段是动态的，单独判。"""
    if path in MULTIPART_BODY_PATHS:
        return True
    prefix = RKB_PREFIX + '/knowledge-bases/'
    return path.startswith(prefix) and path.endswith('/documents')


def multipart_without_files(request: Request, exc: RequestValidationError) -> bool:
    """multipart 请求但没有任何 ``files`` 部件 → 0001。

    ``python-multipart`` 新版本对「只有结束边界」的空 multipart 不再抛
    ``MultipartParseError``，FastAPI 于是报 ``body.files`` missing（422）。
    对上传端点来说这仍是**请求格式问题**，对外保持 400 ``malformed_request``。
    """
    if not is_multipart_body_path(request.url.path):
        return False
    if not content_type.is_multipart(request.headers.get('content-type')):
        return False
    errors = exc.errors()
    if not errors:
        return False
    return any(
        tuple(error.get('loc') or ())[:2] == ('body', 'files')
        and error.get('type') == 'missing'
        for error in errors
    )


def multipart_content_type_missing(request: Request, exc: RequestValidationError) -> bool:
    """multipart 端点被**非 multipart** Content-Type 调用 → 0001（读体阶段抛）。

    三个必要条件缺一不可：

    * 路径是 multipart 上传端点（见 :func:`is_multipart_body_path`）；
    * Content-Type 不是 multipart（缺席也算「不是」—— 无 CT 同样 0001）；
    * **错误全部落在 body**：只要还有一条 query/path 参数的绑定错误，就说明
      参数绑定先于部件解析炸了，此时不能抢答 0001。
    """
    if not is_multipart_body_path(request.url.path):
        return False
    if content_type.is_multipart(request.headers.get('content-type')):
        return False
    errors = exc.errors()
    if not errors:
        return False
    return all(tuple(error.get('loc') or ())[:1] == ('body',) for error in errors)


async def kb_error_handler(request: Request, exc: KbApiError):
    """兜住**逃出路由函数**的 ``KbApiError``（典型：``read_upload`` 的 metadata 解析错误）。

    正常路径上业务异常都在 ``dispatch_sync`` 的阶梯里转成 problem+json；但
    ``read_upload`` 在进分发器**之前**执行，抛出的 ``KbApiError`` 不经过那里 ——
    不挂这个处理器，Starlette 会把它当未处理异常回 500 ``text/plain``。

    非 RKB 前缀理论上到不了这里，真到了就原样重抛，保持「未注册处理器」的行为。
    """
    if not owns_problem_path(request.url.path):
        raise exc
    log.info('kb api error escaped route handler: key=%s code=%s', exc.key, exc.code)
    return responses.error(exc, language(request), request=request)


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """RKB 前缀下的 ``HTTPException`` → 对应状态码的 problem+json。

    典型来源是 multipart 解析失败（400）、方法不允许（405）与框架层的 404。
    保留原状态码，只把 body 换成 RFC 9457；协议端点（``/mcp``、``/health``）
    走各自的默认处理。
    """
    if owns_problem_path(request.url.path):
        lang = language(request)
        spec = spec_for_status(exc.status_code)
        log.info('kb api http exception %s -> problem %s', exc.status_code, spec.code)
        return problem_response(
            spec,
            generic_detail(spec, lang),
            instance=request.url.path,
        )
    return await fastapi_http_exception_handler(request, exc)


# ----------------------------------------------------------------------
# 请求分发
# ----------------------------------------------------------------------


def org_id(request: Request) -> str:
    return (request.headers.get(HEADER_ORG_ID) or '').strip()


async def dispatch(request: Request, fn, with_body: bool = False,
                    body_required: bool = False, ok_status: int = 200,
                    location=None):
    """统一的「解析 → 执行 → 构造纯 REST 响应」。

    业务执行放线程池（psycopg2 是阻塞的）；异常在这里翻译成 problem+json。

    ``ok_status``：成功状态码（创建 201 / 异步 202 / 删除 204）；``location`` 可以是
    字符串，也可以是 ``fn`` 返回值 → 相对路径的函数（创建后才知道新 id 的场景）。
    """

    raw = await request.body() if with_body else b''
    return await run_in_threadpool(
        dispatch_sync, request, raw, fn, body_required, with_body,
        ok_status, location)


def path_long(value: str) -> int:
    """``Long`` 路径变量：不是整数 → 400 ``malformed_request``。"""
    try:
        return int(value)
    except ValueError as error:
        raise KbMalformedRequestError('RetCode.illegalArgument') from error


def enforce_body_content_type(request: Request, raw: bytes) -> None:
    """JSON 体端点的 Content-Type 闸门 —— 按请求体的媒体类型判定。

    判定表与字节级依据见 ``infrastructure/http/content_type.py`` 模块头（实测得出）。
    抛出异常后由调用点的异常阶梯翻成两个归宿：

    * 媒体类型不合格（**含「没有 Content-Type + 非空体」**）
      → ``KbApiError(None)`` → 0005 + ``msg:null``。修复前这里会照常解析，回 0004/业务；
    * form-urlencoded 体解不出 / multipart 缺 boundary → 0001（读体阶段抛）。
      修复前是 0004、或被 ``ContentTypeValidationMiddleware`` 拦成 415。

    ⚠️ 只在**声明了 JSON 请求体**的端点调用（``dispatch(with_body=True)`` 与三个
    数组/导出端点）；GET 等无体端点带任何 Content-Type 都不参与判定
    （实测：GET /kbase 带 text/plain 两侧同为 0000），别扩大打击面。
    """
    verdict = content_type.classify(request.headers.get('content-type'), raw)
    if verdict == content_type.BAD_FORM:
        # 读体阶段解析失败（form 转义不完整 / multipart 缺 boundary）→ 400
        raise KbMalformedRequestError()
    if verdict is not None:
        # 媒体类型不受支持（含「无 Content-Type + 非空体」）→ 415
        raise KbMediaTypeError()


def dispatch_sync(request: Request, raw: bytes, fn, body_required: bool = False,
                   with_body: bool = False, ok_status: int = 200, location=None):
    """解析请求体 → 执行 → 构造纯 REST 响应。

    ``handler`` 的返回值决定成功响应：

    * Starlette ``Response``（下载/流式）→ 原样返回；
    * ``ok_status=204`` 或返回 ``None`` → 204 No Content；
    * ``ok_status=201`` → 201 + ``Location``（``location`` 可为字符串或函数）；
    * ``ok_status=202`` → 202；
    * 其余 → ``ok_status``（默认 200）+ JSON body 本身。
    """
    lang = language(request)
    try:
        if with_body:
            enforce_body_content_type(request, raw)
        payload = responses.parse_json_body(raw, required=body_required)
        result = fn(payload)
        if isinstance(result, Response):
            return result
        if ok_status == 204:
            return responses.no_content()
        if result is None:
            # 异步端点（导入/重抽）服务层正常返回 None：**仍是 202**，
            # 不能并进 204 —— 契约与 docs 都声明 202，客户端据此判断「已受理」。
            if ok_status == 202:
                return responses.accepted(None, location=location
                                          if isinstance(location, str) else None)
            return responses.no_content()
        loc = location(result) if callable(location) else location
        if ok_status == 201:
            return responses.created(result, location=loc)
        if ok_status == 202:
            return responses.accepted(result, location=loc)
        return responses.success(result, status_code=ok_status)
    except KbValidationError as validation_error:
        # 业务层已经给出具体文案（如 "Type must be 0 or 1"）就用它；
        # 只对「请求体本身畸形」这种没有具体键的情况回落到通用文案。
        log.warning('kb api validation error: %s', validation_error)
        return responses.error(validation_error, lang, request=request)
    except ValueError as error:
        # 请求体畸形 / 字段类型对不上 → 400 malformed_request。
        log.warning('kb api malformed request body: %s', error)
        return responses.error(KbMalformedRequestError('RetCode.illegalArgument'),
                               lang, request=request)
    except KbApiError as kb_error:
        return responses.error(kb_error, lang, request=request)
    except KbStoreError as store_error:
        # 存储层细节只进日志：它可能含表名/主机/连接串
        log.error('kb api store error [%s]: %s', store_error.kind, store_error.detail)
        return responses.store_error(store_error, lang, request=request)
    except Exception:
        log.exception('kb api unexpected error')
        return responses.server_error(lang, request=request)
