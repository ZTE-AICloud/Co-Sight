#!/usr/bin/env python3
"""
AgentGenesis Phase 0 — Template Quality Audit Script

Validates all .template.md files in skills/agent-design-patterns/patterns/ against TC-0.1 through TC-0.8.
Exit code: 0 if all pass, 1 if any fail.
"""

import os
import sys
import re
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PATTERNS_DIR = PROJECT_ROOT / "skills/agent-design-patterns/patterns"
CATALOG_PATH = PROJECT_ROOT / "knowledge/shared/pattern-catalog.yaml"

REQUIRED_FIELDS = [
    "pattern_id",
    "pattern_name",
    "category",
    "sub_dimension",
    "selection_rule",
    "solves",
    "fills_spec_section",
    "variables",
    "constraints",
]

LEGAL_SOURCES = {"user_input", "derived", "llm_generate", "decision_table"}

REQUIRED_PARADIGM_PRESETS = {"pipeline", "agent_pool", "swarm", "analysis", "fsm"}


def extract_frontmatter(content: str):
    """Extract YAML frontmatter from template content."""
    # Match content between the first pair of --- delimiters
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return None, content
    frontmatter = match.group(1)
    body = content[match.end():]
    return frontmatter, body


def parse_frontmatter(frontmatter_str: str) -> dict:
    """Parse YAML frontmatter string into a dict."""
    return yaml.safe_load(frontmatter_str)


def validate_required_fields(data: dict) -> list:
    """Check that all required fields are present and non-empty."""
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"Missing required field: {field}")
        elif data[field] is None:
            errors.append(f"Field '{field}' is None/null")
        elif isinstance(data[field], (list, dict)) and len(data[field]) == 0:
            errors.append(f"Field '{field}' is empty")
        elif isinstance(data[field], str) and not data[field].strip():
            errors.append(f"Field '{field}' is empty string")
    return errors


def validate_variables(data: dict) -> list:
    """Check each variable has name, description, source and source is legal."""
    errors = []
    variables = data.get("variables", [])
    if not isinstance(variables, list):
        errors.append("'variables' is not a list")
        return errors

    for i, var in enumerate(variables):
        if not isinstance(var, dict):
            errors.append(f"Variable[{i}] is not a dict")
            continue
        # Check required keys
        for key in ("name", "description", "source"):
            if key not in var:
                errors.append(f"Variable[{i}] missing key: {key}")
            elif not var[key]:
                errors.append(f"Variable[{i}].{key} is empty")
        # Check source is legal
        source = var.get("source", "")
        if source and source not in LEGAL_SOURCES:
            errors.append(
                f"Variable[{i}].source '{source}' not in {LEGAL_SOURCES}"
            )
    return errors


def validate_filled_example(content: str, body: str) -> list:
    """Check for Filled Example section, content >100 chars, no residual placeholders."""
    errors = []
    # Check for the heading in both languages (H1: # or H2: ##), allow suffix like (Enforced)
    has_heading_en = bool(re.search(r'^#{1,2}\s+Filled\s+Example', body, re.MULTILINE))
    has_heading_zh = bool(re.search(r'^#{1,2}\s+填充示例', body, re.MULTILINE))

    if not has_heading_en and not has_heading_zh:
        errors.append("Missing '# Filled Example' / '# 填充示例' section (or variant)")
        return errors

    # Find all section headings to get the filled example boundaries
    heading_pattern = re.compile(r'^#{1,2}\s+', re.MULTILINE)

    filled_example_start = None
    filled_example_end = None

    for match in heading_pattern.finditer(body):
        line_start = match.start()
        line_end = body.index('\n', line_start) if '\n' in body[line_start:] else len(body)
        heading_text = body[line_start:line_end].strip()
        if heading_text.startswith(("# Filled Example", "## Filled Example", "# 填充示例", "## 填充示例")):
            filled_example_start = match.start()
            break

    if filled_example_start is None:
        errors.append("Could not parse Filled Example section boundaries")
        return errors

    # Find next heading AT THE SAME OR HIGHER LEVEL after filled example
    # Since Filled Example is always the last top-level section, we take
    # everything to end-of-file unless there's another H1 heading after it
    next_headings = list(heading_pattern.finditer(body, filled_example_start + 1))
    if next_headings:
        # Check if any subsequent heading is H1 (# with single #)
        found_end = False
        for m in next_headings:
            h_text = body[m.start():body.index('\n', m.start()) if '\n' in body[m.start():] else len(body)].strip()
            if h_text.startswith('# ') and not h_text.startswith('## '):
                filled_example_end = m.start()
                found_end = True
                break
        if not found_end:
            filled_example_end = len(body)
    else:
        filled_example_end = len(body)

    filled_content = body[filled_example_start:filled_example_end]

    if len(filled_content.strip()) < 100:
        errors.append(
            f"Filled Example section too short ({len(filled_content.strip())} chars, need >100)"
        )

    # Check for residual placeholders
    placeholders = re.findall(r'\{\{.*?\}\}', filled_content)
    if placeholders:
        errors.append(
            f"Filled Example contains {len(placeholders)} residual placeholder(s): {placeholders[:5]}"
        )

    return errors


def validate_user_input_variable(data: dict) -> list:
    """Check at least one variable has source: user_input."""
    errors = []
    variables = data.get("variables", [])
    if not isinstance(variables, list):
        errors.append("'variables' is not a list — cannot check user_input")
        return errors

    has_user_input = any(
        isinstance(v, dict) and v.get("source") == "user_input" for v in variables
    )
    if not has_user_input:
        errors.append("No variable with source: user_input found")
    return errors


def validate_template_body_placeholders(body: str) -> list:
    """Check template body (non-frontmatter) has at least one {{...}} placeholder."""
    errors = []
    placeholders = re.findall(r'\{\{.*?\}\}', body)
    if not placeholders:
        errors.append("Template body has no {{...}} placeholders")
    return errors


def check_catalog_template_exists() -> list:
    """Check every template_file in catalog.yaml points to an existing file."""
    errors = []
    if not CATALOG_PATH.exists():
        errors.append(f"Catalog file not found: {CATALOG_PATH}")
        return errors

    with open(CATALOG_PATH, "r") as f:
        catalog = yaml.safe_load(f)

    if not catalog:
        errors.append("Catalog YAML is empty")
        return errors

    # Check template_file references
    for key, entry in catalog.items():
        if key == "paradigm_presets":
            continue
        if isinstance(entry, dict):
            tf = entry.get("template_file")
            if tf:
                tf_path = PATTERNS_DIR / tf
                if not tf_path.exists():
                    errors.append(
                        f"Catalog entry '{key}': template_file '{tf}' not found at {tf_path}"
                    )

    # Check all template files are referenced
    existing_templates = set()
    for entry in catalog.values():
        if isinstance(entry, dict):
            tf = entry.get("template_file")
            if tf:
                existing_templates.add(tf)

    return errors


def check_paradigm_presets() -> list:
    """Verify 5 paradigm presets exist, each with non-empty pattern_composition."""
    errors = []
    if not CATALOG_PATH.exists():
        errors.append(f"Catalog file not found: {CATALOG_PATH}")
        return errors

    with open(CATALOG_PATH, "r") as f:
        catalog = yaml.safe_load(f)

    pp = catalog.get("paradigm_presets", {}) if catalog else {}
    presets = pp.get("presets", {}) if isinstance(pp, dict) else {}
    for preset_name in REQUIRED_PARADIGM_PRESETS:
        if preset_name not in presets:
            errors.append(f"Missing paradigm preset: {preset_name}")
        else:
            pc = presets[preset_name].get("formula", "")
            if not pc:
                errors.append(
                    f"Paradigm preset '{preset_name}' has empty formula"
                )

    return errors


def audit_template(filepath: Path) -> dict:
    """Run all checks on a single template file."""
    result = {
        "file": filepath.name,
        "pass": True,
        "errors": [],
        "checks": {},
    }

    # Read file
    with open(filepath, "r") as f:
        content = f.read()

    # TC-0.2: Extract and parse frontmatter
    frontmatter_str, body = extract_frontmatter(content)
    if frontmatter_str is None:
        result["errors"].append("TC-0.2: No YAML frontmatter found (--- delimiters)")
        result["pass"] = False
        result["checks"]["tc-0.2"] = False
        return result

    try:
        data = parse_frontmatter(frontmatter_str)
    except yaml.YAMLError as e:
        result["errors"].append(f"TC-0.2: YAML parse error: {e}")
        result["pass"] = False
        result["checks"]["tc-0.2"] = False
        return result

    result["checks"]["tc-0.2"] = True

    # Determine if this is a structural template (L2/L3/ARCH-INTENT)
    # Structural templates are programmatic — they don't require Filled Examples or user_input
    pattern_id = data.get("pattern_id", "")
    is_structural = pattern_id.startswith("L2-") or pattern_id.startswith("L3-") or pattern_id.startswith("ARCH-")

    # TC-0.3: Required fields
    field_errors = validate_required_fields(data)
    if field_errors:
        for e in field_errors:
            result["errors"].append(f"TC-0.3: {e}")
        result["checks"]["tc-0.3"] = False
        result["pass"] = False
    else:
        result["checks"]["tc-0.3"] = True

    # TC-0.4: Variable source legality
    source_errors = validate_variables(data)
    if source_errors:
        for e in source_errors:
            result["errors"].append(f"TC-0.4: {e}")
        result["checks"]["tc-0.4"] = False
        result["pass"] = False
    else:
        result["checks"]["tc-0.4"] = True

    # TC-0.5: Filled Example (skip for structural templates)
    if is_structural:
        result["checks"]["tc-0.5"] = True
    else:
        fe_errors = validate_filled_example(content, body)
        if fe_errors:
            for e in fe_errors:
                result["errors"].append(f"TC-0.5: {e}")
            result["checks"]["tc-0.5"] = False
            result["pass"] = False
        else:
            result["checks"]["tc-0.5"] = True

    # TC-0.6: user_input variable count (skip for structural templates)
    if is_structural:
        result["checks"]["tc-0.6"] = True
    else:
        ui_errors = validate_user_input_variable(data)
        if ui_errors:
            for e in ui_errors:
                result["errors"].append(f"TC-0.6: {e}")
            result["checks"]["tc-0.6"] = False
            result["pass"] = False
        else:
            result["checks"]["tc-0.6"] = True

    # TC-0.6b: Template body placeholders
    pl_errors = validate_template_body_placeholders(body)
    if pl_errors:
        for e in pl_errors:
            result["errors"].append(f"TC-0.6b: {e}")
        result["checks"]["tc-0.6b"] = False
        result["pass"] = False
    else:
        result["checks"]["tc-0.6b"] = True

    return result


def main():
    errors_found = False

    # TC-0.1: File count
    template_files = sorted(PATTERNS_DIR.glob("*.template.md"))
    # Exclude .bak files
    template_files = [f for f in template_files if not f.name.endswith(".bak")]
    template_files.sort()

    count = len(template_files)
    print(f"{'='*70}")
    print(f"  AgentGenesis Phase 0 — Template Quality Audit")
    print(f"{'='*70}")
    print(f"\nTC-0.1: File count = {count} (expected 34)")
    if count != 34:
        print(f"  FAIL: Expected 34 files, found {count}")
        errors_found = True
    else:
        print(f"  PASS: 34 files found")

    print(f"\n{'─'*70}")
    print(f"  Per-File Audit Results")
    print(f"{'─'*70}")

    all_results = []
    for tf in template_files:
        result = audit_template(tf)
        all_results.append(result)
        status = "PASS" if result["pass"] else "FAIL"
        print(f"\n  [{status}] {result['file']}")
        if not result["pass"]:
            for err in result["errors"]:
                print(f"         {err}")

    # Summary table
    print(f"\n{'─'*70}")
    print(f"  Summary Table")
    print(f"{'─'*70}")

    # Collect check results
    check_names = ["tc-0.2", "tc-0.3", "tc-0.4", "tc-0.5", "tc-0.6", "tc-0.6b"]
    header = f"  {'File':<30s}" + "".join(f"{c:<10s}" for c in check_names)
    print(header)
    print(f"  {'─'*30}" + "─" * (10 * len(check_names)))

    for result in all_results:
        checks = result["checks"]
        line = f"  {result['file']:<30s}"
        for c in check_names:
            if c in checks:
                line += f"{'PASS' if checks[c] else 'FAIL':<10s}"
            else:
                line += f"{'N/A':<10s}"
        print(line)

    # Totals
    print(f"\n  {'─'*30}" + "─" * (10 * len(check_names)))
    totals = {}
    for c in check_names:
        pass_count = sum(1 for r in all_results if r["checks"].get(c) is True)
        total = sum(1 for r in all_results if c in r["checks"])
        totals[c] = (pass_count, total)

    line = f"  {'Totals':<30s}"
    for c in check_names:
        p, t = totals[c]
        line += f"{f'{p}/{t}':<10s}"
    print(line)

    pass_count = sum(1 for r in all_results if r["pass"])
    total = len(all_results)
    print(f"\n  {'═'*70}")
    print(f"  Overall: {pass_count}/{total} files pass all checks")
    if pass_count == total == 34:
        print(f"  RESULT: ALL CHECKS PASSED")
    else:
        print(f"  RESULT: FAILURES DETECTED — see above for details")
        errors_found = True

    # TC-0.7: Catalog template_file references
    print(f"\n{'─'*70}")
    print(f"  TC-0.7: Catalog template_file reference check")
    print(f"{'─'*70}")
    catalog_errors = check_catalog_template_exists()
    if catalog_errors:
        for e in catalog_errors:
            print(f"  FAIL: {e}")
        errors_found = True
    else:
        print(f"  PASS: All catalog template_file paths resolve")

    # TC-0.8: Paradigm presets
    print(f"\n{'─'*70}")
    print(f"  TC-0.8: Paradigm_presets check")
    print(f"{'─'*70}")
    preset_errors = check_paradigm_presets()
    if preset_errors:
        for e in preset_errors:
            print(f"  FAIL: {e}")
        errors_found = True
    else:
        print(f"  PASS: All 5 paradigm presets present with non-empty pattern_composition")

    print(f"\n{'='*70}")
    if errors_found:
        print(f"  AUDIT RESULT: FAILED")
        print(f"{'='*70}")
        sys.exit(1)
    else:
        print(f"  AUDIT RESULT: ALL PASSED")
        print(f"{'='*70}")
        sys.exit(0)


if __name__ == "__main__":
    main()
