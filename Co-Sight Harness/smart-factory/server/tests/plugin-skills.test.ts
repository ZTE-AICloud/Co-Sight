/**
 * 插件技能与命令（`plugin:skill` / `plugin:command`）：自己声明的 ∪ 产品运行时能力
 * `drive@zte-ai-lab`，只列真装着的；技能还要 `user-invocable` 不为 false。
 * 其余用户自装插件不列。
 *
 * 权威：server/docs/04-api/4.14-可执行技能与命令.md、src/shared/skills/plugin-skills.ts
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';

const env = prepareTestEnv('plugin-skills');

/** 插件登记与载荷都放在测试自己的临时区，不碰真实 ~/.claude。 */
const CONFIG_DIR = join(env.home, 'claude-config');
process.env.CLAUDE_CONFIG_DIR = CONFIG_DIR;

const { enabledPluginIds, listEnabledPluginCommands, listEnabledPluginSkills } = await import(
  '../src/shared/skills/plugin-skills.js'
);
const { scanExecutables } = await import('../src/shared/skills/executables.js');

function writeSkill(installPath: string, dirName: string, frontmatter = 'name: ignored\n'): void {
  const dir = join(installPath, 'skills', dirName);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'SKILL.md'), `---\n${frontmatter}---\n\n正文\n`);
}

/** 插件载荷里的一条命令（`commands/<相对路径>.md`）；frontmatter 为空时连分隔符都不写。 */
function writeCommand(installPath: string, relativePath: string, frontmatter = ''): void {
  const file = join(installPath, 'commands', relativePath);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, frontmatter === '' ? '# 命令\n' : `---\n${frontmatter}---\n\n正文\n`);
}

function writeRegistry(plugins: Record<string, unknown>): void {
  const file = join(CONFIG_DIR, 'plugins', 'installed_plugins.json');
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify({ version: 2, plugins }));
}

function writeSettings(runtimeDir: string, enabledPlugins: Record<string, unknown>): void {
  const file = join(runtimeDir, '.claude', 'settings.json');
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify({ enabledPlugins }));
}

/** 造一颗插件载荷（`skills/<name>/SKILL.md`）。 */
function seedPlugin(installPath: string): void {
  writeSkill(installPath, 'alpha', 'name: Alpha\ndescription: 插件技能\nversion: "1.2"\n');
  writeSkill(installPath, 'beta', 'description: 无 name 的插件技能\n');
  // 缺 SKILL.md 的目录不是技能；隐藏目录引擎不发现
  mkdirSync(join(installPath, 'skills', 'broken'), { recursive: true });
  writeFileSync(join(installPath, 'skills', 'broken', 'notes.txt'), 'x\n');
  writeSkill(installPath, '.hidden');
  writeCommand(installPath, 'deploy.md', 'description: 插件命令\n');
}

test('打开且装着的插件：按 plugin:skill 列出，元数据取插件载荷里的 SKILL.md', () => {
  const installPath = join(env.home, 'cache', 'zed-ai-lab', 'demo', '1.0.0');
  seedPlugin(installPath);
  writeRegistry({ 'demo@market': [{ scope: 'user', installPath }] });

  const runtimeDir = join(env.home, 'expert-enabled');
  writeSettings(runtimeDir, { 'demo@market': true });

  assert.deepEqual(enabledPluginIds(runtimeDir), ['demo@market', 'drive@zte-ai-lab']);
  const items = listEnabledPluginSkills(runtimeDir);
  assert.deepEqual(items.map((item) => item.name), ['demo:alpha', 'demo:beta']);

  const alpha = items[0];
  assert.equal(alpha.displayName, 'Alpha');
  assert.equal(alpha.description, '插件技能');
  assert.equal(alpha.version, '1.2');
  assert.equal(alpha.path, join(installPath, 'skills', 'alpha'));
  assert.match(alpha.updatedAt, /^\d{4}-\d{2}-\d{2}T/);

  // 没有 frontmatter 时 displayName 回落为目录名（不带插件前缀）
  assert.equal(items[1].displayName, 'beta');
});

test('打开且装着的插件：按 plugin:command 列出，名字是插件前缀 + 文件名（含子目录）', () => {
  const installPath = join(env.home, 'cache', 'zed-ai-lab', 'cmd', '1.0.0');
  writeCommand(installPath, 'pkm.md', 'description: 个人知识管理\n');
  writeCommand(installPath, 'soc.md');
  writeCommand(installPath, 'sub/report.md', 'description: 子目录命令\n');
  writeCommand(installPath, 'notes.txt', 'description: 不是命令\n'); // 非 .md 忽略
  writeRegistry({ 'cmd@market': [{ scope: 'user', installPath }] });

  const runtimeDir = join(env.home, 'expert-commands');
  writeSettings(runtimeDir, { 'cmd@market': true });

  const items = listEnabledPluginCommands(runtimeDir);
  assert.deepEqual(items.map((item) => item.name), ['cmd:pkm', 'cmd:report', 'cmd:soc']);

  const pkm = items[0];
  assert.equal(pkm.namespace, 'cmd');
  assert.equal(pkm.description, '个人知识管理');
  assert.equal(pkm.path, join(installPath, 'commands', 'pkm.md'));
  assert.match(pkm.updatedAt, /^\d{4}-\d{2}-\d{2}T/);

  // 没有 frontmatter 时 description 为空串；子目录只影响排序，不改命令名
  assert.equal(items[2].description, '');
  assert.equal(items[1].path, join(installPath, 'commands', 'sub', 'report.md'));
});

test('不同子目录的同名命令：按路径升序取第一个', () => {
  const installPath = join(env.home, 'cache', 'zed-ai-lab', 'dup', '1.0.0');
  writeCommand(installPath, 'b/same.md', 'description: 后者\n');
  writeCommand(installPath, 'a/same.md', 'description: 前者\n');
  writeRegistry({ 'dup@market': [{ scope: 'user', installPath }] });

  const runtimeDir = join(env.home, 'expert-dup-commands');
  writeSettings(runtimeDir, { 'dup@market': true });

  const items = listEnabledPluginCommands(runtimeDir);
  assert.deepEqual(items.map((item) => item.name), ['dup:same']);
  assert.equal(items[0].description, '前者');
});

test('显式关闭 / 没装 / 没写 settings / settings 坏了：技能与命令都不列', () => {
  const installPath = join(env.home, 'cache', 'zed-ai-lab', 'demo', '1.0.0');
  writeCommand(installPath, 'pkm.md');
  writeRegistry({ 'demo@market': [{ scope: 'user', installPath }] });

  const disabled = join(env.home, 'expert-disabled');
  writeSettings(disabled, { 'demo@market': false });
  assert.deepEqual(listEnabledPluginSkills(disabled), []);
  assert.deepEqual(listEnabledPluginCommands(disabled), []);

  const missing = join(env.home, 'expert-missing');
  writeSettings(missing, { 'other@market': true });
  assert.deepEqual(listEnabledPluginSkills(missing), []);
  assert.deepEqual(listEnabledPluginCommands(missing), []);

  const noSettings = join(env.home, 'expert-no-settings');
  mkdirSync(noSettings, { recursive: true });
  assert.deepEqual(listEnabledPluginSkills(noSettings), []);
  assert.deepEqual(listEnabledPluginCommands(noSettings), []);

  const broken = join(env.home, 'expert-broken');
  mkdirSync(join(broken, '.claude'), { recursive: true });
  writeFileSync(join(broken, '.claude', 'settings.json'), '{ not json');
  assert.deepEqual(listEnabledPluginSkills(broken), []);
});

test('同一插件的多条登记：优先取登记在本人份（projectPath）上的那条', () => {
  const userPath = join(env.home, 'cache', 'zed-ai-lab', 'demo', '3.0.0');
  const projectPath = join(env.home, 'cache', 'zed-ai-lab', 'demo', '3.2.0');
  writeSkill(userPath, 'user-only');
  writeSkill(projectPath, 'project-only');

  const runtimeDir = join(env.home, 'expert-scoped');
  writeSettings(runtimeDir, { 'demo@market': true });
  writeRegistry({
    'demo@market': [
      { scope: 'user', installPath: userPath },
      { scope: 'project', projectPath: runtimeDir, installPath: projectPath },
    ],
  });

  assert.deepEqual(listEnabledPluginSkills(runtimeDir).map((item) => item.name), ['demo:project-only']);
});

test('产品运行时能力：目录没声明也列 drive，且只列 `/` 菜单点得到的技能', () => {
  const installPath = join(env.home, 'cache', 'zte-ai-lab', 'drive', '2.3.4');
  writeSkill(installPath, 'drive', 'name: drive\nuser-invocable: true\n');
  writeSkill(installPath, 'startup', 'name: startup\nuser-invocable: false\n');
  writeSkill(installPath, 'plain'); // 缺省 = 可点
  writeSkill(installPath, 'capitalized', 'user-invocable: False\n'); // 大小写不敏感
  writeRegistry({ 'drive@zte-ai-lab': [{ scope: 'user', installPath }] });

  const runtimeDir = join(env.home, 'agent-no-settings');
  mkdirSync(runtimeDir, { recursive: true });

  assert.deepEqual(enabledPluginIds(runtimeDir), ['drive@zte-ai-lab']);
  assert.deepEqual(
    listEnabledPluginSkills(runtimeDir).map((item) => item.name).sort(),
    ['drive:drive', 'drive:plain'],
  );
});

test('产品运行时能力也能关掉：智能体目录或用户 settings 显式写 false 就不列', () => {
  const installPath = join(env.home, 'cache', 'zte-ai-lab', 'drive', '2.3.4');
  writeSkill(installPath, 'drive');
  writeRegistry({ 'drive@zte-ai-lab': [{ scope: 'user', installPath }] });

  const disabled = join(env.home, 'agent-disable-drive');
  writeSettings(disabled, { 'drive@zte-ai-lab': false });
  assert.deepEqual(enabledPluginIds(disabled), []);
  assert.deepEqual(listEnabledPluginSkills(disabled), []);

  // 用户层显式关闭：智能体目录没写 `enabledPlugins` 时继承用户层的关闭
  const userSettings = join(CONFIG_DIR, 'settings.json');
  writeFileSync(userSettings, JSON.stringify({ enabledPlugins: { 'drive@zte-ai-lab': false } }));
  try {
    const bare = join(env.home, 'agent-user-disabled-drive');
    mkdirSync(bare, { recursive: true });
    assert.deepEqual(listEnabledPluginSkills(bare), []);
  } finally {
    rmSync(userSettings, { force: true });
  }
});

test('detail 清单：目录自带的与插件带来的技能、命令各合成一份，按名字字节序排列', () => {
  const installPath = join(env.home, 'cache', 'zed-ai-lab', 'demo', '2.0.0');
  seedPlugin(installPath);
  writeRegistry({ 'demo@market': [{ scope: 'user', installPath }] });

  const runtimeDir = join(env.home, 'expert-merged');
  writeSettings(runtimeDir, { 'demo@market': true });
  writeSkill(join(runtimeDir, '.claude'), 'local', 'name: 本地技能\n');
  const localCommand = join(runtimeDir, '.claude', 'commands', 'build.md');
  mkdirSync(dirname(localCommand), { recursive: true });
  writeFileSync(localCommand, '# 构建\n');

  const result = scanExecutables(runtimeDir);
  assert.deepEqual(result.skills.map((item) => item.name), ['demo:alpha', 'demo:beta', 'local']);
  assert.deepEqual(result.commands.map((item) => item.name), ['build', 'demo:deploy']);
});
