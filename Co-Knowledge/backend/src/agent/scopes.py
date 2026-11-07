"""Agent Key 的权限范围与通用限制（**纯标准库**）。

放在独立模块是为了让 ``python3 -m agent_api.cli`` 与 UI 管理接口共用同一份
常量，又不把任何 Web 依赖带进 CLI（见 ``agent_api/__init__.py`` 的 import-light
约定）。``KNOWN_SCOPES`` / ``DEFAULT_SCOPES`` 必须只有这一份，管理接口再接一份
就会漂移。
"""

from __future__ import annotations

#: 可授予的权限。顺序即 UI 展示顺序。
#: 工作流开放**查询**（``workflow:read``）与**执行已发布工作流**（``workflow:run``）；
#: 创建/编排/发布都在控制台画布完成，不授予 API Key。
KNOWN_SCOPES = ('kb:list', 'kb:search', 'kb:answer',
                'workflow:read', 'workflow:run')

#: 新建 Key 的默认权限（与 CLI 的默认值一致）。
DEFAULT_SCOPES = ('kb:list', 'kb:search')

DEFAULT_RATE_LIMIT_PER_MIN = 60
MAX_RATE_LIMIT_PER_MIN = 100000

MAX_NAME_LENGTH = 128
MAX_DESCRIPTION_LENGTH = 200
MAX_CREATED_BY_LENGTH = 128
MAX_KB_IDS = 200

#: 前缀碰撞时的重试次数（10 位随机前缀，碰撞概率极低）。
KEY_PREFIX_RETRIES = 5
