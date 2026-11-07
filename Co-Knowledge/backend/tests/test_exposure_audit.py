"""``tools/verify/exposure-audit.py`` 的纯函数测试。

脚本本身不依赖服务与数据库；这里钉住四类容易写错的判定：

1. import 解析：副作用 import、带注释的动态 import、**带点号的文件名**
   （``menu.config`` 被 ``Path.with_suffix`` 错切成 ``menu.js`` 的坑）；
2. 动态模板引用：``require(`.../${x}/Drawer`)`` 必须展开到所有 ``Drawer.vue``；
3. 路由解析：``children`` 里的相对路径要拼回父路径；
4. 白名单：过期要变成 error、未命中的条目要报出来；SFC 头部说明性注释
   不能被当成「注释掉的 UI」。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'tools' / 'verify' / 'exposure-audit.py'


def _load_module():
    spec = importlib.util.spec_from_file_location('exposure_audit', SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses 解析类型注解时会按 ``cls.__module__`` 回查 sys.modules。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _load_module()


def test_extract_imports_covers_side_effect_and_commented_dynamic():
    text = "\n".join([
        "import '@/app/bootstrap/mock'",
        "import App from './App.vue'",
        "const page = () => import(/* webpackChunkName: \"module.kb\" */'@/pages/kb.vue')",
        "const mod = require(`./modules/${name}/Drawer`)",
    ])
    specs = audit.extract_import_specifiers(text)
    assert '@/app/bootstrap/mock' in specs          # 副作用 import
    assert './App.vue' in specs
    assert '@/pages/kb.vue' in specs                # 动态 import 带注释
    assert './modules/${name}/Drawer' not in specs  # 反引号模板不进普通列表


def test_resolve_import_keeps_dotted_basename(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, 'FRONTEND_SRC', tmp_path)
    source = tmp_path / 'app' / 'router.js'
    source.parent.mkdir(parents=True)
    source.write_text('', encoding='utf-8')
    target = tmp_path / 'app' / 'layout' / 'nav' / 'menu.config.js'
    target.parent.mkdir(parents=True)
    target.write_text('', encoding='utf-8')

    assert audit.resolve_import('./layout/nav/menu.config', source, {source, target}) == target


def test_expand_dynamic_import_finds_every_drawer(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, 'FRONTEND_SRC', tmp_path)
    monkeypatch.setattr(audit, 'REPO', tmp_path)
    source = tmp_path / 'pages' / 'workflow' / 'editor.vue'
    source.parent.mkdir(parents=True)
    source.write_text('', encoding='utf-8')
    drawers = []
    for name in ('retriever', 'preretriever', 'responsesynthesizer', 'postretriever'):
        drawer = tmp_path / 'features' / 'workflow' / 'modules' / name / 'Drawer.vue'
        drawer.parent.mkdir(parents=True)
        drawer.write_text('', encoding='utf-8')
        drawers.append(drawer.resolve())

    found = audit.expand_dynamic_import(
        '../../features/workflow/modules/${directory}/Drawer', source, set(drawers))
    assert found == set(drawers)


def test_parse_frontend_routes_joins_relative_child_paths():
    router = """
    const routes = [
      { path: '/remoteAccess', component: RemoteAccessIndex,
        children: [
          { path: 'guide', name: 'remoteAccessGuide', component: Guide },
          { path: 'keys', name: 'remoteAccessKeys', component: Keys },
        ] },
      { path: '/kb/knowledgeDetail/:kbId', name: 'knowledgeDetail', component: Detail },
    ]
    """
    routes = audit.parse_frontend_routes(router)
    paths = {route.path for route in routes}
    assert '/remoteAccess/guide' in paths
    assert '/remoteAccess/keys' in paths
    assert '/kb/knowledgeDetail/:kbId' in paths
    assert next(r for r in routes if r.path == '/remoteAccess/guide').name == 'remoteAccessGuide'


def test_path_regex_matches_route_with_params():
    pattern = audit._path_regex('/kb/knowledgeDetail/:kbId/documents')
    assert pattern.search("push('/kb/knowledgeDetail/abc/documents')")
    assert not pattern.search("push('/kb/knowledgeDetail/abc')")


def _finding(key: str, kind: str = 'orphan-route'):
    return audit.Finding(kind=kind, key=key, message='x')


def test_apply_waivers_flags_expired_and_unused():
    today = date(2026, 10, 28)
    result = audit.AuditResult(findings=[_finding('/gone')])
    expired = audit.Waiver('orphan-route', '/gone', '旧基线', today - timedelta(days=1), 3)
    unwaived, waived, leftovers = audit.apply_waivers(result, [expired], today)
    assert [f.kind for f in unwaived] == ['stale-waiver']
    assert waived == []
    assert leftovers == []

    result = audit.AuditResult(findings=[_finding('/gone')])
    future = audit.Waiver('orphan-route', '/gone', '保留', today + timedelta(days=30), 3)
    _, waived, _ = audit.apply_waivers(result, [future], today)
    assert len(waived) == 1

    result = audit.AuditResult()
    _, _, leftovers = audit.apply_waivers(
        result, [audit.Waiver('orphan-route', '/never', 'stale key', None, 1)], today)
    assert [w.key for w in leftovers] == ['/never']


def test_commented_ui_skips_sfc_header_docs(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, 'FRONTEND_SRC', tmp_path)
    page = tmp_path / 'Page.vue'
    page.write_text(
        '<!--\n  用法示例：<AppToolbar><el-button>保存</el-button></AppToolbar>\n-->\n'
        '<template>\n'
        '  <!-- <el-button @click="save">保存</el-button> -->\n'
        '  <div />\n'
        '</template>\n',
        encoding='utf-8')
    result = audit.AuditResult()
    audit.audit_commented_ui(result)
    commented = [f for f in result.findings if f.kind == 'commented-code']
    assert len(commented) == 1
    assert commented[0].line == 5


def test_write_allowlist_only_emits_errors(tmp_path):
    result = audit.AuditResult(findings=[
        _finding('/missing', 'unreachable-file'),
        audit.Finding('todo-marker', 'a.py', 'TODO'),
    ])
    target = tmp_path / 'allowlist.txt'
    audit.write_allowlist(result, target, date(2026, 10, 28), force=False)
    text = target.read_text(encoding='utf-8')
    assert 'unreachable-file | /missing | 待确认 | 2027-01-26' in text
    assert 'todo-marker' not in text
