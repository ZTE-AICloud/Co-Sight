# Skill 设计实例

> 来源: AgentGenesis 评测用例 + Anthropic 官方规范
> 加载者: Main Agent (Plan Mode), builder-agent (Phase 3)
> 用途: 为 Skill 优化方案设计提供具体可参照的 Before/After 实例

---

## 实例 1: 内联代码 → 脚本提取

### Before (反模式)

SKILL.md 内嵌 60 行 Python 代码做 PEP8 检查。问题：
- 代码嵌入 Markdown 阅读困难
- 无法独立测试脚本逻辑
- 每次 Skill 触发都要把代码注入上下文
- description "帮助处理事情" 无法准确触发

```markdown
# helper
> description: 帮助处理事情

## 代码风格检查
检查代码是否符合pep8规范。下面是一些常见规则：

```python
def check_line_length(file_path):
    violations = []
    with open(file_path, 'r') as f:
        for i, line in enumerate(f, 1):
            if len(line.rstrip('\n')) > 79:
                violations.append({'line': i, 'code': 'E501'})
    return violations
```

...（40+ 行代码省略）

## 依赖检查
检查项目的Python依赖是否有已知的安全漏洞。可以调用 `pip-audit`。
```

### After (Anthropic 规范)

```
pep8-helper/
├── SKILL.md              # 核心指令 + 引用 L3 资源
├── scripts/
│   └── check_pep8.py     # 独立可运行的 PEP8 检查脚本
└── references/
    └── pep8-rules.md     # PEP8 规则详细说明
```

**SKILL.md**:
```markdown
# PEP8 Code Checker

> description: 检查 Python 代码的 PEP8 合规性。当用户请求代码风格检查、PEP8 检查或提交前质量检查时触发。输入为文件路径，输出 Markdown 违规报告到 work/ 目录。

## 核心指令

1. 读取目标 Python 文件
2. 执行 PEP8 合规检查:
   - 确定性检查: `Bash python scripts/check_pep8.py <file_path>` — 行长度、尾随空格、空行数量
   - 语义检查: LLM 判断命名规范、注释质量、代码结构
3. 汇总脚本输出和 LLM 语义判断，生成统一报告
4. 输出到 `work/pep8-report.md`

## 详细规范

PEP8 规则详细说明见 `references/pep8-rules.md`
```

> **关键改变**: 确定性行检查交给脚本（E501/E302/W291 等），LLM 只做命名/注释/结构等需要语义理解的判断。description 使用完整公式。

---

## 实例 2: 参考资料内联 → references/ 提取

### Before (反模式)

SKILL.md 内联 12 种安全漏洞的详细说明和修复建议（SQL 注入、XSS、命令注入...），每种含代码示例。文件 ~100 行全部内联。

```markdown
# Security Scanner
> description: 扫描代码安全漏洞

1. SQL 注入 — 检查是否有字符串拼接构建 SQL 查询的情况。使用参数化查询替代字符串拼接。
   Python 中使用 cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,)) 而非 f"SELECT * FROM users WHERE id = {user_id}"。

2. XSS 漏洞 — 检查是否有未转义的用户输入直接渲染到 HTML。使用 html.escape(user_input) 进行转义。

3. 命令注入 — 检查是否有用户输入直接拼接到系统命令。使用 subprocess.run([cmd, arg]) 替代 os.system(f"cmd {user_arg}")。

...（9 种漏洞类型 + 代码示例省略，约 80 行）
```

问题：
- 12 种漏洞详解占用大量上下文，但只在检查到对应类型时才需要参考
- Agent 在核心扫描指令和安全知识之间"失焦"
- 新增漏洞类型需要修改 SKILL.md body

### After (Anthropic 规范)

```
security-scanner/
├── SKILL.md                    # 核心扫描指令 + 分类引用
├── references/
│   ├── injection-attacks.md    # SQL 注入、命令注入、XXE
│   ├── xss-and-web.md          # XSS、CORS、Cookie 安全、CSP
│   ├── crypto-and-deserialization.md  # 弱加密、不安全反序列化
│   └── file-and-path.md        # 路径遍历、SSRF
├── scripts/
│   └── detect_hardcoded_keys.py  # 检测硬编码密钥（正则确定性）
└── templates/
    └── security-report.md      # 标准化输出模板
```

**SKILL.md** (核心指令部分):
```markdown
# Security Scanner

> description: 扫描代码安全漏洞，覆盖 SQL 注入、XSS、命令注入、硬编码密钥等 12 种常见漏洞类型。当用户请求安全检查、安全审查或提交前安全扫描时触发。输入为文件路径，输出分级安全报告到 work/ 目录。

## 核心指令

1. 读取目标代码文件
2. 逐类型检查:
   - 硬编码密钥: `Bash python scripts/detect_hardcoded_keys.py <file>`
   - 注入类漏洞 (SQL/Command/XXE): 见 `references/injection-attacks.md`
   - Web 安全 (XSS/CORS/Cookie/CSP): 见 `references/xss-and-web.md`
   - 加密与序列化: 见 `references/crypto-and-deserialization.md`
   - 文件与路径安全: 见 `references/file-and-path.md`
3. 每个发现标注: 漏洞类型 + 严重级别 (CRITICAL/HIGH/MEDIUM/LOW) + 证据行号 + 修复建议
4. 按 `templates/security-report.md` 格式输出报告到 `work/security-report.md`
```

> **关键改变**: 12 种漏洞详情分散到 4 个 references/ 文件，按类别分组，Agent 只需加载与当前文件相关的类型。新增漏洞类型只需新增 references/ 文件，SKILL.md body 仅需加一行引用。

---

## 实例 3: 单体长链路 → 分层 + 脚本 + 状态

### Before (反模式)

12 步部署管理全部内联在 SKILL.md 中，52 行但无分层、无脚本、无状态追踪。

```markdown
# Deploy Manager
> description: 部署管理

## Step 1: 读取配置文件
## Step 2: 验证环境
...（12 步全内联）
## Step 12: 回滚检查
```

问题：
- description "部署管理" 太宽泛
- 12 步全部内联，但很多步骤（构建/测试/部署）实际上是通过 Bash 调用外部工具
- 无状态追踪，中断后不知道做到哪步
- 无 references/ 分离环境配置说明
- 无 scripts/ 提取健康检查、冒烟测试等确定性操作

### After (Anthropic 规范)

```
deploy-manager/
├── SKILL.md                     # 核心部署流程 + checkpoint
├── references/
│   ├── environments.md          # Staging/Production 环境配置说明
│   ├── rollback-procedures.md   # 回滚详细流程
│   └── notification-templates.md  # 通知消息模板
├── scripts/
│   ├── health_check.sh          # 健康检查（curl + 超时 + 重试）
│   ├── smoke_test.sh            # 冒烟测试
│   └── validate_config.py       # 配置文件校验
├── templates/
│   └── deploy-config.yaml       # 部署配置模板
└── work/                        # 运行时产生
    └── task-state.json          # checkpoint 状态
```

**SKILL.md**:
```markdown
# Deploy Manager

> description: 执行应用的多环境部署流程（构建→测试→Staging→Production），包含冒烟测试、健康检查和自动回滚。当用户请求部署、发布或上线时触发。输入为 deploy-config.yaml，输出部署报告到 work/ 目录。

## 核心流程

1. 配置校验: `Bash python scripts/validate_config.py deploy-config.yaml`
2. 构建: `Bash docker build ...`（参数从 deploy-config.yaml 读取）
3. 测试: 执行单元测试 + 集成测试
4. Staging 部署: `Bash kubectl apply -f staging/`
5. 冒烟测试: `Bash scripts/smoke_test.sh <staging-url>`
6. Production 部署: `Bash kubectl rollout restart deployment/<name>`
7. 健康检查: `Bash scripts/health_check.sh <production-url> --retry 3`
   - 失败 → 执行回滚，详见 `references/rollback-procedures.md`
8. 通知: 按 `references/notification-templates.md` 发送 Slack 通知

## 状态追踪

每步执行前更新 `work/task-state.json`:
- 读取 → 跳过 DONE 步骤
- 开始 → IN_PROGRESS
- 完成 → DONE
- 失败 → FAILED + 错误信息

## 环境配置

Staging/Production 环境差异详见 `references/environments.md`
```

> **关键改变**: 确定性操作（配置校验、健康检查、冒烟测试）提取为 scripts/；环境配置和回滚流程提取为 references/；增加 task-state.json 做 checkpoint；description 使用完整公式；部署配置有模板。

---

## 实例速查

| 实例 | 核心问题 | 关键修复 | 适用场景 |
|------|---------|---------|---------|
| 1 | 代码嵌入 Markdown | 提取至 scripts/ + LLM 只做语义判断 | SKILL.md 含 >20 行代码块 |
| 2 | 参考文档内联 | 提取至 references/ + 按类别分组 | SKILL.md 含大量规范/规则/示例 |
| 3 | 单体无分层 | 分层 + scripts + references + state | SKILL.md 含 8+ 步骤 |
