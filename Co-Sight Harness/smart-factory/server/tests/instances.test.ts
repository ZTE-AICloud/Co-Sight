import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, rmSync } from 'node:fs';
import { join, sep } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';

const env = prepareTestEnv('instances');

const { prisma } = await import('../src/shared/prisma/client.js');
const { instancesRepo } = await import('../src/shared/store/instances.repo.js');
const { agentRoot, assertAgentId, stageDir, stateDir } = await import('../src/shared/workspace/dir-resolver.js');

before(async () => {
  await prisma.instance.deleteMany();
});

after(async () => {
  await prisma.$disconnect();
});

test('getOrCreate 幂等：同一 (agentId, stage) 两次拿到同一行', async () => {
  const a = await instancesRepo.getOrCreate('demo', 'development');
  const b = await instancesRepo.getOrCreate('demo', 'development');

  assert.equal(a.id, b.id);
  assert.equal(await prisma.instance.count({ where: { agentId: 'demo' } }), 1);
});

test('getOrCreate 并发：唯一约束兜底，只落一行', async () => {
  const results = await Promise.all([
    instancesRepo.getOrCreate('race', 'development'),
    instancesRepo.getOrCreate('race', 'development'),
  ]);

  assert.equal(results[0]!.id, results[1]!.id);
  assert.equal(await prisma.instance.count({ where: { agentId: 'race' } }), 1);
});

test('getOrCreate 按 stage 区分：同一智能体的开发与预览是两个实例', async () => {
  const development = await instancesRepo.getOrCreate('two-stage', 'development');
  const preview = await instancesRepo.getOrCreate('two-stage', 'preview');

  assert.notEqual(development.id, preview.id);
  assert.equal(development.engine, 'fake');
});

test('getOrCreate 已有行时不覆盖 engine：配置改了仍是首次写入值', async () => {
  const { config } = await import('../src/config/index.js');
  const mutable = config as { engine: string };
  const original = mutable.engine;

  const first = await instancesRepo.getOrCreate('engine-lock', 'development');
  assert.equal(first.engine, original);

  mutable.engine = 'claude-cli';
  try {
    const again = await instancesRepo.getOrCreate('engine-lock', 'development');
    assert.equal(again.id, first.id);
    assert.equal(again.engine, original);

    const rows = await prisma.instance.findMany({ where: { agentId: 'engine-lock' } });
    assert.equal(rows.length, 1);
    assert.equal(rows[0]!.engine, original);
  } finally {
    mutable.engine = original;
  }
});

test('agentId 形态校验：拒绝空串、路径分隔、穿越与超长', () => {
  for (const bad of ['', 'a/b', '../evil', '.hidden', '-lead', 'a'.repeat(65)]) {
    assert.throws(() => assertAgentId(bad), /形态非法/, `应拒绝 ${JSON.stringify(bad)}`);
  }
  for (const ok of ['a', 'demo', 'weather-agent', 'a.b_c-1']) {
    assert.doesNotThrow(() => assertAgentId(ok));
  }
});

test('agentId 形态收紧：拒绝大写、Windows 保留名与结尾点', () => {
  for (const bad of ['Bad', 'CON', 'con.txt', 'abc.', 'a.b.']) {
    assert.throws(() => assertAgentId(bad), /agentId/, `应拒绝 ${JSON.stringify(bad)}`);
  }
  for (const ok of ['ok-name', 'console', 'com10', 'a.b_c-1']) {
    assert.doesNotThrow(() => assertAgentId(ok), `应放行 ${JSON.stringify(ok)}`);
  }
});

test('目录映射：agentRoot 在工作区下，四个 stage 目录互不包含', () => {
  const root = agentRoot(env.workspaceDir, 'mapper');
  assert.equal(root, join(env.workspaceDir, '.smart-factory', 'agents', 'mapper'));

  const development = stageDir(root, 'development');
  const preview = stageDir(root, 'preview');
  const evaluation = stageDir(root, 'evaluation');
  assert.equal(development, join(root, 'development'));
  assert.equal(preview, join(root, 'preview'));
  assert.equal(evaluation, join(root, 'evaluation'));
  assert.equal(stateDir(root), join(root, '.state'));

  for (const [a, b] of [
    [development, preview],
    [development, evaluation],
    [preview, evaluation],
  ] as const) {
    assert.ok(!a.startsWith(b + sep));
    assert.ok(!b.startsWith(a + sep));
  }
});

test('目录映射是纯函数：只拼路径，不建目录', () => {
  const dir = stageDir(agentRoot(env.workspaceDir, 'mk'), 'development');
  rmSync(dir, { recursive: true, force: true });

  assert.equal(stageDir(agentRoot(env.workspaceDir, 'mk'), 'development'), dir);
  assert.ok(!existsSync(dir));
});

test('getOrCreateByCwd 幂等：同一 cwd 两次拿到同一行', async () => {
  const cwd = join(env.home, 'workshop-idem');
  const a = await instancesRepo.getOrCreateByCwd(cwd, 'development');
  const b = await instancesRepo.getOrCreateByCwd(cwd, 'development');

  assert.equal(a.id, b.id);
  assert.equal(a.agentId, null);
  assert.equal(a.stage, 'development', '目录实例的阶段是它的工作阶段（工坊 = 开发）');
  assert.equal(a.cwd, cwd);
});

test('getOrCreateByCwd 并发：唯一约束兜底，只落一行', async () => {
  const cwd = join(env.home, 'workshop-race');
  const results = await Promise.all([
    instancesRepo.getOrCreateByCwd(cwd, 'development'),
    instancesRepo.getOrCreateByCwd(cwd, 'development'),
  ]);

  assert.equal(results[0]!.id, results[1]!.id);
  assert.equal(await prisma.instance.count({ where: { cwd } }), 1);
});

test('同一 cwd 的两种用途是两个实例：工坊 development、自由对话 runtime', async () => {
  const cwd = join(env.home, 'shared-use');
  const workshop = await instancesRepo.getOrCreateByCwd(cwd, 'development');
  const chat = await instancesRepo.getOrCreateByCwd(cwd, 'runtime');

  assert.notEqual(workshop.id, chat.id);
  assert.equal(workshop.stage, 'development');
  assert.equal(chat.stage, 'runtime');
  assert.equal(await prisma.instance.count({ where: { cwd } }), 2, '(cwd, stage) 才是目录实例的身份');
});

test('getOrCreate 不写 cwd：智能体实例 cwd 为 null', async () => {
  await instancesRepo.getOrCreate('cwdless', 'development');

  const row = await prisma.instance.findUnique({
    where: { agentId_stage: { agentId: 'cwdless', stage: 'development' } },
  });
  assert.ok(row);
  assert.equal(row.cwd, null);
});

test('目录实例不占 (agentId, stage) 键：与智能体实例互不干扰', async () => {
  // 先清掉前面的用例落下的目录实例，让计数断言只反映本用例
  await prisma.instance.deleteMany({ where: { agentId: null } });

  const cwd = join(env.home, 'workshop-key');
  const dirInstance = await instancesRepo.getOrCreateByCwd(cwd, 'development');

  assert.equal(await prisma.instance.count({ where: { agentId: null } }), 1);

  // 同一 stage 的智能体实例照常创建，与目录实例互不影响
  const agentInstance = await instancesRepo.getOrCreate('dir-less', 'development');
  assert.notEqual(agentInstance.id, dirInstance.id);
});
