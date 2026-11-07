"""算子域的测试。

钉的都是「照直觉写就会错」的地方 —— 每一条都对应一个非显然的边界。
跑法（服务目录下）::

    python -m pytest tests/test_kb_api_operator.py -q
"""


import pytest

from shared.errors.api import KbApiError  # noqa: E402
from operators.service import operator_import, operator_service, system_operator  # noqa: E402


# ----------------------------------------------------------------------
# module 改写
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw, expected', [
    ('file_parse', 'file_parse'),
    ('text_split', 'text_split'),
    ('graph_extract', 'graph_extract'),
    ('rag_operator', 'rag_operator'),
    # 环节名不是枚举值 → 一律变 rag_operator。/operator/list/retriever 就吐这个。
    ('retriever', 'rag_operator'),
    ('pre-retriever', 'rag_operator'),
    ('post-retriever', 'rag_operator'),
    ('response-synthesizer', 'rag_operator'),
    ('', 'rag_operator'),
    (None, 'rag_operator'),
])
def test_normalize_module(raw, expected):
    assert operator_service.normalize_module(raw) == expected


def test_string_value_of_matches_java():
    """``String.valueOf(Object)`` 把 null 变成**字符串 "null"**，不是 Python 的 "None"。

    画布直接读 ``position`` / ``operator`` 这两个字段；四个字符的差异会让它认不出算子。
    """
    assert operator_service._string_value_of(None) == 'null'
    assert operator_service._string_value_of('') == ''
    assert operator_service._string_value_of(3) == '3'


# ----------------------------------------------------------------------
# defaultValue 出口转换
# ----------------------------------------------------------------------


def test_convert_default_value_parses_json_structures():
    """``json`` 类型的 defaultValue 必须解析成真结构 —— 否则画布拿到的 kwargs 是字符串。"""
    assert operator_service.convert_default_value(
        'json', '[{"knowledge_base_name": [], "top_k": 8}]') == [
        {'knowledge_base_name': [], 'top_k': 8}]


@pytest.mark.parametrize('arg_type, raw, expected', [
    ('int', '100', 100),
    ('str', 'abc', 'abc'),
    ('bool', 'true', True),
    ('bool', 'True', True),
    ('bool', 'yes', False),      # Boolean.parseBoolean 只认 "true"
    ('float', '0', 0.0),
    ('double', '1.5', 1.5),
    ('INT', '7', 7),             # 入参统一小写后解析
])
def test_convert_default_value_types(arg_type, raw, expected):
    assert operator_service.convert_default_value(arg_type, raw) == expected


def test_convert_default_value_passes_through_nulls():
    """argType 或值任一为空 → **原样返回**（不报错）。"""
    assert operator_service.convert_default_value(None, 'x') == 'x'
    assert operator_service.convert_default_value('int', None) is None


def test_convert_default_value_rejects_unknown_arg_type():
    """认不出的 argType 是**显式失败**（→ 0004），
    不是静默保留原字符串 —— 静默只会把错误推到运行期。"""
    with pytest.raises(KbApiError) as excinfo:
        operator_service.convert_default_value('weird', 'x')
    assert excinfo.value.code == '0004'
    assert 'Unsupported argType: weird' in excinfo.value.render('en')


# ----------------------------------------------------------------------
# support 的格式匹配
# ----------------------------------------------------------------------


def test_system_operator_format_match_is_substring_not_membership():
    """``prop.support_format.toString().contains(format)`` —— 对 ``"[md, pdf]"`` 做子串匹配。

    所以 ``format="d"`` 也会命中。这是有意保持的行为，不是笔误。
    """
    vo = {'prop': {'support_format': ['md', 'pdf', 'docx', 'txt']}}
    assert system_operator.supports_format(vo, 'md')
    assert system_operator.supports_format(vo, 'd')       # 子串，会命中
    assert system_operator.supports_format(vo, 'pdf')
    assert not system_operator.supports_format(vo, 'xlsx')


def test_system_operator_vo_has_null_system_and_hardcoded_published():
    """系统算子不在库里：``system`` 是 **null**（不是 0/1）、``isPublished`` 写死 1、
    四个时间/人字段全 null。"""
    vo = system_operator.to_operator_vo({
        'id': -1, 'display_name': {'zh': '甲', 'en': 'A'}, 'desc': {'zh': 'd', 'en': 'D'},
        'is_published': 0, 'visibleRange': 'public', 'module': 'text_split',
        'version': '1.0.0', 'supportedFormat': ['md'], 'defaultArgs': [],
    })
    assert vo['system'] is None
    assert vo['isPublished'] == 1          # 忽略 DTO 里的 0
    assert vo['createdDate'] is None and vo['createdBy'] is None
    assert vo['lastUpdatedDate'] is None and vo['lastUpdatedBy'] is None
    assert vo['prop'] == {'support_format': ['md']}   # 值是**数组**，不是字符串


def test_system_operator_registry_shape():
    """系统算子注册表的结构（id/display_name/supportedFormat）。

    注册表只有一份（``split/operator_all.json``），没有内置回落的第二份。
    """
    items = system_operator._load_registry()
    assert [item['id'] for item in items] == [-1, -2]
    assert all('display_name' in item and 'supportedFormat' in item for item in items)
    # 注册表里必须有 operator_module / operator_function（服务端靠它们定位并调用
    # main.py），但对外的 to_operator_vo / runtime.system_operators 会剔除。
    # -1 与 -2 共用同一个入口包，用 operator_function 区分。
    assert all('operator_module' in item and 'operator_function' in item for item in items)
    assert items[0]['operator_module'] == 'operators/text_split'
    assert items[0]['operator_function'] == 'file_split_with_chunk'
    assert items[1]['operator_module'] == 'operators/text_split'
    assert items[1]['operator_function'] == 'file_split'


# ----------------------------------------------------------------------
# 导入：config.json 的抽取与校验
# ----------------------------------------------------------------------


def _manifest(tmp_path, config, extra_files=None, lang='zh'):
    work = tmp_path / 'work'
    work.mkdir(parents=True, exist_ok=True)
    import json as _json

    (work / 'config.json').write_text(
        config if isinstance(config, str) else _json.dumps(config), encoding='utf-8')
    for name, payload in (extra_files or {'a.py': 'p'}).items():
        (work / name).write_text(payload, encoding='utf-8')
    return operator_import.build_manifest(work, lang)


BASE_CONFIG = {
    'display_name': {'zh': '甲', 'en': 'A'},
    'desc': {'zh': '描述', 'en': 'desc'},
    'is_published': 1,
    'visibleRange': 'private',
    'module': 'text_split',
    'version': '1.0.0',
    'supportedFormat': ['md'],
    'defaultArgs': [{'argName': 'n', 'argType': 'int', 'defaultValue': 1, 'description': 'd'}],
}


def _config(**overrides):
    payload = dict(BASE_CONFIG)
    payload.update(overrides)
    return payload


def test_import_forces_is_published_to_one(tmp_path):
    """config.json 里的 ``is_published`` **校验通过后被丢弃** —— 三个解析策略都写死 1。"""
    manifest = _manifest(tmp_path, _config(is_published=0))
    assert manifest['isPublished'] == 1


@pytest.mark.parametrize('module, key', [
    ('', 'RetCode.operator.module.check.notblank'),
    ('nope', 'RetCode.operator.type.not.support'),
])
def test_import_module_errors(tmp_path, module, key):
    with pytest.raises(KbApiError) as excinfo:
        _manifest(tmp_path, _config(module=module))
    assert excinfo.value.key == key
    assert excinfo.value.code == '0005'      # 导入链内所有失败都是 0005


@pytest.mark.parametrize('raw_config, key', [
    ('{oops', 'RetCode.operator.type.not.support'),          # 解析失败 → module 为 null
    ('[1,2,3]', 'RetCode.operator.module.check.notblank'),   # 非对象 → MissingNode → 空串
])
def test_import_module_extraction_edge_cases(tmp_path, raw_config, key):
    """这两条映射对应两个不同分支：解析失败与非对象 JSON。"""
    with pytest.raises(KbApiError) as excinfo:
        _manifest(tmp_path, raw_config)
    assert excinfo.value.key == key


def test_import_module_explicit_null_is_unsupported(tmp_path):
    """``{"module": null}`` → null 转文本得到字符串 "null" → 认不出。"""
    with pytest.raises(KbApiError) as excinfo:
        _manifest(tmp_path, _config(module=None))
    assert excinfo.value.key == 'RetCode.operator.type.not.support'


def test_import_violations_are_rendered_and_sorted_per_language(tmp_path):
    """违规消息**先渲染再按渲染结果排序** —— 所以中英顺序可能不同。

    排序必须按渲染后的文案，而不是键名 —— 按键名排会得到不同顺序。
    """
    broken = _config(display_name={'zh': '', 'en': ''})

    with pytest.raises(KbApiError) as zh_error:
        _manifest(tmp_path / 'zh', broken, lang='zh')
    zh_message = zh_error.value.render('zh')

    with pytest.raises(KbApiError) as en_error:
        _manifest(tmp_path / 'en', broken, lang='en')
    en_message = en_error.value.render('en')

    assert zh_message.startswith('config.json配置不正确：')
    # 中文按码点排：'d' < '算'
    assert 'display_name 为空;算子名称' in zh_message
    # 英文按 ASCII 排：'L' < 'd'
    assert 'Length of operator name' in en_message
    assert en_message.index('Length') < en_message.index('displayname.zh.notblank')
    assert 'RetCode.' not in zh_message and 'RetCode.' not in en_message


def test_violation_list_is_frozen_at_build_time(tmp_path):
    """内层违规文案在**抛异常时**就按请求语言定死了，事后换语言只影响外层模板。

    这与对外契约一致（取文案在抛业务异常那一刻就用请求 locale 解析好了）。所以
    ``build_manifest`` 必须拿到与请求一致的语言 —— 这也是它签名里带 ``lang`` 的原因。
    """
    with pytest.raises(KbApiError) as excinfo:
        _manifest(tmp_path, _config(display_name={'zh': '', 'en': ''}), lang='zh')

    assert 'display_name 为空' in excinfo.value.render('zh')
    # 换语言只会换掉外层那句，内层仍是构建时定下的中文
    assert 'display_name 为空' in excinfo.value.render('en')
    assert excinfo.value.render('en').startswith('config.json was not configured correctly:')


def test_import_rejects_float_argtype(tmp_path):
    """导入期只认 ``str`` / ``int`` / ``bool``；``float`` 虽然读路径支持，但传不进来。"""
    with pytest.raises(KbApiError) as excinfo:
        _manifest(tmp_path, _config(defaultArgs=[
            {'argName': 'v', 'argType': 'float', 'defaultValue': 1.0, 'description': 'd'}]))
    assert excinfo.value.key == 'RetCode.operator.arg.type.incorrect'


def test_import_rejects_default_value_type_mismatch(tmp_path):
    """是**真类型判断**，不做字符串转换：``{"argType":"int","defaultValue":"1"}`` 不合法。

    注意与读路径的 ``convertDefaultValues`` 口径不同（那边会把字符串转成 int）。
    """
    with pytest.raises(KbApiError) as excinfo:
        _manifest(tmp_path, _config(defaultArgs=[
            {'argName': 'v', 'argType': 'int', 'defaultValue': '1', 'description': 'd'}]))
    assert excinfo.value.key == 'RetCode.operator.arg.defaultValue.incorrect'


def test_import_requires_exactly_one_python_file_for_file_operators(tmp_path):
    with pytest.raises(KbApiError) as too_many:
        _manifest(tmp_path / 'two', _config(), {'a.py': 'p', 'b.py': 'p'})
    assert too_many.value.key == 'RetCode.operator.python.exist.more'

    with pytest.raises(KbApiError) as none:
        _manifest(tmp_path / 'nopy', _config(), {'readme.md': 'p'})
    assert none.value.key == 'RetCode.operator.python.not.found'


def test_import_rag_operator_uses_operator_and_package(tmp_path):
    """RAG 算子那一支：prop 是 ``{operator, position}``，且**不搬运 config 里的 id**。"""
    manifest = _manifest(tmp_path, {
        'display_name': {'zh': '甲', 'en': 'A'}, 'desc': {'zh': '描述', 'en': 'desc'},
        'is_published': 1, 'visibleRange': 'private', 'module': 'pre-retriever',
        'version': '1.0.0', 'id': 99,
        'operator': 'CustomPreRetriever',
        'package': 'core.rag.pre_retriever.custom_pre_retriever',
        'defaultArgs': [],
    })
    assert manifest['id'] is None                       # RAGOperatorConfigParse 不搬 id
    assert manifest['prop'] == {'operator': 'CustomPreRetriever',
                                'position': 'core.rag.pre_retriever.custom_pre_retriever'}


def test_import_rejects_non_zip_filename():
    with pytest.raises(KbApiError) as excinfo:
        operator_service.import_operator('op.txt', b'x', 'admin', '', 'en')
    assert excinfo.value.key == 'RetCode.operator.type.incorrect'
    assert excinfo.value.code == '0005'


def test_import_rejects_oversize_package():
    """超限报的是「知识检索算子大小应限制在 X 以内」，X 由 ``getReadableFileSize`` 渲染。"""
    oversized = b'x' * (operator_service.IMPORT_LIMIT_BYTES + 1)
    with pytest.raises(KbApiError) as excinfo:
        operator_service.import_operator('op.zip', oversized, 'admin', '', 'en')
    assert excinfo.value.key == 'RetCode.operator.workflow.import.sizecheck'
    assert excinfo.value.args == ('2 MB',)


def test_readable_size_matches_java():
    assert operator_service._readable_size(2097152) == '2 MB'
    assert operator_service._readable_size(512) == '512 Bytes'   # 单位就是 "Bytes"
    assert operator_service._readable_size(1536) == '1.5 KB'
    assert operator_service._readable_size(1024) == '1 KB'


def test_zip_slip_is_rejected(tmp_path):
    """逃出目标目录的条目直接报错，不是解到外面去。"""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('../escape.txt', 'x')
    with pytest.raises(KbApiError) as excinfo:
        operator_import._extract(buffer.getvalue(), tmp_path / 'out')
    assert excinfo.value.key == 'RetCode.zip.decompress.error'


def test_operator_templates_are_bundled():
    """四个模板都在包内 —— 少了任何一个，前端「下载模板」就是一个空的 zip。"""
    for operator_type in ('file_parse', 'text_split', 'graph_extract', 'rag_operator'):
        content, filename = operator_service.operator_template_download(operator_type)
        assert filename == f'{operator_type}.zip'
        assert content[:2] == b'PK'


def test_unknown_template_has_null_message():
    """未知 operatorType → 0005 且 **msg 是 null**（不带文案）。"""
    with pytest.raises(KbApiError) as excinfo:
        operator_service.operator_template_download('nope')
    assert excinfo.value.code == '0005'
    assert excinfo.value.render('zh') is None


def test_prop_value_uses_java_list_tostring():
    """``prop_value`` 存的是列表的字符串形式：``[md, txt]``。

    读路径的 ``selectByFormat`` 是拿它做 ``LIKE '%fmt%'`` 子串匹配的，
    写成 JSON 的 ``'["md", "txt"]'`` 也能匹配上常见格式，但形状就与线上库不一致了。
    """
    assert operator_import._prop_text(['md', 'txt']) == '[md, txt]'
    assert operator_import._prop_text([]) == '[]'
    assert operator_import._prop_text('core.rag.x') == 'core.rag.x'


def test_default_value_is_stored_as_text():
    assert operator_import._as_text(512) == '512'
    assert operator_import._as_text(True) == 'true'
    assert operator_import._as_text(None) is None
