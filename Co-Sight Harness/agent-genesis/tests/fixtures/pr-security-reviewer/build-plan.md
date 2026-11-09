---
plan_id: pr-security-reviewer-build-plan
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-05T03:52:00Z"
basis:
  - {path: clarified-agent-requirements.yaml, verdict: pass}
  - {path: phase1-matching-decision.md, verdict: pass}
  - {path: phase2-review.md, verdict: pass}
selected_patterns: [W1, G1, K1, DT1, DF1, IH1, IT1, CD1, CD2]
---

# Build Plan v2 — pr-security-reviewer

## 决策物化表（绑定后，增量形态）

```yaml
materialization:
  - {pattern_id: W1, target_files: [CLAUDE.md, phase/02-workflows/phase-1-security-scan.md]}
  - {pattern_id: G1, target_files: [.claude/agents/security-reviewer.md, phase/02-workflows/phase-1-security-scan.md]}
  - {pattern_id: K1, target_files: [CLAUDE.md]}
  - {pattern_id: DT1, target_files: [phase/02-workflows/phase-1-security-scan.md, .claude/agents/security-reviewer.md]}
  - {pattern_id: DF1, target_files: [.claude/schemas/security-findings.schema.json, .claude/agents/security-reviewer.md]}
  - {pattern_id: IH1, target_files: [phase/02-workflows/phase-1-security-scan.md]}
  - {pattern_id: IT1, target_files: [CLAUDE.md]}
  - {pattern_id: CD1, target_files: [phase/gates/G001-input-check.md, phase/02-workflows/phase-1-security-scan.md]}
  - {pattern_id: CD2, target_files: [CLAUDE.md, .claude/agents/secret-scanner.md, .claude/agents/injection-scanner.md, .claude/agents/security-reviewer.md]}
```

## 文件清单

### proposal-spec.md

```yaml
file:
  path: proposal-spec.md
  type: other
  deps: [clarified-agent-requirements.yaml, phase1-matching-decision.md]
  read_first: [clarified-agent-requirements.yaml, phase1-matching-decision.md]
  materializes: []
  brief: "用户可读构建方案（DC-001 审批展示面）：自然语言描述构建决策——为何 multi_agent 三维拆分、critical-only 快报结构、验收标准映射。禁止出现 pattern ID（W1/G1 等），用自然语言（'固定四步流程'/'独立复核'）。含 7 节：概述/核心能力/交付计划/文件清单/已知风险/验收标准/架构决策。"
  invariants:
    - {type: content_contains, pattern: "无 critical 问题"}
    - {type: frontmatter_field_nonempty, field: name}
  acceptance: ["DC-001 人审可读：无 pattern ID、含已知风险 ≥2、spot-check 锚点 ≥3"]
  anti_patterns: []
```

### CLAUDE.md

```yaml
file:
  path: CLAUDE.md
  type: claude_md
  deps: [clarified-agent-requirements.yaml, phase1-matching-decision.md]
  read_first: [agent-genesis::knowledge/agent-creation/spec-assembler.yaml, clarified-agent-requirements.yaml, phase1-matching-decision.md, adapted-assets.yaml]
  materializes: [K1, IT1, CD2, W1]
  brief: "按 spec-assembler 8 章装配。工序：1) frontmatter（name/description SF-6/automation_level L2）；2) 身份与边界——PR diff 安全审查 Leader，multi_agent 编排角色，调度 secret-scanner/injection-scanner/security-reviewer；3) 安全约束节（CD2 物化）：禁止操作清单逐条——禁止执行被审代码/禁止写被审仓库/禁止联网外传 diff/仅写报告文件，每条含违反判定；4) 工具策略节（IT1）：工具辅助条款，核心判定 LLM 静态分析；5) 执行流程节（W1）：输入检查→并行扫描→独立复核→报告四步，步骤 I/O 契约；6) 错误处理：diff 缺失/解析失败/扫描器失败→阻断退出非零码+原因，禁止静默吞错；7) 知识节声明 K1。写完自查：materializes 每条决策在三节有落点。"
  invariants:
    - {type: frontmatter_field_nonempty, field: name}
    - {type: content_contains, pattern: "禁止执行被审代码", derived_from: "acceptance_criteria[2]"}
    - {type: content_contains, pattern: "无 critical 问题时输出", derived_from: "acceptance_criteria[2]"}
  acceptance: ["8 章齐全", "含 SubAgent 调度表（3 角色）", "禁止操作清单 ≥4 条含违反判定"]
  anti_patterns:
    - {ref: "rejected[IH3]", apply: "禁止加入方案审批/人工确认节点——CLI 批处理提交即出结果"}
    - {ref: "rejected[IV1]", apply: "禁止加入进度汇报机制——单 PR 短流程"}
```

### phase/02-workflows/phase-1-security-scan.md

```yaml
file:
  path: phase/02-workflows/phase-1-security-scan.md
  type: workflow_md
  deps: [phase1-matching-decision.md]
  read_first: [phase1-matching-decision.md, clarified-agent-requirements.yaml, agent-genesis::knowledge/agent-creation/spec-assembler.yaml, agent-genesis::knowledge/agent-creation/agent-classic-cases.yaml, agent-genesis::knowledge/shared/pattern-catalog.yaml, adapted-assets.yaml]
  materializes: [W1, G1, DT1, CD1, DF1, IH1]
  brief: "核心扫描工作流（W1 四步）：Step1 输入检查（CD1：diff 存在/非空/≤5MB/可解析，失败即阻断报错）；Step2 并行扫描（secret-scanner + injection-scanner 同阶段并行，各自只读 diff 产出 findings.json）；Step3 独立复核（G1：security-reviewer 校验 critical 判定+DF1 schema 校验，误判→打回对应扫描器修正→重审≤2轮，超限阻断）；Step4 结构化报告（合并 reviewed-findings，按 security-findings.schema.json 输出 critical 快报；空发现时输出明确「无 critical 问题」结论）。每步声明输入/输出/失败回退（circuit_breaker max_retries）。写完自查：步骤 I/O 闭合无悬空、回压循环有上限。"
  invariants:
    - {type: content_contains, pattern: "重审≤2轮", derived_from: "acceptance_criteria[0]"}
    - {type: content_contains, pattern: "无 critical 问题", derived_from: "acceptance_criteria[2]"}
    - {type: content_contains, pattern: "diff"}
  acceptance: ["4 步齐全且 I/O 闭合", "含 G1 回压协议", "空发现路径有明确结论输出"]
  anti_patterns:
    - {ref: "rejected[W2]", apply: "禁止按 diff 类型分流——所有 diff 走同一扫描流程"}
    - {ref: "rejected[W4]", apply: "禁止运行时动态派生扫描器——三维度构建时固定"}
```

### .claude/agents/secret-scanner.md

```yaml
file:
  path: .claude/agents/secret-scanner.md
  type: subagent
  deps: [adapted-assets.yaml]
  read_first: [agent-genesis::knowledge/agent-creation/subagent-template.md, clarified-agent-requirements.yaml, adapted-assets.yaml]
  materializes: [CD2, DT1]
  brief: "工序：1) frontmatter——name=secret-scanner，description 按 SF-6（做什么+何时触发+输入 diff+输出 findings.json），tools [Read,Grep,Write]，context_isolation: required，forbidden_inputs 逐项点名（其他扫描器输出/security-reviewer 结论/被审仓库写路径），maxTurns 20；2) 职责节：密钥硬编码维度扫描，只做静态文本分析（CD2），不参与复核/汇总；3) 禁止读取节逐条附原因；4) 执行流程：读 diff→按密钥模式清单（AWS AKIA/Slack xoxb/PEM 头/连接串口令）逐模式 grep→每条命中判 critical→写 findings.json（符合 security-findings.schema.json）→自查四字段齐全；5) 注意节红线：不执行被审代码、不报非密钥类问题。写完自查：description 四要素、forbidden_inputs 到文件名、I/O 闭合。"
  invariants:
    - {type: frontmatter_field_nonempty, field: name}
    - {type: frontmatter_field_nonempty, field: forbidden_inputs}
    - {type: content_contains, pattern: "AKIA", derived_from: "acceptance_criteria[0]"}
  acceptance: ["frontmatter 契约齐全", "密钥模式清单 ≥4 类", "输出契约为 schema 合规 findings"]
  anti_patterns:
    - {ref: "rejected[CD3]", apply: "禁止声称引用外部权威密钥库——判定依据为内嵌模式清单"}
```

### .claude/agents/injection-scanner.md

```yaml
file:
  path: .claude/agents/injection-scanner.md
  type: subagent
  deps: [adapted-assets.yaml]
  read_first: [agent-genesis::knowledge/agent-creation/subagent-template.md, clarified-agent-requirements.yaml, adapted-assets.yaml]
  materializes: [CD2, DT1]
  brief: "工序同 secret-scanner 同构：frontmatter（name=injection-scanner，maxTurns 20，forbidden_inputs 同隔离集）；职责限定注入维度（SQL 字符串拼接/exec/eval/system/用户输入直插命令），critical-only；执行流程：读 diff→按注入特征清单逐特征检查→命中判级（拼接 SQL 直触 critical）→写 findings.json→自查。注意节红线同 CD2。写完自查同 secret-scanner。"
  invariants:
    - {type: frontmatter_field_nonempty, field: name}
    - {type: content_contains, pattern: "SQL", derived_from: "acceptance_criteria[1]"}
    - {type: content_contains, pattern: "字符串拼接", derived_from: "acceptance_criteria[1]"}
  acceptance: ["frontmatter 契约齐全", "注入特征清单 ≥4 类", "输出契约为 schema 合规 findings"]
  anti_patterns:
    - {ref: "rejected[K4]", apply: "禁止依赖外部规则表——特征清单内嵌于职责节"}
```

### .claude/agents/security-reviewer.md

```yaml
file:
  path: .claude/agents/security-reviewer.md
  type: subagent
  deps: [adapted-assets.yaml]
  read_first: [agent-genesis::knowledge/agent-creation/subagent-template.md, knowledge/assets/agent-definitions/critic.md, adapted-assets.yaml]
  materializes: [G1, DF1, CD2, DT1]
  brief: "asset_adapt from critic.md（对抗审查骨架）。工序：1) frontmatter——name=security-reviewer，tools 审查类不含 Edit（CD2 落实），forbidden_inputs：原始 diff 之外的三扫描器中间推理文件/被审仓库；2) 职责节：独立复核三维 findings 的 critical 判定（G1 game——你只看到扫描结论，看不到扫描器推理），校验每条符合 security-findings.schema.json（DF1），误判打回来源扫描器；3) 执行流程：读 findings→逐条复核（证据是否真实存在于 diff 位置/critical 判定是否成立/修复建议是否可行）→通过则汇总 reviewed-findings→不通过标注打回原因→重审≤2轮超限阻断上报；4) 注意节：不自审扫描器、不修改 diff、空 findings 时确认「无 critical 问题」结论合规。写完自查：forbidden_inputs 双向隔离（与扫描器互不可见中间推理）。"
  invariants:
    - {type: frontmatter_field_nonempty, field: forbidden_inputs}
    - {type: content_contains, pattern: "重审≤2轮"}
    - {type: content_contains, pattern: "无 critical 问题", derived_from: "acceptance_criteria[2]"}
  acceptance: ["G1 回压协议完整", "DF1 校验职责明确", "双向 forbidden_inputs 隔离"]
  anti_patterns:
    - {ref: "rejected[IH2]", apply: "禁止向用户追问——复核结论由判定规则给出，不交互"}
```

### .claude/schemas/security-findings.schema.json

```yaml
file:
  path: .claude/schemas/security-findings.schema.json
  type: schema
  deps: []
  read_first: [clarified-agent-requirements.yaml]
  materializes: [DF1]
  brief: "工序：1) $schema 声明（draft-07）+ properties：dimension（enum: secrets|injection|dangerous_config）/severity（enum: critical 单值冻结）/location（文件+行号）/evidence（diff 原文片段）/fix（修复建议），五字段全 required；2) 与报告格式术语对齐（dimension 枚举与扫描器职责节用词一致）；3) 样例对照 schemas/runtime-eval.schema.yaml 结构惯例（仅内部对照，禁止写进产物）。写完自查：json.load 可解析、$schema 存在、required 含四业务字段（G023 json_schema_valid 机检）。落点 .claude/schemas/（多消费者：三扫描器+reviewer+报告步骤）。"
  invariants:
    - {type: json_schema_valid}
    - {type: content_contains, pattern: '"location"', derived_from: "acceptance_criteria[0]"}
    - {type: content_contains, pattern: '"fix"', derived_from: "acceptance_criteria[0]"}
  acceptance: ["json_schema_valid 通过", "required=[dimension,severity,location,evidence,fix]"]
  anti_patterns: []
```

### phase/gates/G001-input-check.md

```yaml
file:
  path: phase/gates/G001-input-check.md
  type: other
  deps: [clarified-agent-requirements.yaml]
  read_first: [clarified-agent-requirements.yaml, agent-genesis::knowledge/agent-creation/agent-classic-cases.yaml, adapted-assets.yaml]
  materializes: [CD1]
  brief: "输入门禁（CD1）：检查清单=diff 文件存在/非空/≤5MB/git diff 格式可解析（含 +++/--- 头）；任一不满足→阻断+明确报错+非零退出，不产出部分报告（exception_flow 语义）。含 gate 元数据（condition_check, blocking: true, retry_count: 0——输入问题重试无意义）。"
  invariants:
    - {type: content_contains, pattern: "blocking: true"}
    - {type: content_contains, pattern: "非零退出", derived_from: "acceptance_criteria[2]"}
  acceptance: ["检查项 ≥4", "失败行为=阻断而非猜测"]
  anti_patterns:
    - {ref: "rejected[W2]", apply: "禁止对异常输入路由到其他路径——一律阻断"}
```

### phase/gates/G003-readiness-score.md

```yaml
file:
  path: phase/gates/G003-readiness-score.md
  type: other
  generation: template
  source: assets/templates/gates/G003-readiness-score.md
  deps: []
  read_first: []
  materializes: []
  brief: "manifest 默认 gate（runner.assets 模板物化）：condition_check readiness_score >= 58，blocking: true，retry_count: 3（与 workflow 失败回退协同，超限 circuit_breaker 升级）。含评分四维说明（正确性/完整性/格式/可操作性）。"
  invariants:
    - {type: content_contains, pattern: "readiness_score >= 58"}
  acceptance: ["condition 与 manifest 默认值一致"]
  anti_patterns: []
```

### phase/gates/G005-no-placeholders.md

```yaml
file:
  path: phase/gates/G005-no-placeholders.md
  type: other
  generation: template
  source: assets/templates/gates/G005-no-placeholders.md
  deps: []
  read_first: []
  materializes: []
  brief: "manifest 默认 gate（runner.assets 模板物化）：condition_check placeholder_count == 0（TODO/TBD/{{}}/待补充），blocking: true，retry_count: 3。含占位符清单与扫描范围（全部产物 md/json）。"
  invariants:
    - {type: content_contains, pattern: "placeholder_count == 0"}
  acceptance: ["condition 与 manifest 默认值一致"]
  anti_patterns: []
```

### phase/gates/gates.yaml

```yaml
file:
  path: phase/gates/gates.yaml
  type: gates_yaml
  deps: []
  read_first: [agent-genesis::knowledge/agent-creation/agent-output-standard.yaml]
  materializes: []
  brief: "gate-framework 配置：① 无自定义 gate 脚本（内置 G003/G005 由 defaults.fallback_gates 自动生效，不写入）；② trigger 映射——每 step 一条（step_id + on_failure + context）：input-check→阻断/scan→回退修正≤2/ review→重审≤2/ report→重试≤3；③ defaults 固定 fallback_gates: [output-exists]。内置 gate ID 不写入本文件。"
  invariants:
    - {type: content_contains, pattern: "fallback_gates"}
  acceptance: ["trigger 映射覆盖 4 步", "defaults 固定", "无内置 gate ID 混入"]
  anti_patterns: []
```

### phase/review/matching-decision-review.md

```yaml
file:
  path: phase/review/matching-decision-review.md
  type: rule
  generation: copy
  source: phase/review/matching-decision-review.md
  deps: []
  read_first: []
  materializes: []
  brief: "agent-output-standard 默认审查规则，REPO_ROOT 模板确定性直拷（g025），跳过 G014 语义检查，G009/G023 照查。"
  invariants:
    - {type: file_reference_exists}
  acceptance: ["与源文件逐字一致"]
  anti_patterns: []
```

### .claude/rules/*.md（6 个通用规则）

```yaml
file:
  path: .claude/rules/{anti-patterns,durable-context,skill-routing,coding-style,security,testing}.md
  type: rule
  generation: copy
  source: knowledge/assets/rules/{同名}.md
  deps: []
  read_first: []
  materializes: [K1]
  brief: "manifest 固定 7 通用规则中的 6 个 .md，确定性直拷（g025）：anti-patterns/durable-context/skill-routing/coding-style/security/testing。逐字拷贝，无适配（generic_copy）。"
  invariants:
    - {type: file_reference_exists}
  acceptance: ["6 文件与源逐字一致"]
  anti_patterns: []
```

### .claude/hooks/hooks.json

```yaml
file:
  path: .claude/hooks/hooks.json
  type: other
  generation: copy
  source: knowledge/assets/gates/hooks-config.json
  deps: []
  read_first: []
  materializes: [DF1, IT1]
  brief: "hook 配置模板整包直拷（Step 3 已核对：无 command 外部脚本引用，整包=单文件，无缺包）。落点 .claude/hooks/hooks.json。g025 直拷，跳过 G014。"
  invariants:
    - {type: file_reference_exists}
  acceptance: ["JSON 可解析", "与源逐字一致"]
  anti_patterns: []
```

### .claude/settings.json

```yaml
file:
  path: .claude/settings.json
  type: settings
  generation: template
  source: assets/templates/settings/settings.json.template
  deps: []
  read_first: [agent-genesis::knowledge/agent-creation/agent-classic-cases.yaml, adapted-assets.yaml]
  materializes: []
  brief: "Claude Code 项目设置（runner.assets 模板物化）：permissionMode default + 工具白名单（Read/Grep/Glob/Write 限报告目录）落实 CD2 写范围限定。JSON 合法。"
  invariants:
    - {type: json_schema_valid}
  acceptance: ["JSON 可解析", "写权限收窄到报告目录"]
  anti_patterns: []
```

### evaluation/pass-criteria.md

```yaml
file:
  path: evaluation/pass-criteria.md
  type: test
  deps: [clarified-agent-requirements.yaml]
  read_first: [clarified-agent-requirements.yaml, agent-genesis::knowledge/agent-creation/agent-classic-cases.yaml, adapted-assets.yaml]
  materializes: []
  brief: "通过标准：三条 acceptance_criteria 的 given-when-then 逐条转为可执行判据（含 planted 样本：AKIA 密钥 diff/SQL 拼接 diff/干净 diff 三个 fixture 描述）；readiness ≥58 门槛；placeholder==0。供 Step 5 readiness-verifier 与 Step 6 product-tester 消费。"
  invariants:
    - {type: content_contains, pattern: "given", derived_from: "acceptance_criteria[0]"}
    - {type: content_contains, pattern: "planted", derived_from: "acceptance_criteria[0]"}
  acceptance: ["3 条判据全覆盖 acceptance_criteria", "含 3 个 planted fixture 描述"]
  anti_patterns: []
```

## 全局生成约束

- 产物内禁止引用插件内部裸路径（knowledge/、schemas/、design/、agents/ 无前缀形式）；schema 语义一律经 `.claude/schemas/` 副本
- copy/template 条目（generation: copy/template）由 g025 确定性直拷/模板物化，executor 不进入 LLM 生成循环，跳过 G014
- produced_by: clarifier 条目（proposal.md）仅存在性校验，不生成内容
- 三 subagent 数量与角色 ≡ matching-decision v2 build_type_decision.subagents（不增不减）
- 0 skill（结构决策），不生成 .claude/skills/ 目录——与 manifest 默认「≥1 skill」的偏差已在 human-review 已知风险标注

## 执行方式

- executor 断点恢复：progress.json 按文件粒度 skip done / retry failed
- 每文件生成后跑 per-file gate（G009 containment / G014 语义（copy 跳过）/ G023 存在性）
- per-file FAIL → ≤2 轮局部修复 → 仍失败标 failed[] 继续（既有语义，P2 之前不改）
- 全部完成后 G003 + G005 批次 gate，产物含 verification-report.md

cross_checks:
  reference_closure: true
  isolation_bidirectional: true
