---
pattern_id: L2-RT
pattern_name: "L2 Runtime Adaptation Rules"
category: loading_strategy
sub_dimension: L2_rules
selection_rule: "LLM architectural intent determines L2 placement for runtime adaptation module"
solves: "Separate runtime adaptation strategies (state recovery, exception handling, degradation paths) into independently maintainable rules"
fills_spec_section: "rules/{agent-name}-runtime-rules.md"
generates: "rules/{agent-name}-runtime-rules.md"

variables:
  - name: AGENT_NAME
    description: "The generated agent's name in kebab-case"
    source: derived
    required: true

  - name: AGENT_DISPLAY_NAME
    description: "Human-readable agent display name"
    source: derived
    required: true

  - name: STATE_RECOVERY_RULES
    description: "Rules for recovering from interrupted states or partial completions"
    source: llm_generate
    required: true

  - name: EXCEPTION_STRATEGIES
    description: "Exception handling strategies for known failure modes"
    source: llm_generate
    required: true

  - name: DEGRADATION_PATHS
    description: "Graceful degradation paths when dependencies are unavailable"
    source: llm_generate
    required: false

constraints:
  - "Must be independently readable without CLAUDE.md context"
  - "Must include recovery step-by-step procedures"
  - "Must specify when to escalate to human vs auto-recover"
---

# {{AGENT_DISPLAY_NAME}} — Runtime Adaptation Rules

> Agent: {{AGENT_NAME}}
> Source: Extracted from CLAUDE.md Execution Workflow and Safety Constraints
> Format: ECC Rules convention — rules list, recovery procedures, escalation policy
> This file extends CLAUDE.md with runtime adaptation strategies.

## State Recovery Rules

When execution is interrupted or a state is inconsistent, apply these recovery rules:

{{#each STATE_RECOVERY_RULES}}
### {{this.state_name}}

**Condition**: {{this.condition}}
**Recovery Procedure**:
{{#each this.steps}}
1. {{this}}
{{/each}}
**Post-Recovery Verification**:
- [ ] {{this.verification}}
{{/each}}

## Exception Handling Strategies

{{#each EXCEPTION_STRATEGIES}}
### {{this.exception_type}}

- **Severity**: {{this.severity}}
- **Detection**: {{this.detection}}
- **Response**:
{{#each this.response_steps}}
1. {{this}}
{{/each}}
- **Escalation**: {{this.escalation}}
- **Recovery**: {{this.recovery}}
{{/each}}

## Degradation Paths

{{#if DEGRADATION_PATHS}}
When a dependency is unavailable, apply these degradation paths:

| Dependency | Unavailable Signal | Degradation Behavior | Restore Condition |
|-----------|-------------------|---------------------|-------------------|
{{#each DEGRADATION_PATHS}}
| {{this.dependency}} | {{this.signal}} | {{this.behavior}} | {{this.restore}} |
{{/each}}
{{else}}
No degradation paths defined. Missing dependencies are treated as hard failures (CD2-Safety-First).
{{/if}}

## Escalation Policy

| Condition | Action | Wait for User? |
|-----------|--------|:--------------:|
| Input validation failure (CD1) | Report missing/invalid input, request correction | Yes |
| Knowledge source unavailable (K2/K3) | Attempt degradation if defined, else halt | Yes, if no degradation path |
| Gate failure after max retries (G1) | Report gate findings, request direction | Yes |
| Safety constraint violation (CD2) | Halt immediately, report violation | Yes |
| Transient error (retryable) | Auto-retry up to max retries, then escalate | Only after max retries |

## Runtime Checklist

Before recovery:
- [ ] Confirm current state by inspecting output artifacts
- [ ] Identify the last successfully completed step
- [ ] Check if partial outputs are usable as inputs for the next step

During recovery:
- [ ] Follow recovery procedure for the identified state
- [ ] Preserve all intermediate artifacts (do not discard)
- [ ] Log recovery actions for traceability

After recovery:
- [ ] Verify recovered state is consistent
- [ ] Resume from the next uncompleted step
- [ ] Mark recovery in output lineage (DP1)

## Reference

See [CLAUDE.md — Execution Workflow](../CLAUDE.md#五-execution-workflow) for the state machine diagram.
See [CLAUDE.md — Safety Constraints](../CLAUDE.md#六-safety-constraints) for hard/soft constraint rules.
