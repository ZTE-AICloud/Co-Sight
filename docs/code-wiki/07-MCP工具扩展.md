# 07 MCP 工具扩展

## MCP 在本项目中的角色

项目支持将外部 MCP Server 暴露的工具注册为 LLM Tools，并在运行时按需调用，从而实现“无需改动主仓库代码，也能扩展工具能力”。

两条关键链路：

- **工具发现（list_tools）**：把 MCP Server 的 tools 列表拉取下来并转换为 OpenAI tool schema。
- **工具调用（call_tool）**：当 LLM 生成的 tool_call 不在本地 functions map 中时，走 MCP 调用通道。

## 配置入口

- 配置文件：`config/mcp_server_config.json`（仓库内默认是空数组，见 [mcp_server_config.json](file:///d:/lingdong/Co-Sight/config/mcp_server_config.json)）
- README 给出的配置结构示例（见 [README.md:L61-L80](file:///d:/lingdong/Co-Sight/README.md#L61-L80)）

## 关键实现点

### 1) MCP Server 适配（stdio / SSE）

- 入口：`MCPEngine.get_server(...)` 会根据 config 选择 stdio 或 SSE（见 [engine.py:L30-L37](file:///d:/lingdong/Co-Sight/app/agent_dispatcher/domain/plan/action/skill/mcp/engine.py#L30-L37)）
- stdio：`MCPServerStdio` 使用 `StdioServerParameters + stdio_client` 启动子进程（见 [server.py:L168-L210](file:///d:/lingdong/Co-Sight/app/agent_dispatcher/domain/plan/action/skill/mcp/server.py#L168-L210)）
- SSE：`MCPServerSse` 使用 `sse_client` 建立 HTTP with SSE 连接（见 [server.py:L217-L258](file:///d:/lingdong/Co-Sight/app/agent_dispatcher/domain/plan/action/skill/mcp/server.py#L217-L258)）

### 2) MCP 工具 schema 转换为 OpenAI tools

- `get_mcp_tools(skills)`：对 `skill_type=local_mcp` 的技能启动临时事件循环，拉取 tools 列表（见 [skill_to_tool.py:L69-L90](file:///d:/lingdong/Co-Sight/app/cosight/agent/base/skill_to_tool.py#L69-L90)）
- `convert_mcp_tools(...)`：把 MCP tool 的 `inputSchema` 转换成 OpenAI tool 的 `parameters`（见 [skill_to_tool.py:L92-L131](file:///d:/lingdong/Co-Sight/app/cosight/agent/base/skill_to_tool.py#L92-L131)）

### 3) BaseAgent 如何决定“本地工具 vs MCP 工具”

- `BaseAgent.__init__` 里构建 `self.tools`（本地技能 + MCP 工具）与 `self.functions`（本地可执行函数映射）（见 [base_agent.py](file:///d:/lingdong/Co-Sight/app/cosight/agent/base/base_agent.py#L36-L54)）
- `BaseAgent._execute_tool_calls`：当 `function_name in self.functions` 时走本地；否则走 `_execute_mcp_tool_call`（见 [base_agent.py:L439-L462](file:///d:/lingdong/Co-Sight/app/cosight/agent/base/base_agent.py#L439-L462)）
- `MCPEngine.invoke_mcp_tool`：真正执行 MCP 调用并将返回内容拼成字符串回传给 LLM（见 [engine.py:L56-L87](file:///d:/lingdong/Co-Sight/app/agent_dispatcher/domain/plan/action/skill/mcp/engine.py#L56-L87)）

## 开发建议（避免踩坑）

- 让 MCP tool 的 `inputSchema` 尽量显式：`type/properties/required` 越完整，LLM 生成参数越稳定。
- MCP 工具输出尽量“短而结构化”：长文本可以通过文件落盘（如写入 workspace）再返回路径，方便前端展示与复查。

