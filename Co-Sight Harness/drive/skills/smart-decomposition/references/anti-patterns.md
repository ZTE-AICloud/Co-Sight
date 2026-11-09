# 反例：不合格的 Task

## 反例 1：违反规则 1（单一输出断言）

```yaml
name: "实现一些功能"  # 不 specific
steps:
  - "改点东西"  # 不可测
  - "再调一下"  # 不可测
acceptance_criteria:
  - "代码质量好"  # 不可测
```

## 反例 2：违反 5 类约束

```yaml
category: simple
context_limit_tokens: 8000
steps: [...]  # 12 个 step → 超过 simple 的 ≤ 3
```

## 正例：拆分用户认证系统

**原始大任务**（不能跑）：

> "实现用户认证系统"

**拆分为**（可执行）：

- T002 (single_file, 5 工具调用): 实现密码 hash + 验证函数 + 单测
- T003 (single_file, 4 工具调用): 实现 session token 生成 + 过期检查
- T006 (multi_file, 7 工具调用): 整合 login/register/logout API + 错误处理

**5 条规则应用**：

- 规则 1: 每个 T00X 输出 1 个 auth primitive + 单测 ✓
- 规则 3: 模块间通过 `auth/registry.py` 共享，不通过参数传递 ✓
- 规则 4: 第三方 OAuth 文档 > 4k，由 Skill 内部处理 ✓
