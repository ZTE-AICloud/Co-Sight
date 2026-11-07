"""flow_api 的异常类型。

分两层，因为它们的**消费方式**不同：

* :class:`FlowError` —— 业务层错误，带「文案键 + 参数」，由路由层按调用方前缀
  翻成对外信封（``code.code`` ∈ {0004 校验, 0005 业务, 0001 服务器}）或
  RKB 信封（``{code:-1, message}``）。**不携带已翻译文本**：同一份错误可能要用
  中/英两种语言渲染，翻译发生在最外层（那里才知道请求语言）。
* :class:`FlowStoreError` —— 存储层错误（表不存在、唯一键冲突、连接失败）。
  它不面向用户，由 service 捕获后转成合适的 :class:`FlowError`
  （唯一键冲突 → 「已存在」/「正在被发布」；其余 → 服务器错误，附原始信息供排查）。

设计红线：存储层**不吞异常**。RKB 既有的 ``exec_ddl`` 会在出错时只打一条 warn 就
返回，用它做删除会出现「删一半静默成功、留下孤儿数据」——本模块的 store 一律抛。
"""

from __future__ import annotations

from typing import Optional

from shared.problem import ApiError

# 旧数字码：仅作过渡期兜底，不再出现在响应里。
CODE_SUCCESS = '0000'
CODE_SERVER_ERROR = '0001'
CODE_VALIDATION_ERROR = '0004'
CODE_BUSINESS_ERROR = '0005'


class FlowError(ApiError):
    """业务错误：文案键 + 参数，由最外层按语言渲染并映射成 problem 响应。

    :param key: ``messages.py`` 里的文案键（如 ``workflow.not.exist``）。
    :param args: 文案里的 ``{0}``、``{1}`` 占位参数
    :param code: 旧数字码（默认 0005），仅作映射兜底
    :param status: 新契约 HTTP 状态码（优先于数字码映射）
    :param problem_code: 新契约稳定机器码
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
        from workflow.messages import render

        return render(self.key, language, *self.args)


class FlowValidationError(FlowError):
    """入参校验失败 → 422 ``validation_failed``。"""

    default_status = 422
    default_problem_code = 'validation_failed'

    def __init__(self, key: str, *args):
        super().__init__(key, *args, code=CODE_VALIDATION_ERROR,
                         status=422, problem_code='validation_failed')


class FlowMalformedRequestError(FlowError):
    """请求体/参数绑定失败 → 400 ``malformed_request``。"""

    def __init__(self, key: Optional[str] = None, *args):
        super().__init__(key, *args, code=CODE_VALIDATION_ERROR,
                         status=400, problem_code='malformed_request')


class FlowStoreError(Exception):
    """存储层错误。

    :param kind: ``'duplicate'``（唯一键冲突）/ ``'not_found'`` / ``'db_error'``
    :param detail: 原始错误信息（只进日志与服务器错误文案，不直接回给用户）
    """

    DUPLICATE = 'duplicate'
    NOT_FOUND = 'not_found'
    DB_ERROR = 'db_error'

    def __init__(self, kind: str, detail: str, message: str = None):
        super().__init__(message or detail)
        self.kind = kind
        self.detail = detail
        self.message = message or detail
