---
pattern_id: L2-DF
pattern_name: "L2 Data Flow Rules"
category: loading_strategy
sub_dimension: L2_rules
selection_rule: "LLM architectural intent determines L2 placement for data flow capability module"
solves: "Separate data flow documentation into an independently maintainable rule file with entity table, flow diagram, schema references, and lineage rules"
fills_spec_section: "rules/{agent-name}-data-flow.md"
generates: "rules/{agent-name}-data-flow.md"

variables:
  - name: AGENT_NAME
    description: "The generated agent's name in kebab-case"
    source: derived
    required: true

  - name: AGENT_DISPLAY_NAME
    description: "Human-readable agent display name"
    source: derived
    required: true

  - name: DATA_ENTITIES
    description: "List of data entities, each with name, type, producer, consumer, format, and persistence"
    source: derived
    required: true

  - name: FLOW_DIAGRAM
    description: "ASCII art data flow diagram from spec-assembly Section 7.3"
    source: derived
    required: true

  - name: SCHEMA_DEFS
    description: "List of schema definitions, each with entity_name and schema_file path"
    source: derived
    required: false

  - name: LINEAGE_RULES
    description: "DP1 traceability rules for data lineage"
    source: llm_generate
    required: false

  - name: VALIDATION_RULES
    description: "Data validation rules and format constraints"
    source: llm_generate
    required: true

constraints:
  - "Every entity must have a declared producer and consumer"
  - "Schema files referenced must exist in schemas/ directory"
  - "Flow diagram must match entity table (cross-reference check)"
  - "Must be independently readable without CLAUDE.md context"
---

# {{AGENT_DISPLAY_NAME}} — Data Flow Rules

> Agent: {{AGENT_NAME}}
> Source: Extracted from CLAUDE.md I/O Contract and Data Flow chapters
> Format: ECC Rules convention — rules list, entity table, flow diagram, checklist
> This file extends CLAUDE.md [I/O Contract](../CLAUDE.md#三-io-contract) with detailed data flow documentation.

## Data Validation Rules

{{#each VALIDATION_RULES}}
- **{{this.label}}**: {{this.description}}
{{/each}}

## Data Entity Table

| Entity | Type | Producer | Consumer | Format | Persistence |
|--------|------|----------|----------|--------|:----------:|
{{#each DATA_ENTITIES}}
| {{this.name}} | {{this.type}} | {{this.producer}} | {{this.consumer}} | {{this.format}} | {{this.persistence}} |
{{/each}}

## Data Flow Diagram

```
{{FLOW_DIAGRAM}}
```

## Schema Definitions

{{#if SCHEMA_DEFS}}
| Entity | Schema File | Description |
|--------|------------|-------------|
{{#each SCHEMA_DEFS}}
| {{this.entity_name}} | [{{this.schema_file}}](../../schemas/{{this.schema_file}}) | {{this.description}} |
{{/each}}
{{else}}
No DF1 schema definitions for this agent. Data format validation is handled inline.
{{/if}}

## Lineage Rules

{{#if LINEAGE_RULES}}
{{#each LINEAGE_RULES}}
- **{{this.label}}**: {{this.description}}
{{/each}}
{{else}}
No DP1 lineage rules defined. Data traceability is not enforced for this agent.
{{/if}}

## Data Flow Checklist

Input validation:
- [ ] All declared input files exist at declared paths
- [ ] Input format validated against schema (if DF1 active)

Runtime validation:
- [ ] Producer writes data in declared format
- [ ] Consumer receives all required fields
- [ ] Intermediate artifacts persist as declared

Lineage validation (if DP1 active):
- [ ] Each output field traceable to its source entity
- [ ] Source annotation format consistent (file:line or pattern:section)
- [ ] No orphan outputs (output without declared producer)

## Reference

See [CLAUDE.md — I/O Contract](../CLAUDE.md#三-io-contract) for input/output file declarations.
See [CLAUDE.md — Data Flow & Format](../CLAUDE.md) for entity definitions and schema format.
