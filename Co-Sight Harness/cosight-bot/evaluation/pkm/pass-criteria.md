# CoSightBot PKM 验收标准（pass-criteria）

> 验收用例 AC-01~AC-03、AC-06（标书链用例见 cosightbot-soc 包），判定方法与通过阈值。执行方式：全新工作目录按 README quickstart 走一遍，逐条对照判定。每条用例给出 Given-When-Then 与**程序化判定**（可通过脚本/退出码验证的部分）。

## AC-01 绑定与自动首建

- **Given**：含 5–10 个混合格式文档（md/pdf/docx/xlsx）的目录
- **When**：对 CoSightBot 说"绑定为资料目录"
- **Then**：绑定成功且自动完成首次构建，章节树可查询

| 维度 | 判定方法 | 通过阈值 |
|---|---|---|
| 绑定生效 | `material_cli.py status` 输出 `configured:true` 且 `exists:true` | 是 |
| 自动构建 | 绑定后无需手动 build，`status` 显示 `index_status:"ready"`，且检索主命令返回 `ready:true` + overview 含 `[F###]` 节点 | 全部文档入库（failed=0） |
| 章节树生成 | `retrieve_cli.py` 主命令返回 `merged_overview` 含 `[F###]` 节点 | 每个入库文档一个节点 |
| 只读约束 | 检索动作未触发任何构建（S-01） | 无构建调用 |

## AC-02 检索三步法

- **Given**：已构建索引的资料目录
- **When**：跨文档提问（答案分散在 ≥2 篇文档）
- **Then**：章节树 → read-doc 逐篇读全文 → 综合答案

| 维度 | 判定方法 | 通过阈值 |
|---|---|---|
| 章节树先行 | 会话记录中首个检索调用是主命令拿 `merged_overview` | 是 |
| 实读全文 | 答案引用的每个 `[F###]` 都有对应 read-doc 调用记录 | 100% |
| 穷尽原则 | 答"未找到"前所有候选 `[F###]` 均已读完 | 无一遗漏 |
| 保真红线 | 长标题一字不差（R1）；无编造 URL（R3） | 抽检通过 |

## AC-03 会话级 ingest

- **Given**：检索会话进行中，用户给一个 PDF 路径
- **When**：说"加入知识库"
- **Then**：落 `upload_files/<session_hash>/` 并自动增量入库，同会话可检索

| 维度 | 判定方法 | 通过阈值 |
|---|---|---|
| 会话隔离 | 文件落在 `data/workspace-main/llamaindex_data/upload_files/<sha256[:16]>/` | 路径正确 |
| 自动入库 | ingest 返回 `ok:true`，随后检索主命令的 overview 出现该文档节点、read-doc 可读取，全程无手动 build | 是 |
| 同会话可检索 | 针对该 PDF 内容的提问命中 `[F###]` | 命中 |
| 优雅降级 | 无 `CLAUDE_CODE_SESSION_ID` 时降级 agent 级目录并明确提示 | 降级+提示 |

## AC-06 进度与完成反馈

- **When**：分钟级任务（首次构建、大目录刷新、KB 构建、批量应答）执行
- **Then**：启动即告知、进度可查、完成时主动汇报摘要

| 维度 | 判定方法 | 通过阈值 |
|---|---|---|
| 启动告知 | 后台任务启动后立即回复"已开始，完成后我会汇报" | 是 |
| 进度可查 | 中途询问进度时读取任务输出尾部如实回答 | 与实际一致 |
| 完成汇报 | 完成时给出结构化摘要（新增 X / 跳过 Y / 失败 Z） | 摘要与脚本统计一致 |
| 失败如实 | 脚本非零退出时报告失败原因，不声称成功（S-05） | 无一例外 |

---

## Phase 3 动态概览验收（AC-07~AC-13）

> 数据口径：51W = 511,962 文档 / 555,644 sections；问题集为 Phase2 500 题（470 题有期望文档，742 refs）。详细实验见 `Phase3/实验验证记录.md` EXP-003/010~015。

### AC-07 51W 动态检索召回与延迟

- **Given**：51W 全量索引（schema v2、稳定 F###、section 向量 + FTS + ANN）
- **When**：跑完整 500 题
- **Then**：Tier1 recall ≥80%，Tier1∪Tier2 >80%，hop0 p95 ≤30s；全链路 p95 ≤60s 可接受（初始目标 30s）；A0/Q1 全链路 degraded ≤5%

| 指标 | 阈值 | 当前结果 | 判定 |
|---|---:|---:|---|
| Tier1 recall（H1 默认） | ≥80% | **81.13%** | 通过 |
| Tier1∪Tier2 | >80% | **83.56%** | 通过 |
| hop0 p95 | ≤30s | **23.04s** | 通过 |
| A0/Q1 50 题 Tier1 | 报告值 | **85.9%**（P1 同题） | 通过 |
| A0/Q1 degraded | ≤5% | **2%（1/50）**（P1；基线 4%） | 通过 |
| 全链路 p95（hop0+A0+hop1） | ≤60s 可接受（初始 30s） | **27.78s**（Qwen）/ **35.36s**（minimax） | 通过 |

> P1 将 evidence 从 60K 降到 30K：p50 23.67s、p95 27.78s，Tier1 不变，degraded 1/50。该结果为 `Qwen3_6-35B-A3B` 口径。P2 同题 20 题对比：minimax-m3 / Qwen / ANTHROPIC 的 Tier1 均 95%，p95 分别为 **35.36s / 27.22s / 28.49s**，均无降级。
>
> **2026-10-21 用户口径**：当前阶段准确率优先，全链路 p95 在 60s 内可接受（30s 是初始目标，不要求严格卡死）。三模型准确率相同，Qwen/ANTHROPIC 快约 7–8s 但未带来准确率提升，因此**保留默认 minimax-m3**；ANTHROPIC/Qwen 作为可选备用。
>
> 口径说明：H1 81.13% 是在 tokenizer 修复前的 51W 索引与查询代码上测得。P0 同一 100 题复测显示新查询 tokenizer 与旧基线 Tier1 完全持平（85.35% vs 85.35%），无系统性退化；但 51W 索引仍是旧 tokenizer，最终指标仍需全量重索引后复测，当前 H1 结果按**历史结果**看待。

### AC-08 ANN

- **Given**：51W 555,644 sections，IVF-PQ 已建
- **When**：同题对比 flat 与 ANN nprobes=20/50/100
- **Then**：n50 同题召回不低于 flat，p50 ≤500ms

当前：flat p50 1,147.9ms / recall@10 45%（9/20）；ANN n50 p50 **215.0ms**、同题 recall@10 45%、top10 重叠 92% → **通过**。

### AC-09 中文语料

- **Given**：中文 md + 中文 PDF/DOCX/XLSX/扫描件
- **When**：分词、正文/骨架 FTS、section 向量、read-doc、动态 resolve
- **Then**：中文词可命中正确文档，路径/OCR 不丢失，动态不降级

当前：语料 A 4 docs/12 sections、语料 B 9 docs/46 sections/106 pointers；四类中文查询 FTS/向量 top-1 均正确；动态 2 题无降级 → **通过（功能验证；无标注 recall 指标）**。

### AC-10 M-3 主文档兜底

- **Given**：主文档为空/仅 TOC/缺失，且存在 `_chapters/`
- **When**：构建 overview + section 索引 + 动态 resolve
- **Then**：章节进树、进 section 索引、计入 doc_count；有 `_pages`/`_slides` 时不重复提升；未提升章节仍可 read-doc alias

当前隔离验证：4 docs/9 sections；`M3PROMOTED` FTS 命中 F001；动态 doc_count=4、Tier1=4、A0 FULL_HIT → **通过**。

### AC-11 51W 构建规模

| 指标 | 阈值 | 当前结果 | 判定 |
|---|---:|---:|---|
| 构建耗时 | 可接受 | **8h15m55s** | 通过 |
| 文档/章节/指针 | failed=0 | **511,962 / 555,644 / 5,370,750** | 通过 |
| 索引体积 | ≤8GB | **4.6GB** | 通过 |
| ANN | 全部索引 | **0 unindexed** | 通过 |

### AC-12 overview 构建期刷新

- **Given**：>50,000 文件
- **When**：构建
- **Then**：不做中间全量刷新，仅首尾刷新，收尾树完整

当前：51W 默认关闭中间刷新；437 隔离首次 14.8ms、收尾 471.8ms，指标不变 → **通过**。

### AC-13 tokenizer 句末标点

- **Given**：英文词/标识符位于句末（`M3PROMOTED.`）
- **When**：建立 FTS 并用无标点查询
- **Then**：可命中；`ERR_401_02`/`v2.3.1`/`192.168.1.1` 仍保持整体

当前：新 tokenizer 单测通过，M-3 小库重建后命中；P0 同一 100 题复测 Tier1 与旧基线持平（85.35% vs 85.35%），无系统性退化；**51W 现有索引仍为旧 tokenizer，需下次全量重建生效** → 代码通过，索引待重建。

---

## 回归用例（可重复执行）

| # | 场景 | 期望 |
|---|---|---|
| R-01 | 无 LLM/embedding 配置时 bind 自动构建 | 硬失败非零退出 + 状态落 failed |
| R-02 | requirements.txt 内容变化后跑任一技能 | exit 3 + please_run_install |
| R-03 | ingest --global 后 remove --global | inbox 路由出现又消失 |
| R-04 | unbind 后 | 索引目录清除、源目录原件零改动 |
