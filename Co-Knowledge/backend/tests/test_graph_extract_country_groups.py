"""通用抽图算子的确定性国家分组（不调 LLM）。"""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / 'deploy/operators/general-graph-extract/graph_extract.py'


def _load_operator():
    operator_api = types.ModuleType('operator_api')
    graph = types.ModuleType('operator_api.graph')
    graph.GraphChecker = type('GraphChecker', (), {})
    llm = types.ModuleType('operator_api.llm')
    llm.invoke_llm = lambda **kwargs: ''
    sys.modules.setdefault('operator_api', operator_api)
    sys.modules.setdefault('operator_api.graph', graph)
    sys.modules.setdefault('operator_api.llm', llm)
    spec = importlib.util.spec_from_file_location('general_graph_extract', OPERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_country_groups_add_canonical_edges_once():
    module = _load_operator()
    entities = [
        {'entity_id': 'Entity_1', 'entity_type': 'Entity',
         'properties': {'entity_name': 'East Germany', 'chunk_id': 'c1'}},
        {'entity_id': 'Entity_2', 'entity_type': 'Entity',
         'properties': {'entity_name': 'Puerto Rico', 'chunk_id': 'c2'}},
    ]
    edges = []
    names = {'East Germany': 'Entity_1', 'Puerto Rico': 'Entity_2'}

    eid, edge_id = module._augment_country_groups(
        entities, edges, names, 3, 1, lambda text: text)
    # 幂等：第二次不应重复加边
    eid, edge_id = module._augment_country_groups(
        entities, edges, names, eid, edge_id, lambda text: text)

    by_name = {entity['properties']['entity_name']: entity
               for entity in entities}
    assert by_name['Germany']['entity_id'] in names.values()
    assert by_name['United States']['entity_id'] in names.values()
    assert len([edge for edge in edges
                if edge['properties']['relationship_keywords'] == 'country_group']) == 2
    assert names['Germany'] == by_name['Germany']['entity_id']
    assert names['United States'] == by_name['United States']['entity_id']
