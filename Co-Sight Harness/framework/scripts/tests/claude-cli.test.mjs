/**
 * Claude Code CLI 的解析与探测。
 *
 * 这些测试**不启动真实 claude**：版本判定、Windows 命令行拼接、PATH 解析
 * 全是纯逻辑，用临时目录与注入的 `run()` 覆盖，跑得比一次 `claude --version` 还快。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, describe, it } from 'node:test';

import {
  claudeFallbackPaths,
  isVersionAtLeast,
  looksLikeClaudeCode,
  MIN_CLAUDE_VERSION,
  parseVersion,
  probePluginList,
  readClaudeVersion,
  resolveClaudeExecutable,
} from '../lib/claude-cli.mjs';
import {
  buildSpawnSpec,
  describeRunFailure,
  executableNames,
  isExecutableFile,
  quoteForCmd,
  resolveExecutable,
  runProcess,
} from '../lib/cli-exec.mjs';

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-claude-test-'));
after(() => fs.rmSync(scratch, { recursive: true, force: true }));

function makeFile(filePath, content = '') {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content);
  return filePath;
}

function makeExecutable(filePath, content = '#!/bin/sh\nexit 0\n') {
  makeFile(filePath, content);
  if (process.platform !== 'win32') {
    fs.chmodSync(filePath, 0o755);
  }
  return filePath;
}

/** 注入用的 run：只关心返回形状，不真的起进程。 */
function fakeRun(result) {
  const calls = [];
  const run = async (spec, options) => {
    calls.push({ spec, options });
    return { code: 0, signal: null, stdout: '', stderr: '', timedOut: false, error: null, ...result };
  };
  return { run, calls };
}

describe('版本解析', () => {
  it('从真实输出形状里取版本', () => {
    assert.equal(parseVersion('2.1.304 (Claude Code)'), '2.1.304');
    assert.equal(parseVersion('v2.1.304'), '2.1.304');
    assert.equal(parseVersion('Claude Code v2.1.304\n另外一行'), '2.1.304');
    assert.equal(parseVersion('2.1.304-beta.1'), '2.1.304');
  });

  it('没有版本号时返回 null', () => {
    assert.equal(parseVersion(''), null);
    assert.equal(parseVersion('Claude Code'), null);
    assert.equal(parseVersion(null), null);
  });

  it('比较版本时不把 2.10 当成小于 2.9', () => {
    assert.equal(isVersionAtLeast('2.10.0', '2.9.9'), true);
    assert.equal(isVersionAtLeast('2.1.0', '2.1.0'), true);
    assert.equal(isVersionAtLeast('2.0.9', '2.1.0'), false);
    assert.equal(isVersionAtLeast('不是版本', '2.1.0'), false);
  });

  it('识别产品名', () => {
    assert.equal(looksLikeClaudeCode('2.1.304 (Claude Code)'), true);
    assert.equal(looksLikeClaudeCode('2.1.304 (Other Tool)'), false);
  });

  it('最低版本是唯一的常量', () => {
    assert.equal(MIN_CLAUDE_VERSION, '2.1.287');
  });

  it('最低版本边界按数值比较', () => {
    assert.equal(isVersionAtLeast('2.1.287', MIN_CLAUDE_VERSION), true);
    assert.equal(isVersionAtLeast('2.1.286', MIN_CLAUDE_VERSION), false);
    assert.equal(isVersionAtLeast('2.1.304', MIN_CLAUDE_VERSION), true);
  });
});

describe('cmd.exe 参数拼接', () => {
  it('安全字符原样，空格与中文加引号', () => {
    assert.equal(quoteForCmd('drive@zte-ai-lab'), 'drive@zte-ai-lab');
    assert.equal(quoteForCmd('--scope'), '--scope');
    assert.equal(quoteForCmd('C:\\node\\claude.cmd'), 'C:\\node\\claude.cmd');
    assert.equal(quoteForCmd('C:\\Program Files\\claude.cmd'), '"C:\\Program Files\\claude.cmd"');
    assert.equal(quoteForCmd('C:\\用户\\张 三\\claude.cmd'), '"C:\\用户\\张 三\\claude.cmd"');
  });

  it('cmd 元字符被引号包住', () => {
    assert.equal(quoteForCmd('a&b'), '"a&b"');
    assert.equal(quoteForCmd('a^b'), '"a^b"');
    assert.equal(quoteForCmd('a|b>c<d'), '"a|b>c<d"');
  });

  it('无法安全转义的输入直接拒绝，而不是猜一个写法', () => {
    assert.throws(() => quoteForCmd('a"b'), /双引号/);
    assert.throws(() => quoteForCmd('C:\\100%\\claude.cmd'), /变量展开/);
    assert.throws(() => quoteForCmd('a\nb'), /换行/);
  });
});

describe('spawn 形状', () => {
  it('Windows 的 .cmd 经 cmd.exe /d /s /c，整行自己拼', () => {
    const spec = buildSpawnSpec(
      'C:\\Users\\张 三\\AppData\\Roaming\\npm\\claude.cmd',
      ['plugin', 'install', 'drive@zte-ai-lab', '--scope', 'user'],
      { platform: 'win32', comspec: 'C:\\Windows\\System32\\cmd.exe' },
    );

    assert.equal(spec.command, 'C:\\Windows\\System32\\cmd.exe');
    assert.deepEqual(spec.args.slice(0, 3), ['/d', '/s', '/c']);
    // 外层引号给 `/s` 剥掉，剩下的 `"…claude.cmd"` 才是真正的命令起点。
    assert.equal(
      spec.args[3],
      '""C:\\Users\\张 三\\AppData\\Roaming\\npm\\claude.cmd" plugin install drive@zte-ai-lab --scope user"',
    );
    assert.equal(spec.windowsVerbatimArguments, true);
  });

  it('Windows 的 .exe 直接 spawn', () => {
    const spec = buildSpawnSpec('C:\\Tools\\claude.exe', ['--version'], { platform: 'win32' });
    assert.equal(spec.command, 'C:\\Tools\\claude.exe');
    assert.deepEqual(spec.args, ['--version']);
    assert.equal(spec.windowsVerbatimArguments, false);
  });

  it('POSIX 永远直接 spawn，即使文件名以 .cmd 结尾', () => {
    const spec = buildSpawnSpec('/opt/claude.cmd', ['--version'], { platform: 'linux' });
    assert.equal(spec.command, '/opt/claude.cmd');
    assert.deepEqual(spec.args, ['--version']);
  });
});

describe('可执行文件查找', () => {
  it('Windows 候选名 exe 优先，其余按 PATHEXT', () => {
    assert.deepEqual(
      executableNames('claude', { platform: 'win32', pathext: '.COM;.CMD;.EXE;.BAT' }),
      ['claude.exe', 'claude.cmd', 'claude.bat'],
    );
    assert.deepEqual(executableNames('claude', { platform: 'linux' }), ['claude']);
  });

  it('POSIX 上必须带可执行位', { skip: process.platform === 'win32' }, () => {
    const bin = path.join(scratch, 'posix-bin');
    const executable = makeExecutable(path.join(bin, 'claude'));
    const notExecutable = makeFile(path.join(scratch, 'plain', 'claude'), 'x');
    fs.chmodSync(notExecutable, 0o644);

    assert.equal(isExecutableFile(executable, 'linux'), true);
    assert.equal(isExecutableFile(notExecutable, 'linux'), false);
  });

  // 这条依赖"文件真的带 Unix 可执行位"，而 Windows 的 chmod 是空操作
  // （`fs.stat` 一律报 0666），构造不出这个前置条件。Windows 的 PATH 查找
  // 由下面那条 `.cmd` 用例覆盖。
  it('在 PATH 中找到并返回来源', { skip: process.platform === 'win32' }, () => {
    const bin = path.join(scratch, 'path-bin');
    const executable = makeExecutable(path.join(bin, 'claude'));
    const found = resolveExecutable('claude', {
      env: { PATH: bin },
      platform: 'linux',
      homeDir: scratch,
    });

    assert.equal(found.path, executable);
    assert.equal(found.source, 'path');
    assert.deepEqual(found.checked.pathDirs, [bin]);
  });

  it('显式指定找不到时不回退到 PATH', () => {
    const bin = path.join(scratch, 'explicit-bin');
    makeExecutable(path.join(bin, 'claude'));
    const missing = path.join(scratch, 'nope', 'claude');

    const found = resolveExecutable('claude', {
      explicit: missing,
      env: { PATH: bin },
      platform: 'linux',
      homeDir: scratch,
    });

    assert.equal(found.path, null);
    assert.equal(found.source, null);
    assert.equal(found.checked.explicitPath, missing);
  });

  it('PATH 里没有时用兜底位置', () => {
    const fallback = makeExecutable(path.join(scratch, 'fallback', 'claude'));
    const found = resolveExecutable('claude', {
      env: { PATH: path.join(scratch, 'empty-bin') },
      platform: 'linux',
      homeDir: scratch,
      fallbacks: [fallback],
    });

    assert.equal(found.path, fallback);
    assert.equal(found.source, 'fallback');
  });

  it('Windows 的 PATH 用分号切分，且能选中 .cmd', () => {
    const bin = path.join(scratch, 'win-bin');
    const cmd = makeFile(path.join(bin, 'claude.cmd'), '@echo off');
    const found = resolveExecutable('claude', {
      env: { PATH: `${path.join(scratch, 'none')};${bin}` },
      platform: 'win32',
      homeDir: scratch,
    });

    assert.equal(found.path, cmd);
    assert.equal(found.source, 'path');
  });

  it('兜底位置覆盖原生安装与 npm 全局安装', () => {
    // 期望值统一用 `path.join`：跑在 Windows 上时它给反斜杠，
    // 直接写字面量 `/home/u/…` 会把"分隔符随平台"当成缺陷。
    const posix = claudeFallbackPaths({ platform: 'linux', homeDir: '/home/u', env: {} });
    assert.ok(posix.includes(path.join('/home/u', '.local', 'bin', 'claude')));
    // 这一条在源码里就是字面量（`/usr/local/bin/claude`），不走 `path.join`，
    // 所以期望值也保持字面量——它本来就是个 POSIX 绝对路径。
    assert.ok(posix.includes('/usr/local/bin/claude'));

    const windows = claudeFallbackPaths({
      platform: 'win32',
      homeDir: 'C:\\Users\\u',
      env: { APPDATA: 'C:\\Users\\u\\AppData\\Roaming' },
    });
    // 测试跑在 POSIX 上，path.join 用的是 "/"；只比较路径的"逻辑尾部"。
    assert.ok(
      windows.some((item) => item.replaceAll('\\', '/').endsWith('AppData/Roaming/npm/claude.cmd')),
    );
  });

  it('resolveClaudeExecutable 会带上默认兜底位置', () => {
    const found = resolveClaudeExecutable({
      env: { PATH: '' },
      platform: 'linux',
      homeDir: path.join(scratch, 'no-home'),
    });
    assert.equal(found.path, null);
    const fallbackTail = ['.local', 'bin', 'claude'].join(path.sep);
    assert.ok(found.checked.fallbacks.some((item) => item.endsWith(fallbackTail)));
  });
});

describe('claude --version 判读', () => {
  it('正常输出通过', async () => {
    const { run, calls } = fakeRun({ stdout: '2.1.304 (Claude Code)\n' });
    const result = await readClaudeVersion({ executable: '/usr/bin/claude', platform: 'linux', run });

    assert.equal(result.ok, true);
    assert.equal(result.version, '2.1.304');
    assert.deepEqual(calls[0].spec.args, ['--version']);
    assert.equal(calls[0].options.timeoutMs, 5_000);
  });

  it('版本过低', async () => {
    const { run } = fakeRun({ stdout: '2.0.9 (Claude Code)' });
    const result = await readClaudeVersion({ executable: '/usr/bin/claude', platform: 'linux', run });

    assert.equal(result.ok, false);
    assert.equal(result.reason, 'too-old');
    assert.equal(result.version, '2.0.9');
  });

  it('输出不是 Claude Code', async () => {
    const { run } = fakeRun({ stdout: '2.1.304 (Some Other CLI)' });
    const result = await readClaudeVersion({ executable: '/usr/bin/claude', platform: 'linux', run });

    assert.equal(result.reason, 'not-claude');
  });

  it('解析不出或超时或非零退出各有原因', async () => {
    const cases = [
      { result: { stdout: '随便什么' }, reason: 'unparsable' },
      { result: { timedOut: true }, reason: 'timeout' },
      { result: { code: 1, stderr: '找不到命令' }, reason: 'exit' },
      { result: { error: new Error('EACCES') }, reason: 'spawn-error' },
    ];

    for (const { result, reason } of cases) {
      const { run } = fakeRun(result);
      const outcome = await readClaudeVersion({ executable: '/usr/bin/claude', platform: 'linux', run });
      assert.equal(outcome.reason, reason);
    }
  });
});

describe('plugin list 兜底探测', () => {
  it('JSON 可解析即可用', async () => {
    const { run, calls } = fakeRun({ stdout: '[]' });
    const result = await probePluginList({ executable: '/usr/bin/claude', platform: 'linux', run });

    assert.equal(result.ok, true);
    assert.deepEqual(calls[0].spec.args, ['plugin', 'list', '--json']);
  });

  it('非零退出或非 JSON 都算不可用', async () => {
    const exit = fakeRun({ code: 1, stderr: 'unknown command' });
    assert.equal(
      (await probePluginList({ executable: 'x', platform: 'linux', run: exit.run })).ok,
      false,
    );

    const junk = fakeRun({ stdout: 'not json' });
    const result = await probePluginList({ executable: 'x', platform: 'linux', run: junk.run });
    assert.equal(result.ok, false);
    assert.equal(result.reason, 'unparsable-json');
  });
});

describe('进程执行', () => {
  it('runProcess 捕获输出与退出码', async () => {
    const spec = buildSpawnSpec(process.execPath, ['-e', 'process.stdout.write("hi"); process.exit(0)'], {
      platform: process.platform,
    });
    const result = await runProcess(spec, { timeoutMs: 5_000 });

    assert.equal(result.code, 0);
    assert.equal(result.stdout, 'hi');
    assert.equal(result.error, null);
    assert.equal(result.timedOut, false);
  });

  it('超时会杀掉进程并标记 timedOut', async () => {
    const spec = buildSpawnSpec(process.execPath, ['-e', 'setTimeout(() => {}, 60_000)'], {
      platform: process.platform,
    });
    const result = await runProcess(spec, { timeoutMs: 100 });

    assert.equal(result.timedOut, true);
  });

  it('失败描述包含退出码与 stderr 尾部', () => {
    assert.match(
      describeRunFailure({ code: 2, stderr: '第一行\n最后一行', stdout: '', timedOut: false, error: null }, 1_000),
      /退出码 2：最后一行/,
    );
    assert.match(
      describeRunFailure({ code: null, stderr: '', stdout: '', timedOut: true, error: null }, 5_000),
      /5 秒内没有返回/,
    );
  });
});
