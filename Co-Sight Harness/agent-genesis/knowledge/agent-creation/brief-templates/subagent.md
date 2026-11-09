# Brief 工序模板 — subagent（SubAgent 定义）

> 槽位原料: subagent-template.md「本厂增补」节 + 「最小合规样例」节
> 前置约束: 数量与角色必须 ≡ matching-decision v2 build_type_decision.subagents（绑定不改增减）

## 生成工序（5 步，逐段写完自查）

1. **frontmatter**: name(=文件名，kebab-case) / description(**SF-6 四要素**: 做什么+何时触发+输入+输出) /
   tools(**必含 Write**; 审查类不含 Write/Edit 即 CD2 落实) / context_isolation: required /
   forbidden_inputs(逐项点名具体文件) / model(默认 sonnet) / maxTurns / effort
   【自查】description 四要素齐? forbidden_inputs 非空且到文件名?
2. **「职责」节**: 一句话角色 + 边界声明句（盲评/审查类必须"你不参与…过程。你只能看到…"）
   【自查】materializes 里每个决策在此节或流程节有语义落点?
3. **「禁止读取」节**: 逐条列 forbidden_inputs 并各附一句"为什么不能读"
4. **「执行流程」节**: 编号 Step 1-N，每步 输入→动作→输出 可追；把 brief 中物化机制
   （如 CD3 引用行号协议 / IT1 先读后判 / G1 输出契约）写进步骤内容而非脚注
   【自查】步骤间 I/O 闭合? 无"魔法步骤"?
5. **「注意」节**: 该角色红线（不自审/不评分/不扩大修改范围）

## 落点规则

`.claude/agents/{name}.md`（Claude Code 官方约定；**废止 `.claude/subagents/`**）。
文件名=name，跨文件引用（其他 agent 的 forbidden_inputs / workflow 调度表）同名同义。

## 自样例

同 build 中首个 subagent 生成后，后续 subagent 与其保持同构；subagent-template.md 样例已读过可跳过。
