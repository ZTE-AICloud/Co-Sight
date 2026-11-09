# Examples — AgentGenesis 生成的 Agent 实物

本目录存放 AgentGenesis pipeline 的**预生成产物**，供未安装插件的读者直接 inspect 生成质量。

---

## ⭐ adversarial-test-agent/ — 对抗式测试 Agent（推荐主例子）

**一句话需求**：

> "帮我建一个测试 Agent：给它一个 Python 模块，它生成的测试必须经过一个'变异批评家'的对抗检验——批评家往代码里注入边界翻转、运算符互换这类真实故障，测试拦不住就打回重写，循环到连续 2 轮零漏检才交付，最后给我击杀率报告。"

**为什么这是门面**：这是**真·多 Agent 协同**——不是任务并行，而是博弈：

```
        ┌─────────── 博弈隔离线 ───────────┐
        │                                 │
 test-writer ◀── 存活报告 ── Leader ── 测试代码 ──▶ mutation-critic
 (只见存活者)        (裁判+状态机)      (只见代码)
        │                                 │
        └── 谁都不知道对方的策略 ──────────┘
```

- **W2-FSM**：WRITE→MUTATE→EVALUATE 循环，收敛条件可判定（连续 2 轮 0 存活）
- **G1 博弈机制**：双向 forbidden_inputs 落地，防止"写手-批评家合谋过拟合"
- **SM1 断点**：每轮 round-state.yaml，kill 后从当前轮恢复
- **CD2 沙箱**：变异体只写沙箱副本（脚本层路径强制，已实测拒绝非沙箱目录）
- **IT1**：击杀裁决由 `run_tests.py` 真实跑 pytest 得出，LLM 不"目测"

**引擎已实测**（生成时验证）：变异扫描器在 fixture 上发现 32 个候选点；强断言测试 2/2 击杀变异体；空壳测试 0% 击杀率——对抗机制确实能区分"真测试"和"装饰品测试"。

**自己跑**：

```bash
cd adversarial-test-agent && claude
> 对 tests/fixtures/src/pricing.py 运行对抗测试
# 观察进度行: [round N] kill X/Y (streak=Z) → 收敛 → 审批 → tests/ 落盘 + 报告
```

---

## pr-security-reviewer/ — PR 审查 Agent（轻量例子）

单轮并行扇出（3 个维度 SubAgent 各审各的）+ K4/CD3 防幻觉规则库。适合 30 秒 quickstart 演示，展示"模式匹配决策"（`phase1-matching-decision.md`）。

```bash
cd pr-security-reviewer && claude
> 审查 tests/fixtures/sample-vulnerable.diff
```

---

**两个例子的对照价值**：同一个工厂，两种模式粒度——pr-security-reviewer 的 G1 是"Schema 校验"（轻量），adversarial-test-agent 的 G1 是"实时博弈"（重量）。README 中并列展示，体现 23 模式目录的弹性。
