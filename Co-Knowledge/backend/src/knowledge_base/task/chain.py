"""handler 链：正序执行、失败时**逆序回滚**。

有一处细节容易写错：回滚从**刚失败的那个 handler 自己**开始
（游标停在它后面），所以回滚序列是 ``[i], [i-1], ..., [0]``，**含失败者**。

回滚里再抛异常只记日志、不往外传（原异常继续往上抛）：
回滚是「尽力而为」，不能让它把真正的错因顶掉。
"""

from __future__ import annotations

from typing import Protocol

from infrastructure.logging.logutil import log


class FileHandler(Protocol):
    """``FileHandler`` 接口：``handle`` + ``rollback``。"""

    def handle(self, file_handle: dict) -> None:
        ...

    def rollback(self, file_handle: dict) -> None:
        ...


class FileHandlerChain:
    """按加入顺序执行；任一步失败就**从它自己开始**倒着回滚。"""

    def __init__(self):
        self._handlers: list[FileHandler] = []

    def add_handler(self, handler: FileHandler) -> 'FileHandlerChain':
        self._handlers.append(handler)
        return self

    def execute(self, file_handle: dict) -> None:
        for index, handler in enumerate(self._handlers):
            try:
                handler.handle(file_handle)
            except Exception:
                log.error('%s handler failed, rolling back',
                          type(handler).__name__, exc_info=True)
                # 倒序回滚，**含当前这个失败的 handler**
                for rollback_handler in reversed(self._handlers[:index + 1]):
                    try:
                        rollback_handler.rollback(file_handle)
                    except Exception:
                        log.error('%s handler rollback error',
                                  type(rollback_handler).__name__, exc_info=True)
                raise
