"""系统算子注册表。

这批算子不在库里，而是 ``ingestion/split/operator_all.json`` 里的固定清单
（2 个内置算子：-1 默认切分 / -2 摘要切分）。

``REGISTRY_FILE`` 直接按路径读这份 JSON，**不**经 ``ingestion.runtime``：
本模块属 ``operators``，测试环境要保持「不依赖 app.py、装了 fastapi/pytest 就能跑」；
引入 runtime 会拖进 pyaml_env / psycopg2 等运行期依赖。

三个必须保持的细节：

1. **``isPublished`` 写死 1**，不回读 DTO 的 ``is_published``；
   ``createdDate`` / ``createdBy`` / ``lastUpdatedDate`` / ``lastUpdatedBy`` 为 null，
   ``system`` 也是 null。
2. ``prop`` 是 ``{"support_format": [...]}``，值是**数组**（库里的那条是字符串，
   两边形状不同 —— 前端对系统算子走数组分支）。
3. ``/operator/support`` 的格式匹配是对整个 ``"[md, pdf, docx, txt]"`` 字符串做子串匹配，
   不是集合成员判断；这是既有行为，保持一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from infrastructure.logging.logutil import log

#: 唯一真源：内置系统算子注册表（与 system_split_manager 读同一份）。
#: 它是**数据文件**而非代码，所以这里按路径引用，不 import ingestion 的模块。
#: 它是**只读静态数据**，不需要数据库表。
REGISTRY_FILE = (Path(__file__).resolve().parents[2]
                 / 'ingestion' / 'split' / 'operator_all.json')


def _load_registry() -> list[dict]:
    """读系统算子注册表。读不到时回空表并记日志。"""
    try:
        with REGISTRY_FILE.open(encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        log.exception('failed to load system operator registry: %s', REGISTRY_FILE)
        return []


def fetch_system_operators() -> list[dict]:
    """取系统算子清单。

    **不做缓存** —— 每次调用都拉一遍（每个 format 各拉一次）。
    加缓存会改变「清单改了何时生效」的时序，属于行为变更。
    """
    return _load_registry()


def to_operator_vo(item: dict) -> dict:
    """系统算子 DTO → VO 的映射。"""
    display_name = item.get('display_name') or {}
    desc = item.get('desc') or {}
    supported_format = item.get('supportedFormat')
    return {
        'id': item.get('id'),
        'visibleRange': item.get('visibleRange'),
        'version': item.get('version'),
        'module': item.get('module'),
        'name': display_name.get('zh'),
        'nameEn': display_name.get('en'),
        'description': desc.get('zh'),
        'descriptionEn': desc.get('en'),
        'isPublished': 1,          # 写死，不读 DTO 的 is_published
        'args': _args_to_vo(item.get('defaultArgs')),
        'prop': {'support_format': supported_format},
        'system': None,
        'createdDate': None,
        'createdBy': None,
        'lastUpdatedDate': None,
        'lastUpdatedBy': None,
    }


def _args_to_vo(default_args) -> Optional[list[dict]]:
    """``defaultArgs`` 已经是 ``OperatorParam`` 的形状，只补全缺失的键。"""
    if default_args is None:
        return None
    return [{
        'argName': arg.get('argName'),
        'argType': arg.get('argType'),
        'defaultValue': arg.get('defaultValue'),
        'description': arg.get('description'),
        'placeholder': arg.get('placeholder'),
        'tips': arg.get('tips'),
    } for arg in default_args]


def supports_format(operator_vo: dict, fmt: str) -> bool:
    """``support_format`` 按**子串**匹配（列表转字符串后 contains）。

    例如对 ``List`` 调 ``toString()`` 得到 ``"[md, pdf, docx, txt]"``。
    """
    prop = operator_vo.get('prop') or {}
    value = str(prop.get('support_format'))
    return fmt in value


def matching_system_operators(fmt: str, module: Optional[str]) -> list[dict]:
    """``getSupportSystemOperator``：格式子串命中 **且** ``module`` 完全相等。"""
    return [vo for vo in (to_operator_vo(item) for item in fetch_system_operators())
            if supports_format(vo, fmt) and vo.get('module') == module]


def all_system_operators() -> list[dict]:
    """``GET /operator/system``：不按格式/环节过滤，全量返回。"""
    return [to_operator_vo(item) for item in fetch_system_operators()]
