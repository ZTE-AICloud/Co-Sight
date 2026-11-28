"""扫描取值发现：只收「字典」，不收标识与文件名。

背景：扫描曾对所有表的文本列做低基数取值收集，结果是账号名、文件名、UUID
堆进语义目录，而真正被查询的表反而没选。现在候选列由「已启用表 + 已启用列」
限定，判类规则在这里钉住。
"""

from __future__ import annotations

from text_to_sql.scanner import _IDENTIFIER_COLUMN, _classify


def test_normal_dictionary_is_collected_as_low():
    # Arrange / Act
    cardinality, count, values = _classify(None, ['西安市', '咸阳市', '宝鸡市'])

    # Assert
    assert cardinality == 'LOW'
    assert count == 3
    assert values == ('西安市', '咸阳市', '宝鸡市')


def test_identifier_values_are_not_a_dictionary():
    uuids = ['09214ce9-b795-4a0c-a4c5-000000000001',
             '0f1e8f2a-d491-4a4f-80df-000000000002']

    assert _classify(None, uuids)[0] == 'HIGH'
    assert _classify(None, ['a@b.com', 'c@d.com'])[0] == 'HIGH'
    assert _classify(None, ['https://x.test/a'])[0] == 'HIGH'
    # 知识库切片表里的文件名同理：是数据结构，不是业务分类
    assert _classify(None, ['big_zh.md', 'report.docx'])[0] == 'HIGH'


def test_too_many_values_is_high():
    assert _classify(None, [str(index) for index in range(21)])[0] == 'HIGH'
    assert _classify(None, ['x' * 121])[0] == 'HIGH'


def test_unknown_when_sampling_failed():
    assert _classify(None, None) == ('UNKNOWN', None, ())


def test_identifier_columns_never_profile():
    for name in ('id', 'order_id', 'user_uuid', 'api_key', 'agent_api_key',
                 'password', 'email', 'file_path', 'avatar_url'):
        assert _IDENTIFIER_COLUMN.search(name), name
    for name in ('status', 'city_name', 'order_status', 'source', 'type'):
        assert not _IDENTIFIER_COLUMN.search(name), name
