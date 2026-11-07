# 模型服务契约（rag-model-gateway）

> 契约版本：见 `VERSION`。本文件是 embedding / LLM / rerank 接入的**唯一边界**。
> 背景：本项目**零 ML 运行时依赖**（`torch`/`transformers`/`sentence-transformers` 都不在
> 依赖里），向量化 100% 走外部模型服务；本契约约束该外部依赖的形状，
> **默认由 docker-compose 中的推理容器实现**。

## 实现方式

**不是新写的服务**，而是一个**契约 + 配置**：各服务按 `MODEL_GATEWAY_URL` 访问一个
OpenAI 兼容端点。端点可以是远端服务，也可以是自带的可选容器。

**默认（2026-10-12 起）走远端 OpenAI 兼容网关**：

| 用途 | 端点 | 模型 | 维度 |
|---|---|---|---|
| embedding | `{MODEL_GATEWAY_URL}/v1/embeddings`（无需 API key） | `Qwen3-Embedding-0.6B` | 1024 |
| 生成 / 重排 | `GENERATION_GATEWAY_URL`（**必须指到真实端点**，见下） | 见 `deploy/.env` 的 `GENERATION_MODELS` | — |

`model-gateway`（本地 Infinity 容器，跑 `BAAI/bge-base-zh-v1.5` / 768 维）仍在 compose 里，
但**默认不启动**（`profiles: ["local-embedding"]`）—— 少一个容器、少一次权重下载、省 4G 内存限额。
要用本地 bge 见「本地模式」一节。

> ### ⚠️ 容器必须把 embedding 域名加进 `NO_PROXY`（2026-10-12 实测）
> 容器会继承宿主 `http_proxy`。`your-llm-endpoint.example.com` 不在 `NO_PROXY` 里时，请求被发到公司代理：
>
> ```
> urllib.error.URLError: <urlopen error Tunnel connection failed: 302 Moved>
> ```
>
> 症状**长得像 embedding 服务本身故障**，很容易查错方向。compose 里由 `EMBEDDING_HOST`
> 注入到 `rag-knowledge-base`（写法同 `GENERATION_HOST`）。

## 端点（OpenAI 兼容子集）

> ### ⚠️ 路径说明（2026-10-04 首测，2026-10-12 补充）
> 契约约束的是 **请求/响应的形状**（OpenAI 兼容），**不是固定路径**。
> 已实测的三种实现路径都不同：
>
> | 实现 | 路径 | 实测 |
> |---|---|---|
> | 远端 OpenAI 兼容网关（当前默认） | `{base}/v1/embeddings` | ✅ 200（`/models` 不存在，404） |
> | Infinity 0.0.77（可选本地容器） | `{base}/embeddings` | ✅ 200；`/v1/embeddings` ❌ 404 |
> | Infinity，模型清单 | `{base}/models` | ✅ 200；`/v1/models` ❌ 404 |
>
> 因此客户端必须使用**可配置路径**（`MODEL_GATEWAY_EMBEDDINGS_PATH`），改实现只改配置、**无需改代码**。

### POST `{MODEL_GATEWAY_URL}{MODEL_GATEWAY_EMBEDDINGS_PATH}`  ← **首条链路必需**

请求：
```json
{ "input": ["文本1", "文本2"], "model": "Qwen3-Embedding-0.6B" }
```
响应（形状与 OpenAI 一致）：
```json
{ "object": "list", "data": [ { "object": "embedding", "embedding": [0.1, 0.2, ...], "index": 0 } ], "model": "..." }
```
**实测确认**（2026-10-12）：`Qwen3-Embedding-0.6B` 返回 **dim = 1024**。
参考值：`BAAI/bge-base-zh-v1.5` = **768**（本地模型）。

**维度约束（关键，别省）**：返回向量维度必须等于该 KB 在 `kb_embedding.dimension` 里登记的维度，
否则写入 `vector(N)` 列会失败。建库时按注册表登记的维度建表，
并在写入前**校验**实际返回维度；不一致必须**显式失败**，不得静默截断或补零。

**多模型共存是支持的**：模型按**每个知识库**解析（按 `kb_kbase.embedding_model` 查模型注册表），所以 768 维与 1024 维的库可以并存 ——
**前提是那个模型的服务端点仍然可达**。这正是「本地模式」还留着的理由。

### POST `{GENERATION_GATEWAY_URL}/chat/completions`  ← **检索编排（v1.1）必需**

生成模型端点，OpenAI 兼容。消费者是检索编排运行时（查询改写 / LLM 重排 / 答案合成）
与画布的「大模型」下拉。

请求形状（`backend/src/engine/custom_llm/openai_llm.py`）：
```json
{ "model": "deepseek-chat", "messages": [{"role": "user", "content": "..."}],
  "temperature": 0.01, "max_tokens": 2048, "stream": false }
```
响应：OpenAI 标准 `{"choices":[{"message":{"content":"..."},"finish_reason":"stop"}]}`。

> ### ⚠️ 推理模型的静默失败（必须按契约处理）
> `deepseek-chat` 这类**推理模型**先输出 `reasoning_content`。`max_tokens` 给小了会出现：
> HTTP 200 + `content` **为空** + `finish_reason=length` —— 看起来调用成功，其实没有答案。
> 实测：64 不够、1024 正常，故默认 `GENERATION_MAX_TOKENS=2048`。
>
> **契约要求调用方显式失败，不得把空 content 当成正常返回**：
> 检索编排运行时在 `content` 为空时抛 `llm-empty-content-truncated`（只出了推理内容被截断）
> 或 `llm-empty-content`，调用侧各自有兜底（改写失败退回原问题、重排失败退回原顺序），
> 但日志里一定看得到。

| 变量 | 含义 | 默认 |
|---|---|---|
| `GENERATION_GATEWAY_URL` | 生成端点（OpenAI 兼容，含 `/v1`） | `http://model-gateway:8000/v1` |
| `GENERATION_MODEL` | 默认模型名 | `deepseek-chat` |
| `GENERATION_API_KEY` | 端点鉴权（**只进 `deploy/.env`**） | 空 |
| `GENERATION_MAX_TOKENS` | 单次生成上限（推理模型要给足） | `2048`（`.env.example` 给 `16384`） |
| `GENERATION_TEMPERATURE` | 温度 | `0.01` |
| `GENERATION_TIMEOUT` | 超时（秒） | `120` |
| `GENERATION_HOST` | 端点主机/IP，仅用于容器的 `NO_PROXY` 排除 | 空 |

> 内置默认实现 **Infinity 0.0.77 不含生成模型**（实测 `POST /v1/chat/completions` → 404），
> 所以「文档→自动出图 / 编排跑通」必须把 `GENERATION_GATEWAY_URL` 指到真实端点。
> 实测可用：`deepseek-chat`、`qwen3-32b`、`minimax-m3`。

#### 流式（`"stream": true`）—— SSE 契约

`stream` 是**每次调用可变的请求字段**（非流式改写/重排传 `false`，答案合成传 `true`）。
后端的 `POST /query` 在 `stream=true` 时以 `text/event-stream` 转发。

**2026-10-11 对 `deepseek-chat` 实测的响应形状**（部署方换端点后应重跑这条探针）：

```
HTTP/1.1 200 OK
content-type: text/event-stream; charset=utf-8
Transfer-Encoding: chunked

data: {"id":"chatcmpl-…","object":"chat.completion.chunk","created":…,"model":"deepseek-chat","choices":[{"index":0,"delta":{"role":"assistant","content":""}}]}

data: {…,"choices":[{"index":0,"delta":{"reasoning_content":"We"}}]}

data: {…,"choices":[{"index":0,"delta":{"content":"你"}}]}

data: [DONE]

```

帧的**硬性约定**（调用方必须按此实现）：

| 约定 | 说明 |
|---|---|
| 帧格式 | 每帧一行 `data: <json>`，**以空行分隔** |
| 增量字段 | 取 `choices[0].delta`。**不是 `message`** —— 用 `message` 解析会拿到 `None`/空串，且**不会报错** |
| 结束帧 | `data: [DONE]`（注意 `[DONE]` **不是 JSON**，必须先判字符串再 `json.loads`） |
| 心跳/注释 | 本部署实测**没有**。但契约不禁止，**消费方应跳过所有不以 `data:` 开头的行** |
| 推理模型 | 先吐 `reasoning_content` 再吐 `content`（同 §「推理模型的静默失败」）。**两者都要处理**，只取 `content` 会丢掉思考过程且首帧长时间为空 |
| 截断风险 | `content` 为空 + `finish_reason=length` 的问题**对流式同样成立**，只是表现成「流完了但没内容」 |

> **为什么这条要写进契约**：编排运行时（`backend/src/engine/`）的 LLM 适配器必须给每帧的
> `CompletionResponse` 设置 `delta`（token 提取在自研原语层
> `backend/src/engine/primitives/llm.py:stream_completion_response_to_tokens`，
> 语义是取 `r.delta or ""`）。**只设 `text` 不设 `delta` 会产出一条全空串的流**，
> 而 HTTP 状态码、响应头、帧格式全部正常 —— 又一个「看起来成功」的静默失败。
> 对应测试：`backend/tests/engine/test_llm_stream.py`。

### GET `{GENERATION_GATEWAY_URL}{GENERATION_MODELS_PATH}`  ← **画布校验（v1.1）必需**

生成端点声明自己提供哪些模型。消费者是 `backend/src/workflow/`，
用于画布的 preCheck / publish：**画布上选的模型，端点是否真的有**。

响应即 OpenAI 兼容的模型列表：

```json
{ "object": "list", "data": [ { "id": "deepseek-chat", "object": "model" } ] }
```

| 变量 | 含义 | 默认 |
|---|---|---|
| `GENERATION_MODELS_PATH` | 拼在 `GENERATION_GATEWAY_URL` 后的路径 | `/models` |

> ### ⚠️ 路径必须可配（2026-10-12 实测）
> 两种实现的路径不同，**和上面 embedding 那条是同一个坑**：
>
> | 实现 | 真实路径 | 实测 |
> |---|---|---|
> | LiteLLM 代理（`GENERATION_GATEWAY_URL` 的常见形态，base 自带 `/v1`） | `{base}/models` | ✅ 200 |
> | Infinity 0.0.77（compose 内置的 embedding 容器，base **不带 `/v1`**） | `/models` | ✅ 200 |
> | 同上 | `/v1/models` | ❌ 404 |
>
> 另外 LiteLLM **需要 `Authorization: Bearer {GENERATION_API_KEY}`**：不带 key 返回
> `401 {"error":{"message":"Authentication Error, No api key passed in."}}`。

> ### ⚠️ 探测失败 = **无法判定**，不是「模型不可用」
> 端点可能不支持 `/models`、可能只是抖了一下、这个部署也可能压根没配 key。
> **这些都不足以断定模型不可用。** 契约要求调用方据此**放行**，不得据此拒绝：
>
> | 环节 | 探测成功且模型不在清单里 | 探测失败（无法判定） |
> |---|---|---|
> | 画布保存（preCheck） | `success=false`，提示改选模型 | 放行，无警告 |
> | 画布发布（publish） | 返回 0005，明确拒绝 | **放行** |
>
> 判错的代价不对称：漏判只是回到改动前的行为；误判会把用户挡在发布之外。
> 实现上探测带 60 秒 TTL 缓存，且**失败不写缓存**（一次抖动不该持续影响一分钟）。

### POST `{RERANK_URL}`  ← 可选（v1 默认**不提供**）

OpenAI 风格的重排端点，只被 `ExternalModelReranker` 算子使用。

请求：`{ "model": "Qwen3-Reranker-4B", "query": "...", "documents": ["...", "..."] }`
响应：`{ "results": [ { "index": 0, "relevance_score": 0.9 }, ... ] }`（按分数降序即可）。

`model` 字段的取值：画布上每个 `ExternalModelReranker` 节点可显式选一个注册表中的重排模型
（`kwargs.model`，下拉数据源 `GET /system/rerank-models`）；没选（空值）时用注册表
默认行 → `RERANK_MODEL` → 常量 `bge-reranker-large`。显式选了但注册表里查不到时，
运行期报 `rerank-model-not-configured`，发布时也会被拒 —— 不会静默换成默认模型。

**留空时（默认）三处一致地拒绝，而不是静默降级**：

| 环节 | 行为 |
|---|---|
| 画布保存（preCheck） | 返回 `success=false`，提示改用 `LLMReranker` |
| 画布发布（publish） | 返回 0005，明确拒绝发布 |
| 运行时 | `rerank-endpoint-not-configured` 显式报错 |

> 阶段0 实测：内置默认实现不提供 rerank（`POST /v1/rerank` → 500 `Unsupported provider: openai`）。
> 因此默认工作流的重排用 **`LLMReranker`**（同一个生成模型做重排），不需要额外组件。
> `LLMReranker` 的提示词格式要求模型返回 `{"ranking":[{"document_id":N,"relevance_score":S}]}`，
> 阶段0 已验证可达（返回合法 JSON 且排序正确）。

## 配置项

| 变量 | 含义 | 默认 |
|---|---|---|
| `MODEL_GATEWAY_URL` | embedding 端点 | `https://your-llm-endpoint.example.com` |
| `MODEL_GATEWAY_EMBEDDINGS_PATH` | embedding 路径（拼在 URL 后） | `/v1/embeddings` |
| `MODEL_GATEWAY_API_KEY` | 可选鉴权（当前端点不需要） | 空 |
| `EMBEDDING_MODEL` | **model_code**：发给端点的 `model` 字段 | `Qwen3-Embedding-0.6B` |
| `EMBEDDING_MODEL_NAME` | **model_name**：写进 `kb_kbase.embedding_model` 的名字 | `Qwen3-Embedding-0.6B` |
| `EMBEDDING_DIMENSION` | 向量维度（**校验基准**） | `1024` |
| `EMBEDDING_HOST` | 仅用于容器 `NO_PROXY` 排除 | `your-llm-endpoint.example.com` |
| `GENERATION_MODELS_PATH` | 可用模型列表的路径（拼在 `GENERATION_GATEWAY_URL` 后） | `/models` |

> `EMBEDDING_MODEL` 与 `EMBEDDING_MODEL_NAME` 是**同一模型的两个命名空间，不要合并**：
> 前者是端点认的仓库名，后者是库里的登记名。两者必须与 `kb_embedding` 同一行的
> `model_code` / `model_name` / `dimension` 三个字段一致（种子见 `db/migration/V1__baseline.sql` 与 `V7`）。

## 本地模式（可选：自建 bge 端点）

远端路线下，**768 维的老知识库无法再导入文档或检索**（query 也要用同一个模型向量化），
因为本地不再有任何服务提供 `bge-base-zh-v1.5`。要恢复它们：

```bash
docker compose --profile local-embedding up -d model-gateway     # 拉起本地 Infinity
```
再把 `.env` 指回本地：
```
MODEL_GATEWAY_URL=http://model-gateway:8000
MODEL_GATEWAY_EMBEDDINGS_PATH=/embeddings
EMBEDDING_MODEL=BAAI/bge-base-zh-v1.5
EMBEDDING_MODEL_NAME=bge-base-zh-v1.5
EMBEDDING_DIMENSION=768
```
也可指向任何自建的 OpenAI 兼容 bge 服务 —— 只改这几个变量，代码不用动。

> ### ⚠️ 768 维库被检索时的症状（2026-10-12 实测）
> 默认（远端 1024）下拿 768 维库做**向量**检索，底层会报：
>
> ```
> org.postgresql.util.PSQLException: ERROR: different vector dimensions 768 and 1024
> ```
>
> **但 API 对外返回的是 `code=0000` + 空结果** —— 维度冲突被检索链路的 catch 吞掉了，
> 只在后端日志里能看到 `Error during retrieve operation` + 上面的 PSQLException。
> 表现与「这篇文档确实没命中」无法区分。
>
> 关键词路（`type=1`）不受影响，仍能命中 —— 可以利用这一点快速判别：
> **关键词有、向量恒空，就是这个维度冲突**。
> 根治要么启用本地模式，要么把该库用新模型重新索引一遍。

## 模型清单与动态纳管（**v1.2 起提供注册表**）


### 清单的权威来源：`model_registry` 表

**唯一权威来源是业务库的 `model_registry` 表**（DDL 见
`backend/src/model/repository_pg.py::SCHEMA_STATEMENTS`，
空库快照见 `deploy/init/pg/00-schema.sql`；首次访问注册表时幂等执行，
每进程一次）。
`deploy/.env` 降级为**首次播种 + 回落**：

| 环节 | 来源 |
|---|---|
| 首次启动 | 注册表按 kind 为空时，从 `.env` 播种（`backend/src/model/seed.py`） |
| 运行期 | 注册表；读不到行 / 读库失败 → **逐项回落** `.env`（行为与 v1.1 一致） |
| 新增模型 | 模型管理页（`#/model`）或 `{RKB_PREFIX}/models` 接口，**不需要重启** |

**「不停机」为什么成立**：模型管理接口与解析层（`backend/src/model/resolver.py`）
在**同一个进程**里，写完直接让缓存失效 —— 下一次调用就用上新模型。缓存只为兜住
同一请求内的重复解析与库抖动，不是正确性的依赖。

### 三类模型与端点（OpenAI 兼容）

| kind | 消费面 | 请求形状 |
|---|---|---|
| `llm` | 画布下拉、`getLlmList`、preCheck/publish、编排的改写/重排/合成、抽图沙箱 | `POST {base}{chat_path}` `/chat/completions` |
| `embedding` | 建库下拉 `/embedding/all`、检索期解析、语料向量化 | `POST {base}{embeddings_path}` `/embeddings` |
| `rerank` | 画布 `ExternalModelReranker` 的可用性判定与运行期调用 | `POST {base}{rerank_path}` `/rerank` |

**四个路径都可在每行单独覆盖**（留空 = 用标准路径）—— 这正是上面「路径必须可配」
那三条实测结论的落点：把它们从「部署级配置」细化到了「每个端点各自可配」。

### 每模型「思考配置」（`thinkingMode`）

`model_registry` 的 `thinking_mode` / `thinking_preset` / `thinking_payload`
是**每模型**的思考配置，只在 LLM 行上有意义。各家字段并不相同，因此不写死某一家：

| 模式 | 存储 | 行为（回答生成） |
|---|---|---|
| `none` | preset/payload 为空 | 不发送任何思考片段（默认；由端点决定是否思考） |
| `auto` | preset/payload 为空 | 运行时按 `apiModel` → `modelName` → `baseUrl` 匹配预置目录 |
| `preset` | preset ID + payload 快照 | 发送快照；换 preset 时重新快照，无关编辑不改快照 |
| `custom` | 用户 JSON 对象 | 发送用户配置（白名单/大小校验） |

**调用场景（`thinking_profile`）**：上面的每模型配置用于**回答生成**
（`profile=answer`，默认）。改写、重排、路由等短输出调用固定带
`profile=aux`：**不读取模型行的 `preset`/`custom`**，只按目录自动匹配
“关闭/最低思考”的预置（DeepSeek/GPT-5 等无法完全关闭时取最低档）；
目录未覆盖的模型则不发。这样回答侧的高推理不会漏到辅助调用。
算子级 `thinking_payload`/`chat_template_kwargs`/`reasoning_effort`
仍然最优先。抽图沙箱不在该链路内。

预置目录在代码里（`backend/src/model/thinking_presets.py`），通过
`GET {RKB_PREFIX}/models/thinking-presets?modelName=&apiModel=&baseUrl=` 暴露给
管理页。目录覆盖 DeepSeek（官方 API / vLLM）、Qwen3（DashScope / vLLM）、
GLM-4.5~4.7（托管 / 自建）、Kimi K2 混合、MiniMax M3、GPT-5.1、GPT-5、o 系列、
Gemini 2.5 Flash / 3、豆包、混元、星火、文心自建等；`confidence` 区分
`verified`（仅 DeepSeek vLLM 是本部署实测）与 `standard-doc`。只思考/不可关闭的
变体（`*-thinking`、QwQ、Kimi K3、MiniMax M1/M2、GLM-5 等）被全局排除。

**优先级**：

| 优先级 | 来源 | 行为 |
|---|---|---|
| 1 | 算子级 `config_info['thinking_payload']` / `chat_template_kwargs` / `reasoning_effort` | 最具体，覆盖模型配置 |
| 2 | 注册表 `auto`/`preset`/`custom` 解析结果 | 合并进请求体；`reasoning_effort` 可覆盖全局 effort |
| 3 | 注册表 `none` | **不发送**，且不再读全局 env |
| 4 | env 回落端点（注册表不可用/模型未注册） | `GENERATION_REASONING_EFFORT` 与 `GENERATION_CHAT_TEMPLATE_KWARGS` 只在此时生效 |

`auto` 无匹配时保存为 no-op 并在 `thinkingWarning` 返回 `no_preset_match`，
不阻塞保存；用户可改选预置或自定义。自定义 payload 只允许顶层键
`chat_template_kwargs`、`thinking`、`reasoning_effort`、`enable_thinking`、
`google`，并限制 8192 字节，防止模型行覆盖 `model`/`messages`/`stream` 等调用契约。

`.env` 播种的模型该配置不适用于抽图沙箱（`model/operator_client.py` 只认 `.env`，
见下方「显式例外」）；管理页新增（`source='user'`）的模型走 `llmConfig`，抽图按
`aux` 档解析思考片段。

### 仍然**不做**的三件事

以下三件事**不做**：

| 仍不提供 | 说明 | 理由 |
|---|---|---|
| 按租户/用户隔离的模型可见性 | 按注册人 / 租户过滤模型 | 需要鉴权体系，而本项目明确不增加权限/鉴权校验（`0002`/`0003` 两个错误码都没定义） |
| 按标签做运营选型 | 按标签筛选模型 | 平台运营能力，与本部署的定位无关 |
| 动态推理服务注册中心 | 适配层维护服务名 / 端点 / 创建时间 | 本项目零 ML 运行时依赖，端点由使用方提供（见「未覆盖」一节） |

### ⚠️ 一处**显式例外**：抽图沙箱不读注册表

四套调用栈里，`src/model/operator_client.py`（抽图算子的沙箱子进程）
**默认只认 `.env`**（`MODEL_GATEWAY_URL` + `MODEL_GATEWAY_CHAT_PATH`）。
**`.env` 播种的 LLM（`source='env'`）对抽图仍不由注册表接管** —— 这是有意设计，
不是遗漏：

同一个小文档、同一算子，把它的生成调用改到注册表里的默认 LLM 端点
（`GENERATION_GATEWAY_URL`）之后，抽图**从 7.52s 变成 >8 分钟不返回**。
两个端点对**同一个模型名**都回 200，但 `reasoning_effort` 只在 `llm` 网关上生效 ——
生成端点上的推理模型开始长篇输出 `reasoning_content`。
「同名模型在两个端点上不等价」这件事对**同一批 `.env` 模型**没有解决，端点来源换不得。


**唯一的口子**：`source='user'`（模型管理页新增）的行
**可以**用于抽图 —— 父进程把它解析成 `{url, model, api_key?, thinking_payload?,
timeout?}`，经算子 kwargs 的 `llmConfig` 下发；沙箱里拿不到数据库凭据，子进程查不了
注册表。`.env` 播种的行不下发，行为与上表完全一致。同时 `invoke_llm` 不再重试 4xx
（408/429 除外），确定性失败秒级失败并带「状态码 + 模型名 + 地址」。


### ⚠️ 改 `.env` 的值必须带引号（回落路径仍然适用）

docker compose 自己解析时加不加都对，但**用 shell 取值时不是**：
`set -a; . deploy/.env; set +a` 会把未加引号值里的 `;` 当**命令分隔符**，
变量被静默截断成只剩第一项 —— 不在 `.env` 这层报错，只表现为容器里少了几个模型。

### ⚠️ 密钥落库是明文

注册表存的是端点鉴权用的 API key（`api_key` 列），**明文**。
接口返回一律脱敏（只留末 4 位，见 `ModelRecord.masked_api_key`），但这不改变库里是明文的事实。
这是**有意的取舍**：当前版本没有独立的密钥管理组件，启用本地账号后应由管理员控制
模型管理页的访问。

## 验证方式

```bash
# 宿主上直接验（当前默认端点）
curl -s "$MODEL_GATEWAY_URL$MODEL_GATEWAY_EMBEDDINGS_PATH" \
  -H 'Content-Type: application/json' \
  -d '{"input":["你好，世界"],"model":"Qwen3-Embedding-0.6B"}' \
  | python3 -c 'import sys,json; print("dim =", len(json.load(sys.stdin)["data"][0]["embedding"]))'
# 期望：dim = 1024（与 .env 的 EMBEDDING_DIMENSION 一致）
```

容器内也要验一遍 —— 宿主能通不代表容器能通（`NO_PROXY` 没配对时会被代理接走）：

```bash
docker exec rag-studio-rag-knowledge-base-1 env | grep -E 'NO_PROXY|EMBEDDING_'
# NO_PROXY 里必须能看到 your-llm-endpoint.example.com
```

生成端点声明的模型清单（画布校验用的就是这条）：

```bash
set -a; . deploy/.env; set +a          # 先回读一次，确认没被 shell 截断
echo "$GENERATION_MODELS"              # 应打印全部模型，不是只有第一个

curl -s -H "Authorization: Bearer ${GENERATION_API_KEY}" \
  "${GENERATION_GATEWAY_URL}${GENERATION_MODELS_PATH:-/models}" \
  | python3 -c 'import sys,json; print([m["id"] for m in json.load(sys.stdin)["data"]])'
# 期望：与 .env 的 GENERATION_MODELS 里的模型名对得上（可能多出 provider 前缀别名）
```

## 未覆盖（明确标记）

- **离线/私有网络部署**：默认的远端 embedding 端点需要能出网（或走公司代理，但**必须**同时把它
  从 `NO_PROXY` 里排除的写法搞清楚 —— 见上文警示）。若要用**本地**容器，首次需从 HuggingFace
  下载权重，按 `docs/TECHNICAL-GUIDE.md` §4.7「本地 embedding 的离线权重预置」放入 `model-cache` 卷。
- **语义能力等价性**：`Qwen3-Embedding-0.6B`（以及更早的 bge）与既有生产系统所用模型的
  检索效果差异**未评估**，且维度不同 → **不同维度的向量不能混用同一张表**（04 §3 D-4）。
- **远端端点的可用性/配额**：`your-llm-endpoint.example.com` 由使用方自行提供，**本项目不对它的 SLA、
  限流、模型下线做任何承诺**。它换了模型名或加了鉴权，本项目只会在调用时报错。
