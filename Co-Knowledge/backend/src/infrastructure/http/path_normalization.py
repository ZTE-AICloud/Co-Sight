"""路径里的连续 ``/`` 折叠 —— 容忍空路径段。

**为什么需要**：web 的 ``frontend/src/api/operator.js`` 把 URL 拼成
``${VUE_APP_KBASE_BASE}//operator/template/download``（双斜杠，实测浏览器就是这样发的）。
空路径段直接被丢掉 —— 所以 ``//operator/x``、甚至 ``///operator/x`` **都能命中**
``/operator/x`` 的映射（三种斜杠数都返回同一份 ZIP）。
Starlette 是精确匹配，``//operator/x`` 匹配不到任何路由 → 落进 kb_api 的兜底路由
→ ``0005 + msg=null``，表现为「下载模板」按钮无反应（无 toast、无下载）。

**只折叠重复的斜杠**，单个尾斜杠不动：``/kbase/`` 那条的差异（Starlette 规范化到
``/kbase`` 列表端点、而按原样落 ``{id}`` 且 id 为空）是**另一回事**，在
``tools/verify/verify-kb-api-boundary-diff.py`` 顶部的 ``URL_NORMALIZATION`` 里有专门
说明，别顺手把它一起"修"了。

放在**最外层**（最后注册）执行：路径归一发生在一切处理之前，
Auth / ContentType 这些中间件看到的应该已经是折叠后的路径。
"""

from __future__ import annotations

import re

_DUPLICATE_SLASH = re.compile('/{2,}')
_DUPLICATE_SLASH_BYTES = re.compile(rb'/{2,}')


class CollapseDuplicateSlashesMiddleware:
    """纯 ASGI 中间件：把 ``scope['path']`` 里的 ``//+`` 折叠成一个 ``/``。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') == 'http':
            path = scope.get('path') or '/'
            if '//' in path:
                scope = dict(scope)
                scope['path'] = _DUPLICATE_SLASH.sub('/', path)
                raw_path = scope.get('raw_path')
                if raw_path and b'//' in raw_path:
                    scope['raw_path'] = _DUPLICATE_SLASH_BYTES.sub(b'/', raw_path)
        await self.app(scope, receive, send)
