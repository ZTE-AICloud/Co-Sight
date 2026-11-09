# pytest API 速查（K2 锚定文档）

> CD3 边界的配对知识源：本文件未覆盖的 API 禁止凭记忆使用，须先跑最小实验验证。
> 覆盖 pytest 9.x 常用断言与 fixture 模式；unittest 为 stdlib 行为（以官方文档为准）。

## 断言（常用全覆盖）

| 用途 | API | 备注 |
|------|-----|------|
| 相等 | `assert a == b` | 失败时自动 introspection 显示差异 |
| 近似 | `pytest.approx(x, rel=1e-6)` | 浮点比较唯一正确姿势 |
| 抛异常 | `with pytest.raises(ValueError, match="msg"):` | match 为正则 |
| 集合包含 | `assert x in coll` / `set(a) <= set(b)` | |
| 近似成员 | `any(pred(x) for x in coll)` | 无内置 contains-pred，用生成式 |
| 参数化 | `@pytest.mark.parametrize("in,exp", [(1,2),(3,4)])` | ids 参数可命名用例 |
| 跳过 | `pytest.skip("reason")` / `@pytest.mark.skipif(cond, reason=...)` | |

## fixture

```python
import pytest

@pytest.fixture
def repo(tmp_path):        # tmp_path: 函数级临时目录，自动清理
    ...

@pytest.fixture(scope="module")   # 模块级只建一次
def heavy():
    ...
```

- 内置：`tmp_path`（Path 对象）、`capsys`（捕获 stdout/stderr）、`monkeypatch`（属性/环境变量补丁，自动还原）
- **禁止**：`monkeypatch` 不还原的场景不存在——它总是自动还原；需要跨测试持久状态时用模块级变量而非全局

## 运行

| 场景 | 命令 |
|------|------|
| 全部 | `python3 -m pytest tests/ -q` |
| 单个 | `python3 -m pytest tests/test_x.py::test_name -q` |
| 失败即停 | `-x`；最近失败优先 `--ff` |
| 输出捕获关闭（调试用） | `-s` |

## 易错点（经验证）

- `pytest.approx` 不支持 `Decimal` 与 `rel` 同用时的某些组合 → 用 `Decimal` 精确比较替代
- fixture 名与测试参数名必须一致；重名会被 shadow
- `match=` 是正约不是子串：特殊字符需 `re.escape`

## unverified 处理

本文件未覆盖的 API：写 3 行最小实验验证行为 → 通过后使用，并在测试注释标 `# verified: <日期>`。
