# Agent Design Patterns — Pattern Index

> Source of truth: `knowledge/pattern-catalog.yaml`, `knowledge/pattern-matcher.yaml`, `knowledge/spec-assembler.yaml`
> Template files: co-located in this directory (30 design pattern `.template.md` files)
> This Skill is self-contained — all template files are included.

## All 30 Patterns

| Pattern ID | Category | Sub-Dimension | Selection Rule | Description | Template Path |
|-----------|----------|:---:|---|-------------|---------------|
| W1-Pipeline | Workflow | Decomposition | 4选1互斥 | Task decomposes into fixed, ordered step sequence; each step has singular responsibility, output validates before passing to next step | `skills/agent-design-patterns/patterns/W1-pipeline.template.md` |
| W2-Router | Workflow | Decomposition | 4选1互斥 | Different input types require different processing paths; entry-point classification dispatches to correct branch | `skills/agent-design-patterns/patterns/W2-router.template.md` |
| W3-MapReduce | Workflow | Decomposition | 4选1互斥 | Multiple homogeneous independent sub-tasks execute in parallel; results aggregated in reduce step | `skills/agent-design-patterns/patterns/W3-mapreduce.template.md` |
| W4-LeaderWorker | Workflow | Decomposition | 4选1互斥 | Leader analyzes input, dynamically spawns Workers at runtime; most flexible, most complex | `skills/agent-design-patterns/patterns/W4-leaderworker.template.md` |
| W5-Adaptive | Workflow | Decomposition (Meta-Overlay) | 可选叠加 | Meta-decomposition overlay wrapping W1-W4; runtime topology switching based on pre-defined measurable conditions with audit trail | `skills/agent-design-patterns/patterns/W5-adaptive.template.md` |
| W6-Self-Referential-Loop | Workflow | Decomposition (Meta-Overlay) | 可选叠加 | Agent self-iterates within a single prompt context; completion promise token triggers stop hook that re-feeds prompt until standards met; max iterations hard-limited | `skills/agent-design-patterns/patterns/W6-self-referential-loop.template.md` |
| G1-Reviewer-Gate | Workflow | Quality Gate | 可选叠加 | Independent agent reviews each step's output before proceeding; max retries with blocking on exceeded limit | `skills/agent-design-patterns/patterns/G1-reviewer-gate.template.md` |
| SM1-FSM | Workflow | State Mgmt | 可选叠加 | Non-linear execution path; intermediate results trigger different next steps; failures allow backtracking to prior states | `skills/agent-design-patterns/patterns/SM1-fsm.template.md` |
| M1-Model-Selection | Workflow | Model Selection | 可选叠加 | Per-step model annotation (opus/sonnet/haiku) based on reasoning depth and latency tolerance; opus for deep reasoning/architecture/security, sonnet as default, haiku for fast lightweight tasks | `skills/agent-design-patterns/patterns/M1-model-selection.template.md` |
| K1-LLM-Native | Knowledge | Sources | 多选，至少1个 | Knowledge falls within LLM training data coverage; no external references needed | `skills/agent-design-patterns/patterns/K1-llm-native.template.md` |
| K2-Document-Grounded | Knowledge | Sources | 多选，至少1个 | Reasoning must be based on specific user-provided documents; every conclusion traced to document source | `skills/agent-design-patterns/patterns/K2-document-grounded.template.md` |
| K3-KB-Backed | Knowledge | Sources | 多选，至少1个 | Knowledge in structured KB too large for context; requires retrieval (embedding/graph/SQL) to find most relevant entries | `skills/agent-design-patterns/patterns/K3-kb-backed.template.md` |
| K4-Rule-Driven | Knowledge | Sources | 多选，至少1个 | Agent behavior constrained by external business rule files; rules can change without modifying agent definition | `skills/agent-design-patterns/patterns/K4-rule-driven.template.md` |
| DT1-Linear-Pass-Through | Data | Topology | 可混合 | Data flows step-to-step as pipeline; each step's output is the next step's input; unidirectional chain | `skills/agent-design-patterns/patterns/DT1-linear-pass-through.template.md` |
| DT2-Shared-State | Data | Topology | 可混合 | Multiple components read/write shared state for coordination, progress tracking, and review status | `skills/agent-design-patterns/patterns/DT2-shared-state.template.md` |
| DF1-Schema-Enforced | Data | Format | 可选叠加 | Strict data format; each step's I/O must pass JSON Schema validation; non-conforming output blocked | `skills/agent-design-patterns/patterns/DF1-schema-enforced.template.md` |
| DP1-Traceable-Lineage | Data | Provenance | 可选叠加 | Every output conclusion traces to its input source — which document, which paragraph, which step | `skills/agent-design-patterns/patterns/DP1-traceable-lineage.template.md` |
| IH1-Fire-and-Forget | Interaction | Human | 可按阶段混合 | Input is complete; no mid-execution user dialogue needed; batch-processing style | `skills/agent-design-patterns/patterns/IH1-fire-and-forget.template.md` |
| IH2-Interactive-Clarify | Interaction | Human | 可按阶段混合 | Initial information may be incomplete; proactively ask user for missing information during execution | `skills/agent-design-patterns/patterns/IH2-interactive-clarify.template.md` |
| IH3-Plan-Approval | Interaction | Human | 可按阶段混合 | Execution plan requires user pre-confirmation to avoid directional errors; high-cost tasks | `skills/agent-design-patterns/patterns/IH3-plan-approval.template.md` |
| IT1-Enforced | Interaction | Tool Strategy | 3选1互斥 | Core capabilities must use external tools/Skills; LLM self-analysis is prohibited | `skills/agent-design-patterns/patterns/IT1-tool-orchestrated.template.md` |
| IV1-Progress-Streaming | Interaction | Visibility | 可选 | Long execution processes; user needs current progress, stage, blocking status, time estimate | `skills/agent-design-patterns/patterns/IV1-progress-streaming.template.md` |
| CD1-Input-Gating | Constraint | Domain Template | 可选多选 | Before execution, confirm all critical input files exist and are readable; check first, execute later | `skills/agent-design-patterns/patterns/CD1-input-gating.template.md` |
| CD2-Safety-First | Constraint | Domain Template | 可选多选 | Security-sensitive scenarios; sandboxing, read-only, input sanitization constraints | `skills/agent-design-patterns/patterns/CD2-safety-first.template.md` |
| CD3-Knowledge-Boundary | Constraint | Domain Template | 可选多选 | Explicitly distinguish LLM-trusted domains from required-external-retrieval domains; prevent hallucinations | `skills/agent-design-patterns/patterns/CD3-knowledge-boundary.template.md` |
| CD4-Environment-Preflight | Constraint | Domain Template | 可选多选 | 5 sequential environment checks (tool availability/config/network/disk/version) with tri-state signals; auto-fix for warnings, manual for errors; three-tier aggregation | `skills/agent-design-patterns/patterns/CD4-environment-preflight.template.md` |
| V1-Adversarial-Verification | Constraint | Adversarial Verification | 可选叠加层 | Independent adversarial verifier with dual context isolation, asymmetric voting (4-confirm/2-refute), 4 attack patterns, calibrated abstention, and tiered model strategy | `skills/agent-design-patterns/patterns/V1-adversarial-verification.template.md` |
| E1-Self-Evaluation | Evolution | Self-Evaluation | 可选，依赖链起点 | Agent self-assesses output quality after each execution using 4-dimension scoring (correctness/completeness/format/actionability); identifies gaps and improvement areas | `skills/agent-design-patterns/patterns/E1-self-evaluation.template.md` |
| E2-Controlled-Evolution | Evolution | Controlled-Evolution | 可选，依赖E1 | Deny-by-default scope-based self-repair; within allowed_scopes auto-fix, out-of-scope escalate to factory rebuild | `skills/agent-design-patterns/patterns/E2-controlled-evolution.template.md` |
| E3-Delta-Modification | Evolution | Delta-Modification | 可选，依赖E2+E1 | Precise incremental spec modification with Before/After/Reason three-section Diff protocol; snapshot + automatic rollback on failure | `skills/agent-design-patterns/patterns/E3-delta-modification.template.md` |

## Pattern Categories Detail

### Category 1: Workflow and Orchestration (9 patterns: W1, W2, W3, W4, W5, W6, G1, SM1, M1)

Defines how an agent decomposes and executes work. This is the structural skeleton of the agent — the "how" of execution.

**Decomposition** (W1-W4) is the primary structural choice. All four patterns are mutually exclusive at the top level — an agent has exactly one primary decomposition pattern. Sub-structures within a step can nest a different decomposition pattern, but maximum nesting depth is 2.

**W5-Adaptive** (v3.0) is a **meta-decomposition overlay** — it is NOT mutually exclusive with W1-W4. Instead, it wraps the chosen base topology (W1|W2|W3|W4) and declares pre-defined adaptation rules for runtime topology switching. Unlike OpenSage's "LLM freely decides topology," W5 requires design-time rules with measurable conditions and produces an audit trail for every switch. Max switches is hard-limited (default 3), and circular switching (A→B→A) is forbidden.

**Model Selection** (M1, v3.0) is an optional infrastructure pattern that annotates each execution step with a recommended model tier:
- **opus**: Deep reasoning — architecture decisions, complex analysis, security review, W5 adaptation_decision
- **sonnet**: Balanced (default) — main coding, orchestration, review
- **haiku**: Fast — format checks, simple validation, high-frequency lightweight tasks

M1 is advisory, not enforced — agents can choose different models at runtime. The default is sonnet; opus is specifically recommended for W5 adaptation_decision steps.

**Quality Gate** (G1) and **State Management** (SM1) are overlay patterns — they modify the behavior of the decomposition pattern but do not replace it.

Key relationships within this category:
- W1 (Pipeline) naturally pairs with DT1 (Linear data flow)
- W3 (Map-Reduce) naturally pairs with DT2 (Shared state) for coordination
- W4 (Leader-Worker) often implies SM1 (FSM) for worker lifecycle management
- G1 overlays onto any W pattern by inserting review steps after each execution unit
- W5 wraps any W1-W4 pattern; requires base_topology declaration
- W5 + M1: adaptation_decision step recommends opus (topology switching involves architectural change)
- W5 + SM1: FSM manages base_topology internal state; W5 adaptation rules are separate from FSM state transitions
- W5 + DP1: audit_trail format must be DP1-compatible (traceable adaptation rationale)

### Category 2: Knowledge (4 patterns: K1, K2, K3, K4)

Defines where the agent gets its information. This is critical for correctness in vertical domains — selecting the wrong knowledge pattern leads to hallucinations or stale responses.

Unlike decomposition patterns, knowledge sources are multi-select. An agent typically depends on multiple sources (e.g., LLM-native for general coding + Document-Grounded for domain-specific protocol analysis).

Key relationships:
- K1 (LLM-Native) is often the fallback; other sources override it when they exist
- K2 (Document-Grounded) vs K3 (KB-Backed): K2 is full-document reading (the entire document is relevant); K3 is retrieval-based (too large, need Top-K selection)
- K4 (Rule-Driven) is exact-match; K3 is semantic-similarity matching
- CD3 (Knowledge-Boundary) requires at least one of K2/K3/K4 — declaring "don't use LLM" without an alternative source is invalid

### Category 3: Data Flow (4 patterns: DT1, DT2, DF1, DP1)

Defines how data moves through the agent, its format constraints, and its traceability. This is the plumbing — getting data from one step to the next correctly.

**Topology** (DT1, DT2) patterns can coexist — DT1 handles business data (step output to next step input), while DT2 handles metadata (execution progress, review status).

**Format** (DF1) and **Provenance** (DP1) are optional overlays. DF1 enforces strict schema validation at step boundaries; DP1 adds audit trail metadata to each data entity.

Key relationships:
- Most agents use both DT1 and DT2 simultaneously
- DF1 is not needed for all structured output — only when schema enforcement (with blocking on failure) is required
- DP1 complements K2: K2 says "which document the info came from", DP1 says "which step of the pipeline produced this conclusion"
- G1 (Reviewer Gate) pairs well with DF1 + DP1: reviewers need clear Schema criteria and traceable conclusion sources
- W5-Adaptive + DP1: DP1 traceability extends to W5 audit_trail (which adaptation rule triggered, what state before/after)

### Category 4: Interaction (5 patterns: IH1, IH2, IH3, IT1, IV1)

Defines how the agent interacts with users, tools, and provides visibility into its execution.

**Human Interaction** (IH1-IH3) can vary by execution phase. For example: planning phase uses IH3 (Plan-Approval), execution phase uses IH1 (Fire-and-Forget). But within a single phase, IH1 and IH2 are incompatible.

**Tool Strategy** (IT1) has three mutually exclusive levels. The default is Optional (tools can assist but are not required). Enforced means correctness depends on tools — skipping them causes hallucinations. Forbidden is for pure reasoning tasks.

**Visibility** (IV1) is independent of other interaction choices. The key criterion: will the user be anxious or interrupt execution if they cannot see progress? If the task takes over 1 minute, IV1 is justified.

Key relationship with evolution:
- E2 (Controlled-Evolution) is incompatible with IH1 (Fire-and-Forget) — self-evolution requires mid-execution review and possible escalation, which IH1's no-dialogue mode cannot support

### Category 5: Constraints and Safety (5 patterns: CD1, CD2, CD3, CD4, V1)

Defines the agent's behavioral boundaries — what it must do before executing (CD1), what it must not do during execution (CD2), and what knowledge boundaries it must respect (CD3).

These are domain templates — pre-configured constraint rule sets that provide a baseline. Custom rules can be added. Each constraint rule has a unified structure: content (what), strength (Hard/Soft), scope (Input/Safety/Knowledge/General), trigger (when), violation_action (block/warn/annotate).

Key relationships:
- CD3 requires at least one of K2/K3/K4 — cannot declare "don't trust LLM" without specifying an alternative
- IT1-Enforced automatically generates CD1+CD3 constraint rules
- CD1 and CD2 can coexist (input verification + operational safety)
- S-01 constraint: `data/` directory must never be modified; patterns are read-only from there

### Category 6: Self-Evolution (3 patterns: E1, E2, E3)

Defines the agent's ability to self-assess, self-repair within boundaries, and escalate when out of scope. This is a strict dependency chain: E3 → E2 → E1. No pattern can be selected without its prerequisite.

**E1 (Self-Evaluation)** is the chain entry point. After each execution, the agent self-assesses output quality using the same 4-dimension framework as Phase 5 external evaluation (correctness/completeness/format_compliance/actionability). Scores below threshold (default 3.5) trigger gap analysis with specific evidence and improvement direction.

**E2 (Controlled-Evolution)** depends on E1. When E1 score < threshold AND root cause is within allowed_scopes (deny-by-default whitelist), E2 triggers the evolution flow: gap_analysis → snapshot → delta_generate → G1 self-review → apply → E1 re-evaluate. If root cause is outside allowed_scopes, or evolution cycle exceeds max (default 3), or G1 self-review fails → Escalation Gate → AgentGenesis factory REVISE.

**E3 (Delta-Modification)** depends on both E2 and E1. When E2 confirms modification is feasible, E3 executes precise incremental changes using a three-section Diff protocol (Before/After/Reason). Max 2 spec sections per change (context collapse protection). Snapshot before every change; automatic rollback on E1 degradation, G1 failure, format errors, or scope violation.

**REVISE vs Self-Evolution boundary**:
| Dimension | REVISE (Factory Rebuild) | Self-Evolution (E1→E2→E3) |
|-----------|--------------------------|----------------------------|
| Executor | AgentGenesis Planner+Creator | Agent itself (E2 decision + E3 execution) |
| Trigger | Phase 5 external evaluation FAIL | E1 internal self-evaluation FAIL |
| Scope | Any spec section (full rebuild) | allowed_scopes only (incremental) |
| Method | Phase 1 rematch → Plan Mode → Phase 3 rebuild | E2 gap_analysis → E3 Delta → G1 self-review |
| Cycles | Max 2 REVISE rounds | Max EVOLUTION_CYCLE_MAX cycles |
| Escalation | REPORT_TO_USER | Escalation Gate → AgentGenesis factory REVISE |

Key relationships:
- E1 pairs well with G1 (shared scoring dimensions) and DP1 (traceable evidence for self-evaluation)
- E2 is incompatible with IH1 (Fire-and-Forget) — evolution needs mid-execution escalation capability
- E3 pairs well with G1 (delta changes pass through G1 self-review before application)
- E1/E2/E3 + W5: W5 adaptation is suspended during active E2/E3 evolution cycles (mutual exclusion to prevent concurrent spec modification)

## How to Read a Pattern Template

Each pattern template file (`skills/agent-design-patterns/patterns/{pattern-id}.template.md`) follows this structure:

### YAML Frontmatter

```yaml
---
pattern_id: W1
pattern_name: Pipeline
category: workflow
sub_dimension: decomposition
selection_rule: "4选1互斥"
solves: "Task decomposes into fixed, ordered step sequence"
fills_spec_section: Execution Workflow

variables:
  - name: STEP_NAMES
    description: "Step names extracted from user requirements"
    type: list
    source: user_input
    required: true

constraints:
  - "Steps must declare input/output dependencies"
  - "Cannot skip steps or rollback (unless paired with SM1)"
---
```

### Template Body

The template body contains the pattern's fillable content using `{{PLACEHOLDER}}` syntax. Placeholders correspond to the `variables` declared in the frontmatter.

### Filled Example

Each template ends with a `# Filled Example` section showing a concrete, filled-out instance of the pattern. This is the most valuable section for understanding how variables translate to real content.

### Variables Source Types

| Source | Meaning | How to Fill |
|--------|---------|------------|
| `user_input` | Value comes from user requirements | Extract during requirement analysis |
| `derived` | Value computed from other variables | Follow the `derive_from` instruction |
| `llm_generate` | Value generated by LLM reasoning | Use judgment based on pattern context |
| `decision_table` | Value from the pattern matching decision table | Read from matching phase output |

## Pattern Matching Reference

For detailed semantic matching guidance (typical indicators, distinguishing from similar patterns, clarification prompts), see `knowledge/pattern-matcher.yaml`. The matcher is designed for LLM reasoning — it describes semantic intent rather than keyword triggers.

For assembly ordering (which pattern's template to use first, how to deduplicate, how to merge overlapping content), see `knowledge/spec-assembler.yaml`.

## File Count Verification

| Category | Count | Pattern IDs |
|----------|:-----:|------------|
| Workflow | 9 | W1, W2, W3, W4, W5, W6, G1, SM1, M1 |
| Knowledge | 4 | K1, K2, K3, K4 |
| Data | 4 | DT1, DT2, DF1, DP1 |
| Interaction | 5 | IH1, IH2, IH3, IT1, IV1 |
| Constraint | 5 | CD1, CD2, CD3, CD4, V1 |
| Evolution | 3 | E1, E2, E3 |
| **Total** | **30** | |
