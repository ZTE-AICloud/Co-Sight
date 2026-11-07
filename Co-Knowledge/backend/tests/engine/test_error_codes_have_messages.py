"""代码里抛出的每个错误码，都必须有中英文案。

为什么需要这条守卫：`get_i18n_safe` 在查不到键时**不会炸**，而是返回
「内部错误，错误码缺失。」—— 于是用户看到一句无用的话，而日志/测试全绿。
恢复图谱检索时就踩到过：新加的 `request-knowledge-graph-failed`
没进 i18n，前端只能看到兜底文案。

所以这里直接从源码里把错误码抠出来，逐个对着 `i18n.rag_i18n.i18n` 验。
"""
import ast
import pathlib

import pytest


from engine.i18n import rag_i18n

# 编排运行时代码在 ``src/engine``（原 ``engine``）。
# 只扫 engine 的错误码；宿主知识库用的是另一套 i18n，不归这条哨兵管。
SRC = pathlib.Path(__file__).resolve().parents[2] / 'src' / 'engine'


def _raised_error_codes():
    """AST 扫本包，取出所有 `RagException(<code>, '<key>', ...)` 里的 key。

    用 AST 而不是 grep：docstring 与注释里经常引用错误码（「它会报 xxx」），
    那些不是真的抛出点，算进来只会产生假失败。
    """
    codes = set()
    for path in SRC.rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, 'attr', None)
            if name != 'RagException':
                continue
            # 第二个位置参数是错误码（第一个是 int 分类码）
            if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
                continue
            value = node.args[1].value
            if isinstance(value, str):
                codes.add(value)
    return codes


def test_src_actually_raises_some_errors():
    """反向哨兵：抠不出错误码说明 AST 取样逻辑失效了（比如 RagException 改了名字）。

    没有这条，下面的参数化用例会在「一个都没扫到」的情况下静默通过。
    """
    codes = _raised_error_codes()
    assert len(codes) > 10, f'只扫到 {len(codes)} 个错误码，AST 取样逻辑可能已失效'


@pytest.mark.parametrize('language', ['zh', 'en'])
def test_every_raised_error_code_has_a_message(language):
    missing = sorted(
        code for code in _raised_error_codes()
        if not rag_i18n.i18n.get(code, {}).get(language)
    )
    assert missing == [], (
        f'这些错误码在 {language} 文案表里缺失（或为空），'
        f'用户会看到「内部错误，错误码缺失」：{missing}')
