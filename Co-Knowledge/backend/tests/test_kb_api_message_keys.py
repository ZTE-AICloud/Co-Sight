"""错误键必须都能落到文案（键名泄漏是最刺眼的一类回归）。

有三处调用点容易把 **i18n 键名**当文案发给用户
（``RetCode.operator.publish.repeat`` / ``RetCode.file.not.exist`` /
``RetCode.chunk.optimization.no.index.to.rollback``）—— ``render`` 查不到键时
会**回落成键名本身**，于是前端弹出一句 ``RetCode.xxx``。这个测试把防线做成
**静态扫描**：``src/`` 下所有「拿键当参数的异常构造」里的字符串字面量（以及能
解析到的模块级字符串常量，如 ``_VECTOR_FORMAT_KEY``）都必须存在于 ``MESSAGES``。

为什么用静态扫描而不是渲染测试：动态测试只能覆盖走过的分支，新写一处
``KbApiError('RetCode.x')`` 不会有任何红灯；静态扫描在提交时就报。
文案本身是否与对外契约一致由各自的业务测试与对照脚本负责，这里只管「键有没有」。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_message_keys.py -q
"""

import ast
import re
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = SERVICE_ROOT / 'src'

from shared.i18n.messages import MESSAGES, render  # noqa: E402

# 键的形状：至少一段点分（``RetCode.`` / ``kbase.`` …）。
KEY_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$')

# 消费「文案键」的四类异常。
#
# ``KbLiteralError`` / ``KbLiteralValidationError`` **按设计直接渲染字面量**，
# 故意不在扫描范围内 —— 其中 ``chunk_service._embedding`` 那处
# （``KbLiteralError('RetCode.embedding.fail')``）是有意保持的行为：响应里就是
# 那个键字符串。把它当缺陷「修」了反而破坏对外契约。
KEY_CLASSES = ('KbApiError', 'KbValidationError', 'KbValidatorError', 'KbWrappedValidatorError')

# 扫描到的键数量下限（当前 224）。数字只是防「扫描器坏掉后空集合恒通过」，
# 不要求精确 —— 键只会随功能增加而增长。
MIN_EXPECTED_KEYS = 150
MIN_EXPECTED_FILES = 100

#: 这些包**不在**本扫描器范围内，必须显式排除，否则扫描范围被无端扩大 ——
#: 它们抛的是文档处理模块 / 编排侧的文案键，不属于 ``kb_api.MESSAGES``。
_EXCLUDED_TOP_DIRS = frozenset({
    'ingestion', 'parsing', 'operators', 'engine',
})


def _module_string_constants(tree: ast.Module) -> dict:
    """模块级 ``NAME = '...'`` 常量（只认最简单的字面量赋值）。

    有些调用点把键放在常量里（``_VECTOR_FORMAT_KEY = 'knowledgeVector.format.incorrect'``），
    只看调用参数的字面量会漏掉它们。
    """
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target, node.value
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            constants[target.id] = value.value
    return constants


def _scan() -> tuple[list, list, int]:
    """扫描 ``src/``。返回 ``(检查过的键, 缺失的键, 扫描的文件数)``。

    缺失项是 ``(文件, 行号, 键)``；检查项同形，便于失败时给出行号。
    """
    checked, missing, files = [], [], 0
    for path in sorted(SRC_DIR.rglob('*.py')):
        if path.relative_to(SRC_DIR).parts[0] in _EXCLUDED_TOP_DIRS:
            continue
        files += 1
        # ``utf-8-sig``：个别历史文件带 BOM，不能被一个字节前缀打断整轮扫描。
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        constants = _module_string_constants(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = (func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute) else None)
            if name not in KEY_CLASSES:
                continue
            first = node.args[0]
            value = None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                value = first.value
            elif isinstance(first, ast.Name) and first.id in constants:
                value = constants[first.id]
            # 键形状之外的字符串参数是「恒为某语言的字面量」，不是键，跳过。
            if value is None or not KEY_PATTERN.match(value):
                continue
            entry = (str(path.relative_to(SRC_DIR)), node.lineno, value)
            checked.append(entry)
            if value not in MESSAGES:
                missing.append(entry)
    return checked, missing, files


def test_every_key_shaped_literal_exists_in_messages():
    """所有以「键」形式传入的四类异常，其键必须在 ``MESSAGES`` 里。"""
    checked, missing, _files = _scan()

    assert not missing, ('以下调用点用了 MESSAGES 里没有的键，会原样把键名发给用户：\n'
                         + '\n'.join('%s:%s -> %s' % row for row in missing))


def test_scan_actually_has_something_to_check():
    """防空转：扫描器坏了（路径写错/正则过严）时上面那条会恒通过，这里兜住。"""
    checked, _missing, files = _scan()

    assert files >= MIN_EXPECTED_FILES, '扫描到的文件太少，rglob 路径可能坏了'
    assert len(checked) >= MIN_EXPECTED_KEYS, '扫描到的键太少，AST 匹配可能坏了'


def test_newly_added_keys_match_the_java_properties():
    """这四个键的文本属于对外契约，不能改写。

    中文原文在 properties 里是 ``\\uXXXX`` 转义，grep 汉字搜不到，必须解码后核对。
    """
    # 与上面 ``file.not.exist`` 同文本，只是键名带 ``Recode`` 前缀
    assert MESSAGES['RetCode.file.not.exist'] == {
        'zh': '文件(夹)不存在',
        'en': 'The file (directory) does not exist',
    }
    assert MESSAGES['RetCode.operator.publish.repeat'] == {
        'zh': '算子已发布，不能再次发布',
        'en': 'Operator has been published and cannot publish again.',
    }
    # 键名里的 ``Recode`` 是历史拼写，不能改
    assert MESSAGES['Recode.chunk.update.error'] == {
        'zh': '切片更新失败',
        'en': 'chunk update error',
    }


def test_parse_empty_key_is_new_not_copied_from_properties():
    """``RetCode.operator.split.empty`` 的文案不属于 properties 契约。

    这里钉的是「两语言都在 + 渲染出的就是文案本身（不回落成键名）」。
    回落成键名是本项目最刺眼的一类回归（见本文件模块 docstring）。
    """
    assert set(MESSAGES['RetCode.operator.split.empty']) == {'zh', 'en'}
    zh = render('RetCode.operator.split.empty', 'zh')
    en = render('RetCode.operator.split.empty', 'en')
    assert zh != 'RetCode.operator.split.empty' and zh.startswith('文件未能解析出文本内容')
    assert en != 'RetCode.operator.split.empty' and en.startswith('No text content could be')


def test_unsupported_format_key_renders_both_languages():
    """``RetCode.operator.split.unsupported``：没有解析器的格式（图片 / OFD / zip）。

    不能落到兜底键 ``RetCode.operator.split.error`` —— 那句文案是
    「切分算子执行失败，请检查算子是否存在问题」，会把「格式不支持」说成「算子坏了」。
    这里钉住「两语言都在 + 渲染出的就是文案本身（不回落成键名）」。
    """
    assert set(MESSAGES['RetCode.operator.split.unsupported']) == {'zh', 'en'}
    zh = render('RetCode.operator.split.unsupported', 'zh')
    en = render('RetCode.operator.split.unsupported', 'en')
    assert zh != 'RetCode.operator.split.unsupported' and zh.startswith('暂不支持解析该格式')
    assert en != 'RetCode.operator.split.unsupported' and en.startswith(
        'This file format cannot be parsed yet')


def test_corrupt_file_key_renders_both_languages():
    """``RetCode.operator.split.corrupt``：文件本身损坏/不完整（截断的 docx 等）。

    不能落到兜底键 ``RetCode.operator.split.error`` —— 会把「文件坏了」说成
    「算子坏了」，用户会去查算子。这里钉住两语言文案（不是回落成键名）。
    """
    assert set(MESSAGES['RetCode.operator.split.corrupt']) == {'zh', 'en'}
    zh = render('RetCode.operator.split.corrupt', 'zh')
    en = render('RetCode.operator.split.corrupt', 'en')
    assert zh != 'RetCode.operator.split.corrupt' and zh.startswith('文件已损坏或不完整')
    assert en != 'RetCode.operator.split.corrupt' and en.startswith('The file is corrupted')


def test_literal_messages_are_deliberately_not_in_messages():
    """字面量异常（``KbLiteralError`` 家族）的文案**不进**这张表。

    进了就得给它们编一个 zh/en 译文，而这些文案本来就该按字面量原样返回 ——
    它们要么是校验器的默认英文 message，要么是写死的中文。
    """
    assert '知识库ID不能为空' not in MESSAGES


def test_content_extension_mismatch_key_renders_both_languages():
    """``file.content.type.mismatch``：exe 改名 .pdf 这类伪造后缀。"""
    assert set(MESSAGES['file.content.type.mismatch']) == {'zh', 'en'}
    zh = render('file.content.type.mismatch', 'zh')
    assert zh != 'file.content.type.mismatch' and zh.startswith('文件内容与扩展名不符')
