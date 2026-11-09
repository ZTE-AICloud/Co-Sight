---
pattern_id: L2-RR
pattern_name: "L2 Review Rule"
category: loading_strategy
sub_dimension: L2_rules
selection_rule: "Always generated when G1-Reviewer-Gate is selected, independent of L1/L2 loading strategy"
solves: "Generate a G1 review gate checklist applied to the agent's own output verification, following ECC's layered rules pattern"
fills_spec_section: "rules/{agent-name}-review-rule.md"
generates: "rules/{agent-name}-review-rule.md"

variables:
  - name: AGENT_NAME
    description: "The generated agent's name in kebab-case"
    source: derived
    required: true

  - name: AGENT_DISPLAY_NAME
    description: "Human-readable agent display name"
    source: derived
    required: true

  - name: REVIEW_DIMENSIONS
    description: "G1 review dimensions with severity levels and pass criteria"
    source: derived
    required: true

  - name: REVIEW_PROCEDURES
    description: "Step-by-step review procedures for each dimension"
    source: llm_generate
    required: true

  - name: GATE_PASS_CRITERIA
    description: "Overall gate pass criteria derived from G1-Reviewer-Gate pattern"
    source: derived
    required: true

constraints:
  - "Must be independently readable without CLAUDE.md context"
  - "Must follow ECC review format: dimensions + severity levels + pass criteria"
  - "Review dimensions must align with G1-Reviewer-Gate pattern template"
---

# {{AGENT_DISPLAY_NAME}} — Review Rule

> Agent: {{AGENT_NAME}}
> Source: Generated from G1-Reviewer-Gate pattern
> Format: ECC Code Review convention — dimensions, severity, pass criteria
> This file extends CLAUDE.md [Evaluation Contract](../CLAUDE.md#七-evaluation-contract) with the G1 review gate checklist.

## Review Dimensions

| Dimension | Severity | Description | Pass Criterion |
|-----------|:--------:|-------------|---------------|
{{#each REVIEW_DIMENSIONS}}
| {{this.name}} | {{this.severity}} | {{this.description}} | {{this.pass_criterion}} |
{{/each}}

## Severity Levels

| Level | Meaning | Gate Behavior |
|-------|---------|:------------:|
| CRITICAL | Integrity gap, consistency conflict, constraint violation | **Block** — Must fix before passing |
| HIGH | Traceability gap, format issue | **Warn** — Should fix, does not block |
| MEDIUM | Improvement opportunity | **Info** — Recorded, does not block |
| LOW | Style suggestion | **Note** — Recorded, does not block |

## Review Procedures

{{#each REVIEW_PROCEDURES}}
### {{this.dimension_name}}

**Review Step**:
{{#each this.steps}}
1. {{this}}
{{/each}}

**Pass Criterion**: {{this.pass_criterion}}
**Common Failures**:
{{#each this.common_failures}}
- {{this.issue}} → {{this.fix}}
{{/each}}
{{/each}}

## Gate Pass Criteria

{{GATE_PASS_CRITERIA}}

## Review Checklist

Before review:
- [ ] Agent output files generated (CLAUDE.md + .claude/ + evaluation/)
- [ ] All required files exist (Check 1 — Integrity)
- [ ] CLAUDE.md chapters are complete and non-empty

During review:
- [ ] CRITICAL dimension checks completed
- [ ] HIGH dimension checks completed
- [ ] MEDIUM/LOW findings recorded

After review:
- [ ] CRITICAL count == 0
- [ ] HIGH findings documented with fix recommendations
- [ ] Review report written with verdict (PASS / WARN / BLOCK)

## Reference

See [CLAUDE.md — Evaluation Contract](../CLAUDE.md#七-evaluation-contract) for pass criteria.
See [CLAUDE.md — Safety Constraints](../CLAUDE.md#六-safety-constraints) for S-02 (禁止跳过审查门禁).
