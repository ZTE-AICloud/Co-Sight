# 重构后检查 ① — Skill 完整性验证(SK-S1 ~ SK-S11)

> **来源**:AgentGenesis-Code `rules/shared/verification-checks.md` §Skill 验证 段
> **用途**:重构完成后,**对修改后的 Skill 跑一遍 10 项静态验证**,确认没破坏、没引入退化
> **执行时机**:`/skill_evolve` 或 `/skill_optimize` 每次 OptimizerGateway 应用 mod 之后;`RefactorAgent` 重构后必跑

---

## 0. 总览矩阵

| 编号 | 检查项 | 严重级别 | 阻断? | 自动修复? |
|------|--------|:------:|:----:|:--------:|
| SK-S1 | 结构完整性 | CRITICAL | ✅ | ✅ |
| SK-S2 | 引用闭合性 | CRITICAL | ✅ | ❌ |
| SK-S3 | 无占位符残留 | CRITICAL | ✅ | ❌ |
| SK-S4 | 逻辑一致性 | HIGH/CRITICAL | ✅ | ❌ |
| SK-S5 | Spec 一致性 | HIGH | 部分 | ❌ |
| SK-S6 | Delta 可追溯 | HIGH | ❌ | ✅ |
| SK-S8 | Design Form 质量 | HIGH/CRITICAL | 部分 | ✅ |
| SK-S9 | Global Context 对齐 | HIGH/MEDIUM | 部分 | ❌ |
| SK-S10 | Anthropic 规范合规 | HIGH/MEDIUM | 部分 | ✅ |
| SK-S11 | 模式应用验证 | MEDIUM/LOW | ❌ | ❌ |
| **SK-S12** | **脚本 source 链一致性** | **CRITICAL** | **✅** | **❌** |
| **SK-S13** | **关键路径/中间层保留** | **HIGH** | **✅** | **❌** |

**AUTO_FIX 限制**:仅限 SK-S1/S2/S3/S8/S10,最多 3 轮。超限 → 报告用户。

---

## SK-S1:结构完整性

**目标**:Skill 文件本身存在且为有效载体。

| 检查项 | 方法 | 通过标准 |
|--------|------|---------|
| SKILL.md 文件存在 | `[ -f "{target}/SKILL.md" ]` | exit 0 |
| YAML frontmatter 合法 | `python3 -c "import yaml; yaml.safe_load(open('SKILL.md').read().split('---')[1])"` | 可解析 |
| 含 name / description / version | grep `^name:`、`^description:`、`^version:` | 三项均存在 |
| 内容 ≥ 50 行(非空壳) | `wc -l SKILL.md` | ≥ 50 |

**失败处理**:Skill 文件被误删 → 从 `before_skill/` 快照恢复;frontmatter 解析失败 → 重新构造 YAML。

---

## SK-S2:引用闭合性(2026-06-23 治理后强制)

**目标**:SKILL.md 中所有本地路径引用 100% 指向真实文件。这是回答"重构后是否破坏"最直接的检查。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| 所有引用的 `rules/` 文件存在 | grep `rules/`,逐一 `[ -f "$p" ] \|\| [ -d "$p" ]` | CRITICAL |
| 所有引用的 `commands/` 文件存在 | grep `commands/`,逐一 `[ -f "$p" ]` | HIGH |
| 所有引用的 `agents/` 文件存在 | grep `agents/`,逐一 `[ -f "$p" ]` | HIGH |
| 所有引用的 `hooks/` 文件存在 | grep `hooks/`,逐一 `[ -f "$p" ]` | MEDIUM |
| 路径为相对路径(无 `/home/` 等绝对路径) | grep 绝对路径模式 | HIGH |

**通过标准**:**100% 存在 → PASS**;**任一不存在 → HIGH FAIL 阻断**(要求补回)。

```bash
# 一键检查脚本模板
SKILL_FILE="$1"
echo "=== 引用闭合性检查 ==="
grep -oE '(rules|commands|agents|hooks|references|scripts|templates)/[a-zA-Z0-9_./-]+\.(md|py|sh|json|yaml|yml)' \
  "$SKILL_FILE" | sort -u | while read -r p; do
    if [ -f "$p" ] || [ -d "$p" ]; then
      echo "OK: $p"
    else
      echo "MISSING: $p"
    fi
done
```

---

## SK-S3:无占位符残留

**目标**:重构后的 Skill 不能含未填充的模板变量。

| 检查项 | grep 模式 | 严重级别 |
|--------|----------|:-------:|
| 无 `TODO` / `TBD` / `FIXME` | `\b(TODO|TBD|FIXME)\b` | CRITICAL |
| 无 `{{PLACEHOLDER}}` 模板变量 | `{{.*}}` | CRITICAL |
| 无 `...待补充` / `...待定` | `待补充\|待定` | HIGH |

**通过标准**:三类占位符匹配数 == 0。**任一命中 → CRITICAL 阻断**。

---

## SK-S4:逻辑一致性(内容级验证)

**目标**:重构后 Skill 的步骤间 I/O 闭合、无矛盾指令、依赖顺序合理。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| 步骤间 I/O 闭合:每个步骤的输入有来源 | 逐步骤检查:输入 = 前序步骤输出 或 外部输入 | HIGH |
| 步骤间 I/O 闭合:每个步骤的输出有消费 | 逐步骤检查:输出被后续步骤消费 或 为最终产出 | HIGH |
| 无矛盾指令:无互斥声明 | grep 互斥关键词对("必须"/"不"、"自动"/"等待"),人工审查 | CRITICAL |
| 步骤顺序合理:无先消费后生产的依赖倒置 | 按执行顺序标注依赖图,检查是否有后向依赖 | HIGH |
| 条件分支可判定:分支条件有明确判定标准 | grep "如果"/"if"/"否则"/"else",检查条件是否有量化标准 | MEDIUM |
| 输入输出支撑:声明的输入足以支撑声明的输出 | 人工审查 I/O 契约 + 知识加载策略 | HIGH |

**关键反例**(重构后常见的逻辑破坏):
- 重构后新增步骤 A,但步骤 A 的输入来源在重构中被删除 → A 悬空
- 重构后修改步骤 B 的输出,但下游 C 仍在引用 B 的旧输出名 → 引用断链
- 重构后调整步骤顺序,但存在后向依赖(步骤 5 引用步骤 7 的输出) → 死锁

---

## SK-S5:Spec 一致性(优化模式)

**目标**:实际变更与 optimization-spec.md §5 变更清单逐项比对,**没多改也没少改**。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| 实际变更与 spec §5 一致 | 对比 spec §5 变更清单与实际文件 diff | HIGH |
| 无清单外的额外修改 | diff 比对(应只命中 spec 列出的文件/行) | MEDIUM |
| 无清单内遗漏的修改 | 反向校验:spec 列出的每条变更都对应一次实际 diff | HIGH |

**核心执行**:
```bash
# 1) 提取 spec §5 期望变更
SPEC_CHANGES=$(grep -A 100 '^## 5\.' optimization-spec.md | \
  grep -E '^\| [0-9]+ \|' | awk -F'|' '{print $3}')

# 2) 提取实际 diff
ACTUAL_CHANGES=$(git diff --name-only before_skill/ after_skill/)

# 3) 比对:差集 = 多改/漏改
comm -23 <(echo "$ACTUAL_CHANGES" | sort) <(echo "$SPEC_CHANGES" | sort)  # 多改
comm -13 <(echo "$ACTUAL_CHANGES" | sort) <(echo "$SPEC_CHANGES" | sort)  # 漏改
```

**失败处理**:多改 → 回滚额外修改;漏改 → 应用 spec 列出但未执行的变更。

---

## SK-S6:Delta 可追溯性

**目标**:每条修改必须有 Before / After / Reason 三段式记录。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| 每次修改有 Before/After/Reason 记录 | 检查 `delta-diff.md` 或 `proposal.md` 中的修改条目 | HIGH |

**最小三段式记录格式**:
```markdown
### Change #{N}

**Before**:
​```
{原内容,精确到行号或代码块}
​```

**After**:
​```
{新内容}
​```

**Reason**:{对应诊断报告中的 finding_id;为什么这样改;预期效果}
```

**通过标准**:`delta-diff.md` 中每个 change 条目都含三段式字段;Reason 字段非空且指向具体诊断发现。

---

## SK-S8:Design Form 质量(内容级验证)

**目标**:重构后 Skill 的形态合规 — 目录分层、渐进式加载、描述公式、脚本独立。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| DF-M1 目录分层 | 有需分层内容时检查 `references/`、`scripts/`、`templates/` 目录存在 | HIGH |
| DF-M2 渐进式加载 | SKILL.md 不内联 > 100 行的参考文档或代码块 | CRITICAL |
| DF-M3 描述公式 | description 含「做什么」+「何时触发」+「输入」+「输出」 | HIGH |
| DF-M4 脚本独立 | 有确定性操作时检查 `scripts/` 下的脚本存在且可独立运行 | HIGH |
| SF-1 ~ SF-8 Anthropic 规范清单 | 逐项对照 skill-diagnosis-rules.md §6.0 | HIGH |

**DF-M2 是最常见的重构破坏点**:把 `references/` 里的内容"内联回 SKILL.md"会导致上下文膨胀,但能"省事"。**必须阻断**。

---

## SK-S9:Global Context 对齐

**目标**:重构后 Skill 仍与所在 Agent / 项目的全局上下文一致。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| GC-1 Role 一致性 | 比对 Skill 职责与 COSIGHT.md Role & Boundaries | HIGH |
| GC-2 Tool 权限对齐 | 对比 Skill 调用工具与 Agent tools 白名单 | HIGH |
| GC-3 I/O Contract 对齐 | 检查输入/输出格式是否匹配下游期望 | MEDIUM |
| GC-4 Safety 一致性 | 对比 Skill 安全策略与 Agent Safety Constraints | HIGH |
| GC-5 文件路径约定 | 检查路径是否符合 Agent work/ 约定 | HIGH |
| GC-6 状态机同步 | 检查 Skill 状态标记是否兼容 Agent Phase | MEDIUM |
| GC-7 Review 策略对齐 | 确认不自审代替 G1 | HIGH |
| GC-8 临时文件管理 | 确认有清理策略 | MEDIUM |

**对 skillx-alpha-agents 的关键**:
- GC-1:重构后的 Skill 不能越过 `COSIGHT.md §1 项目定位`(只做评测-优化循环,不感知业务细节)
- GC-2:Skill 调用工具必须是 Agent tools 白名单内的
- GC-4:Skill 的安全约束不能与 `COSIGHT.md §10 强制约束` 矛盾

---

## SK-S10:Anthropic 规范合规

**目标**:遵守渐进式披露 + L3 引用链闭合 + 脚本独立的 Anthropic 三原则。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| `references/` 加载链闭合 | 如存在 `references/`,每个文件被 SKILL.md 显式引用 | HIGH |
| `scripts/` 脚本独立可运行 | 如存在 `scripts/`,脚本不依赖 LLM 上下文 | MEDIUM |
| L1/L2/L3 渐进式加载完整 | `name`+`description` → 核心指令 → 按需引用 | HIGH |

**L3 加载链 100% 闭合检查**:
```bash
# references/ 下每个文件至少被 SKILL.md 引用一次
for f in references/*.md; do
  basename=$(basename "$f")
  if ! grep -q "$basename" SKILL.md; then
    echo "UNREFERENCED: $f"
  fi
done
```

---

## SK-S11:模式应用验证

**目标**:诊断推荐的优化模式已在重构中应用,未应用的模式有合理说明。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| 诊断推荐的模式已应用 | 对比 diagnosis-report 推荐 vs 实际 Skill 内容 | MEDIUM |
| 未应用模式有合理说明 | 标注原因(不适用 / 超出范围 / 暂缓) | LOW |

**通过标准**:`diagnosis-report.md` 中推荐的每个模式,要么:
- 已在重构后 Skill 中找到对应体现(模式 A → `scripts/` 存在;模式 B → `references/` 存在;模式 C → task-state.json 存在)
- 要么在 `proposal.md` 中标注「不适用,原因:xxx」

---

## 执行流程(强制)

```
Phase X(重构完成) → 执行以下顺序:

Step 1: SK-S1 结构完整性         → FAIL → 阻断(从 before_skill/ 恢复)
Step 2: SK-S2 引用闭合性         → FAIL → 记录缺失文件列表,阻断
Step 3: SK-S3 占位符检查         → FAIL → 阻断(禁止含占位符的 Skill 上线)
Step 4: SK-S4 逻辑一致性         → FAIL → 记录矛盾项,报告
Step 5: SK-S5 Spec 一致性        → FAIL → 回滚额外修改 / 应用遗漏变更
Step 6: SK-S6 Delta 可追溯性     → FAIL → 自动补录 delta-diff.md
Step 7: SK-S8 Design Form 质量   → FAIL → AUTO_FIX(≤3 轮)
Step 8: SK-S9 Global Context 对齐 → FAIL → 记录偏离,报告
Step 9: SK-S10 Anthropic 规范合规 → FAIL → AUTO_FIX(≤3 轮)
Step 10: SK-S11 模式应用验证     → FAIL → 标注原因

AUTO_FIX 范围: SK-S1 / S2 / S3 / S8 / S10,最多 3 轮
超限 → REPORT_TO_USER(报告用户人工介入)
```

---

## 通过标准总结

**整体通过条件**(与 skillx-alpha-agents 流程对齐):

| 条件 | 判定 |
|------|------|
| CRITICAL 项 0 失败 | 必须 |
| HIGH 项 ≤ 1 失败 | 可接受,但需记录原因 |
| MEDIUM/LOW 项 | 记录在案,后续轮次改进 |
| AUTO_FIX 已达 3 轮仍失败 | 上报用户,禁止静默通过 |

**失败回滚路径**(对应 COSIGHT.md §10 退化处理):

```
SK-S1/S2/S3/S8 失败 → 从 round_N_before_skill/ 恢复 SKILL.md
                       → 重新生成 mod,跳过本轮
                       → score_history.md 标记「本轮 revert」

SK-S4 逻辑一致性失败 → 人工审查(mod 自动修复可能引入新矛盾)
                       → 触发 LLM 二次评审(Plan agent 重审)

SK-S5 Spec 不一致  → 多改 → 回滚额外修改
                     漏改 → 应用 spec 列出的变更
```

---

## 与 skillx-alpha-agents 工作的衔接

| skillx-alpha-agents 场景 | 应用 SK-S 检查 |
|------------------------|---------------|
| **OptimizerGateway 应用 mod 后** | 必跑 SK-S1/S2/S3/S5/S6(阻断类),失败 → revert |
| **`/skill_evolve` 候选评测后** | 跑 SK-S8(Design Form),不达标记需优化方向 |
| **`/skill_optimize` 静态评估** | dim 评分已覆盖 SK-S8 部分维度,本清单作为补充维度 |
| **`RefactorAgent`(若有)完成重构** | 全量跑 SK-S1~S11,任一 CRITICAL 失败 → 阻断回流 |
| **每次 round_N 结束** | SK-S5/S6 必跑,确保本轮变更可追溯 |

> **核心约束**(来自 COSIGHT.md §10):**重构后分数不能比 baseline 低**。本清单的 SK-S 检查是结构层保障,**分数验证是行为层保障**,两者必须都通过才能宣告重构成功。
---

### 12. 实战新增:SK-S12 脚本 source 链一致性(2026-07)

**目标**:重构时合并/删除 scripts/ 中的源文件(如 config.sh → lib.sh),必须验证所有脚本的 `source` 调用已同步更新。这是**容易被忽略的「细节级」**问题,但会导致 SKILL.md 通过静态检查、跑出 F1=0 的尴尬。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| 所有脚本 `source xxx.sh` 指向真实存在文件 | `grep -rn "^source" scripts/ \| awk '{print $2}'` 列出所有被 source 的文件,逐个 `[ -f "$f" ]` 检查 | CRITICAL |
| 删除旧文件前已迁移所有引用 | 删除前 `grep -rn "被删文件名" scripts/`,无引用才能删 | CRITICAL |
| 合并 util 类脚本时无残留 `if [ -f 旧文件 ]` 块 | `grep -rn "if.* -f.*config.sh\|if.* -f.*common.sh" scripts/`,确认无残留 | CRITICAL |
| 所有 scripts 可独立 `bash -n` 语法检查通过 | `for f in scripts/*.sh; do bash -n "$f"; done` 全部 exit 0 | HIGH |

**通过标准**:
- **被 source 的文件 100% 存在** → PASS
- **任一不存在 → CRITICAL FAIL,阻断**(要求补回旧文件或更新 source 调用)
- **bash -n 全过** → PASS

**自动化检查脚本模板**:
```bash
SCRIPTS_DIR="scripts"
echo "=== 脚本 source 链一致性检查 ==="
grep -rn "^source" "$SCRIPTS_DIR" | while read -r line; do
  src_file=$(echo "$line" | awk '{print $2}' | tr -d '"' | sed 's/.*\///')
  if [ -f "$SCRIPTS_DIR/$src_file" ] || [ -f "$(dirname $line | sed 's/:.*//')/../$src_file" ]; then
    echo "OK: $line"
  else
    echo "MISSING SOURCE: $line"
  fi
done

echo "=== 残留旧文件引用检查 ==="
for old_file in config.sh common.sh error_handler.sh utils.sh; do
  if grep -rn "$old_file" "$SCRIPTS_DIR"; then
    echo "WARNING: 仍有 $old_file 引用"
  fi
done

echo "=== bash -n 语法检查 ==="
for f in "$SCRIPTS_DIR"/*.sh; do
  bash -n "$f" 2>&1 && echo "OK: $f" || echo "SYNTAX FAIL: $f"
done
```

**典型反例**:
- 合并 `config.sh` / `common.sh` / `error_handler.sh` / `utils.sh` → `lib.sh` 后,**5+ 个脚本里仍写 `if [ -f config.sh ]; then source config.sh; fi`**
- 重构后 `config.sh` 不存在,`if` 永远 false,脚本直接 exit 1,后续步骤输入丢失,F1=0

**真实案例**:2026-07 组件间流程设计 Skill 重构中,RAN-5741646 因 5 个脚本残留 `if [ -f config.sh ]` 块,F1 从 45.99 退化到 0.00。

---

### 13. 实战新增:SK-S13 关键路径/中间层保留(2026-07)

**目标**:SKILL.md §4 详细流程图外移到 `references/router.md` 后,Agent 在自主决策时倾向走"更直接"路径,**跳过中间组件**。必须验证 router.md 中关键路径仍有完整链路,且 SKILL.md 主体保留强制路径提示。

| 检查项 | 方法 | 严重级别 |
|--------|------|:-------:|
| router.md 含完整中间层链路 | 对比 R 链路,确认 router.md 不简化(不跳 SMC/FCS 等中间组件) | HIGH |
| SKILL.md §4 保留强制路径提示 | 检索 SKILL.md 主体是否含"不要简化链路"/"必须包含中间组件"等约束语 | HIGH |
| 回归测试 R-N 含完整中间层用例 | 跑 R-N 场景中"多跳链路"用例(如 MCC → SMC → RKC → FCS → UPA) | CRITICAL |

**通过标准**:
- **router.md 关键路径与 R 一致** → PASS
- **SKILL.md 主体有强制路径约束** → PASS
- **R-N 场景中多跳链路 F1 ≥ baseline** → PASS
- **任一失败 → HIGH FAIL,需回滚 router.md 内容或补充 SKILL.md 主体约束**

**典型反例**:
- router.md 中标"链路 MCC → RKC → UPA"——直接跳过 SMC 和 FCS
- SKILL.md §4 只说"5 个 Procedure",没有提示"完整链路"
- Agent 看到 router.md 后,选了"更短"路径,丢失 5-6 条交互

**真实案例**:2026-07 组件间流程设计 Skill 重构中,RAN-6166005 因 router.md 简化链路,F1 从 24.88 退化到 0.00。

---

### 14. 执行流程更新(含 SK-S12/S13)

```
Phase X(重构完成) → 执行以下顺序:

Step 1:  SK-S1  结构完整性          → FAIL → 阻断(从 before_skill/ 恢复)
Step 2:  SK-S2  引用闭合性          → FAIL → 记录缺失文件列表,阻断
Step 3:  SK-S3  占位符检查          → FAIL → 阻断
Step 4:  SK-S4  逻辑一致性          → FAIL → 记录矛盾项,报告
Step 5:  SK-S5  Spec 一致性         → FAIL → 回滚额外修改 / 应用遗漏变更
Step 6:  SK-S6  Delta 可追溯性      → FAIL → 自动补录 delta-diff.md
Step 7:  SK-S8  Design Form 质量    → FAIL → AUTO_FIX(≤3 轮)
Step 8:  SK-S9  Global Context 对齐  → FAIL → 记录偏离,报告
Step 9:  SK-S10 Anthropic 规范合规  → FAIL → AUTO_FIX(≤3 轮)
Step 10: SK-S11 模式应用验证        → FAIL → 标注原因
Step 11: SK-S12 脚本 source 链一致性 → FAIL → 阻断(补回旧文件或更新 source)
Step 12: SK-S13 关键路径/中间层保留 → FAIL → 阻断(回滚 router.md 或补 SKILL.md 主体约束)

AUTO_FIX 范围: SK-S1 / S2 / S3 / S8 / S10,最多 3 轮
超限 → REPORT_TO_USER
```

**总览矩阵更新**:

| 编号 | 检查项 | 严重级别 | 阻断? | 自动修复? |
|------|--------|:------:|:----:|:--------:|
| SK-S1 | 结构完整性 | CRITICAL | ✅ | ✅ |
| SK-S2 | 引用闭合性 | CRITICAL | ✅ | ❌ |
| SK-S3 | 无占位符残留 | CRITICAL | ✅ | ❌ |
| SK-S4 | 逻辑一致性 | HIGH/CRITICAL | ✅ | ❌ |
| SK-S5 | Spec 一致性 | HIGH | 部分 | ❌ |
| SK-S6 | Delta 可追溯 | HIGH | ❌ | ✅ |
| SK-S8 | Design Form 质量 | HIGH/CRITICAL | 部分 | ✅ |
| SK-S9 | Global Context 对齐 | HIGH/MEDIUM | 部分 | ❌ |
| SK-S10 | Anthropic 规范合规 | HIGH/MEDIUM | 部分 | ✅ |
| SK-S11 | 模式应用验证 | MEDIUM/LOW | ❌ | ❌ |
| **SK-S12** | **脚本 source 链一致性** | **CRITICAL** | **✅** | **❌** |
| **SK-S13** | **关键路径/中间层保留** | **HIGH** | **✅** | **❌** |
