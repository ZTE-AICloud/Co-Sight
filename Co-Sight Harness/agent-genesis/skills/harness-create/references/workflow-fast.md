# Phase 2-fast: Agent 创建/优化 fast 车道（experimental）

> 本文件 = fast 车道人读编排视图（车道 2 create = step-f1 / 车道 7 optimize = step-f2, 各自到尾）。
> 互指: full 车道视图 = `references/workflow.md`（其文件头有对称互指行）。
> 权威链（禁令见 fast-lane-implementation.md §3.3）: 步骤机检权威 = `phase/gates/gates.yaml`
> triggers（step-f1-fast-build）; 执行权威 = `agents/fast-lane-builder.md`; 本文件禁复制
> 步骤定义, 只做调度叙述。
> 判据数据 = `knowledge/fast-lane/criteria.yaml`; 报告契约 = `schemas/fast-lane-report.schema.yaml`。

---

## §Lane 判定节（前置层 + T1 直道执行; 位置 = SKILL.md, 本节为详述规格）

**时机**: Step 1 澄清完成并收敛后单点判定（裁定 3: 判定后移）; 不注册 trigger（先例同入口探针）。

**前置层（澄清收敛门槛, v1.2 裁定）**: 澄清不清楚**不作为** fast/full 路由依据——
clarified 字段缺失 / 未收敛 → **回 Step 1 继续澄清**, 不进入判定（不写 lane-decision）;
断点续跑不重进本节, 旧 work 目录不追朔补填。

**T1 资格判定**（main agent 单轮, 两项职能）:
1. 对照 `criteria.yaml` agent 段评估单判据 `fast_path_hit`（v1.3 D-02: OR 语义,
   输入**只**取 clarified-agent-requirements.yaml 显式字段与需求文本, 不脑补;
   语义判断, R2——criteria.yaml 只声明判据项不含判定逻辑）。三分支任一命中即
   fast 候选, 留痕注明命中分支（供批 4 审计）; 全不命中 → 静默 full:
   - `fast_path_hit`: 三分支任一命中即 fast 候选（OR 语义）:
     - anchor: 主场景锚定 task-mode-pattern-mapping.md 核心模式之一
       （11 唯一核心 id 分布于 12 场景行）, 拓扑 / 外部集成不限
     - low_complexity: 单 Agent 或简单 Agent 协同可交付（无需设计评审的常规形态）
     - sampled: golden 池有同场景 / 同锚定模式实例包（few-shot 可套用）
   （v1.3 撤除 form_fully_prescribed: 形态条目无逐场景对照清单, 判定不可证伪退化为
   从严默认值; 形态把关下沉出口侧——机器检查 + 用户自测 + 重跑 full, 同 D-01 posture）
2. 模式锚定: 对照 task-mode-pattern-mapping.md 认定唯一主模式 id（语义判断, 红线 R2）;
   **格式断言: anchored_mode 必须写 mapping 核心模式全 id**（如 `W2-Router`, 非缩写 `W2`
   ——golden-lookup 以全 id 为检索键, INDEX.yaml lookup.key_domain 为准; 缩写会被检索
   fail-closed 判未命中）

**兜底层**: criteria.yaml 缺失 / 解析失败 / 键缺失 → 静默走 full（C8-1——配置完整性
兜底, 与澄清歧义性质不同）。**非交互静默保障（红线 R7）**: 不可交互上下文（selftest
golden-cases / e2e-test-runner 管道 / headless / CI）→ **直接走 full, 不发
AskUserQuestion**——自动化路径行为与现状 100% 一致; 判定节自身异常同样静默 full 不阻塞。

**直道执行（D-04）**: 判定即执行, 不调 AskUserQuestion——命中 → 直接进 fast 驱动节,
先输出一行 `车道判定 → 标准模式构建（fast）`; 全不命中 → 静默走
full; 用户显式语句（"样例"/"走 fast"/"走 full"）优先于判定（user_override）。

**留痕**: 判定结果写 `.agent-genesis/work/{name}/fast-lane/lane-decision.yaml`:
`lane: fast|full` / `criteria_eval`（命中分支 anchor|low_complexity|sampled + 依据字段;
full 时记全不命中）/ `anchored_mode`（主模式 id）/
`decided_by: t1_auto|user_override|noninteractive_fallback|criteria_missing_fallback` /
`decided_at`（ISO8601）。走 full 也落盘, 供审计。

**DC 语义**: fast 车道不走任何人审 DC（G028 为唯一交付闸门）; clarifier 产出的
dc010_channel 字段照常落盘但 fast 路径忽略。

---

## fast 驱动步骤（step-f1-fast-build 到尾）

前置: 共享段完成（探针 + Step 1 澄清 + §Lane 判定 = fast）; `{name}` 已解析;
`{PLUGIN_ROOT}` = env-probe 解析的插件根绝对路径（字面替换, 禁依赖 shell 环境变量）。

### 步骤 1: init + 落盘 lane-decision

```bash
bash {PLUGIN_ROOT}/scripts/main-agent-helpers.sh init ".agent-genesis/work/{name}" agent-creation-fast
# lane-decision.yaml 已由判定节落盘（上节）
```

### 步骤 2: 派发 fast-lane-builder（单轮; 修复轮见下）

Agent({subagent_type: agent-genesis:fast-lane-builder}, 只传 prompt 参数, P10.5 规则):
`--requirements` / `--lane-decision` / `--mode-entry`（主模式形态条目, main agent 预提取）/
`--few-shot`（golden-lookup 检索产物形态样例包, main agent 经 `golden-lookup.sh` 检索
注入——判定节 anchored_mode 全 id 为检索键, 规则权威 = knowledge/golden/INDEX.yaml;
命中输出包相对路径（含 output-snapshot + anchors）, 未命中（NONE）跳过本指引）/
`--output-standard`（knowledge/agent-creation/agent-output-standard.yaml）/
`--output-dir output/agents/{name}/v1/` / `--fast-work-dir .agent-genesis/work/{name}/fast-lane/`

### 步骤 3: g025 物化 copy/template 条目（main agent 直调, fail-closed）

```bash
bash {PLUGIN_ROOT}/scripts/gates/g025-asset-copy.sh --build-plan ".agent-genesis/work/{name}/fast-lane/build-plan.md" --output-dir "output/agents/{name}/v1/"
```
FAIL（source 缺失/模板变量缺键）→ 原样进 verdict, 走修复轮。

### 步骤 4: G024 落盘检查

```bash
echo '{"step_id": "step-f1-fast-build", "name": "{name}", "root": "'"$PWD"'"}' | bash {PLUGIN_ROOT}/scripts/gates/g024-output-exists.sh
```
（outputs 清单 = gates.yaml trigger 注册: `fast-lane/build-plan.md` + `fast-lane/self-report.md`）

### 步骤 5: G028 交付闸门（直调, 不经 g026 不经 executor——§4.0 直调契约）

```bash
echo '{"profile":"agent-exit","output_dir":"output/agents/{name}/v1","work_dir":".agent-genesis/work/{name}/agent-creation","skills_dir":"output/agents/{name}/v1/.claude/skills","rules_dir":"output/agents/{name}/v1/.claude/rules","build_plan":".agent-genesis/work/{name}/fast-lane/build-plan.md"}' | bash {PLUGIN_ROOT}/scripts/gates/g028-exit-sanity.sh
```
退出码 0=PASS / 1=CONCERNS / 2=FAIL（failures[] 机读错误清单）。
极简 build-plan 使 G028 agent-exit 档零改动复用（g023 batch/cross 照查）。

### 步骤 6: 合并 verdict + 单入口

合并步骤 4/5 结果写 `.agent-genesis/work/{name}/gate-results/step-f1-fast-build.json`
（verdict 取最坏）, 然后单入口:

```bash
bash {PLUGIN_ROOT}/scripts/main-agent-helpers.sh step_complete step-f1-fast-build ".agent-genesis/work/{name}" "output/agents/{name}/v1" "[]"
```

### action 分叉（唯一导航权威 = 单入口输出单行 JSON）

- **PASS / PROCEED_WITH_CONCERNS → 交付汇报**（下方汇报契约）
- **FAIL → 修复轮**（retry max 1, 来源 = gates.yaml trigger on_failure）:
  1. failures[] 写 `.agent-genesis/work/{name}/fast-lane/revision-request.json`
  2. 新 Agent 会话派发 fast-lane-builder, 增传 `--revision-request`（其余参数同步骤 2;
     builder 读盘既有产物增量修改, revision_rounds +1）
  3. 重跑步骤 3-6
  4. **再 FAIL → 终止 + 失败报告**（裁定 4: fast 到尾, 无升级/handoff）, 三要素:
     ① 机读 failures + 用户语义转述（C9-6, 禁内部编号）② 已产文件位置
     （output/agents/{name}/v1/, 物理保留由用户自决——R1）③ 重跑指引
     （"full 车道重跑为全新调用" + fast 车道重新入口指令）
- **ESCALATE_*** → 按单入口已落盘 gate-block.md 选项 AskUserQuestion

---

## 交付汇报契约（fast 车道专用段, 并入 SKILL.md 里程碑）

必须包含四个固定要素:
1. **模式明示**: "本交付由标准模式（fast）生成——机器检查把关,
   未走方案人审和语义评分"（R5 明示之一, 另两处 = 入口一行陈述 + plugin.json 实验性标记）
2. **质量门禁提示**: 数据源 = gate-results/step-f1-fast-build.json 顶层 concerns[];
   无则"质量门禁全部通过", 有则逐条用户语义转述（禁内部编号/术语, C9-6）
3. **评测未运行提示**: "未运行端到端评测, 可随时补跑"（OPT-3 对齐）
4. 产物位置 + 启动方式（`cd output/agents/{name}/v1 && claude`）

## 禁令（本车道专用, 全文有效）

- 禁读 full 车道产物 / 禁把 fast 产物带入 full（R1——fast 失败后重跑 full 是全新调用）
- 禁绕过 G028（R4）; 禁 builder 执行期改道（裁定 4, 无 T3/T4）
- 禁修改本文件步骤语义而不改 gates.yaml（禁反向投影, §3.3）

---

## fast 驱动 — optimize（step-f2-fast-optimize 到尾, FC; 三输入形态分流 + 安全三件）

**optimize 只走 fast**（裁定 6: agent 线无 full optimize——agent-optimize-diagnose-mode.md
已缩水取代; 判据不满足的去处是 create 重建/手动, 绝无降级路径）。

### 澄清段三输入形态分流（在 Step 1 澄清内收敛为"方向 + 点名清单"）

| 形态 | 用户输入 | 处理 |
|------|---------|------|
| ① 提议方向 | "把 X 改成 Y" / "调 Z 的阈值" | clarifier 直取方向 → 追问点名清单（改哪些文件）→ 确认 |
| ② 提供 trace | session JSONL 路径 | main agent 派 **trace-analyzer**（agents/trace-analyzer.md, 只诊断不动手）→ `fast-lane/trace-diagnosis.md`（执行观察/问题发现/候选方向/建议点名 ≤3）→ **AskUserQuestion 请用户确认方向与点名**（可改可选）→ 收敛 |
| ③ 仅"要优化" | 无方向无 trace | 澄清器现状描摹: 派既有 **readiness-verifier** 对目标出证据（零新件）→ 澄清器按证据推荐 1-2 个方向 → 用户确认追问（一次, 带推荐答案）→ 收敛; 两轮仍无方向 → 如实告知"暂无可收敛的优化点"终止（不硬造） |

收敛产物: clarified-agent-requirements.yaml（optimize 形态: 方向描述 + 点名文件清单 +
目标路径）+ change-list.txt（点名清单 = allowlist）。点名 >2 或涉结构变更 → 告知超
fast 判据 + 去处（create 重建/手动）, 不进 step-f2。

### step-f2 步骤（安全三件 = §4.0 共用规格, 与 skill 线 sf2 同款禁变体）

1. init + lane-decision（mode: optimize, decided_by 含形态标识）
2. **安全件①快照**: `cp -r "<目标agent目录>/." ".agent-genesis/work/{name}/fast-lane/snapshot/"`;
   点名清单落 `fast-lane/change-list.txt`
3. Agent(fast-lane-builder): `--mode optimize` / `--requirements`（方向+点名）/
   `--lane-decision` / `--target-agent <目标目录>` / `--change-list` / `--fast-work-dir`
   ——builder 就地修订 + **build-plan 对账**（目标有→增量修正声明; 无→生成反映现状的
   极简 build-plan, G028 agent-exit 档必填消费）; self-report 含 delta 段
4. **安全件②范围机检**: `bash {PLUGIN_ROOT}/scripts/check-delta-scope.sh --snapshot
   .../fast-lane/snapshot --target <目标目录> --allowlist .../fast-lane/change-list.txt`
   ——越界 FAIL → 终止 + 快照自动恢复 + 失败报告（builder 越权不走修复轮）
5. **G024**（outputs 按形态传子集: 形态②含 trace-diagnosis.md, ①③ 仅 self-report.md）
   + **安全件③G028 后测**（agent-exit 档, stdin JSON 同 §fast 驱动步骤 5——build_plan
   指向 fast-lane/build-plan.md 即 builder 的对账产物）+ g025（仅当 build-plan 含
   copy/template 修改条目时重物化）
6. 合并 verdict（安全三件 + G024 全 PASS 才 PROCEED）→ step_complete step-f2-fast-optimize
   → 分叉同 create（修复轮仅修 FAIL 项; 再 FAIL → 终止 + 失败报告三要素 + 快照恢复）

### 交付汇报（optimize 专用要素）

模式明示 + 质量门禁提示 + 评测未运行 + 产物位置与启动方式, 另含:
**delta 摘要**（每文件改动一句话）+ **快照位置**（`fast-lane/snapshot/`, 回滚用）+
优化前后对比提示（如 readiness 证据形态③已取, 附前后对比; 未取则提示可自行验证）。
