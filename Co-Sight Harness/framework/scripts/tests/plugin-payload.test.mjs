/**
 * 插件载荷：文件集合、内容哈希、清单交叉校验、启动前检查。
 *
 * 全是本地临时目录，不碰真实插件仓库，也不装任何东西。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, describe, it } from 'node:test';

import { pluginsCheck } from '../lib/checks/plugins.mjs';
import {
  collectPluginFiles,
  hashPluginDirectory,
  hashPluginEntries,
  isExcludedPluginPath,
} from '../lib/plugin-hash.mjs';
import {
  describePlugins,
  loadHostManifest,
  readPluginMetadata,
} from '../lib/plugin-index.mjs';
import { runChecks } from '../lib/preflight.mjs';

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-plugin-payload-'));
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

/** 造一个最小可识别的插件目录。 */
function makePlugin(root, { dir, plugin, marketplace, version, extra = {} }) {
  const pluginDir = path.join(root, dir);
  write(
    path.join(pluginDir, '.claude-plugin', 'plugin.json'),
    JSON.stringify({ name: plugin, version, description: `${plugin} 测试用` }),
  );
  write(
    path.join(pluginDir, '.claude-plugin', 'marketplace.json'),
    JSON.stringify({
      name: marketplace,
      plugins: [{ name: plugin, source: '.', ...extra }],
    }),
  );
  write(path.join(pluginDir, 'commands', 'hello.md'), `# ${plugin}\n`);
  return pluginDir;
}

function makeManifest(root, plugins) {
  const manifestPath = path.join(root, 'scripts', 'artifact', 'plugins.json');
  write(
    manifestPath,
    JSON.stringify({
      schemaVersion: 1,
      plugins: plugins.map((item) => ({
        dir: item.dir,
        plugin: item.plugin,
        marketplace: item.marketplace,
        requires: item.requires ?? { bins: [] },
      })),
    }),
  );
  return manifestPath;
}

describe('插件文件集合与哈希', () => {
  it('排除测试、缓存与本机配置', () => {
    for (const excluded of [
      'tests/a.md',
      'nested/__pycache__/x.pyc',
      'nested/.pytest_cache/x',
      'nested/.ruff_cache/x',
      'nested/b.pyc',
      '.git/config',
      'node_modules/x/index.js',
      '.claude/settings.json',
      '.env',
      'work/x',
      'output/x',
      '.agent-genesis/x',
    ]) {
      assert.equal(isExcludedPluginPath(excluded), true, excluded);
    }
    for (const kept of ['SKILL.md', 'skills/a/SKILL.md', '.claude-plugin/plugin.json', 'env.example']) {
      assert.equal(isExcludedPluginPath(kept), false, kept);
    }
  });

  it('列出排序后的相对路径，符号链接直接报错', () => {
    const root = freshDir('collect');
    write(path.join(root, 'b.md'), 'b');
    write(path.join(root, 'a', 'z.md'), 'z');
    write(path.join(root, 'tests', 'ignored.md'), 'x');

    assert.deepEqual(collectPluginFiles(root), ['a/z.md', 'b.md']);

    if (process.platform !== 'win32') {
      fs.symlinkSync(path.join(root, 'b.md'), path.join(root, 'link.md'));
      assert.throws(() => collectPluginFiles(root), /符号链接/);
    }
  });

  it('内容变一点，哈希就变；目录哈希与归档条目哈希一致', () => {
    const root = freshDir('hash');
    write(path.join(root, 'a.md'), '原内容');
    const before = hashPluginDirectory(root);
    assert.equal(before.files, 1);
    assert.match(before.sha256, /^[0-9a-f]{16}$/);

    write(path.join(root, 'a.md'), '改过的内容');
    const modified = hashPluginDirectory(root);
    assert.notEqual(modified.sha256, before.sha256);

    const entries = collectPluginFiles(root).map((relative) => ({
      path: `base/plugins/demo/${relative}`,
      kind: 'file',
      read: () => fs.readFileSync(path.join(root, relative)),
    }));
    assert.equal(hashPluginEntries(entries, 'base/plugins/demo').sha256, modified.sha256);

    // 同内容不同位置：路径参与哈希，结果应当不同。
    write(path.join(root, 'b.md'), '改过的内容');
    assert.notEqual(hashPluginDirectory(root).sha256, modified.sha256);
  });
});

describe('插件清单', () => {
  it('正常清单给出插件名、市场名与版本', () => {
    const root = freshDir('meta-ok');
    const dir = makePlugin(root, {
      dir: 'drive',
      plugin: 'drive',
      marketplace: 'zte-ai-lab',
      version: '2.3.4',
    });
    const metadata = readPluginMetadata(dir);

    assert.equal(metadata.ok, true);
    assert.equal(metadata.plugin, 'drive');
    assert.equal(metadata.marketplace, 'zte-ai-lab');
    assert.equal(metadata.version, '2.3.4');
  });

  it('缺文件、缺字段、版本不一致都要说出来', () => {
    const root = freshDir('meta-bad');
    const missing = makePlugin(root, {
      dir: 'a',
      plugin: 'a',
      marketplace: 'm',
      version: '1.0.0',
    });
    fs.rmSync(path.join(missing, '.claude-plugin', 'marketplace.json'));
    assert.match(readPluginMetadata(missing).problems.join('\n'), /读不到/);

    const mismatch = makePlugin(root, {
      dir: 'b',
      plugin: 'b',
      marketplace: 'm',
      version: '1.0.0',
      extra: { version: '2.0.0' },
    });
    assert.match(readPluginMetadata(mismatch).problems.join('\n'), /不一致/);
  });

  it('宿主清单拒绝路径穿越与重复目录', () => {
    const root = freshDir('manifest-bad');
    const manifestPath = path.join(root, 'plugins.json');
    write(
      manifestPath,
      JSON.stringify({
        plugins: [
          { dir: '../evil', plugin: 'x', marketplace: 'm' },
          { dir: 'drive', plugin: 'drive', marketplace: 'zte-ai-lab' },
          { dir: 'drive', plugin: 'drive', marketplace: 'zte-ai-lab' },
        ],
      }),
    );

    const manifest = loadHostManifest(manifestPath);
    assert.equal(manifest.ok, false);
    assert.equal(manifest.plugins.length, 1);
    assert.match(manifest.problems.join('\n'), /不是安全的目录名/);
    assert.match(manifest.problems.join('\n'), /dir 重复/);
  });

  it('仓库布局：从目录读版本并算哈希', () => {
    const root = freshDir('repo');
    makePlugin(root, { dir: 'drive', plugin: 'drive', marketplace: 'zte-ai-lab', version: '2.3.4' });
    makePlugin(root, {
      dir: 'agent-evaluator',
      plugin: 'goldeval',
      marketplace: 'goldeval',
      version: '1.0.0',
    });
    const manifestPath = makeManifest(root, [
      { dir: 'drive', plugin: 'drive', marketplace: 'zte-ai-lab', requires: { bins: ['python3'] } },
      { dir: 'agent-evaluator', plugin: 'goldeval', marketplace: 'goldeval' },
    ]);

    const report = describePlugins({ manifestPath, sourceRoot: root });
    assert.equal(report.mode, 'repo');
    assert.deepEqual(report.problems, []);
    assert.equal(report.plugins.length, 2);
    assert.match(report.line, /drive 2\.3\.4、goldeval 1\.0\.0/);
    assert.deepEqual(report.plugins[0].requires.bins, ['python3']);
    assert.match(report.plugins[0].sha256, /^[0-9a-f]{16}$/);
  });
});

function makeArtifact(names) {
  const root = freshDir('artifact');
  const pluginsDir = path.join(root, 'plugins');
  const index = { schemaVersion: 1, plugins: [] };

  for (const item of names) {
    const pluginDir = makePlugin(pluginsDir, item);
    const hash = hashPluginDirectory(pluginDir);
    index.plugins.push({
      id: item.dir,
      dir: item.dir,
      plugin: item.plugin,
      marketplace: item.marketplace,
      version: item.version,
      sha256: hash.sha256,
      files: hash.files,
      requires: item.requires ?? { bins: [] },
    });
  }

  write(path.join(pluginsDir, 'index.json'), JSON.stringify(index));
  return { root, pluginsDir };
}

describe('产物布局', () => {
  const FIVE = [
    { dir: 'drive', plugin: 'drive', marketplace: 'zte-ai-lab', version: '2.3.4' },
    { dir: 'agent-genesis', plugin: 'agent-genesis', marketplace: 'agent-genesis', version: '0.21.0' },
    { dir: 'agent-evaluator', plugin: 'goldeval', marketplace: 'goldeval', version: '1.0.0' },
    { dir: 'skill-optimizer', plugin: 'skill-optimizer', marketplace: 'skillx', version: '1.0.0' },
    { dir: 'cosight-bot', plugin: 'cosightbot', marketplace: 'cosightbot', version: '0.1.0' },
  ];

  it('index 与目录一致时通过', () => {
    const { pluginsDir } = makeArtifact(FIVE);
    const report = describePlugins({ pluginsDir });

    assert.equal(report.mode, 'artifact');
    assert.deepEqual(report.problems, []);
    assert.equal(report.plugins.length, 5);
    assert.match(report.line, /5 个/);
  });

  it('内容被改动后哈希对不上', () => {
    const { pluginsDir } = makeArtifact(FIVE);
    write(path.join(pluginsDir, 'skill-optimizer', 'commands', 'hello.md'), '# 改过\n');

    const report = describePlugins({ pluginsDir });
    assert.match(report.problems.join('\n'), /内容哈希/);
  });

  it('缺目录、缺 index 都要报出来', () => {
    const { pluginsDir } = makeArtifact(FIVE);
    fs.rmSync(path.join(pluginsDir, 'drive'), { recursive: true, force: true });
    assert.match(describePlugins({ pluginsDir }).problems.join('\n'), /缺少目录 plugins\/drive/);

    const empty = freshDir('artifact-empty');
    const emptyPlugins = path.join(empty, 'plugins');
    fs.mkdirSync(emptyPlugins);
    assert.match(describePlugins({ pluginsDir: emptyPlugins }).problems.join('\n'), /读不到/);
  });
});

function reportOf(mode, dirs, problems = []) {
  return {
    mode,
    plugins: dirs.map((dir) => ({ dir, plugin: dir, version: '1.0.0', files: 3 })),
    problems,
    line: `${dirs.length} 个：${dirs.join('、')}`,
  };
}

describe('启动前的插件检查', () => {
  const FIVE = ['drive', 'agent-genesis', 'agent-evaluator', 'skill-optimizer', 'cosight-bot'];

  it('五个齐全时通过，并给出文件总数', async () => {
    const [result] = await runChecks([pluginsCheck({ pluginReport: reportOf('artifact', FIVE) })]);
    assert.equal(result.ok, true);
    assert.match(result.detail, /产物，共 15 个文件/);
  });

  it('少一个就失败，并点名', async () => {
    const [result] = await runChecks([
      pluginsCheck({ pluginReport: reportOf('artifact', FIVE.slice(1)) }),
    ]);
    assert.equal(result.ok, false);
    assert.match(result.remedy.join('\n'), /缺少插件 drive/);
    assert.match(result.remedy.join('\n'), /--skip-plugins/);
  });

  it('产物布局下没有载荷算失败，仓库布局下算跳过', async () => {
    const [required] = await runChecks([
      pluginsCheck({ pluginReport: reportOf('none', []), required: true }),
    ]);
    assert.equal(required.ok, false);

    const [optional] = await runChecks([
      pluginsCheck({ pluginReport: reportOf('none', []), required: false }),
    ]);
    assert.equal(optional.ok, true);
  });

  it('清单问题原样带进报告', async () => {
    const [result] = await runChecks([
      pluginsCheck({ pluginReport: reportOf('repo', FIVE, ['插件 drive：版本是 1.0.0，清单写的是 2.0.0']) }),
    ]);
    assert.equal(result.ok, false);
    assert.match(result.detail, /1 处问题/);
    assert.match(result.remedy[0], /版本是 1\.0\.0/);
  });
});
