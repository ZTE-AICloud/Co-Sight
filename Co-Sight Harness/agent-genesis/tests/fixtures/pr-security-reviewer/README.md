# Golden Sample — pr-security-reviewer (P0 baseline)

> P0 完整 ceremony 产物 + Step 4 实施结果 + gate verdict。用于：
> - P1/P2/P3 加速前后的回归对比
> - Step 5 readiness-verifier 与 Step 6 runtime-evaluator 在 SubAgent 恢复时的重现

## 目录

| Path | 用途 |
|------|------|
| clarified-agent-requirements.yaml | Step 1 澄清器输出（澄清节点 PASS/GAP_RESOLVED 状态） |
| phase1-matching-decision.md | Step 2a 模式匹配 v2（frontmatter+结构决策+决策物化） |
| phase2-review.md | Step 2b G017 三层+M4-M6 通过回执 |
| matched-assets.yaml | Step 3a 资产匹配（双轴 9 模式映射） |
| adapted-assets.yaml | Step 3b 逐资产五维适配分析 |
| build-plan.md | Step 3 build-plan v2（决策物化表 + 16 per-file yaml） |
| human-review.md | Step 3c DC-001 展示面（11 节 + mermaid） |
| output-snapshot/ | Step 4 实施快照（23 文件，含 CLAUDE.md/3 subagents/schema 等） |
| gate-results/ | 全步骤 gate verdict（PASS/DEFERRED/PASS-WITH-CONDITIONS） |

## 恢复 ceremony（用于回归对比）

```bash
# 完整复跑：使用本目录的澄清输出 + 匹配决策，跳过 Step 1-3，直接进 Step 4
cp tests/fixtures/pr-security-reviewer/clarified-agent-requirements.yaml .agent-genesis/work/<name>/agent-creation/
cp tests/fixtures/pr-security-reviewer/phase1-matching-decision.md .agent-genesis/work/<name>/agent-creation/
# 然后从 Step 3 build-planning 重跑
```

## 验收基线（pass-criteria.md 在 output-snapshot/evaluation/）

- 3 planted fixtures: 密钥 / 注入 / 干净 diff
- 期望: 密钥→critical, 注入→critical, 干净→「无 critical 问题」零误报
- readiness_score ≥ 58；placeholder_count == 0
