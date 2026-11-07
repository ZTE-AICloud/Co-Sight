"""文件域的测试。

重点钉住两处容易实现错的边界：``MEM_LIMIT`` 的压缩逻辑、单库文件数取哪一列。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_file.py -q
"""

import json

import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from shared.errors.api import (  # noqa: E402
    KbServerError,
    KbValidationError,
    KbWrappedValidatorError,
)
from shared.prefixes import RKB_PREFIX as KBASE_PREFIX
from http_api import register_rkb_api  # noqa: E402
from knowledge_base.service import file_service  # noqa: E402


@pytest.fixture(autouse=True)
def _no_operator_formats(monkeypatch):
    """默认不让「自定义算子格式」参与 —— 单测不连库。"""
    monkeypatch.setattr(file_service, '_custom_operator_formats', lambda: set())


def test_size_limit_is_compressed_when_mem_limit_is_small(monkeypatch):
    """显式 ``MEM_LIMIT=8``（开发配置值）< 800 ⇒ 走压缩分支：``>10`` 的变 5、
    ``<=10`` 的减半。

    实测线上 ``GET /file/size_limit`` 就是 ``txt: 2.5, md: 5, number: 1``。
    """
    monkeypatch.setenv('MEM_LIMIT', '8')

    result = file_service.file_size_limit(1)

    assert result['maxSizeMap']['txt'] == 2.5      # 5 / 2
    assert result['maxSizeMap']['md'] == 5.0       # 100 > 10 → 5
    assert result['maxSizeMap']['pdf'] == 5.0      # 150 > 10 → 5
    assert result['number'] == 1                   # outer-document 被压成 1


def test_size_limit_is_raw_when_mem_limit_is_large(monkeypatch):
    monkeypatch.setenv('MEM_LIMIT', '1024')

    result = file_service.file_size_limit(1)

    assert result['maxSizeMap']['txt'] == 5.0      # 原值
    assert result['maxSizeMap']['md'] == 100.0
    assert result['number'] == 50                  # outer-document 原值


def test_mem_limit_falls_back_to_cgroup_when_env_absent(monkeypatch):
    """没给 ``MEM_LIMIT`` 时按容器 cgroup 内存判定。

    本机 cgroup 不限内存 → 原始档位：单次 50 个、pdf 150MB。
    缺少这一步会一律按开发默认值 8 压缩成「1 个 / 5MB」。
    """
    monkeypatch.delenv('MEM_LIMIT', raising=False)
    monkeypatch.setattr(file_service, '_cgroup_memory_mb',
                        lambda: file_service.UNLIMITED_MEMORY_MB)

    result = file_service.file_size_limit(1)

    assert result['number'] == 50
    assert result['maxSizeMap']['pdf'] == 150.0
    assert result['maxSizeMap']['txt'] == 5.0


def test_mem_limit_falls_back_to_small_cgroup(monkeypatch):
    """cgroup 只有 512MB → 仍走压缩分支（小内存容器该有的降级不能丢）。"""
    monkeypatch.delenv('MEM_LIMIT', raising=False)
    monkeypatch.setattr(file_service, '_cgroup_memory_mb', lambda: 512.0)

    result = file_service.file_size_limit(1)

    assert result['number'] == 1
    assert result['maxSizeMap']['pdf'] == 5.0


def test_explicit_mem_limit_wins_over_cgroup(monkeypatch):
    monkeypatch.setenv('MEM_LIMIT', '1024')
    monkeypatch.setattr(file_service, '_cgroup_memory_mb', lambda: 512.0)

    assert file_service.file_size_limit(1)['number'] == 50


def test_empty_mem_limit_env_falls_back_to_cgroup(monkeypatch):
    """compose 用 ``${MEM_LIMIT:-}`` 透传时会传空串 —— 空串必须当未设置。"""
    monkeypatch.setenv('MEM_LIMIT', '')
    monkeypatch.setattr(file_service, '_cgroup_memory_mb', lambda: 512.0)

    assert file_service._memory_limit_value() == 512.0


def test_cgroup_memory_mb_reads_limit_file(tmp_path, monkeypatch):
    limit_file = tmp_path / 'memory.max'
    limit_file.write_text('1073741824\n')
    monkeypatch.setattr(file_service, 'CGROUP_V2_MEMORY_MAX', limit_file)
    monkeypatch.setattr(file_service, 'CGROUP_V1_MEMORY_LIMIT', tmp_path / 'missing')

    assert file_service._cgroup_memory_mb() == 1024.0


def test_cgroup_memory_mb_treats_max_as_unlimited(tmp_path, monkeypatch):
    limit_file = tmp_path / 'memory.max'
    limit_file.write_text('max\n')
    monkeypatch.setattr(file_service, 'CGROUP_V2_MEMORY_MAX', limit_file)
    monkeypatch.setattr(file_service, 'CGROUP_V1_MEMORY_LIMIT', tmp_path / 'missing')

    assert file_service._cgroup_memory_mb() == file_service.UNLIMITED_MEMORY_MB


def test_memory_limit_is_unlimited_when_env_and_cgroup_missing(tmp_path, monkeypatch):
    """两处都读不到 → 按不限处理（取 64 位最大值），不能回落到 8。"""
    monkeypatch.delenv('MEM_LIMIT', raising=False)
    monkeypatch.setattr(file_service, 'CGROUP_V2_MEMORY_MAX', tmp_path / 'missing-v2')
    monkeypatch.setattr(file_service, 'CGROUP_V1_MEMORY_LIMIT', tmp_path / 'missing-v1')

    assert file_service._memory_limit_value() == file_service.UNLIMITED_MEMORY_MB


def test_image_formats_are_not_uploadable(monkeypatch):
    """图片能力已整体退役：文档库与图谱库都不接受 jpg / jpeg / png。"""
    monkeypatch.setenv('MEM_LIMIT', '1024')

    for category in (1, 10):
        sizes = file_service.file_size_limit(category)['maxSizeMap']
        for fmt in ('jpg', 'jpeg', 'png'):
            assert fmt not in sizes

    assert file_service.file_size_limit(10)['number'] == 50    # graph-document 档


def test_upload_check_rejects_image_file():
    """上传 png 直接落 ``file.type.validation``，不再有图片切分兜底。"""
    from shared.errors.api import KbValidationError

    with pytest.raises(KbValidationError) as caught:
        file_service.upload_check(
            [file_service.UploadedFile('a.png', b'\x89PNG\r\n\x1a\nrest')],
            'outer-document')

    assert caught.value.key == 'file.type.validation'


def test_unknown_category_raises_server_error(monkeypatch):
    """``getFileLimitTypeByCode`` 不认识 code 时取到 null → **0001**，
    不是 0000 + ``number: null``。
    """
    monkeypatch.setenv('MEM_LIMIT', '1024')

    with pytest.raises(KbServerError):
        file_service.file_size_limit(99)


def test_custom_operator_formats_get_default_limits(monkeypatch):
    monkeypatch.setenv('MEM_LIMIT', '1024')
    monkeypatch.setattr(file_service, '_custom_operator_formats', lambda: {'zedx', 'xyz'})

    sizes = file_service.file_size_limit(1)['maxSizeMap']

    assert sizes['zedx'] == file_service.ZEDX_OPERATOR_FILE_SIZE       # 650
    assert sizes['xyz'] == file_service.CUSTOM_OPERATOR_FILE_SIZE      # 50


def test_expand_zip_unpacks_single_zip():
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('a.md', b'AAA')
        archive.writestr('nested/b.md', b'BBB')      # 按 basename 展平
    files = [file_service.UploadedFile('pack.zip', buffer.getvalue())]

    expanded = file_service.expand_zip(files)

    assert sorted(f.filename for f in expanded) == ['a.md', 'b.md']


def test_expand_zip_leaves_non_zip_alone():
    files = [file_service.UploadedFile('a.md', b'x')]

    assert file_service.expand_zip(files) is files


def test_expand_zip_leaves_broken_zip_alone():
    files = [file_service.UploadedFile('bad.zip', b'not a zip')]

    assert file_service.expand_zip(files) is files


def test_metadata_violations_are_aggregated_sorted_and_joined():
    """``UploadFileDTO`` 的四个 ``@NotBlank``（含 kType）全缺时**一起回**（不是只报第一条）。

    收集全部 violations → 渲染 → 排序 → ``";"`` 拼接 →
    套 ``RetCode.upload.json.incorrect``。示例（zh；en 只差外层模板）::

        metadata={}                                      → {directoryId};{splitType};{splitType}
        metadata={'directoryId':'x'}                     → {splitType};{splitType}
        metadata={'directoryId':'x','kType':'document'}  → {splitType}

    ⚠️ ``kType`` 与 ``splitType`` 共用同一条 message，两条都缺时同一句出现**两遍**
    —— 这是有意保持的行为，别去重。上面前两例里没有 kbaseId 那条，因为 HTTP 路径上
    查询参数 kbaseId 会回填进 metadata（见 F1 一节）。
    """
    with pytest.raises(KbWrappedValidatorError) as caught:
        file_service.validate_metadata({})
    assert caught.value.code == '0005'
    # 排序发生在**渲染之后**，两侧顺序由文案自己比出来（这里四条都是花括号原文）
    assert caught.value.render('zh') == (
        '上传文件参数报错{RetCode.upload.directoryId.check};{RetCode.upload.kbaseId.check}'
        ';{RetCode.upload.splitType.check};{RetCode.upload.splitType.check}')
    assert caught.value.render('en') == (
        'upload file params incorrect{RetCode.upload.directoryId.check}'
        ';{RetCode.upload.kbaseId.check};{RetCode.upload.splitType.check}'
        ';{RetCode.upload.splitType.check}')

    # 只缺 kType + splitType：两条 message 一模一样 → 拼接结果里出现两遍
    with pytest.raises(KbWrappedValidatorError) as caught:
        file_service.validate_metadata({'directoryId': 'd', 'kbaseId': 'k'})
    assert caught.value.render('zh') == (
        '上传文件参数报错{RetCode.upload.splitType.check};{RetCode.upload.splitType.check}')

    # 单条：缺 splitType（kType 在场）
    with pytest.raises(KbWrappedValidatorError) as caught:
        file_service.validate_metadata({'directoryId': 'd', 'kbaseId': 'k',
                                        'kType': 'document'})
    assert caught.value.render('zh') == '上传文件参数报错{RetCode.upload.splitType.check}'

    # ``@NotBlank`` 的 trim 语义：纯空白也算空
    with pytest.raises(KbWrappedValidatorError) as caught:
        file_service.validate_metadata({'directoryId': 'd', 'kbaseId': 'k',
                                        'kType': 'document', 'splitType': '\t'})
    assert caught.value.render('zh') == '上传文件参数报错{RetCode.upload.splitType.check}'

    # 四个都有值 → 放行
    file_service.validate_metadata(
        {'directoryId': 'd', 'kbaseId': 'k', 'kType': 'document', 'splitType': 'system'})


def test_operator_args_must_be_present():
    """算子条目里的 ``args`` 为 null → 0005 + 注解原文（``args`` 的 @NotNull）。"""
    with pytest.raises(KbWrappedValidatorError) as caught:
        file_service.validate_operator_args(
            {'splitOperator': {'md': {'operatorId': 2}}})
    assert caught.value.code == '0005'
    assert caught.value.render('zh') == '上传文件参数报错OperatorParams list cannot be empty'


# ----------------------------------------------------------------------
# F2：operatorId 的 @NotNull
#
# 三个变体都必须回 0005 ``upload file params incorrectmust not be null``：
# ``''``（空串按 null 绑定）/ ``null`` / 键缺席。
# ----------------------------------------------------------------------


@pytest.mark.parametrize('operator', [{'operatorId': ''},
                                      {'operatorId': None},
                                      {}])
def test_operator_id_must_not_be_null(operator):
    entry = {**operator, 'args': []}                       # args 合规，只留 operatorId 这一条
    with pytest.raises(KbWrappedValidatorError) as caught:
        file_service.validate_operator_args({'splitOperator': {'md': entry}})
    assert caught.value.code == '0005'
    assert caught.value.render('en') == 'upload file params incorrectmust not be null'
    assert caught.value.render('zh') == '上传文件参数报错不能为null'


def test_operator_id_check_covers_parse_operator_table():
    """两张表**各跑一遍**，parseOperator 在前。"""
    with pytest.raises(KbWrappedValidatorError):
        file_service.validate_operator_args(
            {'parseOperator': {'pdf': {'operatorId': '', 'args': []}}})

    # parseOperator 合规、splitOperator 不合规 → 报 splitOperator 那条
    with pytest.raises(KbWrappedValidatorError):
        file_service.validate_operator_args({
            'parseOperator': {'pdf': {'operatorId': 1, 'args': []}},
            'splitOperator': {'md': {'operatorId': None, 'args': []}}})


def test_parse_operator_validated_before_split_operator():
    """两表都不合规时先报 parseOperator 的（:41 在 :42 之前）—— 用两种 violation 区分。"""
    with pytest.raises(KbWrappedValidatorError) as caught:
        file_service.validate_operator_args({
            'parseOperator': {'pdf': {'operatorId': 1}},                 # args 缺席
            'splitOperator': {'md': {'operatorId': '', 'args': []}}})    # operatorId 空串
    assert caught.value.render('en') == (
        'upload file params incorrectOperatorParams list cannot be empty')


def test_combined_violations_are_sorted_and_joined():
    """同一算子的两条 violation：**先本地化、再排序、``";"`` 拼接**（:52-54）。

    两种语言下 ``OperatorParams...`` 都排在 ``must not be null`` / ``不能为null`` 前面
    —— 但顺序是渲染后比出来的，不能在调用点写死。整段再套 ``RetCode.upload.json.incorrect``。
    """
    with pytest.raises(KbWrappedValidatorError) as caught:
        file_service.validate_operator_args(
            {'splitOperator': {'md': {'operatorId': '', 'args': None}}})
    assert caught.value.render('en') == ('upload file params incorrect'
                                         'OperatorParams list cannot be empty;must not be null')
    assert caught.value.render('zh') == ('上传文件参数报错'
                                         'OperatorParams list cannot be empty;不能为null')


def test_numeric_string_operator_id_passes_validation():
    """数字串 ``"3"`` 在绑定期被强转成整数 —— 校验只认 null，类型归一由 handler 负责。"""
    file_service.validate_operator_args(
        {'splitOperator': {'md': {'operatorId': '3', 'args': []}}})   # 不抛


# ----------------------------------------------------------------------
# F1：文档上传的 kbaseId —— 路径参数在**校验之前**回填进 metadata
#
# 路径参数在**校验之前**回填进 metadata：``buildUploadFileDTO(metadata)`` 之后立刻
# ``uploadFileDTO.setKbaseId(kbaseId)``（无条件 setter = **覆盖**），
# bean validation 发生在回填之后。metadata 里没有 kbaseId 时不能先撞
# ``validate_metadata`` → 0005。
# ----------------------------------------------------------------------


def _build_client() -> TestClient:
    app = FastAPI()
    register_rkb_api(app)
    return TestClient(app)


def _upload(client: TestClient, kbase_id: str, metadata: dict):
    return client.post(
        f'{KBASE_PREFIX}/knowledge-bases/{kbase_id}/documents',
        files={'files': ('a.md', b'AAA')},
        data={'metadata': json.dumps(metadata)})


@pytest.fixture()
def upload_probe(monkeypatch):
    """挂上真实路由、只把 ``upload_files`` 换成探针 —— 单测不连库。"""
    captured = {}

    def fake_upload_files(files, metadata, kbase_id, emp_no, queue=None, run_split_pipeline=True):
        captured['metadata'] = metadata
        captured['kbase_id'] = kbase_id
        return {item.filename: 'fid-' + item.filename for item in files}

    monkeypatch.setattr(file_service, 'upload_files', fake_upload_files)
    return _build_client(), captured


def test_upload_backfills_query_kbaseid_into_metadata(upload_probe):
    """F1：metadata 里不带 kbaseId 也要 0000（不是 0005）。"""
    client, captured = upload_probe
    response = _upload(client, 'kb-from-query',
                       {'directoryId': 'd1', 'kType': 'document', 'splitType': 'system',
                        'splitOperator': {'md': {'operatorId': -1, 'args': []}}})

    assert response.status_code == 200
    assert captured['metadata']['kbaseId'] == 'kb-from-query'
    assert captured['kbase_id'] == 'kb-from-query'


def test_upload_query_kbaseid_overrides_metadata(upload_probe):
    """同名键并存时**查询参数赢**（无条件 setter 的覆盖语义，不是「缺了才补」）。"""
    client, captured = upload_probe
    response = _upload(client, 'kb-from-query',
                       {'kbaseId': 'kb-in-metadata', 'directoryId': 'd1',
                        'kType': 'document', 'splitType': 'system',
                        'splitOperator': {'md': {'operatorId': -1, 'args': []}}})

    assert response.status_code == 200
    assert captured['metadata']['kbaseId'] == 'kb-from-query'
    assert captured['kbase_id'] == 'kb-from-query'






def test_missing_split_operator_is_npe():
    """``splitOperator`` 整个缺席 → 0001（不是 0005 校验错误）。"""
    with pytest.raises(RuntimeError):
        file_service.require_split_operator({})


def test_operator_check_requires_coverage():
    """切分算子必须覆盖所有扩展名；解析算子齐了则必须有 ``md``。"""
    from shared.errors.api import KbApiError

    with pytest.raises(KbApiError) as caught:
        file_service.operator_check({}, {}, {'txt'})
    assert caught.value.render('zh') == '切分算子选择错误'

    with pytest.raises(KbApiError):
        # 解析算子齐了但切分算子没有 md
        file_service.operator_check({'txt': {}}, {'txt': {}}, {'txt'})

    file_service.operator_check({}, {'txt': {}}, {'txt'})               # 覆盖即可
    file_service.operator_check({'txt': {}}, {'txt': {}, 'md': {}}, {'txt'})


def test_upload_missing_directory_reports_directory_not_exist():
    """上传时目录不存在 → 0005「目录不存在」（``RetCode.directory.not.exist``）。

    metadata 的 directoryId 指向不存在的目录时回 `0005 msg='目录不存在'`；
    不能回 `file.not.exist`（「文件(夹)不存在」）—— 两个键在 properties 里是分开的，别混用。
    """
    from shared.errors.api import KbApiError
    from knowledge_base.service import file_service

    assert file_service._DIRECTORY_MISSING_KEY == 'directory.not.exist'
    error = KbApiError(file_service._DIRECTORY_MISSING_KEY)
    assert error.code == '0005'
    assert error.render('zh') == '目录不存在'
    assert error.render('en') == 'directory not exist'


# ---------------------------------------------------------------------------
# 内容与扩展名一致性（伪造文件类型不校验）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('extension, content', [
    ('pdf', b'MZ\x90\x00\x03\x00\x00\x00'),          # exe 改名 .pdf
    ('docx', b'not a zip at all'),
    ('xlsx', b'MZ\x90\x00'),
    ('pptx', b'%PDF-1.7'),
    ('png', b'GIF89a'),
    ('jpg', b'\xff\xd8'),                            # 少一个 0xFF，不是合法 SOI
])
def test_content_must_match_extension(extension, content):
    """内容魔数与扩展名不符 → 拒绝。以前只看后缀，exe 改名 .pdf 也照收。"""
    assert file_service._content_matches_extension(extension, content) is False


@pytest.mark.parametrize('extension, content', [
    ('pdf', b'%PDF-1.7\n...'),
    ('docx', b'PK\x03\x04rest'),
    ('xlsx', b'PK\x03\x04rest'),
    ('pptx', b'PK\x03\x04rest'),
    ('ofd', b'PK\x03\x04rest'),
    ('png', b'\x89PNG\r\n\x1a\nrest'),
    ('jpg', b'\xff\xd8\xff\xe0rest'),
    ('jpeg', b'\xff\xd8\xff\xe1rest'),
    # 没有魔数的格式一律放行（宁可漏判，不可误拒真实文件）
    ('txt', b'MZ\x90\x00'),
    ('md', b'%PDF-1.7'),
    ('csv', b''),
    ('html', b'<html>'),
    ('json', b'{"a":1}'),
    ('zedx', b'anything'),
])
def test_content_check_allows_valid_and_magicless_formats(extension, content):
    assert file_service._content_matches_extension(extension, content) is True


def test_ofd_upload_is_rejected_as_unsupported_format():
    """OFD 没有解析器（``text_split_service`` 显式拒绝），上传阶段就要拦下。

    以前 ``ofd`` 在 ``FILE_MAX_SIZE_MAP`` 白名单里、解析器里却没有它：用户能
    传上去，切分时才报「不支持的格式」，文档停在「解析失败」。
    """
    from shared.errors.api import KbValidationError

    assert 'ofd' not in file_service.FILE_MAX_SIZE_MAP
    files = [file_service.UploadedFile('a.ofd', b'PK\x03\x04rest')]
    with pytest.raises(KbValidationError) as caught:
        file_service.upload_check(files, 'outer-document')
    assert caught.value.key == 'file.type.validation'


def test_upload_check_rejects_mismatched_content_after_zip_expansion():
    """``upload_check`` 在**展开 zip 之后**逐条判内容 —— 混在好的文件里也要被拦。"""
    from shared.errors.api import KbValidationError

    good = file_service.UploadedFile('a.txt', b'hello world')
    fake = file_service.UploadedFile('b.pdf', b'MZ\x90\x00\x03\x00\x00\x00')
    with pytest.raises(KbValidationError) as caught:
        file_service.upload_check([good, fake], 'outer-document')
    assert caught.value.key == 'file.content.type.mismatch'


# ----------------------------------------------------------------------
# appendFileId：只能指向本库已存在的 32 位 hex 文件
#
# 这个值会被当作落盘路径的最后一段（core/<前4位>/<id>）。放过任意字符串，
# 调用方就能控制磁盘文件名；配合解析链（pdfminer CMap 反序列化）可构成 RCE。
# ----------------------------------------------------------------------
def test_append_file_id_rejects_non_hex_name():
    with pytest.raises(KbValidationError):
        file_service.validate_append_file_id('malicious.pickle.gz', 'kb1')


def test_append_file_id_rejects_missing_file(monkeypatch):
    monkeypatch.setattr(file_service.directory_store, 'get_directory',
                        lambda *args, **kwargs: None)
    with pytest.raises(KbValidationError):
        file_service.validate_append_file_id('a' * 32, 'kb1')


def test_append_file_id_accepts_existing_file(monkeypatch):
    monkeypatch.setattr(file_service.directory_store, 'get_directory',
                        lambda *args, **kwargs: {'id': 'a' * 32})
    file_service.validate_append_file_id('a' * 32, 'kb1')   # 不抛
