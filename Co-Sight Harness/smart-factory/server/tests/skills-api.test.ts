import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, utimesSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { prepareTestEnv } from './helpers/test-db.js';
import { agentRootIn, seedAgents, TEST_WORKSPACE_ID } from './helpers/agents.js';
import { startWorkspaceStub } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

const env = prepareTestEnv('skills-api');
const stub = await startWorkspaceStub(env);

const { prisma } = await import('../src/shared/prisma/client.js');

const serverDir = fileURLToPath(new URL('..', import.meta.url));

/** 评审版布局（10-skill-library.md §2）：工坊 cwd 是 skill-workshop/，库在其 output/skills/ 下。 */
const skillsRoot = join(env.home, 'smart-factory', 'skill-workshop');
const libraryRoot = join(skillsRoot, 'output', 'skills');

let api: TestApi;

/** 建一个库内技能：`<name>/<version>/SKILL.md`，并固定技能目录 mtime 供排序断言。 */
function seedLibrarySkill(
  name: string,
  opts: { skillMd?: string; versions?: string[]; mtime?: Date } = {},
): void {
  for (const version of opts.versions ?? ['v1']) {
    const dir = join(libraryRoot, name, version);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, 'SKILL.md'), opts.skillMd ?? `---\nname: ${name}\ndescription: ${name} 的描述\n---\n\n正文\n`);
  }
  if (opts.mtime) utimesSync(join(libraryRoot, name), opts.mtime, opts.mtime);
}

/** 在子进程里加载 config 并回传 skillsRoot：config 在 import 时读环境，进程内只能测一次。 */
function probeSkillsRoot(overrides: Record<string, string | undefined> = {}): string {
  const probe = "const m = await import('./src/config/index.js'); process.stdout.write(m.config.skillsRoot);";
  const merged: NodeJS.ProcessEnv = {
    ...process.env,
    COSIGHT_HOME: env.home,
    DOTENV_CONFIG_PATH: join(serverDir, '.env.probe-absent'),
    DOTENV_CONFIG_QUIET: 'true',
    ...overrides,
  };
  if (merged.SKILLS_ROOT === undefined) delete merged.SKILLS_ROOT;
  return execFileSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', probe], {
    cwd: serverDir,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    env: merged,
  });
}

before(async () => {
  // 库内技能：mtime 各不相同，用于断言 updatedAt 倒序
  seedLibrarySkill('lib-alpha', { mtime: new Date('2026-01-01T00:00:02.000Z') });
  seedLibrarySkill('lib-beta', { mtime: new Date('2026-01-01T00:00:05.000Z') });
  seedLibrarySkill('lib-bad', { skillMd: 'not: [yaml', mtime: new Date('2026-01-01T00:00:01.000Z') });
  seedLibrarySkill('lib-quotes', {
    skillMd: `---\nname: "带引号"\ndescription: '单引号描述'\n---\n\n正文\n`,
    mtime: new Date('2026-01-01T00:00:03.000Z'),
  });
  seedLibrarySkill('lib-vers', { versions: ['v1', 'v10', 'v2'], mtime: new Date('2026-01-01T00:00:04.000Z') });
  // 块标量 description：`>-` 折行 / `|` 保留换行（真实技能里常见 `description: >-`）
  seedLibrarySkill('lib-folded', {
    skillMd: `---\nname: lib-folded\ndescription: >-\n  折叠块写的第一行，\n  第二行。\n---\n\n正文\n`,
    mtime: new Date('2026-01-01T00:00:08.000Z'),
  });
  seedLibrarySkill('lib-literal', {
    skillMd: `---\nname: lib-literal\ndescription: |\n  第一行\n  第二行\n---\n\n正文\n`,
    mtime: new Date('2026-01-01T00:00:07.000Z'),
  });

  // skill-foundry 的过程目录：在 cwd 下但不在 output/skills 里，不进扫描面
  const ghostDir = join(skillsRoot, '.agent-genesis', 'work', 'ghost');
  mkdirSync(ghostDir, { recursive: true });
  writeFileSync(join(ghostDir, 'SKILL.md'), '---\nname: ghost\n---\n');

  // 智能体技能：与库内同名技能各出一项
  await seedAgents('skill-agt', 'skill-empty');
  const agentSkillDir = join(agentRootIn(env.workspaceDir, 'skill-agt'), 'development', 'output', 'skills', 'shared-name', 'v1');
  mkdirSync(agentSkillDir, { recursive: true });
  writeFileSync(join(agentSkillDir, 'SKILL.md'), '---\nname: shared-name\ndescription: agent 版描述\n---\n');
  seedLibrarySkill('shared-name', { skillMd: '---\nname: shared-name\ndescription: library 版描述\n---\n', mtime: new Date('2026-01-01T00:00:06.000Z') });

  // 产物自带技能：development/output/agents/<name>/<vN>/.claude/skills/*
  // v1 放一个旧技能、v10 放当前技能 —— 只有最新 vN 进扫描面
  const productRoot = join(
    agentRootIn(env.workspaceDir, 'skill-empty'),
    'development',
    'output',
    'agents',
    'built-agent',
  );
  for (const [version, skillName] of [
    ['v1', 'bundled-old'],
    ['v10', 'bundled-skill'],
  ] as const) {
    const dir = join(productRoot, version, '.claude', 'skills', skillName);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, 'SKILL.md'), `---\nname: ${skillName}\ndescription: ${skillName} 的描述\n---\n`);
  }
  // preview 是从产物整拷的物化副本：不扫，否则同一技能会出现两次
  const previewDir = join(
    agentRootIn(env.workspaceDir, 'skill-empty'),
    'preview',
    '.claude',
    'skills',
    'preview-only',
  );
  mkdirSync(previewDir, { recursive: true });
  writeFileSync(join(previewDir, 'SKILL.md'), '---\nname: preview-only\n---\n');

  // skill-empty 只落 development，output/skills 缺失 → 按空处理

  api = await startTestApi();
});

after(async () => {
  await api.close();
  await stub.close();
  await prisma.$disconnect();
});

test('无 workspaceId：只含 library 项，root / cwd 指向 skill-workshop 布局', async () => {
  const { status, body } = await api.get(`${API}/skills`);
  assert.equal(status, 200);
  assert.equal(body.root, join(env.home, 'smart-factory', 'skill-workshop', 'output', 'skills'));
  assert.equal(body.cwd, join(env.home, 'smart-factory', 'skill-workshop'));

  const items = body.items as Array<Record<string, unknown>>;
  assert.ok(items.length > 0);
  assert.ok(items.every((item) => item.source === 'library'));
  assert.ok(items.every((item) => item.ownerAgentId === null && item.ownerName === null));
  // 组内 updatedAt 倒序（lib-quotes 的 frontmatter name 是「带引号」）
  assert.deepEqual(
    items.map((item) => item.name),
    ['lib-folded', 'lib-literal', 'shared-name', 'lib-beta', 'lib-vers', '带引号', 'lib-alpha', 'lib-bad'],
  );
  // updatedAt 是 ISO 串
  for (const item of items) {
    assert.equal(new Date(String(item.updatedAt)).toISOString(), item.updatedAt);
  }
});

test('v1 与 v10 并存：按数字比较取 v10', async () => {
  const { body } = await api.get(`${API}/skills`);
  const item = body.items.find((item: { name: string }) => item.name === 'lib-vers');
  assert.ok(item);
  assert.equal(item.version, 'v10');
  assert.equal(item.path, join(libraryRoot, 'lib-vers'));
});

test('坏 SKILL.md：name 回落目录名、description 空串，其余项不受影响', async () => {
  const { status, body } = await api.get(`${API}/skills`);
  assert.equal(status, 200);
  const bad = body.items.find((item: { name: string }) => item.name === 'lib-bad');
  assert.ok(bad);
  assert.equal(bad.description, '');
  const good = body.items.find((item: { name: string }) => item.name === 'lib-alpha');
  assert.equal(good.description, 'lib-alpha 的描述');
});

test('frontmatter 正常：name / description 取自 YAML 并剥成对引号', async () => {
  const { body } = await api.get(`${API}/skills`);
  const quoted = body.items.find((item: { name: string }) => item.name === '带引号');
  assert.ok(quoted);
  assert.equal(quoted.description, '单引号描述');
  const plain = body.items.find((item: { name: string }) => item.name === 'lib-beta');
  assert.equal(plain.description, 'lib-beta 的描述');
});

test('description 写成块标量：`>` 折成一行，`|` 保留换行', async () => {
  const { body } = await api.get(`${API}/skills`);
  const folded = body.items.find((item: { name: string }) => item.name === 'lib-folded');
  assert.ok(folded);
  // `>`：行间断行折成空格（不是把 `>-` 本身当成值）
  assert.equal(folded.description, '折叠块写的第一行， 第二行。');
  const literal = body.items.find((item: { name: string }) => item.name === 'lib-literal');
  assert.ok(literal);
  assert.equal(literal.description, '第一行\n第二行');
});

test('SKILLS_ROOT 缺省：{COSIGHT_HOME}/smart-factory/skill-workshop', () => {
  assert.equal(probeSkillsRoot(), join(env.home, 'smart-factory', 'skill-workshop'));
});

test('SKILLS_ROOT 环境变量生效：resolve() 后采用', () => {
  const custom = join(env.home, 'custom-skills');
  assert.equal(probeSkillsRoot({ SKILLS_ROOT: custom }), resolve(custom));
});

test('.agent-genesis 过程目录不进扫描面', async () => {
  const { body } = await api.get(`${API}/skills`);
  const names = body.items.map((item: { name: string }) => item.name);
  assert.ok(!names.includes('ghost'));
});

test('带 workspaceId：agent 项出现在 library 组之后，source / owner 字段正确', async () => {
  const { status, body } = await api.get(`${API}/skills?workspaceId=${TEST_WORKSPACE_ID}`);
  assert.equal(status, 200);
  const items = body.items as Array<Record<string, unknown>>;

  const shared = items.filter((item) => item.name === 'shared-name');
  assert.equal(shared.length, 2);
  assert.equal(shared[0]!.source, 'library');
  assert.equal(shared[0]!.description, 'library 版描述');
  assert.equal(shared[1]!.source, 'agent');
  assert.equal(shared[1]!.ownerAgentId, 'skill-agt');
  assert.equal(shared[1]!.ownerName, 'skill-agt');
  assert.equal(shared[1]!.version, 'v1');
  assert.equal(
    shared[1]!.path,
    join(agentRootIn(env.workspaceDir, 'skill-agt'), 'development', 'output', 'skills', 'shared-name'),
  );
  // library 组在前、agent 组在后
  const firstAgentIndex = items.findIndex((item) => item.source === 'agent');
  const lastLibraryIndex = items.map((item) => item.source).lastIndexOf('library');
  assert.ok(lastLibraryIndex < firstAgentIndex);
});

test('产物自带技能：扫当前产物最新 vN 的 .claude/skills，旧版本与 preview 副本不扫', async () => {
  const { status, body } = await api.get(`${API}/skills?workspaceId=${TEST_WORKSPACE_ID}`);
  assert.equal(status, 200);
  const items = body.items as Array<Record<string, unknown>>;

  const bundled = items.find((item) => item.name === 'bundled-skill');
  assert.ok(bundled, '产物 .claude/skills 下的技能必须出现在列表里');
  assert.equal(bundled.source, 'agent');
  assert.equal(bundled.ownerAgentId, 'skill-empty');
  assert.equal(bundled.ownerName, 'skill-empty');
  assert.equal(bundled.description, 'bundled-skill 的描述');
  // 技能目录里没有 vN 子目录 → 空串，前端拼出来就是 <path>/SKILL.md
  assert.equal(bundled.version, '');
  assert.equal(
    bundled.path,
    join(
      agentRootIn(env.workspaceDir, 'skill-empty'),
      'development',
      'output',
      'agents',
      'built-agent',
      'v10',
      '.claude',
      'skills',
      'bundled-skill',
    ),
  );

  const names = items.map((item) => item.name);
  assert.ok(!names.includes('bundled-old'), '只扫最新 vN，旧版本不进扫描面');
  assert.ok(!names.includes('preview-only'), 'preview 是物化副本，不扫');
});

test('workspaceId 非 uuid：400', async () => {
  const { status } = await api.get(`${API}/skills?workspaceId=not-a-uuid`);
  assert.equal(status, 400);
});

test('stub 未登记的 workspaceId：502', async () => {
  const { status } = await api.get(`${API}/skills?workspaceId=00000000-0000-4000-8000-000000000000`);
  assert.equal(status, 502);
});

test('agent 技能目录不存在：按空处理，不报错', async () => {
  const { status, body } = await api.get(`${API}/skills?workspaceId=${TEST_WORKSPACE_ID}`);
  assert.equal(status, 200);
  const names = body.items.map((item: { name: string }) => item.name);
  // skill-agt 之外，skill-empty 的 output/skills 缺失，不应产生任何项也不应 500
  assert.ok(!names.includes('skill-empty'));
});

test('库目录不存在：200 + 空列表，root / cwd 仍有值', async () => {
  // 放到最后：整棵 output/skills 删掉后，其余用例的库内技能都不在了
  rmSync(libraryRoot, { recursive: true, force: true });
  const { status, body } = await api.get(`${API}/skills`);
  assert.equal(status, 200);
  assert.deepEqual(body.items, []);
  assert.equal(body.root, join(env.home, 'smart-factory', 'skill-workshop', 'output', 'skills'));
  assert.equal(body.cwd, join(env.home, 'smart-factory', 'skill-workshop'));
});
