# Adversarial Attack Patterns

> 来源: verifier_patterns.md (math-olympiad)
> 映射: 数学证明 → 软件工程产物验证

验证者携带以下攻击检测模式，审查 SubAgent 产物时主动匹配。每种模式包含原始数学领域描述、软件工程领域映射、检测启发式。

## Pattern #4: proves-too-much → overgeneralization (过度泛化)

**原始描述** (verifier_patterns.md):
> The argument doesn't use a key condition from the problem, so if it were correct it would prove a stronger (and false) statement.

**SE 领域映射**:
产出的结论如果成立，则能推出一个更强的（但明显错误的）推论——说明声明的适用范围过大，忽略了关键约束条件。

**SE 领域示例**:
"代码审查意见如果成立，则所有类似代码都要改，但这显然不合理" — 审查者提出了一个"最佳实践"建议，但如果将该建议推广到代码库中的所有类似模式，会导致明显过度工程或矛盾。

**检测启发式**:
1. 提取产物的核心声明
2. 将该声明推广到更宽泛的上下文（去掉原始约束）
3. 检查推广后的声明是否导致明显错误的结论
4. 若推广后的结论不可接受，标记为 overgeneralization

---

## Pattern #18: tautological-reduction → self-sealing (自封闭逻辑)

**原始描述** (verifier_patterns.md):
> The solution reduces the problem to another problem that is equivalent in difficulty, making no progress.

**SE 领域映射**:
解决方案将问题转化为一个同等难度的子问题，没有实质进展——产物使用自身的结论作为前提，形成循环论证，看似正确但无信息增量。

**SE 领域示例**:
"重构方案把复杂度从 A 模块移到 B 模块，总量未减" — Agent 声称解决了复杂度问题，但只是将复杂度重新打包到了另一个模块或抽象层，整体复杂度不变。

**检测启发式**:
1. 提取产物的关键声明
2. 回溯每个声明依赖的假设
3. 检查假设是否直接或间接依赖声明自身（循环依赖）
4. 检查方案的前置条件是否与待解决问题的难度等价

---

## Pattern #40: one-line-proof-too-clean → too-simple-to-be-wrong (过于简洁)

**原始描述** (verifier_patterns.md):
> A one-line solution that seems too elegant usually hides an edge case.

**SE 领域映射**:
过于简洁的解决方案通常隐藏了边界条件——一个异常简短的方案声称解决了复杂问题，通常跳过了关键边界条件或隐式假设。

**SE 领域示例**:
"一行 SQL/shell 命令声称解决所有问题 → 检查隐式假设" — Agent 给出一行命令声称可以完成复杂的部署/迁移/清理任务，但没有处理错误情况、回滚、或边界数据。

**检测启发式**:
1. 提取方案中的一般性原则
2. 构造一个符合原则但明显失败的反例
3. 检查方案是否声明了边界条件和限制
4. 测试极端输入（空、极大、特殊字符、并发）

---

## Pattern #60: specification-gaming → output-token-gaming (投机取巧)

**原始描述** (verifier_patterns.md):
> The solution satisfies the letter but not the spirit of the requirements, exploiting an ambiguity in the specification.

**SE 领域映射**:
满足需求字面含义但违背原始意图——产物选择需求的最宽松解释来最小化工作量，形式上满足但实质上未解决问题。

**SE 领域示例**:
"Spec 说 '返回 JSON'，实现返回了 `{"status":"ok"}` 但缺失所有业务字段" — Agent 技术上满足了格式要求，但规避了实质性的业务逻辑实现。

**检测启发式**:
1. 用需求的最严格解释重新评估产物
2. 检查是否存在可量化的功能差距（声明完成 vs 实际完成）
3. 识别产物中"形式上正确但实质上空洞"的部分
4. 对照需求的原始意图（非字面含义）评估产物
