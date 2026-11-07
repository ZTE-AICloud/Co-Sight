"""绑定基名 → 物理向量表维度（画布校验用）。

这一层是「模型名字能解析」之外的**第二道判据**：名字对了但维度和库里的向量表
对不上，检索仍然必然出错。维度真值只能读物理列 —— ``kb_storage_registry``
对图谱导入的库会缺行（实测），不能当唯一来源。
"""

from knowledge_base import kbase_dimensions

from infrastructure.db import ddl


def test_dimensions_for_appends_the_vector_suffix_and_keeps_the_canvas_name(monkeypatch):
    looked_up = []

    def fake_vector_dimension(table_name):
        looked_up.append(table_name)
        return {'graph_abc_vector': 1024, 'doc_def_vector': 768}.get(table_name)

    monkeypatch.setattr(ddl, 'vector_dimension', fake_vector_dimension)

    dimensions = kbase_dimensions.dimensions_for(['graph_abc', 'doc_def', 'doc_missing'])

    # 键是**画布上的原名**（校验按它匹配），查表用 ``<基名>_vector``
    assert dimensions == {'graph_abc': 1024, 'doc_def': 768}
    assert looked_up == ['graph_abc_vector', 'doc_def_vector', 'doc_missing_vector']


def test_dimensions_for_strips_the_scope_suffix_before_looking_up(monkeypatch):
    monkeypatch.setattr(ddl, 'vector_dimension',
                        lambda table_name: 1024 if table_name == 'graph_abc_vector' else None)

    assert kbase_dimensions.dimensions_for(['graph_abc|#|dev']) == {'graph_abc|#|dev': 1024}


def test_dimensions_for_tolerates_names_already_carrying_the_suffix(monkeypatch):
    monkeypatch.setattr(ddl, 'vector_dimension', lambda table_name: 1024)

    dimensions = kbase_dimensions.dimensions_for(['doc_abc_vector'])

    assert dimensions == {'doc_abc_vector': 1024}


def test_dimensions_for_skips_empty_and_duplicate_names(monkeypatch):
    calls = []
    monkeypatch.setattr(ddl, 'vector_dimension',
                        lambda table_name: calls.append(table_name) or 1024)

    dimensions = kbase_dimensions.dimensions_for(['graph_abc', '', None, 'graph_abc'])

    assert dimensions == {'graph_abc': 1024}
    assert calls == ['graph_abc_vector']


def test_parse_vector_dimension_reads_the_pgvector_type():
    assert ddl.parse_vector_dimension('vector(1024)') == 1024
    assert ddl.parse_vector_dimension('vector(1792)') == 1792
    assert ddl.parse_vector_dimension('vector') is None
    assert ddl.parse_vector_dimension('') is None
    assert ddl.parse_vector_dimension(None) is None
