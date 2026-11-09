# 三维审查检查清单

> G1 审查项。三个维度各自的触发模式与必查点。
> 交叉引用: CLAUDE.md §五 Data Flow / §八 Execution Workflow

## 安全维度（security-reviewer 执行）

- 加载 `.claude/rules/owasp-top10.md` 作为唯一 CWE 权威源（IT1-Enforced）
- 触发模式：拼接 SQL/命令/路径、硬编码密钥、弱加密、无授权入口、SSRF、日志泄敏
- 输出 findings 必须含：条款号 + cwe_id + evidence（diff 原文行）
- 见 owasp-top10.md 检查清单

## 性能维度（perf-reviewer 执行）

- N+1 查询：循环内出现 DB 查询/ORM 调用，或新增查询未随循环外批量
- 无界操作：对列表/查询结果未分页、未 LIMIT；递归无终止条件
- 热路径阻塞：请求处理链路上新增同步 IO（网络调用、文件读写、sleep）
- 内存放大：大对象全量载入（一次性 read 全文件/全表到内存且无流式处理）
- 复杂度退化：嵌套循环处理集合（O(n²) 模式），无明显索引/哈希优化
- 严重度经验值：critical=必然拖垮生产（无界全表扫）、high=热路径明显退化、medium=可优化

## 可维护性维度（maintainability-reviewer 执行）

- 函数爆炸：新增函数 > 80 行或嵌套 > 4 层
- 重复代码：本次 diff 内复制粘贴模式（改个变量名的重复块）
- 命名/契约：公共接口命名与现有约定冲突；返回值类型隐式变化
- 错误吞噬：`catch` 块空处理、吞异常继续执行
- 死代码：新增不可达分支、未使用变量/导入
- 测试缺口：新增 public 函数无任何对应测试文件变更（提示，不强制）

## 通过标准

- 每个维度输出独立 findings[]，含 severity / file / line / evidence / fix_suggestion
- evidence 必须引用 diff 中的真实行（禁止描述"整个函数"）
- fix_suggestion 一行可执行（"参数化查询替代拼接"，不是"注意注入风险"）
