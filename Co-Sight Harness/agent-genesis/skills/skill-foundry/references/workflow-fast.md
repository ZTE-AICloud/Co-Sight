# Phase 2-fast: Skill Foundry fast 车道（experimental）

> 本文件 = skill 线 fast 车道人读视图（车道 4 create / 车道 6 optimize）。互指: full 车道
> 视图 = `references/workflow.md`。机检权威 = `phase/gates/gates.yaml` triggers
> （step-sf1-fast-build / step-sf2-fast-optimize）; 执行权威 = `agents/fast-skill-builder.md`;
> 本文件禁复制步骤定义。判据数据 = `knowledge/fast-lane/criteria.yaml`（skill_create /
> skill_optimize 段）; 报告契约 = `schemas/fast-lane-report.schema.yaml`。
> agent 线 fast 视图 = `skills/harness-create/references/workflow-fast.md`（判定节通用
> 规格同源, 本文件只写 skill 线差异）。

---

## §Lane 判定节（s0 澄清完成后; SKILL.md 内联逻辑, 本节为详述）

**非交互静默保障优先（红线 R7）**: 不可交互上下文（selftest / e2e 管道 / headless / CI）
→ **静默走 full, 不询问**; criteria.yaml 缺失/解析失败 → 同样静默 full。

**前置层（v1.2 裁定, 两线一致）**: 澄清不清楚不作为 fast/full 路由依据——clarified
字段缺失 / 未收敛 → 回 s0 继续澄清, 不进入判定（不写 lane-decision）; 续跑不重进本节。

**create 车道 4（T1 判据 = criteria.yaml skill_create 段单判据 `fast_path_hit`, OR 语义）**:
- `fast_path_hit`: 三分支任一命中即 fast 候选（语义判断, R2; 留痕注明命中分支）:
  - light: 单一 Skill 职责 + 知识内联或单文件（原 single_skill + no_multi_file_references 合并）
  - template_form: 命中既有模板形态（流程型/检查清单型等标准 Skill 形态; 充分条件非必要, v1.3 D-03）
  - sampled: golden 池有同形态实例包（--few-shot golden-lookup 已就位）
- T1 命中 → 直接进 fast 驱动节（D-04, 不调 AskUserQuestion）, 输出一行
  `车道判定 → 标准模式构建（fast）`; 全不命中 → 静默走 full
  （既有 s1+ 管线零改动）; 用户显式语句（"样例"/"走 full"）优先于判定（user_override）

**optimize 车道 6（裁定 6: skill optimize 默认路由 fast——T1 判据 = skill_optimize 段）**:
- `delta_files_le_2`: 改动点名文件 ≤2（澄清段收敛为"方向+点名"）
- `no_structural_change`: 无结构性变更（不拆分/不合并章节骨架、不改 frontmatter 必需字段集）
- `target_statically_locatable`: 目标 Skill 静态可定位（路径明确, 不需运行时探测）
- T1 全过 → 直接 fast（D-04 不再确认; 用户显式拒绝 → 终止改走手动, decided_by: user_override）
- **T1 任一不过 → 不进 full optimize（R6 条款②: full optimize 维护态不作 fallback）**——
  告知超范围项 + 去处（拆成 create 重建 / 手动修改）, 由用户选, 绝不静默降级

**留痕**: `.agent-genesis/work/{name}/fast-lane/lane-decision.yaml`（走 full 也落盘,
decided_by 区分 t1_auto/user_override/noninteractive_fallback/scope_blocked_optimize）。
**DC 语义**: fast 车道不走 DC-002（G028 为唯一交付闸门）; dc010_channel 落盘但忽略。

**形态锚定记录**: T1 通过（create）后 lane-decision 必记 `anchored_mode`——命中模板形态所锚
核心模式全 id（对照 task-mode-pattern-mapping.md 语义判断）; 无锚定核心模式写 `null`
（检索跳过）。**格式断言: anchored_mode 必须写 mapping 核心模式全 id**（如 `K3-KB-Backed`,
非缩写 `K3`——golden-lookup 以全 id 为检索键, INDEX.yaml lookup.key_domain 为准; 缩写会被
检索 fail-closed 判未命中）。

---

## fast 驱动 — create（step-sf1-fast-build 到尾）

前置: 探针 + s0 澄清 + 判定 = fast; `{PLUGIN_ROOT}` 字面替换。

1. `helpers init ".agent-genesis/work/{name}" skill-foundry-fast` + lane-decision 落盘
2. Agent(fast-skill-builder, 只传 prompt 参数): `--mode create` / `--requirements` /
   `--lane-decision` / `--output-dir output/skills/{name}/v1/` / `--fast-work-dir` /
   `--few-shot`（golden-lookup 检索产物形态样例包, main agent 经 `golden-lookup.sh` 检索
   注入——判定节 anchored_mode 全 id 为检索键, 规则权威 = knowledge/golden/INDEX.yaml;
   命中输出包相对路径（含 output-snapshot + anchors）, 未命中（NONE）或 anchored_mode
   为 null 时跳过本指引）
3. **G024 落盘检查**（outputs = trigger 注册: fast-lane/self-report.md）:
   ```bash
   echo '{"step_id": "step-sf1-fast-build", "name": "{name}", "root": "'"$PWD"'"}' | bash {PLUGIN_ROOT}/scripts/gates/g024-output-exists.sh
   ```
4. **G028 直调**（skill-build 档; skill 线 fast 无 build-plan 不走 g025——§4.0 直调契约）:
   ```bash
   echo '{"profile":"skill-build","output_dir":"output/skills/{name}/v1"}' | bash {PLUGIN_ROOT}/scripts/gates/g028-exit-sanity.sh
   ```
   （skill-build 档 g014 条件启用: 纯 skill 交付物无 .claude/ 子目录不误拦）
5. 合并 verdict 写 gate-results/step-sf1-fast-build.json（最坏值）→ step_complete 单入口
6. action 分叉: PASS/CONCERNS → 交付汇报; FAIL → 修复轮一轮（failures→revision-request.json
   → builder 新会话 `--revision-request` → 重跑 3-5）→ 再 FAIL → **终止 + 失败报告三要素**
   （机读 failures+语义转述 / 已产文件位置 / 重跑指引——full 重跑为全新调用）; ESCALATE_* → 问用户

---

## fast 驱动 — optimize（step-sf2-fast-optimize 到尾, 安全三件接线）

**optimize 安全三件（§4.0 共用规格, 不可裁——R6）**: 快照回滚 → 就地修订 →
改动范围机检 → G028 后测, 四步全过才交付。

1. init + lane-decision（decided_by 含 scope 判定）
2. **安全件①快照**: 就地修订前 main agent 快照——
   ```bash
   mkdir -p ".agent-genesis/work/{name}/fast-lane/snapshot"
   cp -r "<目标skill目录>/." ".agent-genesis/work/{name}/fast-lane/snapshot/"
   ```
   终止/失败时自动恢复（cp -r 反向覆盖回目标）; 点名清单同时落 fast-lane/change-list.txt
3. Agent(fast-skill-builder): `--mode optimize` / `--requirements`（收敛后方向+点名）/
   `--target-skill <目标目录>` / `--change-list fast-lane/change-list.txt` /
   `--fast-work-dir`（+ 修复轮 `--revision-request`）
   ——self-report 统一写 `fast-lane/self-report.md`（与 trigger outputs 同名; delta 段为
   其内容部分, optimize 必含; 首战实战发现的口径对齐项）
4. **安全件②改动范围机检**:
   ```bash
   bash {PLUGIN_ROOT}/scripts/check-delta-scope.sh \
     --snapshot ".agent-genesis/work/{name}/fast-lane/snapshot" \
     --target "<目标skill目录>" --allowlist ".agent-genesis/work/{name}/fast-lane/change-list.txt"
   ```
   越界 FAIL → 终止 + 快照自动恢复 + 失败报告（builder 越权 = 不可信修订, 不进修复轮）
5. **G024**（outputs = fast-lane/self-report.md 含 delta 段）+ **安全件③G028 后测**:
   ```bash
   echo '{"profile":"skill-verify","output_dir":"<目标skill目录>"}' | bash {PLUGIN_ROOT}/scripts/gates/g028-exit-sanity.sh
   ```
   （后测档 = skill-verify——对既有 Skill 全量静态校验, 防优化引入回归）
6. 合并 verdict（三件全 PASS 才 PROCEED）→ step_complete → 分叉同 create
   （修复轮只修 G028/自报 FAIL 项; check-delta-scope 越界不走修复轮直接终止恢复）

## 交付汇报契约（两 mode 同）

四固定要素: ① 模式明示（"标准模式（fast）生成——机器检查把关, 未走方案人审和语义评分"——R5;
optimize 汇报另含 delta 摘要与快照位置）② 质量门禁提示（concerns 用户语义转述, 禁内部编号）
③ 评测未运行提示 ④ 产物位置与使用方式。

## 禁令

- 禁读 full 车道产物 / 禁 fast 产物带入 full（R1）; 禁绕过 G028（R4）
- optimize 禁越点名清单（check-delta-scope 机检）/ 禁改 frontmatter 必需字段集（no_structural_change）
- 禁修改步骤语义而不改 gates.yaml（禁反向投影）
