/**
 * 三个宿主侧检查项的分支：Claude Code / Claude 目录 / Python 3。
 *
 * 每个失败分支都要能说清"查过什么、怎么办、不办会怎样"——这些文案就是
 * 用户看到的第一屏，不能只在正常路径上测。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, describe, it } from 'node:test';

import {
  claudeCheck,
  claudeConfigDir,
  claudeDirCheck,
  pluginsRequiring,
  pythonCheck,
} from '../lib/checks/claude.mjs';
import { exitCodeFor, runChecks } from '../lib/preflight.mjs';

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-claude-check-'));
after(() => fs.rmSync(scratch, { recursive: true, force: true }));

const HOME = path.join(scratch, 'home');

function foundAt(executable = '/usr/bin/claude') {
  return {
    path: executable,
    source: 'path',
    checked: {
      explicitPath: null,
      pathDirs: ['/usr/bin'],
      fallbacks: [path.join(HOME, '.local', 'bin', 'claude')],
    },
  };
}

const okVersion = async () => ({ ok: true, version: '2.1.304', raw: '2.1.304 (Claude Code)' });

/** "一个都没找到"的解析结果，测试里多处复用。 */
const notFoundAnywhere = () => ({
  path: null,
  source: null,
  checked: { explicitPath: null, pathDirs: [], fallbacks: [] },
});

describe('Claude Code 检查', () => {
  it('没找到时列出查过的位置与安装办法', async () => {
    const [result] = await runChecks([
      claudeCheck({
        homeDir: HOME,
        resolve: () => ({
          path: null,
          source: null,
          checked: { explicitPath: null, pathDirs: ['/usr/bin'], fallbacks: [path.join(HOME, '.local', 'bin', 'claude')] },
        }),
      }),
    ]);

    assert.equal(result.ok, false);
    assert.equal(result.detail, '未找到');
    assert.match(result.remedy[0], /PATH（1 个目录）/);
    // 提示里的路径按平台分隔符渲染，断言不绑定某一种分隔符。
    assert.match(result.remedy[0], /~[/\\]\.local[/\\]bin[/\\]claude/);
    assert.match(result.remedy.join('\n'), /npm install -g @anthropic-ai\/claude-code/);
    assert.match(result.impact, /drive/);
  });

  it('--claude 指到不存在的路径时直接说清楚', async () => {
    const [result] = await runChecks([
      claudeCheck({
        explicit: '/nope/claude',
        homeDir: HOME,
        resolve: () => ({
          path: null,
          source: null,
          checked: { explicitPath: '/nope/claude', pathDirs: [], fallbacks: [] },
        }),
      }),
    ]);

    assert.equal(result.ok, false);
    assert.match(result.detail, /--claude 指定的 \/nope\/claude/);
    assert.match(result.remedy.join('\n'), /去掉 --claude/);
  });

  it('正常版本通过，并给出路径', async () => {
    const [result] = await runChecks([
      claudeCheck({ homeDir: HOME, resolve: () => foundAt(), readVersion: okVersion }),
    ]);

    assert.equal(result.ok, true);
    assert.match(result.detail, /2\.1\.304，\/usr\/bin\/claude/);
  });

  it('版本过低时给升级命令', async () => {
    const [result] = await runChecks([
      claudeCheck({
        homeDir: HOME,
        resolve: () => foundAt(),
        readVersion: async () => ({ ok: false, reason: 'too-old', version: '2.1.286', raw: '2.1.286 (Claude Code)' }),
      }),
    ]);

    assert.equal(result.ok, false);
    assert.match(result.detail, /2\.1\.286 低于要求的 2\.1\.287/);
    assert.match(result.remedy.join('\n'), /@anthropic-ai\/claude-code@latest/);
  });

  it('找到的不是 Claude Code', async () => {
    const [result] = await runChecks([
      claudeCheck({
        homeDir: HOME,
        resolve: () => foundAt(),
        readVersion: async () => ({ ok: false, reason: 'not-claude', raw: '2.1.304 (Some Other CLI)' }),
      }),
    ]);

    assert.equal(result.ok, false);
    assert.match(result.detail, /不是 Claude Code/);
    assert.match(result.detail, /Some Other CLI/);
  });

  it('超时与异常退出分开说', async () => {
    const [timeout] = await runChecks([
      claudeCheck({
        homeDir: HOME,
        resolve: () => foundAt(),
        readVersion: async () => ({ ok: false, reason: 'timeout', raw: '' }),
      }),
    ]);
    assert.match(timeout.detail, /5 秒内没有返回/);
    assert.match(timeout.remedy.join('\n'), /首次启动/);

    const [failed] = await runChecks([
      claudeCheck({
        homeDir: HOME,
        resolve: () => foundAt(),
        readVersion: async () => ({ ok: false, reason: 'exit', raw: '找不到命令', code: 1 }),
      }),
    ]);
    assert.match(failed.detail, /执行 --version 失败（找不到命令）/);
  });

  it('版本行解析不出来但 plugin list 可用时降为 warn 放行', async () => {
    const [result] = await runChecks([
      claudeCheck({
        homeDir: HOME,
        resolve: () => foundAt(),
        readVersion: async () => ({ ok: false, reason: 'unparsable', raw: '新格式' }),
        probe: async () => ({ ok: true }),
      }),
    ]);

    assert.equal(result.ok, false);
    assert.equal(result.level, 'warn');
    assert.match(result.detail, /放行/);
    assert.equal(exitCodeFor([result]), 0);
  });

  it('版本行解析不出来且插件命令不可用时拦住', async () => {
    const [result] = await runChecks([
      claudeCheck({
        homeDir: HOME,
        resolve: () => foundAt(),
        readVersion: async () => ({ ok: false, reason: 'unparsable', raw: '新格式' }),
        probe: async () => ({ ok: false, reason: 'exit', code: 1 }),
      }),
    ]);

    assert.equal(result.ok, false);
    assert.equal(result.level, 'block');
    assert.match(result.detail, /无法解析/);
    assert.match(result.remedy.join('\n'), /plugin list --json 退出码 1/);
  });
});

describe('Claude 目录检查', () => {
  it('优先使用 CLAUDE_CONFIG_DIR', () => {
    // 期望值走 `path.resolve`：Windows 上 `/custom/claude` 会被解析成
    // `D:\custom\claude`，直接和字面量比等于在要求它"别按平台规则解析"。
    assert.equal(
      claudeConfigDir({ env: { CLAUDE_CONFIG_DIR: '/custom/claude' }, homeDir: '/home/u' }),
      path.resolve('/custom/claude'),
    );
    assert.equal(claudeConfigDir({ env: {}, homeDir: '/home/u' }), path.join('/home/u', '.claude'));
  });

  it('已存在且可写时通过', async () => {
    const home = fs.mkdtempSync(path.join(scratch, 'home-exists-'));
    const dir = path.join(home, '.claude');
    fs.mkdirSync(dir);

    const [result] = await runChecks([claudeDirCheck({ env: {}, homeDir: home })]);
    assert.equal(result.ok, true);
    assert.match(result.detail, /已存在且可写/);
  });

  it('尚未创建时看上级目录，并说明会创建', async () => {
    const home = fs.mkdtempSync(path.join(scratch, 'home-missing-'));
    const [result] = await runChecks([claudeDirCheck({ env: {}, homeDir: home })]);
    assert.equal(result.ok, true);
    assert.match(result.detail, /尚未创建.*可写.*首次安装时创建/);
  });

  it('同名文件或不可写时拦住，并提醒不要用 sudo', async () => {
    const home = fs.mkdtempSync(path.join(scratch, 'home-file-'));
    fs.writeFileSync(path.join(home, '.claude'), 'not a dir');

    const [result] = await runChecks([claudeDirCheck({ env: {}, homeDir: home })]);
    assert.equal(result.ok, false);
    assert.match(result.detail, /不是目录/);
    assert.match(result.remedy.join('\n'), /不要用 sudo/);
  });
});

describe('Python 3 检查', () => {
  const plugins = [
    { id: 'drive', requires: { bins: ['python3'] } },
    { id: 'agent-genesis', requires: { bins: ['python3'] } },
    { id: 'goldeval', requires: { bins: [] } },
  ];

  it('没有插件声明时跳过', async () => {
    const [result] = await runChecks([pythonCheck({ plugins: [] })]);
    assert.equal(result.ok, true);
    assert.match(result.detail, /没有声明需要 python3/);
  });

  it('找一个都不满足就点名需要它的插件', async () => {
    const [result] = await runChecks([
      pythonCheck({
        plugins,
        resolve: () => ({ path: null, source: null, checked: { explicitPath: null, pathDirs: [], fallbacks: [] } }),
      }),
    ]);

    assert.equal(result.ok, false);
    assert.match(result.detail, /drive、agent-genesis/);
    assert.match(result.remedy.join('\n'), /PATH/);
    assert.doesNotMatch(result.impact, /goldeval/);
  });

  // Windows 的 Python 安装包只生成 python.exe / py.exe，没有 python3.exe。
  // 提示里必须说清"怎么让 python3 这个名字存在"，否则用户按提示做完仍然被拦。
  it('Windows 上说明 python3 这个名字要怎么来', async () => {
    const [windows] = await runChecks([
      pythonCheck({ plugins, platform: 'win32', resolve: notFoundAnywhere }),
    ]);
    const winRemedy = windows.remedy.join('\n');
    assert.match(winRemedy, /python3\.exe/);
    assert.match(winRemedy, /install\.cmd/);

    const [posix] = await runChecks([
      pythonCheck({ plugins, platform: 'linux', resolve: notFoundAnywhere }),
    ]);
    const posixRemedy = posix.remedy.join('\n');
    assert.doesNotMatch(posixRemedy, /python3\.exe/);
    assert.match(posixRemedy, /install\.sh/);
  });

  it('找到并跑通 --version 时给出真实版本', async () => {
    const [result] = await runChecks([
      pythonCheck({
        plugins,
        resolve: () => ({ path: '/usr/bin/python3', source: 'path', checked: { explicitPath: null, pathDirs: [], fallbacks: [] } }),
        run: async () => ({ code: 0, signal: null, stdout: 'Python 3.11.8\n', stderr: '', timedOut: false, error: null }),
      }),
    ]);

    assert.equal(result.ok, true);
    assert.match(result.detail, /3\.11\.8，\/usr\/bin\/python3/);
    assert.match(result.detail, /drive、agent-genesis/);
  });

  it('存在但跑不通（应用商店占位别名）时拦住', async () => {
    const [result] = await runChecks([
      pythonCheck({
        plugins,
        resolve: () => ({ path: '/usr/bin/python3', source: 'path', checked: { explicitPath: null, pathDirs: [], fallbacks: [] } }),
        run: async () => ({
          code: 9009,
          signal: null,
          stdout: '',
          stderr: 'Python was not found',
          timedOut: false,
          error: null,
        }),
      }),
    ]);

    assert.equal(result.ok, false);
    assert.match(result.detail, /退出码 9009/);
    assert.match(result.remedy.join('\n'), /占位别名/);
  });

  it('pluginsRequiring 忽略形状不对的声明', () => {
    assert.deepEqual(pluginsRequiring([{ id: 'a' }, { id: 'b', requires: { bins: 'python3' } }], 'python3'), []);
    assert.deepEqual(pluginsRequiring(plugins, 'python3'), ['drive', 'agent-genesis']);
  });
});
