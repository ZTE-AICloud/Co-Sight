"""图片能力已整体退役。

本测试锁定五件事，防止能力被改名复活或漏删：

1. ``operators/omni_image`` 模块与 ``-3`` 注册项不存在；
2. 系统算子注册表不再声明任何图片格式；
3. 上传白名单不含 ``jpg`` / ``jpeg`` / ``png``（文档库与图谱库）；
4. 解析层不引用图片模块；
5. 前端文件选择器与文案不再列出图片。

不提供数据迁移脚本；存量图片文件保留在库中，但不再接受新上传。
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / 'backend' / 'src'

IMAGE_FORMATS = ('png', 'jpg', 'jpeg')


def test_omni_image_operator_is_gone():
    from operators.service import system_operator

    assert not (SRC / 'operators' / 'omni_image').exists()

    items = system_operator._load_registry()
    assert [item['id'] for item in items] == [-1, -2]
    assert all(item['operator_module'] != 'operators/omni_image' for item in items)
    for item in items:
        assert set(item['supportedFormat']).isdisjoint(IMAGE_FORMATS)

    assert system_operator.matching_system_operators('png', 'text_split') == []


def test_upload_whitelist_has_no_image_formats(monkeypatch):
    from knowledge_base.service import file_service

    monkeypatch.setenv('MEM_LIMIT', '1024')
    monkeypatch.setattr(file_service, '_custom_operator_formats', lambda: set())

    for category in (1, 10):
        sizes = file_service.file_size_limit(category)['maxSizeMap']
        assert set(sizes).isdisjoint(IMAGE_FORMATS), category

    for k_type in ('outer-document', 'graph-document'):
        assert file_service._allowed_formats_for(k_type).isdisjoint(IMAGE_FORMATS)


def test_parser_does_not_reference_removed_image_modules():
    removed_files = (
        SRC / 'parsing' / 'parsers' / 'docx_tool' / 'word_img_tool.py',
        SRC / 'parsing' / 'parsers' / 'html_tool' / 'html_img_tool.py',
        SRC / 'parsing' / 'common' / 'replace_img_tool.py',
        SRC / 'parsing' / 'common' / 'img_tool.py',
    )
    for path in removed_files:
        assert not path.exists(), f'图片模块仍在：{path.relative_to(REPO)}'

    offenders = []
    for path in sorted(SRC.rglob('*.py')):
        text = path.read_text(encoding='utf-8')
        for needle in ('omni_image', 'word_img_tool', 'html_img_tool', 'replace_img_tool', 'img_tool'):
            if needle in text:
                offenders.append(f'{path.relative_to(REPO)}: {needle}')
    assert offenders == [], f'仍有图片模块引用：{offenders}'


def test_message_key_removed():
    from shared.i18n.messages import MESSAGES

    assert 'RetCode.operator.split.image.no_model' not in MESSAGES


def test_frontend_does_not_offer_image_extensions():
    frontend = REPO / 'frontend' / 'src'
    for relative in ('features/knowledge-base/lib/knowledge-files.js',
                     'features/knowledge-base/lib/quick-create.ts'):
        limits = (frontend / relative).read_text(encoding='utf-8')
        for fmt in IMAGE_FORMATS:
            assert f"'{fmt}'" not in limits, relative

    for locale in ('zh', 'en'):
        kb_text = (frontend / 'app' / 'i18n' / locale / 'kb.js').read_text(encoding='utf-8')
        assert 'imageSplitPrompt' not in kb_text
        assert 'multimodalLlm' not in kb_text

        chat_text = (frontend / 'app' / 'i18n' / locale / 'chatTest.js').read_text(encoding='utf-8')
        assert 'addImage' not in chat_text
        assert 'imageNotConnected' not in chat_text
