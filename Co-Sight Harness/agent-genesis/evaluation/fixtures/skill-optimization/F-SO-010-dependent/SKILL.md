# Deployment Gate

> description: 部署门禁检查

## 流程

1. 读取依赖安全报告（work/dependency-security-report.md）
2. 读取代码检查报告（work/code-check-report.md）
3. 读取测试结果（work/test-results.md）
4. 如果依赖安全报告中有 CRITICAL 级别漏洞 → 阻断部署
5. 如果代码检查报告中有未解决的 HIGH 级别问题 → 阻断部署
6. 如果测试覆盖率 < 80% → 阻断部署
7. 如果测试有失败 → 阻断部署
8. 全部通过 → 放行，输出 work/deployment-gate-pass.md
9. 任何阻断 → 输出 work/deployment-gate-block.md 并列出阻断原因
