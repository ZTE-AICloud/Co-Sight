import json
from typing import Any, Dict, List

from pydantic import BaseModel


class Property(BaseModel):
    """图存储属性定义（名称 / 说明 / 类型）。"""

    name: str
    desc: str = ''
    type: str


class Entity(BaseModel):
    """顶点类定义。"""

    entity_type: str
    index_keys: List[str] = []
    properties: List[Property] = []


class Edge(BaseModel):
    """边类定义。"""

    edge_type: str
    index_keys: List[str] = []
    properties: List[Property] = []


class GraphStruct(BaseModel):
    """图谱结构（``/graph/create`` 上传的 JSON）。

    字段名与 JSON 形态沿用既有的属性图模型，在仓库内定义，不依赖外部 SDK。
    """

    graph_id: str = ''
    graph_name: str
    graph_desc: str = ''
    entities: List[Entity] = []
    edges: List[Edge] = []

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GraphStruct':
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> 'GraphStruct':
        return cls.model_validate_json(json_str)


class EntityData:
    """实体数据结构"""

    def __init__(self, entity_id: str, entity_type: str, properties: Dict[str, Any]):
        self.entity_id = entity_id
        self.entity_type = entity_type
        self.properties = properties

    @classmethod
    def from_json(cls, json_str: str) -> 'EntityData':
        """从 entities.jsonl 的一行反序列化。"""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {str(e)}") from e
        return cls(entity_id=data.get('entity_id'),
                   entity_type=data.get('entity_type'),
                   properties=data.get('properties') or {})


class EdgeData:
    """边数据结构"""

    def __init__(self, edge_id: str, edge_type: str, source_id: str, target_id: str, properties: Dict[str, Any]):
        self.edge_id = edge_id
        self.edge_type = edge_type
        self.source_id = source_id
        self.target_id = target_id
        self.properties = properties

    @classmethod
    def from_json(cls, json_str: str) -> 'EdgeData':
        """从 edges.jsonl 的一行反序列化。"""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {str(e)}") from e
        return cls(edge_id=data.get('edge_id'),
                   edge_type=data.get('edge_type'),
                   source_id=data.get('source_id'),
                   target_id=data.get('target_id'),
                   properties=data.get('properties') or {})