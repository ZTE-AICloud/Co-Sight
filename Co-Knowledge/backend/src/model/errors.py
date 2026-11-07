"""模型管理接口的异常类型。

**复用 kb_api 的码表与信封，但不复用它的文案表**：

* 码值（``0000/0001/0004/0005``）与信封形状（``{code:{code,msg,msgId},bo,other}``）
  是**对外契约的一部分**，前端 ``frontend/src/api/base.js`` 就按它解包 —— 必须一致，
  所以 :class:`ModelApiError` 直接继承 ``shared.errors.api.KbApiError``，
  这样 ``infrastructure/http/kb_responses.py`` 的 ``error()`` 与路由里的异常阶梯都能原样复用。
* 文案渲染被**覆写**成走本模块的 ``messages.py``（朴素的 ``{0}`` 替换），
  不继承 ``MessageFormat`` 的引号/千分位副作用 —— 本接口没有对端契约，
  不需要兼容那些副作用。
"""

from __future__ import annotations

from typing import Optional

from shared.errors.api import (CODE_BUSINESS_ERROR, CODE_VALIDATION_ERROR,
                                  KbApiError)
from model import messages

__all__ = ['CODE_BUSINESS_ERROR', 'CODE_VALIDATION_ERROR', 'ModelApiError',
           'ModelBusinessError', 'ModelValidationError']


class ModelApiError(KbApiError):
    """模型管理的业务错误（默认 0005）。文案键来自 ``model_api/messages.py``。"""

    def render(self, language: str) -> Optional[str]:
        if self.key is None:
            return None
        return messages.render(self.key, language, *self.args)


class ModelValidationError(ModelApiError):
    """入参校验失败 → 422 ``validation_failed``。"""

    default_status = 422
    default_problem_code = 'validation_failed'

    def __init__(self, key: str, *args):
        super().__init__(key, *args, code=CODE_VALIDATION_ERROR,
                         status=422, problem_code='validation_failed')


class ModelBusinessError(ModelApiError):
    """业务拒绝 → 按文案键映射（模型不存在 404、重名/占用 409，其余 400）。"""

    def __init__(self, key: Optional[str], *args):
        super().__init__(key, *args, code=CODE_BUSINESS_ERROR)
