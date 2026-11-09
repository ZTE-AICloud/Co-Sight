# build-plan（mcp-bridge-router 过程锚, derived）

> derived: true——外部启发过程锚（源自 oh-my-claudecode 路由分发切片重塑）,
> 非真实构建产物。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼
> path; invariants 按改造后资产实际字面量书写（R6 双锚约定）。

---
plan_id: golden-mcp-bridge-router-anchor
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-17"
selected_patterns: [W2-Router]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| W2-Router | CLAUDE.md, prompts/dispatch.instruction.md, prompts/verify.instruction.md |
```

# files

```yaml
path: CLAUDE.md
type: agent_entry
brief: 关键词路由 + 工具桥接 Agent 运行时入口——路由表/回退推断/委派编目/外部工具接口位/文件状态交接/执行协议/Not for。
deps: []
read_first: []
materializes: [W2-Router]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "关键词路由表"}
  - {type: content_contains, value: "回退推断规则"}
  - {type: content_contains, value: "外部工具桥接（用户自备接口位）"}
  - {type: content_contains, value: "state/status.yaml"}
  - {type: content_contains, value: "不自我批准"}
  - {type: content_contains, value: "dispatch.instruction.md"}
  - {type: content_contains, value: "verify.instruction.md"}
acceptance:
  - 关键词路由表触发词为用户原话词汇, 新增流程=路由表登记一行+指令文件
  - 外部工具为用户自备接口位, 包内不绑定任何具体供应方
  - 声明完成前必须经独立核验通道
anti_patterns: [路由表写语义猜测而非查表, 桥接层硬编码外部供应方凭据]
```

```yaml
path: prompts/dispatch.instruction.md
type: prompt_file
brief: 委派执行通道——角色选择/状态登记/证据优先/并行派发/便签流转/自证禁区/交接摘要产出。
deps: [CLAUDE.md]
read_first: [CLAUDE.md]
materializes: [W2-Router]
invariants:
  - {type: content_contains, value: "状态登记"}
  - {type: content_contains, value: "证据优先"}
  - {type: content_contains, value: "自证禁区"}
  - {type: content_contains, value: "交接摘要"}
acceptance:
  - 执行步骤含状态登记与便签流转, 中断可续
  - 只产出声称完成, 声明权在 verify 通道
anti_patterns: [执行通道内自我宣布完成]
```

```yaml
path: prompts/verify.instruction.md
type: prompt_file
brief: 独立核验通道——交接摘要读取/规模定层/证据核对/迭代门/通过准则/核验证据产出。
deps: [CLAUDE.md]
read_first: [CLAUDE.md]
materializes: [W2-Router]
invariants:
  - {type: content_contains, value: "证据核对"}
  - {type: content_contains, value: "迭代门"}
  - {type: content_contains, value: "同一活跃上下文不得既执行又核验"}
acceptance:
  - 证据不足即 FAIL, 不接受表面成立
  - 核验证据是唯一完成声明凭据
anti_patterns: [核验通道复用执行结论代替独立核对]
```
