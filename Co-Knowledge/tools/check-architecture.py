#!/usr/bin/env python3
"""Architecture guard for ``backend/src``.

The backend is organised as domain-first packages.  This script makes the
dependency rules executable instead of relying on review comments.

Usage::

    python3 tools/check-architecture.py                  # compare with baseline
    python3 tools/check-architecture.py --write-baseline # record current debt
    python3 tools/check-architecture.py --strict         # zero debt required

Exit codes: 0 = clean (or baseline-only debt), 1 = new violation, 2 = bad usage.

Violation identifiers are intentionally coarse (package-level, not file-level)
so the baseline stays readable and shrinks as the refactor progresses::

    cycle:engine,retrieval
    module-naming:doc_pipeline/config/LOGLEVEL.py
    stdlib-shadow:platform
    cross-domain-repository:knowledge_base->graph.repository
    forbidden-edge:engine->workflow
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

#: Target domain packages.  They may call each other's public service layer,
#: never another domain's ``repository`` package.
DOMAINS = frozenset({
    'knowledge_base', 'graph', 'operators', 'workflow', 'engine', 'chat',
    'model', 'retrieval', 'agent', 'ingestion', 'system', 'auth',
})

#: Packages that must never import a domain.
LEAF_PACKAGES = frozenset({'infrastructure', 'shared', 'parsing'})

#: Directed edges that are forbidden regardless of the repository rule.
FORBIDDEN_EDGES = {
    ('engine', 'workflow'),
    ('engine', 'chat'),
    ('graph', 'retrieval'),
    ('ingestion', 'knowledge_base'),
    ('ingestion', 'graph'),
}

#: Python module names are snake_case.  A handful of historical Java-style
#: names are recorded in the baseline and removed during the refactor.
MODULE_NAME_RE = re.compile(r'^[a-z][a-z0-9_]*\.py$')

BASELINE = Path(__file__).resolve().parent / 'architecture-baseline.json'


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def iter_python_files(src: Path):
    for path in sorted(src.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        yield path


def _relative_import(file_path: Path, src: Path, node: ast.ImportFrom):
    """Resolve ``from .foo import bar`` to a dotted module name."""
    if not node.level:
        return node.module or ''
    parts = list(file_path.relative_to(src).with_suffix('').parts[:-1])
    up = node.level - 1
    base = parts[:len(parts) - up] if up else parts
    if node.module:
        base = base + node.module.split('.')
    return '.'.join(base)


def imported_modules(file_path: Path, src: Path):
    """Yield ``(line, dotted_module)`` for every import in a file."""
    try:
        # Some historical parser files carry a UTF-8 BOM; utf-8-sig strips it.
        tree = ast.parse(file_path.read_text(encoding='utf-8-sig'), filename=str(file_path))
    except SyntaxError as exc:  # pragma: no cover - malformed files are a hard error
        raise SystemExit(f'cannot parse {file_path}: {exc}')
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = _relative_import(file_path, src, node)
            if module:
                yield node.lineno, module


def top_level(module: str) -> str:
    return module.split('.', 1)[0]


def package_dirs(src: Path) -> dict[str, Path]:
    return {
        child.name: child
        for child in sorted(src.iterdir())
        if child.is_dir() and child.name != '__pycache__' and not child.name.startswith('.')
    }


def module_files(src: Path) -> dict[str, Path]:
    return {
        path.stem: path
        for path in sorted(src.glob('*.py'))
    }


def detect_cycles(nodes: set[str], edges: set[tuple[str, str]]):
    """Tarjan SCC; return SCCs that contain a cycle."""
    graph: dict[str, set[str]] = defaultdict(set)
    for left, right in edges:
        graph[left].add(right)

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    result: list[list[str]] = []

    def strongconnect(node: str):
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in graph.get(node, ()):  # deterministic enough after sorting below
            if nxt not in indices:
                strongconnect(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], indices[nxt])
        if low[node] == indices[node]:
            component = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            # Package-level self-imports (``from agent_api import x`` inside
            # ``agent_api``) are normal; only multi-package SCCs are cycles.
            if len(component) > 1:
                result.append(sorted(component))

    for node in sorted(nodes):
        if node not in indices:
            strongconnect(node)
    return sorted(result)


def scan(src: Path):
    violations: dict[str, list[str]] = defaultdict(list)
    dirs = package_dirs(src)
    modules = module_files(src)
    internal = set(dirs) | set(modules)

    # Structural rules -----------------------------------------------------
    for name, path in dirs.items():
        # Ignore leftover directories that only contain stale __pycache__ files;
        # they are not part of a clean checkout.
        has_source = any(p for p in path.rglob('*.py') if '__pycache__' not in p.parts)
        if not has_source:
            continue
        if name in sys.stdlib_module_names:
            violations[f'stdlib-shadow:{name}'].append(str(path))
    for name, path in modules.items():
        if name in sys.stdlib_module_names:
            violations[f'stdlib-shadow:{name}'].append(str(path))

    for path in iter_python_files(src):
        if path.name == '__init__.py':
            continue
        rel = path.relative_to(src).as_posix()
        if not MODULE_NAME_RE.match(path.name):
            violations[f'module-naming:{rel}'].append(str(path))

    # Import rules ---------------------------------------------------------
    edges: set[tuple[str, str]] = set()
    for path in iter_python_files(src):
        rel = path.relative_to(src)
        importer = rel.parts[0] if len(rel.parts) > 1 else path.stem
        for line, module in imported_modules(path, src):
            imported_top = top_level(module)
            if imported_top not in internal:
                continue
            edges.add((importer, imported_top))

            if importer in DOMAINS and imported_top in DOMAINS and importer != imported_top:
                if module.startswith(f'{imported_top}.repository'):
                    key = f'cross-domain-repository:{importer}->{imported_top}.repository'
                    violations[key].append(f'{rel}:{line}')

            if importer in LEAF_PACKAGES and imported_top in DOMAINS:
                key = f'leaf-reverse-dependency:{importer}->{imported_top}'
                violations[key].append(f'{rel}:{line}')

            if (importer, imported_top) in FORBIDDEN_EDGES:
                key = f'forbidden-edge:{importer}->{imported_top}'
                violations[key].append(f'{rel}:{line}')

    for component in detect_cycles(internal, edges):
        key = 'cycle:' + ','.join(component)
        violations[key].append(' -> '.join(component))

    return dict(sorted(violations.items()))


def load_baseline() -> set[str]:
    if not BASELINE.exists():
        return set()
    data = json.loads(BASELINE.read_text(encoding='utf-8'))
    return set(data.get('violations', []))


def write_baseline(violations: dict[str, list[str]]) -> None:
    payload = {
        'comment': 'Historical architecture debt recorded before the rename. '
                   'This list must only shrink; run --write-baseline to refresh.',
        'violations': sorted(violations),
    }
    BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
                        encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--src', default=None, help='defaults to <repo>/backend/src')
    parser.add_argument('--write-baseline', action='store_true')
    parser.add_argument('--strict', action='store_true',
                        help='fail on any violation, ignoring the baseline')
    args = parser.parse_args()

    src = Path(args.src) if args.src else repo_root() / 'backend' / 'src'
    if not src.is_dir():
        print(f'check-architecture: no such directory: {src}', file=sys.stderr)
        return 2

    violations = scan(src)
    found = set(violations)

    if args.write_baseline:
        write_baseline(violations)
        print(f'check-architecture: wrote {len(found)} violation(s) to {BASELINE}')
        return 0

    baseline = set() if args.strict else load_baseline()
    new = sorted(found - baseline)
    resolved = sorted(baseline - found)

    for key in resolved:
        print(f'  resolved: {key}')
    for key in new:
        print(f'  NEW: {key}')
        for detail in violations[key][:5]:
            print(f'       {detail}')
        if len(violations[key]) > 5:
            print(f'       ... {len(violations[key]) - 5} more')

    if args.strict and found:
        print(f'check-architecture: FAILED — {len(found)} violation(s) (strict mode)')
        return 1
    if new:
        print(f'check-architecture: FAILED — {len(new)} new violation(s) '
              f'({len(found)} total, {len(resolved)} resolved)')
        return 1

    print(f'check-architecture: OK — {len(found)} known violation(s), '
          f'{len(resolved)} newly resolved')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
