"""算子清单的**活对哨兵**：运行时能跑的 ↔ 画布放行的，必须是同一套。

## 为什么要有这一条

「哪些算子能跑」在本仓有**三处**表述，任何一处漂移的表现都是同一个症状：
画布上能选、保存正常、发布**被拒**（或反过来：发布成功、第一次提问 500）。

| # | 位置 | 作用 |
|---|---|---|
| 1 | `engine/core/config_loader/default_packages_info.py` | **运行时**真正 `importlib` 导入的包名 |
| 2 | `src/compat/flow_api/validation.py` 的 `RUNNABLE_OPERATOR_PACKAGES` | **画布 preCheck / 发布**放行的判据（按字符串比对） |
| 3 | `src/compat/flow_api/templates/*.json` 的 `package` 字段 | 建流时**写进画布**的值 |

`tests/test_flow_api_templates.py` 钉的是 3 ⊆ 2，`engine/tests/test_flow_templates.py`
钉的是 3 ∈ 1 —— **1 与 2 之间也需要直接断言**。
"""

from workflow import validation
from engine.config_loader import default_packages_info

_MISSING = '两侧对不上时，症状是「画布上能选、发布被拒」或「发布成功、一跑就 500」'


def test_runtime_operators_are_all_allowed_by_the_canvas_validator():
    """运行时清单 ⊆ 画布放行清单：**能跑的都别被发布卡住**。"""
    runtime = set(default_packages_info.operator_packages.values())
    runnable = set(validation.RUNNABLE_OPERATOR_PACKAGES)
    assert runtime <= runnable, (
        f'这些算子运行时会导入、但画布校验不放行：{sorted(runtime - runnable)} —— {_MISSING}')


def test_canvas_validator_has_no_operator_that_runtime_cannot_import():
    """画布放行清单 ⊆ 运行时清单：**放行的都得真跑得起来**。"""
    runtime = set(default_packages_info.operator_packages.values())
    runnable = set(validation.RUNNABLE_OPERATOR_PACKAGES)
    unknown = runnable - runtime
    assert not unknown, f'这些算子画布放行、但运行时清单里没有：{sorted(unknown)} —— {_MISSING}'


def test_the_two_lists_are_exactly_equal_and_not_empty():
    """两张表完全相同；顺带防「两边都被清空」的假绿。"""
    runtime = set(default_packages_info.operator_packages.values())
    runnable = set(validation.RUNNABLE_OPERATOR_PACKAGES)
    assert runnable == runtime, (
        f'仅运行时 {sorted(runtime - runnable)}；'
        f'仅画布 {sorted(runnable - runtime)}')
    assert len(runtime) >= 9, f'清单只剩 {len(runtime)} 条 —— 像是被误删过'


def test_query_engines_are_registered_and_named_consistently():
    """引擎那一张表同样要非空且带 `core.rag.` 前缀（少了前缀 = 每个画布都判「不可运行」）。"""
    engines = default_packages_info.query_engine_packages
    assert len(engines) >= 3, f'引擎清单只剩 {len(engines)} 条'
    bad = {name: pkg for name, pkg in engines.items() if not pkg.startswith('core.rag.')}
    assert not bad, f'引擎包名缺 `core.rag.` 前缀：{bad}'
