from typing import List, Optional

from pydantic import BaseModel, Field, validator


class GraphRetrieveDto(BaseModel):
    """图检索请求DTO"""
    query: str = Field(..., description="用于检索的自然语言")
    embedding: str = Field(..., description="embedding模型服务名称")
    bases: List[str] = Field(..., description="知识库标识列表")
    seed_k: Optional[int] = Field(default=5, ge=1, le=50, description="种子节点个数")
    depth: Optional[int] = Field(default=1, ge=1, le=10, description="种子节点传播的深度")
    limit: Optional[int] = Field(default=1000, ge=1, le=5000, description="边数预算上限（深图可调大；实体只带返回边端点）")
    score: Optional[float] = Field(default=0.0, ge=0.0, le=1.0, description="种子节点相似性分数（余弦值）过滤阈值")
    labels: Optional[List[str]] = Field(default=None, description="标签列表，用于前置过滤，最多10个字符串标签")

    @validator('query')
    def validate_query(cls, v):
        if not v or not v.strip():
            raise ValueError('查询语句不能为空')
        return v.strip()

    @validator('embedding')
    def validate_embedding(cls, v):
        if not v or not v.strip():
            raise ValueError('embedding模型服务名称不能为空')
        return v.strip()

    @validator('bases')
    def validate_bases(cls, v):
        if not v or len(v) == 0:
            raise ValueError('知识库标识列表不能为空')
        return v

    @validator('seed_k')
    def validate_seed_k(cls, v):
        if v < 1 or v > 50:
            raise ValueError('种子节点个数必须在1-50之间')
        return v

    @validator('depth')
    def validate_depth(cls, v):
        if v < 1 or v > 10:
            raise ValueError('深度必须在1-10之间')
        return v

    @validator('limit')
    def validate_limit(cls, v):
        if v < 1 or v > 5000:
            raise ValueError('返回结果数量限制必须在1-5000之间')
        return v

    @validator('score')
    def validate_score(cls, v):
        if v < 0.0 or v > 1.0:
            raise ValueError('相似性分数阈值必须在0-1之间')
        return v

    @validator('labels')
    def validate_labels(cls, v):
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError('labels必须是列表类型')
        if len(v) > 10:
            raise ValueError('labels列表长度不能超过10个')
        if len(v) == 0:
            return None  # 空列表视为None，不进行过滤
        # 验证每个元素都是字符串类型
        for i, label in enumerate(v):
            if not isinstance(label, str):
                raise ValueError(f'labels列表的第{i+1}个元素必须是字符串类型')
            if not label.strip():
                raise ValueError(f'labels列表的第{i+1}个元素不能为空字符串')
        # 返回去重后的列表（保持顺序）
        seen = set()
        result = []
        for label in v:
            label_stripped = label.strip()
            if label_stripped not in seen:
                seen.add(label_stripped)
                result.append(label_stripped)
        return result if result else None

    def to_json(self):
        """转换为JSON格式"""
        return self.dict()

