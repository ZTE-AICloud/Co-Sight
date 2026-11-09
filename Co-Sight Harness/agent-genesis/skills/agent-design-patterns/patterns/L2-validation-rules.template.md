---
pattern_id: L2-VAL
pattern_name: "L2 Validation Rules"
category: loading_strategy
sub_dimension: L2_rules
selection_rule: "LLM architectural intent determines L2 placement for validation capability module"
solves: "Separate validation rules (schema checks, format constraints, cross-references) into independently maintainable rule files"
fills_spec_section: "rules/{agent-name}-validation-rules.md"
generates: "rules/{agent-name}-validation-rules.md"

variables:
  - name: AGENT_NAME
    description: "The generated agent's name in kebab-case"
    source: derived
    required: true

  - name: AGENT_DISPLAY_NAME
    description: "Human-readable agent display name"
    source: derived
    required: true

  - name: SCHEMA_CHECKS
    description: "Schema validation rules for each data entity"
    source: derived
    required: true

  - name: FORMAT_CONSTRAINTS
    description: "Format constraints for input/output validation"
    source: llm_generate
    required: true

  - name: CROSS_REFERENCE_CHECKS
    description: "Cross-reference consistency rules between entities"
    source: llm_generate
    required: false

  - name: VERIFICATION_PROCEDURES
    description: "Step-by-step verification procedures for Phase V"
    source: llm_generate
    required: true

constraints:
  - "Must be independently readable without CLAUDE.md context"
  - "Each validation rule must have a clear pass/fail criterion"
  - "Must include auto-fix guidance for common failures"
---

# {{AGENT_DISPLAY_NAME}} — Validation Rules

> Agent: {{AGENT_NAME}}
> Source: Extracted from CLAUDE.md Evaluation Contract and Data Flow chapters
> Format: ECC Rules convention — rules list, check procedures, fix guidance
> This file extends CLAUDE.md [Evaluation Contract](../CLAUDE.md#七-evaluation-contract) with detailed validation rules.

## Format Constraints

{{#each FORMAT_CONSTRAINTS}}
### {{this.target}}

- **Constraint**: {{this.constraint}}
- **Validation**: {{this.validation}}
- **On Failure**: {{this.failure_action}}
{{/each}}

## Schema Validation Rules

{{#each SCHEMA_CHECKS}}
### {{this.entity_name}}

- **Schema File**: [{{this.schema_file}}](../../schemas/{{this.schema_file}})
- **Required Fields**: {{this.required_fields}}
- **Field Types**: {{this.field_types}}
- **Value Constraints**: {{this.constraints}}
- **Pass Criterion**: {{this.pass_criterion}}
- **Fix Guidance**: {{this.fix_guidance}}
{{/each}}

## Cross-Reference Checks

{{#if CROSS_REFERENCE_CHECKS}}
| Source Entity | Target Entity | Relationship | Check Rule | Pass Criterion |
|--------------|--------------|-------------|-----------|---------------|
{{#each CROSS_REFERENCE_CHECKS}}
| {{this.source}} | {{this.target}} | {{this.relationship}} | {{this.check_rule}} | {{this.pass_criterion}} |
{{/each}}
{{else}}
No cross-reference checks defined. Entity relationships are not structurally enforced.
{{/if}}

## Verification Procedures

{{#each VERIFICATION_PROCEDURES}}
### Check {{@index+1}}: {{this.name}}

**Purpose**: {{this.purpose}}
**Severity**: {{this.severity}}

**Procedure**:
```
{{this.procedure}}
```

**Pass Criterion**: {{this.pass_criterion}}
**Auto-Fix**: {{this.auto_fix}}
**Manual Fix Guidance**: {{this.manual_fix}}
{{/each}}

## Verification Checklist

Before running verification:
- [ ] All input files exist at declared paths
- [ ] Schema files exist for all DF1 entities
- [ ] Previous phase outputs are available

Running verification:
- [ ] Execute checks in order (Check 1 → Check N)
- [ ] Record pass/fail for each check
- [ ] Auto-fix where possible (max 1 round)
- [ ] Report unresolved failures to user

After verification:
- [ ] All hard checks pass (100%)
- [ ] Soft checks average >= 4.0/5.0
- [ ] Verification report written to `evaluation/verification-report.md`

## Reference

See [CLAUDE.md — Evaluation Contract](../CLAUDE.md#七-evaluation-contract) for pass criteria and scoring dimensions.
