# Brief 工序模板 — claude_md（Agent 主 Spec）

> 槽位原料: spec-assembler.yaml（assembly_order 8 章）+ matching-decision v2（物化条款）

## 生成工序（6 步）

1. **frontmatter**: name / description(SF-6) / 按 spec-assembler 模板变量填 automation_level 等
2. **身份与边界**: 一句话职责 + 编排角色（single 或 multi_agent 的 Leader）；触及 Role & Boundaries
   【自查】与 build_type_decision.type 一致?（single 不写 SubAgent 调度节）
3. **安全约束节**: 物化 CD2/CD3——禁止操作清单逐条（含违反判定）+ 知识边界条款（CD3: 禁裸判断+引用行号协议）
4. **工具策略节**: 物化 IT1——"先 Read/先调用再下结论"硬条款（如适用）
5. **执行流程节**: 物化 W1/SM1——步骤或状态机；IH3 审批节点（如选）
   【自查】materializes 每条决策在这三节中有落点?
6. **错误处理**: 关键失败路径显式行为（阻断/重试/升级），禁止静默吞错

## 落点规则

根 `CLAUDE.md`。格式: spec-assembler.yaml 的 assembly_order（8 章）。

## 自样例

同 build 仅一个 claude_md；spec-assembler 为标准，无自样例需求。
