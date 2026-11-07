#!/usr/bin/env node
/**
 * 把 `.md` 渲染成**单文件、离线可用**的 HTML（内联 CSS/JS，无外部请求）。
 *
 * 用法（仓库根目录）：
 *   node tools/docs/build-external-api-html.mjs
 *   node tools/docs/build-external-api-html.mjs docs/external-api/knowledge-studio-api.md
 *
 * 依赖 frontend 的 marked（已在 frontend/package.json 声明），不引入新的构建链。
 * 生成物与 Markdown 同目录、同名、扩展名 .html。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const DEFAULT_MD = path.join(ROOT, 'docs/external-api/knowledge-studio-api.md');
const MARKED_ENTRY = path.join(ROOT, 'frontend/node_modules/marked/lib/marked.esm.js');

function fail(message) {
  console.error(`❌ ${message}`);
  process.exit(1);
}

function readMeta(markdown) {
  const meta = {};
  const re = /^<!--\s*doc-([a-z-]+):\s*(.*?)\s*-->\s*$/gm;
  let match;
  while ((match = re.exec(markdown)) !== null) meta[match[1]] = match[2];
  const withoutMeta = markdown.replace(re, '');
  return { meta, markdown: withoutMeta };
}

function stripTags(value) {
  return value
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function addHeadingIds(html) {
  const toc = [];
  let h2 = 0;
  let h3 = 0;
  const withIds = html.replace(
    /<h([23])([^>]*)>([\s\S]*?)<\/h\1>/g,
    (_full, level, attrs, inner) => {
      let id;
      if (level === '2') {
        h2 += 1;
        h3 = 0;
        id = `sec-${h2}`;
      } else {
        h3 += 1;
        id = `sec-${h2}-${h3}`;
      }
      toc.push({ level: Number(level), id, text: stripTags(inner) });
      return `<h${level} id="${id}"${attrs}>${inner}` +
        `<a class="heading-anchor" href="#${id}" aria-label="本节链接">#</a></h${level}>`;
    },
  );
  return { html: withIds, toc };
}

function buildToc(toc) {
  // 按 h2 分组，h3 挂在最近的 h2 下；避免手写开闭状态。
  const groups = [];
  let current = null;
  for (const heading of toc) {
    if (heading.level === 2) {
      current = { ...heading, children: [] };
      groups.push(current);
    } else if (current) {
      current.children.push(heading);
    }
  }
  return groups.map((group) => {
    const children = group.children.length
      ? `<ul class="toc-sub">${group.children.map((child) =>
          `<li class="toc-item toc-h3" data-text="${escapeHtml(child.text)}">` +
          `<a href="#${child.id}">${escapeHtml(child.text)}</a></li>`).join('')}</ul>`
      : '';
    return `<li class="toc-item toc-h2" data-text="${escapeHtml(group.text)}">` +
      `<a href="#${group.id}">${escapeHtml(group.text)}</a>${children}</li>`;
  }).join('');
}

function wrapTables(html) {
  return html
    .replace(/<table>/g, '<div class="table-wrap"><table>')
    .replace(/<\/table>/g, '</table></div>');
}

function addCodeLanguages(html) {
  return html.replace(
    /<pre><code class="language-([^"]+)">/g,
    '<pre data-lang="$1"><code class="language-$1">',
  );
}

function addTableCodeBreaks(html) {
  // 表格里的长标识符只在 _ / - 处断行，避免手机端把单词从中间劈开。
  // 必须先在 <td> 边界内截取内容：单元格里 <code> 前后可能还有别的文字，
  // 直接匹配 `<td><code>…</code></td>` 会跨过单元格吞掉后面的标题/属性。
  return html.replace(/<td([^>]*)>([\s\S]*?)<\/td>/g, (_full, tdAttrs, cell) => {
    const broken = cell.replace(
      /<code([^>]*)>([\s\S]*?)<\/code>/g,
      (_code, codeAttrs, content) =>
        `<code${codeAttrs}>${content.replace(/([_-])/g, '$1<wbr>')}</code>`,
    );
    return `<td${tdAttrs}>${broken}</td>`;
  });
}

const CSS = String.raw`
:root {
  --paper: #fbfaf6;
  --surface: #ffffff;
  --surface-2: #f4f0e6;
  --ink: #1d232b;
  --ink-2: #3c4652;
  --muted: #6b7480;
  --line: #e2dccd;
  --line-strong: #cfc6b4;
  --accent: #0f6b5c;
  --accent-2: #b4552a;
  --accent-soft: #e6f1ee;
  --code-bg: #f4f1e9;
  --code-border: #e0d9ca;
  --topbar: #1b222b;
  --topbar-ink: #f5f1e7;
  --radius: 8px;
  --shadow: 0 10px 30px rgba(29, 35, 43, .08);
}

* { box-sizing: border-box; }

html {
  scroll-behavior: smooth;
  scroll-padding-top: 84px;
}

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", "Source Han Sans SC",
    "Noto Sans CJK SC", sans-serif;
  font-size: 15.5px;
  line-height: 1.74;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: #0a4d42; }

.progress {
  position: fixed; top: 0; left: 0; height: 3px; width: 0;
  background: linear-gradient(90deg, var(--accent), #2f9b86);
  z-index: 100;
}

.topbar {
  position: sticky; top: 0; z-index: 90;
  height: 64px; display: flex; align-items: center; gap: 18px;
  padding: 0 24px;
  background: var(--topbar);
  color: var(--topbar-ink);
  border-bottom: 1px solid rgba(255, 255, 255, .08);
}
.brand { display: flex; align-items: center; gap: 10px; min-width: 0; }
.brand-mark {
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: 7px;
  background: var(--accent); color: #fff;
  font-size: 11px; font-weight: 800; letter-spacing: .06em;
}
.brand-text { font-size: 14px; font-weight: 650; letter-spacing: .02em; white-space: nowrap; }
.topbar-meta { margin-left: auto; display: flex; align-items: center; gap: 14px; }
.pill {
  display: inline-flex; align-items: center; height: 26px; padding: 0 10px;
  border: 1px solid rgba(245, 241, 231, .28); border-radius: 999px;
  font-size: 12px; letter-spacing: .02em; color: rgba(245, 241, 231, .9);
}
.topbar-date { font-size: 12px; color: rgba(245, 241, 231, .55); }
.print-btn {
  appearance: none; border: 1px solid rgba(245, 241, 231, .28);
  background: transparent; color: var(--topbar-ink);
  height: 30px; padding: 0 12px; border-radius: 6px;
  font: inherit; font-size: 12px; cursor: pointer;
}
.print-btn:hover { background: rgba(255, 255, 255, .08); }
.menu-toggle {
  display: none; appearance: none; border: 0; background: transparent;
  color: var(--topbar-ink); font-size: 20px; line-height: 1; cursor: pointer;
  padding: 4px 2px;
}

.shell {
  display: grid;
  grid-template-columns: 292px minmax(0, 1fr);
  max-width: 1480px;
  margin: 0 auto;
}

.sidebar {
  position: sticky; top: 64px;
  height: calc(100vh - 64px);
  overflow-y: auto;
  padding: 22px 16px 28px 24px;
  border-right: 1px solid var(--line);
  scrollbar-width: thin;
}
.search-wrap { position: relative; margin-bottom: 18px; }
#tocSearch {
  width: 100%; height: 36px; padding: 0 34px 0 11px;
  border: 1px solid var(--line-strong); border-radius: 6px;
  background: var(--surface); color: var(--ink);
  font: inherit; font-size: 13px; outline: none;
}
#tocSearch:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.search-hint {
  position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
  color: var(--muted); font-size: 11px; border: 1px solid var(--line);
  border-radius: 4px; padding: 0 5px; background: var(--surface-2);
}
.toc, .toc ul { list-style: none; margin: 0; padding: 0; }
.toc-item { margin: 0; }
.toc-h2 > a {
  display: block; padding: 6px 10px 6px 11px;
  border-left: 2px solid transparent;
  color: var(--ink-2); text-decoration: none;
  font-size: 13px; font-weight: 600; line-height: 1.45;
}
.toc-h2 > a:hover { background: var(--surface-2); color: var(--ink); }
.toc-sub { margin: 1px 0 6px 10px !important; border-left: 1px solid var(--line); }
.toc-h3 > a {
  display: block; padding: 4px 8px 4px 12px;
  color: var(--muted); text-decoration: none;
  font-size: 12.5px; line-height: 1.45;
}
.toc-h3 > a:hover { color: var(--ink); background: var(--surface-2); }
.toc-item.active > a {
  color: var(--accent); border-left-color: var(--accent); background: var(--accent-soft);
}
.toc-h3.active > a { color: var(--accent); background: transparent; font-weight: 600; }
.toc-empty { display: none; padding: 10px 11px; color: var(--muted); font-size: 12.5px; }
.sidebar-foot {
  margin-top: 26px; padding-top: 16px; border-top: 1px solid var(--line);
  display: grid; gap: 3px; color: var(--muted); font-size: 11.5px;
}

.scrim { display: none; }
.main { min-width: 0; padding: 46px 56px 80px; }
.content { max-width: 900px; margin: 0 auto; }

.doc-kicker {
  margin-bottom: 10px; color: var(--accent);
  font-size: 11.5px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase;
}
h1 {
  margin: 0 0 10px; font-size: clamp(2rem, 3.6vw, 2.65rem);
  line-height: 1.14; letter-spacing: -.025em; font-weight: 750;
  word-break: keep-all; overflow-wrap: anywhere;
}
h1 + p { margin-top: 14px; }
h2 {
  margin: 3.4rem 0 1rem; padding-top: 1.5rem;
  border-top: 1px solid var(--line);
  font-size: 1.52rem; line-height: 1.3; letter-spacing: -.015em; font-weight: 720;
}
h2:first-of-type { margin-top: 2.4rem; }
h3 {
  margin: 2.3rem 0 .75rem; padding-left: .72rem;
  border-left: 3px solid var(--accent);
  font-size: 1.13rem; line-height: 1.4; font-weight: 700;
}
h4 { margin: 1.8rem 0 .6rem; font-size: 1rem; font-weight: 700; }
h2, h3, h4 { scroll-margin-top: 84px; }
.heading-anchor {
  margin-left: .45rem; color: var(--line-strong); text-decoration: none;
  font-weight: 500; opacity: 0; transition: opacity .15s ease;
}
h2:hover .heading-anchor, h3:hover .heading-anchor, h4:hover .heading-anchor { opacity: 1; }

p { margin: .9rem 0; }
strong { font-weight: 700; color: #11161c; }
ul, ol { margin: .8rem 0; padding-left: 1.45rem; }
li { margin: .32rem 0; }
li > p { margin: .35rem 0; }
hr { border: 0; border-top: 1px solid var(--line); margin: 2.6rem 0; }

blockquote {
  margin: 1.15rem 0; padding: 12px 16px;
  background: #f7f3e9; border-left: 4px solid var(--accent-2);
  border-radius: 0 var(--radius) var(--radius) 0;
  color: var(--ink-2); font-size: 14.5px;
}
blockquote p:first-child { margin-top: 0; }
blockquote p:last-child { margin-bottom: 0; }
blockquote code { background: #fff; }

code {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: .88em;
  background: #f6f2e8; border: 1px solid var(--line);
  border-radius: 4px; padding: .1em .34em;
  word-break: break-word;
}
pre {
  position: relative; margin: 1.1rem 0; padding: 16px 18px;
  background: var(--code-bg); border: 1px solid var(--code-border);
  border-radius: var(--radius); overflow: auto;
}
pre code {
  display: block; padding: 0; border: 0; background: transparent;
  font-size: 13px; line-height: 1.62; white-space: pre;
}
pre[data-lang]::before {
  content: attr(data-lang);
  position: absolute; top: 8px; right: 58px;
  color: var(--muted); font-size: 10.5px; letter-spacing: .08em;
  text-transform: uppercase; pointer-events: none;
}
.copy-btn {
  position: absolute; top: 7px; right: 8px;
  appearance: none; border: 1px solid var(--code-border);
  background: rgba(255, 255, 255, .7); color: var(--muted);
  height: 24px; padding: 0 8px; border-radius: 5px;
  font: inherit; font-size: 11px; cursor: pointer;
}
.copy-btn:hover { color: var(--ink); border-color: var(--line-strong); }

.table-wrap {
  margin: 1.1rem 0; overflow-x: auto; overscroll-behavior-x: contain;
  border: 1px solid var(--line); border-radius: var(--radius);
}
table { width: 100%; border-collapse: collapse; font-size: 13.5px; line-height: 1.55; }
thead th {
  background: #efe9dc; color: var(--ink-2);
  text-align: left; font-weight: 700; white-space: nowrap;
}
th, td { padding: 9px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:nth-child(even) { background: #fcfbf7; }
tbody tr:hover { background: #f7f3e9; }
td code { white-space: normal; word-break: normal; overflow-wrap: normal; }

.doc-foot {
  max-width: 900px; margin: 56px auto 0; padding-top: 18px;
  border-top: 1px solid var(--line);
  display: flex; justify-content: space-between; gap: 18px;
  color: var(--muted); font-size: 12px;
}

#toTop {
  position: fixed; right: 22px; bottom: 22px; z-index: 80;
  width: 38px; height: 38px; border-radius: 50%;
  border: 1px solid var(--line-strong); background: var(--surface);
  color: var(--ink-2); box-shadow: var(--shadow);
  cursor: pointer; font-size: 15px; opacity: 0; pointer-events: none;
  transition: opacity .2s ease, transform .2s ease;
}
#toTop.show { opacity: 1; pointer-events: auto; }
#toTop:hover { transform: translateY(-2px); }

@media (max-width: 980px) {
  .shell { display: block; }
  .sidebar {
    position: fixed; top: 64px; left: 0; bottom: 0; z-index: 85;
    width: min(320px, 86vw); height: auto;
    background: var(--paper); border-right: 1px solid var(--line);
    transform: translateX(-102%); transition: transform .22s ease;
    box-shadow: 16px 0 40px rgba(29, 35, 43, .12);
  }
  .sidebar.open { transform: translateX(0); }
  .scrim {
    display: block; position: fixed; inset: 64px 0 0; z-index: 84;
    background: rgba(20, 24, 30, .38); opacity: 0; pointer-events: none;
    transition: opacity .22s ease;
  }
  .scrim.show { opacity: 1; pointer-events: auto; }
  .menu-toggle { display: inline-block; }
  .main { padding: 34px 24px 64px; }
  .topbar-date { display: none; }
}

@media (max-width: 620px) {
  body { font-size: 15px; }
  .topbar { padding: 0 14px; gap: 12px; }
  .brand-text { display: none; }
  .print-btn { display: none; }
  .main { padding: 26px 16px 56px; }
  h1 { font-size: 1.85rem; }
  h2 { font-size: 1.34rem; }
  h3 { font-size: 1.06rem; }
  table { font-size: 11.8px; }
  th { white-space: normal; }
  th, td { padding: 7px 8px; }
  .doc-foot { display: block; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}

@media print {
  @page { margin: 15mm 13mm; }
  body { background: #fff; color: #000; font-size: 10.5pt; line-height: 1.55; }
  .topbar, .sidebar, .scrim, .progress, #toTop, .copy-btn, .heading-anchor { display: none !important; }
  .shell { display: block; }
  .main { padding: 0; }
  .content { max-width: none; }
  h1 { font-size: 22pt; }
  h2 { font-size: 15pt; page-break-before: auto; page-break-after: avoid; margin-top: 18pt; padding-top: 10pt; }
  h3 { font-size: 12pt; page-break-after: avoid; }
  pre, blockquote, .table-wrap { page-break-inside: avoid; }
  pre code { white-space: pre-wrap; font-size: 8.5pt; }
  .table-wrap { overflow: visible; border: 1px solid #ccc; }
  table { width: 100%; table-layout: fixed; font-size: 8.5pt; }
  th, td { word-break: break-word; }
  td code { white-space: normal; overflow-wrap: anywhere; }
  a { color: inherit; text-decoration: none; }
  .doc-foot { max-width: none; }
}
`;

const JS = fs.readFileSync(
  path.join(HERE, 'external-api-doc.js'), 'utf8');

async function main() {
  const mdPath = path.resolve(process.argv[2] || DEFAULT_MD);
  if (!fs.existsSync(mdPath)) fail(`Markdown 不存在：${mdPath}`);
  if (!fs.existsSync(MARKED_ENTRY)) {
    fail(`找不到 marked：${MARKED_ENTRY}。请先在 frontend 目录执行 npm ci。`);
  }

  const raw = fs.readFileSync(mdPath, 'utf8');
  const { meta, markdown } = readMeta(raw);
  const { marked } = await import(pathToFileURL(MARKED_ENTRY).href);

  let html = marked.parse(markdown, { gfm: true, breaks: false });
  const { html: withIds, toc } = addHeadingIds(html);
  html = addTableCodeBreaks(wrapTables(addCodeLanguages(withIds)));

  const title = meta.title || (markdown.match(/^#\s+(.+)$/m) || [])[1] || 'API Documentation';
  const version = meta.version || '';
  const date = meta.date || '';
  const tocHtml = buildToc(toc);

  const page = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="description" content="Knowledge Studio 对外接口文档（集成面）：知识库只读、检索、问答、Agent REST 与 MCP。契约版本 ${escapeHtml(version)}。">
<title>${escapeHtml(title)}</title>
<style>${CSS}</style>
</head>
<body>
<div class="progress" id="progress"></div>
<header class="topbar">
  <button class="menu-toggle" id="menuToggle" type="button" aria-label="打开目录">☰</button>
  <div class="brand">
    <span class="brand-mark">RAG</span>
    <span class="brand-text">Knowledge Studio · API Reference</span>
  </div>
  <div class="topbar-meta">
    ${version ? `<span class="pill">契约 v${escapeHtml(version)}</span>` : ''}
    ${date ? `<span class="topbar-date">${escapeHtml(date)}</span>` : ''}
    <button class="print-btn" id="printBtn" type="button">打印 / PDF</button>
  </div>
</header>
<div class="scrim" id="scrim"></div>
<div class="shell">
  <aside class="sidebar" id="sidebar">
    <div class="search-wrap">
      <input id="tocSearch" type="search" placeholder="搜索目录…" autocomplete="off" aria-label="搜索目录">
      <span class="search-hint">/</span>
    </div>
    <nav class="toc" id="toc" aria-label="文档目录">${tocHtml}</nav>
    <div class="sidebar-foot">
      <span>${escapeHtml(title)}</span>
      <span>${date ? `生成于 ${escapeHtml(date)}` : ''}</span>
    </div>
  </aside>
  <main class="main">
    <article class="content">
      <div class="doc-kicker">External API Reference · Integration Surface</div>
      ${html}
    </article>
    <footer class="doc-foot">
      <span>${escapeHtml(title)}</span>
      <span>${version ? `契约版本 ${escapeHtml(version)}` : ''}${date ? ` · ${escapeHtml(date)}` : ''}</span>
    </footer>
  </main>
</div>
<button id="toTop" type="button" aria-label="回到顶部">↑</button>
<script>${JS}</script>
</body>
</html>
`;

  const outPath = path.join(path.dirname(mdPath), `${path.basename(mdPath, '.md')}.html`);
  fs.writeFileSync(outPath, page, 'utf8');
  console.log(`✅ 已生成 ${outPath}（${toc.filter((item) => item.level === 2).length} 个一级章节）`);
}

main().catch((error) => fail(error.stack || error.message));
