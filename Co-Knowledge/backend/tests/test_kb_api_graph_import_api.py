"""``/graph/import`` 的纯逻辑测试（不连库、不发请求）。

端到端往返在 ``tools/verify/verify-graph-import-e2e.py``（拿真导出 zip 当输入，
两边各建库各导入，再查出来比）；这里钉的是解压/查找/校验那几处纯函数。

跑法::

    python -m pytest tests/test_kb_api_graph_import_api.py -q
"""

import io
import json
import zipfile

import pytest

from shared.errors.api import KbApiError  # noqa: E402
from graph.service import graph_import_api as api  # noqa: E402


def make_zip(entries: dict, *, utf8_names=True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, payload in entries.items():
            info = zipfile.ZipInfo(name)
            if not utf8_names:
                # 抹掉 UTF-8 标志位，逼它走 GB18030 那条解码路径
                info.flag_bits &= ~0x800
            archive.writestr(info, payload)
    return buffer.getvalue()


# ----------------------------------------------------------------------
# desc.json 的 id 校验
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw', [None, '', '   '])
def test_optional_id_blank_is_none(raw):
    """id 是**可选**字段：没给就不校验。"""
    assert api._validate_optional_id(raw) is None


def test_optional_id_valid_returns_suffix():
    # 32 位：历史 uuid；16 位：新建库的短 id
    assert api._validate_optional_id('graph_' + 'a1B2' * 8) == 'a1B2' * 8
    assert api._validate_optional_id('graph_' + 'a1B2' * 4) == 'a1B2' * 4


def test_optional_id_missing_prefix():
    with pytest.raises(KbApiError) as caught:
        api._validate_optional_id('kb_' + 'a' * 32)
    assert caught.value.key == 'graph.import.id.format.invalid.prefix'


@pytest.mark.parametrize('length', [8, 20, 31, 33])
def test_optional_id_wrong_length_passes_the_length(length):
    with pytest.raises(KbApiError) as caught:
        api._validate_optional_id('graph_' + 'a' * length)
    assert caught.value.key == 'graph.import.id.format.invalid.length'
    assert caught.value.args == (length,)


def test_optional_id_non_hex_reports_the_char():
    with pytest.raises(KbApiError) as caught:
        api._validate_optional_id('graph_' + 'z' * 32)
    assert caught.value.key == 'graph.import.id.format.invalid.char'
    assert caught.value.args == ('z',)


# ----------------------------------------------------------------------
# 按 endsWith 找 desc.json / schema.json
# ----------------------------------------------------------------------


def test_find_json_matches_by_suffix_not_equality():
    """``xdesc.json`` 也算命中 —— 按后缀匹配（不是相等）。"""
    entries = {'xdesc.json': json.dumps({'name': 'n'}).encode()}
    found, parsed = api._find_json(entries, 'desc.json')
    assert found and parsed == {'name': 'n'}


def test_find_json_distinguishes_missing_from_unparseable():
    """**找不到**（illegal）与**找到但解析不出来**（fail）是两回事，别合并。"""
    found, parsed = api._find_json({}, 'schema.json')
    assert (found, parsed) == (False, None)

    found, parsed = api._find_json({'schema.json': b'{bad'}, 'schema.json')
    assert (found, parsed) == (True, None)


def test_find_json_skips_non_object_json():
    """解析出来是数组/字符串的，当作没命中（只接受 JSON 对象）。"""
    found, parsed = api._find_json({'schema.json': b'[1,2]'}, 'schema.json')
    assert (found, parsed) == (True, None)


def test_find_json_prefers_first_parsable_when_several_match():
    entries = {'a.schema.json': b'{bad', 'b.schema.json': json.dumps({'ok': 1}).encode()}
    found, parsed = api._find_json(entries, 'schema.json')
    assert found and parsed == {'ok': 1}


# ----------------------------------------------------------------------
# 解压
# ----------------------------------------------------------------------


def test_unzip_roundtrip_utf8_names():
    content = make_zip({'entities.jsonl': b'{}\n', 'sub/edges.jsonl': b'\n'})
    entries = api._unzip(content)
    assert set(entries) == {'entities.jsonl', 'sub/edges.jsonl'}
    assert entries['entities.jsonl'] == b'{}\n'


def test_unzip_rejects_non_zip():
    with pytest.raises(KbApiError) as caught:
        api._unzip(b'definitely not a zip')
    assert caught.value.key == 'zip.decompress.error'


@pytest.mark.parametrize('name', ['../evil.txt', 'sub/../../evil.txt', '/abs.txt',
                                  '\\abs.txt', 'c:/win.txt'])
def test_unzip_rejects_zip_slip(name):
    """zip-slip：条目名逃出根目录一律拒绝。"""
    assert api._is_unsafe_entry(name) is True


@pytest.mark.parametrize('name', ['entities.jsonl', 'sub/entities.jsonl', 'a-b_c.json'])
def test_safe_entries_pass(name):
    assert api._is_unsafe_entry(name) is False


def test_unzip_skips_directory_entries():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('dir/', b'')
        archive.writestr('dir/entities.jsonl', b'{}\n')
    assert set(api._unzip(buffer.getvalue())) == {'dir/entities.jsonl'}


def test_gb18030_entry_names_are_decoded():
    """条目名按 **GB18030** 解码。

    这里直接调 ``_decode_entry_name`` 而不是造一个 zip —— Python 的 ``zipfile``
    写非 ASCII 名字时会**自动置 UTF-8 标志位**，造不出「标志位为 0 + GB18030 字节」
    的真 zip；而那种 zip 恰恰是本函数要处理的目标（中文 Windows 的压缩工具会产出）。
    用 ``ZipInfo`` 直接表达那两种输入即可。
    """
    info = zipfile.ZipInfo('实体.jsonl')
    info.flag_bits = 0
    # zipfile 读取时按 cp437 解成了 str；原始字节是 GB18030
    info.filename = '实体.jsonl'.encode('gb18030').decode('cp437')
    assert api._decode_entry_name(info) == '实体.jsonl'

    utf8 = zipfile.ZipInfo('实体.jsonl')
    utf8.flag_bits = 0x800
    utf8.filename = '实体.jsonl'
    assert api._decode_entry_name(utf8) == '实体.jsonl'      # 置了位就直接用


# ----------------------------------------------------------------------
# 与已有库的比对
# ----------------------------------------------------------------------


def test_same_kbase_reports_all_three_mismatches_joined_by_fullwidth_semicolon():
    existing = {'kbase_id': 'x', 'name': 'old', 'description': 'd1', 'embedding_model': 'm1'}
    with pytest.raises(Exception) as caught:
        api._assert_same_kbase(existing, {'desc': 'd2', 'embedding': 'm2'}, 'new')
    message = caught.value.message          # 字面量文案在 .message 上
    assert 'name字段与当前记录不一致' in message
    assert 'desc字段与当前记录不一致' in message
    assert 'embedding字段与当前记录不一致' in message
    assert message.count('；') == 2          # 全角分号连接


def test_same_kbase_passes_when_identical():
    existing = {'kbase_id': 'x', 'name': 'n', 'description': 'd', 'embedding_model': 'm'}
    api._assert_same_kbase(existing, {'desc': 'd', 'embedding': 'm'}, 'n')   # 不抛


def test_same_kbase_treats_null_desc_as_empty():
    """``desc`` 为 null 时按空串比（比较前先 normalize）。"""
    existing = {'kbase_id': 'x', 'name': 'n', 'description': '', 'embedding_model': 'm'}
    api._assert_same_kbase(existing, {'desc': None, 'embedding': 'm'}, 'n')


# ----------------------------------------------------------------------
# 临时 zip：保留 document_chunk + 去重 + 清理
# ----------------------------------------------------------------------


def test_write_temp_zip_keeps_document_chunk():
    import os

    path = api._write_temp_zip({
        'entities.jsonl': b'{"entity_id":"E1"}',
        'edges.jsonl': b'{"edge_id":"R1"}',
        'document_chunk.jsonl': b'{"id":"c1"}',
        'other.txt': b'ignored',
    })
    try:
        with zipfile.ZipFile(path) as archive:
            assert sorted(archive.namelist()) == [
                'document_chunk.jsonl', 'edges.jsonl', 'entities.jsonl']
    finally:
        os.unlink(path)


def test_write_temp_zip_prefers_root_and_dedupes_nested_entries():
    import os

    path = api._write_temp_zip({
        'nested/entities.jsonl': b'{"entity_id":"nested"}',
        'entities.jsonl': b'{"entity_id":"root"}',
        'deep/dir/entities.jsonl': b'{"entity_id":"deep"}',
    })
    try:
        with zipfile.ZipFile(path) as archive:
            assert archive.namelist() == ['entities.jsonl']
            assert archive.read('entities.jsonl') == b'{"entity_id":"root"}'
    finally:
        os.unlink(path)


def test_submit_removes_temp_zip_after_run(monkeypatch):
    import os

    captured = {}

    def fake_import(*args, **kwargs):
        captured['path'] = args[2]
        assert os.path.exists(captured['path'])

    monkeypatch.setattr(api.graph_import_engine, 'import_from_zip', fake_import)
    monkeypatch.setattr(api._GRAPH_IMPORT_POOL, 'submit', lambda fn: fn())

    api._submit({'name': 'kb'}, {'kbase_id': 'a' * 32}, {'schema_id': 's'},
                {'entities.jsonl': b'{}'})

    assert captured['path'].startswith('/tmp/graph_import_')
    assert not os.path.exists(captured['path'])


def test_same_kbase_rejects_document_category():
    """按 id 命中文档库时不能当作图谱库复用。"""
    with pytest.raises(KbApiError):
        api._assert_same_kbase(
            {'kbase_id': 'a' * 32, 'category': 1, 'name': 'n',
             'description': '', 'embedding_model': 'm'},
            {'desc': '', 'embedding': 'm'}, 'n')


# ----------------------------------------------------------------------
# 受理前先落「入库中」
# ----------------------------------------------------------------------


def test_mark_importing_sets_indexing_status(monkeypatch):
    """202 返回前必须把库标成 4（入库中）。

    不标的话客户端刷新到的是静止的 status=0，列表的「有构建中行」闸门不会启动，
    导入完成后也不会自动刷新。
    """
    calls = []
    monkeypatch.setattr(api.kbase_store, 'update_process_with_time',
                        lambda *args: calls.append(args))

    api._mark_importing('abc123')
    api._mark_importing(None)
    api._mark_importing('')

    assert calls == [('abc123', '4', 0)]
