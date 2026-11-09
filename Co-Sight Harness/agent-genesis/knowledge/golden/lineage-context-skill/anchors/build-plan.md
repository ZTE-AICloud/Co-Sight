# build-plan（lineage-context-skill 过程锚）

> 外部启发锚（derived: true）——本包源自外部参照库
> zilliztech/claude-context（MIT）重塑: 旧词汇已重映射为本仓库现行模式
> 词汇, 身份已消毒（源仓名/品牌/真实端点不进入交付物）, provenance 见
> manifest.yaml。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼
> path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按资产实际
> 字面量书写（R6 双锚约定）。

---
plan_id: golden-lineage-context-skill-anchor
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-17"
selected_patterns: [DP1-Traceable-Lineage, K3-KB-Backed]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| DP1-Traceable-Lineage | SKILL.md, templates/env.example |
| K3-KB-Backed | SKILL.md, templates/env.example |
```

# files

```yaml
path: SKILL.md
type: skill
brief: 可溯源语义上下文管线 Skill——切分→嵌入→入向量库→检索→组装五段, lineage 五元组（路径/行区间/语言/分值）切分段生成一次后续只透传, 检索结果 100% 带出处, 用户自备嵌入凭据+向量库端点（环境变量契约, 启动校验 fail-closed）, Merkle 指纹增量同步。
deps: []
read_first: []
materializes: [DP1-Traceable-Lineage, K3-KB-Backed]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "启动校验清单（fail-closed, 缺一不可）"}
  - {type: content_contains, value: "管线五段"}
  - {type: content_contains, value: "Merkle"}
  - {type: content_contains, value: "绝不部分执行"}
  - {type: content_contains, value: "禁入最终上下文"}
  - {type: content_contains, value: "templates/env.example"}
acceptance:
  - lineage 五元组切分段生成一次、后续段禁改写, 纪律明文化
  - 启动校验 fail-closed 条款在场（缺凭据/探活失败即拒, 无降级跑通）
  - 凭据禁入产物与日志的明令在场
  - Merkle 增量同步与删除检测条款在场
anti_patterns: [无出处内容块; 凭据硬编码; 缺环境变量降级跑通; 全库重嵌入同步]
```

```yaml
path: templates/env.example
type: template
brief: 用户自备凭据环境变量契约模板——嵌入服务段（四选一注释约定）+ 向量库端点段 + 切分段配置; 占位值视为未设, 禁真实凭据入库。
deps: [SKILL.md]
read_first: [SKILL.md]
materializes: [K3-KB-Backed]
invariants:
  - {type: content_contains, value: "EMBEDDING_PROVIDER"}
  - {type: content_contains, value: "VECTOR_DB_ADDRESS"}
  - {type: content_contains, value: "VECTOR_DB_TOKEN"}
  - {type: content_contains, value: "SPLITTER_TYPE"}
acceptance:
  - 嵌入服务商段四选一且注释约定清晰, 向量库段地址+令牌两件齐
anti_patterns: [真实凭据入库; 服务商段全部解开无选择约定]
```
