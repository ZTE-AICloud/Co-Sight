# build-plan（browser-automation-suite 过程锚）

> 外部启发锚——本包源出 golden-examples 外部参照库（重塑后入库, anchors 标
> derived: true; 重塑记录见 manifest.provenance 与 self-report）。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼
> path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按资产实际
> 字面量书写（R6 双锚约定）。

---
plan_id: golden-browser-automation-suite-anchor
plan_version: "1.0"
mode: greenfield
generated_at: "2026-10-17"
selected_patterns: [W3-MapReduce]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| W3-MapReduce | SKILL.md, scripts/compile-report.mjs, references/research-file-format.md |
```

# files

```yaml
path: SKILL.md
type: skill
brief: 托管浏览器并行研究套件——搜索发现→去重→每目标子代理扇出研究（单文件证据档）→汇聚脚本合并打分报告+CSV; 凭据由用户提供（环境变量注入）; 反幻觉证据锚定。
deps: []
read_first: []
materializes: [W3-MapReduce]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: content_contains, value: "扇出研究 + 汇聚合并"}
  - {type: content_contains, value: "凭据契约"}
  - {type: content_contains, value: "反幻觉规则"}
  - {type: content_contains, value: "scripts/compile-report.mjs"}
acceptance:
  - 流水线 5 步固定顺序（计划→发现→扇出→合成→交付）且禁跳步
  - 扇出子代理单 Bash heredoc 写单目标文件, 禁 Write 工具
  - 单目标失败不阻塞整批, 报告如实列缺失
anti_patterns: [子代理读原始发现 JSON; 手工拼抽取管道; 无据臆断目标画像]
```

```yaml
path: scripts/compile-report.mjs
type: script
brief: 汇聚（reduce）脚本——解析全部单目标 .md（references/research-file-format.md 契约）产出 index.html 打分总表 + results.csv; 零依赖 node。
deps: [references/research-file-format.md]
read_first: [references/research-file-format.md]
materializes: [W3-MapReduce]
invariants:
  - {type: content_contains, value: "compile-report.mjs"}
  - {type: content_contains, value: "results.csv"}
  - {type: content_contains, value: "index.html"}
acceptance:
  - 输入目录无单目标文件时非零退出（fail-closed）
  - CSV 总分降序且逐行转义
anti_patterns: [引入外部依赖; 静默空目录成功]
```

```yaml
path: references/research-file-format.md
type: reference
brief: 单目标研究文件格式契约——YAML 头固定字段 + 三段固定段落; 汇聚脚本按字面解析, 禁改字段名。
deps: []
read_first: []
materializes: [W3-MapReduce]
invariants:
  - {type: content_contains, value: "固定字段"}
  - {type: content_contains, value: "## 证据"}
  - {type: content_contains, value: "## 失败记录"}
acceptance:
  - 字段名与段落顺序声明为冻结契约
anti_patterns: [格式字段可协商; 凭据写入研究文件]
```
