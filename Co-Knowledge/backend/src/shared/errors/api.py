"""kb_api 的异常类型。

与 ``workflow.errors`` **同构但不复用**：异常只带文案键与参数，翻译发生在最外层
（那里才知道请求语言）。两边共用 ``shared.problem`` 的 key→状态码/机器码
映射，不再各自维护一套数字码；异常类仍分家，避免把两个接口族的路由生命周期绑在一起。
"""

from __future__ import annotations

from typing import Optional

from shared.problem import ApiError

# RetCode 码表（**过渡期兜底**）。对外契约是
# 真实 HTTP 状态码 + RFC 9457 problem+json；这些数字码只在错误对象内部用于
# 「旧行为兜底」，不再出现在响应里。新代码应优先传 ``status`` + ``problem_code``。
CODE_SUCCESS = '0000'
CODE_SERVER_ERROR = '0001'
CODE_VALIDATION_ERROR = '0004'
CODE_BUSINESS_ERROR = '0005'


class KbApiError(ApiError):
    """业务错误：文案键 + 参数，由最外层按语言渲染并映射成 problem 响应。

    :param key: ``messages.py`` 里的文案键（如 ``kbase.not.exist``）。
                传 ``None`` 表示没有文案，由 problem 层按状态码补通用 detail。
    :param args: 文案里的 ``{0}``、``{1}`` 占位参数
    :param code: 旧数字码（默认 0005），仅作映射兜底
    :param status: 新契约的 HTTP 状态码（优先于数字码映射）
    :param problem_code: 新契约的稳定机器码（如 ``knowledge_base_not_found``）
    """

    default_status = 400
    default_problem_code = 'bad_request'

    def __init__(self, key: Optional[str], *args, code: str = CODE_BUSINESS_ERROR,
                 status: Optional[int] = None,
                 problem_code: Optional[str] = None):
        super().__init__(key, *args, code=code, status=status,
                         problem_code=problem_code)

    def render(self, language: str) -> Optional[str]:
        if self.key is None:
            return None
        # 延迟 import：messages 是纯数据模块，这里只是避免循环引用的习惯写法
        from shared.i18n.messages import render

        return render(self.key, language, *self.args)


class KbValidationError(KbApiError):
    """入参校验失败 → 422 ``validation_failed``。"""

    default_status = 422
    default_problem_code = 'validation_failed'

    def __init__(self, key: str, *args):
        super().__init__(key, *args, code=CODE_VALIDATION_ERROR,
                         status=422, problem_code='validation_failed')


class KbMalformedRequestError(KbApiError):
    """请求体/查询参数无法绑定 → 400 ``malformed_request``。"""

    def __init__(self, key: Optional[str] = None, *args):
        super().__init__(key, *args, code=CODE_VALIDATION_ERROR,
                         status=400, problem_code='malformed_request')


class KbMediaTypeError(KbApiError):
    """请求媒体类型不受支持 → 415 ``unsupported_media_type``。"""

    def __init__(self, key: Optional[str] = None, *args):
        super().__init__(key, *args, code=CODE_BUSINESS_ERROR,
                         status=415, problem_code='unsupported_media_type')


class KbNotFoundError(KbApiError):
    """资源不存在 → 404。"""

    def __init__(self, key: Optional[str] = None, *args,
                 problem_code: str = 'not_found'):
        super().__init__(key, *args, code=CODE_BUSINESS_ERROR,
                         status=404, problem_code=problem_code)


class KbConflictError(KbApiError):
    """状态冲突 → 409。"""

    def __init__(self, key: Optional[str] = None, *args,
                 problem_code: str = 'conflict'):
        super().__init__(key, *args, code=CODE_BUSINESS_ERROR,
                         status=409, problem_code=problem_code)


class KbPermissionError(KbApiError):
    """无权限 → 403。"""

    def __init__(self, key: Optional[str] = None, *args):
        super().__init__(key, *args, code=CODE_BUSINESS_ERROR,
                         status=403, problem_code='permission_denied')


class KbLiteralError(KbApiError):
    """文案是**一句字面量**，不查 i18n 表；默认按 422 校验错误处理。

    字面量与请求语言无关（抛出前已拼好），所以 ``render`` 原样返回。
    业务含义不是「校验」的调用点（不存在/冲突/超限/上游失败）必须显式传
    ``status`` + ``problem_code``，或使用上面的便捷类。
    """

    default_status = 422
    default_problem_code = 'validation_failed'

    def __init__(self, message: str, code: str = CODE_BUSINESS_ERROR,
                 status: Optional[int] = None,
                 problem_code: Optional[str] = None):
        super().__init__(None, code=code, status=status, problem_code=problem_code)
        self.message = message

    def render(self, language: str) -> Optional[str]:
        return self.message

    def literal_message(self) -> Optional[str]:
        return self.message


class KbValidatorError(KbValidationError):
    """参数校验的**默认** message（上下界/必填没写 message）。

    与 :class:`KbValidationError` 只差渲染器：这些文案由校验器的
    插值器渲染，**没有 MessageFormat 的数字分组**（``最大不能超过10000``，
    不是 ``10,000``）。见 ``messages.render_validator``。
    """

    def render(self, language: str) -> Optional[str]:
        if self.key is None:
            return None
        from shared.i18n.messages import render_validator

        return render_validator(self.key, language, *self.args)


class KbWrappedValidatorError(KbApiError):
    """**包装型**校验错误：把每个 violation 各自的渲染结果排序、用 ``";"`` 拼接，再套外层模板。

    两处写法相同（:37-39 与 :52-54）::

        violations.stream().map(ConstraintViolation::getMessage).sorted()
                  .collect(joining(";"))
        → getMessageWithArgs("RetCode.upload.json.incorrect", new String[]{violationMsg})

    ⚠️ 排序发生在**本地化之后**（map(getMessage) 先出当前语言的文案，sorted 再排）
    —— 所以不能把「哪个在前」写死在调用点，必须在知道语言之后、逐条渲染完再排。
    本项目里两种语言的次序恰好一致（``OperatorParams list cannot be empty`` 在两个
    语言下都排在 ``must not be null`` / ``不能为null`` 前面），但这是**巧合**，
    按步骤实现才不会被下一条文案咬到。

    :param key: 外层模板键（上传域是 ``RetCode.upload.json.incorrect``）
    :param violations: 内层异常列表（``KbValidatorError`` / ``KbLiteralError`` 之类，
                       渲染后才拼接；它们自己不能是 :class:`KbWrappedValidatorError`）
    """

    default_status = 422
    default_problem_code = 'validation_failed'

    def __init__(self, key: str, violations: list):
        super().__init__(key, status=422, problem_code='validation_failed')
        self.violations = list(violations)

    def render(self, language: str) -> Optional[str]:
        from shared.i18n.messages import render

        # 先逐条渲染成当前语言，再排序拼接（顺序必须如此）
        inner = ';'.join(sorted(item.render(language) for item in self.violations))
        return render(self.key, language, inner)


class KbLiteralValidationError(KbLiteralError):
    """**校验类**的字面量文案（DTO/@Size 那一类）→ 默认 422。

    请求体缺失/畸形属于**绑定失败**，调用点传 ``status=400`` +
    ``problem_code='malformed_request'``（见 ``parse_json_body``）。
    """

    def __init__(self, message: str, status: Optional[int] = None,
                 problem_code: Optional[str] = None):
        super().__init__(message, code=CODE_VALIDATION_ERROR, status=status,
                         problem_code=problem_code)


class KbServerError(Exception):
    """服务端错误（对应 0001 / ``RetCode.ServerError``）。

    用在「本该由兜底处理器吞成 0001」的地方。与其在 Python
    里故意制造一个 TypeError（行为对但读不懂），不如显式抛这个 —— 调用点能一眼看出
    对应哪种失败模式。
    """


class KbStoreError(Exception):
    """存储层错误。

    :param kind: ``'duplicate'``（唯一键冲突）/ ``'not_found'`` / ``'db_error'``
    :param detail: 原始错误信息（只进日志与服务器错误文案，不直接回给用户）

    设计红线与 flow_api 相同：存储层**不吞异常**。RKB 既有的 ``exec_ddl`` 出错只打一条
    warn 就返回，用它做写入会把「表不存在」「唯一键冲突」都变成静默失败。
    """

    DUPLICATE = 'duplicate'
    NOT_FOUND = 'not_found'
    DB_ERROR = 'db_error'

    def __init__(self, kind: str, detail: str, message: str = None):
        super().__init__(message or detail)
        self.kind = kind
        self.detail = detail
        self.message = message or detail
