# build-plan（command-router 过程锚, derived）

> derived: true——外部启发过程锚（源自 gacui-claude 重塑）, 非真实构建产物。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼 path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按改造后资产实际字面量书写（R6 双锚约定）。

---
plan_id: golden-command-router-anchor
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-16"
selected_patterns: [W2-Router]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| W2-Router | CLAUDE.md, prompts/ask.instruction.md, prompts/investigate.instruction.md, prompts/kb.instruction.md |
```

# files

```yaml
path: CLAUDE.md
type: agent_entry
brief: 关键词路由 Agent 运行时入口——首词路由表 + 启发式回退 + 指令文件分离协议 + 语音输入检测（可选）+ Not for。
deps: []
read_first: []
materializes: [W2-Router]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "首词路由表"}
  - {type: content_contains, value: "启发式回退推断"}
  - {type: content_contains, value: "指令文件完全分离"}
  - {type: content_contains, value: "ask.instruction.md"}
  - {type: content_contains, value: "investigate.instruction.md"}
  - {type: content_contains, value: "kb.instruction.md"}
acceptance:
  - 首词路由表触发词用用户原话词汇, 不用内部术语
  - 回退推断规则 IF-THEN 格式, 特异性从高到低
  - Not for 段声明状态传递与超 8 目标两个边界
anti_patterns: [路由表写语义猜测而非查表]
```

```yaml
path: prompts/ask.instruction.md
type: doc
brief: 研究/问答指令文件——分析不改码 + 先读后答 + 不确定性边界声明。
deps: [CLAUDE.md]
read_first: [CLAUDE.md]
materializes: [W2-Router]
invariants:
  - {type: content_contains, value: "# ask — 研究/问答指令"}
  - {type: content_contains, value: "不要修改任何源码"}
acceptance:
  - 指令自包含可独立执行, 不引用其他指令文件路径
anti_patterns: [指令间互相引用形成隐式耦合]
```

```yaml
path: prompts/investigate.instruction.md
type: doc
brief: 调查/编码指令文件——四步识别+构造+复现+方案, 验证标记 CONFIRMED/DENIED, 每步落盘支持断点恢复。
deps: [CLAUDE.md]
read_first: [CLAUDE.md]
materializes: [W2-Router]
invariants:
  - {type: content_contains, value: "# investigate — 调查/编码指令"}
  - {type: content_contains, value: "CONFIRMED / DENIED"}
  - {type: content_contains, value: "断点恢复"}
acceptance:
  - 六步序列完整, 验证步有通过/不通过两分支
anti_patterns: [无验证步的一次性执行]
```

```yaml
path: prompts/kb.instruction.md
type: doc
brief: 知识库维护指令文件——学习文件统一格式（!!!LEARNING!!! 头/Orders 索引/Refinements 正文）+ 四步提取流程 + 项目/通用分层。
deps: [CLAUDE.md]
read_first: [CLAUDE.md]
materializes: [W2-Router]
invariants:
  - {type: content_contains, value: "# kb — 知识库维护指令"}
  - {type: content_contains, value: "# !!!LEARNING!!!"}
  - {type: content_contains, value: "# Orders"}
  - {type: content_contains, value: "# Refinements"}
acceptance:
  - 学习文件三段格式完整; 项目特有与通用分层规则各一条
anti_patterns: [项目经验写入通用学习文件]
```
