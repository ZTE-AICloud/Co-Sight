---
name: agent-design-patterns
description: 22 Agent design patterns reference for Claude Code agent construction — workflow, knowledge, data, interaction, and constraint patterns
---

# Agent Design Patterns — 22 Design Patterns for Agent Construction

> Source of truth: `knowledge/pattern-catalog.yaml`, `knowledge/pattern-matcher.yaml`, `knowledge/spec-assembler.yaml`
> Template files: `skills/agent-design-patterns/patterns/*.template.md` (22 files, co-located with this Skill)
> This Skill is L3 (Skill-On-Demand) — loaded only when invoked, not at boot.

## Overview

This Skill provides the complete reference for 22 Agent design patterns across 5 categories, covering 12 sub-dimensions. These patterns are the foundational vocabulary for constructing Claude Code agents — from simple single-agent pipelines to complex leader-worker swarms.

Use this Skill when you need to:
- Design a new agent from requirements
- Match user needs to appropriate design patterns
- Look up pattern definitions, constraints, and selection rules
- Fill pattern templates for agent Spec generation
- Understand pattern relationships and incompatibilities

## Pattern Categories (5 Categories, 12 Sub-Dimensions)

### Category 1: Workflow and Orchestration
Defines agent step decomposition, quality control, and state management.

**Sub-dimension: Decomposition** (4-choose-1, mutually exclusive — only one can be the top-level pattern; sub-structures can nest another, max depth 2)
- **W1-Pipeline**: Fixed, ordered step sequence where each step has a singular responsibility and cannot be skipped. Steps have clear input/output dependencies — like a production line.
- **W2-Router**: Different input types require different processing paths. Entry-point classification dispatches to the correct branch. Paths are mutually exclusive.
- **W3-MapReduce**: Multiple homogeneous, independent sub-tasks execute in parallel, with a final reduce/merge step. Sub-tasks have no dependencies on each other.
- **W4-LeaderWorker**: Task decomposition is not known until runtime. A Leader first analyzes the input, then dynamically spawns Workers based on findings. Most flexible but most complex.

**Sub-dimension: Quality Gate** (optional, can overlay any W1-W4 decomposition)
- **G1-Reviewer-Gate**: Each step's output undergoes independent quality inspection before passing to the next step. Review is performed by a separate Agent (no self-review).

**Sub-dimension: State Management** (optional, can overlay any W1-W4 decomposition; pairs well with DT1+DF1)
- **SM1-FSM**: Execution path is non-linear — intermediate results may trigger different subsequent steps. Failures may require backtracking to prior states for retry.

### Category 2: Knowledge
Defines the agent's information sources and retrieval strategies.

**Sub-dimension: Knowledge Sources** (multi-select, at least one required)
- **K1-LLM-Native**: Task knowledge falls within LLM training data coverage — general programming, analysis, writing knowledge.
- **K2-Document-Grounded**: Reasoning must be based on specific user-provided documents. Every conclusion must be traceable to a document source.
- **K3-KB-Backed**: Knowledge resides in a structured knowledge base, too large for full context. Requires retrieval (embedding/graph/SQL) to inject the most relevant entries.
- **K4-Rule-Driven**: Agent behavior is constrained by external business rule files — naming standards, judgment thresholds, classification criteria. Rules can change without modifying the agent definition.

### Category 3: Data Flow
Defines how data flows between components, format constraints, and provenance requirements.

**Sub-dimension: Topology** (can mix both)
- **DT1-Linear-Pass-Through**: Data passes through steps like a pipeline. Each step's output is the next step's input. Unidirectional chain: A to B to C to D.
- **DT2-Shared-State**: Multiple components read/write a shared state to coordinate execution progress, record intermediate results, and track review status.

**Sub-dimension: Format** (optional, overlays any data topology)
- **DF1-Schema-Enforced**: Data format has strict requirements. Each step's input/output must pass JSON Schema validation. Non-conforming output is blocked.

**Sub-dimension: Provenance** (optional, overlays any data topology)
- **DP1-Traceable-Lineage**: Every output conclusion must be traceable to its input source — which document, which paragraph, which step produced this conclusion. Essential for audit and debugging.

### Category 4: Interaction
Defines human interaction, tool strategy, and visibility.

**Sub-dimension: Human Interaction** (can mix by execution phase)
- **IH1-Fire-and-Forget**: Input is complete; execution does not require interrupting the conversation. Batch-processing style.
- **IH2-Interactive-Clarify**: Initial information may be incomplete. Proactively ask the user for missing information during execution.
- **IH3-Plan-Approval**: Execution plan requires user confirmation before proceeding. Prevents directional errors when execution cost is high.

**Sub-dimension: Tool Strategy** (3-choose-1, defaults to Optional)
- **IT1-Enforced**: Core capabilities must be performed through external tools/Skills — using LLM embedded knowledge for domain analysis is prohibited.
- **IT1-Optional**: Tools/Skills can assist but are not mandatory dependencies.
- **Tool-Forbidden**: Pure reasoning task; no external tools needed or permitted.

**Sub-dimension: Visibility** (optional)
- **IV1-Progress-Streaming**: Long execution processes — user needs to know current progress, what stage, what's blocking, estimated time remaining.

### Category 5: Constraints and Safety
Defines the agent's behavioral boundaries and safety constraints.

**Sub-dimension: Domain Templates** (optional, multi-select; provides baseline rule sets)
- **CD1-Input-Gating**: Before execution, confirm all critical input files exist and are readable. Check first, execute later.
- **CD2-Safety-First**: Security-sensitive scenarios — operations require additional constraints: sandboxing, read-only, input sanitization.
- **CD3-Knowledge-Boundary**: Explicitly distinguish which domains can trust LLM knowledge and which must use external retrieval. Prevents hallucinations in vertical domains.

## When to Invoke This Skill

An agent should invoke `Skill(agent-design-patterns)` when:

1. **Designing a new agent**: When asked to create or design a Claude Code agent from user requirements. This Skill provides the pattern vocabulary for matching user needs to architectural choices.

2. **Analyzing an existing agent**: When reviewing an agent's architecture to understand which patterns it uses and whether the composition is valid.

3. **Reconfiguring an agent**: When an agent's behavior needs to change and you need to understand which patterns to swap, add, or remove.

4. **Learning about patterns**: When you need to understand what a specific pattern does, what problem it solves, and how it differs from similar patterns.

5. **Troubleshooting agent failures**: When diagnosing why an agent is failing — to identify which pattern might be misapplied or missing.

## How to Use This Skill

### 1. Pattern Matching Workflow

When designing an agent from user requirements, follow this matching workflow:

```
User Requirement → Semantic Analysis → Per-Dimension Decisions → Decision Table
```

For each of the 12 sub-dimensions:
1. Read the pattern solves description and typical indicators
2. Read the distinguishing_from notes (how this pattern differs from similar ones)
3. Based on semantic understanding of the user's need (not keyword matching), decide which pattern fits
4. If uncertain, flag for clarification instead of guessing

The full matching guide with detailed distinguishing notes is in `knowledge/pattern-matcher.yaml`.

### 2. Looking Up Pattern Details

Each pattern has:
- **Template file** at `skills/agent-design-patterns/patterns/{pattern-id}.template.md` — contains variable declarations (YAML frontmatter) and fillable template body
- **Catalog entry** in `knowledge/pattern-catalog.yaml` — contains name, solves description, constraints, and references
- **Matcher entry** in `knowledge/pattern-matcher.yaml` — contains typical_indicators, distinguishing_from other patterns, and clarification_needed questions

To look up a specific pattern:
1. Read `skills/agent-design-patterns/patterns/{pattern-id}.template.md` to see the template structure and variables
2. Cross-reference `knowledge/pattern-catalog.yaml` for constraints and selection rules
3. Use `knowledge/pattern-matcher.yaml` for matching guidance if comparing similar patterns

### 3. Filling Pattern Templates

Pattern templates use `{{PLACEHOLDER}}` syntax. Each template declares its variables in YAML frontmatter with:
- `source`: Where the value comes from — `user_input`, `derived`, `llm_generate`, or `decision_table`
- `required`: Whether the variable must be filled
- `type`: The data type (string, list, markdown)

Fill workflow:
1. Read the template's variable declarations to understand what needs to be filled
2. Extract values from user requirements for `user_input` sourced variables
3. Derive values for `derived` sourced variables (the derivation rule is in the `derive_from` field)
4. LLM-generate values for `llm_generate` sourced variables
5. Remove unfilled optional variables from the final output

### 4. Pattern Assembly Order

When building a complete agent Spec from patterns, follow the assembly order defined in `knowledge/spec-assembler.yaml`:

1. Generate Execution Workflow skeleton (from W1-W4 decomposition pattern)
2. Insert review gates (from G1, if selected)
3. Overlay state management (from SM1, if selected)
4. Assemble Knowledge Contract (from K1-K4 + CD3)
5. Assemble Data Flow (from DT1-DT2 + DF1 + DP1)
6. Assemble Interaction Rules (from IH1-IH3 + IT1 + IV1)
7. Assemble Safety Constraints (from CD1-CD3 + custom rules)
8. Derive Evaluation Contract (from assembled Spec)
9. Fill Runtime Adaptation (only if W4 or SM1 selected)
10. Fill Validation (from DF1 + G1)
11. Assemble Frontmatter (from all selected patterns)

### 5. Pattern Relationships

Key relationships to be aware of when combining patterns:

| When you select... | It tends to imply... | Because... |
|-------------------|---------------------|------------|
| W1-Pipeline | DT1-Linear | Pipeline's serial structure naturally fits chain data flow |
| W3-MapReduce | DT2-Shared-State | Parallel tasks need shared state for coordination |
| W4-LeaderWorker | SM1-FSM, K3-KB | Dynamic worker lifecycle fits FSM; dynamic decomposition needs KB support |
| G1-Reviewer-Gate | DF1-Schema-Enforced, DP1-Lineage | Review needs clear Schema criteria and traceable conclusions |
| SM1-FSM | DF1-Schema-Enforced | State transition conditions need format validation for objective judgment |
| IT1-Enforced | CD1/CD3 constraint rules | Forced tool strategy auto-generates "do not self-analyze" and input-gating constraints |
| CD3-Knowledge-Boundary | K2/K3/K4 (at least one) | Declaring "don't use LLM" must specify an alternative source |

**Incompatibilities to avoid:**

| Combination | Issue | Resolution |
|------------|-------|------------|
| IH1 + IH2 same phase | Cannot both be no-dialogue and ask questions | Mix by execution phase |
| W1 + W2 both top-level | Only one top-level decomposition allowed | Choose one as top, nest the other as sub-structure (max depth 2) |
| Tool-Forbidden + IT1-Enforced | Direct contradiction | Choose one |
| K1 only + CD3 | CD3 forbids LLM but only K1 selected — no alternative source | Add K2/K3/K4 |

## Pattern Quick Reference

### Workflow Patterns

| Pattern ID | Name | Solves | Typical Indicators | Template Path |
|-----------|------|--------|-------------------|---------------|
| W1-Pipeline | Pipeline | Task decomposes into fixed, ordered steps with input/output dependencies | User describes sequential phases/steps ("first...then...finally"); steps have data dependencies; structure known before execution | `skills/agent-design-patterns/patterns/W1-pipeline.template.md` |
| W2-Router | Router | Different input types need different processing paths; classify at entry and dispatch | User describes conditional logic ("if/when/depending on..."); entry is unified but downstream forks; one path per execution | `skills/agent-design-patterns/patterns/W2-router.template.md` |
| W3-MapReduce | Map-Reduce | Multiple independent homogeneous sub-tasks execute in parallel; results need aggregation | User describes tasks that can be "simultaneous/parallel/independent"; sub-tasks share structure but differ in input; final merge step exists | `skills/agent-design-patterns/patterns/W3-mapreduce.template.md` |
| W4-LeaderWorker | Leader-Worker | Task decomposition unknown at start; Leader analyzes then dynamically spawns Workers | User says "dynamically decide based on content", "may or may not need certain steps"; open-ended problem space | `skills/agent-design-patterns/patterns/W4-leaderworker.template.md` |
| G1-Reviewer-Gate | Reviewer Gate | Each step's output must pass independent quality inspection before proceeding | User says "review/check/verify each step", "rejected output must be redone"; separate QA role explicitly called for | `skills/agent-design-patterns/patterns/G1-reviewer-gate.template.md` |
| SM1-FSM | Finite State Machine | Non-linear execution path; intermediate results may trigger different subsequent steps; failures require backtracking | User says "if a step fails, go back to previous state and retry"; distinct state concepts (init/processing/retrying/completed/failed); execution has branches and loops | `skills/agent-design-patterns/patterns/SM1-fsm.template.md` |

### Knowledge Patterns

| Pattern ID | Name | Solves | Typical Indicators | Template Path |
|-----------|------|--------|-------------------|---------------|
| K1-LLM-Native | LLM-Native Knowledge | Domain is within LLM training data — general programming, analysis, writing | Domain is general knowledge (not company/industry proprietary); no external docs or KB mentioned | `skills/agent-design-patterns/patterns/K1-llm-native.template.md` |
| K2-Document-Grounded | Document-Grounded | Reasoning must be based on specific user-provided documents as authoritative sources | User says "based on document X/spec/protocol", "take X as authoritative"; document content is the primary or sole basis | `skills/agent-design-patterns/patterns/K2-document-grounded.template.md` |
| K3-KB-Backed | Knowledge-Base Backed | Knowledge in structured KB, too large for context; needs retrieval then injection | User says "search/retrieve from knowledge base", "query historical cases/library"; knowledge volume exceeds context window | `skills/agent-design-patterns/patterns/K3-kb-backed.template.md` |
| K4-Rule-Driven | Rule-Driven | Agent behavior constrained by external rule files — naming standards, thresholds, classifications | User says "judge by standard table/rules", "names must match table X", "thresholds in config file"; structured, table-like criteria exist | `skills/agent-design-patterns/patterns/K4-rule-driven.template.md` |

### Data Patterns

| Pattern ID | Name | Solves | Typical Indicators | Template Path |
|-----------|------|--------|-------------------|---------------|
| DT1-Linear-Pass-Through | Linear Pass-Through | Data flows step-to-step in pipeline fashion; each output becomes next input | User describes clear data handoff between steps; "X's output feeds Y"; unidirectional flow | `skills/agent-design-patterns/patterns/DT1-linear-pass-through.template.md` |
| DT2-Shared-State | Shared State | Multiple components read/write a shared state for coordination | User mentions "multiple agents", "shared progress", "status file"; need to know "where execution is", "review results" | `skills/agent-design-patterns/patterns/DT2-shared-state.template.md` |
| DF1-Schema-Enforced | Schema-Enforced | Strict data format; each step's I/O must pass JSON Schema validation | User says "output must be in X format", "structured output", "Schema defined"; data consumed by downstream programs (not human reading) | `skills/agent-design-patterns/patterns/DF1-schema-enforced.template.md` |
| DP1-Traceable-Lineage | Traceable Lineage | Every output conclusion must trace to its input source — which document, which step | User says "must know where conclusions come from", "traceable/auditable"; compliance/audit requirements; outputs subject to downstream challenge | `skills/agent-design-patterns/patterns/DP1-traceable-lineage.template.md` |

### Interaction Patterns

| Pattern ID | Name | Solves | Typical Indicators | Template Path |
|-----------|------|--------|-------------------|---------------|
| IH1-Fire-and-Forget | Fire-and-Forget | Input is complete; no mid-execution user interaction needed | User says "give input, get output", "no intermediate confirmation needed"; task is function-like: deterministic input to output | `skills/agent-design-patterns/patterns/IH1-fire-and-forget.template.md` |
| IH2-Interactive-Clarify | Interactive Clarify | Initial information may be incomplete; proactively ask user during execution | User says "ask if information is incomplete", "needs clarification"; input quality uncertain, may need multiple dialogue rounds | `skills/agent-design-patterns/patterns/IH2-interactive-clarify.template.md` |
| IH3-Plan-Approval | Plan Approval | Execution plan requires user confirmation before proceeding to avoid directional errors | User says "show me the plan first", "confirm before executing"; task cost is high (time/resources/impact); key decisions need human approval | `skills/agent-design-patterns/patterns/IH3-plan-approval.template.md` |
| IT1-Enforced | Tool-Orchestrated (Enforced) | Core capabilities must use external tools/Skills; self-analysis is prohibited | User says "must use tool/skill X", "do not self-analyze", "must call X"; correctness guaranteed by tool, not LLM reasoning | `skills/agent-design-patterns/patterns/IT1-tool-orchestrated.template.md` |
| IV1-Progress-Streaming | Progress Streaming | Long execution — user needs to know current progress, stage, and remaining time | User says "keep reporting progress", "let me know status"; multi-stage flow expected to exceed ~1 minute | `skills/agent-design-patterns/patterns/IV1-progress-streaming.template.md` |

### Constraint Patterns

| Pattern ID | Name | Solves | Typical Indicators | Template Path |
|-----------|------|--------|-------------------|---------------|
| CD1-Input-Gating | Input Gating | Before execution, confirm all critical input files exist and are readable | User says "must have X to start", "cannot start without X"; inputs from external systems or user files with "may not be ready" risk | `skills/agent-design-patterns/patterns/CD1-input-gating.template.md` |
| CD2-Safety-First | Safety First | Security-sensitive scenarios — sandbox, read-only, input sanitization | User says "don't modify source code", "don't touch database", "don't access network"; involves production systems or irreversible operations | `skills/agent-design-patterns/patterns/CD2-safety-first.template.md` |
| CD3-Knowledge-Boundary | Knowledge Boundary | Explicitly distinguish LLM-trusted domains from required-external-retrieval domains | User says "don't guess/make up", "must search/retrieve", "protocol details must..."; high-accuracy domain where LLM training data is unreliable | `skills/agent-design-patterns/patterns/CD3-knowledge-boundary.template.md` |

### Paradigm Presets (Verified Combinations)

For common agent archetypes, these pre-verified combinations serve as shortcuts:

| Paradigm | Description | Formula | Reference |
|----------|------------|---------|-----------|
| Pipeline | Vertical domain analysis system | W1 + G1 + K2+K3+K4 + DT1+DT2 + DF1 + IH1+IH3 + IT1(Enforced) + IV1 + CD1+CD3 | 需求分析Agent |
| Agent Pool | General-purpose dev toolkit | W2+W3 + K1+K4 + DT2 + IH1 + IT1(Optional) + CD1 | ECC |
| Swarm | Exploratory research tasks | W4 + K3 + DT2 + IH1 + IV1 + CD2 | ClawTeam |
| Analysis | Analytical single-agent | W1 + K2 + DT1 + IH1 + CD1 | — |
| FSM | Dynamic state machine tasks | W1 + SM1 + K4 + DT1 + DF1 + IH1 + CD1 | MetaAgent (SaFo-Lab) |

## Loading Strategy

This Skill is **L3 (Skill-On-Demand)** in the AgentGenesis loading strategy:

| Level | What | When Loaded | Example |
|:-----:|------|------------|---------|
| L1 | CLAUDE.md | Every boot (always) | Role, boundaries, safety constraints |
| L2 | Rules files | Read on demand during relevant Phase | `phases/phase1-analysis.md`, `rules/data-flow-rules.md` |
| **L3** | **Skills (like this one)** | **Invoked via Skill() only when needed** | **`Skill(agent-design-patterns)`** |

This means:
- The 22 pattern definitions are NOT loaded into context at boot
- They are loaded only when an agent explicitly invokes `Skill(agent-design-patterns)`
- This keeps boot context minimal (~6K tokens) while making patterns available on demand
- The `skills/agent-design-patterns/patterns/*.template.md` files remain the authoritative source of truth and are Read by this Skill when specific pattern details are needed

## Related Resources

| Resource | Path | Role |
|----------|------|------|
| Pattern Catalog | `knowledge/pattern-catalog.yaml` | Complete pattern definitions, constraints, selection rules, relationships |
| Pattern Matcher | `knowledge/pattern-matcher.yaml` | Semantic matching guide with distinguishing notes and clarification prompts |
| Spec Assembler | `knowledge/spec-assembler.yaml` | Assembly order and chapter-purpose guidance for building agent Specs |
| Pattern Templates | `skills/agent-design-patterns/patterns/*.template.md` (27 files) | Fillable templates with variable declarations for each pattern |
| Pattern Index | `skills/agent-design-patterns/patterns/INDEX.md` | Navigation index listing all 27 patterns with descriptions and template paths |
