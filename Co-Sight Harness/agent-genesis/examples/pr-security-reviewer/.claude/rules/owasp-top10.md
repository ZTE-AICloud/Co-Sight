# OWASP Top 10 — PR Diff 审查规则库

> K4 权威知识源。安全 finding 的 CWE 引用**只准来自本文件**（CD3）。
> 加载策略：L2 按需 Read。安全审查 SubAgent 必须先读本文件再下结论（IT1-Enforced）。
> 交叉引用：CLAUDE.md §三 Knowledge Contract / §四 Safety Constraints

## 规则列表

| 条款 | OWASP | CWE | diff 可判定信号 | 典型严重度 |
|------|-------|-----|----------------|:---------:|
| R-A01-1 | A01 访问控制失效 | CWE-862 缺少授权检查 | 新增 handler/endpoint/controller 方法无权限注解或校验调用 | high |
| R-A01-2 | A01 访问控制失效 | CWE-22 路径遍历 | 文件 API 参数直接拼接路径（`open(dir + input)`、`Path.Combine(userInput)`） | critical |
| R-A02-1 | A02 加密失效 | CWE-327 弱加密算法 | 新增 `DES`/`RC4`/`MD5(用于加密)`/`ECB` 模式调用 | high |
| R-A02-2 | A02 加密失效 | CWE-798 硬编码凭据 | 新增疑似密钥赋值：变量名含 secret/password/token/apikey 且值为字符串字面量 | critical |
| R-A02-3 | A02 加密失效 | CWE-321 硬编码加密密钥 | 密钥材料以字面量参与加密调用 | critical |
| R-A03-1 | A03 注入 | CWE-89 SQL 注入 | SQL 语句与变量拼接（`"SELECT ... " + var`、`f"..."`、`String.format`） | critical |
| R-A03-2 | A03 注入 | CWE-79 XSS | 前端输出未经转义直接拼 DOM/`innerHTML`/模板插值进脚本上下文 | high |
| R-A03-3 | A03 注入 | CWE-78 OS 命令注入 | `os.system`/`exec`/`Runtime.exec`/`subprocess(shell=True)` 含变量拼接 | critical |
| R-A05-1 | A05 安全配置错误 | CWE-548 目录遍历默认开放 | 新增静态文件服务/路由配置无访问限制 | medium |
| R-A06-1 | A06 脆弱组件 | CWE-1104 使用含漏洞组件 | manifest（package.json/pom/requirements）新增依赖且版本命中已知漏洞模式 | high |
| R-A07-1 | A07 认证失效 | CWE-307 无限制重试 | 登录/验证码逻辑无尝试次数限制 | high |
| R-A07-2 | A07 认证失效 | CWE-640 弱密码恢复 | 新增重置密码逻辑使用可预测 token/无过期 | high |
| R-A09-1 | A09 日志监控失效 | CWE-778 记录敏感信息 | 日志语句打印密码/token/完整身份证/卡号 | medium |
| R-A09-2 | A09 日志监控失效 | CWE-532 日志中硬编码凭据 | 日志配置/代码中出现内联凭据字面量 | high |
| R-A10-1 | A10 SSRF | CWE-918 服务端请求伪造 | 新增 HTTP 请求以用户输入为 URL（无 allowlist/无内网拦截） | critical |

**注意**：A04（不安全设计）与 A08（软件完整性失效）多为架构/供应链层面，单次 diff 无法可靠判定——发现疑似时标 `unverified`，不强行定级。

## 检查清单（安全维度）

- [ ] 每个新增/修改的入口点（endpoint/handler/命令）都过了 R-A01 授权检查？
- [ ] 全文搜索拼接模式：`+ "`、`f"`、`${`、`String.format`、`concat(` 逐一确认是否为 SQL/命令/路径拼接
- [ ] 字符串字面量中是否出现密钥形态（≥16 位 base64/hex、AWS AKIA 前缀、私钥头）
- [ ] 加密调用使用的算法名是否命中 R-A02-1 弱算法清单
- [ ] 日志语句的变量是否可能包含凭据（password/token/secret/idCard）
- [ ] 每个 finding 的 cwe_id 都在上表中吗？不在 → 标 `unverified`，禁止编造

## 通过标准

- 所有 critical/high finding 附带：条款号（如 R-A03-1）+ 规则库行号 + diff 中证据行
- 无 "凭记忆" 的 CWE 引用（每个编号可在此文件中找到）
- 报告中的 `unverified` finding 单独成节，不与确定性发现混排

## 未覆盖处理

规则库未覆盖的可疑模式：描述现象 + 标注 `unverified: true` + 建议人工复核点。**禁止**为未覆盖项临时指派 CWE 编号。
