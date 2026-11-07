"""损坏/截断的 OOXML 文件必须报「文件已损坏」，不能报「切分算子执行失败」。

场景：上传的 33.1 MB docx 只有 ZIP 前半段，文件在
``word/media/image1.jpeg`` 中间结束、没有中央目录。python-docx 抛
``PackageNotFoundError: Package not found at ...``；若把它兜底成
``RetCode.operator.split.error``（"切分算子执行失败，请检查算子是否存在问题"），
用户会按提示去查算子 —— 真正该查的是文件本身。

这里钉住 ``parsing.corpus.process_single_file`` 的归类：截断包 → ``ParseCorruptError``，
``message`` 是对外文案键 ``RetCode.operator.split.corrupt``。
"""
import io
import zipfile

import pytest

from parsing.corpus import load_corpus_file
from parsing.exception import ParseCorruptError


def _write_truncated_docx(path):
    """写一个「合法 ZIP 的前半段」：砍掉尾部（含 EOCD），与线上截断包同形。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document/>' * 1000)
    data = buffer.getvalue()
    # 砍掉尾部 120 字节：中央目录与结束记录都没了，is_zipfile() 返回 False。
    assert not zipfile.is_zipfile(io.BytesIO(data[:-120]))
    path.write_bytes(data[:-120])


def test_truncated_docx_raises_parse_corrupt(tmp_path):
    path = tmp_path / 'truncated.docx'
    _write_truncated_docx(path)

    with pytest.raises(ParseCorruptError) as caught:
        load_corpus_file(str(path), str(tmp_path / 'out'), 512, 128)

    assert caught.value.message == 'RetCode.operator.split.corrupt'
    # 诊断信息留在异常字符串里（日志/排障），不外泄到文案键
    assert 'truncated.docx' in str(caught.value)


def test_non_package_error_is_not_misclassified(tmp_path, monkeypatch):
    """与损坏包无关的解析异常必须原样抛出，不能被误报成「文件损坏」。"""
    from parsing import corpus

    class _ExplodingStrategy:
        def process(self, file_path):
            raise ValueError('boom')

    monkeypatch.setitem(corpus.FILE_PARSE_STRATEGIES, 'txt', _ExplodingStrategy())
    path = tmp_path / 'a.txt'
    path.write_text('hello')

    with pytest.raises(ValueError):
        corpus.load_corpus_file(str(path), str(tmp_path / 'out'), 512, 128)
