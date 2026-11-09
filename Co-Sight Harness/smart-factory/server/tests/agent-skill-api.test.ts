import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { agentRootIn, seedAgent, seedPipelineState } from './helpers/agents.js';
import { startWorkspaceStub } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

/**
 * 智能体技能装配（2026-10-26 最小模型）：
 * 装配 = 把库技能的选定版本整拷进 `<product>/.claude/skills/<目录名>/`，
 * 不落库、不记来源、不改 CLAUDE.md；前置门禁 = user 来源 + 无活跃 run + 产物 completed。
 */

const env = prepareTestEnv('agent-skill-api');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');

const libraryRoot = join(env.home, 'smart-factory', 'skill-workshop', 'output', 'skills');

let api: TestApi;

/** 库技能：`<name>/<version>/SKILL.md`；描述带上版本号，便于断言复制的是哪一版。 */
function seedLibrarySkill(name: string, versions: string[], label = name, versionField = ''): void {
  for (const version of versions) {
    const dir = join(libraryRoot, name, version);
    mkdirSync(dir, { recursive: true });
    const frontmatter = [
      '---',
      `name: ${name}`,
      `description: ${label}-${version}`,
      ...(versionField === '' ? [] : [`version: "${versionField}"`]),
      '---',
      '',
      '正文',
      '',
    ].join('\n');
    writeFileSync(join(dir, 'SKILL.md'), frontmatter);
  }
}

/** 就绪产物：`<agentRoot>/development/output/agents/<agentName>/<version>/` + COMPLETED 状态。 */
function seedProduct(agentId: string, agentName = 'demo', version = 'v1'): string {
  const root = agentRootIn(env.workspaceDir, agentId);
  const product = join(root, 'development', 'output', 'agents', agentName, version);
  mkdirSync(join(product, '.claude', 'skills'), { recursive: true });
  writeFileSync(join(product, 'CLAUDE.md'), '# demo\n');
  seedPipelineState(root, agentName);
  return product;
}

before(async () => {
  seedLibrarySkill('report-gen', ['v1', 'v3'], '周报', '1.0');
  seedLibrarySkill('weather-query', ['v1'], '天气', '1.0');
  // 目录存在但没有 SKILL.md：不是可运行的技能
  mkdirSync(join(libraryRoot, 'broken', 'v1'), { recursive: true });

  await seedAgent('skill-agt', '技能智能体');
  await seedAgent('skill-draft', '草稿智能体');
  seedProduct('skill-agt');

  // 内置智能体：定义目录只读，装配 / 删除一律 409
  await prisma.agent.create({
    data: {
      id: 'builtin-skill',
      workspaceId: null,
      name: '内置技能智能体',
      source: 'builtin',
    },
  });

  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
});

test('未开始生成：200 + ready=false，不报错', async () => {
  const { status, body } = await api.get(`${API}/agents/skill-draft/skills`);
  assert.equal(status, 200);
  assert.equal(body.ready, false);
  assert.equal(body.product, null);
  assert.deepEqual(body.items, []);
  assert.ok(body.reasons.length > 0);
});

test('就绪产物：ready=true，清单来自 .claude/skills', async () => {
  const { status, body } = await api.get(`${API}/agents/skill-agt/skills`);
  assert.equal(status, 200);
  assert.equal(body.ready, true);
  assert.equal(body.product.agentName, 'demo');
  assert.equal(body.product.version, 'v1');
  assert.deepEqual(body.items, []);
});

test('装配：复制最新 vN 到产物，版本层被剥掉', async () => {
  const product = join(agentRootIn(env.workspaceDir, 'skill-agt'), 'development', 'output', 'agents', 'demo', 'v1');
  const { status, body } = await api.post(`${API}/agents/skill-agt/skills`, {
    path: join(libraryRoot, 'report-gen'),
  });
  assert.equal(status, 200);
  assert.equal(body.item.name, 'report-gen');
  assert.equal(body.item.displayName, 'report-gen');
  assert.equal(body.item.version, '1.0');
  assert.equal(body.item.description, '周报-v3');

  const installed = join(product, '.claude', 'skills', 'report-gen');
  assert.equal(readFileSync(join(installed, 'SKILL.md'), 'utf8').includes('周报-v3'), true);
  assert.equal(existsSync(join(installed, 'v3')), false, '复制的是版本目录内容，不是版本目录本身');
});

test('装配后清单可读', async () => {
  const { status, body } = await api.get(`${API}/agents/skill-agt/skills`);
  assert.equal(status, 200);
  const names = body.items.map((item: { name: string }) => item.name);
  assert.deepEqual(names, ['report-gen']);
  assert.equal(body.items[0].description, '周报-v3');
});

test('同名技能：409，不覆盖已有内容', async () => {
  const { status, body } = await api.post(`${API}/agents/skill-agt/skills`, {
    path: join(libraryRoot, 'report-gen'),
  });
  assert.equal(status, 409);
  assert.equal(body.messageKey, 'error.conflict.skill_exists');
});

test('显式 version：只复制指定版本；非法 / 不存在的版本 400', async () => {
  const ok = await api.post(`${API}/agents/skill-agt/skills`, {
    path: join(libraryRoot, 'report-gen'),
    version: 'v1',
  });
  // report-gen 已经装过 → 同名 409；换个名字验证 version 生效
  assert.equal(ok.status, 409);

  const explicit = await api.post(`${API}/agents/skill-agt/skills`, {
    path: join(libraryRoot, 'weather-query'),
    version: 'v1',
  });
  assert.equal(explicit.status, 200);
  assert.equal(explicit.body.item.name, 'weather-query');

  const missing = await api.post(`${API}/agents/skill-agt/skills`, {
    path: join(libraryRoot, 'weather-query'),
    version: 'v9',
  });
  assert.equal(missing.status, 400);

  const malformed = await api.post(`${API}/agents/skill-agt/skills`, {
    path: join(libraryRoot, 'weather-query'),
    version: 'latest',
  });
  assert.equal(malformed.status, 400);
});

test('来源校验：相对路径 / 不是目录 / 缺 SKILL.md / 不存在', async () => {
  const relative = await api.post(`${API}/agents/skill-agt/skills`, { path: 'relative/skill' });
  assert.equal(relative.status, 400);

  const file = await api.post(`${API}/agents/skill-agt/skills`, {
    path: join(libraryRoot, 'report-gen', 'v1', 'SKILL.md'),
  });
  assert.equal(file.status, 400);

  const broken = await api.post(`${API}/agents/skill-agt/skills`, { path: join(libraryRoot, 'broken') });
  assert.equal(broken.status, 400);
  assert.equal(broken.body.messageKey, 'error.bad_request.skill_md_missing');

  const absent = await api.post(`${API}/agents/skill-agt/skills`, {
    path: join(env.home, 'no-such-skill'),
  });
  assert.equal(absent.status, 404);
});

test('产物未就绪：装配 409', async () => {
  const { status } = await api.post(`${API}/agents/skill-draft/skills`, {
    path: join(libraryRoot, 'report-gen'),
  });
  assert.equal(status, 409);
});

test('内置智能体：清单与装配都 409', async () => {
  const listed = await api.get(`${API}/agents/builtin-skill/skills`);
  assert.equal(listed.status, 409);
  const attached = await api.post(`${API}/agents/builtin-skill/skills`, {
    path: join(libraryRoot, 'report-gen'),
  });
  assert.equal(attached.status, 409);
  assert.equal(attached.body.messageKey, 'error.conflict.builtin_agent');
});

test('有活跃 run：装配 / 删除 409，清单按未就绪处理', async () => {
  const { instancesRepo } = await import('../src/shared/store/instances.repo.js');
  const instance = await instancesRepo.getOrCreate('skill-agt', 'development');
  await prisma.run.create({
    data: { id: 'run-active', sessionId: 'session-active', instanceId: instance.id, stage: 'development', status: 'running' },
  });

  try {
    const attached = await api.post(`${API}/agents/skill-agt/skills`, {
      path: join(libraryRoot, 'report-gen'),
      version: 'v1',
    });
    assert.equal(attached.status, 409);
    assert.equal(attached.body.messageKey, 'error.conflict.active_run');

    const removed = await api.post(`${API}/agents/skill-agt/skills/remove`, { name: 'weather-query' });
    assert.equal(removed.status, 409);

    const listed = await api.get(`${API}/agents/skill-agt/skills`);
    assert.equal(listed.status, 200);
    assert.equal(listed.body.ready, false, 'development 有活跃 run 时不信任旧产物');
  } finally {
    await prisma.run.delete({ where: { id: 'run-active' } });
  }
});

test('删除：移除产物里的技能目录；重复删除 404', async () => {
  const product = join(agentRootIn(env.workspaceDir, 'skill-agt'), 'development', 'output', 'agents', 'demo', 'v1');
  const removed = await api.post(`${API}/agents/skill-agt/skills/remove`, { name: 'report-gen' });
  assert.equal(removed.status, 200);
  assert.equal(removed.body.removed, 'report-gen');
  assert.equal(existsSync(join(product, '.claude', 'skills', 'report-gen')), false);

  const again = await api.post(`${API}/agents/skill-agt/skills/remove`, { name: 'report-gen' });
  assert.equal(again.status, 404);

  const listed = await api.get(`${API}/agents/skill-agt/skills`);
  const names = listed.body.items.map((item: { name: string }) => item.name);
  assert.deepEqual(names, ['weather-query'], '另一个已装配技能不受影响');
});

test('删除名非法：400（不允许路径段）', async () => {
  const { status } = await api.post(`${API}/agents/skill-agt/skills/remove`, { name: '../weather-query' });
  assert.equal(status, 400);
});
