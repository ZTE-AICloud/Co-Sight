import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { agentRootIn, seedAgent, seedPipelineState } from './helpers/agents.js';
import { startWorkspaceStub } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

/**
 * 智能体详情的**可执行**清单（04-api/4.14）：
 * 只看 `runtimeDir` 下的 `.claude/skills` 与 `.claude/commands`，与 runtime 起跑门禁同源；
 * 产物未就绪 / 未生成时两项为空，列表与 create / update 不带这两项。
 */

const env = prepareTestEnv('agent-executables');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');

let api: TestApi;

/** 就绪产物：`<agentRoot>/development/output/agents/<agentName>/<version>/` + COMPLETED 状态。 */
function seedProduct(agentId: string, agentName = 'demo', version = 'v1'): string {
  const root = agentRootIn(env.workspaceDir, agentId);
  const product = join(root, 'development', 'output', 'agents', agentName, version);
  mkdirSync(join(product, '.claude', 'skills'), { recursive: true });
  writeFileSync(join(product, 'CLAUDE.md'), '# demo\n');
  seedPipelineState(root, agentName);
  return product;
}

function writeSkill(product: string, dirName: string, frontmatter: string): string {
  const dir = join(product, '.claude', 'skills', dirName);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'SKILL.md'), `---\n${frontmatter}---\n\n正文\n`);
  return dir;
}

function writeCommand(product: string, relativePath: string, head = ''): string {
  const file = join(product, '.claude', 'commands', relativePath);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, head === '' ? '执行一件事。\n' : `---\n${head}---\n\n执行一件事。\n`);
  return file;
}

before(async () => {
  await seedAgent('exec-ready', '就绪可执行');
  const product = seedProduct('exec-ready');
  writeSkill(product, 'beta', 'name: Beta 技能\ndescription: 第二个技能\nversion: "1.1"\n');
  writeSkill(product, 'alpha', 'name: Alpha Skill\ndescription: 第一个技能\nversion: "2.0"\n');
  // 缺 SKILL.md 的不是可执行技能（管理面 GET /skills 会列出来删，详情不列）
  mkdirSync(join(product, '.claude', 'skills', 'broken'), { recursive: true });
  writeFileSync(join(product, '.claude', 'skills', 'broken', 'notes.txt'), 'x\n');
  // 隐藏目录引擎不发现
  writeSkill(product, '.hidden', 'name: Hidden\n');

  writeCommand(product, 'build.md', 'description: 构建项目\n');
  writeCommand(product, 'deploy.md'); // 无 frontmatter：description 为空串
  writeCommand(product, 'ci/build.md', 'description: 子目录里的同名命令（被去重）\n');
  writeCommand(product, 'ci/test.md', 'description: 跑测试\n');
  writeCommand(product, 'nested/deep/run.md', 'description: 深层命令\n');
  writeCommand(product, 'notes.txt'); // 非 .md 不列
  writeCommand(product, '.hidden.md'); // 隐藏文件不列

  await seedAgent('exec-fresh', '无产物可执行');

  // 内置智能体：定义目录就是 runtimeDir，可执行清单照扫（与 /skills 的 409 不矛盾）
  const builtinDir = join(env.home, 'smart-factory', 'builtin-agents', 'exec-builtin');
  const builtinSkill = join(builtinDir, '.claude', 'skills', 'builtin-skill');
  mkdirSync(builtinSkill, { recursive: true });
  writeFileSync(join(builtinSkill, 'SKILL.md'), '---\nname: 内置技能\n---\n\n正文\n');
  writeFileSync(join(builtinDir, 'CLAUDE.md'), '# builtin\n');
  await prisma.agent.create({
    data: { id: 'exec-builtin', workspaceId: null, name: '内置可执行', source: 'builtin' },
  });

  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
});

test('detail：未就绪 / 没有产物时两项都是空数组；list 不带这两项', async () => {
  const fresh = await api.get(`${API}/agents/exec-fresh`);
  assert.equal(fresh.status, 200);
  assert.equal(fresh.body.runtimeDir, null);
  assert.deepEqual(fresh.body.skills, []);
  assert.deepEqual(fresh.body.commands, []);

  const listed = await api.get(`${API}/agents?keyword=无产物可执行`);
  assert.equal(listed.body.items.length, 1);
  // 列表一页 200 行，不扫盘：可执行清单是详情专属
  assert.equal('skills' in listed.body.items[0], false);
  assert.equal('commands' in listed.body.items[0], false);
});

test('detail：就绪产物按 .claude 扫出可执行技能；缺 SKILL.md / 隐藏目录不算', async () => {
  const res = await api.get(`${API}/agents/exec-ready`);
  assert.equal(res.status, 200);

  const root = agentRootIn(env.workspaceDir, 'exec-ready');
  const product = join(root, 'development', 'output', 'agents', 'demo', 'v1');
  assert.equal(res.body.runtimeDir, product);

  assert.deepEqual(res.body.skills.map((item: { name: string }) => item.name), ['alpha', 'beta']);
  const alpha = res.body.skills[0];
  assert.equal(alpha.displayName, 'Alpha Skill');
  assert.equal(alpha.description, '第一个技能');
  assert.equal(alpha.version, '2.0');
  assert.equal(alpha.path, join(product, '.claude', 'skills', 'alpha'));
  assert.match(alpha.updatedAt, /^\d{4}-\d{2}-\d{2}T/);

  // 没有 SKILL.md 的 broken / 点开头的 .hidden 都不在清单里
  const names = res.body.skills.map((item: { name: string }) => item.name);
  assert.equal(names.includes('broken'), false);
  assert.equal(names.includes('.hidden'), false);
});

test('detail：命令递归扫子目录；命令名只取文件名，同名按路径序去重', async () => {
  const res = await api.get(`${API}/agents/exec-ready`);

  assert.deepEqual(
    res.body.commands.map((item: { name: string }) => item.name),
    ['build', 'deploy', 'run', 'test'],
  );
  assert.deepEqual(
    res.body.commands.map((item: { name: string }) => item.namespace),
    ['', '', 'nested/deep', 'ci'],
  );

  const build = res.body.commands[0];
  // 顶层 build.md 与 ci/build.md 同名：按相对路径升序保留顶层那份
  assert.equal(build.namespace, '');
  assert.equal(build.description, '构建项目');
  assert.equal(build.path, join(agentRootIn(env.workspaceDir, 'exec-ready'), 'development', 'output', 'agents', 'demo', 'v1', '.claude', 'commands', 'build.md'));
  assert.match(build.updatedAt, /^\d{4}-\d{2}-\d{2}T/);

  // 没有 frontmatter 的命令照样可执行，只是没有说明
  assert.equal(res.body.commands[1].description, '');
});

test('detail：内置智能体的定义目录就是 runtimeDir，技能照扫；装配端点仍是 409', async () => {
  const res = await api.get(`${API}/agents/exec-builtin`);
  assert.equal(res.status, 200);

  const builtinDir = join(env.home, 'smart-factory', 'builtin-agents', 'exec-builtin');
  assert.equal(res.body.runtimeDir, builtinDir);
  assert.equal(res.body.status, 'completed', '内置智能体开箱即用，状态恒为 completed');
  assert.deepEqual(res.body.skills.map((item: { name: string }) => item.name), ['builtin-skill']);
  assert.deepEqual(res.body.commands, []);

  // 可执行是只读视图；装配 / 清单仍是产物专属入口，内置只读
  const skills = await api.get(`${API}/agents/exec-builtin/skills`);
  assert.equal(skills.status, 409);
});

test('detail：门禁翻 FAIL → runtimeDir 回 null，可执行清单跟着清空', async () => {
  const root = agentRootIn(env.workspaceDir, 'exec-ready');
  const gate = join(root, 'development', '.agent-genesis', 'work', 'demo', 'gate-results', 'step-4-implementation.json');
  writeFileSync(gate, JSON.stringify({ verdict: 'FAIL', concerns: [] }));

  const res = await api.get(`${API}/agents/exec-ready`);
  assert.equal(res.body.runtimeDir, null);
  assert.equal(res.body.status, 'failed');
  assert.deepEqual(res.body.skills, []);
  assert.deepEqual(res.body.commands, []);
});
