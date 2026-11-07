from typing import List, Dict, Any, Optional

from pydantic import BaseModel, Field, validator


class GraphFilter(BaseModel):
    """图查询过滤条件"""
    entity_type: Optional[List[str]] = None
    edge_type: Optional[List[str]] = None
    properties: Optional[Dict[str, Any]] = None

    # 起点查询相关字段
    start_entity_type: Optional[List[str]] = None
    start_entity_properties: Optional[Dict[str, Any]] = None
    start_entity_rid: Optional[str] = None

    # 沿途经过的实体相关字段
    path_entity_type: Optional[List[str]] = None
    path_entity_properties: Optional[Dict[str, Any]] = None

    # 沿途经过的边相关字段
    path_edge_type: Optional[List[str]] = None
    path_edge_properties: Optional[Dict[str, Any]] = None

    @validator('entity_type')
    def validate_entity_type(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError('实体类型数组不能为空')
        return v

    @validator('edge_type')
    def validate_edge_type(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError('关系类型数组不能为空')
        return v

    @validator('start_entity_type')
    def validate_start_entity_type(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError('起点实体类型数组不能为空')
        return v

    @validator('path_entity_type')
    def validate_path_entity_type(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError('沿途实体类型数组不能为空')
        return v

    @validator('path_edge_type')
    def validate_path_edge_type(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError('沿途边类型数组不能为空')
        return v


class GraphQueryDto(BaseModel):
    """图查询请求DTO"""
    kb_id: str = Field(..., description="知识库ID")
    query_type: str = Field(..., description="查询类型：entity, edge, path, sub_graph")
    filters: Optional[List[GraphFilter]] = Field(default=[], description="过滤条件列表")
    depth: Optional[int] = Field(default=10, ge=1, le=100, description="查询深度限制")
    direction: Optional[str] = Field(default="both", description="查询方向：in, out, both")
    limit: Optional[int] = Field(default=100, ge=1, le=5000, description="返回结果数量限制（边）")
    offset: Optional[int] = Field(default=0, ge=0, description="分页偏移量")
    cursor: Optional[str] = Field(default=None, description="游标分页的游标值（边的@rid）")
    prioritize_levels: Optional[bool] = Field(
        default=False, description="检索场景：按 BFS 层级优先返回边，并只带返回边的端点顶点")

    @validator('query_type')
    def validate_query_type(cls, v):
        valid_types = ['entity', 'edge', 'path', 'sub_graph']
        if v not in valid_types:
            raise ValueError(f'查询类型必须是以下之一：{", ".join(valid_types)}')
        return v

    @validator('direction')
    def validate_direction(cls, v):
        if v not in ['in', 'out', 'both']:
            raise ValueError('方向必须是in、out或both')
        return v

    @validator('depth')
    def validate_depth(cls, v):
        if v < 1 or v > 100:
            raise ValueError('深度必须在1-100之间')
        return v

    @validator('filters')
    def validate_filters(cls, v):
        if not isinstance(v, list):
            raise ValueError('过滤条件必须是列表格式')
        return v

    def to_json(self):
        """转换为JSON格式"""
        return self.dict()
