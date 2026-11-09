---
pattern_id: L2-ER
pattern_name: "L2 Execution Rules"
category: loading_strategy
sub_dimension: L2_rules
selection_rule: "LLM architectural intent determines L2 placement for execution capability module"
solves: "Separate execution rules into independently maintainable rule files, following ECC's layered rules pattern (rules list + checklist + pass criteria)"
fills_spec_section: "rules/{agent-name}-execution-rules.md"
generates: "rules/{agent-name}-execution-rules.md"

variables:
  - name: AGENT_NAME
    description: "The generated agent's name in kebab-case"
    source: derived
    required: true

  - name: AGENT_DISPLAY_NAME
    description: "Human-readable agent display name"
    source: derived
    required: true

  - name: WORKFLOW_STEPS
    description: "List of execution steps with inputs/actions/outputs/verification from W1-W4 template filling"
    source: derived
    required: true

  - name: GATE_POSITIONS
    description: "Gate insertion points if G1 selected, each with step_index, gate_name, review_agent, dimensions, pass_criteria, max_retries, failure_action"
    source: derived
    required: false

  - name: STATE_TRANSITIONS
    description: "State transition table if SM1 selected"
    source: derived
    required: false

  - name: EXECUTION_CONSTRAINTS
    description: "Global execution constraints derived from Safety Constraints and architectural intent"
    source: llm_generate
    required: true

constraints:
  - "Must be independently readable without CLAUDE.md context"
  - "Must include a cross-reference back to CLAUDE.md Execution Workflow chapter"
  - "Must follow ECC layered rules format: rules list + checklist + pass criteria"
  - "Must include step-by-step verification checklist"
---

# {{AGENT_DISPLAY_NAME}} — Execution Rules

> Agent: {{AGENT_NAME}}
> Source: Extracted from CLAUDE.md Execution Workflow
> Format: ECC Rules convention — rules list, checklist, pass criteria
> This file extends CLAUDE.md [Execution Workflow](../CLAUDE.md#五-execution-workflow) with detailed operational rules.

## Execution Constraint Rules

{{#each EXECUTION_CONSTRAINTS}}
- **{{this.label}}**: {{this.description}}
{{/each}}

## Step-by-Step Execution Protocol

{{#each WORKFLOW_STEPS}}
### Step {{@index+1}}: {{this.name}}

**Inputs:**
{{#each this.inputs}}
- `{{this.path}}` — {{this.description}}
{{/each}}

**Actions:**
{{#each this.actions}}
1. {{this.description}}
{{/each}}

**Outputs:**
{{#each this.outputs}}
- `{{this.path}}` — {{this.description}}
{{/each}}

**Verification:**
- [ ] {{this.verification}}
{{/each}}

## Gate Insertion Points

{{#if GATE_POSITIONS}}
{{#each GATE_POSITIONS}}
### Gate after Step {{this.step_index}}: {{this.gate_name}}
- **Review Agent**: {{this.review_agent}}
- **Check Dimensions**: {{this.dimensions}}
- **Pass Criteria**: {{this.pass_criteria}}
- **Max Retries**: {{this.max_retries}}
- **On Failure**: {{this.failure_action}}
{{/each}}
{{else}}
No G1 gates defined for this agent.
{{/if}}

## State Management

{{#if STATE_TRANSITIONS}}
### State Transition Table

| From State | To State | Trigger Condition | Action |
|-----------|----------|-------------------|--------|
{{#each STATE_TRANSITIONS}}
| {{this.from}} | {{this.to}} | {{this.trigger}} | {{this.action}} |
{{/each}}

### Backtracking Rules
- Max backtrack depth: {{max_backtrack_depth}}
- Preserved artifacts: {{preserved_artifacts}}
- Discarded artifacts: {{discarded_artifacts}}
{{else}}
No SM1 state machine defined for this agent.
{{/if}}

## Execution Checklist

Before starting execution:
- [ ] All input files validated (CD1 gate)
- [ ] Execution order confirmed (no skip/parallel violations)
- [ ] Knowledge sources available (K2/K3/K4)

Per-step:
- [ ] Previous step output verified
- [ ] Current step inputs validated
- [ ] Step actions executed in declared order
- [ ] Output written to declared path
- [ ] Output format validated (if DF1 active)

After all steps:
- [ ] All gates passed
- [ ] Final output exists and is non-empty
- [ ] Lineage trace complete (if DP1 active)

## Reference

See [CLAUDE.md — Execution Workflow](../CLAUDE.md#五-execution-workflow) for the workflow architecture overview and state machine diagram.
