"""自定义算子包解析（明确不支持）。

自定义算子包这条链是断的：

  * 上传的是算子包（`.py` + `config.json`），runtime 期望的是解压后的目录
  * `resources/operator/template/rag_operator.zip` 里的 .py 是 **0 字节**

所以这里不装作能找到：**找不到就抛带包名的错误**，让「画布上选了一个跑不了的算子」
在第一次执行时就能看出原因，而不是静默用一个错的内置包去 import。

没有定义 `load_rag_operator` / `load_rag_operator_with_retry` / `delete_loaded_operator` /
`update_loaded_operator` / `get_operator_parse_cache`：它们全都是「扫描磁盘上的 tar 包
并解压」这一件事的分身，而这件事没有生产者（见 `plugins_change_listener` 的文件头）。
留着只会让 import 成功、调用时才发现是空的，所以干脆不定义 —— 谁要调，会在 import
期就发现。
"""
from engine.common.exception.rag_exception import RagException
from engine.config_loader.default_packages_info import operator_packages
from engine.config_loader.plugins_change_listener import start_plugins_listener  # 供 vendored 代码导入
from engine.logutil import logger

__all__ = ['find_package_in_custom_operator_cache', 'start_plugins_listener']


def find_package_in_custom_operator_cache(package: str, operator: str) -> str:
    builtin = operator_packages.get(operator)
    if builtin:
        return builtin
    logger.error('custom operator is not supported in this build: operator=%s package=%s', operator, package)
    raise RagException(-1, 'workflow-has-no-operator', operator)
