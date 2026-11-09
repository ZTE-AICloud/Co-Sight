/**
 * 装配态清单（`<id>.artifact.json`）的读取与两个解析方向。
 *
 * 这些断言守的是"清单写错了会怎样"：这份文件同时被打包脚本和产物里的
 * `start.mjs` 读，写错一个字段名的后果分别是"模块没进包"和"模块没被拉起"，
 * 而两种现象都不会指向清单本身。所以这里要求**当场报错**，并且错误里
 * 带上文件名与字段路径。
 *
 * 不碰网络、不起进程：只对着临时目录里手写的 JSON 跑解析。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, it } from 'node:test';

import {
  DATA_DIR_PLACEHOLDER,
  readArtifactSpec,
  resolveSpecForPackaging,
  resolveSpecForRuntime,
  scanArtifactSpecs,
} from '../lib/artifact-spec.mjs';

let scratch;

beforeEach(() => {
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-artifact-spec-'));
});

afterEach(() => {
  fs.rmSync(scratch, { recursive: true, force: true });
});

/** 一份最小的合法清单；测试只覆盖自己关心的那一段。 */
function baseSpec(overrides = {}) {
  return {
    schemaVersion: 1,
    id: 'module-a',
    moduleRoot: 'module-a',
    priority: 10,
    // bundle 是必填的：这份清单存在就等于"这个模块要进产物"，
    // 没有搬运规则的话它只会安静地什么也不带。
    bundle: { include: ['package.json'] },
    services: [
      {
        name: 'server',
        cwd: '.',
        command: ['node', 'server/index.js'],
        port: 4830,
        readyPath: '/health',
        readyTimeoutMs: 5000,
        env: { PORT: '4830', DATA: `${DATA_DIR_PLACEHOLDER}/data` },
      },
    ],
    ...overrides,
  };
}

function writeSpec(text, name = 'module-a.artifact.json') {
  const file = path.join(scratch, name);
  fs.writeFileSync(file, text, 'utf8');
  return file;
}

function writeSpecObject(overrides = {}, name) {
  return writeSpec(JSON.stringify(baseSpec(overrides), null, 2), name);
}

/** 运行时解析用的模块目录。放在模块级：它不是每个用例都要新建的东西。 */
function moduleDir() {
  return path.join(scratch, 'module-a');
}

/** 在 `modules/<name>/artifact.json` 写一份产物形态的清单。 */
function writeModuleDir(name, specOrText) {
  const dir = path.join(scratch, 'modules', name);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, 'artifact.json'),
    typeof specOrText === 'string' ? specOrText : JSON.stringify(specOrText),
  );
}

describe('装配态清单的校验', () => {
  it('合法清单读出 id / priority / services', () => {
    const spec = readArtifactSpec(writeSpecObject());
    assert.equal(spec.id, 'module-a');
    assert.equal(spec.priority, 10);
    assert.equal(spec.services.length, 1);
    assert.equal(spec.services[0].readyPath, '/health');
    assert.equal(spec.services[0].readyTimeoutMs, 5000);
  });

  it('开头的 UTF-8 BOM 被吃掉（Windows 记事本写出来的文件带 BOM）', () => {
    const file = writeSpec(`﻿${JSON.stringify(baseSpec(), null, 2)}`);
    assert.deepEqual(fs.readFileSync(file).subarray(0, 3), Buffer.from([0xef, 0xbb, 0xbf]));
    assert.equal(readArtifactSpec(file).id, 'module-a');
  });

  it('未知字段报错，不静默失效（写错名字是最常见的错）', () => {
    const file = writeSpecObject({ service: [] });
    assert.throws(() => readArtifactSpec(file), /未知字段 "service"/);
  });

  it('services 里的未知字段同样报错', () => {
    const spec = baseSpec();
    spec.services[0].readyPat = '/health';
    const file = writeSpec(JSON.stringify(spec));
    assert.throws(() => readArtifactSpec(file), /未知字段 "readyPat"/);
  });

  it('端口越界、id 不合法、服务重名都直接报错', () => {
    assert.throws(() => readArtifactSpec(writeSpecObject({ id: 'Module_A' }, 'Module_A.artifact.json')), /id 必须是/);

    const badPort = baseSpec();
    badPort.services[0].port = 70_000;
    assert.throws(() => readArtifactSpec(writeSpec(JSON.stringify(badPort))), /1\.\.65535/);

    const duplicated = baseSpec();
    duplicated.services.push({ ...duplicated.services[0] });
    assert.throws(() => readArtifactSpec(writeSpec(JSON.stringify(duplicated))), /name "server" 重复/);
  });

  it('文件名前缀与 id 不一致时拒绝（否则"哪个模块没被拉起"只能靠猜）', () => {
    const file = writeSpec(JSON.stringify(baseSpec({ id: 'other' })));
    assert.throws(() => readArtifactSpec(file), /文件名前缀 "module-a" 与 id "other" 不一致/);
  });

  it('产物里的固定文件名 artifact.json：id 取自内容，目录名由扫描核对', () => {
    const modulesDir = path.join(scratch, 'modules');
    fs.mkdirSync(path.join(modulesDir, 'module-a'), { recursive: true });
    const file = path.join(modulesDir, 'module-a', 'artifact.json');
    fs.writeFileSync(file, JSON.stringify(baseSpec()));

    assert.equal(readArtifactSpec(file).id, 'module-a');

    // 文件名固定成 artifact.json 之后，前缀不再能表达目录名；
    // 这个核对放在 scanArtifactSpecs 里（只有它知道自己在扫哪个目录）。
    fs.writeFileSync(file, JSON.stringify(baseSpec({ id: 'module-b' })));
    const { specs, problems } = scanArtifactSpecs(modulesDir);
    assert.deepEqual(specs, []);
    assert.match(problems.map((item) => item.message).join('\n'), /清单 id 是 "module-b"，与目录名不一致/);
  });
});

describe('产物里的清单 → 可启动的服务', () => {
  it('cwd 相对模块目录解析，node 换成当前解释器', () => {
    const spec = readArtifactSpec(writeSpecObject());
    const runtime = resolveSpecForRuntime(spec, { moduleDir: moduleDir(), dataDir: '/data' });

    assert.equal(runtime.moduleDir, moduleDir());
    assert.equal(runtime.services[0].cwd, moduleDir());
    assert.equal(runtime.services[0].command[0], process.execPath);
    assert.deepEqual(runtime.services[0].command.slice(1), ['server/index.js']);
  });

  it('{{dataDir}} 被替换成调用方给的数据目录', () => {
    const spec = readArtifactSpec(writeSpecObject());
    const runtime = resolveSpecForRuntime(spec, { moduleDir: moduleDir(), dataDir: '/tmp/home' });
    assert.equal(runtime.services[0].env.DATA, '/tmp/home/data');
  });

  it('不支持的占位符报错，而不是留下一个叫 {{data-dir}} 的目录', () => {
    const spec = readArtifactSpec(writeSpecObject());
    spec.services[0].env.DATA = '{{data-dir}}/data';
    assert.throws(
      () => resolveSpecForRuntime(spec, { moduleDir: moduleDir(), dataDir: '/tmp/home' }),
      /不支持的占位符 \{\{data-dir\}\}/,
    );
  });

  it('cwd 越出模块目录一律拒绝', () => {
    const spec = readArtifactSpec(writeSpecObject());
    spec.services[0].cwd = '../../..';
    assert.throws(
      () => resolveSpecForRuntime(spec, { moduleDir: moduleDir(), dataDir: '/tmp/home' }),
      /指向模块目录之外/,
    );
  });

  it('运行期结果里没有 bundle（那段只有打包脚本读）', () => {
    const spec = readArtifactSpec(writeSpecObject());
    const runtime = resolveSpecForRuntime(spec, { moduleDir: moduleDir(), dataDir: '/tmp/home' });
    assert.equal('bundle' in runtime, false);
    assert.equal('bundle' in runtime.services[0], false);
  });
});

describe('仓库里的清单 → 打包用绝对路径', () => {
  it('moduleRoot 与 build.cwd 都解析成绝对路径', () => {
    const file = writeSpecObject({
      bundle: {
        include: ['package.json'],
        build: { command: ['npm', 'run', 'build'], cwd: 'client', outputs: ['dist/index.html'] },
      },
    });
    const spec = resolveSpecForPackaging(readArtifactSpec(file), { repoRoot: scratch });

    assert.equal(spec.moduleRoot, path.join(scratch, 'module-a'));
    assert.equal(spec.build.cwd, path.join(scratch, 'module-a', 'client'));
    assert.deepEqual(spec.include, ['package.json']);
  });

  it('build.cwd 越出模块目录同样拒绝', () => {
    const file = writeSpecObject({
      bundle: {
        include: ['package.json'],
        build: { command: ['npm', 'run', 'build'], cwd: '../elsewhere', outputs: ['dist/index.html'] },
      },
    });
    assert.throws(
      () => resolveSpecForPackaging(readArtifactSpec(file), { repoRoot: scratch }),
      /指向模块目录之外/,
    );
  });
});

describe('模块级配置：env / prepare / startAfter / platforms', () => {
  it('顶层 env 并入每个服务，服务自己的同名键优先', () => {
    const spec = readArtifactSpec(
      writeSpecObject({
        env: { NODE_ENV: 'production', SHARED: 'top' },
      }),
    );
    spec.services[0].env.SHARED = 'service';
    const runtime = resolveSpecForRuntime(spec, { moduleDir: moduleDir(), dataDir: '/data' });

    assert.equal(runtime.env.NODE_ENV, 'production');
    assert.equal(runtime.services[0].env.NODE_ENV, 'production');
    assert.equal(runtime.services[0].env.SHARED, 'service');
  });

  it('{{frameworkUrl}} 与 {{dataDir}} 同时可用；缺值时当场报错', () => {
    const file = writeSpecObject({
      env: { FRAMEWORK_BASE_URL: '{{frameworkUrl}}' },
    });
    const spec = readArtifactSpec(file);

    const runtime = resolveSpecForRuntime(spec, {
      moduleDir: moduleDir(),
      dataDir: '/tmp/home',
      frameworkUrl: 'http://127.0.0.1:4300',
    });
    assert.equal(runtime.services[0].env.FRAMEWORK_BASE_URL, 'http://127.0.0.1:4300');
    // 服务自己的 {{dataDir}} 仍然照常替换。
    assert.equal(runtime.services[0].env.DATA, '/tmp/home/data');

    assert.throws(
      () => resolveSpecForRuntime(spec, { moduleDir: moduleDir(), dataDir: '/tmp/home' }),
      /清单里用了 \{\{frameworkUrl\}\}，但调用方没有给出对应的值/,
    );
  });

  it('prepare 被解析成可 spawn 的步骤，node 同样换成当前解释器', () => {
    const spec = readArtifactSpec(
      writeSpecObject({
        prepare: [
          {
            name: 'database',
            cwd: 'server',
            command: ['node', 'scripts/db.mjs', 'sync'],
            timeoutMs: 1234,
          },
        ],
      }),
    );
    const runtime = resolveSpecForRuntime(spec, { moduleDir: moduleDir(), dataDir: '/data' });

    assert.equal(runtime.prepare.length, 1);
    assert.equal(runtime.prepare[0].label, 'module-a:database');
    assert.equal(runtime.prepare[0].cwd, path.join(moduleDir(), 'server'));
    assert.equal(runtime.prepare[0].command[0], process.execPath);
    assert.equal(runtime.prepare[0].timeoutMs, 1234);
  });

  it('prepare 名字重复、cwd 越界、startAfter 取值未知都报错', () => {
    assert.throws(
      () => readArtifactSpec(writeSpecObject({
        prepare: [
          { name: 'db', cwd: '.', command: ['node', 'a.mjs'] },
          { name: 'db', cwd: '.', command: ['node', 'b.mjs'] },
        ],
      })),
      /prepare 里 name "db" 重复/,
    );

    const escaping = readArtifactSpec(writeSpecObject({
      prepare: [{ name: 'db', cwd: '../..', command: ['node', 'a.mjs'] }],
    }));
    assert.throws(
      () => resolveSpecForRuntime(escaping, { moduleDir: moduleDir(), dataDir: '/data' }),
      /指向模块目录之外/,
    );

    assert.throws(
      () => readArtifactSpec(writeSpecObject({ startAfter: 'later' })),
      /startAfter 目前只支持 "framework"/,
    );
  });

  it('platforms 只接受 <os>-<arch>，且不能重复', () => {
    const spec = readArtifactSpec(writeSpecObject({ platforms: ['linux-x64', 'win32-x64'] }));
    assert.deepEqual(spec.platforms, ['linux-x64', 'win32-x64']);

    assert.throws(
      () => readArtifactSpec(writeSpecObject({ platforms: ['linux'] })),
      /platforms\[0\] 必须是 "<os>-<arch>"/,
    );
    assert.throws(
      () => readArtifactSpec(writeSpecObject({ platforms: ['linux-x64', 'linux-x64'] })),
      /platforms 里 "linux-x64" 重复/,
    );
  });
});

describe('打包段：多构建 / 附加文件 / 数据库模板', () => {
  it('builds 逐条解析；与 build 同时出现时报错', () => {
    const spec = readArtifactSpec(
      writeSpecObject({
        bundle: {
          include: ['package.json'],
          builds: [
            { command: ['npm', 'run', 'build'], cwd: 'server', outputs: ['dist/index.js'] },
            { command: ['npm', 'run', 'build'], cwd: 'web', outputs: ['dist/index.html'], env: { VITE_X: '' } },
          ],
        },
      }),
    );
    assert.equal(spec.bundle.builds.length, 2);
    assert.equal(spec.bundle.builds[1].env.VITE_X, '');

    assert.throws(
      () => readArtifactSpec(writeSpecObject({
        bundle: {
          include: ['package.json'],
          build: { command: ['npm', 'run', 'build'], outputs: ['dist/index.html'] },
          builds: [{ command: ['npm', 'run', 'build'], outputs: ['dist/index.html'] }],
        },
      })),
      /bundle\.build 与 bundle\.builds 只能写一个/,
    );
  });

  it('assets 的 from 相对仓库根解析，to 必须是模块内相对路径', () => {
    const file = writeSpecObject({
      bundle: {
        include: ['package.json'],
        assets: [{ from: 'framework/scripts/artifact/helper.mjs', to: 'helper.mjs' }],
      },
    });
    const spec = resolveSpecForPackaging(readArtifactSpec(file), { repoRoot: scratch });

    assert.equal(spec.assets[0].from, path.join(scratch, 'framework', 'scripts', 'artifact', 'helper.mjs'));
    assert.equal(spec.assets[0].to, 'helper.mjs');

    assert.throws(
      () => readArtifactSpec(writeSpecObject({
        bundle: { include: ['package.json'], assets: [{ from: 'x.mjs', to: '../escape.mjs' }] },
      })),
      /bundle\.assets\[0\]\.to 必须是模块目录内的相对路径/,
    );
  });

  it('assets 写到同一位置会报错（后一份会静默覆盖前一份）', () => {
    assert.throws(
      () => readArtifactSpec(writeSpecObject({
        bundle: {
          include: ['package.json'],
          assets: [
            { from: 'a.mjs', to: 'same.mjs' },
            { from: 'b.mjs', to: 'same.mjs' },
          ],
        },
      })),
      /有两份文件要写到同一个位置/,
    );
  });

  it('database 的 cwd 解析成绝对路径，template/file 都有约束', () => {
    const file = writeSpecObject({
      bundle: {
        include: ['package.json'],
        database: {
          command: ['node', 'scripts/db.mjs', 'sync'],
          cwd: 'server',
          template: 'db-template.sqlite',
          file: 'smart-factory.db',
        },
      },
    });
    const spec = resolveSpecForPackaging(readArtifactSpec(file), { repoRoot: scratch });
    assert.equal(spec.database.cwd, path.join(scratch, 'module-a', 'server'));

    assert.throws(
      () => readArtifactSpec(writeSpecObject({
        bundle: {
          include: ['package.json'],
          database: { command: ['node', 'x.mjs'], template: '../db', file: 'x.db' },
        },
      })),
      /bundle\.database\.template 必须是模块目录内的相对路径/,
    );
    assert.throws(
      () => readArtifactSpec(writeSpecObject({
        bundle: {
          include: ['package.json'],
          database: { command: ['node', 'x.mjs'], template: 'db.sqlite', file: '../x.db' },
        },
      })),
      /bundle\.database\.file 必须是不带路径分隔符的文件名/,
    );
  });

  it('required / executable / dependencyRoots 原样读出', () => {
    const spec = readArtifactSpec(
      writeSpecObject({
        bundle: {
          include: ['package.json'],
          required: ['server/index.js'],
          executable: ['bin/tool'],
          dependencyRoots: ['server', 'web'],
        },
      }),
    );
    assert.deepEqual(spec.bundle.required, ['server/index.js']);
    assert.deepEqual(spec.bundle.executable, ['bin/tool']);
    assert.deepEqual(spec.bundle.dependencyRoots, ['server', 'web']);
  });
});

describe('扫描产物里的 modules/', () => {
  it('目录不存在返回空结果（没有打进模块是正常状态）', () => {
    assert.deepEqual(scanArtifactSpecs(path.join(scratch, 'nope')), { specs: [], problems: [] });
  });

  it('按 priority 升序返回', () => {
    writeModuleDir('module-a', baseSpec({ id: 'module-a', priority: 20 }));
    writeModuleDir('module-b', baseSpec({ id: 'module-b', priority: 10 }));

    const { specs, problems } = scanArtifactSpecs(path.join(scratch, 'modules'));
    assert.deepEqual(specs.map((spec) => spec.id), ['module-b', 'module-a']);
    assert.deepEqual(problems, []);
  });

  it('坏清单与目录名不一致只记问题，不让整个扫描失败', () => {
    writeModuleDir('module-a', { ...baseSpec({ id: 'module-a' }), services: [] });
    writeModuleDir('module-b', baseSpec({ id: 'module-c' }));
    fs.mkdirSync(path.join(scratch, 'modules', 'module-d'), { recursive: true });

    const { specs, problems } = scanArtifactSpecs(path.join(scratch, 'modules'));
    assert.deepEqual(specs, []);
    assert.equal(problems.length, 3);
    assert.match(problems.map((item) => item.message).join('\n'), /services 必须是/);
    assert.match(problems.map((item) => item.message).join('\n'), /与目录名不一致/);
    assert.match(problems.map((item) => item.message).join('\n'), /缺少 artifact\.json/);
  });

  it('priority 冲突会被指出来（启动顺序不确定）', () => {
    writeModuleDir('module-a', baseSpec({ id: 'module-a', priority: 10 }));
    writeModuleDir('module-b', baseSpec({ id: 'module-b', priority: 10 }));

    const { problems } = scanArtifactSpecs(path.join(scratch, 'modules'));
    assert.match(problems.map((item) => item.message).join('\n'), /priority 10 与 module-a 冲突/);
  });
});
