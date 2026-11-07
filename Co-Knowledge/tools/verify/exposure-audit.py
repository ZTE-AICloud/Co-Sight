#!/usr/bin/env python3
"""入口暴露审计（exposure audit）：找出「实现了但没有对外暴露」的地方。

## 为什么有这个脚本

常见问题：页面、路由、REST、单测都在，唯独没有任何菜单或跳转能到达它 ——
用户根本看不到。同类问题还有三类：

1. **可达性**：前端文件/路由没人引用；后端端点没有前端、e2e 或文档消费方；
2. **假绿**：单测挂的是用户永远看不到的组件（测了，但测的是死代码）；
3. **无声隐藏**：模板注释里的交互块、`v-if="false"`、占位实现。

本脚本把这些变成可重复执行的**清单**，并由 `--check` 在 CI 里挡住新增。

## 五层判据

=================================  ==========================================
层                                 判据
=================================  ==========================================
L1 入口可达性                      路由必须在菜单/跳转里；端点必须有消费方
L2 代码可达性                      从 main.js/router.js 做传递闭包
L3 契约一致性                      （本版只输出分类数据，不设门禁）
L4 注释 / 开关 / 占位              注释里的 `<el-*>`、`v-if="false"`、TODO
L5 测试有效性                      测不可达文件的 spec 视为假绿
=================================  ==========================================

## 跑法

    python3 tools/verify/exposure-audit.py                 # 生成 .audit/ 下的 JSON + Markdown
    python3 tools/verify/exposure-audit.py --check         # CI：有未豁免错误即退出 1
    python3 tools/verify/exposure-audit.py --check --strict # 警告也失败
    python3 tools/verify/exposure-audit.py --write-allowlist --force  # 首次基线
    python3 tools/verify/exposure-audit.py --no-backend    # 不导入 FastAPI 应用

退出码：0 = 通过；1 = 有未豁免/过期项；2 = 用法或环境错误。

## 已知局限（写在明处，别把绿当成全对）

* 前端可达性靠**静态** import 图：运行时字符串拼出来的路径会漏；动态模板
  ``require(`.../${x}/Drawer`)`` 已按 glob 展开，但更花哨的写法仍需白名单兜底。
* 后端「消费方」是**文本匹配**：路径常量间接拼 URL 时按最后静态段判定，宁可
  少报（漏报）也不误报；真正的接线请以 L3 矩阵为准（后续版本）。
* 注释扫描只认**交互标签/调用**，纯说明性注释不当问题。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO / 'frontend' / 'src'
FRONTEND_TESTS = REPO / 'frontend' / 'tests'
BACKEND_SRC = REPO / 'backend' / 'src'
E2E_DIR = REPO / 'e2e'
DOCS_DIR = REPO / 'docs'
CONTRACTS_DIR = REPO / 'contracts'
ALLOWLIST = Path(__file__).with_name('exposure-allowlist.txt')
DEFAULT_MD = REPO / '.audit' / 'exposure-audit.md'
DEFAULT_JSON = REPO / '.audit' / 'exposure-audit.json'
RKB_PREFIX = '/api/co-knowledge/v1'

FRONTEND_ENTRIES = ('app/main.js', 'app/router.js')

#: 视为「错误」的 finding（--check 会让 CI 失败）。
ERROR_KINDS = {
    'unreachable-file',
    'orphan-route',
    'unreachable-endpoint',
    'spec-of-unreachable',
    'stale-waiver',
    'backend-import-failed',
}

#: 视为「警告」的 finding（--strict 才失败）。
WARN_KINDS = {'commented-code', 'disabled-ui', 'unused-waiver', 'unused-api-wrapper'}
INFO_KINDS = {'todo-marker'}

SEVERITY = {
    **{kind: 'error' for kind in ERROR_KINDS},
    **{kind: 'warning' for kind in WARN_KINDS},
    **{kind: 'info' for kind in INFO_KINDS},
}


# ----------------------------------------------------------------------
# 数据结构
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    kind: str
    key: str
    message: str
    file: str = ''
    line: int = 0

    @property
    def severity(self) -> str:
        return SEVERITY.get(self.kind, 'warning')

    def sort_key(self) -> tuple:
        return (self.kind, self.key)


@dataclass
class Waiver:
    kind: str
    key: str
    reason: str
    review_by: date | None
    line: int


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)


# ----------------------------------------------------------------------
# 通用工具
# ----------------------------------------------------------------------


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return ''


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def collect_files(root: Path, suffixes: set[str]) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob('*')
                  if p.is_file() and p.suffix in suffixes
                  and 'node_modules' not in p.parts and '__pycache__' not in p.parts)


def line_of(text: str, offset: int) -> int:
    return text.count('\n', 0, offset) + 1


# ----------------------------------------------------------------------
# L2 前端代码可达性
# ----------------------------------------------------------------------

_IMPORT_RE = re.compile(
    r"""(?:from\s+|import\s+|import\s*\(\s*(?:/\*.*?\*/\s*)?|require\(\s*)"""
    r"""['"]([^'"]+)['"]""",
    re.S,
)
#: 模板拼接的动态引用：``require(`../../modules/${x}/Drawer`)``。
_DYNAMIC_RE = re.compile(r"""(?:require|import)\s*\(\s*`([^`]+)`\s*\)""")
_TAG_RE = re.compile(r'<([A-Za-z][A-Za-z0-9-]*)[\s/>]')


def extract_import_specifiers(text: str) -> list[str]:
    return [m.group(1) for m in _IMPORT_RE.finditer(text)]


def resolve_import(spec: str, source: Path, known: set[Path]) -> Path | None:
    """把 import 说明符解析成仓库内文件；解析不到返回 None。"""
    if spec.startswith('@/'):
        base = (FRONTEND_SRC / spec[2:]).resolve()
    elif spec.startswith('.'):
        base = (source.parent / spec).resolve()
    else:
        return None
    candidates = [base]
    candidates += [base.parent / (base.name + suffix) for suffix in ('.js', '.ts', '.vue')]
    candidates += [base / 'index.js', base / 'index.ts']
    try:
        candidates += [base.with_suffix(suffix) for suffix in ('.js', '.ts', '.vue')]
    except ValueError:
        pass
    for candidate in candidates:
        if candidate in known:
            return candidate
    return None


def expand_dynamic_import(spec: str, source: Path, known: set[Path]) -> set[Path]:
    """把 ``.../${x}/...`` 展开成所有匹配文件（只展开仓库内相对/别名路径）。"""
    if '${' not in spec:
        return set()
    if spec.startswith('@/'):
        base = FRONTEND_SRC / spec[2:]
    elif spec.startswith('.'):
        base = (source.parent / spec).resolve()
    else:
        return set()
    pattern = re.sub(r'\$\{[^}]*\}', '*', rel(base))
    if '*' not in pattern:
        return set()
    matches: set[Path] = set()
    for candidate in (pattern, f'{pattern}.*'):
        try:
            matches |= {p.resolve() for p in REPO.glob(candidate) if p.is_file()}
        except (ValueError, NotImplementedError):
            continue
    return {p for p in matches if p in known}


def build_frontend_graph(files: list[Path], texts: dict[Path, str]) -> dict[Path, set[Path]]:
    known = set(files)
    by_tag = {p.stem.lower().replace('-', ''): p for p in files if p.suffix == '.vue'}
    edges: dict[Path, set[Path]] = defaultdict(set)
    for path in files:
        text = texts[path]
        for spec in extract_import_specifiers(text):
            target = resolve_import(spec, path, known)
            if target is not None:
                edges[path].add(target)
        for spec in _DYNAMIC_RE.findall(text):
            edges[path] |= expand_dynamic_import(spec, path, known)
        for tag in _TAG_RE.findall(text):
            target = by_tag.get(tag.lower().replace('-', ''))
            if target is not None and target != path:
                edges[path].add(target)
    return edges


def reachable_files(edges: dict[Path, set[Path]], entries: Iterable[Path]) -> set[Path]:
    seen = {e for e in entries if e.exists()}
    queue = deque(seen)
    while queue:
        current = queue.popleft()
        for nxt in edges.get(current, ()):  # type: ignore[arg-type]
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def audit_unreachable_files(result: AuditResult) -> set[Path]:
    files = collect_files(FRONTEND_SRC, {'.js', '.ts', '.vue'})
    texts = {p: read_text(p) for p in files}
    edges = build_frontend_graph(files, texts)
    entries = [FRONTEND_SRC / name for name in FRONTEND_ENTRIES]
    reachable = reachable_files(edges, entries)
    unreachable = {p for p in files if p not in reachable and not p.name.endswith('.d.ts')}

    specs = collect_files(FRONTEND_TESTS, {'.js', '.ts'})
    spec_texts = {p: read_text(p) for p in specs}
    for path in sorted(unreachable):
        loc = len(texts[path].splitlines())
        result.add(Finding(
            'unreachable-file', rel(path),
            f'从入口不可达（{loc} 行）；无任何文件 import/渲染它', file=rel(path)))
        src_rel = path.relative_to(FRONTEND_SRC).as_posix()
        stem_path = src_rel.rsplit('.', 1)[0]
        markers = (f'@/{src_rel}', f'@/{stem_path}', f'/{src_rel}')
        for spec, spec_text in spec_texts.items():
            if any(marker in spec_text for marker in markers):
                result.add(Finding(
                    'spec-of-unreachable', f'{rel(spec)} -> {rel(path)}',
                    '测试覆盖的是不可达代码（假绿）',
                    file=rel(spec)))
    result.stats['frontend_files'] = len(files)
    result.stats['frontend_unreachable'] = len(unreachable)
    return unreachable


# ----------------------------------------------------------------------
# L1 前端路由可达性
# ----------------------------------------------------------------------

_ROUTE_PATH_RE = re.compile(r"path:\s*'([^']+)'")
_ROUTE_NAME_RE = re.compile(r"name:\s*'([^']+)'")


@dataclass(frozen=True)
class FrontendRoute:
    path: str
    name: str
    line: int
    is_redirect: bool


def parse_frontend_routes(router_text: str) -> list[FrontendRoute]:
    routes: list[FrontendRoute] = []
    last_absolute = ''
    for match in _ROUTE_PATH_RE.finditer(router_text):
        path = match.group(1)
        tail = router_text[match.end():match.end() + 240]
        name_match = _ROUTE_NAME_RE.search(tail)
        name = name_match.group(1) if name_match else ''
        if path.startswith('/'):
            last_absolute = path
        else:
            path = (last_absolute.rstrip('/') + '/' + path).replace('//', '/')
        routes.append(FrontendRoute(
            path=path,
            name=name,
            line=line_of(router_text, match.start()),
            is_redirect='redirect:' in tail[:120],
        ))
    return routes


def _path_regex(path: str) -> re.Pattern[str]:
    parts = re.split(r'(/[:\w-]*:[\w]+|:\w+)', path)
    pattern = ''
    for part in parts:
        if not part:
            continue
        if part.startswith(':') or ': ' in part:
            pattern += r'[^/`"\'\s]+'
        elif re.search(r':\w+', part):
            pattern += re.escape(re.sub(r':\w+', '', part)) + r'[^/`"\'\s]+'
        else:
            pattern += re.escape(part)
    return re.compile(pattern)


def audit_frontend_routes(result: AuditResult) -> None:
    router = FRONTEND_SRC / 'app' / 'router.js'
    menu = FRONTEND_SRC / 'app' / 'layout' / 'nav' / 'menu.config.js'
    if not router.exists():
        return
    routes = parse_frontend_routes(read_text(router))
    menu_paths = set(re.findall(r"path:\s*'([^']+)'", read_text(menu)))
    files = collect_files(FRONTEND_SRC, {'.js', '.ts', '.vue'})
    texts = {p: read_text(p) for p in files if p != router}

    for route in routes:
        if route.path == '/' or route.is_redirect:
            continue
        if any(route.path == m or route.path.startswith(m.rstrip('/') + '/')
               for m in menu_paths):
            continue
        pattern = _path_regex(route.path)
        name_hit = bool(route.name) and any(
            f"name: '{route.name}'" in text or f'name: "{route.name}"' in text
            or f"push('{route.name}'" in text or f'push("{route.name}"' in text
            for text in texts.values())
        path_hit = any(pattern.search(text) for text in texts.values())
        if not (name_hit or path_hit):
            result.add(Finding(
                'orphan-route', route.path,
                f'路由 {route.path}（name={route.name or "-"}）没有菜单或跳转能到达',
                file=rel(router), line=route.line))
    result.stats['frontend_routes'] = len(routes)


# ----------------------------------------------------------------------
# L1 后端端点消费方
# ----------------------------------------------------------------------


def runtime_backend_routes() -> list[tuple[str, str]]:
    sys.path.insert(0, str(BACKEND_SRC))
    try:
        from app import app  # type: ignore import-not-found
        from fastapi.routing import APIRoute
    finally:
        try:
            sys.path.remove(str(BACKEND_SRC))
        except ValueError:
            pass
    rows: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if '{unknown_path:path}' in route.path:
            continue
        for method in route.methods or ():
            if method in {'HEAD', 'OPTIONS'}:
                continue
            rows.add((method, route.path))
    return sorted(rows)


def _corpus(*roots: Path) -> str:
    chunks: list[str] = []
    suffixes = {'.js', '.ts', '.vue', '.md', '.yaml', '.yml', '.html'}
    for root in roots:
        for path in collect_files(root, suffixes):
            chunks.append(read_text(path))
    return '\n'.join(chunks)


def _endpoint_pattern(path: str) -> re.Pattern[str]:
    rel_path = path.replace(RKB_PREFIX, '')
    parts = re.split(r'(\{[^}]+\})', rel_path)
    pattern = ''
    for part in parts:
        if not part:
            continue
        pattern += r'[^`"\'\s]+' if part.startswith('{') else re.escape(part)
    return re.compile(pattern)


def _endpoint_tail(path: str) -> str:
    rel_path = path.replace(RKB_PREFIX, '')
    static = [s for s in rel_path.split('/') if s and not s.startswith('{')]
    return static[-1] if static else ''


def audit_backend_endpoints(result: AuditResult, include_backend: bool) -> None:
    if not include_backend:
        result.notes.append('已跳过后端端点审计（--no-backend）')
        return
    try:
        routes = runtime_backend_routes()
    except Exception as error:  # noqa: BLE001 - 审计脚本要自己解释失败
        result.add(Finding(
            'backend-import-failed', 'backend/src/app.py',
            f'无法导入 FastAPI 应用，后端审计未执行：{error}'))
        return

    frontend = _corpus(FRONTEND_SRC)
    e2e = _corpus(E2E_DIR)
    docs = _corpus(DOCS_DIR, CONTRACTS_DIR)
    api_only: list[str] = []
    for method, path in routes:
        pattern = _endpoint_pattern(path)
        tail = _endpoint_tail(path)
        in_frontend = bool(pattern.search(frontend)) or (tail and f'/{tail}' in frontend)
        in_e2e = bool(pattern.search(e2e))
        in_docs = bool(pattern.search(docs))
        if not (in_frontend or in_e2e or in_docs):
            result.add(Finding(
                'unreachable-endpoint', f'{method} {path}',
                '后端端点没有前端调用、e2e 或对外文档消费方'))
        elif not in_frontend:
            api_only.append(f'{method} {path}')
    result.stats['backend_endpoints'] = len(routes)
    result.stats['backend_endpoints_api_only'] = len(api_only)
    result.stats['api_only_endpoints'] = api_only  # L3 数据，供报告展示


# ----------------------------------------------------------------------
# L4 注释 / 开关 / 占位
# ----------------------------------------------------------------------

_VUE_COMMENT_RE = re.compile(r'<!--(.*?)-->', re.S)
_INTERACTIVE_RE = re.compile(
    r'<(el-(?:dropdown-item|button|menu-item|tab-pane|option|table-column|'
    r'form-item|input|select|dialog|drawer|tabs)|'
    r'router-link|button|a\s|input|select|template)\b|@click')
_DISABLED_RE = re.compile(r'v-(?:if|show)="false"|:disabled="true"')
_PY_COMMENT_CODE_RE = re.compile(r'^\s*#\s*(?:@router\.|def\s+\w+\(|register_\w+\()')
_TODO_RE = re.compile(r'TODO|FIXME|未实现|待实现|暂时屏蔽|暂不开放|占位实现|先注释')
_JS_COMMENT_CODE_RE = re.compile(
    r'^\s*//\s*(?:export\s+(?:function|const)|function\s+\w+\(|\$router\.push|axios\.)')


def audit_commented_ui(result: AuditResult) -> None:
    for path in collect_files(FRONTEND_SRC, {'.vue'}):
        text = read_text(path)
        # SFC 头部的说明性注释会引用组件名/标签示例，不当「注释掉的 UI」。
        template_at = text.find('<template')
        for match in _VUE_COMMENT_RE.finditer(text):
            body = match.group(1)
            if template_at != -1 and match.start() < template_at and not text[:match.start()].strip():
                continue
            if _INTERACTIVE_RE.search(body):
                snippet = ' '.join(body.split())[:100]
                result.add(Finding(
                    'commented-code', rel(path), f'注释掉的交互块：{snippet}',
                    file=rel(path), line=line_of(text, match.start())))
    for path in collect_files(FRONTEND_SRC, {'.js', '.ts'}):
        text = read_text(path)
        for lineno, line in enumerate(text.splitlines(), 1):
            if _JS_COMMENT_CODE_RE.match(line):
                result.add(Finding(
                    'commented-code', rel(path),
                    f'注释掉的调用：{line.strip()[:100]}',
                    file=rel(path), line=lineno))
    for path in collect_files(BACKEND_SRC, {'.py'}):
        text = read_text(path)
        for lineno, line in enumerate(text.splitlines(), 1):
            if _PY_COMMENT_CODE_RE.match(line):
                result.add(Finding(
                    'commented-code', rel(path),
                    f'注释掉的注册/定义：{line.strip()[:100]}',
                    file=rel(path), line=lineno))


def audit_unused_api_wrappers(result: AuditResult) -> None:
    """前端 API 模块里「定义了但没人调用」的封装。

    这是「后端有能力、前端只差一个按钮」最直接的信号：wrapper 写好了，页面没接。
    只扫 ``**/api/*.js|ts``，并按标识符做全文引用计数（含同文件内部调用）。
    """
    api_files = [p for p in collect_files(FRONTEND_SRC, {'.js', '.ts'})
                 if p.parent.name == 'api' or p.name in {'api.js', 'api.ts'}]
    all_texts = {p: read_text(p) for p in collect_files(FRONTEND_SRC, {'.js', '.ts', '.vue'})}
    for path in api_files:
        text = read_text(path)
        names = re.findall(r'export\s+(?:async\s+)?function\s+(\w+)', text)
        names += re.findall(r'export\s+const\s+(\w+)\s*=', text)
        for name in dict.fromkeys(names):
            defined = len(re.findall(rf'\b{re.escape(name)}\b', text))
            outside = sum(len(re.findall(rf'\b{re.escape(name)}\b', body))
                          for other, body in all_texts.items() if other != path)
            if outside == 0 and defined <= 1:
                result.add(Finding(
                    'unused-api-wrapper', f'{rel(path)}::{name}',
                    f'API 封装 {name} 没有任何调用方（后端能力可能没有 UI 入口）',
                    file=rel(path)))


def audit_disabled_ui(result: AuditResult) -> None:
    for path in collect_files(FRONTEND_SRC, {'.vue', '.js', '.ts'}):
        text = read_text(path)
        for match in _DISABLED_RE.finditer(text):
            result.add(Finding(
                'disabled-ui', rel(path),
                f'恒关闭的 UI：{match.group(0)}',
                file=rel(path), line=line_of(text, match.start())))


def audit_todos(result: AuditResult) -> None:
    for root, suffixes in ((BACKEND_SRC, {'.py'}), (FRONTEND_SRC, {'.js', '.ts', '.vue'})):
        for path in collect_files(root, suffixes):
            text = read_text(path)
            for lineno, line in enumerate(text.splitlines(), 1):
                if _TODO_RE.search(line):
                    result.add(Finding(
                        'todo-marker', rel(path),
                        line.strip()[:120], file=rel(path), line=lineno))


# ----------------------------------------------------------------------
# 白名单
# ----------------------------------------------------------------------


def load_allowlist(path: Path) -> list[Waiver]:
    if not path.exists():
        return []
    waivers: list[Waiver] = []
    for lineno, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        fields = [part.strip() for part in line.split('|')]
        if len(fields) < 3:
            raise ValueError(f'{path}:{lineno}: 需要 kind | key | reason | review-by')
        kind, key, reason = fields[0], fields[1], fields[2]
        review_by: date | None = None
        if len(fields) >= 4 and fields[3]:
            try:
                review_by = date.fromisoformat(fields[3])
            except ValueError as error:
                raise ValueError(f'{path}:{lineno}: review-by 需为 YYYY-MM-DD') from error
        waivers.append(Waiver(kind, key, reason, review_by, lineno))
    return waivers


def apply_waivers(result: AuditResult, waivers: list[Waiver],
                  today: date) -> tuple[list[Finding], list[Finding], list[Waiver]]:
    """返回 (未豁免, 已豁免, 过期/未命中)。"""
    by_key = {(w.kind, w.key): w for w in waivers}
    unwaived: list[Finding] = []
    waived: list[Finding] = []
    used: set[tuple[str, str]] = set()
    for finding in result.findings:
        key = (finding.kind, finding.key)
        waiver = by_key.get(key)
        if waiver is None:
            unwaived.append(finding)
            continue
        used.add(key)
        if waiver.review_by is not None and waiver.review_by < today:
            unwaived.append(Finding(
                'stale-waiver', finding.key,
                f'豁免已过期（{waiver.review_by.isoformat()}）：{waiver.reason}',
                file=finding.file, line=finding.line))
        else:
            waived.append(finding)
    leftovers = [w for w in waivers
                 if (w.kind, w.key) not in used
                 and not (w.kind == 'stale-waiver')]
    return unwaived, waived, leftovers


def write_allowlist(result: AuditResult, path: Path, today: date, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f'{path} 已存在；要覆盖请加 --force')
    review_by = today + timedelta(days=90)
    lines = [
        '# 入口暴露审计白名单',
        '# 格式：kind | key | 理由 | review-by（YYYY-MM-DD，过期即失败）',
        f'# 生成于 {today.isoformat()}；首次基线请逐条补齐理由。',
        '',
    ]
    for finding in sorted(result.findings, key=Finding.sort_key):
        if finding.severity != 'error':
            continue
        lines.append(f'{finding.kind} | {finding.key} | 待确认 | {review_by.isoformat()}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


# ----------------------------------------------------------------------
# 报告
# ----------------------------------------------------------------------


def finding_dict(finding: Finding) -> dict:
    return {
        'kind': finding.kind,
        'severity': finding.severity,
        'key': finding.key,
        'message': finding.message,
        'file': finding.file,
        'line': finding.line,
    }


def write_json(path: Path, result: AuditResult, unwaived: list[Finding],
               waived: list[Finding], stale: list[Waiver], today: date) -> None:
    payload = {
        'generated_on': today.isoformat(),
        'stats': result.stats,
        'notes': result.notes,
        'findings': [finding_dict(f) for f in sorted(result.findings, key=Finding.sort_key)],
        'unwaived': [finding_dict(f) for f in sorted(unwaived, key=Finding.sort_key)],
        'waived': [finding_dict(f) for f in sorted(waived, key=Finding.sort_key)],
        'stale_or_unused_waivers': [
            {'kind': w.kind, 'key': w.key, 'reason': w.reason,
             'review_by': w.review_by.isoformat() if w.review_by else None,
             'line': w.line}
            for w in stale
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _table(findings: list[Finding]) -> list[str]:
    if not findings:
        return ['（无）', '']
    lines = ['| kind | 位置 | 说明 |', '|---|---|---|']
    for finding in sorted(findings, key=Finding.sort_key):
        location = finding.file or '-'
        if finding.line:
            location = f'{location}:{finding.line}'
        message = finding.message.replace('|', '\\|')
        lines.append(f'| `{finding.kind}` | `{location}` | {message} |')
    lines.append('')
    return lines


def write_markdown(path: Path, result: AuditResult, unwaived: list[Finding],
                   waived: list[Finding], leftovers: list[Waiver], today: date) -> None:
    errors = [f for f in unwaived if f.severity == 'error']
    warnings = [f for f in unwaived if f.severity == 'warning']
    infos = [f for f in unwaived if f.severity == 'info']
    lines = [
        '# 入口暴露审计',
        '',
        f'> 生成时间：{today.isoformat()}　'
        f'扫描：{result.stats.get("frontend_files", 0)} 个前端文件 / '
        f'{result.stats.get("frontend_routes", 0)} 条前端路由 / '
        f'{result.stats.get("backend_endpoints", 0)} 个后端端点',
        '> 生成器：`tools/verify/exposure-audit.py`；'
        '白名单：`tools/verify/exposure-allowlist.txt`。**本文件自动生成，不要手改。**',
        '',
        '## 摘要',
        '',
        '| 级别 | 未豁免 | 已豁免 |',
        '|---|---:|---:|',
        f'| error | {len(errors)} | {len([f for f in waived if f.severity == "error"])} |',
        f'| warning | {len(warnings)} | {len([f for f in waived if f.severity == "warning"])} |',
        f'| info | {len(infos)} | {len([f for f in waived if f.severity == "info"])} |',
        '',
    ]
    if result.notes:
        lines += ['> 备注：' + '；'.join(result.notes), '']
    lines += ['## 1. 未豁免：error', ''] + _table(errors)
    lines += ['## 2. 未豁免：warning', ''] + _table(warnings)
    lines += ['## 3. 未豁免：info（待办，不参与门禁）', ''] + _table(infos)
    lines += ['## 4. 已豁免', ''] + _table(waived)
    api_only = result.stats.get('api_only_endpoints') or []
    lines += ['## 5. L3 数据：无前端调用的端点（仅 e2e / 文档）', '']
    if api_only:
        lines += ['| method path |', '|---|']
        lines += [f'| `{row}` |' for row in api_only]
        lines += ['', '> 这些端点可能是**有意只对外**，也可能只是 UI 没接；本版不设门禁。', '']
    else:
        lines += ['（无）', '']
    lines += ['## 6. 过期 / 未命中的白名单', '']
    if leftovers:
        lines += ['| kind | key | 理由 | review-by |', '|---|---|---|---|']
        for waiver in leftovers:
            review = waiver.review_by.isoformat() if waiver.review_by else '-'
            lines.append(f'| `{waiver.kind}` | `{waiver.key}` | {waiver.reason} | {review} |')
        lines.append('')
    else:
        lines += ['（无）', '']
    lines += [
        '## 方法与局限',
        '',
        '- L2 可达性 = 从 `frontend/src/app/main.js`、`app/router.js` 出发的静态 import/'
        '模板标签/动态模板 require 闭包；运行时字符串拼接的入口会漏。',
        '- L1 端点消费方按「前端 / e2e / 文档（含生成的 OpenAPI）」文本匹配；'
        '路径常量间接拼接时按最后静态段判定，宁可漏报不误报。',
        '- L5 只认 spec 里的 `@/` import 说明符；通过变量或运行时拼出来的引用可能漏判。',
        '- 结论请配合人工复核；白名单必须写理由与复核日期，过期即失败。',
        '',
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8')


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------


def run_audit(include_backend: bool) -> AuditResult:
    result = AuditResult()
    audit_unreachable_files(result)
    audit_frontend_routes(result)
    audit_backend_endpoints(result, include_backend)
    audit_unused_api_wrappers(result)
    audit_commented_ui(result)
    audit_disabled_ui(result)
    audit_todos(result)
    result.findings.sort(key=Finding.sort_key)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true', help='CI 模式：有未豁免 error 即退出 1')
    parser.add_argument('--strict', action='store_true', help='--check 时把 warning 也算失败')
    parser.add_argument('--no-backend', action='store_true', help='跳过 FastAPI 运行时端点审计')
    parser.add_argument('--write-allowlist', action='store_true', help='把当前 error 写成白名单基线')
    parser.add_argument('--force', action='store_true', help='配合 --write-allowlist 覆盖已有文件')
    parser.add_argument('--json', type=Path, default=DEFAULT_JSON)
    parser.add_argument('--md', type=Path, default=DEFAULT_MD)
    parser.add_argument('--allowlist', type=Path, default=ALLOWLIST)
    parser.add_argument('--today', type=date.fromisoformat, default=date.today(),
                        help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    try:
        waivers = load_allowlist(args.allowlist)
    except ValueError as error:
        print(f'[exposure-audit] 白名单格式错误：{error}', file=sys.stderr)
        return 2

    result = run_audit(include_backend=not args.no_backend)
    if args.write_allowlist:
        write_allowlist(result, args.allowlist, args.today, args.force)
        print(f'[exposure-audit] 已写入白名单：{rel(args.allowlist)}')
        return 0

    unwaived, waived, leftovers = apply_waivers(result, waivers, args.today)
    write_json(args.json, result, unwaived, waived, leftovers, args.today)
    write_markdown(args.md, result, unwaived, waived, leftovers, args.today)

    errors = [f for f in unwaived if f.severity == 'error']
    warnings = [f for f in unwaived if f.severity == 'warning']
    infos = [f for f in unwaived if f.severity == 'info']
    print(f'[exposure-audit] error={len(errors)} warning={len(warnings)} info={len(infos)} '
          f'waived={len(waived)} stale/unused={len(leftovers)}')
    print(f'[exposure-audit] 报告：{rel(args.md)} / {rel(args.json)}')
    if errors:
        for finding in errors[:10]:
            print(f'  - {finding.kind}: {finding.key} — {finding.message}')
        if len(errors) > 10:
            print(f'  ... 其余 {len(errors) - 10} 条见报告')

    if args.check:
        if errors:
            return 1
        if args.strict and warnings:
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
