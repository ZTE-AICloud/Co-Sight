"""切分算子的落盘文件名收敛。

``fileName`` 来自上传请求，可能带绝对路径或 ``..``。校验发生在落盘之前，但落盘
这一层仍要独立收敛 —— 任何新增调用点都不该依赖上游校验。
"""

import pytest

from ingestion.service.operator.text_split_service import safe_file_name


@pytest.mark.parametrize('raw, expected', [
    ('/app/src/main.py', 'main.py'),
    ('../../etc/passwd', 'passwd'),
    ('C:\\Windows\\evil.md', 'evil.md'),
    ('..', 'clean_file.md'),
    ('', 'clean_file.md'),
    (None, 'clean_file.md'),
    ('正常文件名.docx', '正常文件名.docx'),
])
def test_safe_file_name_always_returns_one_component(raw, expected):
    assert safe_file_name(raw, 'md') == expected
