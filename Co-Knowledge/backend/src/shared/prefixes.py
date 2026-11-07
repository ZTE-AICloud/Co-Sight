"""对外路由前缀的**单点定义**。

所有后端接口（含编排、Agent、图谱检索、账号）都只挂 :data:`RKB_PREFIX` 一条前缀，
nginx 也只反代它。

## 纪律

不要在别处再写第二份前缀字面量：nginx、前端 ``.env``、verify 脚本各自持有一份
「配置态」的副本是不可避免的（它们在不同的运行时里），但**后端代码**里只能有这一处。
"""

#: 对外契约前缀（nginx 只暴露它）。外部集成方请使用这个前缀。
RKB_PREFIX = '/api/co-knowledge/v1'

#: Agent REST facade：挂在 RKB_PREFIX 下，经 nginx 暴露。
#: 与 UI 面共用一条前缀，避免引入第二条对外契约前缀（见本模块 docstring 的纪律）。
AGENT_PREFIX = f'{RKB_PREFIX}/agent'

#: MCP Streamable HTTP 的精确路径（不是 RKB_PREFIX 下的通配子路径）。
#: nginx 需要为它单独关缓冲；app.py 必须在 register_rkb_api 之前注册它。
AGENT_MCP_PATH = f'{RKB_PREFIX}/mcp'

#: Agent API Key 的 UI 管理面。
#: 与 ``AGENT_PREFIX`` **平级**而不是它的子路径：``AGENT_PREFIX`` 由
#: ``app.mount`` 的子应用整体接管，所有请求都要求 Agent Key；管理接口必须走
#: 浏览器会话（AUTH_MODE=gateway 时由网关令牌保护），不能混进去。
AGENT_ADMIN_PREFIX = f'{RKB_PREFIX}/agent-keys'

#: 图谱向量检索的对外路径。
#: 仍在 app.py 里、必须在 register_rkb_api 之前注册（兜底路由会吃掉同前缀的后注册路径）。
GRAPH_RETRIEVE_PATH = f'{RKB_PREFIX}/retrieval/graph'

#: 本地账号登录：``status/login/logout/me/password``。
#: 与其它领域共用 RKB_PREFIX；必须在 register_rkb_api 之前注册（同一个兜底路由坑）。
AUTH_PREFIX = f'{RKB_PREFIX}/auth'
