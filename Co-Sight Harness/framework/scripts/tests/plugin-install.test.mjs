/**
 * 插件安装：判定表、状态解析、幂等与失败路径。
 *
 * 这些测试**不调用真的 claude**：`run` 与 `readState` 都是注入的。
 * 真机上"命令成功但状态没变"这种情况比命令失败更难查，所以这里把
 * 状态变化也当成 mock 的一部分来断言。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, describe, it } from 'node:test';

import { hashPluginDirectory } from '../lib/plugin-hash.mjs';
import {
  acquireInstallLock,
  decideMarketplaceAction,
  decidePluginAction,
  ensurePlugins,
  parseMarketplaceList,
  parsePluginList,
  readPluginState,
  readStateFromFiles,
  shouldInstallPlugins,
} from '../lib/plugin-install.mjs';

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-plugin-install-'));
after(() => fs.rmSync(scratch, { recursive: true, force: true }));

let counter = 0;
function freshDir(name) {
  counter += 1;
  const dir = path.join(scratch, `${name}-${counter}`);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function write(filePath, content = '') {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content);
}

/** 造一个最小插件目录，返回 `ensurePlugins` 需要的坐标对象。 */
function makePlugin(root, { dir = 'plug', plugin = 'plug', marketplace = 'market', version = '1.0.0' } = {}) {
  const pluginDir = path.join(root, dir);
  write(
    path.join(pluginDir, '.claude-plugin', 'plugin.json'),
    JSON.stringify({ name: plugin, version }),
  );
  write(
    path.join(pluginDir, '.claude-plugin', 'marketplace.json'),
    JSON.stringify({ name: marketplace, plugins: [{ name: plugin, source: '.' }] }),
  );
  write(path.join(pluginDir, 'commands', 'hello.md'), `# ${plugin}\n`);
  const { sha256, files } = hashPluginDirectory(pluginDir);
  return {
    id: dir,
    dir,
    plugin,
    marketplace,
    version,
    sha256,
    files,
    path: pluginDir,
  };
}

const OK_RESULT = { code: 0, signal: null, stdout: '{}', stderr: '', timedOut: false, error: null };

/**
 * 假 CLI + 假状态。命令执行会**真的改状态**，这样 `ensurePlugins`
 * 安装后的复核走的是和真机一样的路径。
 */
function makeHarness(initial = {}) {
  const state = {
    plugins: [...(initial.plugins ?? [])],
    marketplaces: [...(initial.marketplaces ?? [])],
  };
  const calls = [];
  const versions = new Map();

  const run = async (spec) => {
    const args = spec.args;
    calls.push(args.join(' '));

    if (args[0] === 'plugin' && args[1] === 'list') {
      return { ...OK_RESULT, stdout: JSON.stringify(state.plugins) };
    }
    if (args[0] === 'plugin' && args[1] === 'marketplace' && args[2] === 'list') {
      return { ...OK_RESULT, stdout: JSON.stringify(state.marketplaces) };
    }
    if (args[0] === 'plugin' && args[1] === 'marketplace' && args[2] === 'add') {
      const dir = args[3];
      const name = path.basename(dir);
      state.marketplaces = [
        ...state.marketplaces.filter((item) => item.name !== name),
        { name, source: 'directory', installLocation: dir },
      ];
      return OK_RESULT;
    }
    if (args[0] === 'plugin' && args[1] === 'marketplace' && args[2] === 'remove') {
      state.marketplaces = state.marketplaces.filter((item) => item.name !== args[3]);
      return OK_RESULT;
    }
    if (args[0] === 'plugin' && args[1] === 'uninstall') {
      state.plugins = state.plugins.filter((item) => item.id !== args[2]);
      return OK_RESULT;
    }
    if (args[0] === 'plugin' && (args[1] === 'install' || args[1] === 'update')) {
      const id = args[2];
      const marketplace = id.slice(id.indexOf('@') + 1);
      const canonical = state.marketplaces.find((item) => item.name === marketplace)?.installLocation;
      state.plugins = [
        ...state.plugins.filter((item) => item.id !== id),
        {
          id,
          version: versions.get(id) ?? id,
          scope: 'user',
          installPath: canonical ?? null,
        },
      ];
      return OK_RESULT;
    }
    return OK_RESULT;
  };

  const readState = async () => ({
    ok: true,
    source: 'cli',
    plugins: state.plugins.map((item) => ({ ...item })),
    marketplaces: state.marketplaces.map((item) => ({ ...item })),
    problems: [],
  });

  return { state, calls, run, readState, versions };
}

async function runEnsure(plugin, harness, extra = {}) {
  const home = freshDir('home');
  const configDir = path.join(freshDir('claude'), '.claude');
  fs.mkdirSync(configDir, { recursive: true });
  const result = await ensurePlugins({
    plugins: [plugin],
    executable: '/usr/bin/claude',
    home,
    configDir,
    platform: 'linux',
    run: harness.run,
    readState: harness.readState,
    ...extra,
  });
  return { result, configDir };
}

describe('decidePluginAction', () => {
  const base = { payloadVersion: '1.0.0', payloadHash: 'aaaa' };

  it('没装过就安装', () => {
    assert.equal(decidePluginAction({ ...base, installedVersion: null, cacheHash: null }), 'install');
  });

  it('版本不同就升级', () => {
    assert.equal(
      decidePluginAction({ ...base, installedVersion: '0.9.0', cacheHash: 'aaaa' }),
      'update',
    );
  });

  it('版本相同但内容不同就重装', () => {
    assert.equal(
      decidePluginAction({ ...base, installedVersion: '1.0.0', cacheHash: 'bbbb' }),
      'reinstall',
    );
  });

  it('版本与内容都相同就跳过', () => {
    assert.equal(
      decidePluginAction({ ...base, installedVersion: '1.0.0', cacheHash: 'aaaa' }),
      'none',
    );
  });
});

describe('decideMarketplaceAction', () => {
  const canonicalDir = path.join(path.sep, 'canonical', 'market');

  it('未注册就新增', () => {
    assert.equal(decideMarketplaceAction({ registered: null, canonicalDir }), 'add');
  });

  it('git 来源默认拒绝覆盖', () => {
    assert.equal(
      decideMarketplaceAction({
        registered: { source: { source: 'git', url: 'https://example.com/m.git' } },
        canonicalDir,
      }),
      'block',
    );
  });

  it('显式 --replace-marketplace 才替换 git 来源', () => {
    assert.equal(
      decideMarketplaceAction({
        registered: { source: 'git' },
        canonicalDir,
        replace: true,
      }),
      'replace',
    );
  });

  it('同名且位置就是产物副本时只刷新内容', () => {
    assert.equal(
      decideMarketplaceAction({
        registered: { source: 'directory', installLocation: canonicalDir },
        canonicalDir,
      }),
      'refresh',
    );
  });

  it('同名但位置不同就替换', () => {
    assert.equal(
      decideMarketplaceAction({
        registered: { source: 'directory', installLocation: path.join(path.sep, 'elsewhere') },
        canonicalDir,
      }),
      'replace',
    );
  });
});

describe('状态解析', () => {
  it('解析 plugin list --json', () => {
    const list = parsePluginList(
      JSON.stringify([
        { id: 'drive@zte-ai-lab', version: '2.3.4', scope: 'user', installPath: '/cache/drive' },
        { nope: true },
      ]),
    );
    assert.deepEqual(list, [
      {
        id: 'drive@zte-ai-lab',
        plugin: 'drive',
        marketplace: 'zte-ai-lab',
        version: '2.3.4',
        scope: 'user',
        installPath: '/cache/drive',
      },
    ]);
  });

  it('解析 marketplace list --json', () => {
    const list = parseMarketplaceList(
      JSON.stringify([{ name: 'market', source: 'directory', installLocation: '/m' }]),
    );
    assert.deepEqual(list, [{ name: 'market', source: 'directory', installLocation: '/m' }]);
  });

  it('非数组输出直接报错', () => {
    assert.throws(() => parsePluginList('{}'), /不是数组/);
    assert.throws(() => parseMarketplaceList('null'), /不是数组/);
  });

  it('状态文件兜底，同 id 优先 user scope', () => {
    const configDir = freshDir('config-files');
    write(
      path.join(configDir, 'plugins', 'installed_plugins.json'),
      JSON.stringify({
        version: 2,
        plugins: {
          'drive@zte-ai-lab': [
            { scope: 'project', installPath: '/p', version: '1.0.0' },
            { scope: 'user', installPath: '/u', version: '2.0.0' },
          ],
        },
      }),
    );
    write(
      path.join(configDir, 'plugins', 'known_marketplaces.json'),
      JSON.stringify({
        'zte-ai-lab': {
          source: { source: 'directory', url: '/local/zte-ai-lab' },
          installLocation: '/local/zte-ai-lab',
        },
      }),
    );

    const state = readStateFromFiles(configDir);
    assert.equal(state.plugins.length, 1);
    assert.deepEqual(
      { version: state.plugins[0].version, scope: state.plugins[0].scope },
      { version: '2.0.0', scope: 'user' },
    );
    assert.equal(state.marketplaces[0].name, 'zte-ai-lab');
    assert.equal(state.marketplaces[0].installLocation, '/local/zte-ai-lab');
  });

  it('两个状态文件都不存在时返回 null', () => {
    assert.equal(readStateFromFiles(freshDir('empty-config')), null);
  });

  it('CLI 不可用时回落到状态文件', async () => {
    const configDir = freshDir('fallback');
    write(
      path.join(configDir, 'plugins', 'installed_plugins.json'),
      JSON.stringify({ version: 2, plugins: {} }),
    );
    write(
      path.join(configDir, 'plugins', 'known_marketplaces.json'),
      JSON.stringify({}),
    );

    const state = await readPluginState({
      executable: '/usr/bin/claude',
      platform: 'linux',
      configDir,
      run: async () => ({ ...OK_RESULT, code: 1, stderr: 'unknown command' }),
    });
    assert.equal(state.ok, true);
    assert.equal(state.source, 'files');
    assert.equal(state.problems.length, 2);
  });
});

describe('ensurePlugins', () => {
  it('首次安装：复制载荷、注册市场、装插件并复核', async () => {
    const plugin = makePlugin(freshDir('payload'));
    const harness = makeHarness();
    harness.versions.set(`${plugin.plugin}@${plugin.marketplace}`, plugin.version);

    const { result, configDir } = await runEnsure(plugin, harness);

    assert.equal(result.ok, true, JSON.stringify(result.failure));
    assert.deepEqual(
      result.steps.map((step) => step.action),
      ['install'],
    );
    assert.ok(
      fs.existsSync(
        path.join(configDir, 'plugins', 'marketplaces', plugin.marketplace, 'commands', 'hello.md'),
      ),
    );
    assert.ok(harness.calls.includes(`plugin install ${plugin.plugin}@${plugin.marketplace} --scope user --json -y`));
  });

  it('第二次运行内容一致：不重复安装', async () => {
    const plugin = makePlugin(freshDir('payload'));
    const harness = makeHarness();
    harness.versions.set(`${plugin.plugin}@${plugin.marketplace}`, plugin.version);

    const first = await runEnsure(plugin, harness);
    assert.equal(first.result.ok, true);

    // 用同一份状态再跑一次。
    const second = await ensurePlugins({
      plugins: [plugin],
      executable: '/usr/bin/claude',
      home: freshDir('home'),
      configDir: first.configDir,
      platform: 'linux',
      run: harness.run,
      readState: harness.readState,
    });

    assert.equal(second.ok, true, JSON.stringify(second.failure));
    assert.deepEqual(
      second.steps.map((step) => step.action),
      ['none'],
    );
    const installs = harness.calls.filter((line) => line.startsWith('plugin install '));
    assert.equal(installs.length, 1);
    const adds = harness.calls.filter((line) => line.startsWith('plugin marketplace add '));
    assert.equal(adds.length, 1);
  });

  it('版本不同走升级', async () => {
    const plugin = makePlugin(freshDir('payload'), { version: '2.0.0' });
    const harness = makeHarness({
      plugins: [
        {
          id: `${plugin.plugin}@${plugin.marketplace}`,
          version: '1.0.0',
          scope: 'user',
          installPath: makePlugin(freshDir('old'), { version: '1.0.0' }).path,
        },
      ],
      marketplaces: [],
    });
    harness.versions.set(`${plugin.plugin}@${plugin.marketplace}`, '2.0.0');

    const { result } = await runEnsure(plugin, harness);
    assert.equal(result.ok, true, JSON.stringify(result.failure));
    assert.deepEqual(
      result.steps.map((step) => step.action),
      ['update'],
    );
    assert.ok(harness.calls.includes(`plugin update ${plugin.plugin}@${plugin.marketplace} --scope user --json -y`));
  });

  it('版本相同但内容不同走重装', async () => {
    const plugin = makePlugin(freshDir('payload'), { version: '1.0.0' });
    const old = makePlugin(freshDir('old'), { version: '1.0.0' });
    write(path.join(old.path, 'commands', 'hello.md'), '# drifted\n');

    const harness = makeHarness({
      plugins: [
        {
          id: `${plugin.plugin}@${plugin.marketplace}`,
          version: '1.0.0',
          scope: 'user',
          installPath: old.path,
        },
      ],
    });
    harness.versions.set(`${plugin.plugin}@${plugin.marketplace}`, '1.0.0');

    const { result } = await runEnsure(plugin, harness);
    assert.equal(result.ok, true, JSON.stringify(result.failure));
    assert.deepEqual(
      result.steps.map((step) => step.action),
      ['reinstall'],
    );
    assert.ok(harness.calls.some((line) => line.startsWith('plugin uninstall ')));
    assert.ok(harness.calls.some((line) => line.startsWith('plugin install ')));
  });

  it('同名 git 市场默认拒绝覆盖，并给出处理办法', async () => {
    const plugin = makePlugin(freshDir('payload'));
    const harness = makeHarness({
      plugins: [],
      marketplaces: [
        {
          name: plugin.marketplace,
          source: { source: 'git', url: 'https://example.com/other.git' },
          installLocation: '/somewhere/else',
        },
      ],
    });

    const { result } = await runEnsure(plugin, harness);
    assert.equal(result.ok, false);
    assert.match(result.failure.detail, /git/);
    assert.ok(result.failure.remedy.some((line) => line.includes('--replace-marketplace')));
    assert.equal(harness.calls.length, 0);
  });

  it('--replace-marketplace 时先移除再注册', async () => {
    const plugin = makePlugin(freshDir('payload'));
    const harness = makeHarness({
      plugins: [],
      marketplaces: [
        { name: plugin.marketplace, source: 'git', installLocation: '/somewhere/else' },
      ],
    });
    harness.versions.set(`${plugin.plugin}@${plugin.marketplace}`, plugin.version);

    const { result } = await runEnsure(plugin, harness, { replaceMarketplace: true });
    assert.equal(result.ok, true, JSON.stringify(result.failure));
    assert.ok(
      harness.calls.includes(`plugin marketplace remove ${plugin.marketplace} --scope user --json`),
    );
  });

  it('安装命令失败时报告插件、命令与原因', async () => {
    const plugin = makePlugin(freshDir('payload'));
    const harness = makeHarness();
    const failingRun = async (spec) => {
      if (spec.args[0] === 'plugin' && spec.args[1] === 'install') {
        return { ...OK_RESULT, code: 1, stderr: 'network down' };
      }
      return harness.run(spec);
    };

    const { result } = await runEnsure(plugin, harness, { run: failingRun });
    assert.equal(result.ok, false);
    assert.equal(result.failure.plugin, plugin.id);
    assert.match(result.failure.command, /plugin install/);
    assert.match(result.failure.detail, /network down/);
  });

  it('命令成功但版本没变，复核仍然失败', async () => {
    const plugin = makePlugin(freshDir('payload'), { version: '2.0.0' });
    const harness = makeHarness();
    // 故意不登记新版本：模拟 marketplace 没指向产物副本。
    harness.versions.set(`${plugin.plugin}@${plugin.marketplace}`, '1.0.0');

    const { result } = await runEnsure(plugin, harness);
    assert.equal(result.ok, false);
    assert.match(result.failure.detail, /装上的版本是 1\.0\.0/);
  });

  it('同一个 marketplace 由两个目录提供时拒绝继续', async () => {
    const root = freshDir('dup');
    const one = makePlugin(root, { dir: 'one', plugin: 'one' });
    const two = makePlugin(root, { dir: 'two', plugin: 'two' });
    const harness = makeHarness();

    const home = freshDir('home');
    const configDir = path.join(freshDir('claude'), '.claude');
    const result = await ensurePlugins({
      plugins: [one, two],
      executable: '/usr/bin/claude',
      home,
      configDir,
      platform: 'linux',
      run: harness.run,
      readState: harness.readState,
    });

    assert.equal(result.ok, false);
    assert.match(result.failure.detail, /同时由/);
  });
});

describe('shouldInstallPlugins', () => {
  const repo = { layoutMode: '仓库布局', pluginMode: 'repo' };
  const artifact = { layoutMode: '产物布局', pluginMode: 'artifact' };

  it('--install --skip-plugins 必须跳过（曾经绕过判定写进 ~/.claude）', () => {
    assert.equal(shouldInstallPlugins({ ...repo, install: true, skipPlugins: true }), false);
    assert.equal(shouldInstallPlugins({ ...artifact, skipPlugins: true }), false);
  });

  it('仓库布局下只有显式 --install 才装', () => {
    assert.equal(shouldInstallPlugins({ ...repo }), false);
    assert.equal(shouldInstallPlugins({ ...repo, install: true }), true);
  });

  it('产物布局下启动即装', () => {
    assert.equal(shouldInstallPlugins({ ...artifact }), true);
  });

  it('没有插件载荷时即使 --install 也不装', () => {
    assert.equal(
      shouldInstallPlugins({ layoutMode: '产物布局', pluginMode: 'none', install: true }),
      false,
    );
  });
});

describe('acquireInstallLock', () => {
  it('第二个进程拿不到锁；释放后可以重新拿到', () => {
    const home = freshDir('lock');
    const first = acquireInstallLock(home);
    assert.throws(() => acquireInstallLock(home), /另一个安装进程/);

    first.release();
    const second = acquireInstallLock(home);
    second.release();
    assert.equal(fs.existsSync(path.join(home, '.install.lock')), false);
  });
});
