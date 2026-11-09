#!/usr/bin/env python3
"""Fixture: Simulate evolvable agent scenario for E1/E2/E3 testing.

This script provides a test harness that simulates:
1. An agent that produces output with intentional gaps (simulating E1 self-eval)
2. An E2 decision about whether the gap is within allowed_scopes
3. An E3 delta modification with snapshot and rollback

It does NOT implement the agent itself — it provides the test data
that an evaluator would use to verify a generated agent's evolution behavior.
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone


def create_sample_agent_spec(base_dir: str) -> str:
    """Create a sample agent spec with a deliberate gap for evolution testing."""
    spec = Path(base_dir) / "sample-agent" / "CLAUDE.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    content = """---
agent_name: "sample-code-reviewer"
agent_id: "sample-reviewer-v1"
tools: [Read, Bash]
---

# Sample Code Reviewer

## Execution Workflow

### Step 1: Read Input
Read the target file.

### Step 2: Run Tool
Run pycodestyle to check PEP 8 compliance.
```
pycodestyle --select=E501,W291,E302 {target_file}
```

### Step 3: Generate Report
Generate a report of findings.

## Safety Constraints

| # | Constraint | Strength |
|---|-----------|:--------:|
| S-01 | Only read files, never modify | Hard |
"""
    spec.write_text(content)
    return str(spec)


def create_simulated_self_eval(base_dir: str) -> dict:
    """Simulate an E1 self-evaluation finding a gap."""
    report = {
        "self_eval": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_id": "exec-sim-001",
            "scores": {
                "correctness": {"score": 4, "evidence": "4/5 violations detected correctly"},
                "completeness": {"score": 2.5, "evidence": "missing E305 and E703 detection"},
                "format_compliance": {"score": 5, "evidence": "report structure complete"},
                "actionability": {"score": 4, "evidence": "fix suggestions present but missing for E305"},
            },
            "weighted_total": 3.7,  # (4*0.4)+(2.5*0.3)+(5*0.15)+(4*0.15)=1.6+0.75+0.75+0.6=3.7
            "verdict": "FAIL",  # completeness=2.5 < 3.0 threshold
            "gap_analysis": [
                {
                    "dimension": "completeness",
                    "gap": "pycodestyle --select 缺少 E305 和 E703 参数",
                    "probable_cause": "execution_workflow.step_2 工具调用参数不完整",
                    "suggested_fix": "在 --select 中添加 E305,E703",
                }
            ],
        }
    }
    report_path = Path(base_dir) / "work" / "self-eval-report.yaml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # Write as JSON for simplicity
    (Path(base_dir) / "work" / "self-eval-report.json").write_text(
        json.dumps(report, indent=2)
    )
    return report


def simulate_e2_decision(self_eval: dict, allowed_scopes: list) -> dict:
    """Simulate E2 deciding whether to evolve based on self-eval."""
    gap = self_eval["self_eval"]["gap_analysis"][0]
    cause_scope = "execution_workflow.step_2"

    in_scope = any(
        scope["scope"] == cause_scope for scope in allowed_scopes
    )

    return {
        "decision": "evolve" if in_scope else "escalate",
        "gap_cause": cause_scope,
        "in_allowed_scope": in_scope,
        "allowed_scopes": allowed_scopes,
        "evolution_cycle": 1,
        "max_cycles": 3,
    }


def simulate_e3_delta() -> dict:
    """Simulate E3 delta modification."""
    return {
        "delta_id": "delta-001",
        "scope": "execution_workflow.step_2",
        "change_type": "modify",
        "before": "pycodestyle --select=E501,W291,E302 {target_file}",
        "after": "pycodestyle --select=E501,W291,E302,E305,E703 {target_file}",
        "reason": "E1 completeness=2.5 — missing E305 and E703 detection. "
                  "gap_analysis confirmed tool invocation incomplete.",
        "rollback": "remove E305,E703 from --select to restore",
        "affected_sections": ["Execution Workflow — Step 2"],
    }


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        spec_path = create_sample_agent_spec(tmp)
        self_eval = create_simulated_self_eval(tmp)
        allowed_scopes = [
            {"scope": "execution_workflow.step_2", "max_changes_per_cycle": 2},
            {"scope": "knowledge_contract.sources", "max_changes_per_cycle": 1},
        ]
        decision = simulate_e2_decision(self_eval, allowed_scopes)
        delta = simulate_e3_delta()

        print("=== E1 Self-Eval ===")
        print(json.dumps(self_eval, indent=2))
        print("\n=== E2 Decision ===")
        print(json.dumps(decision, indent=2))
        print("\n=== E3 Delta ===")
        print(json.dumps(delta, indent=2))
