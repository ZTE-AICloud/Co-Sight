# 检索用法与引用返回契约

检索是知识库技能的出口，返回结构必须满足两项契约：

## 1. 检索调用形状

```python
from scripts.kb_builder import VectorCollectionBuilder

builder = VectorCollectionBuilder()
builder.init_embedding()                       # 用户密钥注入
query_vec = builder.embed_text("用户问题")[0]
# 实现位: client.search(collection, query_vec, limit=k, metric="COSINE")
```

## 2. 引用返回契约（K3 货架位验收要点）

每条检索结果必须携带可追溯引用，缺一不可：

| 字段 | 语义 |
|------|------|
| `text` | 命中的原文片段（逐字，禁改写） |
| `score` | 相似度得分（与建集合时度量一致，余弦） |
| `source` | 来源标记（文档路径 / 入库批次） |

## 3. 用户凭据边界

- 检索只读：不写入、不删除集合数据
- 凭据只在环境变量 / 显式传参出现，禁硬编码进任何脚本或文档
