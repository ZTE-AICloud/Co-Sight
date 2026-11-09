import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, symlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { agentRootIn, seedAgent, seedPipelineState } from './helpers/agents.js';
import { startWorkspaceStub } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('artifact-api');
const stub = await startWorkspaceStub(env);

let api: TestApi;

const AGENT = 'art-demo';
const AGENT_AMBIGUOUS = 'art-ambiguous';
const AGENT_NO_VERSION = 'art-no-version';
const AGENT_NO_RUNTIME = 'art-no-runtime';

before(async () => {
  api = await startTestApi();
  for (const id of [AGENT, AGENT_AMBIGUOUS, AGENT_NO_VERSION, AGENT_NO_RUNTIME]) {
    await seedAgent(id);
    mkdirSync(join(agentRootIn(env.workspaceDir, id), 'development'), { recursive: true });
  }
  seed();
});

after(async () => {
  await api.close();
  await stub.close();
});

function write(path: string, content: string): void {
  mkdirSync(join(path, '..'), { recursive: true });
  writeFileSync(path, content);
}

function development(agentId = AGENT): string {
  return join(agentRootIn(env.workspaceDir, agentId), 'development');
}

/** 四个 stage 各自的样本；runtime 取最新 v2。 */
function seed(): void {
  write(join(development(), 'readme.md'), '你好\n');
  write(join(development(), 'notes', 'a.txt'), 'A');
  write(join(agentRootIn(env.workspaceDir, AGENT), 'preview', 'sandbox.txt'), 'preview');
  write(join(agentRootIn(env.workspaceDir, AGENT), 'evaluation', 'sandbox.txt'), 'evaluation');
  write(join(development(), 'output', 'agents', 'runtime-demo', 'v1', 'readme.md'), 'v1');
  write(join(development(), 'output', 'agents', 'runtime-demo', 'v2', 'readme.md'), 'v2');
  seedPipelineState(agentRootIn(env.workspaceDir, AGENT), 'runtime-demo');

  write(join(development(AGENT_AMBIGUOUS), 'output', 'agents', 'a', 'v1', 'x.txt'), 'x');
  write(join(development(AGENT_AMBIGUOUS), 'output', 'agents', 'b', 'v1', 'x.txt'), 'x');
  write(join(development(AGENT_NO_VERSION), 'output', 'agents', 'demo', 'draft', 'x.txt'), 'x');
}

test('artifacts/list：development 根、目录优先、文件项带体积与 mtime', async () => {
  const { status, body } = await api.get(`${API}/artifacts/list?stage=development&agentId=${AGENT}`);

  assert.equal(status, 200);
  assert.deepEqual(
    body.items.map((item: any) => item.name),
    ['.agent-genesis', 'notes', 'output', 'readme.md'],
  );
  const dirItem = body.items[0];
  const fileItem = body.items.find((item: any) => item.name === 'readme.md');
  assert.equal(dirItem.type, 'dir');
  assert.equal(dirItem.size, 0);
  assert.equal(fileItem.type, 'file');
  assert.equal(fileItem.size, 7, '「你好」为 6 字节 + 换行 1 字节');
  assert.ok(!Number.isNaN(Date.parse(fileItem.mtime)), `mtime 应为 ISO 串：${fileItem.mtime}`);
  assert.equal(body.total, 4);

  const nested = await api.get(`${API}/artifacts/list?stage=development&agentId=${AGENT}&path=notes`);
  assert.deepEqual(nested.body.items.map((item: any) => item.name), ['a.txt']);
});

test('preview / evaluation 各看各的目录；runtime 根是最新 vN 产物目录', async () => {
  const preview = await api.get(`${API}/artifacts/list?stage=preview&agentId=${AGENT}`);
  assert.deepEqual(preview.body.items.map((item: any) => item.name), ['sandbox.txt']);

  const evaluation = await api.get(`${API}/artifacts/file?stage=evaluation&agentId=${AGENT}&path=sandbox.txt`);
  assert.equal(evaluation.status, 200);
  assert.equal(evaluation.body.content, 'evaluation');

  const runtime = await api.get(`${API}/artifacts/file?stage=runtime&agentId=${AGENT}&path=readme.md`);
  assert.equal(runtime.status, 200);
  assert.equal(runtime.body.content, 'v2', 'runtime 根指向最新版本');
});

test('artifacts/file：读文本文件正文；目录与不存在都给 404，缺 path 400', async () => {
  const { status, body } = await api.get(`${API}/artifacts/file?stage=development&agentId=${AGENT}&path=readme.md`);
  assert.equal(status, 200);
  assert.equal(body.name, 'readme.md');
  assert.equal(body.content, '你好\n');
  assert.equal(body.size, 7);

  assert.equal((await api.get(`${API}/artifacts/file?stage=development&agentId=${AGENT}&path=missing.txt`)).status, 404);
  assert.equal((await api.get(`${API}/artifacts/file?stage=development&agentId=${AGENT}&path=notes`)).status, 404);
  assert.equal((await api.get(`${API}/artifacts/file?stage=development&agentId=${AGENT}`)).status, 400);
});

test('runtime 候选缺失 404；多子目录或无 v* 版本 409；未知 agent 404', async () => {
  assert.equal((await api.get(`${API}/artifacts/list?stage=runtime&agentId=${AGENT_NO_RUNTIME}`)).status, 404);

  const ambiguous = await api.get(`${API}/artifacts/list?stage=runtime&agentId=${AGENT_AMBIGUOUS}`);
  assert.equal(ambiguous.status, 409);
  assert.equal(ambiguous.body.error, 'CONFLICT');

  const noVersion = await api.get(`${API}/artifacts/list?stage=runtime&agentId=${AGENT_NO_VERSION}`);
  assert.equal(noVersion.status, 409);

  const unknown = await api.get(`${API}/artifacts/list?stage=development&agentId=art-absent`);
  assert.equal(unknown.status, 404);
});

test('artifacts/list：未物化的沙箱是 404，stage / agentId 非法 400', async () => {
  assert.equal((await api.get(`${API}/artifacts/list?stage=development&agentId=${AGENT}&path=no-such-dir`)).status, 404);
  assert.equal((await api.get(`${API}/artifacts/list?stage=preview&agentId=${AGENT_NO_RUNTIME}`)).status, 404, '预览从未物化');
  assert.equal((await api.get(`${API}/artifacts/list?stage=staging&agentId=${AGENT}&path=readme.md`)).status, 400);
  assert.equal((await api.get(`${API}/artifacts/list?stage=development&agentId=Bad&path=readme.md`)).status, 400);
});

test('artifacts/download：attachment 附件头 + 原始流内容', async () => {
  const response = await fetch(`${api.base}${API}/artifacts/download?stage=development&agentId=${AGENT}&path=readme.md`);

  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-disposition') ?? '', /attachment;\s*filename="?readme\.md"?/);
  assert.equal(await response.text(), '你好\n');
});

test('symlink 逃出 stage 根一律 400：读文件、下载与按目录列举都拒绝', { skip: process.platform === 'win32' }, async () => {
  const outsideFile = join(env.home, 'outside-secret.txt');
  const outsideDir = join(env.home, 'outside-dir');
  writeFileSync(outsideFile, 'outside');
  mkdirSync(outsideDir, { recursive: true });
  writeFileSync(join(outsideDir, 'leak.txt'), 'leak');
  symlinkSync(outsideFile, join(development(), 'escape.txt'));
  symlinkSync(outsideDir, join(development(), 'escape-dir'));

  const listRoot = await api.get(`${API}/artifacts/list?stage=development&agentId=${AGENT}`);
  assert.equal(listRoot.status, 200);
  assert.equal(listRoot.body.items.find((item: any) => item.name === 'escape.txt').type, 'file');

  for (const target of ['escape.txt', 'escape-dir/leak.txt']) {
    const file = await api.get(`${API}/artifacts/file?stage=development&agentId=${AGENT}&path=${encodeURIComponent(target)}`);
    assert.equal(file.status, 400, `file 应拒绝 symlink 逃逸 ${target}`);
    assert.equal(file.body.error, 'BAD_REQUEST');

    const download = await api.get(`${API}/artifacts/download?stage=development&agentId=${AGENT}&path=${encodeURIComponent(target)}`);
    assert.equal(download.status, 400, `download 应拒绝 symlink 逃逸 ${target}`);
  }

  const listThroughLink = await api.get(`${API}/artifacts/list?stage=development&agentId=${AGENT}&path=escape-dir`);
  assert.equal(listThroughLink.status, 400);
  assert.equal(listThroughLink.body.error, 'BAD_REQUEST');
});

test('路径逃逸与非法段一律 400：.. / 绝对路径 / 空段 / 反斜杠 / NUL', async () => {
  const badPaths = ['..', '../etc/passwd', `${AGENT}/../../etc/passwd`, '/etc/passwd', 'notes//a.txt', 'notes\\a.txt', 'a\u0000b'];

  for (const bad of badPaths) {
    const escaped = encodeURIComponent(bad);
    const list = await api.get(`${API}/artifacts/list?stage=development&agentId=${AGENT}&path=${escaped}`);
    assert.equal(list.status, 400, `list 应拒绝 path=${JSON.stringify(bad)}`);
    assert.equal(list.body.error, 'BAD_REQUEST');

    const file = await api.get(`${API}/artifacts/file?stage=development&agentId=${AGENT}&path=${escaped}`);
    assert.equal(file.status, 400, `file 应拒绝 path=${JSON.stringify(bad)}`);

    const download = await api.get(`${API}/artifacts/download?stage=development&agentId=${AGENT}&path=${escaped}`);
    assert.equal(download.status, 400, `download 应拒绝 path=${JSON.stringify(bad)}`);
  }
});
