# build-plan（vector-kb-skill 过程锚）

> 外部启发锚（derived）——本包源自外部参照库 golden-examples 的
> milvus-rag-skill 蒸馏重塑（详见 manifest provenance）。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼
> path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按资产实际
> 字面量书写（R6 双锚约定）。

---
plan_id: golden-vector-kb-skill-anchor
plan_version: "1.0"
mode: greenfield
generated_at: "2026-10-17"
selected_patterns: [K3-KB-Backed]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| K3-KB-Backed | SKILL.md, scripts/check_env.py, scripts/kb_builder.py, scripts/insert_data.py, references/retrieval.md |
```

# files

```yaml
path: SKILL.md
type: skill
brief: 用户自备向量库凭据的知识库支撑技能——意图→集合预设创建→文档切块入库→检索引用的全链路; 集成契约位 = VECTOR_DB_URI/TOKEN + OPENAI_API_KEY 用户凭据接口。
deps: []
read_first: []
materializes: [K3-KB-Backed]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "集成契约位 = 用户自备凭据"}
  - {type: content_contains, value: "VECTOR_DB_URI"}
  - {type: content_contains, value: "check_env.py"}
  - {type: content_contains, value: "预设场景"}
acceptance:
  - 用户凭据接口位显式声明（URI/token/Embedding 密钥三件套, 禁硬编码）
  - 环境检测 fail-closed（不满足即非零退出, 不静默跳过）
  - 预设场景表固定（text_search / rag）且字段配置写明
anti_patterns: [凭据硬编码; 环境检测静默跳过; 检索结果不带原文引用]
```

```yaml
path: scripts/check_env.py
type: script
brief: 环境检测——Python 版本 / 客户端包可导入 / 服务可连通 / Embedding 密钥在位; 逐项 PASS/FAIL 打印, 任一失败非零退出。
deps: [SKILL.md]
read_first: [SKILL.md]
materializes: [K3-KB-Backed]
invariants:
  - {type: content_contains, value: "sys.exit(1)"}
  - {type: content_contains, value: "CHECKS"}
acceptance:
  - fail-closed: 失败项计数非零即退出码 1
anti_patterns: [检测失败仍退出 0; 异常裸吞]
```

```yaml
path: scripts/kb_builder.py
type: script
brief: 集合构建器骨架——凭据契约位（env 注入, 缺省回退本地地址）→ create_from_preset/create_from_intent → init_embedding（密钥缺失显式抛错）→ embed_and_insert 批量写入接入位。
deps: [SKILL.md]
read_first: [SKILL.md]
materializes: [K3-KB-Backed]
invariants:
  - {type: content_contains, value: "class VectorCollectionBuilder"}
  - {type: content_contains, value: "create_from_preset"}
  - {type: content_contains, value: "init_embedding"}
  - {type: content_contains, value: "embed_and_insert"}
acceptance:
  - 骨架占位处明标"实现位", 不冒充完整实现
  - 密钥缺失 raise 显式报错（fail-closed）
anti_patterns: [静默返回空结果; 凭据默认值硬编码进源码]
```

```yaml
path: scripts/insert_data.py
type: script
brief: 数据入库骨架——滑窗切块（500/50）→ embed_and_insert → 写入计数回执; 命令行入口带用法提示。
deps: [scripts/kb_builder.py]
read_first: [scripts/kb_builder.py]
materializes: [K3-KB-Backed]
invariants:
  - {type: content_contains, value: "CHUNK_SIZE = 500"}
  - {type: content_contains, value: "chunk_text"}
acceptance:
  - 切块参数具名常量, 非魔法数散落
anti_patterns: [魔法数; 缺用法提示]
```

```yaml
path: references/retrieval.md
type: reference
brief: 检索用法与引用返回契约——每条结果必带 text/score/source 三字段; 凭据边界（只读, 禁硬编码）。
deps: [scripts/kb_builder.py]
read_first: [SKILL.md]
materializes: [K3-KB-Backed]
invariants:
  - {type: content_contains, value: "text"}
  - {type: content_contains, value: "score"}
  - {type: content_contains, value: "source"}
acceptance:
  - 引用三字段契约表完整（原文逐字 / 相似度 / 来源标记）
anti_patterns: [检索结果无来源标记]
```
