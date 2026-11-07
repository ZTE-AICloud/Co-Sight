# chrome-devtools MCP 辅助验收清单

> 这是**辅助轨**，不参与 CI 门禁。由 Agent 用 chrome-devtools MCP 驱动浏览器，产出证据与问题链接。
> 触发场景：高风险 PR（`needs-mcp-audit`）、发布候选、夜间失败复现。

## 前置

- 栈已启动：`bash e2e/scripts/stack-up.sh`（或指向已有测试环境）。
- 使用独立 browser context / 测试数据前缀（`E2E-<runId>`），不要在共享环境留下数据。
- 不指向生产环境，不使用真实用户凭证。

## 清单

| # | 检查 | 操作 | 证据 |
|---|---|---|---|
| 1 | 入口与健康 | 打开 `/`，确认重定向 `/#/login`；访问唯一健康端点 `/api/co-knowledge/v1/health` | 截图；`list_network_requests` |
| 2 | 导航 | 依次打开文档知识库、图谱知识库、知识检索、对话测试、自定义算子、模型管理 | 每个页面截图；控制台无 error |
| 3 | 列表与控制台 | `#/knowledge` 搜索/清空、翻页；检查 `list_console_messages` | 截图；console 列表 |
| 4 | 建库 | `#/knowledge` → 「新建知识库」弹窗，填名称、上传 md、提交 | 提交前后截图；创建请求与响应 |
| 5 | 导入与检索 | 打开 `#/knowledge/detail/<id>/documents` 等待文件状态成功；检索用 `POST /api/co-knowledge/v1/retrieval` 或对话测试页验证 | 命中片段截图；检索请求/响应 |
| 6 | 编排发布 | `#/flow` 找到测试流，发布，确认状态“已发布” | 发布前后截图；publish 响应 |
| 7 | 对话流式 | `#/chat` 选已发布流，发送问题，观察流式与结束态 | 生成中截图；最终回答截图；SSE 请求 |
| 8 | 模型管理 | `#/models` 三个页签、连接测试、脱敏展示 | 每个页签截图；测试结果 |
| 9 | 错误路径 | 断网/5xx（可选 `emulate` 或后端停止）观察错误提示与恢复 | 错误提示截图；console/network |
| 10 | 性能 | 对 `#/knowledge`、`#/flow` 执行 `performance_start_trace` / `lighthouse_audit` | trace 文件、Lighthouse 报告 |

## 证据归档

```text
e2e/mcp/evidence/<YYYY-MM-DD>-<runId>/
├── screenshots/
├── console/
├── network/
├── traces/
└── report.md          # 每条检查：结论（通过/问题/受阻）+ 证据路径 + issue 链接
```

## 输出规则

- 不产出 pass/fail 门禁；只产出**证据 + 问题链接**。
- 每个问题附最小复现步骤、截图/网络记录、影响范围。
- 与 Playwright 失败相关时，附上对应 trace 路径，便于对照。
- 发现产品缺陷后，在 Playwright 套件补回归用例（5 个工作日内）。
