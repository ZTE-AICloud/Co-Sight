# 图谱检索与 2Wiki 端到端指标

用公开 KGQA / 多跳问答基准度量图谱这一层：

- **MetaQA（L1）**：topic 实体能不能被向量种子召回，按 `depth` 展开的子图能不能覆盖标准答案；只测检索层。
- **2WikiMultiHopQA（L2）**：文档库 + 图谱库混合检索 → 已发布工作流 → 最终答案，计算 EM / F1 / 答案覆盖 / 证据召回。

## 数据集

### MetaQA

MetaQA（Zhang et al., AAAI 2018）vanilla 文本版，HF 镜像
<https://huggingface.co/datasets/camazlucas/MetaQA>（原始发布在 Google Drive，
镜像是逐字节副本）。

| 项 | 值 |
|---|---|
| KB | WikiMovies：134,741 条三元组 / 43,234 个实体 / 9 个关系 |
| 1-hop test | 9,947 题 |
| 2-hop test | 14,872 题 |
| 3-hop test | 14,274 题 |
| topic 标注 | 题目里的 `[实体]`，每道题都有 |
| 答案 | KB 实体名，多答案用 `\|` 分隔 |

### 2WikiMultiHopQA

采用官方 **dev** 集（12,576 题；带标准答案与 supporting facts），按 4 种题型各抽 25 题，
共 100 题（`seed=42`）。每题自带 10 篇候选文章，按标题去重后共 **802 篇**。

数据只落在 `.metrics-data/`（已 gitignore），不入库、不随报告分发。

## KB 转换口径（MetaQA）

- 一个实体 = KB 中出现过的 subject/object；`entity_id` 就是实体名，和答案标注同一命名空间。
- 实体类型统一为 `Entity`。MetaQA 的实体类型是隐含的；强行推断会把
  「演员也导演过电影」拆成两个 ID，破坏多跳。
- 9 个关系映射成纯字母 PascalCase 边类型（schema 校验器要求 `^[A-Za-z]*$`）：
  `directed_by → DirectedBy`、`starred_actors → StarredActors` 等。
- 边 ID 用 `r<行号>`，重复导入按 edge_id 幂等跳过。

## 目录

```text
tools/graph-metrics/
├── prepare_metaqa.py       # 下载 → 校验 → questions.jsonl + 导入 zip + stats.json
├── import_metaqa.py        # 上传 zip → 轮询 status → 真检索一次做验收
├── run_metaqa_metrics.py   # 抽样跑检索 → 指标 + bootstrap + results.json + report.md
├── prepare_2wiki.py        # 2Wiki dev 分层抽样 → questions/articles/graph_upload
├── import_2wiki.py         # 建文档库 + 图谱库 + Blended_normal_graph 工作流并发布
├── run_2wiki_e2e.py        # 逐题 /query → EM / F1 / 覆盖 / 证据召回
├── analyze_2wiki_graph.py  # 检查图谱规模、连通性与 gold 证据覆盖
├── make_ablation_workflows.py  # 仅文档 / 混合 / 仅图谱对照工作流
├── graph_client.py         # 复用 rag-metrics 的登录/重试，补图谱接口
├── metrics.py              # topic_hit / answer_covered / answer_recall / bootstrap
└── tests/
```

## 用法

### MetaQA

```bash
# 1) 准备数据（首次下载约 9 MB；build zip）
python3 tools/graph-metrics/prepare_metaqa.py

# 2) 导入（幂等：同 id 且 status=5 时跳过；--force 重建）
python3 tools/graph-metrics/import_metaqa.py --timeout 7200

# 3) 跑指标（默认每跳 500 题，depth=hop）
python3 tools/graph-metrics/run_metaqa_metrics.py \
  --kb-id <kb-id> --limit-per-hop 500 --depths hop --seed-k 10 --limit 1000

# 看深度收益：同一批题跑 depth=1,2,3
python3 tools/graph-metrics/run_metaqa_metrics.py \
  --kb-id <kb-id> --limit-per-hop 500 --depths 1,2,3 --out .metrics-data/runs/metaqa-depth

# 单测
python3 -m pytest tools/graph-metrics/tests -q
```

产物在 `.metrics-data/runs/metaqa-<kb-id>/`：`results.jsonl`（每题一行，可断点续跑）、
`results.json`（聚合）、`report.md`（可提交的报告体裁）。

### 2WikiMultiHopQA

```bash
# 1) 准备数据（默认每种题型 25 题，共 100 题）
python3 tools/graph-metrics/prepare_2wiki.py \
  --input .metrics-data/2wiki/raw/dev_voidful.json \
  --out .metrics-data/2wiki/data --per-type 25

# 2) 建文档库 + 图谱库 + 工作流（可重复执行，按 state 断点续跑）
python3 tools/graph-metrics/import_2wiki.py \
  --state .metrics-data/2wiki/state-attr-v2.json \
  --graph-kb-name 2wiki-e2e-graph-attr-v2 \
  --workflow-id RAG_Workflow_2wiki_attr2 \
  --extraction-profile general_attributes --graph-workers 4

# 3) 端到端问答（逐题 /query）
python3 tools/graph-metrics/run_2wiki_e2e.py \
  --state .metrics-data/2wiki/state-attr-v2.json \
  --out .metrics-data/runs/2wiki-e2e-100-attr-v2 --workers 4 --no-resume

# 4) 图谱覆盖分析（需要导出的 graph zip）
python3 tools/graph-metrics/analyze_2wiki_graph.py \
  --graph-zip .metrics-data/2wiki/graph-v2/graph.zip \
  --data-dir .metrics-data/2wiki/data \
  --dev-json .metrics-data/2wiki/raw/dev_voidful.json
```

## 指标口径

### MetaQA

- `topic_hit`：题目标注的 topic entity ∈ `seed_entity_ids`。只测种子召回/实体链接。
- `answer_covered`：任一标准答案 ∈ 返回子图实体。测「种子 + depth 跳展开」的覆盖。
- `answer_recall`：多答案题的覆盖比例。
- `empty_seed_rate` / `truncated_rate`：空种子比例；子图实体撞到 `limit` 上限的比例。
- 每个比例给题目级 95% bootstrap 区间；另给「含错误按 0 分」的保守值。
- 失败不静默：每题的异常落 `results.jsonl`，报告里单列错误率。

### 2WikiMultiHopQA

- **EM / 规范化 EM**：SQuAD 规范化（小写、去标点、去冠词）；另做去括号、去爵位/王室前缀的规范化口径。
- **F1**：答案 token 级 F1。
- **答案覆盖**：gold 是否是预测的完整词序列。
- **证据召回**：supporting facts 的标题是否出现在返回片段文本里。
- 每题独立 `conversation_id`，`include_retrieval=true`；去掉 `<think>…</think>` 后再评分。
- 多答案用 `|` 分隔时取最佳；结果逐行落 `results.jsonl`，默认断点续跑。

## 实测结果

结果逐题写入 `--out` 指定的目录（默认 `.metrics-data/runs/`，已 gitignore）；
公开基准上的汇总指标见 [`docs/rag-benchmark-20261101.md`](../../docs/rag-benchmark-20261101.md)。

## 已知边界

- MetaQA 只测检索层，不测 LLM 回答；2Wiki 补上了答案级端到端口径。
- `seed_k` 的实际种子数会超过 10：边向量命中会带出两个端点（产品既有行为）。
- `limit=1000` 时 3-hop 子图可能截断；报告里用 `truncated_rate` 显式登记。
- MetaQA 的 KB 里有大小写不同的同名实体（`tim robbins` / `Tim Robbins`）；
  本工具按原样导入，不做消歧——这也是基准的一部分。
