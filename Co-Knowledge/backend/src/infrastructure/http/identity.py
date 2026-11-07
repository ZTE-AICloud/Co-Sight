"""当前用户的解析（**不做鉴权**）。

明确不增加权限/鉴权校验。这里解析出来的用户只用于两件事：写入行上的
``created_by``/``user_name`` 一类字段，以及「我的知识库」这类按用户过滤的查询。

与 ``workflow/router.py`` 的 ``current_user`` **同一口径**：web 发 ``X-Emp-No``，
RKB 习惯用 ``username``，都没有时回落 ``AUTH_DEFAULT_USER``（默认 ``admin``）。
"""

from __future__ import annotations

import logging
import os

from fastapi import Request

log = logging.getLogger(__name__)

HEADER_EMP_NO = 'x-emp-no'
HEADER_USERNAME = 'username'
ENV_DEFAULT_USER = 'AUTH_DEFAULT_USER'
DEFAULT_USER = 'admin'

# ``SysGlobalConst``
HEADER_ORG_ID = 'x-org-id'
HEADER_LANGUAGE_OPTION = 'language-option'


def header_language(request: Request) -> str:
    """``HeaderHolder.get().getLanguage()`` —— **建库/建目录取默认文件夹名用的那个**。

    ⚠️ 三条与 ``language()``（文案语言）完全不同的规矩，实测过：

    * 读的是 ``language-option``，**不是** ``Accept-Language``；
    * ``X-Org-Id`` 缺席时**直接写死 ``"en-US"``** —— 于是「默认文件夹」会变成
      ``Default``（实测：只带 ``language-option: zh-CN`` 建出来的文件夹叫 Default）；
    * 头在但值为 ``None`` 时同理。

    别拿它去渲染错误文案 —— 那走 :func:`language`。
    """
    if not (request.headers.get(HEADER_ORG_ID) or '').strip():
        return 'en-US'
    return request.headers.get(HEADER_LANGUAGE_OPTION) or 'en-US'


def current_user(request: Request) -> str:
    """请求里的当前用户（只用于归属字段与按用户过滤）。

    ``AUTH_MODE=local`` 时**只认** ``AuthMiddleware`` 写进 ``request.state.auth_user``
    的会话身份；``X-Emp-No`` / ``username`` 是客户端可伪造的，绝不能在这里回落到
    它们。``none`` / ``gateway`` 保留历史口径（gateway 由前置网关剥离伪造头）。
    """
    principal = getattr(request.state, 'auth_user', None)
    if principal is not None:
        return principal.username

    # 不 import auth 域：infrastructure 是叶子层（架构检查会拦反向依赖）。
    # 启动期 `auth.service.validate_auth_mode()` 已拒绝未知取值；这里只做字符串判断。
    mode = (os.environ.get('AUTH_MODE') or 'local').strip().lower()

    if mode == 'local':
        # 走到这里说明路由没被中间件保护（白名单/新增的非 RKB 路径）。返回空串
        # 而不是 admin —— 宁可归属字段为空，也不要悄悄把操作记到别人头上。
        log.warning('current_user called without a local session: %s',
                    getattr(request, 'url', None))
        return ''

    user = request.headers.get(HEADER_EMP_NO) or request.headers.get(HEADER_USERNAME)
    if user and user.strip():
        return user.strip()
    return os.environ.get(ENV_DEFAULT_USER) or DEFAULT_USER


def language(request: Request) -> str:
    """请求语言。

    ⚠️ **读的是 ``Accept-Language``，不是 ``language-option``／``X-Lang-Id``。**

    文案语言只看 ``Accept-Language``；``language-option``／``X-Lang-Id`` 都不参与
    判定（后者在本服务里是死代码）。实际生效的就是请求头的主标签。

    实测（``GET /kbase/{不存在的id}``，看返回文案）：

    ==========================  ======
    ``Accept-Language``         文案
    ==========================  ======
    （不带）                     英文
    ``zh-CN``                   **中文**
    ``zh`` / ``zh-TW`` / ``de``  英文
    ``*``                       **中文**
    ``zh-CN,en;q=0.9``          **中文**
    ``en-US,zh-CN;q=0.9``       英文
    ==========================  ======

    不是「zh 开头就中文」：``zh``／``zh-TW`` 都是英文。根因是那几个 locale 都没有对应
    的 properties，而默认的回退策略 ``fallbackToSystemLocale=true`` ——
    回落的是**服务端默认 locale**（en_US），不是基础包 ``messages.properties``。
    只有 ``zh_CN`` 有专属包、以及 ``*``（解析出空语言，取基础包 = 中文）才落到中文。
    浏览器发的是 ``zh-CN,zh;q=0.9,...``，首要标签正是 ``zh-CN``，所以真实用户拿到中文。

    返回值**已经归一化**成 ``zh`` / ``en``（见 :func:`messages.normalize_language`）。
    这是一条要紧的约定：``Accept-Language: zh`` 与 ``Accept-Language: zh-CN`` 归一化后
    分别是 ``en`` 和 ``zh`` —— 所以调用方拿到的 ``zh`` **一定**是真中文，
    不用再猜自己手上的是原始标签还是归一化结果。

    ⚠️ 一个盲区：``*`` 也映成 ``zh``，但 ``*`` 请求取的是 base 包文案 —— 需要区分这一支
    的调用点（基础包缺席的键）另取 :func:`base_bundle`。
    """
    from shared.i18n.messages import normalize_language

    return normalize_language(_preferred_tag(request.headers.get('accept-language')))


def base_bundle(request: Request) -> bool:
    """当前请求是否落到**基础包**（``Accept-Language`` 的主标签恰好是 ``*``）。

    只给需要区分「base 包 / zh_CN 包」的调用点用：有一族键**基础包里没有**（只在
    zh_CN / en_US 里），``*`` 请求下取文案会在构造业务异常之前抛
    ``NoSuchMessageException``，归宿与 zh-CN 档不同 —— 而那族键是拿归一化后的
    ``zh`` 渲染的（:func:`language` 把 ``*`` 与 ``zh-CN`` 都映成 zh，
    **单靠它分不开这一支**）。逐键登记与各自的归宿见 ``messages.BASE_ABSENT_KEYS``。

    归一化结果（触发用的是回退删除那条饿汉式取文案的键）：
    ``*`` 与 ``*;q=0.9`` → base；``zh-CN`` / ``zh-CN,*;q=0.9``
    → zh_CN（q 值语义与 ``AcceptHeaderLocaleResolver`` 一致）；``en-US`` / ``zh`` /
    无头 → en_US。只有**胜出的**主标签是 ``*`` 才算 base。
    """
    return _preferred_tag(request.headers.get('accept-language')) == '*'


def _preferred_tag(header: str | None) -> str:
    """按 q 值取 ``Accept-Language`` 的主标签；同 q 时先出现者优先。

    ``*`` 原样返回 —— 交给 :func:`messages.normalize_language` 按「空语言 → 基础包」
    处理（实测是中文）。
    """
    if not header:
        return ''
    best_tag, best_quality = '', -1.0
    for part in header.split(','):
        pieces = part.split(';')
        tag = pieces[0].strip()
        quality = 1.0
        for param in pieces[1:]:
            name, _, value = param.partition('=')
            if name.strip().lower() == 'q':
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
        if quality <= 0 or not tag:
            continue
        if quality > best_quality:
            best_tag, best_quality = tag, quality
    return best_tag
