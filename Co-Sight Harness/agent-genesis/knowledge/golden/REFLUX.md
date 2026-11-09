# REFLUX — 沉淀回流手册（golden 池运营约定唯一活权威）

> 地位： 本文档是 golden 资产池运营约定的**唯一活权威**（v1.2 裁定 R5）。
> 历史方案（`docs/plan/golden-asset-pool-plan.md` §3.4 等）自此仅作档案记录，
> 约定以本文为准；两文档冲突时按本文执行。
> 单源纪律： manifest 字段语义只在 `schemas/golden-manifest.schema.yaml` 定义一次；
> 检索规则只在 `INDEX.yaml` 头部声明一次。本文不复制其内容，只引用。

---

## 1. 触发与对象

- **触发**: full 车道交付汇报时，由 main agent 在汇报末尾提一句沉淀建议
  （固定措辞见 §4，C9-6 用户词汇）。**必须用户确认后才启动抽取**；用户未置
  可否不启动，绝不在交付中途自动入库。
- **对象**: 交付产物 `output/agents/{name}/v1/` 或 `output/skills/{name}/v1/`。
- fast 车道构建源自样例，形态已入库时汇报**不再建议沉淀**（建议句仅 full 车道）。
  例外： fast 产物形态未被任何既有样例覆盖（检索 miss）且用户确认 → 仍走档 1 入库，
  入库留痕如实标注构建车道（批 2 实例 parallel-scan-audit 即此情形）。

## 2. 两档流程

### 档 1 — 例行沉淀（轻， 目标 <30min）

1. 用户确认后走 §3 七步流程。**只允许挂靠既有 mode_id**（∈ INDEX key_domain，
   现 11 个核心 id）；形态不像任何既有核心时转档 2，不勉强挂靠。
2. 抽取由 SubAgent 辅助 + 人工策展（用户裁定： 人工策展为主，SubAgent 为辅）。
3. G028 准入： agent 线 `agent-exit` 档 / skill 线 `skill-build` 档（§3 第 7 步）。
4. `INDEX.yaml` pool 区加一行 —— 唯一注册点，零代码改动。

### 档 2 — 重沉淀（新核心模式）

新增核心模式是结构变更，四要件齐备缺一不可：

| 要件 | 落点 |
|------|------|
| mapping 场景行 | `knowledge/agent-creation/task-mode-pattern-mapping.md` |
| 形态条目（形态标准） | 对应模式 form 条目（形态包锚定用） |
| ≥1 个 golden 包 | 按档 1 §3 流程入库 |
| 人工评审 | 用户逐件确认 |

另需两前提： ① 该形态与既有核心模式无一贴合；② 该形态需求已发生 **≥2 次**。
数量硬顶与维护责任见 §5。

## 3. 档 1 抽取流程（七步）

1. **选件**: 交付产物形态完整（运行时面齐备）+ 有过程锚或能补过程锚
   （anchors/build-plan.md + anchors/self-report.md）。
2. **旧词汇重映射**: 外部件的外部术语/旧模式词汇一律重映射为本仓库现行
   模式词汇；重映射后 builder few-shot 看到的零外部残留。
3. **挂靠核心**: `mode_id ∈ INDEX key_domain`；贴合度如实标 `anchor_fit`
   （real / partial / forced+理由），禁为入库而虚标。
4. **重塑改造**: 外部件**必须重塑，禁原样搬运**（用户裁定： 复制后按本仓库规则
   改造）；身份消毒——禁残留外部仓库名 / 人名 / 品牌名。入库后一律为本仓库
   模板资产： 池成员无内外之分，`provenance` 只作溯源注记（R8）。
5. **补过程锚**:
   - `anchors/build-plan.md` 的 file 路径**相对交付根**，基准 = 包内
     `output-snapshot/` 根（坑位： 禁写成磁盘绝对路径，禁带
     `knowledge/golden/<pkg>/` 前缀）；shape 计数如实
     （required/conditional/generate/copy）。
   - `anchors/self-report.md` 如实记录生成轮次与 shape 对账。
6. **manifest.yaml**: 按 schema 全字段；`known_concerns` 用**单引号 YAML 标量**
   （内嵌双引号会破坏双引号标量解析）；外部件 `anchors.derived: true` 且
   `provenance: {origin_repo, license, snapshot_date, reshaped: true}` 如实填；
   自有产物 `reshaped: false`。
7. **G028 准入 + 登记**: `output_dir=<pkg>/output-snapshot`；
   agent 线须在 output-snapshot 内设 `.claude/skills/.gitkeep` 与
   `.claude/rules/.gitkeep` 诚实占位（g014 fail-closed 查键也查目录）；
   concerns 如实回填 `known_concerns` 后 `status: active` 入库。
   随后在 `INDEX.yaml` pool 加一行，`tests/flow/golden-lookup-verify.sh`
   加单命中断言。

**外部参照库只读零改动**（用户裁定 ⑨）： 抽取可 Read 参照库
（`plugin-core/knowledge/golden-examples/sources/` 等），禁止任何写入。

## 4. 汇报句契约（C9-6）

full 车道交付汇报末尾，main agent 固定补一句（用户词汇，禁内部编号与术语）:

> 本次构建的形态可沉淀为样例，下次同类需求可走样例模式。

- 位置（agent 线）: `skills/harness-create/SKILL.md` 第三步 +
  `skills/harness-create/references/workflow.md` §Milestone。
- skill 线对称位置: `skills/skill-foundry/SKILL.md` §里程碑 +
  `skills/skill-foundry/references/workflow.md` §Milestone（两线对称, 机检锚点 =
  tests/flow/fast-lane-criteria-verify.sh FB 段）。
- `mode_id` 只允许出现在 lane-decision（机读），禁随建议句上用户面。
- 用户接话确认 → 按 §2 档 1 启动；用户不接话 → 不启动，不追问。

## 5. 模式上限与池维护

- 核心模式现 **11 唯一 id**（mapping 12 场景行，WF5 跨行重复计 1）。
  **硬顶 20**——LLM 锚定难度与每模式样例预期所约束。
- 到顶后先合并 / 退役再新增，禁顶着硬顶加行。
- 池包数量不限： 同 mode_id 多包共存，检索裁决唯一权威 =
  `INDEX.yaml lookup.multi_hit_rule`（现为 acceptance 条数多者优先，再平
  词典序）。新包入库可能翻转既有裁决——**测试断言必须跟着终态走**（改断言，
  不改数据去迁就断言）。
- 退役流程: manifest `status: deprecated` + INDEX pool 行删除（或同期标注），
  包目录留存待清。

## 6. 入库批次登记

| 批次 | 包 | 备注 |
|------|-----|------|
| G0 | skill-router | 试抽包（源自 waza 重塑） |
| G2 | command-router / verify-loop / plan-approval / knowledge-reflux | 批量抽取（外部参照库 4 源） |
| G3 | skill-gate-report | 自有产物追加演练（跨线通用验证） |
| v1.2 批 2 | 档 1 实例 + 外部集成实例包 | 见各 manifest `source` 字段 |

新增批次在登记表现实追加一行，与 INDEX pool 行同步。
