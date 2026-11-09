# 重构案例 d7bcf0da — Skill 组件间流程设计

> **来源**:session `d7bcf0da-0160-485e-8cf0-9f015a73bf48`(2026-07-07)
> **目的**:作为 `/skill_refactor` 的**标杆案例**,CC 接到 refactor 任务时主动参考本案例的 7 大类改动,避免浅层重排版。
> **关联文件**:`docs/重构原则-skill分层与目录结构.md` / `docs/重构原则-skill重构模式库.md` / `docs/重构后检查-Skill完整性验证.md` / `docs/重构后检查-等效性与回归测试.md`
> **diff 报告**:本地生成的《组件间流程设计 Skill 重构 Diff》报告（不随仓库分发）

---

## 1. 案例背景

| 指标 | 数值 |
|---|---|
| 目标 Skill | 组件间流程设计(子 Agent 用的设计 Skill) |
| 改动前 SKILL.md | 243 行 / 19295 字节 |
| 改动前文件总数 | 35 个(20 md + 15 sh) |
| 改动后文件总数 | 33 个(增加 4 个新文件 + 删除 8 个 orphan md + 删除 4 个被合并脚本) |
| 改动后 SKILL.md | 约 110 行 / 减 60% |
| 总变更 | 33 个文件,+752 / -970 |
| 关联业务 | 5G 基站子系统设计(需求 RAN-6166005 等) |

---

## 2. 7 大类改动详表(对标未来 /skill_refactor 调用)

| # | 类别 | 改动量 | 实施方法 |
|---|---|---|---|
| **1** | frontmatter description 4 要素公式 | L4 1 行 | Edit description 字段(原 1 句描述 → 4 要素公式,202 字符) |
| **2** | §3 硬约束 + §7 任务完成标准 | -2 段 + 重排 | d7bcf0da 保留内容在 SKILL.md body 并重排版;其他做法:外置到 `references/execution-rules.md` |
| **3** | §1 技能定位大图 → 1 行 + 引用 skill-assets.md | -9 行 | 合并 §1 大图与 §2 目录树外移到 `references/skill-assets.md` |
| **4** | §4 执行总览大流程图 → 5 行 + 引用 router.md | -37 行 | ASCII 流程图外移到 `references/router.md` |
| **5** | §5.1 Scripts 表格 + §5.2 Templates 表格 | -18 行 | 完全删除,改用 `scripts/README.md` + `templates/README.md` 目录索引 |
| **6** | §6.2 过程产物 13 行表格 → 1 行 + 引用 io-contract.md | -12 行 | 13 项过程产物路径外移到 `references/io-contract.md` |
| **7** | orphan 8 md + scripts/ 工具层 4 sh 合并 | -8 md -4 sh | 见下两表 |

### 2.1 orphan md 删除清单(8 个 → 0 个 + 1 个 manifest.json)

| 原文件 | 大小 | 合并到 |
|---|---|---|
| `references/组件变更拆分规则/SPA_SMC_2_SPA_UAC_发送组件.md` | 646 B | `references/lookup-rules/manifest.json` (规则类型=组件变更拆分) |
| `references/组件变更拆分规则/MCC_2_SPA_SMC_接收组件.md` | 643 B | 同上 |
| `references/组件变更拆分规则/SPA_RAC_2_PHY_发送组件.md` | 634 B | 同上 |
| `references/子系统间消息处理组件规则/MCC_2_SPA_消息接收组件.md` | 457 B | `references/lookup-rules/manifest.json` (规则类型=子系统间消息处理组件) |
| `references/子系统间消息处理组件规则/SPA_2_CPA_消息接收组件.md` | 555 B | 同上 |
| `references/子系统间消息处理组件规则/UPA_2_CPA_消息接收组件.md` | 555 B | 同上 |
| `references/子系统间消息处理组件规则/UPA_2_SPA_消息接收组件.md` | 490 B | 同上 |
| `references/子系统间消息处理组件规则/SPA_2_PHY_消息发送组件.md` | 457 B | 同上 |

**配套新增**:
- `references/lookup-rules/manifest.json`(67 行,JSON 格式规则清单)
- `scripts/load_rule.sh`(按规则类型 + id 查询 manifest.json)

### 2.2 scripts/ 工具层合并(4 个 → 1 个)

| 原文件 | 行数 | 合并到 |
|---|---|---|
| `scripts/common.sh` | 7 | `scripts/lib.sh` (路径常量) |
| `scripts/error_handler.sh` | 169 | `scripts/lib.sh` (日志机制 + 错误处理) |
| `scripts/utils.sh` | 116 | `scripts/lib.sh` (通用工具函数) |
| `scripts/config.sh` | 160 | `scripts/lib.sh` (业务常量与映射表 + 路径推导) |

**合并后**:
- `scripts/lib.sh`(353 行,5 大块:一路径 / 二日志 / 三工具 / 四业务 / 五路径推导)
- 14 个 scripts/*.sh 把 `source if [ -f config.sh` 块改为 `source lib.sh` 直接调用

**配套新增**:
- `scripts/table_io.sh`(表格 IO 工具)
- `scripts/README.md`(脚本目录索引)

### 2.3 references/ 新增文件(3 个)

| 文件 | 行数 | 用途 |
|---|---|---|
| `references/router.md` | 44 | 5 Procedure 完整 ASCII 流程图 |
| `references/io-contract.md` | ~50 | 13 项过程产物输入/输出/Schema 清单 |
| `references/skill-assets.md` | 50 | 资产目录树(执行时不读,维护者参考) |

### 2.4 templates/ 新增文件(1 个)

| 文件 | 用途 |
|---|---|
| `templates/README.md` | 5 个模板文件的目录索引与适用 Procedure |

---

## 3. 实战教训(提炼到框架层)

### 3.1 SK-S12 脚本 source 链一致性(d7bcf0da 实战第 1 个回滚点)

**问题**:d7bcf0da 合并 scripts/ 时,5 个脚本(validate_*.sh × 5)残留 `if [ -f config.sh ]` 块。config.sh 已删除,运行时 `source` 失败直接 exit 1。

**修复**:把整个 `if [ -f config.sh ] ... fi` 块删除,改为 `source lib.sh` 直接调用。

**预防**(已落到框架):
- `docs/重构后检查-Skill完整性验证.md` 新增 **SK-S12**(脚本 source 链一致性)
- `docs/重构后检查-等效性与回归测试.md` 新增 **R-ScriptLink** 场景(跑每个修改后的 scripts/*.sh 不应 exit 1)
- `scripts/optimizers/static_plan_drafter.py` Step 5 必做项:合并 4 个脚本 + 改 source 块

### 3.2 SK-S13 关键路径/中间层保留(d7bcf0da 实战第 2 个回滚点)

**问题**:d7bcf0da 把 5 Procedure 流程图外移到 router.md 后,1/6 需求(RAN-6166005)的中间组件被 Agent 跳过:原始 R 链路 `MCC → SMC → RKC → FCS → UPA` 被 Agent 跳成 `MCC → RKC → UPA`(跳了 SMC、FCS)。

**修复**:在 router.md 的关键路径加 ⚠️ "必须包含中间组件" 标注。

**预防**(已落到框架):
- `docs/重构后检查-等效性与回归测试.md` 新增 **R-MidLayer** 场景
- `scripts/optimizers/static_plan_drafter.py` Step 13 必做项:外移流程图前对比 R 链路

### 3.3 d7bcf0da 增量数据(33 文件 752/970)

```
文件数: 33
新增行: +752
删除行: -970
```

典型节奏:**深度重构** 删除量 > 新增量(净减),原因是:
1. 8 个 orphan md 整段删除 → 删除多
2. scripts/ 工具层合并(4 → 1) → 删 169+116+160-353=92 行
3. 5 个新增 references(精简版)→ 新增 < 200 行
4. SKILL.md 243 → 110 行 → 净删 133 行

---

## 4. 与浅层重构的对比

| 维度 | 浅层重构(本 session 第一次) | 深度重构(d7bcf0da) |
|---|---|---|
| 总改动 | 12 文件 +164/-58 | 33 文件 +752/-970 |
| orphan 处理 | 加 HTML 注释"预留知识库" | 删除 8 个 + 合并为 manifest.json |
| scripts/ 工具层 | 0 改动 | 合并 4 个为 lib.sh(353 行) |
| 内联大内容 | 仅 §3 §7 外置 | §1 §2 §4 §5.1 §5.2 §6.2 全外置 |
| 新增辅助文件 | 3 个 | 8 个(4 references + 1 manifest + 3 scripts/README) |
| 实战教训沉淀 | 0 | SK-S12/S13 + R-ScriptLink/R-MidLayer 落地到框架 |

**核心差距**:浅层重构 = 仅修改 SKILL.md 文本;深度重构 = 重组目录结构 + 合并脚本层 + 沉淀实战教训到框架。

---

## 5. 关联框架改动(本 session 做的"根治"工作)

为了避免下次 /skill_refactor 重复踩"浅层重构"的坑,session d7bcf0da 后,skillx-alpha-agents 框架做了以下改动:

| 改动 | 文件 | 目的 |
|---|---|---|
| 根因A | `scripts/optimizers/static_plan_drafter.py` (新增) | 7 步 plan 草稿自动生成,CC 不必从零合成 |
| 根因A | `scripts/orchestrator.py` `_run_refactor_mode` | 调用 plan drafter 自动生成 `refactor_plan_draft.md` |
| 根因B | `scripts/optimizers/static_refactor.py` LLM prompt | 注入 d7bcf0da 13 FD 必查类别,LLM 必须覆盖 |
| 根因C | `scripts/optimizers/static_refactor_diff.py` `_build_key_findings` | diff HTML 加 SK-S12 source 链检查 + top 5 大改文件 |
| 根因D | `docs/重构后检查-Skill完整性验证.md` | 新增 SK-S12 脚本 source 链一致性 |
| 根因D | `docs/重构后检查-等效性与回归测试.md` | 新增 R-ScriptLink / R-MidLayer 场景 |
| 根因E | `docs/重构案例-d7bcf0da-Skill组件间流程设计.md`(本文件) | 标杆案例,CC 主动参考 |
| 根因F | `commands/skill_refactor.md` | 7 步 plan 模板升级为 8 步(加 Step 0.5 案例参考 + 1.5 source 链预检 + 4.5 中间层保留) |

---

## 6. CC 使用本案例的指引

### 6.1 接到 /skill_refactor 任务时

1. **Read 本案例**(了解 d7bcf0da 7 大类改动,作为标杆)
2. **Read** `workspace/refactor_plan_draft.md`(自动生成的 7 步 plan 草稿)
3. **进入 plan mode**,在 plan 草稿基础上微调每个 Step 的 before/after
4. **ExitPlanMode** 让用户批准
5. **在 after_skill/ 副本**上用 Read + Edit 应用
6. **跑 6 项 SK-S 静态验证** + 3 个 R-N 场景
7. **调 orchestrator** `--mode refactor-diff-report` 生成 diff HTML
8. **最终报告** 对照本案例,记录"做了多少 / 还差多少"

### 6.2 自我检查清单(对照 d7bcf0da)

- [ ] 删除了 orphan md 吗?(8 个常见为组件变更拆分规则/* 与子系统间消息处理组件规则/*)
- [ ] scripts/ 工具层合并了吗?(common + error_handler + utils + config → lib.sh)
- [ ] 5 个新文件都建了吗?(router.md / io-contract.md / skill-assets.md / scripts/README.md / templates/README.md)
- [ ] 14 个 scripts/*.sh 的 `source if [ -f config.sh` 块全删了吗?
- [ ] 改完后跑过 `bash scripts/*.sh` 不应 exit 1 吗?(R-ScriptLink)
- [ ] 流程图外移后,关键中间组件(SMC/FCS/XC)保留了吗?(R-MidLayer)
- [ ] 增量数据对标 d7bcf0da 吗?(预期 +700/-800,实际差异 < 30%)

---

## 7. 实战数据(用于自我校准)

| 维度 | d7bcf0da 数据 | 浅层重构参考线 | 优秀阈值 |
|---|---|---|---|
| 文件数 | 33 | < 15 | ≥ 30 |
| 新增行 | +752 | < 200 | ≥ 700 |
| 删除行 | -970 | < 100 | ≥ 800 |
| 净变化 | -218 | 几乎 0 或正 | < -200 |
| orphan 处理 | 删除 8 个 | 加注释 | 删除 + manifest |
| scripts/ 工具层 | 4→1 合并 | 0 改动 | 至少合并 2 个 |
| 新增 references | 3 个核心 | 0-1 个 | ≥ 3 个 |
| 新增 scripts | 3 个(2 工具 + 1 README) | 0-1 个 | ≥ 3 个 |

**判定标准**:
- 新增行 ≥ 500 且 删除行 ≥ 600 → 深度重构
- 新增行 < 200 或 删除行 < 50 → 浅层重构,需返工
- 中间状态 → 看是否覆盖 7 大类(本案例 §2 表),未覆盖的 FD 需补

---

> **回归测试**:本案例是 `/skill_refactor` 的**质量基准**。后续每次 refactor,CC 应在最终报告里引用本案例 + 标注"实际改动 vs d7bcf0da 7 大类对照表",作为质量自评依据。