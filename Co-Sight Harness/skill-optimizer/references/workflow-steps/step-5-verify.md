# Step 5: Verify(验证)— 静态检查假设是否站得住

> **对应 debug-pro Step 5**:确认根因,假说错则回 Step 3。
>
> **能力边界**:LLM 无法真实跑评测 — 此步只能做**静态逻辑检查**(读 diff 文本 + 跨 rounds 对比),不能验证「mod 应用后分数是否真提升」(真实评测由下一轮 orchestrator 跑)。

## 目标
在落盘 mod 前,用 4 道静态检查过滤掉"假设错的 mod"。

## 必做动作(每条 mod 在落盘前必过 4 道**静态**检查)

### 检查 1: 失败证据存在

此 mod 修复的 case 在清单中某份 diff 报告的第 N 段确实有 gold vs LLM 输出差异吗?
(读 diff 文本核实,并记下是哪份报告)

### 检查 2: 根因匹配

假设的失败模式(M1-M7)和 diff_notes 五维评分对得上吗?(纯文本比对)

### 检查 3: mod ↔ 历史一致性(来自 Step 4)

历史 rounds diff 中是否已有类似 mod 改过同类 case?效果如何?(跨 rounds 对比)

### 检查 4: 副作用预测

`non_target_cases_risk` 评估 — 这个 mod 会不会误伤 Step 2 识别的「稳定满分 case」?(基于 diff 文本推断)

## 硬约束

- **任一检查不过** → 回到 Step 3 重写假设,**禁止**直接进入 Step 6
- **所有检查通过** → 进入 Step 6 落盘 mod
- ❌ **禁止**用 Step 5 的 4 道检查替代真实评测 — Step 5 只过滤假设错的,真实分数涨跌留给下一轮 orchestrator

## 失败处理

如某 mod 4 道检查有任一不过 → 在 `_plan_summary.md` 标注 `rejected: <reason>`,不进 Step 6 落盘。