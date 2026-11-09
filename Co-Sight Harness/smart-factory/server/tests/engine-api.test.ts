import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { realpathSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import type { ClaudeInitializeResponse } from '../src/shared/engine/claude-protocol.js';
import { prepareTestEnv } from './helpers/test-db.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

/**
 * 引擎 `/` 菜单与自身信息（04-api/4.16）：
 * 端点经适配器取数据，测试用 `ENGINE=fake` 的固定桩，不启动真实 Claude Code 进程；
 * initialize 回执 → DTO 的纯映射另用夹具单测。
 */

const env = prepareTestEnv('engine-api');

const { slashCommandsOf, engineInfoOf } = await import('../src/shared/engine/claude-adapter.js');

let api: TestApi;

before(async () => {
  api = await startTestApi();
});

after(async () => {
  await api.close();
});

/** 真实 Claude Code 的 initialize 回执形状；第三行刻意缺字段，覆盖老引擎的兜底。 */
const INIT = {
  commands: [
    { name: 'deep-research', description: '内置命令', argumentHint: '', builtin: true },
    { name: 'plugin:skill', description: '插件技能', argumentHint: '--mode optimize', aliases: ['skill'] },
    { name: 'project-cmd' },
  ],
  agents: [{ name: 'Explore', description: '探索' }],
  output_style: 'default',
  available_output_styles: ['default', 'Concise'],
  models: [
    { value: 'default', resolvedModel: 'claude-opus-5-5', displayName: 'Default', description: '默认模型' },
    { value: 'sonnet', displayName: 'Sonnet', description: '均衡' },
  ],
  account: { tokenSource: 'ANTHROPIC_AUTH_TOKEN', apiProvider: 'firstParty' },
  claude_code_version: '2.1.311',
} as unknown as ClaudeInitializeResponse;

test('slashCommandsOf：原样透传名字 / 说明 / 参数提示，缺省补空串，aliases 与 builtin 只在有时出现', () => {
  assert.deepEqual(slashCommandsOf(INIT), [
    { name: 'deep-research', description: '内置命令', argumentHint: '', builtin: true },
    { name: 'plugin:skill', description: '插件技能', argumentHint: '--mode optimize', aliases: ['skill'] },
    { name: 'project-cmd', description: '', argumentHint: '' },
  ]);
});

test('engineInfoOf：只给引擎 / 目录 / 版本 / 可见命令数，不回本机的模型与账号', () => {
  const info = engineInfoOf(INIT, '/tmp/probe');
  // 回执里带了 models / account / output_style，也不进响应：产品模型由框架配置
  assert.deepEqual(info, {
    engine: 'claude-cli',
    cwd: '/tmp/probe',
    version: '2.1.311',
    // 与列表端点同口径：自带命令不计入
    commandCount: 2,
    available: true,
  });
});

test('GET /engine/commands/list：缺省 cwd 用主目录，且过滤掉引擎自带命令', async () => {
  const { status, body } = await api.get(`${API}/engine/commands/list`);
  assert.equal(status, 200);
  assert.equal(body.engine, 'fake');
  assert.equal(body.cwd, realpathSync(homedir()));
  assert.deepEqual(body.items, [
    { name: 'fake-command', description: '桩引擎的固定命令', argumentHint: '' },
  ]);
});

test('GET /engine/commands/list：cwd 解析为真实绝对路径（已解 symlink）', async () => {
  const { status, body } = await api.get(
    `${API}/engine/commands/list?cwd=${encodeURIComponent(env.workspaceDir)}`,
  );
  assert.equal(status, 200);
  assert.equal(body.cwd, realpathSync(env.workspaceDir));
  assert.equal(body.items.length, 1);
});

test('cwd 校验：相对路径 400、不存在 404、不是目录 400', async () => {
  const relative = await api.get(`${API}/engine/commands/list?cwd=relative/path`);
  assert.equal(relative.status, 400);
  assert.match(relative.body.message, /绝对路径/);

  const missing = await api.get(`${API}/engine/commands/list?cwd=${encodeURIComponent('/definitely-missing-dir/engine-api')}`);
  assert.equal(missing.status, 404);

  const file = join(env.workspaceDir, 'not-a-dir.txt');
  writeFileSync(file, 'x\n');
  const notDir = await api.get(`${API}/engine/detail?cwd=${encodeURIComponent(file)}`);
  assert.equal(notDir.status, 400);
  assert.match(notDir.body.message, /不是目录/);
});

test('GET /engine/detail：桩引擎信息只含四个字段', async () => {
  const { status, body } = await api.get(`${API}/engine/detail?cwd=${encodeURIComponent(env.workspaceDir)}`);
  assert.equal(status, 200);
  assert.deepEqual(body, {
    engine: 'fake',
    cwd: realpathSync(env.workspaceDir),
    version: '0.0.0-fake',
    commandCount: 1,
  });
});
