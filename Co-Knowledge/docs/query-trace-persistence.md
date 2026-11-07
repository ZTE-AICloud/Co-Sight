# 查询链路耗时入库与查询 API

每次 `POST /query` 的**指标**会 best-effort 写入
`public.chat_query_trace`，并提供只读的列表 / 详情 / 聚合接口。目标是单次排障 +
按工作流/时间做 P50/P95/P99 与命中率统计，而不是存聊天内容。

## 1. 存什么、不存什么

一行 = 一次 `/query`。只存指标与不透明标识：

- `trace_id`（来自 `X-Request-Id`；合法客户端值原样沿用，缺失或不合法时由服务端生成；
  ≤64 字符，**可重复**，不是唯一键）
- `conversation_id` / `workflow_id` / `org_id`（客户端可控，≤128 字符，写库前去 NUL/
  非法字符并截断）
- `is_stream`、`status`（`ok` / `error` / `client_disconnect`）
- `error_code`、`http_status`（实际 wire 状态）、`error_status`（problem 规格状态）
- `question_len` / `answer_len`（字符数；流式 `answer_len` 含思考段）
- `understanding_ms` / `retrieval_ms` / `rerank_ms` / `generate_ms` /
  `first_token_ms` / `total_ms`
- `hit_count` / `source_count` / `kb_count` / `top_score`
- `created_at`（**完成时刻**，不是请求开始）

**不存**问题、答案、证据正文、`emp_no`、客户端 IP。`generate_ms` 仅流式有值；
非流式合成发生在 `engine.query()` 内，无法与检索段精确拆分，不伪造。

阶段耗时口径与面板一致：

- `first_token_ms`：handler 入口 → 首个内容 token；
- `generate_ms`：开始消费模型流 → done/空回答/中途 error/断连（含客户端背压）；
- `total_ms`：handler 入口 → 终态（断连时可能偏大）；
- 阶段没执行 → `NULL`，不是 0。

## 2. 写入：best-effort 队列

```text
chat.app.chat() → TraceState（带锁，首个终态胜出）
  → BackgroundTask(enqueue_trace)        # 只入队，不碰 DB
  → queue.Queue(maxsize=1000) + 单 daemon 写线程
  → repository_pg.persist_query_trace()  # 参数化 INSERT，2s statement_timeout
```

- 队列满、DB 不可达、连续失败 3 次熔断 30s：直接丢 trace，**绝不影响问答**。
- 进程被 kill / ASGI 硬取消时队列尾部会丢：观测数据，已知取舍。
- 表不存在时 `ensure_table()` 先检查 `to_regclass`，缺表才建；DDL 失败 30s 内不重试。
- 开关 `RKB_QUERY_TRACE_ENABLED`（默认 `true`）；关闭时 handler 不创建状态、不调度。
- 上游 LLM 在流中途失败会被适配器转换成正常 token + `[DONE]`，本层只能记为 `ok`。

## 3. 读 API

前缀：`/api/co-knowledge/v1`。只读、无鉴权（与其它 UI API 一致）。

### 列表

```http
GET /query-traces?workflowId=wf-1&status=ok&from=2024-01-01&to=2024-01-31&page=1&size=20
```

- `from`/`to` 支持 `YYYY-MM-DD` 与 ISO-8601；`to` 为开区间；date-only 按
  **Asia/Shanghai** 解释。
- 返回 `{items,total,page,pageSize}`；`items` 字段：
  `id,traceId,conversationId,workflowId,orgId,isStream,status,errorCode,httpStatus,
  errorStatus,questionLen,answerLen,understandingMs,retrievalMs,rerankMs,generateMs,
  firstTokenMs,totalMs,hitCount,sourceCount,kbCount,topScore,createdAt`。

### 详情

```http
GET /query-traces/{id}      # 内部 bigint id；不存在 404 problem
```

### 统计

```http
GET /query-traces/stats?workflowId=wf-1&from=2023-12-25&to=2024-01-01&bucket=day
```

```json
{
  "summary": {
    "count": 42, "okCount": 40, "errorCount": 1, "clientDisconnectCount": 1,
    "hitRate": 0.93, "avgHitCount": 4.2, "avgSourceCount": 3.1,
    "understanding": {"count": 40, "p50": 310.0, "p95": 420.0, "p99": 500.0},
    "retrieval": {...}, "rerank": {...}, "generate": {...},
    "firstToken": {...}, "total": {...}
  },
  "series": [{"bucket": "2024-01-01T00:00:00+08:00", "...": "同 summary"}]
}
```

口径：

- `count/okCount/errorCount/clientDisconnectCount` 统计所有行；
- **命中率、均值、延迟分位数只统计 `status='ok'`**（错误行通常很快，会把 P50 拉低）；
- 每个阶段都返回样本数 `count`，避免「P50 是 40 条还是 2 条算出来的」误读；
- `hitRate = 有命中的 ok 行 / ok 行`；`okCount=0` 时为 `null`。它不是 Recall@10；
- `bucket=day` 最多 366 天、`bucket=hour` 最多 31 天；默认最近 7 天；
- series 只返回有数据的桶，不补零。

存储不可用时返回 503 `query_trace_store_unavailable` problem；参数语义错误返回
422 `validation_failed`。

## 4. 隐私与权限

- 默认 `AUTH_MODE=none`，所有 UI API（含本接口）对能访问端口的人开放；需要保护时
  用网关/`AUTH_MODE=gateway` 或网络隔离。
- 行内只有指标与不透明 ID；`conversation_id` 可能被调用方塞入用户标识，按 30 天保留，
  文档需告知调用方不要放敏感信息。

## 5. 所有权与保留

- 空卷新装：`deploy/init/pg/00-schema.sql` 已包含表与索引；
  `05-app-role.sh` 创建应用角色并移交所有权。
- 30 天保留由宿主侧工具执行（`tools/` 不在 RKB 镜像里）：

  ```bash
  # 宿主连接：显式给 127.0.0.1；用户/口令会回落 RKB_DB_* / POSTGRES_*
  export RKB_DB_HOST=127.0.0.1 RKB_DB_PORT=5432
  python3 tools/ops/prune-query-traces.py --dry-run
  python3 tools/ops/prune-query-traces.py --apply --yes --older-than-days 30
  ```

  cron 示例见脚本头。`--apply` 必须 `--yes`，且天数不能小于 1；删除按
  `created_at,id` 分批（默认 5000/批），避免长锁。

## 6. 统计口径与容量建议

- 队列容量 1000 条，单写线程；进程被 kill / ASGI 硬取消时队列尾部会丢几条。
  这是观测数据的容量边界，不影响问答主链路。
- 断连竞态：首个终态胜出，可能把刚好完成的请求记为 `client_disconnect`；
  排障时结合 `http_status` 与 `error_code` 看。
- 上游 LLM 流中途失败会被适配器转换成正常 token + `[DONE]`，本层记为 `ok`；
  需要区分时可对照上游日志。
- 非流式请求没有 `generate_ms`；统计百分位忽略 NULL。
- 统计只覆盖 `status='ok'` 的行，各阶段样本数可能不同，响应里的 `count` 是判读依据。
- `created_at` 是完成时刻；按天分桶以 Asia/Shanghai 为准。
- 默认保留 30 天，按 `created_at,id` 分批清理；容量规划按「每题一行、行宽约数百字节」
  估算，高并发部署可缩短保留期或调大清理批次。
- 页面侧可直接复用 `frontend/src/features/chat/lib/trace.ts` 的数据结构。
