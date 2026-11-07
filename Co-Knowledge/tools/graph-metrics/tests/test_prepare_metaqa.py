"""数据转换单测：输入格式、关系映射、导入包结构都钉死。"""
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prepare_metaqa import (  # noqa: E402
    ENTITY_TYPE,
    build_schema,
    build_zip,
    parse_kb,
    parse_questions,
    relation_to_type,
    strip_brackets,
)


def test_relation_to_type_pascal_case_letters_only():
    assert relation_to_type('directed_by') == 'DirectedBy'
    assert relation_to_type('starred_actors') == 'StarredActors'
    assert relation_to_type('has_imdb_rating') == 'HasImdbRating'
    with pytest.raises(ValueError):
        relation_to_type('has-imdb')


def test_parse_kb_rejects_wrong_field_count(tmp_path):
    path = tmp_path / 'kb.txt'
    path.write_text('Kismet|directed_by|William Dieterle\n', encoding='utf-8')
    assert parse_kb(path) == [('Kismet', 'directed_by', 'William Dieterle')]

    path.write_text('Kismet|directed_by\n', encoding='utf-8')
    with pytest.raises(ValueError, match='3 个字段'):
        parse_kb(path)


def test_parse_questions_keeps_topic_and_multi_answers(tmp_path):
    path = tmp_path / 'qa_test.txt'
    path.write_text(
        '[Joe Thomas] appears in which movies\tThe Inbetweeners Movie|The Inbetweeners 2\n'
        'what does [Helen Mack] star in\tThe Son of Kong\n',
        encoding='utf-8')
    rows = parse_questions(path, '1-hop')
    assert rows[0]['topic'] == 'Joe Thomas'
    assert rows[0]['answers'] == ['The Inbetweeners Movie', 'The Inbetweeners 2']
    assert rows[1]['answers'] == ['The Son of Kong']
    assert rows[0]['qid'] == '1-hop-1'


def test_strip_brackets_keeps_entity_text():
    assert strip_brackets('[Joe Thomas] appears in which movies') == \
        'Joe Thomas appears in which movies'


def test_build_schema_has_one_entity_type_and_letter_edge_types():
    schema = build_schema(['directed_by', 'starred_actors'])
    assert [entity['entity_type'] for entity in schema['entities']] == [ENTITY_TYPE]
    assert {edge['edge_type'] for edge in schema['edges']} == \
        {'DirectedBy', 'StarredActors'}
    for edge in schema['edges']:
        assert edge['source_entity'] == edge['target_entity'] == ENTITY_TYPE


def test_build_zip_roundtrip(tmp_path):
    out = tmp_path / 'metaqa.zip'
    triples = [
        ('Kismet', 'directed_by', 'William Dieterle'),
        ('Kismet', 'starred_actors', 'Marlene Dietrich'),
        ('Kismet', 'starred_actors', 'Edward Arnold'),
    ]
    stats = build_zip(out, triples, kb_name='kb', embedding='emb',
                      kbase_id='graph_0123456789abcdef')
    assert stats['entities'] == 4
    assert stats['edges'] == 3
    assert stats['edge_types'] == ['DirectedBy', 'StarredActors']

    with zipfile.ZipFile(out) as archive:
        assert set(archive.namelist()) == {
            'desc.json', 'schema.json', 'entities.jsonl', 'edges.jsonl'}
        desc = json.loads(archive.read('desc.json'))
        schema = json.loads(archive.read('schema.json'))
        entities = [json.loads(line) for line in
                    archive.read('entities.jsonl').decode().splitlines()]
        edges = [json.loads(line) for line in
                 archive.read('edges.jsonl').decode().splitlines()]

    assert desc == {'name': 'kb', 'id': 'graph_0123456789abcdef',
                    'embedding': 'emb',
                    'desc': 'MetaQA benchmark: 3 triples / 4 entities'}
    assert schema['entities'][0]['properties'][0]['is_primary'] is True
    assert [entity['entity_id'] for entity in entities] == sorted(
        ['Kismet', 'William Dieterle', 'Marlene Dietrich', 'Edward Arnold'])
    assert edges[0]['edge_id'] == 'r1'
    assert edges[0]['edge_type'] == 'DirectedBy'
    assert edges[0]['properties'] == {}
