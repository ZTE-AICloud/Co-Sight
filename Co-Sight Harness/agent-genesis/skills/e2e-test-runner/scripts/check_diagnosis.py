#!/usr/bin/env python3
"""Diagnosis Accuracy Checker — compares Phase 1 diagnosis reports against test fixtures.

Usage:
    python3 check_diagnosis.py --fixtures evaluation/fixtures/skill-optimization/test-fixtures.yaml \
                                --reports work/*/optimize-skill/phase1-diagnosis-report.md
    python3 check_diagnosis.py --fixtures ... --report work/foo/optimize-skill/phase1-diagnosis-report.md \
                                --fixture-id F-SO-002
    python3 check_diagnosis.py --fixtures ... --dry-run   # list fixtures without actual reports
"""
import argparse
import glob
import os
import re
import sys

import yaml


# ── Fixture Loading ─────────────────────────────────────────────────────

def load_fixtures(path):
    """Load all fixtures from test-fixtures.yaml."""
    with open(path) as f:
        content = f.read()

    fixtures = []
    # Each fixture is wrapped in a ```yaml ... ``` code block
    for block in re.finditer(r'```yaml\n(.*?)```', content, re.DOTALL):
        try:
            fixture = yaml.safe_load(block.group(1))
            if fixture and fixture.get("fixture_id"):
                fixtures.append(fixture)
        except yaml.YAMLError as e:
            print(f"WARN: Failed to parse fixture block: {e}")

    return fixtures


# ── Diagnosis Report Parsing ────────────────────────────────────────────

DIMENSION_NAMES = {
    "decomposition": r"(?:Decomposition|分解)",
    "information": r"(?:Information|信息)",
    "state": r"(?:State|状态)",
    "verification": r"(?:Verification|校验)",
    "design_form": r"(?:Design Form|设计形态)",
    "global_context": r"(?:Global Context|全局上下文)",
}


def _parse_dimension_status(text, dim_regex):
    """Extract PASS/FAIL status for a dimension from the diagnosis report."""
    # Look for table rows like: | Decomposition 分解 | PASS | — |
    pattern = rf'{dim_regex}.*?\|.*?\b(PASS|FAIL)\b'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def parse_diagnosis_report(path):
    """Parse a phase1-diagnosis-report.md into structured data.

    Returns dict with:
      - dimensions: {dim_name: {"status": "PASS"/"FAIL", "severity": ...}}
      - recommended_patterns: list of pattern numbers
      - boundary_decision: str
    """
    with open(path) as f:
        text = f.read()

    result = {
        "dimensions": {},
        "recommended_patterns": [],
        "boundary_decision": None,
        "raw": text,
    }

    # Parse dimension statuses from the summary table
    for dim_key, dim_regex in DIMENSION_NAMES.items():
        status = _parse_dimension_status(text, dim_regex)
        if status:
            result["dimensions"][dim_key] = {"status": status}

    # Extract recommended pattern numbers (模式 1, 模式 2, etc.)
    pattern_refs = re.findall(r'模式\s*(\d+)', text)
    result["recommended_patterns"] = sorted(set(int(p) for p in pattern_refs))

    # Extract boundary decision
    boundary_patterns_text = [
        r'(?:纯\s*Skill\s*优化|SKILL_ONLY)',
        r'(?:部分超出|PARTIALLY_EXCEEDED)',
        r'(?:完全超出|FULLY_EXCEEDED)',
    ]
    for bp in boundary_patterns_text:
        if re.search(bp, text, re.IGNORECASE):
            if 'SKILL_ONLY' in bp or '纯' in bp:
                result["boundary_decision"] = "SKILL_ONLY"
            elif 'PARTIAL' in bp or '部分' in bp:
                result["boundary_decision"] = "PARTIALLY_EXCEEDED"
            elif 'FULLY' in bp or '完全' in bp:
                result["boundary_decision"] = "FULLY_EXCEEDED"
            break

    return result


# ── Comparison Logic ────────────────────────────────────────────────────

def compare_diagnosis(actual, fixture):
    """Compare parsed diagnosis report against fixture expectations.

    Returns list of (check_name, result, detail) tuples.
    """
    checks = []
    expected = fixture.get("expected", {})

    # 1. Dimension status comparison
    expected_diagnosis = expected.get("diagnosis", {})
    if expected_diagnosis:
        actual_dims = actual.get("dimensions", {})
        for dim_key in ["decomposition", "information", "state", "verification", "design_form", "global_context"]:
            dim_expect = expected_diagnosis.get(dim_key)
            if dim_expect is None:
                continue

            expected_status = dim_expect if isinstance(dim_expect, str) else dim_expect.get("status")
            actual_dim = actual_dims.get(dim_key, {})
            actual_status = actual_dim.get("status") if isinstance(actual_dim, dict) else actual_dim

            if expected_status and actual_status:
                match = expected_status.upper() == actual_status.upper()
                checks.append((
                    f"dimension_{dim_key}",
                    "PASS" if match else "FAIL",
                    f"expected={expected_status}, actual={actual_status or 'NOT_FOUND'}",
                ))
            elif expected_status and not actual_status:
                checks.append((
                    f"dimension_{dim_key}",
                    "FAIL",
                    f"expected={expected_status}, actual=NOT_PARSED",
                ))

    # 2. Recommended patterns comparison
    expected_patterns = expected.get("selected_patterns_include", [])
    actual_patterns = actual.get("recommended_patterns", [])
    if expected_patterns:
        missing = set(expected_patterns) - set(actual_patterns)
        extra = set(actual_patterns) - set(expected_patterns)
        if not missing and not extra:
            checks.append(("patterns", "PASS", f"matched: {actual_patterns}"))
        else:
            detail_parts = []
            if missing:
                detail_parts.append(f"missing={missing}")
            if extra:
                detail_parts.append(f"extra={extra}")
            checks.append(("patterns", "FAIL", "; ".join(detail_parts)))

    # 3. Boundary decision comparison
    expected_boundary = expected.get("boundary_decision")
    actual_boundary = actual.get("boundary_decision")
    if expected_boundary and actual_boundary:
        match = expected_boundary == actual_boundary
        checks.append((
            "boundary_decision",
            "PASS" if match else "FAIL",
            f"expected={expected_boundary}, actual={actual_boundary}",
        ))
    elif expected_boundary and not actual_boundary:
        checks.append((
            "boundary_decision",
            "FAIL",
            f"expected={expected_boundary}, actual=NOT_PARSED",
        ))

    # 4. Anthropic violations (SF checks) — only if fixture defines them
    expected_sf = expected.get("anthropic_violations", [])
    if expected_sf:
        # Check if the report mentions these SF violations
        raw = actual.get("raw", "")
        matched_sf = []
        for sf in expected_sf:
            if sf in raw:
                matched_sf.append(sf)
        if matched_sf == expected_sf:
            checks.append(("anthropic_violations", "PASS", f"all SF violations detected: {expected_sf}"))
        else:
            missing_sf = set(expected_sf) - set(matched_sf)
            checks.append(("anthropic_violations", "FAIL", f"missing: {missing_sf}"))

    return checks


# ── Fixture Matching ────────────────────────────────────────────────────

def match_fixture_to_report(fixtures, report_path):
    """Find the fixture that best matches a given diagnosis report.

    Uses fixture_id in the report path or description to match.
    """
    report_dir = os.path.dirname(report_path)
    # Try to find fixture_id reference in the report
    with open(report_path) as f:
        content = f.read()

    for fixture in fixtures:
        fid = fixture["fixture_id"]
        # Check if fixture_id appears in report or path
        if fid in content or fid in report_path:
            return fixture
        # Also match by skill_path
        skill_path = fixture.get("skill_path", "")
        if skill_path and (skill_path in content or skill_path in report_path):
            return fixture

    return None


# ── Output ──────────────────────────────────────────────────────────────

def print_report(results):
    """Print structured comparison report."""
    total = len(results)
    passed = sum(1 for r in results if r["overall"] == "PASS")
    failed = sum(1 for r in results if r["overall"] == "FAIL")
    skipped = sum(1 for r in results if r["overall"] == "SKIP")

    print(f"\n{'='*70}")
    print(f"Diagnosis Accuracy Report")
    print(f"{'='*70}")
    print(f"  Total fixtures: {total}")
    print(f"  PASS: {passed}")
    print(f"  FAIL: {failed}")
    print(f"  SKIP (no report): {skipped}")
    print()

    for r in results:
        fid = r["fixture_id"]
        overall = r["overall"]
        icon = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}.get(overall, "???")
        print(f"  [{icon}] {fid}: {r['description']}")

        for check_name, check_result, detail in r.get("checks", []):
            c_icon = "PASS" if check_result == "PASS" else "FAIL"
            print(f"         [{c_icon}] {check_name}: {detail}")

        if r.get("report_path"):
            print(f"         report: {r['report_path']}")
        else:
            print(f"         report: (not found)")
        print()

    return passed, failed, skipped


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Diagnosis Accuracy Checker for Skill Optimization")
    parser.add_argument("--fixtures", required=True, help="Path to test-fixtures.yaml")
    parser.add_argument("--report", default=None, help="Single diagnosis report to check")
    parser.add_argument("--reports", default=None, help="Glob pattern for multiple reports")
    parser.add_argument("--fixture-id", default=None, help="Check only this fixture ID")
    parser.add_argument("--dry-run", action="store_true", help="List fixtures without checking")
    parser.add_argument("--output", default=None, help="Write report to file (JSON)")
    args = parser.parse_args()

    fixtures = load_fixtures(args.fixtures)
    if args.fixture_id:
        fixtures = [f for f in fixtures if f["fixture_id"] == args.fixture_id]

    if args.dry_run:
        print(f"Available fixtures ({len(fixtures)}):")
        for f in fixtures:
            print(f"  {f['fixture_id']}: {f.get('description', 'N/A')}")
            expected = f.get("expected", {})
            dims = expected.get("diagnosis", {})
            fail_dims = [k for k, v in dims.items() if (isinstance(v, str) and v == "FAIL") or (isinstance(v, dict) and v.get("status") == "FAIL")]
            if fail_dims:
                print(f"           FAIL dimensions: {fail_dims}")
            boundary = expected.get("boundary_decision", "")
            if boundary:
                print(f"           boundary: {boundary}")
            patterns = expected.get("selected_patterns_include", [])
            if patterns:
                print(f"           patterns: {patterns}")
        return 0

    # Collect report paths
    report_paths = []
    if args.report:
        report_paths = [args.report]
    elif args.reports:
        report_paths = sorted(glob.glob(args.reports))
    else:
        # Try to find reports under work/ directories (v0.18: optimize-skill 已并入 skill-foundry)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(args.fixtures)))
        report_paths = sorted(glob.glob(os.path.join(project_root, "work", "*", "skill-foundry", "phase1-diagnosis-report.md")))

    results = []

    for fixture in fixtures:
        fid = fixture["fixture_id"]
        description = fixture.get("description", "")

        if not report_paths:
            results.append({
                "fixture_id": fid,
                "description": description,
                "overall": "SKIP",
                "checks": [],
                "report_path": None,
            })
            continue

        # Try to match fixture to report
        report_path = None
        actual = None

        if args.fixture_id:
            # Single fixture mode: use provided report
            report_path = args.report
        else:
            # Multi-report mode: try to match
            for rp in report_paths:
                matched = match_fixture_to_report([fixture], rp)
                if matched:
                    report_path = rp
                    break

        if report_path and os.path.isfile(report_path):
            try:
                actual = parse_diagnosis_report(report_path)
            except Exception as e:
                results.append({
                    "fixture_id": fid,
                    "description": description,
                    "overall": "FAIL",
                    "checks": [("parse_error", "FAIL", str(e))],
                    "report_path": report_path,
                })
                continue
        else:
            results.append({
                "fixture_id": fid,
                "description": description,
                "overall": "SKIP",
                "checks": [],
                "report_path": report_path,
            })
            continue

        # Run comparison
        checks = compare_diagnosis(actual, fixture)
        overall = "PASS" if all(c[1] == "PASS" for c in checks) else "FAIL"

        results.append({
            "fixture_id": fid,
            "description": description,
            "overall": overall,
            "checks": checks,
            "report_path": report_path,
        })

    passed, failed, skipped = print_report(results)

    # Optional JSON output
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        import json
        with open(args.output, "w") as f:
            json.dump({"results": results, "summary": {"passed": passed, "failed": failed, "skipped": skipped}}, f, indent=2)
        print(f"JSON report written to {args.output}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
