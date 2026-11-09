# 契约偏差表

> **打开动机跟 `contracts.md` 不同**：那份是"我要改接口 / 改代码"时看，这份是**要跟后端对齐时**看 ——
> 所以单独一个文件。改代码不用翻这里。
>
> 一行一格的规矩：只写「前端这样 / 后端要确认什么」。**不写原因散文** ——
> 一旦开始解释"为什么前端这么做"，表格就变散文，散文没人维护。
>
> 最后核对：2026-10-16

## 智能体 / 专家（`agents`）

**这张表已经清空**：智能体管理的后端收进本仓了（`server/src/modules/agent/`），
接口形状以 `server/docs/05-openapi/5.01-agent-openapi.yaml` 为正本，不再是「两边各猜一套」。

原来的每一条都有了落点：id 由服务端发 `agt_<uuid>`（不再由前端 slug 化）、重名 409 不自动
加后缀、`dir` 返回绝对路径、status 改为派生的产物状态、分页有 `page`/`pageSize`、
`update` 存在且身份在路径上、`requestId` 幂等键**仍未实现**（缺口见 `open-questions.md`）。

**唯一还留着的一条**：

| 项 | 前端这样 | 后端要确认 |
|---|---|---|
| `requestId`（幂等键） | 还没有 —— 首页与新建弹窗都没有它 | 收不收这个字段？去重窗口多长？（口径见 `contracts.md` §4） |

## 模型（`models`）

已接框架（`Cosight-Harness-开源/model-config-api.md`），不再有 mock：

| 项 | 现在的行为 |
|---|---|
| 动作 | **只有 `list`，且只读**（没有新增/编辑/删除/「测试连通性」）；写在框架界面里做 |
| `apiKey` | 只在服务端进程里；本仓只代理框架的列表端点，`/active` 与 `/{id}`（含明文密钥）不代理 |
| `id` | 框架的 uuid |
| `protocol` | 直接用框架给的 `anthropic` / `openai`，不从 `provider` 硬推 |
| 默认选中 | 首页用列表同一响应里的 `activeId`；没有生效模型时取第一个。设计页的真会话读会话自己的 `modelId`，为空时显示「选择模型」。预览 / 评估**首次**建会话（还没有会话可继承）时，前端按「工作区 `defaultModelId` → `activeId` → 列表第一项」解析后显式传给 `sessions/create`（`shared/api/default-model.ts`）；服务端不猜模型 |
| 切换 | 设计页发送框的模型选择器调 `POST /sessions/:sessionId/update`；有活跃 run 时后端 409，前端提示停下后再切。候选只有模型列表，没有「跟随本机配置」项 |

## 会话（`sessions`，创建会话那一套还没实现）

| 项 | 前端这样 | 后端要确认 |
|---|---|---|
| 「这场创建会话」怎么找 | 有首页交接的 `initSessionId` 时**直接打开那一场**（校验 agentId / stage）；否则按 `(agentId, development)` 取最近一条（`sessions/list`，updatedAt 降序取第一条）；没有就 `sessions/create`。见 `features/agent-create/useCreationChat.ts` | 认不认这个推法？（`purpose` 列已删，没有字段能标识"创建用途"）同 stage 建了第二场时，前端拿到的就是"最近用过的那场"，可能不是用户以为的那场 |
| 创建会话与首轮消息 | **过渡实现**：首页经路由 state 把原话带进设计页，设计页打开 development 会话后若为空则补发一次；后端 `init.input` 只校验不落库（口径见 `contracts.md` §4） | 已按「前端补发」走；目标契约（turn=0 + 幂等 start + requestId 去重）仍未实现 |
| 消息 `state` | **不用**：忙碌态由 `runs/list` 最近一条的 status 判定（沿用 `useLiveSession`），不读消息的 pending/running | 契约 §4 那套「按消息 state 驱动、`start` 幂等点火」本期前端没实现 —— 后端还留着这条路吗？ |
