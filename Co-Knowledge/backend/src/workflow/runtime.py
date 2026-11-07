"""flow_api 的**运行时单例**：HTTP 路由与进程内调用共用同一个 FlowService。

为什么需要它：编排并入后，画布配置有了两条读法 ——
  1. RKB 自己的路由 `GET /flow` / `GET /flow/published`；
  2. 编排在进程内直接读同一份配置（`chat.adapters.rkb_inprocess.get_flow_config`）。
如果两边各建一个 `FlowService`，将来任何一侧加了缓存/连接池，另一侧就看不到，
「HTTP 读到的画布」与「编排跑的画布」会悄悄分叉 —— 那是最难查的一类问题。

所以：**生产装配只此一处**。`register_flow_api` 在未注入 store/替身时也取这一个实例；
单测注入自己的 store 时不受影响（各建各的，隔离依旧）。
"""

from __future__ import annotations

from workflow.service import FlowService
from workflow.repository import create_default_store

_service: FlowService | None = None


def get_flow_service() -> FlowService:
    """生产默认的 FlowService（惰性建、进程内唯一）。

    惰性而非模块级构造：`create_default_store()` 会 import psycopg2，
    而单测环境不需要 psycopg2 —— 模块级构造会让「只装了 fastapi/pytest」
    的测试环境在 import 期就炸。
    """
    global _service
    if _service is None:
        _service = FlowService(create_default_store())
    return _service
