"""Agent 接口（REST + MCP）的进程内实现。

本包刻意保持 **import-light**：``schema`` / ``keys`` / ``cli`` 只依赖标准库或
``infrastructure.db.kb``，不应因为导入本包就拉起 FastAPI / MCP 依赖树 ——
容器内的 ``python3 -m agent_api.cli`` 靠这一点。
"""
