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

本技能**只允许**下表五个只读入口。**禁止**在本技能内调用任何构建/写入命令（`llamaindex_task_runner` 的 `common_build` / `common_update` 等）。索引缺失或未构建时，引导用户使用 cosightbot-material 完成构建后再检索。

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
| **scan（全文扫描）** | `--agent-id main scan --terms "甲,乙"` | pre-processed 层受控全文扫描（多词 and 共现、忽略大小写），命中带 `[F###]` 接 read-doc |

## 动态概览（resolve）语义

- **小库**（目录树未超上下文阈值）且未传 `--force-dynamic`：`resolve` 退化为全量 `merged_overview`，行为与主命令一致。
- **大库/强制动态**：输出 Tier 1 候选池（带命中行号）+ Tier 2 边缘候选（仅列命中位置）；`stats` 给出 `doc_count/tier1/tier2/candidate_pool/tier1_truncated/tier2_truncated/omitted_candidates/hops/rerank` 等。
- **Tier 1/Tier 2 是候选池，不是必读清单**：先按原始问题、标题、命中行号和综合分选**最小充分集**（通常 3–10 篇；复杂枚举/完整性可扩展）精读；**不要求把 Tier 1 逐篇读完**。Tier 2 按需续读，并在答案中披露候选池规模、已选/已精读/未精读数量。枚举/完整性问题才扩大覆盖（Tier1 选读 + Tier2 命中靠前 + 必要时 scan）。
- **A0 是诊断，不是答案**：`quality`/`gaps`/Q1、Tier 命中行、rerank 分数都只是召回线索；缺口里的人名/客户名/数值若目标文档没有，不得当事实，也不得让 gaps 决定答案结构。A0 判 MISS/PARTIAL 不等于候选池没有答案，必须自己检查 Tier 1/2。
- **scan 闸门**：Tier1/Tier2 已有候选时先 read-doc，**禁止用 scan 代替 read-doc**；动态模式每问题最多 1 次 scan，scan 词必须是专名/字段名/流程框架名（如 `allowlisted_tenants`、`per_route_group_budget`、`h200-80`、`ten-step`、`restoration sprint`、`fidelity`、`experimentation lab`、`final approved`），命中全是已知文档立即停止。仅在候选读完仍缺正文事实，或枚举/完整性/`info_not_found` 需证明全库不存在时使用；**流程/完整性题如果已读候选没有一篇覆盖全部步骤/维度，允许 1 次定向 scan**；政策解释题、单文档事实题、已有候选且已覆盖全部维度的冲突题默认不 scan；证明“不存在”时先引用原文的 REDACTED / illustrative / no exception / 无记录声明，只有原文证据不足才 scan；**scan 多词是 AND，默认选 1 个最稀有的专名/字段名/文档类型词，确定会共现才用多词；scan 输出被截断时只能写“已检查范围内未找到”，不得下“全库没有”结论。**
- **覆盖检查**：回答“没有单一文档/未找到”前，先从 `merged_overview`（或持久化输出）用 grep/awk/只读解析脚本确定性提取标题/路径含 `manual / handbook / operating / SLA / policy / PRD / acceptance / experiment lab / runbook / playbook / ten-step / final / approval / decision / terms` 的候选，逐条标记“已读/不读+理由”；匹配未读不得下结论。再检查 Tier1/Tier2 标题与命中行及文档类型/权威性先验；**唯一精确覆盖题面维度/时间窗/区域拆分的文档作为主来源**，其他只补充/披露冲突；显式算法/完整阈值表优先于 `example defaults` / `illustrative` / `initial proposal` / `draft`；已读的精确覆盖文档若不用，必须说明理由。流程题优先找单一权威 runbook；展示的 250 篇不等于全候选池；否定结论必须披露检查范围、scan 词、命中数和截断状态。
- `degraded=true`：A0/Q1 二跳失败，本次是单跳收敛；必须在答案中显式披露 `degraded_reason`，不得假装完成二跳。
- `error_code=DYNAMIC_INDEX_MISSING`：动态索引未构建，返回的是目录地图；引导用户重建索引，**不得**自行扫盘或退回 scan 冒充结果。
- `error_code=INDEX_BUILDING`：section 索引正在全量构建（会清空旧行）；此时不要检索动态树，等待构建完成或改用主命令/scan 临时补盲。
- `error_code=EMBEDDING_FAILED`：embedding 服务不可用；如实报错，**不得**静默降级为无向量结果。
- `rerank=false`：rerank 未配置或失败，已使用向量/BM25 分数；在答案或进度中如实说明。

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
| 1 | `"ok": false`（read-doc/scan 子命令） | 节点不存在 / 参数错误 / 文档不可读 | 按 `error` 字段修正参数重试；节点不存在时先回 Step 1 重拿章节树 |
| 3 | `"hint": "please_run_install"` | 运行环境未初始化 | 执行 `python "${CLAUDE_PLUGIN_ROOT}"/scripts/install.py`（幂等、非交互），装完按 `数据根目录下的 .env` 引导配置；不得绕过（S-05） |
| 其他非零 | stderr 报错 | 脚本失败 | 阻断并如实报告（S-05），不得降级为目测/自由文本结论 |

## 检索三步法（摘要）

完整纪律见 `"${CLAUDE_PLUGIN_ROOT}"/rules/pkm/retrieval-discipline.md`（本技能不重复全文，执行前必须阅读）：

1. **Step 1**：小库用主命令拿全量 `merged_overview`；大库/超阈值用 `resolve --question "..."`
   拿动态概览。两者都是硬性入口，不能跳过、不能反问"你有资料吗"。
2. **Step 2**：先判断原始问题与候选的相关性，按 `[F###]` 选**最小充分集**（通常 3–10 篇；复杂枚举/完整性可扩展）并 read-doc 逐篇读全文；
   Tier 1/Tier 2 只是候选池，**不要求把 Tier 1 全读**；Tier 2 按需续读；禁止只看标题跳过整个 `[DIR]`，也禁止不判断相关性直接全读候选池。**精读 = 端到端读完（含 `--line-range` 分段覆盖全文）；打印截断/定向提取不算精读。**
3. **Step 2.5**：候选完整性自查 + 权威候选清单——全量树逐条扫所有 `[F###]`；动态概览核对候选池规模、已选/已精读/未精读并说明选择理由；从 `merged_overview` 确定性提取标题/路径匹配 manual、handbook、PRD、final、approval、runbook 等的候选，逐条标记已读/不读+理由；匹配未读不得回答“没有单一文档/未找到”。枚举/完整性问题额外披露 Tier 2 覆盖和 scan 补盲；权威候选必须读，不能因分数低或标题不含题面原词跳过；唯一精确覆盖文档作主来源，显式算法/完整阈值表优先于示例默认值。
4. **Step 3**：组织答案，遵守 R1-R11 答案纪律（R1-R5 保真：标题一字不差 / HTML 样式剥除 / 链接原样不编造 / 标题边界完整 / 图片元数据命中必须 Read 实读 PNG；R6-R11：事实与推断分层 / 字段术语逐字 / 多问清单逐项 / 篇幅与披露分区 / 读取口径与引用对账 / 冲突证据采信）

**答案纪律摘要（详见 retrieval-discipline 第四节 R6-R11）**：

- **R6 事实与推断分层**：超出原文的因果、日期推算、跨文档调和必须标“（推断）”，否则删除；把两篇文档措辞合并成一句因果解释时，该句必须标“（推断）”。
- **R7 字段/术语逐字**：`output_tokens`、`SI CSVs`、`ap-southeast` 等原文术语不得泛化；答案落笔前用 1 行清单核对每个点名术语是否出现在正文；actor/object 用原文名称，答案语言跟随问题。
- **R8 多问/清单逐项**：先编号 `1..N` 再逐条回答；多文档政策/流程题先逐篇列 MUST/例外/边界再合并；completeness/流程题必须显式写源文档的最后一步（如关闭记录）。
- **R9 篇幅与披露分区**：正文 = 问题要求的要点数，事实点写完即停；候选池/未读/干扰项/权限拦截统一放末尾披露区；`info_not_found` 不铺示例数字。
- **R10 读取口径与引用对账**：精读只计 `truncated=false` 或 `--line-range` 分段覆盖全文的端到端读完；定向读取单独计数；每个引用必须有成功 `read-doc` 记录；被拦/未读不得写成“知识库没有”；未覆盖的事实必须明确写“未覆盖”。
- **R11 冲突证据采信**：文档状态（Published/sign-off）> 证据完整度（完整日期+星期+可执行示例）> 内部自洽 > 时间戳；无 `supersedes` 时禁止假设“最新覆盖旧”；**同等状态冲突先按证据完整度选 best-supported，答案先给 best-supported 值再披露其他冲突值；没有 supersedes 不等于没有权威日期**；标准 + ADR 题中，Published ADR 明确声明对齐时，把 ADR 的受控实现视为标准允许路径，不自行要求 exception/amendment。

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
- [ ] 动态模式：已按问题选择最小充分集（通常 3–10 篇）并精读；未读候选数量和 Tier 2 覆盖已披露；`degraded=true` 时已披露原因
- [ ] 执行了 Step 2.5 候选完整性自查并明示结论
- [ ] 读取口径已登记：全文精读/定向读取/未读分开计数，未把截断读取写成精读；每个引用都有成功 read-doc 记录（R10/S-04）
- [ ] 答案事实与推断分层（综合句标推断）；字段名/术语逐字并有输出前清单；多问/清单逐项 + 多文档硬约束清单；completeness 含收尾；篇幅 = 问题要求的要点数，披露在末尾；未覆盖明确写“未覆盖”（R6-R10）
- [ ] 冲突证据按 R11 采信并在答案中说明依据；A0 gaps/Q1 未作事实或答案结构
- [ ] 答案中每个结论可回溯到 read-doc 实读记录（S-04）
- [ ] 命中 `image`/`images` 元数据时用 Read 工具实读了全部 PNG（R5）
- [ ] scan 补盲遵守纪律：未自写脚本扫盘；动态模式 scan ≤1 次；流程/完整性缺步骤/维度时可做 1 次定向 scan；scan 词为专名/字段名/流程框架名；多词 scan 确认共现后才使用；命中后 read-doc 实读正文；截断时不下“全库没有”结论
- [ ] 回答“没有单一文档/未找到”前已确定性提取权威候选并逐条标记已读/不读+理由；已检查覆盖、文档类型/权威性和单一 runbook，并披露范围/命中数/截断状态
- [ ] 唯一精确覆盖的权威文档已作为主来源；显式算法/完整阈值表未被示例默认值替代；已读权威候选若不采用，已说明理由
- [ ] 枚举类问题走了脚本统计，数字/条目全部来自脚本 stdout，跨章节逐章节报告
- [ ] 未触发任何构建/写入命令（S-01）
- [ ] "未找到"结论满足穷尽原则；hint=no_documents/building 按表处理未谎报
