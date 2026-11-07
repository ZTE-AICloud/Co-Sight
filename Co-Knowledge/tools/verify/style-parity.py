#!/usr/bin/env python3
"""样式对齐体检：把 frontend/src 的样式与 5173 原型（rag-studio-ui-demo）对齐。

校验三类「自己搞一套」的问题（这些是硬性失败，退出码 1）：
  1. 组件 <style> 里整条复制的全局规则（全局样式已能提供同选择器同声明）；
  2. 未定义的私有 token 词汇（--ux-* / --ds-*）或组件内重新定义 --rs-*；
  3. 全局样式文件与原型逐字节不一致（tokens/theme 必须相同；base 等允许有
     带注释的增量，脚本只打印差异，不计失败）。

可选 --pairs：按文件名 + 别名表，把原型组件/页面与线上实现逐规则比对。
⚠️ 原型以 `rag-studio-ui-demo` 的 git HEAD 为准（0.1.12+；`package.json`
里的 0.1.9 是旧值），线上已实现到 0.1.13；原型尚未覆盖的新页面，成对差异
只作参考，不要盲目照抄。

用法：
    python3 tools/verify/style-parity.py --demo ../rag-studio-ui-demo/src
    python3 tools/verify/style-parity.py --demo ../rag-studio-ui-demo/src --pairs

只依赖 Python 3 标准库。
"""
import argparse
import os
import re
import sys
from collections import defaultdict

GLOBAL_CSS = [
    'styles/tokens.css', 'styles/base.css', 'styles/theme.css', 'styles/tables.css',
    'styles/management.css', 'styles/dialogs.css', 'styles/deletions.css',
    'styles/workspaces.css', 'styles/flow-config.css', 'styles/fonts.css',
    'styles/reduced-motion.css',
]
# 原型旧文件与线上新文件的别名（同名文件会自动配对，这里只补改名/拆页的）
PAIR_ALIASES = {
    'components/AppSidebar.vue': 'app/layout/nav/LeftNav.vue',
    'views/Knowledge.vue': 'pages/knowledge-base/KnowledgeBaseListPage.vue',
    'views/KnowledgeDetail.vue': 'pages/knowledge-base/KnowledgeBaseDetailPage.vue',
    'views/GraphDetail.vue': 'pages/graph/GraphDetailPage.vue',
    'views/GraphEdit.vue': 'features/graph/EditKnowledgeGraph.vue',
    'views/Flow.vue': 'pages/workflow/WorkflowListPage.vue',
    'views/FlowDetail.vue': 'pages/workflow/WorkflowEditorPage.vue',
    'views/Keys.vue': 'pages/agent/KeyManagementPage.vue',
    'views/Login.vue': 'pages/login/LoginPage.vue',
    'views/Chat.vue': ['pages/chat/ChatPage.vue', 'pages/chat/chat.less'],
    'views/Models.vue': ['pages/model/ModelListPage.vue', 'features/model/ModelTable.vue'],
    'views/Operators.vue': ['pages/operators/OperatorListPage.vue', 'features/operators/OperatorTable.vue'],
    'views/Access.vue': ['pages/agent/AgentLayout.vue', 'pages/agent/AccessGuidePage.vue'],
    'components/ChatHistory.vue': 'features/chat/components/ChatHistoryPanel.vue',
    'components/CanvasViewport.vue': 'features/graph/components/GraphEditor/GraphCanvas.vue',
    'components/GraphRelationDrawer.vue': 'features/graph/components/GraphRelationCreateDrawer.vue',
}


def strip_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def normalize_decl(decl):
    decl = ' '.join(decl.split())
    decl = re.sub(r'\s*:\s*', ':', decl)
    decl = re.sub(r'\s*,\s*', ',', decl)
    return re.sub(r'\s*!\s*important', '!important', decl)


def parse(css, media=None, out=None):
    """最小 CSS 解析器：返回 [(media, selector, [decl...])]，支持 @media/@supports 展开。"""
    if out is None:
        out = []
    css = css.strip()
    i, n = 0, len(css)
    while i < n:
        j = css.find('{', i)
        if j == -1:
            break
        head = css[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            if css[k] == '{':
                depth += 1
            elif css[k] == '}':
                depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        if head.startswith('@media') or head.startswith('@supports'):
            norm = re.sub(r'\s+', '', head)
            parse(body, (media + ' ' if media else '') + norm, out)
        elif not head.startswith('@'):
            decls, cur, pdepth = [], '', 0
            for ch in body:
                if ch == '(':
                    pdepth += 1
                elif ch == ')':
                    pdepth -= 1
                if ch == ';' and pdepth == 0:
                    d = normalize_decl(cur)
                    if d:
                        decls.append(d)
                    cur = ''
                else:
                    cur += ch
            d = normalize_decl(cur)
            if d:
                decls.append(d)
            for sel in head.split(','):
                out.append(((media or ''), ' '.join(sel.split()), decls))
        i = k
    return out


def style_rules(path):
    text = open(path, encoding='utf-8').read()
    rules = defaultdict(list)
    blocks = [m.group(2) for m in re.finditer(r'<style([^>]*)>(.*?)</style>', text, re.S)]
    if not blocks and path.endswith(('.css', '.less')):
        blocks = [text]
    for block in blocks:
        for media, sel, decls in parse(strip_comments(block)):
            rules[(media, sel)].extend(decls)
    return {k: sorted(set(v)) for k, v in rules.items()}


def walk_style_sources(src):
    for dirpath, _, files in os.walk(src):
        for f in files:
            if f.endswith(('.vue', '.css', '.less')):
                p = os.path.join(dirpath, f)
                rel = os.path.relpath(p, src)
                if rel.startswith('styles/'):
                    continue
                yield rel, p


def global_rules(src):
    rules = defaultdict(set)
    for rel in GLOBAL_CSS:
        p = os.path.join(src, rel)
        if not os.path.exists(p):
            continue
        for media, sel, decls in parse(strip_comments(open(p, encoding='utf-8').read())):
            rules[(media, sel)] |= set(decls)
    return rules


def check_duplicates(src, g_rules):
    findings = []
    for rel, path in walk_style_sources(src):
        text = open(path, encoding='utf-8').read()
        if not text.strip():
            continue
        found = []
        for media, sel, decls in parse(strip_comments(''.join(
                m.group(2) for m in re.finditer(r'<style([^>]*)>(.*?)</style>', text, re.S)))):
            if '&' in sel or not decls:
                continue
            g = g_rules.get((media, sel))
            if g and set(normalize_decl(d) for d in decls) <= g:
                found.append((media, sel, len(decls)))
        if found:
            findings.append((rel, found))
    return findings


def check_tokens(src):
    bad_usage, local_rs = [], []
    for rel, path in walk_style_sources(src):
        text = open(path, encoding='utf-8').read()
        if re.search(r'--(?:ux|ds)-[a-z0-9-]+', text):
            bad_usage.append(rel)
        if re.search(r'--rs-[a-z0-9-]+\s*:', text):
            local_rs.append(rel)
    return bad_usage, local_rs


def diff_global(src, demo):
    rows = []
    for rel in GLOBAL_CSS:
        a, b = os.path.join(demo, rel), os.path.join(src, rel)
        if not os.path.exists(a) or not os.path.exists(b):
            rows.append((rel, 'missing', ''))
            continue
        ta = open(a, encoding='utf-8').read().splitlines()
        tb = open(b, encoding='utf-8').read().splitlines()
        if ta == tb:
            rows.append((rel, 'same', ''))
        else:
            rows.append((rel, 'diff', f'+{len(tb) - len(ta)} lines' if len(tb) > len(ta)
                         else f'{len(tb) - len(ta)} lines'))
    return rows


def pair_report(src, demo):
    demo_files, prod_files = {}, {}
    for root, bucket in ((demo, demo_files), (src, prod_files)):
        for dirpath, _, files in os.walk(root):
            for f in files:
                if f.endswith('.vue'):
                    rel = os.path.relpath(os.path.join(dirpath, f), root)
                    bucket.setdefault(f[:-4], []).append(rel)
    pairs = []
    for name, rels in demo_files.items():
        if name == 'Graph':
            continue  # 原型没有 Graph.vue 列表页（只有详情/编辑）
        drel = rels[0]
        prel = PAIR_ALIASES.get(drel) or (prod_files.get(name) or [None])[0]
        if prel:
            prels = [prel] if isinstance(prel, str) else list(prel)
            prels = [p for p in prels if os.path.exists(os.path.join(src, p))]
            if prels:
                pairs.append((name, drel, prels))

    rows = []
    for name, drel, prels in sorted(pairs):
        d = style_rules(os.path.join(demo, drel))
        p = {}
        for prel in prels:
            for k, v in style_rules(os.path.join(src, prel)).items():
                p[k] = sorted(set(p.get(k, [])) | set(v))
        only_d = [k for k in d if k not in p]
        only_p = [k for k in p if k not in d]
        changed = [k for k in d if k in p and d[k] != p[k]]
        rows.append((len(only_d) + len(only_p) + len(changed), name, len(d), len(p),
                     len(only_d), len(only_p), len(changed), ', '.join(prels)))
    return sorted(rows, reverse=True)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    default_src = os.path.normpath(os.path.join(here, '../../frontend/src'))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', default=default_src, help='frontend/src 路径')
    ap.add_argument('--demo', required=True, help='rag-studio-ui-demo/src 路径')
    ap.add_argument('--pairs', action='store_true', help='输出与原型成对文件的规则差异（参考）')
    args = ap.parse_args()

    src, demo = os.path.abspath(args.src), os.path.abspath(args.demo)
    if not os.path.isdir(src) or not os.path.isdir(demo):
        ap.error('--src / --demo 必须是目录')

    failed = False
    g = global_rules(src)

    print('== 1. 组件内整条复制的全局规则 ==')
    dups = check_duplicates(src, g)
    if dups:
        failed = True
        for rel, rules in dups:
            print(f'  {rel}')
            for media, sel, count in rules:
                print(f'    [{media or "base"}] {sel}  ({count} decls)')
    else:
        print('  无')

    print('\n== 2. 私有 token 词汇 / 组件内重定义 --rs-* ==')
    bad_usage, local_rs = check_tokens(src)
    if bad_usage or local_rs:
        failed = True
        for rel in bad_usage:
            print(f'  {rel}: 使用了未定义的 --ux-* / --ds-*')
        for rel in local_rs:
            print(f'  {rel}: 组件内重新定义 --rs-*')
    else:
        print('  无')

    print('\n== 3. 全局样式与原型的一致性 ==')
    for rel, state, note in diff_global(src, demo):
        print(f'  {rel}: {state} {note}'.rstrip())
    print('  （tokens/theme 必须 same；base/workspaces 等允许有注释说明的增量）')

    if args.pairs:
        print('\n== 4. 与原型成对文件的规则差异（0.1.10+ 新页面不适用，仅参考） ==')
        print('  total  name                         demo prod only-d only-p changed  file')
        for total, name, dn, pn, od, op, ch, prel in pair_report(src, demo):
            print(f'  {total:5d}  {name:28s} {dn:4d} {pn:4d} {od:6d} {op:6d} {ch:7d}  {prel}')

    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
