"""算子代码的 AST 危险调用扫描（防御纵深，不是安全边界）。

这些用例钉住常见的「不经过 os.system/subprocess」的逃逸写法。真正的隔离
（独立容器/namespace/非 root）仍由部署层负责；导入算子本身只允许管理员。
"""

import pytest

from ingestion.service.operator.dangerous_function_visitor import scan_file_with_ast


@pytest.mark.parametrize('source', [
    'import os\nos.execv("/bin/sh", ["sh"])\n',
    'import os\nos.fork()\n',
    'import ctypes\nctypes.CDLL(None).system("id")\n',
    'from os import fork\nfork()\n',
    'import importlib\nimportlib.import_module("os")\n',
])
def test_common_escape_hatches_are_flagged(source, tmp_path):
    script = tmp_path / 'operator.py'
    script.write_text(source, encoding='utf-8')

    assert scan_file_with_ast(str(script))


def test_benign_operator_has_no_issues(tmp_path):
    script = tmp_path / 'operator.py'
    script.write_text(
        'def run(text, **kwargs):\n'
        '    return [{"text": line} for line in text.splitlines()]\n',
        encoding='utf-8',
    )

    assert scan_file_with_ast(str(script)) == []
