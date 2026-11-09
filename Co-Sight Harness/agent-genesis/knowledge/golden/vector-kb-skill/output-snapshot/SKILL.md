---
name: vector-kb-skill
version: "1.0"
description: 用户自备向量库凭据的知识库支撑技能。用自然语言创建向量集合（文本语义搜索 / RAG 知识库两种预设场景），完成文档切块、向量生成、写入与检索。当用户要建向量知识库、文档搜索、语义检索、RAG 系统、FAQ 问答时使用。需要用户提供：向量库连接地址与访问令牌（或本地服务）、Embedding 服务 API Key（兼容 OpenAI 接口）。
---

# Vector KB Skill — 向量知识库支撑技能

用一句话创建向量集合并完成知识入库与检索，无需关心底层向量库概念。
本技能的**集成契约位 = 用户自备凭据**：向量库连接（URI + token）与
Embedding 服务密钥均由使用方提供，技能只负责编排。

## 前置条件

### 1. 安装依赖

```bash
pip install -U pymilvus openai python-dotenv
```

### 2. 准备用户凭据（集成契约位，必配）

```bash
# 向量库连接——远程服务（用户提供）
export VECTOR_DB_URI="https://your-vector-db-endpoint"
export VECTOR_DB_TOKEN="your-access-token"
# 或本地服务（默认回退）
#   本地默认地址 localhost:19530, 无 token

# Embedding 服务（用户提供, 兼容 OpenAI 接口）
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://your-endpoint/v1"   # 可选, 兼容服务必填
```

### 3. 环境检测

```bash
cd <技能目录> && python3 scripts/check_env.py
```

检测项（任一不满足即 fail-closed 报出，不静默跳过）：
- Python 版本 ≥ 3.9
- 向量库客户端包可导入
- 向量库服务可连通（凭据有效）
- Embedding 密钥已配置（仅在使用向量生成功能时必需）

## 目录结构

```
<技能目录>/
├── SKILL.md                # 技能说明（本文件）
├── scripts/
│   ├── check_env.py        # 环境检测
│   ├── kb_builder.py       # 集合构建器（预设场景 + 意图解析接入位）
│   └── insert_data.py      # 数据入库（切块 → 向量 → 写入 → 建索引）
└── references/
    └── retrieval.md        # 检索用法与引用返回契约
```

## 执行方式

所有 Python 命令先切到技能目录执行，确保引用本目录代码：

```bash
cd <技能目录> && python3 -c "
from scripts.kb_builder import VectorCollectionBuilder
builder = VectorCollectionBuilder()
result = builder.create_from_preset('my_kb', scene='rag')
print(result['code'])
"
```

## 使用流程

1. **解析意图**: 场景（text_search / rag）、向量维度、字段需求
2. **连通检测**: 跑 `check_env.py`，凭据不齐先回到前置条件第 2 步
3. **创建集合**: `create_from_preset()` 或 `create_from_intent()`
4. **入库（可选）**: `insert_data.py` 文档切块 → 向量生成 → 批量写入 → 建索引
5. **检索**: 见 `references/retrieval.md`——检索结果必须带原文引用与来源标记

## 预设场景

| 场景 | 适用 | 默认字段 | 默认配置 |
|------|------|---------|---------|
| text_search | 文档检索 / 语义搜索 / FAQ | id, content, vector | 余弦相似度, 自动索引 |
| rag | RAG 问答 / 企业知识库 | id, text, metadata, vector | 余弦相似度, 自动索引, 动态字段 |

## 限制（如实声明）

- 不支持多向量字段 / 嵌套字段 / 数组类型
- 不支持分区键与高级索引参数调优
- 本地 Embedding 模型仅用于维度配置，实际向量生成需对应服务
