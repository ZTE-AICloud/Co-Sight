/**
 * 模块进产物的搬运规则。
 *
 * 这里守的是三类"打包机上看着正常、用户那边才炸"的错误：
 *   1. include 写错路径 —— 少搬一整个目录，现象是某个页面 404；
 *   2. 依赖树不完整 —— 用户第一次 require 才报 ERR_MODULE_NOT_FOUND；
 *   3. 符号链接 —— Windows 解压后变成 0 字节文件，和缺文件长得一样。
 *
 * 全部在临时目录里跑，不调 npm、不联网、不跑构建（清单里不声明 build）。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, it } from 'node:test';

import {
  generatedModuleEntries,
  planModuleEntries,
  prepareModuleBundles,
} from '../lib/artifact-modules.mjs';
import { readArtifactSpec, resolveSpecForPackaging } from '../lib/artifact-spec.mjs';

const BASE = 'cosight-harness-9.9.9';
const MODULES_SUBDIR = 'modules';

let scratch;
let repo;
let docs;

function write(file, content) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content);
}

function makeModule(id = 'module-a', { dependencies = { dep: '1.0.0' } } = {}) {
  const root = path.join(repo, id);
  write(path.join(root, 'package.json'), JSON.stringify({ name: id, dependencies }));
  write(path.join(root, 'server', 'index.js'), 'process.exit(0);\n');
  write(path.join(root, 'node_modules', 'dep', 'package.json'), JSON.stringify({ name: 'dep', version: '1.0.0' }));
  write(path.join(root, 'client', 'dist', 'index.html'), '<!doctype html>');
  return root;
}

function writeArtifact(id = 'module-a', overrides = {}) {
  const spec = {
    schemaVersion: 1,
    id,
    moduleRoot: id,
    priority: 10,
    bundle: {
      include: ['package.json', 'server', 'client/dist', 'node_modules'],
      exclude: [],
    },
    services: [
      {
        name: 'server',
        cwd: '.',
        command: ['node', 'server/index.js'],
        port: 4830,
        readyPath: '/health',
      },
    ],
    ...overrides,
  };
  const file = path.join(docs, `${id}.artifact.json`);
  write(file, JSON.stringify(spec, null, 2));
  return file;
}

function writeManifest(id = 'module-a') {
  write(path.join(docs, `${id}.module.json`), JSON.stringify({ id, entry: 'http://127.0.0.1:4830/' }));
}

function prepareOptions(writeLine) {
  return {
    modulesDocDir: docs,
    repoRoot: repo,
    artifactBase: BASE,
    modulesSubdir: MODULES_SUBDIR,
    stagingDir: path.join(scratch, 'module-staging'),
    ...(writeLine === undefined ? {} : { writeLine }),
  };
}

beforeEach(() => {
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-artifact-modules-'));
  repo = path.join(scratch, 'repo');
  docs = path.join(scratch, 'docs');
  fs.mkdirSync(repo, { recursive: true });
  fs.mkdirSync(docs, { recursive: true });
});

afterEach(() => {
  fs.rmSync(scratch, { recursive: true, force: true });
});

describe('模块搬运的展开规则', () => {
  it('include 里的目录逐层展开到 modules/<id>/ 下', () => {
    makeModule();
    const spec = resolveSpecForPackaging(readArtifactSpec(writeArtifact()), { repoRoot: repo });
    const entries = planModuleEntries(spec, prepareOptions());
    const paths = entries.map((entry) => entry.path);

    const destination = `${BASE}/${MODULES_SUBDIR}/module-a`;
    assert.ok(paths.includes(`${destination}/package.json`));
    assert.ok(paths.includes(`${destination}/server/index.js`));
    assert.ok(paths.includes(`${destination}/client/dist/index.html`));
    assert.ok(paths.includes(`${destination}/node_modules/dep/package.json`));
  });

  it('exclude 可以剔到文件粒度', () => {
    makeModule();
    const spec = resolveSpecForPackaging(
      readArtifactSpec(writeArtifact('module-a', {
        bundle: {
          include: ['package.json', 'server'],
          exclude: ['server/index.js'],
        },
      })),
      { repoRoot: repo },
    );

    const paths = planModuleEntries(spec, prepareOptions()).map((entry) => entry.path);
    assert.ok(!paths.includes(`${BASE}/${MODULES_SUBDIR}/module-a/server/index.js`));
    assert.ok(paths.includes(`${BASE}/${MODULES_SUBDIR}/module-a/package.json`));
  });

  it('include 里有不存在的路径直接报错（不静默少搬）', () => {
    makeModule();
    const spec = resolveSpecForPackaging(
      readArtifactSpec(writeArtifact('module-a', {
        bundle: { include: ['package.json', 'server', 'client/missing'], exclude: [] },
      })),
      { repoRoot: repo },
    );

    assert.throws(() => planModuleEntries(spec, prepareOptions()), /不存在的路径：client\/missing/);
  });

  it('exclude 指向不存在的路径时打印一行，不当作错误', () => {
    makeModule();
    const spec = resolveSpecForPackaging(
      readArtifactSpec(writeArtifact('module-a', {
        bundle: { include: ['package.json'], exclude: ['node_modules/.bin'] },
      })),
      { repoRoot: repo },
    );

    const lines = [];
    planModuleEntries(spec, prepareOptions((line) => lines.push(line)));
    assert.match(lines.join('\n'), /exclude "node_modules\/\.bin" 指向不存在的路径/);
  });

  it('符号链接一律拒绝（Windows 解压后会变成 0 字节文件）', (t) => {
    makeModule();
    try {
      fs.symlinkSync(path.join(repo, 'module-a', 'server', 'index.js'), path.join(repo, 'module-a', 'server', 'link.js'));
    } catch {
      t.skip('当前环境不允许创建符号链接');
      return;
    }

    const spec = resolveSpecForPackaging(readArtifactSpec(writeArtifact()), { repoRoot: repo });
    assert.throws(() => planModuleEntries(spec, prepareOptions()), /符号链接.*bundle\.exclude/s);
  });
});

describe('清单文件本身也要进包', () => {
  it('生成 module.json（运行时契约）与 artifact.json（启动清单）', () => {
    makeModule();
    writeManifest();
    const file = writeArtifact();
    const spec = resolveSpecForPackaging(readArtifactSpec(file), { repoRoot: repo });

    const paths = generatedModuleEntries(spec, prepareOptions()).map((entry) => entry.path);
    assert.deepEqual(paths.toSorted(), [
      `${BASE}/${MODULES_SUBDIR}/module-a/artifact.json`,
      `${BASE}/${MODULES_SUBDIR}/module-a/module.json`,
    ]);
  });

  it('有装配态清单却没有运行时契约时报错', () => {
    makeModule();
    const spec = resolveSpecForPackaging(readArtifactSpec(writeArtifact()), { repoRoot: repo });
    assert.throws(
      () => generatedModuleEntries(spec, prepareOptions()),
      /有装配态清单，却没有 .*module-a\.module\.json/,
    );
  });
});

describe('多构建、附加文件与数据库模板', () => {
  it('builds 逐条判定与执行，构建期 env 会传给命令', async () => {
    makeModule();
    write(path.join(repo, 'module-a', 'src', 'a.txt'), 'a');
    writeManifest();
    writeArtifact('module-a', {
      bundle: {
        include: ['package.json', 'server', 'build'],
        exclude: [],
        builds: [
          {
            command: ['node', '-e', "const fs=require('node:fs');fs.mkdirSync('build',{recursive:true});fs.writeFileSync('build/one.txt',process.env.MARKER??'')"],
            cwd: '.',
            inputs: ['src'],
            outputs: ['build/one.txt'],
            env: { MARKER: 'first' },
          },
          {
            command: ['node', '-e', "const fs=require('node:fs');fs.mkdirSync('build',{recursive:true});fs.writeFileSync('build/two.txt','two')"],
            cwd: '.',
            inputs: ['src'],
            outputs: ['build/two.txt'],
          },
        ],
      },
    });

    const result = await prepareModuleBundles(prepareOptions());
    assert.equal(result.builds[0].status, 'rebuilt');
    assert.match(result.builds[0].detail, /\[0\].*\[1\]/);
    assert.equal(fs.readFileSync(path.join(repo, 'module-a', 'build', 'one.txt'), 'utf8'), 'first');
  });

  it('bundle.assets 从仓库根取文件，放进模块目录的指定位置', async () => {
    makeModule();
    write(path.join(repo, 'helpers', 'web-server.mjs'), '// helper\n');
    writeManifest();
    writeArtifact('module-a', {
      bundle: {
        include: ['package.json'],
        exclude: [],
        assets: [{ from: 'helpers/web-server.mjs', to: 'web-server.mjs' }],
      },
    });

    const result = await prepareModuleBundles(prepareOptions());
    const entry = result.entries.find(
      (item) => item.path === `${BASE}/${MODULES_SUBDIR}/module-a/web-server.mjs`,
    );
    assert.ok(entry, '附加文件应当出现在模块目录里');
    assert.equal(entry.read().toString('utf8'), '// helper\n');
  });

  it('bundle.database 用 COSIGHT_HOME 生成模板，并作为条目进包', async () => {
    makeModule();
    writeManifest();
    writeArtifact('module-a', {
      bundle: {
        include: ['package.json'],
        exclude: [],
        database: {
          command: [
            'node',
            '-e',
            "const fs=require('node:fs');const p=require('node:path');fs.writeFileSync(p.join(process.env.COSIGHT_HOME,'smart-factory.db'),'template-bytes')",
          ],
          cwd: '.',
          template: 'db-template.sqlite',
          file: 'smart-factory.db',
        },
      },
    });

    const result = await prepareModuleBundles(prepareOptions());
    const entry = result.entries.find(
      (item) => item.path === `${BASE}/${MODULES_SUBDIR}/module-a/db-template.sqlite`,
    );
    assert.ok(entry);
    assert.equal(entry.read().toString('utf8'), 'template-bytes');
    assert.ok(result.requiredPaths.includes(`${MODULES_SUBDIR}/module-a/db-template.sqlite`));
  });

  it('声明了 database 却没有给 stagingDir 时报错（不往模块源码里写）', async () => {
    makeModule();
    writeManifest();
    writeArtifact('module-a', {
      bundle: {
        include: ['package.json'],
        exclude: [],
        database: { command: ['node', 'x.mjs'], cwd: '.', template: 'db.sqlite', file: 'db.sqlite' },
      },
    });

    const withoutStaging = prepareOptions();
    delete withoutStaging.stagingDir;
    await assert.rejects(prepareModuleBundles(withoutStaging), /没有给出 stagingDir/);
  });

  it('可执行件必须是文件、带可执行位，且真的被 include 收进来', async () => {
    makeModule();
    write(path.join(repo, 'module-a', 'bin', 'tool'), '#!/bin/sh\n');
    fs.chmodSync(path.join(repo, 'module-a', 'bin', 'tool'), 0o755);
    writeManifest();

    writeArtifact('module-a', {
      bundle: { include: ['package.json', 'bin'], exclude: [], executable: ['bin/tool'] },
    });
    const result = await prepareModuleBundles(prepareOptions());
    const entry = result.entries.find(
      (item) => item.path === `${BASE}/${MODULES_SUBDIR}/module-a/bin/tool`,
    );
    // Windows 的 `fs.stat` 不带 Unix 权限位（一律 0666），这个断言在那里没有意义，
    // 与 `assertDependenciesPresent` 之前对可执行位的态度一致：只在 POSIX 上核。
    // 归档里的 755 由装配阶段按 `bundle.executable` 的声明强制写入
    // （`withExecutableModes`），所以这条在 Windows 上跳过并不会放走真正的错。
    if (process.platform !== 'win32') {
      assert.equal(entry.mode & 0o111, 0o111);
    }
    assert.deepEqual(result.executablePaths, [`${MODULES_SUBDIR}/module-a/bin/tool`]);

    writeArtifact('module-a', {
      bundle: { include: ['package.json'], exclude: [], executable: ['bin/tool'] },
    });
    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /必需的路径[\s\S]*bin\/tool/,
    );
  });

  it('原生件缺失时，错误里带上模块自带的补齐命令', async () => {
    const root = makeModule();
    write(path.join(root, 'scripts', 'prepare-native-artifacts.mjs'), '// stub\n');
    writeManifest();
    writeArtifact('module-a', {
      bundle: { include: ['package.json'], exclude: [], executable: ['bin/claude.exe'] },
    });

    // 打包机重装依赖后缺少另一个平台的可选依赖——这正是 smart-factory 的实际情况。
    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /bundle\.executable 指向不存在的文件：bin\/claude\.exe[\s\S]*node .*prepare-native-artifacts\.mjs/,
    );
  });

  it('dependencyRoots 让前后端各自装依赖的模块也能被核对', async () => {
    const root = path.join(repo, 'module-a');
    write(path.join(root, 'server', 'package.json'), JSON.stringify({ name: 'srv', dependencies: { ghost: '1' } }));
    write(path.join(root, 'server', 'node_modules', 'dep', 'package.json'), '{}');
    write(path.join(root, 'package.json'), JSON.stringify({ name: 'module-a', dependencies: {} }));
    writeManifest();
    writeArtifact('module-a', {
      bundle: {
        include: ['package.json', 'server'],
        exclude: [],
        dependencyRoots: ['server'],
      },
    });

    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /server：缺 ghost/,
    );
  });

  it('include 里带 .env 时拒绝打进产物（模板 .env.example 除外）', async () => {
    makeModule();
    write(path.join(repo, 'module-a', 'server', '.env'), 'SECRET=1\n');
    write(path.join(repo, 'module-a', 'server', '.env.example'), 'SECRET=\n');
    writeManifest();
    writeArtifact('module-a');

    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /会把本机环境变量文件打进产物/,
    );
  });
});

describe('整条准备流程', () => {
  it('有 artifact 清单的模块进包，只有 module.json 的列进"未打进"', async () => {
    makeModule();
    writeManifest();
    writeArtifact();

    // 另一个模块只有运行时契约：它不该被静默忽略。
    writeManifest('module-b');

    const result = await prepareModuleBundles(prepareOptions());
    assert.deepEqual(result.builds, [{ id: 'module-a', status: 'none', detail: '清单未声明构建步骤，直接搬运现有文件' }]);
    assert.deepEqual(result.unbundledIds, ['module-b']);

    const paths = result.entries.map((entry) => entry.path);
    assert.ok(paths.includes(`${BASE}/${MODULES_SUBDIR}/module-a/module.json`));
    assert.ok(paths.includes(`${BASE}/${MODULES_SUBDIR}/module-a/artifact.json`));

    // 条目路径带产物顶层目录，读回校验的必需路径**不带**（package.mjs 统一加）。
    // 两边都加会得到 `x/x/modules/...` 的假缺失：产物明明是好的，打包却报缺文件。
    assert.ok(result.requiredPaths.includes(`${MODULES_SUBDIR}/module-a/module.json`));
    assert.ok(result.requiredPaths.every((item) => !item.startsWith(`${BASE}/`)));
  });

  it('package.json 里的每个 dependencies 都必须在 node_modules 里', async () => {
    makeModule('module-a', { dependencies: { dep: '1.0.0', ghost: '2.0.0' } });
    writeManifest();
    writeArtifact();

    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /依赖树不完整[\s\S]*缺 ghost/,
    );
  });

  it('整个依赖根没装依赖时，报错直接给出可执行的安装命令', async () => {
    // 对应"拉完代码只在 client 里装过依赖"的情形：根目录的 node_modules 压根没有。
    const root = makeModule();
    fs.rmSync(path.join(root, 'node_modules'), { recursive: true, force: true });
    write(path.join(root, 'package-lock.json'), '{}\n');
    writeManifest();
    writeArtifact();

    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /依赖树不完整[\s\S]*\.：没有 node_modules[\s\S]*cd .*module-a && npm ci/,
    );
  });

  it('没有锁文件的依赖根给 npm install，而不是会改写锁文件的 npm ci', async () => {
    const root = makeModule();
    fs.rmSync(path.join(root, 'node_modules'), { recursive: true, force: true });
    writeManifest();
    writeArtifact();

    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /没有 node_modules[\s\S]*cd .*module-a && npm install/,
    );
  });

  it('缺依赖时按 bundle.install 先自动补齐，而不是直接失败', async () => {
    const root = makeModule('module-a', { dependencies: { dep: '1.0.0', ghost: '2.0.0' } });
    writeManifest();
    writeArtifact('module-a', {
      bundle: {
        include: ['package.json', 'server', 'client/dist', 'node_modules'],
        exclude: [],
        install: [
          {
            // 真的跑一条命令，证明补齐发生在展开条目之前。
            command: [
              'node',
              '-e',
              "const fs = require('node:fs'); fs.mkdirSync('node_modules/ghost', { recursive: true }); fs.writeFileSync('node_modules/ghost/package.json', '{}');",
            ],
            cwd: '.',
          },
        ],
      },
    });

    const result = await prepareModuleBundles(prepareOptions());
    assert.ok(fs.existsSync(path.join(root, 'node_modules', 'ghost', 'package.json')));
    assert.ok(result.entries.some((entry) => entry.path.endsWith('node_modules/ghost/package.json')));
  });

  it('缺原生件时按 bundle.install 补齐，并保留可执行位', async () => {
    makeModule();
    writeManifest();
    writeArtifact('module-a', {
      bundle: {
        include: ['package.json', 'server', 'client/dist', 'node_modules', 'bin'],
        exclude: [],
        executable: ['bin/claude.exe'],
        install: [
          {
            command: [
              'node',
              '-e',
              "const fs = require('node:fs'); fs.mkdirSync('bin', { recursive: true }); fs.writeFileSync('bin/claude.exe', ''); fs.chmodSync('bin/claude.exe', 0o755);",
            ],
            cwd: '.',
          },
        ],
      },
    });

    const result = await prepareModuleBundles(prepareOptions());
    assert.ok(result.executablePaths.some((item) => item.endsWith('bin/claude.exe')));
  });

  it('什么都不缺时不跑安装步骤（正常打包不联网）', async () => {
    const root = makeModule();
    writeManifest();
    writeArtifact('module-a', {
      bundle: {
        include: ['package.json', 'server', 'client/dist', 'node_modules'],
        exclude: [],
        install: [
          {
            command: ['node', '-e', "require('node:fs').writeFileSync('install-ran', '');"],
            cwd: '.',
          },
        ],
      },
    });

    await prepareModuleBundles(prepareOptions());
    assert.equal(fs.existsSync(path.join(root, 'install-ran')), false);
  });

  it('自动修复没补上时，仍然给出缺什么、在哪补', async () => {
    makeModule('module-a', { dependencies: { dep: '1.0.0', ghost: '2.0.0' } });
    writeManifest();
    writeArtifact('module-a', {
      bundle: {
        include: ['package.json', 'server', 'client/dist', 'node_modules'],
        exclude: [],
        install: [{ command: ['node', '-e', 'process.exit(1);'], cwd: '.' }],
      },
    });

    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /依赖树不完整[\s\S]*缺 ghost[\s\S]*npm install/,
    );
  });

  it('模块源码目录不存在时报错，而不是产出一个少了一个模块的包', async () => {
    writeManifest();
    writeArtifact('module-ghost', { moduleRoot: 'module-ghost' });

    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /源码目录不存在/,
    );
  });

  it('文件名与 id 不一致时报错（防止同一模块被两份清单描述）', async () => {
    makeModule();
    writeManifest();
    writeArtifact();
    write(path.join(docs, 'copy.artifact.json'), fs.readFileSync(path.join(docs, 'module-a.artifact.json')));

    await assert.rejects(
      prepareModuleBundles(prepareOptions()),
      /文件名前缀 "copy" 与 id "module-a" 不一致/,
    );
  });
});
