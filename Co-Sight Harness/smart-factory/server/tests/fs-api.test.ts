import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs';
import { dirname, join, parse } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { startWorkspaceStub } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('fs-api');
const stub = await startWorkspaceStub(env);

let api: TestApi;

/** 工作区里的一套夹具：一个目录、两个文件 */
const DOCS = join(env.workspaceDir, 'docs');
const ROOT_FILE = join(env.workspaceDir, 'CLAUDE.md');
const DOC_FILE = join(DOCS, 'sources.yaml');

/**
 * 预览端点夹具放在 COSIGHT_HOME 下、**不放进 workspaceDir**：
 * 工作区里多一个条目，上面「列目录」用例的期望值就跟着变，彼此耦合。
 */
const PREVIEW_DIR = join(env.home, 'preview-fixtures');
const BOM_FILE = join(PREVIEW_DIR, 'bom.md');
const LARGE_FILE = join(PREVIEW_DIR, 'large.txt');
const BINARY_FILE = join(PREVIEW_DIR, 'blob.bin');
const HTML_FILE = join(PREVIEW_DIR, 'report.html');
const UNICODE_DIR = join(PREVIEW_DIR, '中文 目录');
const UNICODE_FILE = join(UNICODE_DIR, '说明 文件.txt');

/** 文本上限调到 1 KiB：413 用一个 2 KiB 的文件就能覆盖，不必真造 2 MiB */
const MAX_TEXT_BYTES = 1024;

function readFile(path: string) {
  return api.get(`${API}/fs/read?path=${encodeURIComponent(path)}`);
}

/** 把绝对路径按分段拼成 raw URL（前端也是这么编的） */
function rawUrl(path: string): string {
  return `${api.base}${API}/fs/raw${path.split('/').map(encodeURIComponent).join('/')}`;
}

before(async () => {
  mkdirSync(DOCS, { recursive: true });
  writeFileSync(ROOT_FILE, '# 根目录说明\n');
  writeFileSync(DOC_FILE, 'sources: []\n');

  // 必须赶在 createApp() 之前设：config 在 import 时读环境变量
  process.env.ARTIFACT_MAX_FILE_BYTES = String(MAX_TEXT_BYTES);
  mkdirSync(PREVIEW_DIR, { recursive: true });
  writeFileSync(BOM_FILE, `${String.fromCharCode(0xfeff)}# 带 BOM\n`);
  writeFileSync(LARGE_FILE, 'x'.repeat(MAX_TEXT_BYTES * 2));
  writeFileSync(BINARY_FILE, Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x00, 0x01, 0x02]));
  writeFileSync(HTML_FILE, '<!doctype html><title>t</title><p>hi</p>\n');
  mkdirSync(UNICODE_DIR, { recursive: true });
  writeFileSync(UNICODE_FILE, '中文内容\n');

  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
});

function list(path?: string) {
  const query = path === undefined ? '' : `?path=${encodeURIComponent(path)}`;
  return api.get(`${API}/fs/list${query}`);
}

test('可浏览的根：主目录 + 框架工作区，当前生效的工作区带 active', async () => {
  const { status, body } = await api.get(`${API}/fs/roots`);
  assert.equal(status, 200);

  const labels = body.items.map((item: any) => item.label);
  assert.ok(labels.includes('主目录'));
  assert.ok(labels.includes('工作区：测试工作区'));

  const workspace = body.items.find((item: any) => item.workspaceId !== null);
  assert.equal(workspace.active, true);
  assert.equal(workspace.path, env.workspaceDir);
});

test('列目录：返回绝对路径、目录在前、按名称升序', async () => {
  const { status, body } = await list(env.workspaceDir);
  assert.equal(status, 200);
  assert.equal(body.path, env.workspaceDir);
  assert.equal(body.truncated, false, '条目没到上限时不截断');

  const names = body.items.map((item: any) => item.name);
  assert.deepEqual(names, ['docs', 'CLAUDE.md']);

  const file = body.items.find((item: any) => item.name === 'CLAUDE.md');
  assert.equal(file.type, 'file');
  assert.equal(file.path, ROOT_FILE);
  assert.ok(file.size > 0);
  assert.notEqual(file.mtime, '');

  const dir = body.items.find((item: any) => item.name === 'docs');
  assert.equal(dir.type, 'dir');
  assert.equal(dir.size, 0);
});

test('进入子目录：parent 指回上一级', async () => {
  const { status, body } = await list(DOCS);
  assert.equal(status, 200);
  assert.equal(body.parent, env.workspaceDir);
  assert.deepEqual(
    body.items.map((item: any) => item.name),
    ['sources.yaml'],
  );
});

test('上一级不再卡在快捷入口：指向真实父目录', async () => {
  const { status, body } = await list(env.workspaceDir);
  assert.equal(status, 200);
  assert.equal(body.parent, dirname(env.workspaceDir));
});

test('文件系统根：parent 为 null', async () => {
  const { status, body } = await list(parse(env.workspaceDir).root);
  assert.equal(status, 200);
  assert.equal(body.parent, null);
});

test('主目录与工作区之外：照样能列（浏览范围不设限）', async () => {
  const { status, body } = await list('/etc');
  assert.equal(status, 200);
  assert.equal(body.path, realpathSync('/etc'));
});

test('相对路径：400', async () => {
  const { status, body } = await list('docs');
  assert.equal(status, 400);
  assert.equal(body.error, 'BAD_REQUEST');
});

test('合法但不存在：404', async () => {
  const { status, body } = await list(join(env.workspaceDir, 'nope'));
  assert.equal(status, 404);
  assert.equal(body.error, 'NOT_FOUND');
});

test('路径指向文件而不是目录：400', async () => {
  const { status, body } = await list(ROOT_FILE);
  assert.equal(status, 400);
  assert.equal(body.error, 'BAD_REQUEST');
});

test('软链：按目标解析成真实路径，照样能列', async () => {
  const link = join(env.workspaceDir, 'outside-link');
  symlinkSync('/etc', link);

  const parentListing = await list(env.workspaceDir);
  const entry = parentListing.body.items.find((item: any) => item.name === 'outside-link');
  assert.equal(entry.type, 'dir', '软链目录按目标判成目录，否则整个工程点不进去');

  const { status, body } = await list(link);
  assert.equal(status, 200);
  assert.equal(body.path, realpathSync('/etc'));
});

/* ---------- /fs/read ---------- */

test('读文件：返回内容、绝对路径与元信息，BOM 被去掉', async () => {
  const { status, body } = await readFile(BOM_FILE);
  assert.equal(status, 200);
  assert.equal(body.path, realpathSync(BOM_FILE));
  assert.equal(body.name, 'bom.md');
  assert.equal(body.content, '# 带 BOM\n');
  assert.ok(body.size > 0);
  assert.notEqual(body.mtime, '');
});

test('读文件：~/ 会被展开成主目录', async () => {
  // 主目录在测试环境里就是临时 HOME；这里只验「不再被『必须是绝对路径』挡掉」
  const { status, body } = await readFile('~/does-not-exist-probe.md');
  assert.equal(status, 404);
  assert.equal(body.error, 'NOT_FOUND');
});

test('读文件：相对路径 400、不存在 404、目录 400', async () => {
  const relative = await readFile('docs/readme.md');
  assert.equal(relative.status, 400);
  assert.equal(relative.body.error, 'BAD_REQUEST');

  const missing = await readFile(join(env.workspaceDir, 'nope.md'));
  assert.equal(missing.status, 404);
  assert.equal(missing.body.error, 'NOT_FOUND');

  const directory = await readFile(DOCS);
  assert.equal(directory.status, 400);
  assert.equal(directory.body.error, 'BAD_REQUEST');
});

test('读文件：超过上限 413', async () => {
  const { status, body } = await readFile(LARGE_FILE);
  assert.equal(status, 413);
  assert.equal(body.error, 'PAYLOAD_TOO_LARGE');
});

test('读文件：含 NUL 的二进制 415', async () => {
  const { status, body } = await readFile(BINARY_FILE);
  assert.equal(status, 415);
  assert.equal(body.error, 'UNSUPPORTED_MEDIA_TYPE');
});

/* ---------- /fs/raw/* ---------- */

test('原始字节流：Content-Type 按扩展名，HTML 带 nosniff 与 CSP sandbox', async () => {
  const response = await fetch(rawUrl(HTML_FILE));
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type') ?? '', /^text\/html/);
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.match(response.headers.get('content-security-policy') ?? '', /sandbox/);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.match(await response.text(), /<p>hi<\/p>/);
});

test('原始字节流：中文与空格路径能往返', async () => {
  const response = await fetch(rawUrl(UNICODE_FILE));
  assert.equal(response.status, 200);
  assert.equal(await response.text(), '中文内容\n');
});

test('原始字节流：不存在 404、目录 400', async () => {
  const missing = await fetch(rawUrl(join(env.workspaceDir, 'nope.html')));
  assert.equal(missing.status, 404);

  const directory = await fetch(rawUrl(DOCS));
  assert.equal(directory.status, 400);
});

test('原始字节流：不受文本上限约束（413 只看 /fs/read）', async () => {
  const response = await fetch(rawUrl(LARGE_FILE));
  assert.equal(response.status, 200);
  assert.equal((await response.text()).length, MAX_TEXT_BYTES * 2);
});
