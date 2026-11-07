# RAG 检索指标（L1）

目标：**用公开中文检索基准，度量产品两条基础检索路径（向量 / 关键词）的效果，
产出一份可提交的验收报告。** L1 聚焦检索；L2 用独立 judge 另测生成质量。

> 当前 L1 基线（2026-10-29）：向量 NDCG@10 **81.57%** / Recall@80 **95.02%**，
> 关键词 NDCG@10 **59.96%**。公开基准（11 个数据集，2026-11-01）见
> [`docs/rag-benchmark-20261101.md`](../../docs/rag-benchmark-20261101.md)，工具在 `tools/bench/`。

## 数据集

| 数据集 | 语料 | 查询 | qrels | 说明 |
|---|---|---|---|---|
| **DuRetrieval**（默认） | 100,001 passage | 2,000 | 9,839（二值） | C-MTEB / MTEB 检索任务；中文网页检索；规模刚好可整库导入 |
| T2Retrieval（备选） | 118,605 passage | 22,812 | — | 同属 C-MTEB；查询量大，适合后续扩大样本 |

上游：

- <https://huggingface.co/datasets/C-MTEB/DuRetrieval>
- <https://huggingface.co/datasets/C-MTEB/DuRetrieval-qrels>

数据只落在 `.metrics-data/`（已 gitignore），**不入库、不随报告分发**；报告只写聚合指标
与少量查询示例。

## 目录

```text
tools/rag-metrics/
├── prepare_dataset.py       # 下载/校验/落 parquet + stats.json
├── rkb_client.py            # 产品 HTTP 客户端（建库/容器文件/手工切片/检索）
├── import_corpus.py         # 一 passage = 一 chunk 灌库（可断点续灌）
├── repair_parts.py          # 按子片正文对账，补齐失败/漏导的子片
├── metrics.py               # Hit/Recall/Precision/MRR/NDCG（支持「一个位置多条候选」）
├── run_retrieval_metrics.py # 跑查询 + 聚合 + bootstrap + results.json
├── db_stats.py              # 存储侧核对（PG/chunk/ES/孤儿行）
├── render_report.py         # results.json → Markdown 报告
├── cleanup_kbs.py           # 先删文件再删库，清残留 ES 索引
├── prepare_rerank_input.py  # 从 L1 结果生成 rerank 候选（JSONL）
├── rerank_cross.py          # cross-encoder /v1/rerank 消融（Qwen3-Reranker-4B）
├── rerank_llm.py            # LLMReranker 消融（负结果；--thinking off 可关推理）
├── probe_thinking_switch.py # 直测推理模型 thinking 开关的写法
├── analyze_rerank.py        # 基线 vs rerank 的指标/置信区间
├── with_model_env.sh        # 从部署容器注入模型网关配置（不落盘 key）
└── tests/                   # 指标与映射层单测
```

## 口径（报告里必须原样保留）

1. **一 passage = 一（或数个）chunk**：走产品自己的 `POST /chunk/add` 手工切片接口；
   超过 4,000 字符的 passage 切子片，子片共享同一 pid 标记，指标在 pid 级去重。
   这样把「切片策略」固定成变量，避免 512 字重新切片把多条 passage 混进一个 chunk。
2. **标记不参与检索**：`content`（embedding + ES 索引正文）是干净 passage；
   `supplement`（向量路返回的展示正文）才带 `【DURET-<pid>】`。实测：
   - 向量路返回 `supplement` → 按标记映射；
   - 关键词路返回 `content` → 按正文精确/空白归一映射。
3. **非语料文档保守计分**：容器文件自身的正文、删除切片后残留的空向量行，按
   「非相关、占一个排名位」处理（伪 pid），**不直接过滤**。
4. **top_k=80**：产品 `RetrieveDTO` 限制 1–80，因此报告 Recall@80，不报 Recall@100。
5. **静默失败**：`retrieve()` 在服务端把异常吞成 `bo=[]`；用 `--log-container`
   统计 RKB 日志里 `retrieve failed, returning empty result` 的增量。
6. **置信区间**：查询级 2,000 次 bootstrap；向量 vs 关键词用同一批查询做配对 bootstrap。

## 用法

```bash
# 1) 准备数据（首次下载约 64 MB）
python3 tools/rag-metrics/prepare_dataset.py --out .metrics-data/duretrieval

# 2) 灌库（先小样本验速）
python3 tools/rag-metrics/import_corpus.py --limit 500 --workers 16 --kb-name rag-metrics-pilot
python3 tools/rag-metrics/import_corpus.py --workers 16 --kb-name rag-metrics-duretrieval-v1

# 3) 补齐失败/漏导的子片（幂等；全量 KB 不要传 --limit）
python3 tools/rag-metrics/repair_parts.py --kb-id <kb-id> --workers 8

# 4) 关键词索引（OpenSearch）从 PG 重建（text = COALESCE(向量表 text, chunk 表 text)）
python3 tools/rag-metrics/reindex_es.py --kb-id <kb-id> --apply

# 5) 跑指标（strict-coverage：qrels pid 缺一条就拒绝出报告）
#    ⚠️ 先确认 hnsw.ef_search >= top_k，否则向量路实际只返回 ef_search 条
python3 tools/rag-metrics/run_retrieval_metrics.py \
  --kb-id <kb-id> --systems vector,keyword --top-k 80 --ef-search 80 \
  --out .metrics-data/runs/<kb-id> \
  --product-version <image-digest> \
  --log-container rag-studio-rag-knowledge-base-1 --strict-coverage

# 6) 存储侧核对 + 出 Markdown
python3 tools/rag-metrics/db_stats.py --kb-id <kb-id> \
  --es-index kb_index_<kb-id> --out .metrics-data/runs/<kb-id>/db-stats.json
python3 tools/rag-metrics/render_report.py \
  --results .metrics-data/runs/<kb-id>/results.json \
  --db-stats .metrics-data/runs/<kb-id>/db-stats.json \
  --out .metrics-data/runs/<kb-id>/retrieval-metrics-report.md

# 单测
python3 -m pytest tools/rag-metrics/tests -q
```

断点续灌：`import_corpus.py --resume`。它会先列出 KB 里已有的带标记切片，
跳过已导入 pid；不会再上传已有的容器文件。

## Re-ranker（Qwen3-Reranker-4B）

- 端点：`POST http://<rerank-host>:8003/v1/rerank`，模型名 `Qwen3-Reranker-4B`（vLLM）。
  请求 `{model, query, documents}`，响应 `{results:[{index, relevance_score}]}`。
- 在模型管理页注册：`modelKind=rerank`、`baseUrl=http://<rerank-host>:8003`、
  `rerankPath=/v1/rerank`、`apiModel=Qwen3-Reranker-4B`；保存即生效，无需重建容器。
- **容器 `no_proxy` 必须包含 rerank 主机**：Python 不认 `10.*.*.*` 通配，
  否则 rerank 请求会被宿主代理截胡。compose 已接 `RERANK_HOST`（`.env` 里设
  `RERANK_HOST=<rerank-host>`），改完要 recreate `rag-knowledge-base`。
- 评测用 `rerank_cross.py` 直接打端点（chunk 级）；产品 `ExternalModelReranker` 标准模式（旧逻辑 ID `BgeLargeReranker`）
  会按 `source` 合并 chunk，是文档级上下文的语义，不要拿它和 chunk 级 L1 指标直接对拍。
- 候选并集（`prepare_rerank_input.py --keyword-k 20`，vector top-50 ∪ keyword top-20）
  实测在本基准**无显著增益**（NDCG@10 +0.57 pp，CI 含 0，延迟 +24%）；
  主路径保持「向量 + cross-encoder」，关键词作为精确词兜底。
- **LLM reranker 关闭推理**：部分推理模型只认
  `chat_template_kwargs={"thinking": false}`（顶层 `reasoning_effort=none` 仍会思考）。
  harness 用 `rerank_llm.py --thinking off`；产品侧支持算子级
  `chat_template_kwargs` 与部署级 `GENERATION_CHAT_TEMPLATE_KWARGS`。
  关闭后 fallback 0、延迟 ~7 s，但 NDCG@10 仍 −3.5 pp，故不做生产 reranker。

## 实测吞吐与环境

| 项 | 实测 |
|---|---|
| 导入吞吐 | 16 并发实测 **17.9 parts/s**；32 并发出现 `0001` 服务端错误且不提速 → 用 16 |
| 全量导入 | 100,296 个子片，**93 分钟**（一次性；372 个失败由 `repair_parts.py` 补齐） |
| 检索延迟 | 10 万切片全量：向量 P95 ≈ 180 ms（ef_search=80），关键词 P95 ≈ 44 ms |
| Embedding | `Qwen3-Embedding-0.6B`（1024 维） |

## 已知坑（都已在代码/注释里处理）

- **本地账号（2026-10-25 起）**：默认 `AUTH_MODE=local`，评测客户端会自动
  `POST /auth/login`（`RKB_USERNAME` / `RKB_PASSWORD`，默认 `admin` / `admin`），
  并在带 Cookie 的 unsafe 请求上补 `Origin`（CSRF 校验要求其 host 等于 `Host`）。
  非 local 模式返回 `409 auth_not_enabled`、端点不存在（404/405）时静默跳过；
  自带 nginx 用 `Host $host` 会剥掉端口，带端口的 Origin 被拒后客户端会用
  host-only Origin 重试一次。会话中途失效（401）会重新登录一次再重试。
- **`chunkId` / `sourceDocId` 有 null 路径**：不要拿它们做 gold 映射；用标记与正文。
- **向量路与关键词路返回字段不同**：向量返回 `supplement`，关键词返回 `content`；
  这是 `chunk/add` 的 `content`（embedding/ES）与 `chunk.text`（展示）分工的直接结果。
- **并发下 `chunk/add` 可能写成无 chunk 行的正文行**（`vector.text` 存干净正文、无 chunk 行）。这类行仍能按正文映射，
  不影响指标，但说明 `chunk/add` 的并发健壮性值得单独关注。
- **删除切片不清向量行**：`/chunk/delete` 后向量表可能残留孤儿行，检索返回空正文；
  本 harness 不删容器切片，避免制造孤儿。
- **HNSW 的 `ef_search` 会偷偷截断 top_k**：pgvector 默认 `hnsw.ef_search=40`，
  10 万行时向量路最多返回 40 条。测 Recall@80 前必须确认 `ef_search >= 80`
  （`ALTER DATABASE ... SET hnsw.ef_search=80` 后重连/重启 RKB），否则 K>40
  的指标都是在 top-40 上算的。报告里同时给 as-shipped（默认 40）对照。
- **断点续灌以 pid 为单位**：长 passage 的某个子片失败时，`--resume` 会因 pid
  已存在而跳过；必须用 `repair_parts.py` 按子片正文对账补齐。
- **容器文件必须能通过切分校验**：太短/纯英文标题会报 `RetCode.operator.split.empty`；
  容器正文用中英双语说明。
- **工作树隔离钩子**：bash 命令里出现 `eval` 子串会被误判成 shell eval 拒绝执行；
  目录/脚本名均已避开该子串（`tools/rag-metrics`、`.metrics-data`）。

## 后续（L2）

L2 在同一数据集上打 `POST /query`，用独立 judge 模型打分：

- RAGAS 口径：faithfulness / answer_relevancy / answer_correctness /
  context_precision / context_recall；
- 可精确判定的引用准确性（citation node_id / source 是否命中 gold）；
- 负样本拒答率（不可回答问题）；
- 延迟与 token 成本。

L1 基线（DuRetrieval，2,000 条查询）与公开基准复跑见
[`docs/rag-benchmark-20261101.md`](../../docs/rag-benchmark-20261101.md)；L2 与 2Wiki 端到端工具见
`tools/bench/`、`tools/graph-metrics/`。
