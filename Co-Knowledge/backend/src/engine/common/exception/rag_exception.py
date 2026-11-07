from typing import Any, Tuple


class RagException(Exception):
    """业务异常：错误码 + i18n tag + 占位参数（app.py 据此映射成 `{code, message}` JSON）。

    逻辑与错误码取值是对外契约，不要改动。
    """

    def __init__(self, error_code: int, error_tag: str, *args: Any):
        """
        :param error_code: -1 -> pre_retrieve failed; -2 -> retrieve failed; -3 -> post_retrieve failed; -4 -> response synthesizer
        :param error_tag: i18n tag
        :param args: place-holder arguments
        """
        self.error_code = error_code
        self.error_tag = error_tag
        self.args = args

    def get_error_code(self) -> int:
        return self.error_code

    def get_error_tag(self) -> str:
        return self.error_tag

    def get_args(self) -> Tuple[Any, ...]:
        return self.args
