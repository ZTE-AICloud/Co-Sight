/**
 * 随包内置专家定义的启动同步：只补定义文件、不碰运行数据、内容相同不重写、源根缺失静默。
 *
 * 权威：server/docs/03-architecture/08-agent.md（内置专节）、src/shared/workspace/bundled-builtin.ts
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, statSync, utimesSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';

const env = prepareTestEnv('bundled-builtin');

const { syncBundledBuiltinAgents } = await import('../src/shared/workspace/bundled-builtin.js');

/** 定义根与生产布局逐字一致；源根用测试自己的临时目录，避免依赖仓库里真实随包的专家。 */
const DEFINITION_ROOT = join(env.home, 'smart-factory', 'builtin-agents');
const SOURCE_ROOT = join(env.home, 'bundled-source');

function writeFiles(root: string, files: Record<string, string>): void {
  for (const [name, content] of Object.entries(files)) {
    const path = join(root, name);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content);
  }
}

/** 写一颗源端专家目录；`agent: false` 用于造「缺清单」的坏目录。 */
function writeSourceExpert(id: string, files: Record<string, string>, agent = true): void {
  const dir = join(SOURCE_ROOT, id);
  mkdirSync(dir, { recursive: true });
  if (agent) writeFiles(dir, { 'agent.json': JSON.stringify({ name: id, description: '', tags: [], icon: '' }) });
  writeFiles(dir, files);
}

test('首次同步：定义文件（含 .claude）进定义根，源端运行数据目录不带过去', () => {
  writeSourceExpert('alpha', {
    'CLAUDE.md': '# alpha',
    '.claude/settings.json': '{"enabledPlugins":{}}',
    'workspace/notes.md': '不应被同步',
    'data/state.json': '{}',
  });

  const result = syncBundledBuiltinAgents(SOURCE_ROOT);

  assert.deepEqual(result.synced.map((item) => item.id), ['alpha']);
  assert.equal(result.skipped.length, 0);
  const target = join(DEFINITION_ROOT, 'alpha');
  assert.equal(readFileSync(join(target, 'agent.json'), 'utf8'), JSON.stringify({ name: 'alpha', description: '', tags: [], icon: '' }));
  assert.equal(readFileSync(join(target, 'CLAUDE.md'), 'utf8'), '# alpha');
  assert.equal(readFileSync(join(target, '.claude', 'settings.json'), 'utf8'), '{"enabledPlugins":{}}');
  assert.equal(existsSync(join(target, 'workspace')), false);
  assert.equal(existsSync(join(target, 'data')), false);
});

test('目标端已有的运行数据不覆盖也不删除', () => {
  const target = join(DEFINITION_ROOT, 'alpha');
  writeFiles(target, {
    'workspace/keep.md': '用户项目',
    'data/.env': 'SECRET=1',
    '.drive/executeState.json': '{"stage":"execute"}',
  });
  writeSourceExpert('alpha', { 'CLAUDE.md': '# alpha v2' });

  syncBundledBuiltinAgents(SOURCE_ROOT);

  assert.equal(readFileSync(join(target, 'workspace', 'keep.md'), 'utf8'), '用户项目');
  assert.equal(readFileSync(join(target, 'data', '.env'), 'utf8'), 'SECRET=1');
  assert.equal(readFileSync(join(target, '.drive', 'executeState.json'), 'utf8'), '{"stage":"execute"}');
  assert.equal(readFileSync(join(target, 'CLAUDE.md'), 'utf8'), '# alpha v2');
});

test('定义文件内容变了才重写；内容相同不动 mtime', () => {
  const target = join(DEFINITION_ROOT, 'beta');
  writeSourceExpert('beta', { 'CLAUDE.md': '# beta', 'agent.json': JSON.stringify({ name: 'beta', description: '', tags: [], icon: '' }) });
  syncBundledBuiltinAgents(SOURCE_ROOT);

  const past = new Date('2026-01-01T00:00:00.000Z');
  utimesSync(join(target, 'CLAUDE.md'), past, past);
  const again = syncBundledBuiltinAgents(SOURCE_ROOT);
  assert.equal(again.synced.find((item) => item.id === 'beta')?.files, 0);
  assert.ok(
    statSync(join(target, 'CLAUDE.md')).mtimeMs < Date.now() - 24 * 60 * 60 * 1000,
    '内容没变却被重写（mtime 应该是过去的时刻）',
  );

  writeSourceExpert('beta', { 'CLAUDE.md': '# beta v2' });
  const changed = syncBundledBuiltinAgents(SOURCE_ROOT);
  assert.equal(changed.synced.find((item) => item.id === 'beta')?.files, 1);
  assert.equal(readFileSync(join(target, 'CLAUDE.md'), 'utf8'), '# beta v2');
});

test('缺 agent.json / 非法 id / 隐藏目录都跳过，不建目标目录', () => {
  writeSourceExpert('no-manifest', { 'CLAUDE.md': '# 缺清单' }, false);
  writeSourceExpert('UPPER', { 'CLAUDE.md': '# 非法 id' });
  writeSourceExpert('.hidden', { 'CLAUDE.md': '# 隐藏' });

  const result = syncBundledBuiltinAgents(SOURCE_ROOT);

  assert.deepEqual(result.skipped, ['no-manifest']);
  for (const id of ['no-manifest', 'UPPER', '.hidden']) {
    assert.equal(existsSync(join(DEFINITION_ROOT, id)), false, `${id} 不该被同步`);
  }
});

test('源根不存在：静默返回空，不抛', () => {
  const result = syncBundledBuiltinAgents(join(env.home, 'no-such-source'));
  assert.deepEqual(result, { synced: [], skipped: [] });
});
