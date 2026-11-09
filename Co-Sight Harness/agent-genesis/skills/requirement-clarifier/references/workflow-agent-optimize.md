# agent-optimize 模式 Workflow — Requirement Clarifier L3（FC 新增）

> 加载者: mode=agent-optimize 命中后由 L2 SKILL.md 派发
> 上游: harness-create SKILL.md §第 1.5 步 optimize 维度（fast-only, 裁定 6）
> 输出 schema: 同 agent 模式（clarified-agent.schema.yaml, optimize 形态填充——见下）
> 防三重拷贝: 三形态分流协议以 `docs/plan/fast-lane-implementation.md` §4.2b 为权威,
> 本文件是其澄清段实例化, 不复制判据数值

## 职责

把三种优化输入收敛为 clarified-agent-requirements.yaml 的 **optimize 形态**:
`why/what/how` 各维填方向语义, `acceptance_criteria` 填点名清单可验证形态,
frontmatter 增 `optimize_target`（目标 Agent 路径）与 `change_list`（点名文件, ≤2）。

## 三输入形态分流（对应用户输入判定, 语义理解非关键词匹配）

### 形态① 用户提议方向（"把 X 改成 Y" / "调 Z 阈值"）

直取方向 → 追问点名清单（改哪些文件; 用户说不清时对照目标目录文件列表给推荐）→
一次确认（D 编号格式, 带推荐答案）→ 收敛落盘。

### 形态② 用户提供 trace（session JSONL 路径）

本 Skill 无派发权——**回报 main agent 派 trace-analyzer**（agents/trace-analyzer.md:
只诊断不动手）→ 诊断落 `{work_dir}/fast-lane/trace-diagnosis.md` → 本 Skill Read 诊断的
「候选优化方向 + 建议点名清单」→ AskUserQuestion 请用户确认/修改方向与点名 → 收敛。
诊断建议点名 >3 → 如实告知超 fast 判据, 去处 create 重建/手动。

### 形态③ 仅"要优化"（无方向无 trace）

现状描摹确认循环:
1. 回报 main agent 派既有 **readiness-verifier** 对目标出证据（零新件; 输入目标路径）
2. Read 证据报告 → 按 10 项信号推荐 1-2 个最值方向（每个: 一句话 + 预期收益 + 点名建议）
3. AskUserQuestion 一次（带推荐答案; 用户可全拒）→ 追问一次仍无方向 →
   如实输出"暂无可收敛的优化点"（status: blocked）终止——**不硬造方向**

## 收敛产物契约（optimize 形态特有字段）

clarified-agent-requirements.yaml 在 agent 模式 schema 上追加:

```yaml
optimize_target: output/agents/{name}/v1/   # 或用户指明路径
change_list: [<文件相对路径>, ...]           # ≤2; = check-delta-scope allowlist 源
direction: <一句话方向描述>
```

`acceptance_criteria` 每条 then 必须可静态验证（改后文件含 X / 阈值为 Y）——
G028 后测与人工抽检的对照基准。

## 完成状态协议

同 L2 共享（完成/有顾虑/阻止/缺上下文）; 形态③ blocked 是合法终态（不硬造）。
dc010_channel: fast 车道忽略（同 L2 规则, 落盘但不消费）。

## 失败回路

- 形态② trace 非 Claude Code JSONL → 显式"暂不支持该格式"（禁硬解析）, 请用户换格式或改形态①
- 目标 Agent 路径不存在 → BLOCKED 报路径问题
- 点名 >2 或结构变更诉求 → 输出超范围提示与去处（create/手动）, 不落 optimize 形态
