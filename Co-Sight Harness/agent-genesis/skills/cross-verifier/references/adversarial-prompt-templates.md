# Adversarial Prompt Templates

> 来源: adversarial_prompts.md (math-olympiad)
> 映射: 数学证明攻击prompt → 软件工程产物攻击prompt

验证者使用以下攻击 prompt 对 SubAgent 产物进行压力测试。每个模板针对不同的攻击面，所有模板使用统一的标准化输出格式。

## 标准化输出格式

```yaml
VERDICT: PASS | FAIL
CONFIDENCE: 0-100
ISSUE: "具体问题描述" (仅 FAIL 时)
```

---

## Template 1: Logical Gap Detection (逻辑漏洞检测)

**攻击面**: 产物中的推理跳跃——从前提直接跳到结论，中间缺少必要的推理步骤。

**Prompt**:
```
You are an adversarial verifier. Your task is to find logical gaps in the following 
artifact. A logical gap occurs when the artifact asserts a conclusion without 
providing the necessary intermediate reasoning steps, or when a step in the 
reasoning chain does not logically follow from the previous step.

For each gap found, identify:
- The specific claim that lacks support
- What intermediate step is missing
- Why the gap is significant (what could go wrong if the missing step is incorrect)

Artifact to verify:
---
{artifact_content}
---

Output your findings in the standardized format.
```

**SE 使用场景**: 验证 Agent 生成的架构决策、代码重构方案、或技术方案中是否存在推理跳跃。例如：Agent 声称"使用微服务架构可以解决性能问题"但未解释因果关系。

---

## Template 2: Hidden Assumption Detection (隐藏假设检测)

**攻击面**: 产物中未被声明的隐式前提——如果这些前提不成立，整个结论将崩溃。

**Prompt**:
```
You are an adversarial verifier. Your task is to identify hidden assumptions in 
the following artifact. A hidden assumption is a premise that the artifact 
depends on but does not explicitly state. If the assumption is false, the 
artifact's conclusions become invalid.

For each hidden assumption found, identify:
- The assumption itself (stated clearly)
- Which part of the artifact depends on it
- Under what conditions the assumption would be false
- The impact on the artifact's correctness if the assumption fails

Artifact to verify:
---
{artifact_content}
---

Output your findings in the standardized format.
```

**SE 使用场景**: 验证 Agent 生成的部署方案、环境配置、或依赖声明中是否存在未声明的环境假设。例如：Agent 的部署脚本假设目标机器已安装特定版本的运行时。

---

## Template 3: Calculation Verification (计算验证)

**攻击面**: 产物中的数值计算、资源估算、或性能预测——检查计算是否正确，假设是否合理。

**Prompt**:
```
You are an adversarial verifier. Your task is to verify all calculations, 
estimates, and numerical claims in the following artifact. Check for:
- Arithmetic errors
- Unit mismatches or conversion errors
- Unreasonable assumptions in estimates
- Missing factors that would significantly change the result

For each issue found, identify:
- The specific calculation or estimate that is wrong
- The nature of the error
- The corrected calculation or a range of plausible correct values

Artifact to verify:
---
{artifact_content}
---

Output your findings in the standardized format.
```

**SE 使用场景**: 验证 Agent 生成的容量规划、性能预估、资源配额计算等。例如：Agent 估算"需要 2GB 内存"但未考虑峰值负载。

---

## Template 4: Edge Case Enumeration (边界条件枚举)

**攻击面**: 产物未覆盖的边界条件——空输入、极大值、并发冲突、网络故障等。

**Prompt**:
```
You are an adversarial verifier. Your task is to enumerate edge cases that the 
following artifact fails to handle. Consider:
- Boundary values (empty, zero, max, min)
- Concurrent or interleaved execution
- Failure modes (network down, disk full, timeout)
- Invalid or malformed inputs
- State inconsistencies (partially completed operations)

For each edge case found, identify:
- The edge case scenario
- Which part of the artifact fails under this scenario
- The expected behavior vs. the artifact's actual behavior
- Severity of the failure

Artifact to verify:
---
{artifact_content}
---

Output your findings in the standardized format.
```

**SE 使用场景**: 验证 Agent 生成的代码实现、API 设计、或工作流定义。例如：Agent 的文件处理逻辑未处理二进制文件或编码异常。

---

## Template 5: Counterexample Construction (反例构造)

**攻击面**: 产物中的通用声明——如果存在一个反例，声明即被证伪。

**Prompt**:
```
You are an adversarial verifier. Your task is to construct counterexamples 
that disprove claims made in the following artifact. For any general statement 
or universal claim, try to find a specific case where the claim does not hold.

For each counterexample found, identify:
- The specific claim being challenged
- The counterexample (concrete and specific)
- Why the counterexample invalidates the claim
- Whether the claim can be salvaged by narrowing its scope

Artifact to verify:
---
{artifact_content}
---

Output your findings in the standardized format.
```

**SE 使用场景**: 验证 Agent 生成的编码规范、最佳实践声明、或通用设计原则。例如：Agent 声称"所有 API 都应使用 RESTful 风格"——WebSocket 和 gRPC 是有效反例。

---

## Template 6: Scope Creep Detection (范围膨胀检测)

**攻击面**: 产物是否超出了需求范围——做了未被要求的工作，引入了不必要的复杂度。

**Prompt**:
```
You are an adversarial verifier. Your task is to detect scope creep in the 
following artifact. Scope creep occurs when the artifact includes features, 
considerations, or complexity that is not required by the original specification. 
While these additions might seem valuable, they introduce risk, maintenance 
burden, and divert focus from core requirements.

For each instance of scope creep found, identify:
- The out-of-scope content
- Which requirement it allegedly addresses (or if it addresses none)
- The cost of including it (complexity, risk, maintenance)
- Whether it should be deferred to a future iteration

Artifact to verify:
---
{artifact_content}
---
Original requirements:
---
{requirements}
---

Output your findings in the standardized format.
```

**SE 使用场景**: 验证 Agent 生成的实现方案是否精准匹配需求。例如：需求只要求"用户列表页面"，Agent 额外增加了"导出 PDF"和"批量操作"功能。

---

## Template 7: Specification Ambiguity Detection (规格歧义检测)

**攻击面**: 产物是否利用了需求规格中的歧义——选择最省力的解释而非最合理的解释。

**Prompt**:
```
You are an adversarial verifier. Your task is to detect specification ambiguity 
exploitation in the following artifact. This occurs when the artifact interprets 
an ambiguous requirement in the way that minimizes implementation effort, rather 
than the way that best serves the requirement's intent.

For each instance found, identify:
- The ambiguous requirement (exact wording)
- The interpretation chosen by the artifact
- Alternative interpretations that would require more work but better serve the intent
- The gap between what was implemented and what was likely intended

Artifact to verify:
---
{artifact_content}
---
Original requirements:
---
{requirements}
---

Output your findings in the standardized format.
```

**SE 使用场景**: 验证 Agent 生成的实现是否真正满足需求意图。例如：需求说"支持数据导出"，Agent 实现了 CSV 导出但用户实际需要的是带格式的 Excel 报表。
