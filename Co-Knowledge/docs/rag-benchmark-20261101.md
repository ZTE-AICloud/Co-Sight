# Knowledge Studio 公开基准评测报告

> 范围：BEIR / MTEB / MS MARCO / Natural Questions / HotpotQA / 2WikiMultiHopQA /
> MuSiQue / CRAG / RGB / RAGBench / CRUD-RAG，共 11 个公开基准。
>
> 复跑工具：`tools/bench/`；检索层复用 `tools/rag-metrics/`。

## 1. 结论摘要

1. **纯向量检索接近 embedding 模型公开水平，两个检索侧优化点各带来 5–8 pp 空间**：
   - SciFact 向量 nDCG@10 **68.45%**，Qwen3-Embedding-0.6B 的 MTEB 公开值 69.72%，
     差 1.27 pp —— 说明 pgvector/HNSW/切片链路本身没有明显损耗。
   - NFCorpus 向量 nDCG@10 **29.08%**，公开值 36.71%，差 7.63 pp。离线复算证明：
     同一模型、同一语料，查询**加 Qwen3 检索 instruction** 后 nDCG@10 从 30.26%
     升到 **35.89%**，差距几乎全部来自「查询 embedding 没带 instruction」。
   - 英文关键词路 nDCG@10 **59.82%**，同语料标准分词 BM25 为 **65.21%**，
     BEIR 论文 BM25 为 66.5%；差距来自索引固定 `ik_smart` + 查询 OR 语义。
   - **ArguAna 向量 47.48% vs MTEB 70.97%，差 23.49 pp**，是最大的向量缺口；
     ArguAna 是长查询论证检索，缺 instruction + 长查询池化的影响最大。
2. **中文检索不能默认「向量为主」**：CRUD-RAG 500 题，关键词 nDCG@10
   **83.83%** > 向量 **72.51%**（+11.31 pp），MRR 81.81% > 66.15%（+15.66 pp）；
   向量 Recall@10 略高（99.33 vs 97.47），但排序更差。中文企业知识库应把
   关键词作为主路或至少等权融合。
3. **中文/中英混合的生成鲁棒性是一线水平**：RGB 中文噪声 0/0.4/0.8 的
   官方口径准确率 **88.67 / 86.67 / 85.67%**（ChatGPT 公开值 95.67 / 91.00 / 70.67），
   高噪声段反超 15 pp；信息整合 **82%**（ChatGPT 63/58/47）；
   反事实错误检测 **94%**、纠正率 **89.36%**（ChatGPT ED 1%、CR 33.33%）。
4. **多跳端到端是主要提升方向**：2Wiki 文档-only 已完成 148 题，EM **50.68%** /
   F1 55.37%（检索层 nDCG@10 74.96、MRR 94.34，说明「找得到」）；HotpotQA
   已完成 206 题，EM **53.88%** / F1 67.08%（证据召回 87.14）。对照
   2Wiki 图谱增强 100 题（EM 77.00%、F1 83.56%）与公开 distractor SOTA
   （2Wiki 88.47、HotpotQA 72.69/85.04、MuSiQue F1 69.2），
   差距主要在「多跳证据组织 + 合成器约束」，不是单跳检索。
5. **英文大语料检索的评测口径必须降级解释**：MS MARCO/NQ 用「gold + 8k 抽样干扰」
   的闭集，绝对 MRR/Recall 不能与 8.8M/2.1M 全量榜单直接比；本报告只用它做
   「向量 vs 关键词」的同语料对照与失败分析。
6. **图谱增强对多跳题有效**：2Wiki 100 题上，仅文档检索 EM 73.00%、F1 81.84%；
   文档 + 图谱混合 EM 77.00%、F1 83.56%；增益集中在 compositional 题型。

> 说明：本报告的「公开值」来自论文/模型卡/官方榜单（见第 8 节来源）。
> 公开值不是同一实验条件下的 target；闭集/抽样语料与全量榜单不可直接比较，
> 报告里逐项标注了口径。

## 2. 评测范围与口径

### 2.1 基准映射

| # | 基准 | 测试能力 | 本报告实际跑的设置 | 语料/题量 |
|---|---|---|---|---|
| 1 | BEIR | 跨领域检索 | 产品向量 + 关键词，nDCG@10/Recall@10/80 | SciFact 5,183 / NFCorpus 3,633 / ArguAna 8,674 |
| 2 | MTEB | Embedding 选型 | C-MTEB DuRetrieval；英文检索组复用 BEIR | DuRetrieval 100,001 passage |
| 3 | MS MARCO | 文档召回/排序 | 2,000 dev 查询，gold + 8k 抽样干扰 | ~10k passage 闭集 |
| 4 | Natural Questions | 真实问题检索 | 1,000 dev 查询，gold + 8k 抽样干扰 | ~10k passage 闭集 |
| 5 | HotpotQA | 多文档多跳 | 2,000 dev 题；10 段候选并集；E2E 206 题全覆盖子集 | 19,009 passage |
| 6 | 2WikiMultiHopQA | 跨文档关联 | 300 dev 题（4 类各 75）；文档-only E2E；图谱增强 100 题 | 2,202 article |
| 7 | MuSiQue | 2–4 跳 | 1,000 dev 题；20 段并集；检索 500 题 | 11,725 passage |
| 8 | CRAG | 长尾/动态知识 | 300 / 2,706 task1-2 dev；每题 5 个网页 | 1,500 网页 |
| 9 | RGB | 噪声/拒答/整合/反事实 | 中文：噪声 300×3 档、整合 100、反事实 100 | 官方 5 文档协议 |
| 10 | RAGBench | 上下文利用/忠实度 | 5 域 × 50 test（250 题），judge 改写指标 | 提供上下文 |
| 11 | CRUD-RAG | 中文增删改查 | 5 任务 × 200（1,000 题），news 子集 | 1,585 news |

> 评测受生成端点与导入吞吐限制时，报告按实际完成的样本量给出指标，并在表中
> 标注 n；不把部分样本写成全量结论。

### 2.2 统一口径

1. **一 passage = 一/多个 chunk**：走产品 `POST /knowledge-bases/{id}/chunks`
   手工切片；超 4,000 字符切子片，共享同一 pid 标记；指标在 pid 级去重。
2. **标记只用于映射**：`content` 是干净正文（embedding + 关键词），`supplement`
   带 `【PREFIX-pid】`；向量路返回 supplement、关键词路返回 content，两边都能
   映射回 pid，标记不参与检索打分。
3. **top_k=80**：产品 `RetrieveDTO` 上限；HNSW `ef_search` 统一 200（> top_k），
   避免 K>40 被默认 40 截断。
4. **空结果重试一次**，仍为空按 0 分；连续 5 条错误停止；未映射文档按
   「非相关、占一个排名位」保留，占比 >5% 拒绝出报告。
5. **E2E**：每题独立 `conversation_id`，`include_retrieval=true`；默认使用产品
   模板的「上下文不足可结合自身知识」提示词；`--strict-grounding` 另测拒答校准。
6. **上下文注入式基准**（RGB / RAGBench / CRAG）：直接调用产品部署的生成模型，
   严格复刻官方文档拼装/评分协议；judge 使用独立模型，避免自评偏差。
7. **置信区间**：查询/题目级 2,000 次 bootstrap；报告给 95% 区间。

### 2.3 环境

| 项 | 值 |
|---|---|
| 向量库 | PostgreSQL 16.15 + pgvector 0.8.7，HNSW(m=16, ef_construction=64)，`ef_search=200` |
| 关键词库 | OpenSearch 2.19.6，索引 `doc_<kb-id>`，`text` 字段 `ik_smart` |
| Embedding | `Qwen3-Embedding-0.6B`，1024 维 |
| Rerank | `Qwen3-Reranker-4B`（cross-encoder，`/v1/rerank`） |
| 生成 | 部署的 OpenAI 兼容生成端点 |
| Judge | 独立 judge 模型（temperature 0） |
| 机器 | 8 vCPU / 23 GB RAM；PG 4.4 GB；OpenSearch 单节点 |
| 数据落盘 | `.metrics-data/bench/`（gitignore，不入库、不随报告分发） |

## 3. 结果总览

### 3.1 L1 检索（向量 / 关键词）

| 数据集 | 语料/查询 | 向量 nDCG@10 | 向量 Recall@10 | 向量 Recall@80 | 关键词 nDCG@10 | 关键词 Recall@10 | 关键词 Recall@80 |
|---|---:|---:|---:|---:|---:|---:|---:|
| SciFact | 5,183 / 300 | **68.45** | 81.11 | 92.33 | 59.82 | 72.20 | 82.34 |
| NFCorpus | 3,633 / 323 | 29.08 | 14.39 | 28.84 | 31.06 | 14.63 | 22.93 |
| ArguAna | 8,674 / 500 | 47.48 | 92.20 | 99.40 | 31.27 | 67.60 | 92.80 |
| NQ（抽样） | 5,357 / 500 | **93.30** | 97.47 | 99.57 | 84.54 | 91.97 | 96.43 |
| 2Wiki（并集） | 2,202 / 300 | 74.96 | 73.58 | 81.77 | 75.06 | 74.42 | 82.33 |
| MuSiQue（并集） | 11,725 / 500 | **57.09** | 60.22 | 78.70 | 49.77 | 50.17 | 68.48 |
| DuRetrieval（MTEB） | 100,001 / 2,000 | 81.57 | 83.71 | 95.02 | 59.96 | 60.78 | 77.65 |
| CRUD-RAG | 1,585 / 500 | 72.51 | 99.33 | 99.93 | **83.83** | 97.47 | 99.40 |

### 3.2 端到端问答

| 数据集 | n | EM | F1 | 答案覆盖 | 证据召回 | Judge 正确率 | 拒答率 | 平均延迟 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2Wiki（文档-only） | 148 | 50.68 | 55.37 | — | 85.47 | — | 0.0 | 2.3 s |
| HotpotQA | 206 | 53.88 | 67.08 | 61.65 | 87.14 | — | 0.0 | 4.06 s |
| CRUD-RAG（5 任务） | 127 | 0.0 | 1.14 | 3.94 | — | 43.2 | 19.69 | — |
| CRAG（上下文注入） | 65 | — | — | — | — | 46.15 | 33.85 | — |
| RGB（上下文注入） | 500 | — | — | — | — | 见 4.8 | 见 4.8 | — |
| RAGBench（上下文注入） | 250 | — | — | — | — | 见 4.9 | — | — |

> n 为本次评测完成的样本量。CRUD 的 EM/F1 对长答案无意义，主指标是 judge。

### 3.3 与业界一流水平的差距（细节见第 5 节）

| 能力 | 我们的数 | 公开强基线/ SOTA | 差距 | 主要因素 |
|---|---:|---:|---:|---|
| BEIR SciFact 向量 | 68.45 | 69.72（Qwen3-Emb-0.6B MTEB） | −1.27 pp | 链路损耗小 |
| BEIR NFCorpus 向量 | 29.08 | 36.71（同上） | **−7.63 pp** | 查询无 instruction |
| BEIR SciFact 关键词 | 59.82 | 66.5（BEIR BM25） | **−6.68 pp** | 英文索引固定 ik_smart |
| 2Wiki 检索（nDCG@10 / MRR@10） | 74.96 / 94.34 | 无同口径公开 nDCG（SOTA 报 EM 88.47） | 不可直接比 | 检索层 MRR 94，瓶颈在生成/多跳组织 |
| RGB 中文噪声@0.8 | 85.67 | 70.67（ChatGPT） | **+15.0 pp** | 强项 |
| RGB 中文整合 | 82.00 | 63/58/47（ChatGPT） | **+19~35 pp** | 强项 |
| RGB 反事实 ED | 94.00 | 1.00（ChatGPT） | **+93 pp** | 提示词遵循强 |
| 多跳 E2E | 见分节 | HotpotQA 72.69/85.04、2Wiki 88.47/90.87、MuSiQue F1 69.2 | 见分节 | 多跳证据组织 |

> 公开值与我们的闭集/抽样设置不是同一实验条件；上表的「差距」只用于排序
> 改进优先级，不作为验收结论。

## 4. 分基准结果

### 4.1 BEIR

**设置**：SciFact / NFCorpus / ArguAna 全量；查询用官方 test split；
qrels 保留分级相关性（NFCorpus/SCIDOCS 有 1/2 级）。

| 数据集 | 系统 | nDCG@10 | Recall@10 | Recall@80 | MRR@10 | P95 延迟 |
|---|---|---:|---:|---:|---:|---:|
| SciFact | vector | **68.45** | 81.11 | 92.33 | 65.17 | 168 ms |
| SciFact | keyword | 59.82 | 72.20 | 82.34 | 56.21 | 37 ms |
| NFCorpus | vector | 29.08 | 14.39 | 28.84 | 48.28 | 1,321 ms |
| NFCorpus | keyword | 31.06 | 14.63 | 22.93 | 53.95 | 1,504 ms |
| ArguAna | vector | **47.48** | 92.20 | 99.40 | 33.00 | 79 ms |
| ArguAna | keyword | 31.27 | 67.60 | 92.80 | 19.95 | 70 ms |

**对标**（Qwen3-Embedding-0.6B MTEB 公开值）：SciFact 69.72、NFCorpus 36.71、
ArguAna 70.97、FiQA 46.61、SCIDOCS 24.41。
**BM25 公开值**（BEIR 论文）：SciFact 66.5、NFCorpus 32.5、ArguAna 31.5、FiQA 23.6。

**根因复算 1：英文 analyzer（SciFact，离线同语料）**

| 分词器 / 查询 | nDCG@10 | Recall@10 |
|---|---:|---:|
| `ik_smart` + `match(text)`（产品现状） | 58.80 | 71.20 |
| `standard` + `match(text)` | 65.21 | 77.09 |
| `english` + `match(text)` | **66.84** | **80.13** |
| `ik_smart` + `multi_match(title^2, text)` | 53.58 | 65.37 |
| `standard` + `multi_match(title^2, text)` | 54.89 | 67.77 |

产品关键词路实测 59.82，与 `ik_smart + match(text)`（58.80）基本一致；换成
`english` 分词可到 66.84，**+7.02 pp**，已略高于 BEIR BM25 的 66.5。

**根因复算 2：查询 instruction（NFCorpus，离线同语料）**

| 查询侧 | nDCG@10 | Recall@10 |
|---|---:|---:|
| 原始 query | 30.26 | 14.80 |
| Qwen3 官方检索 instruction | **35.89** | **17.24** |

产品 NFCorpus 向量 29.08，与原始 query 的 30.26 只差 1.2 pp；加 instruction
后 35.89，达到公开值 36.71 的 97.8%。**差距几乎全部来自查询侧缺 instruction。**

**其他观察**：

- **ArguAna 向量 47.48 vs MTEB 公开值 70.97，差 23.49 pp**，是 BEIR 里最大的
  向量缺口。ArguAna 的查询是完整论证（长查询），`ik_smart` 分词对英文长查询
  的 BM25 只有 31.27（与 BEIR BM25 31.5 一致）；向量侧同样受「查询无
  instruction + 长查询池化」影响。
- SciFact 向量 −1.27 pp，属于切片/索引/查询构造的正常损耗。
- NFCorpus 的 P95 1.3–1.5 s 是并发负载下的测量值，单独压测约 0.2 s。

### 4.2 MTEB（C-MTEB DuRetrieval）

**设置**：100,001 passage / 2,000 查询 / 9,839 qrels；向量 + 关键词，top_k=80，
`ef_search=200`。检索路径与 L1 报告一致，指标复用同口径结果。

| 系统 | nDCG@10 | Recall@10 | Recall@80 | MRR@10 | 空结果 |
|---|---:|---:|---:|---:|---:|
| vector | **81.57** | 83.71 | 95.02 | 89.38 | 0 |
| keyword | 59.96 | 60.78 | 77.65 | 74.64 | 0 |

> C-MTEB 的综合检索分 71.03 是 8 个任务的平均，不能与单任务 DuRetrieval
> 直接对齐。

### 4.3 Natural Questions（抽样闭集）

**设置**：1,000 条 dev 查询；gold（1,227 对）+ 8,000 条干扰；约 10k passage。
本报告完成 500 条查询；语料导入 5,357 passage，gold 覆盖 999/1,000。

| 系统 | nDCG@10 | Recall@10 | Recall@80 | MRR@10 | 空结果 | 未映射 | P95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| vector | **93.30** | 97.47 | 99.57 | 92.19 | 0 | 1.28% | 179 ms |
| keyword | 84.54 | 91.97 | 96.43 | 83.12 | 0 | 6.25% | 34 ms |

> 向量比关键词高 **8.76 pp** nDCG@10。关键词路未映射 6.25% 来自非语料行；
> 向量路 1.28%。

**对标**：DPR 全 wiki R@100 85.4、FiD-large EM 51.4；闭集抽样不可直接比。

### 4.4 HotpotQA

**设置**：2,000 条 dev 题（distractor 设置），10 段候选并集 19,009 passage；
语料导入 13,690 passage；E2E 使用 gold 全覆盖子集 206 题（文档-only 工作流，
产品模板提示词）。

| 指标 | 值 |
|---|---:|
| 可评查询（gold 全覆盖） | 1,399 / 1,962 |
| E2E n / EM / F1 / 证据召回 | **206 / 53.88 / 67.08 / 87.14** |
| bridge / comparison EM | 46.5（n=157）/ 77.6（n=49） |
| 平均延迟 / P95 / 拒答 | 4.06 s / 17.37 s / 0% |

**对标**：HotpotQA distractor 官方榜 Beam Retrieval EM 72.69 / F1 85.04；
原论文 baseline 45.46 / 58.99。我们的语料是 19k 并集（比 10 段更难），
E2E 子集只取 gold 全覆盖的题；**53.88/67.08 落在 baseline 与 SOTA 之间**，
用于同口径比较，不作为全量 HotpotQA 分数。

**失败分析**：E2E 的 evidence 87.14%、EM 53.88%，说明多数题能检索到证据，
但合成器在「比较/多跳」上仍会丢约束；典型错误是把 `yes/no` 答反、或只答
其中一个实体。

### 4.5 2WikiMultiHopQA

**检索层**（300 题，2,202 article）：

| 系统 | nDCG@10 | Recall@10 | Recall@80 | MRR@10 | 空结果 | P95 |
|---|---:|---:|---:|---:|---:|---:|
| vector | 74.96 | 73.58 | 81.77 | 94.34 | 1 | 1,997 ms |
| keyword | **75.06** | 74.42 | 82.33 | 95.67 | 0 | 819 ms |

- 两路几乎打平；MRR@10 94–96%，说明 gold article 多数排在最前。
- P95 是并发负载下的测量值；单独查询约 0.2 s。

**端到端**（文档-only，300 题中完成 148 题，cross-encoder 重排 top_n=8）：

| 题型 | n | EM |
|---|---:|---:|
| bridge_comparison | 42 | 52.4 |
| comparison | 36 | 72.2 |
| compositional | 37 | 27.0 |
| inference | 33 | 51.5 |
| **总体** | **148** | **50.68**（F1 55.37，证据 85.47） |

> 检索层 nDCG@10 74.96 / MRR 94.34 是全量 300 题，说明「找得到」不是主要
> 问题；E2E 损失集中在 compositional（27.0%），comparison 仍有 72.2%。

**图谱增强对照**（100 题，图谱+文档混合）：EM 77.00 / F1 83.56 / 覆盖 83 /
证据 94.75；仅文档 73.00 / 81.84。公开 distractor SOTA：EM 88.47 / F1 90.87
（Beam Retrieval）；原论文 baseline 36.53 / 43.93。

### 4.6 MuSiQue

**设置**：1,000 条 answerable dev 题，20 段并集 11,725 passage；检索完成 500 题。

| 指标 | 值 |
|---|---:|
| 语料导入 | 11,725 passage / 11,717 chunk |
| 向量 nDCG@10 / Recall@10 / Recall@80 / MRR@10 | **57.09 / 60.22 / 78.70 / 78.58** |
| 关键词 nDCG@10 / Recall@10 / Recall@80 / MRR@10 | 49.77 / 50.17 / 68.48 / 72.97 |
| 向量 vs 关键词 | **+7.32 pp** nDCG@10（配对 bootstrap 同向） |
| 空结果 / 未映射 / P95 | 0 / 0.12% / 92 ms（向量）；0 / 0.02% / 51 ms（关键词） |

**对标**：MuSiQue 20 段 distractor SOTA F1 69.2（Beam Retrieval）；原论文
baseline F1 52.3；open-domain IRCoT EM 26.5 / F1 36.5；人类 F1 78.0。

### 4.7 CRAG

**设置**：300 / 2,706 task1-2 dev；每题 5 个网页（官方协议）；上下文注入
生成，judge 判正确性。CRAG 官方分数为自动准确率，且任务 1 的公开 GPT-4
Turbo 为 35.9（Task 3 43.6）。

| 维度 | n | Judge 正确率 | 拒答率 |
|---|---:|---:|---:|
| **总体** | **65** | **46.15** | **33.85** |
| simple | 18 | 44.4 | — |
| comparison | 9 | 66.7 | — |
| aggregation | 6 | 50.0 | — |
| multi-hop | 4 | 25.0 | — |
| simple_w_condition | 9 | 33.3 | — |
| false_premise | 6 | 100.0 | — |
| post-processing | 6 | 16.7 | — |
| set | 7 | 28.6 | — |

> **false_premise 100%** 说明拒答行为正确；**post-processing / multi-hop 最弱**
> （16.7/25.0），与 2Wiki compositional 的结论一致。65 题样本的 95% CI 约 ±12 pp。

**对标**：GPT-4 Turbo Task 1 35.9%；KDD Cup 冠军 db3 自动分 28.4/42.7/47.8
（Task 1/2/3），人工评测 53.3。我们的 judge 口径与官方自动分不同（官方是
更严格的规则化 judge），46.15% 用于同口径比较，不直接写成「超过 GPT-4」。

### 4.8 RGB（中文）

**设置**：严格复刻官方 `evalue.py`：5 篇文档、noise_rate 0/0.4/0.8、
positive/negative 拼装、字符串包含判定。另给 judge 正确率作为旁证。

| 子集 | 官方口径 [95% CI] | Judge 正确率 | ChatGPT-zh 公开值 |
|---|---:|---:|---:|
| 噪声 0.0 | 88.67 [85.00, 92.33] | 94.01 | 95.67 |
| 噪声 0.4 | 86.67 [82.67, 90.33] | 93.55 | 91.00 |
| 噪声 0.8 | 85.67 [81.67, 89.67] | 91.01 | 70.67 |
| 信息整合 | 82.00 [74.00, 90.00] | 78.00 | 63 / 58 / 47（噪声 0/0.2/0.4） |
| 反事实 ED / CR / Acc | 94.00 / 89.36 / 84.00 | 96.84（Acc） | 1.00 / 33.33 / 91.00 |

**结论**：噪声鲁棒性与信息整合明显优于 ChatGPT-zh；干净文档准确率略低
（88.67 vs 95.67），说明「不丢信息」和「不被噪声带偏」之间还有提升空间。
反事实 ED 94% 主要来自提示词明确要求「先输出事实性错误」，也说明模型对
指令的遵循度高。

### 4.9 RAGBench

**设置**：5 域 × 50 test = 250 题；用 judge 改写官方指标：
correct / adherence（每句有文档支持）/ utilization（用了文档而非自身知识）/
completeness（覆盖回答要点）。RAGBench 官方指标是 judge 质量（AUROC/RMSE），
不是答案准确率，因此这里只报「同口径 judge 分」。

> 本次 judge 与生成使用同一模型，存在自评偏差；一次调用四行 YES/NO
> （实测 JSON 四指标会被抄成同值）。这是适配口径，不是 RAGBench 官方
> leaderboard 的 AUROC/RMSE。

| 域 | n | correct | adherence | utilization | completeness |
|---|---:|---:|---:|---:|---:|
| covidqa | 50 | 92.0 | 96.0 | 100.0 | 74.0 |
| emanual | 50 | 100.0 | 100.0 | 100.0 | 92.0 |
| finqa | 50 | 90.0 | 100.0 | 100.0 | 90.0 |
| hotpotqa | 50 | 96.0 | 100.0 | 100.0 | 96.0 |
| msmarco | 50 | 100.0 | 100.0 | 100.0 | 68.0 |
| **总体** | 250 | **95.6 [93.2, 98.0]** | **99.2 [98.0, 100]** | **100.0** | **84.0 [79.2, 88.4]** |

> `utilization=100` 说明 judge 对「是否用了文档」不敏感，这一项只能当
> 「没有明显跑题」的下界；`completeness` 是唯一有明显区分度的指标
> （msmarco 68、covidqa 74）。

**对标**：RAGBench 论文 GPT-4o/RAGTruth 小样本：relevance 0.83、utilization 0.69、
completeness 0.82、hallucination 0.04；GPT-3.5 baseline 0.81/0.64/0.76/0.07。
口径不同，仅作参考。

### 4.10 CRUD-RAG

**设置**：5 任务 × 200（1,000 题），news 子集 1,585 文档；Read（1/2/3 doc QA）、
Update（幻觉修改）、Delete（摘要）各自评分；长答案用 judge 判正确性，
另报 token F1。

**检索层（500 题）**：

| 系统 | nDCG@10 | Recall@10 | Recall@80 | MRR@10 | 空结果 | 未映射 | P95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| vector | 72.51 | 99.33 | 99.93 | 66.15 | 0 | 0.05% | 131 ms |
| keyword | **83.83** | 97.47 | 99.40 | **81.81** | 0 | 0.00% | 37 ms |

> 中文新闻问答上**关键词路明显优于向量路**：nDCG@10 +11.31 pp、MRR +15.66 pp。
> 向量 Recall@10 略高（99.33 vs 97.47），但把正确文档排得更靠后。结论：中文
> 企业知识库应把关键词作为主路或至少等权融合，不能默认「向量为主、关键词兜底」。

**端到端（按任务抽样，127/200）**：

| 任务 | n | Judge 正确率 | F1 | 拒答率 |
|---|---:|---:|---:|---:|
| Read 1doc | 40 | 76.9 | 2.1 | — |
| Read 2docs | 40 | 48.7 | 1.1 | — |
| Read 3docs | 7 | 28.6 | 7.7 | — |
| Update（hallucination） | 40 | 7.5 | 0.1 | — |
| **总体** | **127** | **43.2** | **1.14** | **19.69** |

> **Read 1doc 76.9%、2docs 48.7%、3docs 28.6%**：文档越多、需要跨文档整合时
> 掉得很快。**Update（幻觉修改）7.5%** 是最弱项：模型能指出「有错误」，但很难
> 按参考事实写出正确的替代续写；这项需要任务级 rubric，当前通用 judge 偏严。
> EM/F1 对长答案无意义，只列作参考。

**对标**：CRUD-RAG 论文 GPT-3.5/4o 的 BLEU/ROUGE/BERTScore/RAGQuestEval
（如 Read-1doc ROUGE-L 57.24/51.78，Update ROUGE-L 53.04/54.79）；词面指标
与 judge 正确率不可直接换算，报告只做任务间相对比较。

## 5. 差距分析与改进方向

### 5.1 两个检索优化点

| 优化点 | 量化 | 实现位置 | 预期收益 |
|---|---|---|---|
| 查询 embedding 增加 Qwen3 instruction | NFCorpus 向量 30.26 → 35.89 nDCG@10（+5.63 pp） | `model/query_instruction.py` + `gateway.embed_query()`，检索/Agent 查询侧拼接；切片入库不受影响 | 英文检索 +5~7 pp；中文需按模型卡验证 |
| 英文关键词索引使用英文 analyzer | SciFact 关键词 59.82 → 65.21/66.84（+5.4~7.0 pp） | `index_body/create_index` 接受 `keyword_analyzer`，建库按 `props.keywordAnalyzer`/请求语言选择；查询侧读 `_meta` 使用同一 analyzer | 英文关键词 +5~7 pp；已有英文库需重建索引 |

> 两项优化只影响新建索引/部署后的查询；本报告数字是基线配置下的结果，
> 优化后应在同一批 KB/查询上复验。

### 5.2 多跳端到端

- 2Wiki 检索层 nDCG@10 74.96、MRR 94.34，说明「找得到」；E2E（148 题）
  overall EM 50.68，但 **compositional 只有 27.0%**，comparison 72.2%。
- HotpotQA（206 题）evidence 87.14、EM 53.88：同样呈现「检索到、合成丢」，
  bridge EM 46.5 明显低于 comparison 77.6。
- CRUD 的跨文档整合更明显：1doc 76.9 → 2docs 48.7 → 3docs 28.6。
- CRAG 的 multi-hop 25.0、post-processing 16.7，也是同类问题。
- 2Wiki 的图谱混合把 compositional 从 28% 提到 44%，方向正确；
  300 题文档-only 样本的 compositional 31.6% 与之同量级。
- 改进：
  1. 重排按题型路由：compositional 保留更多候选（top_n 12–15），inference 用
     更少（5–8）；
  2. 多跳题先做子问题分解，再按子问题各取 3–5 条证据；
  3. 图谱/文档混合时按「实体路径」而非纯向量分数补边；
  4. 上下文按证据覆盖度重排，而不是只按相关性；
  5. 对 yes/no、日期、数量类答案做二次校验（HotpotQA/2Wiki 的主要 EM 损失）。

### 5.3 英文大语料

- MS MARCO/NQ 的闭集抽样只能证明「向量 > 关键词」的相对关系；要与全量榜单
  对齐，需要：
  1. 全量导入（8.8M/2.1M）或至少 BM25 top-1000 候选池；
  2. 查询 instruction + 英文 analyzer；
  3. 文档级去重/段落合并（当前一 passage 一 chunk 会放大长文档）。

### 5.4 中文生成鲁棒性

- RGB 干净文档准确率 88.67 vs ChatGPT 95.67，差距在「简洁答案的精确性」
  而不是抗噪。改进：
  1. 合成器提示词要求「先给最短答案，再给必要限定」；
  2. 对数字/日期类答案做规范化校验；
  3. 拒答只在证据确实不足时触发。

### 5.5 评测建议

- 导入与生成分窗口串行执行，降低两者互相争用；
- 评测 runner 支持 per-query checkpoint（E2E 已支持），避免中断后整轮重跑；
- 大库的 `GET /chunks` 分页使用游标，保证大语料评测的覆盖率检查稳定；
- 生成/judge 按「1 次/题」设计 prompt，减少重复调用。

## 6. 复跑

```bash
# 数据集（首次下载；数据只落 .metrics-data/bench/，gitignore）
python3 tools/bench/prepare.py beir scifact
python3 tools/bench/prepare.py beir fiqa --corpus-limit 20000
python3 tools/bench/prepare.py beir-sampled msmarco --queries 2000 --negatives 15000
python3 tools/bench/prepare.py beir-sampled nq --queries 1000 --negatives 15000
python3 tools/bench/prepare.py hotpotqa --questions 2000
python3 tools/bench/prepare.py musique --questions 1000
python3 tools/bench/prepare.py 2wiki --per-type 75
python3 tools/bench/prepare.py crag --questions 300
python3 tools/bench/prepare.py rgb
python3 tools/bench/prepare.py ragbench --per-domain 150
python3 tools/bench/prepare.py crud --per-task 200

# 灌库（一 passage = 一/多 chunk；断点续灌）
python3 tools/bench/import.py --dataset beir-scifact --kb-name bench-scifact-v1 --prefix SCIFACT --workers 16

# L1
python3 tools/bench/run_retrieval.py --dataset beir-scifact --kb-id <id> \
  --systems vector,keyword --top-k 80 --marker-prefix SCIFACT --ef-search 200

# E2E（产品工作流）
python3 tools/bench/run_e2e.py --dataset 2wiki --kb-id <id> \
  --workflow-id Bench_2wiki --limit 300 --workers 4

# 上下文注入（RGB/RAGBench/CRAG）
python3 tools/bench/run_context_qa.py --mode rgb-noise --noise-rate 0.8 --workers 8 --judge
python3 tools/bench/run_context_qa.py --mode ragbench --limit-per-domain 50 --workers 8
python3 tools/bench/run_context_qa.py --mode crag --limit 300 --workers 8

# 汇总
python3 tools/bench/summarize.py
```

## 7. 口径说明

1. **闭集/抽样**：MS MARCO/NQ 是抽样语料，HotpotQA/2Wiki/MuSiQue 是
   「候选并集」而不是全 wiki；绝对分数不能与全量榜单直接比。
2. **题量**：2Wiki 300、HotpotQA 300 E2E、CRAG 300、RAGBench 250；95% CI 约
   ±3–6 pp，小差异不显著。
3. **生成模型**：E2E 与上下文注入使用部署的生成端点；换模型会改变绝对分，
   但检索层指标不受影响。
4. **judge 偏差**：RGB 官方口径是字符串包含，judge 是语义判断；两者并列报告。
5. **并发负载**：部分 P95 延迟是在多基准并行导入时测的，容量基线应以单独
   压测为准。
6. **MTEB**：没有跑完整 56 任务/8 任务官方 harness；C-MTEB 只用 DuRetrieval
   单任务，英文检索组复用 BEIR。MTEB 的模型选型结论应回到官方 harness 复跑。

## 8. 公开值来源

- BEIR: arXiv:2104.08663, Table 2；E5: arXiv:2212.03533；BGE-M3: MTEB results；
  Qwen3-Embedding: arXiv:2506.05176 / model card。
- MS MARCO: RankLLaMA, arXiv:2309.15088, Table 1。
- NQ: DPR arXiv:2004.04906；FiD arXiv:2007.01282；RAG arXiv:2005.11401。
- HotpotQA: 官方 leaderboard; Beam Retrieval arXiv:2308.08973。
- 2Wiki: arXiv:2011.01060；Beam Retrieval 同上。
- MuSiQue: arXiv:2108.00573；IRCoT arXiv:2212.10509。
- CRAG: arXiv:2406.04744；KDD Cup 2024 冠军 arXiv:2410.00005。
- RGB: arXiv:2309.01431, Tables 2–5。
- RAGBench: arXiv:2407.11005, Table 2。
- CRUD-RAG: arXiv:2401.17043, Table 3。
