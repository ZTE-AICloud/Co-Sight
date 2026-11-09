#!/usr/bin/env python3
"""Fixture: Simulate adaptive topology scenario for W5 testing.

This script simulates a scenario where an adaptive agent needs to decide
whether to switch from W1-Pipeline to W3-MapReduce based on file count.

It does NOT implement the agent itself — it provides the test harness
that an evaluator would use to verify a generated agent's behavior.
"""

import os
import json
from pathlib import Path


def generate_test_fixture(base_dir: str) -> dict:
    """Generate a test fixture directory with a variable number of files."""
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)

    # Generate a configurable number of files for testing thresholds
    file_counts = {
        "below_threshold": 30,   # Should NOT trigger W3 switch
        "at_threshold": 51,      # Should trigger W3 switch (>50)
        "far_above": 200,        # Should trigger W3 switch
    }

    fixtures = {}
    for scenario, count in file_counts.items():
        scenario_dir = base / scenario
        scenario_dir.mkdir(exist_ok=True)
        for i in range(count):
            (scenario_dir / f"file_{i:03d}.py").write_text(
                f"# Test file {i}\ndef foo_{i}():\n    pass\n"
            )
        fixtures[scenario] = {
            "file_count": count,
            "expected_topology": "W3-MapReduce" if count > 50 else "W1-Pipeline",
            "directory": str(scenario_dir),
        }

    manifest = {
        "test_name": "adaptive-topology-fixture",
        "scenarios": fixtures,
        "threshold": 50,
        "adaptation_rules": [
            {
                "rule_id": "AR-01",
                "condition": "file_count > 50",
                "target_topology": "W3-MapReduce",
                "transition_action": "Serialize context, split by file, parallel process, reduce results",
            },
        ],
    }

    manifest_path = base / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        manifest = generate_test_fixture(tmp)
        print(json.dumps(manifest, indent=2))
