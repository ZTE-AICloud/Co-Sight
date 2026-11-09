# Dependency Security Checker

> description: 检查依赖安全

## 流程

1. 扫描项目的依赖清单（package.json / requirements.txt / Gemfile 等）
2. 使用 npm audit / pip-audit / bundler-audit 检查已知漏洞
3. 检查许可证类型，标记 GPL 等传染性许可证的依赖
4. 生成依赖安全报告，按严重级别排序
5. 对 CRITICAL 和 HIGH 级别的漏洞给出修复建议（升级版本或替换库）
6. 输出报告到 work/dependency-security-report.md
