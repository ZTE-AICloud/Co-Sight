"""请求体 ``Content-Type`` 的判定表 —— 媒体类型行为做成纯函数。

**为什么需要**：请求体在**媒体类型层面**就会失败，而本服务的
两层（FastAPI 参数校验的 422→0004、``ContentTypeValidationMiddleware`` 的 415 裸 JSON）
给出的都是另一种形态，甚至直接照常解析。本模块只回答「这组
（Content-Type, 请求体）落到哪个归宿」；抛异常、装信封由调用方负责
（``kb_api/router.py`` 与 ``flow_api/router.py`` 的 ``_enforce_body_content_type``）。

**判定表**（kb 4 个 JSON 端点 × 45 例 + 补充探测，flow 侧 3 个端点复核）::

    Content-Type                        请求体             归宿
    ------------------------------------------------------------------------------
    缺失 / 空串 / 不含 '/' 等解析不出     非空              0005 + msg=null
    缺失 / 空串 / 不含 '/' 等解析不出     0 字节            必填体判定接管
                                                          （缺 → 0004）
    application/json（大小写/参数任意）   任意              正常解析
    application/*+json（如 merge-patch）  任意              正常解析
    其它可解析类型（text/plain、         任意（含 0 字节） 0005 + msg=null
    text/json、application/xml、
    octet-stream、image/png…，含 text/json）
    application/x-www-form-urlencoded    0 字节 / 可解码   0005 + msg=null
    application/x-www-form-urlencoded    非空且读体炸*     0001
    multipart/*（带 boundary 参数）       任意              0005 + msg=null
    multipart/*（缺 boundary 参数）       任意（含 0 字节） 0001

    * 读体炸（→ 0001）的两个触发点：% 转义不完整（``%zz`` / ``%E4%B``），
      或转义还原后的字节按 charset 严格解不出（GBK 字节、孤立 ``\\x80``、``%E4%B8``）。

**0 字节体为什么不一律 0005**：CT 缺失时连媒体类型都没有，直接走
必填体判定（``/operator`` 无 CT + 0 字节 → 0004 missing；
``/retrieve`` 必填体同款）；而 CT **在**（哪怕是 text/plain）时媒体类型判定先行，
0 字节也照样 0005（``text/plain`` + 0 字节 → 0005）。所以 ``classify`` 返回
``None`` 是「放行」，由调用方随后照常走 ``parse_json_body``。

**已知未测绘角落**（不在本闸门内，别拿它当保证）：JSON 族带 ``charset=`` 参数时
按该 charset 解码请求体，本服务固定 UTF-8；``multipart/*`` 的非 form-data 子类型。
"""

from __future__ import annotations

import codecs
from typing import Dict, Optional

# ``classify`` 的两种「不放行」结论；``None`` 表示放行
UNSUPPORTED = 'unsupported'   # 200 + 0005，msg=null（RetCode.BusinessError）
BAD_FORM = 'bad-form'         # 200 + 0001（RetCode.ServerError，读体阶段抛异常）

_FORM_MEDIA_TYPE = 'application/x-www-form-urlencoded'
_MULTIPART_PREFIX = 'multipart/'
_JSON_SUFFIX = '+json'
_HEX_DIGITS = b'0123456789abcdefABCDEF'


def media_type_of(content_type_header: Optional[str]) -> Optional[str]:
    """媒体类型本体（小写、去参数）；**解析不出来**（缺席 / 空串 / 不含 ``/``）→ ``None``。

    ``'application/json, text/plain'`` 这种逗号列表不含 ``;``，会整体返回（不是
    JSON 族）—— 实测该形态 → 0005。
    """
    if not content_type_header:
        return None
    base = content_type_header.split(';', 1)[0].strip().lower()
    if not base or '/' not in base:
        return None
    return base


def is_multipart(content_type_header: Optional[str]) -> bool:
    """是否 multipart 族（不含 boundary 判定）—— multipart 端点用来挡「非 multipart」调用。"""
    media_type = media_type_of(content_type_header)
    return bool(media_type) and media_type.startswith(_MULTIPART_PREFIX)


def classify(content_type_header: Optional[str], raw: bytes) -> Optional[str]:
    """判定一组（Content-Type, 请求体）的归宿：``None`` / ``UNSUPPORTED`` / ``BAD_FORM``。"""
    media_type = media_type_of(content_type_header)
    if media_type is None:
        # 解析不出媒体类型：非空体 → 0005；0 字节 → 交给必填体判定
        return UNSUPPORTED if raw else None
    if _is_json_family(media_type):
        return None
    if media_type == _FORM_MEDIA_TYPE:
        if raw and not _form_body_readable(raw, _charset_of(content_type_header)):
            return BAD_FORM
        return UNSUPPORTED
    if media_type.startswith(_MULTIPART_PREFIX):
        # 带 boundary → 容器能「解析」（即使体是垃圾/空）→ 媒体类型不支持 → 0005；
        # 缺 boundary → Servlet 多部件解析当场炸 → 0001（0 字节与 ``{}`` 两态都是 0001）
        return UNSUPPORTED if 'boundary' in _params_of(content_type_header) else BAD_FORM
    return UNSUPPORTED


def _is_json_family(media_type: str) -> bool:
    """两种可读的 JSON 媒体类型：``application/json`` 与 ``application/*+json``。

    注意 ``text/json`` **不**在内（实测 0005）—— 别凭名字想当然。
    """
    return (media_type == 'application/json'
            or (media_type.startswith('application/') and media_type.endswith(_JSON_SUFFIX)))


def _params_of(content_type_header: str) -> Dict[str, str]:
    """Content-Type 的参数表（``boundary`` / ``charset``…），键小写、值去引号。"""
    params: Dict[str, str] = {}
    for part in content_type_header.split(';')[1:]:
        name, separator, value = part.partition('=')
        if not separator:
            continue
        params[name.strip().lower()] = value.strip().strip('"\'')
    return params


def _charset_of(content_type_header: str) -> str:
    """form 读体用的 charset：取参数，缺省 UTF-8；未知编码回落 UTF-8。"""
    charset = _params_of(content_type_header).get('charset') or 'utf-8'
    try:
        codecs.lookup(charset)
    except LookupError:
        return 'utf-8'
    return charset


def _form_body_readable(raw: bytes, charset: str) -> bool:
    """form-urlencoded 读体的两个可能失败点（都 → 0001）。

    ① 百分号转义必须完整合法；② 转义还原后的字节须能按 charset **严格**解码。
    纯 ASCII 控制字节与 UTF-8 中文都能解出来 —— 那时继续走 0005。
    """
    decoded = bytearray()
    index = 0
    length = len(raw)
    while index < length:
        byte = raw[index]
        if byte != 0x25:                      # '%'
            decoded.append(byte)
            index += 1
            continue
        if index + 3 > length:                # 尾巴上半个转义（如 "%E4%B"）
            return False
        if raw[index + 1] not in _HEX_DIGITS or raw[index + 2] not in _HEX_DIGITS:
            return False
        decoded.append(int(raw[index + 1:index + 3], 16))
        index += 3
    try:
        bytes(decoded).decode(charset, errors='strict')
    except (UnicodeDecodeError, LookupError):
        return False
    return True
