# Python Code Analyzer

> description: 分析 Python 代码的代码质量、安全问题和性能瓶颈。当用户请求分析 Python 代码时触发。输入为文件路径或代码片段，输出 Markdown 格式分析报告到 work/ 目录。

## 核心指令

1. 读取目标 Python 文件，执行静态分析
2. 检查项: PEP8 合规、常见安全漏洞、性能反模式
3. 所有发现标注严重级别（CRITICAL/HIGH/MEDIUM/LOW）
4. 输出报告到 `work/{name}-analysis-report.md`

## 详细规范

详细检查规则见 `references/pep8-checklist.md`、`references/security-patterns.md`。

确定性校验使用 `scripts/verify_pep8.py` 执行（不依赖 LLM 判断格式问题）。

报告模板见 `templates/report-template.md`。
