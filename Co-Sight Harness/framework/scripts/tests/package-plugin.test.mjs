/**
 * 插件安装包的纯逻辑。
 *
 * 这些断言守的是**打包期**才暴露的问题：哪些目录不能进包（尤其是 `.env` 与
 * pipeline 过程产物）、插件清单自带的声明是否被真的用上、随包生成的安装脚本
 * 是否以包根目录为基准。它们错了不会在本机报错，而是变成"用户装不上"或
 * "把本机配置发出去了"。
 *
 * 与其它脚本测试一样：不跑 claude、不碰网络，只对纯函数与清单断言。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';

import {
  buildCompatibleManifest,
  declaredPluginPaths,
  executablePluginPaths,
  generatedPluginEntries,
  isExcluded,
  manifestCompatAdjustments,
  manifestOverrideEntry,
  pluginArchivePaths,
  readPluginMetadata,
  renderGeneratedFiles,
} from '../lib/plugin-package.mjs';
import { REPO_ROOT } from '../lib/project.mjs';

const AGENT_GENESIS_DIR = path.join(REPO_ROOT, 'agent-genesis');

/** 在临时目录里铺一个最小插件，用来验证清单校验的失败分支。 */
function makePluginFixture(marketplacePlugins) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'plugin-package-'));
  fs.mkdirSync(path.join(dir, '.claude-plugin'));
  fs.writeFileSync(
    path.join(dir, '.claude-plugin', 'plugin.json'),
    JSON.stringify({ name: 'demo-plugin', version: '1.2.3', agents: [], skills: [], commands: [] }),
  );
  fs.writeFileSync(
    path.join(dir, '.claude-plugin', 'marketplace.json'),
    JSON.stringify({ name: 'demo-marketplace', plugins: marketplacePlugins }),
  );
  return dir;
}

describe('isExcluded：运行期过程产物与密钥不进包', () => {
  it('顶层的 work / output / .agent-genesis / .claude 全部排除', () => {
    for (const item of [
      'work/run-1/state.yaml',
      'output/agents/demo/v1/SKILL.md',
      '.agent-genesis/work/x.json',
      '.claude/settings.local.json',
      '.claude/DEV_MODE',
    ]) {
      assert.equal(isExcluded(item), true, `${item} 应当被排除`);
    }
  });

  it('只排除顶层的 output，golden 样例里的 output-snapshot 必须留下', () => {
    // 用"任意层级都叫 output 就排除"会把 knowledge/golden 的样例池挖空，
    // 而那个目录名只是历史叫法，不是过程产物。
    assert.equal(isExcluded('knowledge/golden/demo/output-snapshot/CLAUDE.md'), false);
    assert.equal(isExcluded('knowledge/golden/demo/output-snapshot/output/CLAUDE.md'), false);
  });

  it('任意层级的 __pycache__ / node_modules / .git 排除', () => {
    assert.equal(isExcluded('scripts/__pycache__/state.cpython-312.pyc'), true);
    assert.equal(isExcluded('skills/demo/node_modules/left-pad/index.js'), true);
    assert.equal(isExcluded('knowledge/demo/.git/config'), true);
  });

  it('.env 与 .env.* 排除，但 .env.example 是模板要随包发', () => {
    assert.equal(isExcluded('.env'), true);
    assert.equal(isExcluded('scripts/.env'), true);
    assert.equal(isExcluded('.env.local'), true);
    assert.equal(isExcluded('.env.example'), false);
  });

  it('编辑器残留与日志不进包', () => {
    assert.equal(isExcluded('.DS_Store'), true);
    assert.equal(isExcluded('docs/Thumbs.db'), true);
    assert.equal(isExcluded('scripts/state.pyc'), true);
    assert.equal(isExcluded('work/run.log'), true);
  });

  it('插件本体的文件不会被误伤', () => {
    for (const item of [
      'README.md',
      'agents/pattern-matcher.md',
      'skills/harness-create/SKILL.md',
      'knowledge/INDEX.yaml',
      'phase/gates/gates.yaml',
      'tests/fixtures/demo.yaml',
      'evaluation/test-cases/e2e/fixtures/security-vulnerability-samples.yaml',
    ]) {
      assert.equal(isExcluded(item), false, `${item} 不该被排除`);
    }
  });
});

describe('readPluginMetadata：从清单推导，而不是写死文件表', () => {
  it('读得出 agent-genesis 的名字、版本与声明的 agent/skill 路径', () => {
    const metadata = readPluginMetadata(AGENT_GENESIS_DIR);

    assert.equal(metadata.name, 'agent-genesis');
    assert.match(metadata.version, /^\d+\.\d+\.\d+/);
    assert.equal(metadata.marketplaceName, 'agent-genesis');
    assert.ok(metadata.agents.length > 0, '清单应当声明 agents');
    assert.ok(metadata.skills.length > 0, '清单应当声明 skills');
    // 归一化：清单里写的是 "./agents/x.md"，归档路径不能带 "./"。
    for (const item of [...metadata.agents, ...metadata.skills]) {
      assert.ok(!item.startsWith('./'), `${item} 应当已去掉 ./ 前缀`);
    }
  });

  it('marketplace 没列出该插件时报错，而不是产出一个装不上的包', () => {
    const dir = makePluginFixture([{ name: 'someone-else', source: './' }]);

    assert.throws(() => readPluginMetadata(dir), /没有列出 demo-plugin/);
  });

  it('清单不是合法 JSON 时给出带文件名的错误', () => {
    const dir = makePluginFixture([{ name: 'demo-plugin', source: './' }]);
    fs.writeFileSync(path.join(dir, '.claude-plugin', 'plugin.json'), '{ not json');

    assert.throws(() => readPluginMetadata(dir), /plugin\.json 不是合法 JSON/);
  });
});

describe('归档命名与随包生成的文件', () => {
  it('产物名带 -plugin 后缀，与框架自身的产物区分开', () => {
    // 期望值一律用 `path.join` 拼：Windows 上它给出 `\tmp\out\…`，直接写字面量
    // `/tmp/out/…` 会把"分隔符随平台"这件事当成缺陷报出来。
    const outDir = path.join('/tmp/out');
    const paths = pluginArchivePaths(outDir, 'agent-genesis', '0.21.0');

    assert.equal(paths.base, 'agent-genesis-0.21.0');
    assert.equal(paths.tarball, path.join(outDir, 'agent-genesis-0.21.0-plugin.tar.gz'));
    assert.equal(paths.zip, path.join(outDir, 'agent-genesis-0.21.0-plugin.zip'));
    assert.equal(paths.manifest, path.join(outDir, 'agent-genesis-0.21.0-plugin.manifest.txt'));
  });

  it('生成三个装配件，安装脚本以包根目录为基准', () => {
    const metadata = readPluginMetadata(AGENT_GENESIS_DIR);
    const files = renderGeneratedFiles(metadata);
    const byName = new Map(files.map((file) => [file.relative, file]));

    assert.deepEqual(
      files.map((file) => file.relative),
      ['install.sh', 'install.cmd', 'INSTALL.md'],
    );

    const installSh = byName.get('install.sh');
    assert.equal(installSh.mode, 0o755);
    // 安装基准必须是脚本自己所在目录；写死路径或依赖仓库结构都会在用户机器上错。
    assert.match(installSh.content, /BASH_SOURCE\[0\]/);
    assert.match(installSh.content, /plugin marketplace add/);
    assert.match(installSh.content, /plugin install "\$PLUGIN_NAME@\$MARKETPLACE_NAME"/);
    // 插件源码里的 install.sh 曾经把 REPO_ROOT 算成 scripts/，这里不能复制那个写法。
    assert.doesNotMatch(installSh.content, /REPO_ROOT/);

    const installCmd = byName.get('install.cmd');
    assert.match(installCmd.content, /%~dp0/);
    // Windows 批处理必须是 CRLF，LF 在部分环境里会让标签跳转读错行。
    assert.match(installCmd.content, /\r\n/);

    const installMd = byName.get('INSTALL.md');
    assert.match(installMd.content, new RegExp(metadata.name));
    assert.match(installMd.content, new RegExp(metadata.version.replaceAll('.', '\\.')));
  });

  it('生成的条目与从磁盘收集的条目形状一致，且可执行位只在安装脚本上', () => {
    const metadata = readPluginMetadata(AGENT_GENESIS_DIR);
    const entries = generatedPluginEntries('agent-genesis-0.21.0', metadata);
    const byPath = new Map(entries.map((entry) => [entry.path, entry]));

    for (const entry of entries) {
      assert.equal(entry.kind, 'file');
      assert.ok(entry.size > 0);
      assert.ok(Buffer.isBuffer(entry.read()));
    }
    assert.equal(byPath.get('agent-genesis-0.21.0/install.sh').mode, 0o755);
    assert.equal(byPath.get('agent-genesis-0.21.0/INSTALL.md').mode, 0o644);

    assert.deepEqual(executablePluginPaths('agent-genesis-0.21.0'), [
      'agent-genesis-0.21.0/install.sh',
      'agent-genesis-0.21.0/install.cmd',
    ]);
  });

  it('清单兼容调整只改包内这一份，源码字段不动', () => {
    const metadata = readPluginMetadata(AGENT_GENESIS_DIR);
    const adjustments = manifestCompatAdjustments(metadata.manifest);
    const fields = adjustments.map((item) => item.field).toSorted();

    // agent-genesis 的实测冲突：agents 显式列表加载 0 个、commands 空数组让目录被忽略。
    assert.deepEqual(fields, ['agents', 'commands']);

    const patched = buildCompatibleManifest(metadata.manifest, adjustments);
    assert.equal('agents' in patched, false);
    assert.equal('commands' in patched, false);
    // 深拷贝一层即可，但绝不能反向污染调用方拿到的原始清单。
    assert.ok('agents' in metadata.manifest);

    const entry = manifestOverrideEntry('agent-genesis-0.21.0', patched);
    assert.equal(entry.path, 'agent-genesis-0.21.0/.claude-plugin/plugin.json');
    assert.equal(JSON.parse(entry.read().toString('utf8')).name, metadata.name);
  });

  it('传了调整项时 INSTALL.md 会写明包内清单与源码不同', () => {
    const metadata = readPluginMetadata(AGENT_GENESIS_DIR);
    const adjustments = manifestCompatAdjustments(metadata.manifest);
    const installMd = renderGeneratedFiles(metadata, adjustments).find(
      (file) => file.relative === 'INSTALL.md',
    );

    assert.match(installMd.content, /包内清单的兼容调整/);
    assert.match(installMd.content, /`agents`/);
    // 默认（没有调整项）不出现这一节。
    const plain = renderGeneratedFiles(metadata).find((file) => file.relative === 'INSTALL.md');
    assert.doesNotMatch(plain.content, /包内清单的兼容调整/);
  });

  it('声明路径与 README 一起构成必需文件表', () => {
    const metadata = readPluginMetadata(AGENT_GENESIS_DIR);
    const declared = declaredPluginPaths(metadata);

    assert.equal(declared[0], 'README.md');
    assert.ok(declared.includes('agents/pattern-matcher.md'));
    assert.ok(declared.includes('skills/harness-create/SKILL.md'));
  });
});
