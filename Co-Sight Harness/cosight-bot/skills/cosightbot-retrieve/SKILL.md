---
name: cosightbot-retrieve
description: >
  个人知识库检索问答：拿章节树（merged_overview）、按 [F###] 节点读文档全文、
  pre-processed 层全文扫描。纯只读——绝不触发索引构建。
  在任何业务/资料类问题时默认触发（不依赖用户明说"查资料"）："XX 怎么配置的 /
  上周提了哪些问题 / 这个方案的进展 / 资料里有没有 XX"。
  输入为用户问题，输出为基于实读文档的答案（附文档来源）。
---

# cosightbot-retrieve —— 知识检索（纯只读）

## When to Activate

- **默认路径**：所有业务/资料类问题一律先走本技能的三步法，不依赖用户主动说"查资料"
- 用户问"知识库 / 文档 / 资料 / 文件里有没有 XX"
- 用户问业务事实、进展、清单、状态、方案细节等

**Not for**：绑定目录 / 加文件 / 删文件 / 构建索引（→ cosightbot-material）； SOC 标书知识库检索（由本插件的标书智能体 soc-expert / cosightbot-soc-* 承担）。

## 只读红线（S-01）

本技能**只允许**下表所列只读入口。**禁止**在本技能内调用任何构建/写入命令（`llamaindex_task_runner` 的 `common_build` / `common_update` 等）。索引缺失或未构建时，引导用户使用 cosightbot-material 完成构建后再检索。

## 执行入口

```bash
python "${CLAUDE_PLUGIN_ROOT}"/skills/cosightbot-retrieve/scripts/retrieve_cli.py --agent-id main <子命令>
```

| 入口 | 用法 | 输出 |
|---|---|---|
| **主命令（章节树）** | `--agent-id main` | `merged_overview`：全路由合并的章节树（`[F###]` 全局节点 ID）。检索三步法 Step 1 的唯一入口 |
| **resolve（动态概览）** | `--agent-id main resolve --question "自包含问题" [--entity ...] [--constraint ...] [--identifier ...] [--exclude ...] [--force-dynamic]` | 大库/强制动态时返回局部 `merged_overview`：Tier 1 候选池（带命中行号）+ Tier 2 边缘候选 + `stats`/`degraded` 披露。小库且未强制时退化为全量树 |
| **状态检查** | `--agent-id main --check-only` | 只看就绪状态，不读内容 |
| **read-doc（读全文）** | `--agent-id main read-doc --node-id f001 [--line-range A:B]` | 节点对应文档全文（大文件自动截断置 `truncated=true`，用 `--line-range` 定点续读）；多模态时注入 `image` / `images` 元数据 |
| **scan（全文扫描）** | `--agent-id main scan --terms "甲,乙" [--offset N]` | pre-processed 层受控全文扫描（多词 and 共现、忽略大小写），命中带 `[F###]` 接 read-doc；截断时输出 `hits_total/hits_remaining` 与翻页指针 |
| **check-authority（权威候选提取）** | `--agent-id main check-authority --file <overview文件>`（或 stdin） | 从 resolve 的 merged_overview 结合内置中英文权威/名录词表、行尾 `[权威角色:...]` 徽标及 `doc_skeleton` 构建期角色先验列确定性提取权威候选（`authority_candidates`：`node_id/tier/score/title/path/matched_terms` 及 `jev_doc_type/jev_is_registry/match_sources/authority_role`），消除弱标题权威文档漏检与现场手写 grep 风险 |
| **filter-hits（枚举候选预筛）** | `--agent-id main filter-hits --question "原始问题" --include-rule "纳入口径" --exclude-rule "排除口径" --scan-json /tmp/scan_all.json` | 把（多页 `--offset` 合并后的）scan 命中回溯扩展为所在小节整段（≤1200 字、自动补表格表头），按 55K 预算拆批走内网 JEV 双路 Noul（in_scope / is_draft_or_template）三桶分流：`confirmed_docs` + `grey_docs` 仍必须逐篇 read-doc 实读确认后交 Python 脚本精确计数（JEV 判归属、代码做加法，S-03），`dropped_noise_ids` 仅留审计；`scan_truncated_warning=true` 时严禁下全库枚举结论，必须先用 `--offset` 翻完页再合并预筛；`all_dropped_warning=true` 时必须抽查回捞的 grey 候选确认 `--include-rule` 未写窄；`jev_degraded=true` 时全部候选落 grey_docs，退回标准手工核查 |
| **check-conflict（冲突裁决）** | `--agent-id main check-conflict --question-json '<json 或本地json路径>' --doc-ids f014,f052` | 对 ≥2 篇已读文档并行评估题面各维度显式覆盖度、5 档权威状态、显式 `supersedes` 与细节完整度，结合 Python 正则日期解析输出 R11 主来源裁决（`primary_doc_id`/`verdict`/`r11_guidance`）与 `DISCLOSURE_ONLY` 草案/示例硬隔离警告；输出是裁决辅助信号，事实仍须以 read-doc 实读原文为准（S-03）；JEV 不可用时确定性软降级（`jev_degraded=true`，退出码 0） |
| **verify-answer（答案出口核验）** | `--agent-id main verify-answer --question-file <问题文本> --draft-file <答案草稿> --read-docs <f003,f018,...> [--elapsed-seconds <float>]` | Step 3 定稿输出前的出口双向核验闸门：48 分钟预算零延迟短路 + S-04 引文集合对账（正文/披露区切分）+ 技术字面量精确子串快检 + JEV 正反双向漏点/错误否认/字面量支持核验；`PASS` 直接交卷，`REVISE_ONCE` 按 issues 定向修补 1 次后立即输出（严禁二次调用），`PASS_BUDGET_CAP`（elapsed_seconds >= 2880s）立即交卷让位 50 分钟死线 |

## 动态概览（resolve）语义

- **小库**（目录树未超上下文阈值）且未传 `--force-dynamic`：`resolve` 退化为全量 `merged_overview`，行为与主命令一致。
- **大库/强制动态**：输出 Tier 1 候选池（带命中行号）+ Tier 2 边缘候选（仅列命中位置）；`stats` 给出 `doc_count/tier1/tier2/candidate_pool/tier1_truncated/tier2_truncated/omitted_candidates/hops/rerank` 等。
- **★ 优先精读建议与行尾徽标优先参考**：`merged_overview` 顶部出现 `## ★ 优先精读建议` 区块及 Tier 1/2 文档行尾的 `[实体吻合:... | 限定:... | 权威角色:...]`（含 `↑灰区晋升`）徽标时，第一轮选读应优先覆盖该区块清单并优先打开带 `权威角色`/`↑灰区晋升` 徽标的弱标题候选（弱标题+徽标组合是最高价值信号）；该区块仍是导航建议而非唯一必读范围，不得据此跳过其余候选，仍须结合 Tier 1/2 命中行与覆盖检查完成最小充分集精读。
- **Tier 1/Tier 2 是候选池，不是必读清单**：先按原始问题、标题、命中行号和综合分选**最小充分集**（通常 3–10 篇；复杂枚举/完整性可扩展）精读；**不要求把 Tier 1 逐篇读完**。Tier 2 默认按需续读，但以下两种情形**升级为硬步骤**（不做等同候选选择未完成，禁止以"披露未读 Tier2"过关）：①Tier1 读完后答案仍依赖"唯一/最新/具名哪一份"的判别；②候选中存在 ≥2 个同名/近重复候选（公司名/项目名/单号相近）——此时必须逐条过 Tier2 标题并选读相关项。答案中披露候选池规模、已选/已精读/未精读数量。枚举/完整性问题才扩大覆盖（Tier1 选读 + Tier2 命中靠前 + 必要时 scan）。
- **标题弱信号候选必看命中行**：标题为"日期/ID 前缀 + 弱 topical 词"形态（如 `2026-11-27-mariner-…`、`SUP-425001-…`）的 Tier1 候选，与"提交记录/具名客户/具体事件"类问题天然相关，**必须打开其 resolve 命中行看内容片段再决定去留，禁止只凭标题丢弃**——标题不含题面原词 ≠ 内容不相关（评测中多起金标因此未进选读清单）。
- **hop 实体指认须排除性确认**：resolve 二跳（Q1/hops）点名的实体只是召回线索；当它指向某文档而候选里还有其他同主题近重复时，必须对每个近重复候选列出判别值并说明"为何不是它"后方可采信 hop 指认——hop 锚定错误曾直接锁定错误实体、金标全程 0 出现。
- **近重复消歧（判别性属性对照）**：候选中若出现 ≥2 篇同主题近重复（同事故/同客户/同机制/同版本，标题或来源域相近），差异往往只是一个日期、数值、专名或版本号——选读前必须抽取判别性属性列成对照表，逐一对照题面要求再决定选哪篇；题面问"哪个机制/哪个客户/哪份文档"的判别型问题，强制先列出 Top-N 候选的判别值差异，禁止凭"标题更像/分数更高"直接锁定。
- **多文档冲突矩阵（check-conflict 辅助）**：当已 `read-doc` 的候选 ≥2 篇且对同一问点给出相互冲突的数值/日期/SLA/规则时，可调用 `check-conflict --question-json '{"question":"...","dimensions":["..."]}' --doc-ids f014,f052` 生成结构化裁决矩阵（逐维度显式覆盖、5 档权威状态、显式 supersedes、细节完整度与 Python 解析日期），按其 `primary_doc_id`/`verdict`/`r11_guidance` 辅助执行 R11 采信；判为 `DISCLOSURE_ONLY` 的草案/示例默认值文档严禁把数值并入主结论，只能文末一句话披露；输出是裁决辅助信号，最终事实仍须以 read-doc 实读原文为准（S-03）。
- **A0 是诊断，不是答案**：`quality`/`gaps`/Q1、Tier 命中行、rerank 分数都只是召回线索；缺口里的人名/客户名/数值若目标文档没有，不得当事实，也不得让 gaps 决定答案结构。A0 判 MISS/PARTIAL 不等于候选池没有答案，必须自己检查 Tier 1/2。**A0/hop 使用红线**：A0 的 `answer_preview`/实体指认与 hop 点名**只用于决定多读哪些文档，禁止作为答案采信依据或主来源推荐**；A0 点名的实体必须用 scan 专名核验身份后再锁定；A0=PARTIAL_HIT 不得反向背书"不存在"结论（info_not_found 只能来自无截断 scan + 原文 REDACTED/illustrative 声明）。
- **scan 闸门**：Tier1/Tier2 已有候选时先 read-doc，**禁止用 scan 代替 read-doc**；动态模式每问题最多 1 次 scan（`--offset` 翻页视为同一次 scan 的延续，不算第 2 次），scan 词必须是专名/字段名/流程框架名（如 `allowlisted_tenants`、`per_route_group_budget`、`h200-80`、`ten-step`、`restoration sprint`、`fidelity`、`experimentation lab`、`final approved`），命中全是已知文档立即停止。仅在候选读完仍缺正文事实，或枚举/完整性/`info_not_found` 需证明全库不存在时使用；**流程/完整性题如果已读候选没有一篇覆盖全部步骤/维度，允许 1 次定向 scan**；政策解释题、单文档事实题、已有候选且已覆盖全部维度的冲突题默认不 scan；证明"不存在"时先引用原文的 REDACTED / illustrative / no exception / 无记录声明，只有原文证据不足才 scan；**scan 多词是 AND，默认选 1 个最稀有的专名/字段名/文档类型词，确定会共现才用多词**。
- **scan 三纪律（配合 scan 子命令截断提示输出）**：①**截断必响应**——输出 `truncated=true` 或 `hits_remaining>0` 时，禁止只读已展示部分下结论；先缩词（加专名）重扫，仍不够再按 suggestion 用 `--offset N` 翻页查看后续命中；截断状态下只能写"已检查范围内未找到"，不得写"全库没有"。②**发现式 scan**——scan 词取"题目点名的专名/字段名 + gaps 中出现的专名"，禁止拿已选答案的名字做"确认式自证扫描"（围绕已选对象反复换词扫描视为违规，说明选读决策缺少独立证据）。③**0 命中强制换词**——0 命中必须换 ≥2 个同义专名/机械变体（连写/分写、大小写、同义词）重试后，才允许作为弱证据；0 命中不得与 A0 gaps 互相印证。
- **枚举大命中集预筛（filter-hits）**：无截断 scan 命中文件数超过 15 篇时，可把（`--offset` 翻页合并后的）完整 scan 输出存为 JSON/JSONL 文件交给 `filter-hits` 做批量 Noul 口径预筛，秒级筛除词面噪声与疑似草稿/模板；`scan_truncated_warning=true` 说明还没翻完页，严禁据此预筛下全库枚举结论，必须先 `--offset` 翻完页；`confirmed_docs + grey_docs` 仍必须逐篇 `read-doc` 实读确认后交 Python 脚本精确计数（JEV 判归属、代码做加法，S-03），`confirmed_count` 绝不能直接当答案数字；`all_dropped_warning=true` 时必须抽查回捞的 grey 候选确认 `--include-rule` 是否写得过窄，禁止直接采信零命中；`jev_degraded=true` 时全部候选落 `grey_docs`，退回标准手工核查流程。
- **覆盖检查**：准备回答“没有单一文档/需要拼接/未找到”前，先对 `merged_overview`（或持久化输出文件）调用 `check-authority` 子命令（覆盖中英文权威/名录词表、行尾 `[权威角色:...]` 徽标与 `doc_skeleton` 构建期角色先验；仅在子命令不可用时回退 grep/awk/只读解析脚本）确定性提取标题/路径或角色匹配 `manual / handbook / operating / SLA / policy / PRD / acceptance / experiment lab / runbook / playbook / ten-step / final / approval / decision / terms / 制度 / 规范 / 手册 / 台账` 的候选，逐条标记“已读/不读+理由”，匹配未读不得下结论；再检查 Tier1/Tier2 标题与命中行是否有单一权威文档覆盖题面维度；按文档类型/权威性先验（阈值/准入→PRD/experiment lab/acceptance；SLA/目标→operating manual/handbook；final approved→final terms/approval；流程→ten-step/restoration sprint/runbook）优先读标题/类型匹配的文档，即使分数低或标题不含题面原词；**如果唯一文档精确覆盖题面维度/时间窗/区域 split，把它作为主来源，其他文档只能补充/披露冲突；显式决策算法/完整维度阈值表优先于 example defaults/illustrative/initial proposal/draft；已读的精确覆盖文档若不用，必须说明理由**；流程/runbook 题优先找单一 runbook；Tier2 仍无覆盖才做一次定向 scan，scan 词带实体/区域/SKU/流程名，不得只用泛词；**展示的 250 篇不等于全候选池，不能据此说“没有”**；否定结论必须披露检查范围、scan 词、命中数和截断状态。
- `degraded=true`：A0/Q1 二跳失败，本次是单跳收敛；必须在答案中显式披露 `degraded_reason`，不得假装完成二跳。
- `error_code=DYNAMIC_INDEX_MISSING`：动态索引未构建，返回的是目录地图；引导用户重建索引，**不得**自行扫盘或退回 scan 冒充结果。
- `error_code=INDEX_BUILDING`：section 索引正在全量构建（会清空旧行）；此时不要检索动态树，等待构建完成或改用主命令/scan 临时补盲。
- `error_code=EMBEDDING_FAILED`：embedding 服务不可用；先按"时间预算与故障降级"章节的 resolve 重试上限与降级路径处理（重试 ≤3 次后可披露故障并经 scan 直查），不得无限重试。
- `rerank=false`：rerank 未配置或失败，已使用向量/BM25 分数；在答案或进度中如实说明。

## 时间预算与故障降级（超时防护）

评测实证：不限时的检索循环会让单题卡死到外部超时（embedding 故障反复重试 resolve 数百次、100 篇候选全读、换近义词死磕），59 分钟耗尽仍未进入答案组织阶段。本节是强制节奏纪律：

- **总预算意识**：单题总时长预算 60 分钟。到达 **30 分钟**时必须进入"答案组织阶段"——只允许带着已读材料写答案；剩余时间用于补充关键缺口（最多再精读 1-2 篇）。
- **resolve 重试上限**：同一问题 resolve 失败（`EMBEDDING_FAILED`/超时/空候选）最多重试 3 次；第 3 次仍失败立即停止重试，按下方降级路径处理。**单题 resolve 总调用次数 ≤5**，超限视为违规。
- **EMBEDDING_FAILED 降级路径**（对本技能"禁止静默降级"的显式例外，仅限本场景）：第 3 次 resolve 仍失败时，允许改用 scan 全文扫描直接定位候选（绕过向量召回），必须同时满足：①在答案披露区写明"embedding 服务故障，本次经 scan 直查"；②scan 纪律照常遵守（专名词、截断必响应、命中 read-doc 实读）；③恢复后无需重答。禁止既不报错也不走 scan、只对着空候选池反复重试。
- **候选爆炸处理**：Tier 1 候选 >50 篇时**禁止全读**：先逐篇看命中行/标题做相关性初筛（初筛预算 ≤5 分钟），把候选压缩到 ≤15 篇再精读；初筛后被证明高度相关的剩余候选可分批续读，但每批都要先报告"为什么这批值得读"。
- **needle 题早识别**：同一检索目标换 ≥2 组专名/机械变体仍 0 命中、或 resolve 候选池与题面维度明显无关时，立即切换穷举直查（文件名签名/JSON 字段字面量/正则），**不得继续换近义词重试 embedding**——embedding 对字面未命中的专名无效，继续重试是纯时间黑洞。
- **部分答案降级**：时间预算到达 **50 分钟**仍未开始组织答案时，立即基于已读材料输出当前所知 + 明确标注未覆盖维度（"基于已检查的 N 篇文档：……；未覆盖：……"），禁止抱着"再读一篇就够了"的心态继续检索——部分答案远好于空卷。

## 退码与 hint 语义（必须按表处理）

| 退出码 | 输出特征 | 含义 | 处理 |
|:---:|---|---|---|
| 0 | 含 `merged_overview` | 索引就绪 | 进入三步法 Step 2 |
| 1 | `"hint": "no_documents"` | 从未添加过文档 | 如实告知"还没有绑定资料/加入文件"，引导用户使用 cosightbot-material 绑定目录或加入文件；**禁止报成"未检索到相关内容"** |
| 1 | `"hint": "building"` | 有路由索引未就绪/构建中 | 告知用户"索引尚未构建完成"，引导运行 cosightbot-material build（或等待后台构建完成）；**禁止绕过直接裸答** |
| 1 | `"error_code": "OVERVIEW_TOO_LARGE"`（无 hint 字段） | 目录树超出当前模型上下文窗口 | 把 `error` 文案如实转告用户（建议缩减知识库文档或换大上下文模型）；**禁止**自行删减目录树后继续 |
| 1 | `"error_code": "DYNAMIC_INDEX_MISSING"` | 动态索引未构建（返回目录地图） | 引导用户用 cosightbot-material 重建索引；**禁止**扫盘或把目录地图当检索结果 |
| 1 | `"error_code": "INDEX_BUILDING"` | section 索引正在全量构建 | 告知用户等待构建完成；期间可用主命令/scan 临时补盲，**禁止**把半成品当结果 |
| 1 | `"error_code": "EMBEDDING_FAILED"` | embedding 服务不可用 | 如实报错并建议检查 `COSIGHTBOT_EMBEDDING_*`；**禁止**静默降级 |
| 0 | `"degraded": true` | A0/Q1 失败，已返回单跳 Tier 树 | 正常使用 Tier 1/2，但必须披露 `degraded_reason`，不得声称完成二跳 |
| 1 | `"ok": false`（read-doc/scan/check-authority/filter-hits/check-conflict/verify-answer 子命令） | 节点不存在 / 参数错误 / 文档不可读 | 按 `error` 字段修正参数重试；节点不存在时先回 Step 1 重拿章节树 |
| 3 | `"hint": "please_run_install"` | 运行环境未初始化 | 执行 `python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py`（幂等、非交互），装完按 `数据根目录下的 .env` 引导配置；不得绕过（S-05） |
| 其他非零 | stderr 报错 | 脚本失败 | 阻断并如实报告（S-05），不得降级为目测/自由文本结论 |

## 检索三步法（摘要）

完整纪律见 `"${CLAUDE_PLUGIN_ROOT}"/rules/pkm/retrieval-discipline.md`（本技能不重复全文，执行前必须阅读）：

1. **Step 1**：小库用主命令拿全量 `merged_overview`；大库/超阈值用 `resolve --question "..."`
   拿动态概览。两者都是硬性入口，不能跳过、不能反问"你有资料吗"。
2. **Step 2**：先判断原始问题与候选的相关性，按 `[F###]` 选**最小充分集**（通常 3–10 篇；复杂枚举/完整性可扩展）并 read-doc 逐篇读全文；
   Tier 1/Tier 2 只是候选池，**不要求把 Tier 1 全读**；Tier 2 按需续读（两种硬步骤情形见上"Tier 1/Tier 2"条）；禁止只看标题跳过整个 `[DIR]`，也禁止不判断相关性直接全读候选池。**精读 = 端到端读完（含 `--line-range` 分段覆盖全文）；打印截断/定向提取不算精读。**
   **未选清单强制披露**：选读定稿前，必须输出"未选候选 + 一句不选理由"清单（覆盖 Tier1 前 30；Tier1 不足 30 则全覆盖）——把"看见了但没选"逼到纸面上；理由必须是内容层面的（命中行/标题与题面维度无关），不得只写"分数低"。
3. **Step 2.5**：候选完整性自查 + 权威候选清单——全量树逐条扫所有 `[F###]`；动态概览核对“候选池规模 / 已选 / 已精读 / 未精读”并说明选择理由，**不需要 Tier 1 全读**；枚举/完整性问题额外披露 Tier 2 覆盖和 scan 补盲；**权威候选清单必须调用 `check-authority` 子命令提取**（merged_overview 直接输出可经 stdin 传入，CC persisted-output spill 用 `--file`；输出逐条标记“已读 / 不读 + 理由”）；无 `check-authority` 可用时才允许用 grep/awk/只读解析脚本从 `merged_overview` 确定性提取标题含 `manual / handbook / operating / SLA / policy / PRD / acceptance / experiment lab / runbook / playbook / ten-step / final / approval / decision / terms` 的 `[F###]` 候选（`tier score title path`），**禁止凭记忆手写清单**；逐条标记“已读 / 不读 + 理由”；Tier1 有标题/类型匹配的权威文档（PRD、operating manual、final terms、ten-step/runbook 等）时必须读，不能因分数低或标题不含题面原词跳过；同类权威文档有多篇时全部读或逐篇说明排除理由；如果唯一文档精确覆盖题面维度/时间窗/区域 split，把它作为主来源，其他文档只能补充/披露冲突；显式决策算法/完整维度阈值表优先于 example defaults/illustrative/initial proposal/draft；已读的精确覆盖文档若不用，必须说明理由。
4. **Step 3**：组织答案，遵守 R1-R11 答案纪律（R1-R5 保真：标题一字不差 / HTML 样式剥除 / 链接原样不编造 / 标题边界完整 / 图片元数据命中必须 Read 实读 PNG；R6-R11：事实与推断分层 / 字段术语逐字 / 多问清单逐项 / 篇幅与披露分区 / 读取口径与引用对账 / 冲突证据采信）。**定稿输出前（单题耗时 < 48 分钟时）必须调用 1 次 `verify-answer` 出口终检**：返回 `PASS` 直接把草稿作为最终答案输出；返回 `REVISE_ONCE` 按 issues 定向修补 1 次（必要时补 1 次 `read-doc --line-range`）后立即输出，**严禁第二次调用 verify-answer 循环**；`--elapsed-seconds >= 2880`（48 分钟）时脚本零延迟短路放行（`PASS_BUDGET_CAP`），让位 50 分钟强制交卷红线。

**答案纪律摘要（详见 retrieval-discipline 第四节 R6-R11）**：

- **R6 事实与推断分层**：超出原文的因果、日期推算、跨文档调和必须标“（推断）”，否则删除；把两篇文档措辞合并成一句因果解释时，该句必须标“（推断）”。
- **R7 字段/术语逐字**：`output_tokens`、`SI CSVs`、`ap-southeast` 等原文术语不得泛化；答案落笔前用 1 行清单核对每个点名术语是否出现在正文；actor/object 用原文名称，答案语言跟随问题。
- **R8 多问/清单逐项**：先编号 `1..N` 再逐条回答；多文档政策/流程题先逐篇列 MUST/例外/边界再合并；completeness/流程题必须显式写源文档的最后一步（如关闭记录）。
- **R9 篇幅与披露分区**：正文 = 问题要求的要点数，事实点写完即停；候选池/未读/干扰项/权限拦截统一放末尾披露区；`info_not_found` 不铺示例数字。
- **R10 读取口径与引用对账**：精读只计 `truncated=false` 或 `--line-range` 分段覆盖全文的端到端读完；定向读取单独计数；每个引用必须有成功 `read-doc` 记录；被拦/未读不得写成“知识库没有”；未覆盖的事实必须明确写“未覆盖”。
- **R11 冲突证据采信**：文档状态（Published/sign-off）> 证据完整度（完整日期+星期+可执行示例）> 内部自洽 > 时间戳；无 `supersedes` 时禁止假设“最新覆盖旧”；**同等状态冲突先按证据完整度选 best-supported，答案先给 best-supported 值再披露其他冲突值；没有 supersedes 不等于没有权威日期**；标准 + ADR 题中，Published ADR 明确声明对齐时，把 ADR 的受控实现视为标准允许路径，不自行要求 exception/amendment；已读 ≥2 篇文档出现数值/日期/规则冲突时，可调用 `check-conflict` 子命令生成结构化裁决矩阵（维度覆盖/权威档位/supersedes/细节完整度 + Python 日期），按其裁决辅助执行 R11，`DISCLOSURE_ONLY` 文档数值严禁并入主结论。

**全局红线**：全量树模式下，所有候选 `[F###]` 逐篇读完且全文 0 命中，才允许回答
"未找到相关内容"；动态模式下，所选候选精读 + 未选候选披露 + 必要时 scan 覆盖证明，
才允许回答"未找到"。未命中时如实反馈，不降级联网搜索或模型自身知识。**引用清单必须与 read-doc 记录对账（R10/S-04）。**

## 会话范围

- 会话标识来自 CC 自动注入的 `CLAUDE_CODE_SESSION_ID`，脚本自动推导 session 路由，**无需**手动传 `--session-key-hash`；老版本 CC 未注入时自动只查 agent 级路由。
- `merged_overview` 已合并全部本地路由（绑定目录 + agent 级收件箱 + 当前会话上传），**一次调用即覆盖**，无需逐路由调用。

## 进度汇报话术

1. 「正在检索知识库章节树」
2. 「检索完成：命中 N 个章节，正在读全文」
3. 「已读完所选候选文档，正在组织答案」

## 检查清单

- [ ] 走了主命令/resolve → read-doc 的三步法，未跳过章节树直接裸答（S-03）；主命令本问题只调了一次
- [ ] 动态模式：已按问题选择最小充分集（通常 3–10 篇）并精读；未读候选数量和 Tier 2 覆盖已披露；`degraded=true` 时已披露原因；未选清单（Tier1 前 30）已逐条给不选理由；标题弱信号候选已看命中行再决定去留；触发 Tier2 硬步骤情形（唯一/最新判别、近重复 ≥2）时已逐条过 Tier2 标题并选读
- [ ] 同主题近重复 ≥2 篇时已做判别性属性对照（日期/数值/版本/专名/区域）再选读，未凭"标题更像"锁定
- [ ] 执行了 Step 2.5 候选完整性自查并明示结论
- [ ] 读取口径已登记：全文精读/定向读取/未读分开计数，未把截断读取写成精读；每个引用都有成功 read-doc 记录（R10/S-04）
- [ ] 答案事实与推断分层（综合句标推断）；字段名/术语逐字并有输出前清单；多问/清单逐项 + 多文档硬约束清单；completeness 含收尾；篇幅 = 问题要求的要点数，披露在末尾；未覆盖明确写“未覆盖”（R6-R10）
- [ ] 冲突证据按 R11 采信并在答案中说明依据；A0 gaps/Q1 未作事实或答案结构
- [ ] 答案中每个结论可回溯到 read-doc 实读记录（S-04）
- [ ] 命中 `image`/`images` 元数据时用 Read 工具实读了全部 PNG（R5）
- [ ] scan 补盲遵守纪律：未自写脚本扫盘；动态模式 scan ≤1 次（`--offset` 翻页计同一次）；Tier1/Tier2 已有候选但只是部分覆盖时，流程/完整性题可做 1 次定向 scan；政策解释/单文档事实/已覆盖全部维度的冲突题默认不 scan；证明不存在先引原文 REDACTED/illustrative/no exception 声明；scan 词为专名/字段名/流程框架名且发现式选取（未拿已选答案自证）；**scan 多词是 AND，优先单稀有词**；命中全是已知文档即停止；命中后 read-doc 实读正文；**截断必响应：truncated/hits_remaining 提示已缩词重扫或 --offset 翻页，截断状态未下"全库没有"结论**；0 命中已换 ≥2 个机械变体重试且未与 A0 gaps 互证
- [ ] 回答“没有单一文档/未找到”前已做覆盖检查：已用 `check-authority`（或确定性解析脚本，非凭记忆）提取权威候选清单（manual/handbook/PRD/final/approval/runbook 等）并逐条标记已读/不读+理由；Tier1/Tier2 标题与命中行、文档类型/权威性先验（PRD/manual/final terms/runbook）、流程题单一 runbook、scan 词含实体/区域/SKU/流程名；已披露检查范围/命中数/截断状态
- [ ] 唯一文档精确覆盖题面维度/时间窗/区域 split 时已作为主来源；已读的精确覆盖文档已使用或说明不采用理由
- [ ] 显式决策算法/完整维度阈值表优先于 `example defaults`/`illustrative`/`initial proposal`/`draft`；示例默认值只作补充或披露
- [ ] 枚举类问题走了脚本统计，数字/条目全部来自脚本 stdout，跨章节逐章节报告
- [ ] Step 3 定稿输出前（耗时 < 48 分钟）已调用 1 次 `verify-answer` 出口终检并按 action 处理：`PASS` 直接输出 / `REVISE_ONCE` 已按 issues 定向修补 1 次后输出且未二次调用 / `PASS_BUDGET_CAP` 已立即交卷；正文引用与 `--read-docs` 已对账（S-04），末尾披露区未读声明行已被正确豁免
- [ ] 未触发任何构建/写入命令（S-01）
- [ ] "未找到"结论满足穷尽原则；hint=no_documents/building 按表处理未谎报
