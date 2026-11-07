"""导入包头部解析单测：id 形态与计数必须和 prepare 的产物一致。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from import_metaqa import read_zip_header  # noqa: E402
from prepare_metaqa import build_zip, make_kbase_id  # noqa: E402


def test_read_zip_header_roundtrip(tmp_path):
    out = tmp_path / 'kb.zip'
    triples = [
        ('Kismet', 'directed_by', 'William Dieterle'),
        ('Kismet', 'starred_actors', 'Marlene Dietrich'),
    ]
    build_zip(out, triples, kb_name='MetaQA', embedding='emb',
              kbase_id='graph_0123456789abcdef')
    desc, schema, first_entity, entity_count, edge_count = read_zip_header(out)
    assert desc['id'] == 'graph_0123456789abcdef'
    assert desc['name'] == 'MetaQA'
    assert desc['embedding'] == 'emb'
    assert first_entity == 'Kismet'          # entities.jsonl 按名字排序
    assert entity_count == 3
    assert edge_count == 2
    assert {edge['edge_type'] for edge in schema['edges']} == \
        {'DirectedBy', 'StarredActors'}


def test_make_kbase_id_matches_import_contract():
    value = make_kbase_id()
    assert value.startswith('graph_')
    assert len(value) == len('graph_') + 16
    int(value[len('graph_'):], 16)            # 必须全是十六进制
