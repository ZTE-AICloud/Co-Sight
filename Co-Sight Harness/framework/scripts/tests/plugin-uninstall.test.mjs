/**
 * 插件卸载：坐标清单、判定表、执行顺序、失败路径与载荷清理。
 *
 * 与 `plugin-install.test.mjs` 同一套路数：`run` 与 `readState` 都注入，
 * 假 CLI 会**真的改状态**——这样"卸载完再读一次状态"走的是和真机一样的路径，
 * "命令成功但状态没变"这类问题才会在测试里露头。
 *
 * 这里最要紧的两条断言不是"删掉了什么"，而是"没删什么"：
 *   - 别人的插件还挂在同一个市场上时，那个市场必须留着；
 *   - 插件还在的时候，不能先删市场（会留下悬空的注册项）。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

import { MARKETPLACES_SUBDIR } from '../lib/plugin-install.mjs';
import {
  BUNDLED_PLUGIN_COORDINATES,
  directorySize,
  planRetirement,
  pluginIdOf,
  retirePlugins,
} from '../lib/plugin-uninstall.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-plugin-uninstall-'));
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

const OK_RESULT = { code: 0, signal: null, stdout: '{}', stderr: '', timedOut: false, error: null };

const ALL_IDS = BUNDLED_PLUGIN_COORDINATES.map(pluginIdOf);

/**
 * 假 CLI + 假状态：`uninstall` 与 `marketplace remove` 会真的把状态改掉。
 *
 * `failOn` 让包含该子串的命令返回非零，用来测"卸到一半失败"。
 */
function makeHarness({ plugins = ALL_IDS, marketplaces = [], failOn = null } = {}) {
  const state = {
    plugins: [...plugins],
    marketplaces: [...marketplaces],
  };
  const calls = [];
  let reads = 0;

  const run = async (spec) => {
    const args = spec.args;
    const text = args.join(' ');
    calls.push(text);
    if (failOn !== null && text.includes(failOn)) {
      return { ...OK_RESULT, code: 1, stderr: 'boom' };
    }
    if (args[0] === 'plugin' && args[1] === 'uninstall') {
      state.plugins = state.plugins.filter((id) => id !== args[2]);
      return OK_RESULT;
    }
    if (args[0] === 'plugin' && args[1] === 'marketplace' && args[2] === 'remove') {
      // 状态里存的是市场名字符串，`readState` 才把它们包成对象。
      state.marketplaces = state.marketplaces.filter((name) => name !== args[3]);
      return OK_RESULT;
    }
    return OK_RESULT;
  };

  const readState = async () => {
    reads += 1;
    return {
      ok: true,
      source: 'cli',
      plugins: state.plugins.map((id) => ({ id, version: '1.0.0', scope: 'user' })),
      marketplaces: state.marketplaces.map((name) => ({ name, source: 'directory' })),
      problems: [],
    };
  };

  return {
    run,
    readState,
    calls,
    state,
    get reads() {
      return reads;
    },
  };
}

/** 造 `<configDir>/plugins/marketplaces/<name>`，返回 configDir。 */
function makeConfigDir(names = []) {
  const configDir = freshDir('claude');
  for (const name of names) {
    write(path.join(configDir, MARKETPLACES_SUBDIR, name, 'plugin.json'), '{"name":"x"}');
  }
  return configDir;
}

describe('BUNDLED_PLUGIN_COORDINATES', () => {
  it('与 artifact/plugins.json 的插件/市场坐标逐项一致', () => {
    const manifest = JSON.parse(
      fs.readFileSync(path.join(here, '..', 'artifact', 'plugins.json'), 'utf8'),
    );
    const fromManifest = manifest.plugins.map((entry) => ({
      plugin: entry.plugin,
      marketplace: entry.marketplace,
    }));
    assert.deepEqual(BUNDLED_PLUGIN_COORDINATES, fromManifest);
  });

  it('插件 id 是 <plugin>@<marketplace>', () => {
    assert.equal(
      pluginIdOf({ plugin: 'skill-optimizer', marketplace: 'skillx' }),
      'skill-optimizer@skillx',
    );
  });
});

describe('planRetirement', () => {
  it('五个都装着、五个市场都注册着：全部标为存在', () => {
    const plan = planRetirement({
      state: {
        plugins: ALL_IDS.map((id) => ({ id })),
        marketplaces: ['zte-ai-lab', 'agent-genesis', 'goldeval', 'skillx', 'cosightbot'].map(
          (name) => ({ name }),
        ),
      },
    });
    assert.deepEqual(
      plan.plugins.map((item) => [item.id, item.present]),
      ALL_IDS.map((id) => [id, true]),
    );
    assert.deepEqual(
      plan.marketplaces.map((item) => [item.name, item.present, item.foreign]),
      [
        ['zte-ai-lab', true, []],
        ['agent-genesis', true, []],
        ['goldeval', true, []],
        ['skillx', true, []],
        ['cosightbot', true, []],
      ],
    );
  });

  it('没装过的标为 absent，而不是错误', () => {
    const plan = planRetirement({ state: { plugins: [], marketplaces: [] } });
    assert.equal(
      plan.plugins.every((item) => item.present === false),
      true,
    );
    assert.equal(
      plan.marketplaces.every((item) => item.present === false),
      true,
    );
  });

  it('同一个市场下还有别人的插件时，记进 foreign（该市场不能删）', () => {
    const plan = planRetirement({
      state: {
        plugins: [{ id: 'drive@zte-ai-lab' }, { id: 'their-tool@zte-ai-lab' }],
        marketplaces: [{ name: 'zte-ai-lab' }],
      },
    });
    const market = plan.marketplaces.find((item) => item.name === 'zte-ai-lab');
    assert.deepEqual(market.foreign, ['their-tool@zte-ai-lab']);
    // 其它市场不受牵连。
    assert.deepEqual(
      plan.marketplaces.filter((item) => item.name !== 'zte-ai-lab').map((item) => item.foreign),
      [[], [], [], []],
    );
  });

  it('插件名里带 @（scoped）时，市场名按最后一个 @ 切', () => {
    const plan = planRetirement({
      state: {
        plugins: [{ id: '@scope/tool@skillx' }],
        marketplaces: [{ name: 'skillx' }],
      },
    });
    const market = plan.marketplaces.find((item) => item.name === 'skillx');
    assert.deepEqual(market.foreign, ['@scope/tool@skillx']);
  });
});

describe('directorySize', () => {
  it('累加文件大小；路径不存在时返回 0 而不是抛错', () => {
    const dir = freshDir('size');
    write(path.join(dir, 'a.txt'), 'x'.repeat(10));
    write(path.join(dir, 'nested', 'b.txt'), 'x'.repeat(5));
    assert.equal(directorySize(dir), 15);
    assert.equal(directorySize(path.join(dir, 'nope')), 0);
  });
});

describe('retirePlugins', () => {
  it('先卸插件再摘市场，并清掉市场目录下的载荷副本', async () => {
    const configDir = makeConfigDir(['zte-ai-lab']);
    const harness = makeHarness({ marketplaces: ['zte-ai-lab'] });

    const outcome = await retirePlugins({
      executable: '/fake/claude',
      configDir,
      run: harness.run,
      readState: harness.readState,
    });

    assert.equal(outcome.ok, true);
    assert.equal(outcome.failure, null);

    // 顺序：五条 uninstall 都在那条 marketplace remove 之前。
    const removeCommand = 'plugin marketplace remove zte-ai-lab --scope user --json';
    const removeIndex = harness.calls.indexOf(removeCommand);
    assert.notEqual(removeIndex, -1);
    for (const id of ALL_IDS) {
      const uninstallIndex = harness.calls.indexOf(`plugin uninstall ${id} --scope user --json`);
      assert.notEqual(uninstallIndex, -1, `缺 ${id} 的卸载命令`);
      assert.ok(uninstallIndex < removeIndex, `${id} 必须在摘市场之前卸掉`);
    }

    // 状态真的变了。
    assert.deepEqual(harness.state.plugins, []);
    assert.deepEqual(harness.state.marketplaces, []);
    assert.equal(harness.reads, 2, '卸载完必须再读一次状态');

    const market = outcome.steps.find((step) => step.kind === 'marketplace');
    assert.equal(market.action, 'removed');
    assert.ok(market.purgedBytes > 0, '应报告清掉了多少字节');
    assert.equal(
      fs.existsSync(path.join(configDir, MARKETPLACES_SUBDIR, 'zte-ai-lab')),
      false,
      '载荷副本应被删掉',
    );
  });

  it('别人的插件还挂在同一个市场上：跳过该市场，不动它的目录', async () => {
    const configDir = makeConfigDir(['zte-ai-lab']);
    const harness = makeHarness({
      plugins: [...ALL_IDS, 'their-tool@zte-ai-lab'],
      marketplaces: ['zte-ai-lab'],
    });

    const outcome = await retirePlugins({
      executable: '/fake/claude',
      configDir,
      run: harness.run,
      readState: harness.readState,
    });

    assert.equal(outcome.ok, true);
    assert.equal(
      harness.calls.some((call) => call.startsWith('plugin marketplace remove')),
      false,
    );
    const market = outcome.steps.find((step) => step.kind === 'marketplace');
    assert.equal(market.action, 'kept-in-use');
    assert.deepEqual(market.foreign, ['their-tool@zte-ai-lab']);
    assert.equal(
      fs.existsSync(path.join(configDir, MARKETPLACES_SUBDIR, 'zte-ai-lab')),
      true,
      '别人的市场目录必须还在',
    );
  });

  it('--dry-run：不执行任何命令、不动文件系统，只报告将要做什么', async () => {
    const configDir = makeConfigDir(['zte-ai-lab']);
    const harness = makeHarness({ marketplaces: ['zte-ai-lab'] });

    const outcome = await retirePlugins({
      executable: '/fake/claude',
      configDir,
      dryRun: true,
      run: harness.run,
      readState: harness.readState,
    });

    assert.equal(outcome.ok, true);
    assert.deepEqual(harness.calls, []);
    assert.equal(harness.reads, 1, 'dry-run 不必读第二次状态');
    assert.equal(
      outcome.steps.filter((step) => step.kind === 'plugin' && step.action === 'planned').length,
      ALL_IDS.length,
    );
    const market = outcome.steps.find((step) => step.kind === 'marketplace');
    assert.equal(market.action, 'planned');
    assert.match(market.command, /plugin marketplace remove zte-ai-lab/);
    assert.equal(fs.existsSync(path.join(configDir, MARKETPLACES_SUBDIR, 'zte-ai-lab')), true);
  });

  it('本来就没装：幂等地成功，不执行任何命令', async () => {
    const harness = makeHarness({ plugins: [], marketplaces: [] });
    const outcome = await retirePlugins({
      executable: '/fake/claude',
      configDir: makeConfigDir(),
      run: harness.run,
      readState: harness.readState,
    });

    assert.equal(outcome.ok, true);
    assert.deepEqual(harness.calls, []);
    assert.equal(
      outcome.steps.every((step) => step.action === 'absent'),
      true,
    );
  });

  it('某个卸载命令失败：立即停下，带上命令与原因，不再继续摘市场', async () => {
    const harness = makeHarness({
      marketplaces: ['zte-ai-lab'],
      failOn: 'uninstall agent-genesis@agent-genesis',
    });

    const outcome = await retirePlugins({
      executable: '/fake/claude',
      configDir: makeConfigDir(['zte-ai-lab']),
      run: harness.run,
      readState: harness.readState,
    });

    assert.equal(outcome.ok, false);
    assert.match(outcome.failure.command, /uninstall agent-genesis@agent-genesis/);
    assert.match(outcome.failure.detail, /退出码 1|boom/);
    assert.ok(Array.isArray(outcome.failure.remedy) && outcome.failure.remedy.length > 0);
    assert.equal(
      harness.calls.some((call) => call.startsWith('plugin marketplace remove')),
      false,
      '失败后不该再动市场',
    );
    // 已经卸掉的那个留在 steps 里，好让用户知道现在的实际状态。
    assert.equal(outcome.steps.filter((step) => step.action === 'removed').length, 1);
  });

  it('读不到状态：失败并给出补救，且不执行任何卸载命令', async () => {
    const harness = makeHarness();
    const outcome = await retirePlugins({
      executable: '/fake/claude',
      configDir: makeConfigDir(),
      run: harness.run,
      readState: async () => ({ ok: false, problems: ['claude 不在 PATH 上'] }),
    });

    assert.equal(outcome.ok, false);
    assert.match(outcome.failure.detail, /claude 不在 PATH 上/);
    assert.deepEqual(outcome.steps, []);
    assert.deepEqual(harness.calls, []);
  });

  it('市场名里带 ../ 时不越界删除', async () => {
    /*
     * 模拟"状态文件里写着这么一个市场名"（真实 CLI 不会给，但它来自磁盘文件，
     * 属于外部数据）。卸载最多只能删市场根之下的东西，不能顺着 ../ 删到外面。
     */
    const configDir = makeConfigDir();
    const outside = path.join(configDir, 'outside');
    write(path.join(outside, 'keep.txt'), 'keep');

    const harness = makeHarness({
      plugins: ['evil@outside'],
      marketplaces: [{ name: '../outside' }],
    });

    const outcome = await retirePlugins({
      executable: '/fake/claude',
      configDir,
      coordinates: [{ plugin: 'evil', marketplace: '../outside' }],
      run: harness.run,
      readState: harness.readState,
    });

    assert.equal(outcome.ok, true);
    assert.equal(
      fs.existsSync(path.join(outside, 'keep.txt')),
      true,
      '市场根之外的目录一个字节都不能少',
    );
  });
});
