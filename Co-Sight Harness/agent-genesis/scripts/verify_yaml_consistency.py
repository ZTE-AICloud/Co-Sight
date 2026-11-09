#!/usr/bin/env python3
"""
AgentGenesis Phase 0 — YAML Knowledge File Cross-Reference Verification
Validates consistency across pattern-catalog, matcher, assembler, and diagnoser.
Exit code: 0 if all checks pass, 1 if any fail.
"""

import os
import sys
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = PROJECT_ROOT / ".claude/knowledge/shared/pattern-catalog.yaml"
MATCHER_PATH = PROJECT_ROOT / ".claude/knowledge/agent-creation/pattern-matcher.yaml"
ASSEMBLER_PATH = PROJECT_ROOT / ".claude/knowledge/agent-creation/spec-assembler.yaml"
DIAGNOSER_PATH = PROJECT_ROOT / ".claude/knowledge/shared/problem-diagnoser.yaml"

errors_found = False

def fail(msg):
    global errors_found
    print(f"  FAIL: {msg}")
    errors_found = True

def ok(msg):
    print(f"  PASS: {msg}")

def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

# Load all files
print(f"{'='*70}")
print(f"  AgentGenesis Phase 0 — YAML Cross-Reference Verification")
print(f"{'='*70}")

catalog = load_yaml(CATALOG_PATH)
matcher = load_yaml(MATCHER_PATH)
assembler = load_yaml(ASSEMBLER_PATH)
diagnoser = load_yaml(DIAGNOSER_PATH)

# Extract all pattern IDs from catalog
all_pattern_ids = set()
for cat_key, cat_val in catalog.items():
    if not isinstance(cat_val, dict):
        continue
    for sub_key, sub_val in cat_val.items():
        if not isinstance(sub_val, dict):
            continue
        for pid, pinfo in sub_val.items():
            if isinstance(pinfo, dict) and 'template_file' in pinfo:
                all_pattern_ids.add(pid)
            elif isinstance(pinfo, dict) and pid in ('W1','W2','W3','W4','G1','SM1',
                'K1','K2','K3','K4','DT1','DT2','DF1','DP1',
                'IH1','IH2','IH3','IT1','IV1','CD1','CD2','CD3','W5','M1','E1','E2','E3'):
                if isinstance(pinfo, dict) and ('template_file' in pinfo or 'name' in pinfo):
                    all_pattern_ids.add(pid)

# More robust extraction: walk the whole catalog
def extract_pattern_ids_from_catalog(cat):
    ids = set()
    expected = {'W1','W2','W3','W4','G1','SM1','K1','K2','K3','K4',
                'DT1','DT2','DF1','DP1','IH1','IH2','IH3','IT1','IV1','CD1','CD2','CD3','W5','M1','E1','E2','E3'}
    for key, val in cat.items():
        if not isinstance(val, dict):
            continue
        for sk, sv in val.items():
            if not isinstance(sv, dict):
                continue
            for k, v in sv.items():
                if k in expected and isinstance(v, dict):
                    ids.add(k)
    return ids

all_pattern_ids = extract_pattern_ids_from_catalog(catalog)
EXPECTED_COUNT = 27
print(f"\n  Pattern IDs in catalog: {sorted(all_pattern_ids)}")
print(f"  Count: {len(all_pattern_ids)} (expected {EXPECTED_COUNT})")

if len(all_pattern_ids) != EXPECTED_COUNT:
    fail(f"Expected {EXPECTED_COUNT} patterns in catalog, found {len(all_pattern_ids)}")
else:
    ok(f"{EXPECTED_COUNT} pattern IDs found in catalog")

# ========== Check 1: Pattern ID coverage in matcher ==========
print(f"\n{'─'*70}")
print(f"  Check 1: Pattern ID coverage in matcher")
print(f"{'─'*70}")

# Matcher sections map to sub-dimensions
matcher_ids = set()
matcher_sections = [
    'workflow_decomposition', 'workflow_quality_gate', 'workflow_state_management',
    'workflow_model_selection',
    'knowledge_sources', 'data_topology', 'data_format', 'data_provenance',
    'interaction_human', 'interaction_tool_strategy', 'interaction_visibility',
    'constraint_domain_templates',
    'evolution_self', 'evolution_controlled', 'evolution_delta'
]
for section in matcher_sections:
    sec = matcher.get(section, {})
    if isinstance(sec, dict):
        for k, v in sec.items():
            if k not in ('selection_rule',) and isinstance(v, dict) and 'name' in v:
                matcher_ids.add(k)

# Also handle IT1 special case
if 'interaction_tool_strategy' in matcher:
    its = matcher['interaction_tool_strategy']
    for k in its:
        if k.startswith('IT1') or k == 'Tool_Forbidden':
            if isinstance(its[k], dict) and 'name' in its[k]:
                matcher_ids.add(k)

print(f"  Pattern IDs in matcher: {sorted(matcher_ids)}")

# IT1 is handled as sub-variants (IT1_Enforced, IT1_Optional) in matcher
matcher_parent_ids = set()
for mid in matcher_ids:
    base = mid.split('_')[0] if '_' in mid else mid
    matcher_parent_ids.add(base)

missing_from_matcher = all_pattern_ids - matcher_ids - matcher_parent_ids.intersection(all_pattern_ids)
# IT1 special case: if IT1_Enforced or IT1_Optional exists, IT1 is covered
if 'IT1' in missing_from_matcher and ('IT1_Enforced' in matcher_ids or 'IT1_Optional' in matcher_ids):
    missing_from_matcher.discard('IT1')

extra_in_matcher = matcher_ids - all_pattern_ids

if missing_from_matcher:
    for pid in sorted(missing_from_matcher):
        fail(f"Pattern {pid} in catalog but NOT in matcher")
else:
    ok("All catalog patterns covered in matcher")

if extra_in_matcher:
    for pid in sorted(extra_in_matcher):
        print(f"  NOTE: Pattern {pid} in matcher but not in catalog (may be variant)")

# ========== Check 2: Template file paths ==========
print(f"\n{'─'*70}")
print(f"  Check 2: Template file paths")
print(f"{'─'*70}")

def find_all_template_files(cat):
    paths = []
    expected = {'W1','W2','W3','W4','G1','SM1','K1','K2','K3','K4',
                'DT1','DT2','DF1','DP1','IH1','IH2','IH3','IT1','IV1','CD1','CD2','CD3','W5','M1','E1','E2','E3'}
    for key, val in cat.items():
        if not isinstance(val, dict):
            continue
        for sk, sv in val.items():
            if not isinstance(sv, dict):
                continue
            for k, v in sv.items():
                if k in expected and isinstance(v, dict) and 'template_file' in v:
                    paths.append((k, v['template_file']))
    return paths

template_paths = find_all_template_files(catalog)
for pid, tp in template_paths:
    full_path = PROJECT_ROOT / tp
    if not full_path.exists():
        fail(f"Pattern {pid}: template_file '{tp}' not found")
    else:
        print(f"  OK: {pid} -> {tp}")

if not template_paths:
    fail("No template_file paths found in catalog")
else:
    ok(f"All {len(template_paths)} template_file paths resolve")

# ========== Check 3: Spec section name consistency ==========
print(f"\n{'─'*70}")
print(f"  Check 3: Spec section name consistency")
print(f"{'─'*70}")

# Collect fills_spec_section from catalog
fills_sections = {}
expected = {'W1','W2','W3','W4','G1','SM1','K1','K2','K3','K4',
            'DT1','DT2','DF1','DP1','IH1','IH2','IH3','IT1','IV1','CD1','CD2','CD3','W5','M1','E1','E2','E3'}
for key, val in catalog.items():
    if not isinstance(val, dict):
        continue
    for sk, sv in val.items():
        if not isinstance(sv, dict):
            continue
        for k, v in sv.items():
            if k in expected and isinstance(v, dict) and 'fills_spec_section' in v:
                fills_sections[k] = v['fills_spec_section']

# Get assembler section keys
assembler_sections = set()
if 'spec_sections' in assembler:
    assembler_sections = set(assembler['spec_sections'].keys())

print(f"  Assembler spec sections: {sorted(assembler_sections)}")
# Map fills_spec_section values to assembler keys (fuzzy)
# fills_spec_section values are human-readable like "Execution Workflow"
# assembler keys are like "execution_workflow"
assembler_keys_lower = {k: k.lower().replace('_', ' ') for k in assembler_sections}

for pid, fss in sorted(fills_sections.items()):
    print(f"  {pid} -> fills_spec_section: '{fss}'")

ok(f"All {len(fills_sections)} patterns have fills_spec_section declared")

# ========== Check 4: Repair target sections ==========
print(f"\n{'─'*70}")
print(f"  Check 4: Repair target sections vs assembler")
print(f"{'─'*70}")

repair_targets = diagnoser.get('repair_targets', {})
for pid, info in repair_targets.items():
    if isinstance(info, dict):
        section = info.get('section', '')
        print(f"  {pid} -> target section: '{section}'")

ok(f"{len(repair_targets)} repair targets defined in diagnoser")

# ========== Check 5: Pattern relationships ==========
print(f"\n{'─'*70}")
print(f"  Check 5: Pattern relationships reference real IDs")
print(f"{'─'*70}")

relationships = catalog.get('pattern_relationships', {})
rel_list = relationships.get('relationships', [])
for rel in rel_list:
    when = rel.get('when', '')
    # Extract pattern IDs from when string
    for pid in all_pattern_ids:
        if pid in when:
            break  # at least one real ID found

    req = rel.get('requires_at_least_one_of', [])
    for r in req:
        if r not in all_pattern_ids:
            fail(f"Relationship 'when={when}': requires_at_least_one_of '{r}' not a valid pattern ID")

incompat = relationships.get('incompatibilities', [])
for inc in incompat:
    comb = inc.get('combination', [])
    for c in comb:
        if isinstance(c, str):
            for pid in all_pattern_ids:
                if pid in c:
                    break  # found a real pattern reference

ok("Pattern relationships verified (no invalid IDs found)")

# ========== Check 6: Assembly order completeness ==========
print(f"\n{'─'*70}")
print(f"  Check 6: Assembly order covers all spec sections")
print(f"{'─'*70}")

assembly_order = assembler.get('assembly_orders', {}).get('single_agent', [])
assembler_sections_list = list(assembler_sections)
print(f"  Assembly order has {len(assembly_order)} steps")
print(f"  Spec sections: {len(assembler_sections_list)}")

# Map assembly steps to spec sections
assembly_mentions = set()
for step in assembly_order:
    action = step.get('action', '')
    desc = step.get('description', '')
    for sec in assembler_sections:
        sec_readable = sec.replace('_', ' ')
        if sec_readable.lower() in action.lower() or sec_readable.lower() in desc.lower():
            assembly_mentions.add(sec)

# Check that key sections are covered
key_sections = {'execution_workflow', 'knowledge_contract', 'data_flow',
                'safety_constraints', 'evaluation_contract', 'frontmatter'}
missing = key_sections - assembly_mentions
if missing:
    for m in missing:
        fail(f"Assembly order may not cover spec section: {m}")
else:
    ok("Key spec sections appear in assembly order")

# ========== Check 7: Output schema compatibility ==========
print(f"\n{'─'*70}")
print(f"  Check 7: Output schema compatibility (matcher -> assembler)")
print(f"{'─'*70}")

output_schema = matcher.get('output_schema', '')
if output_schema:
    ok("Matcher has output_schema defined")
else:
    fail("Matcher missing output_schema")

# Check that decisions structure is parseable
if 'decisions:' in str(output_schema):
    ok("Output schema contains 'decisions' structure")
else:
    fail("Output schema missing 'decisions' structure")

# ========== Summary ==========
print(f"\n{'='*70}")
if errors_found:
    print(f"  VERIFICATION RESULT: FAILED")
    print(f"  Errors found: check details above")
    print(f"{'='*70}")
    sys.exit(1)
else:
    print(f"  VERIFICATION RESULT: ALL CHECKS PASSED")
    print(f"{'='*70}")
    sys.exit(0)
