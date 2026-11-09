/**
 * 跨平台打包的常量与纯函数。
 *
 * 这些断言守的是**打包期**才用得上的那几个决定：哪些原生件必须有、
 * deploy 要带哪些平台旗标、产物里该有哪些脚本。它们全都有一个共同性质——
 * 错了不会在本机报错，而是变成"用户那边起不来"。
 *
 * 注意这里不去跑 pnpm，也不碰网络：只对着常量与纯函数断言，能在毫秒级跑完。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it } from 'node:test';

import {
  ARTIFACT_LAYOUT,
  ARTIFACT_SLUG,
  ARTIFACT_TARGETS,
  MODULE_ROOT,
  artifactBaseName,
  artifactPaths,
  artifactTimestamp,
  deployPlatformArgs,
  nativePackagesFor,
} from '../lib/project.mjs';

describe('产物平台与原生件', () => {
  it('默认覆盖 linux-x64 与 win32-x64', () => {
    assert.deepEqual(ARTIFACT_TARGETS, ['linux-x64', 'win32-x64']);
  });

  it('每个平台的原生件都在（名字对着 @neon-rs/load 的 currentTarget 抄的）', () => {
    assert.deepEqual(nativePackagesFor(), [
      '@libsql/linux-x64-gnu',
      '@esbuild/linux-x64',
      // win32 那一份的名字带 ABI 后缀，libsql 的 win32-x64 用户拿不到不带后缀的包。
      '@libsql/win32-x64-msvc',
      '@esbuild/win32-x64',
    ]);
  });

  it('目标重复时不会给出重复的包名', () => {
    assert.deepEqual(nativePackagesFor(['linux-x64', 'linux-x64']), [
      '@libsql/linux-x64-gnu',
      '@esbuild/linux-x64',
    ]);
  });

  it('未知平台直接报错，不静默少装', () => {
    assert.throws(() => nativePackagesFor(['darwin-arm64']), /未知的产物平台/);
  });

  it('平台目标翻译成 --os/--cpu（pnpm 只认这两个 CLI 旗标）', () => {
    assert.deepEqual(deployPlatformArgs(), ['--os=linux', '--cpu=x64', '--os=win32', '--cpu=x64']);
  });

  it('写坏的平台目标要报错，而不是拼出一个奇怪的旗标', () => {
    assert.throws(() => deployPlatformArgs(['linuxx64']), /<os>-<cpu>/);
  });
});

describe('产物命名与布局', () => {
  it('归档名与顶层目录名同源', () => {
    const base = artifactBaseName('9.9.9');
    assert.equal(base, `${ARTIFACT_SLUG}-9.9.9`);
    const paths = artifactPaths('9.9.9');
    assert.equal(paths.base, base);
    assert.ok(paths.tarball.endsWith(`${base}.tar.gz`));
    assert.ok(paths.zip.endsWith(`${base}.zip`));
  });

  it('时间戳同时进入归档名与顶层目录名', () => {
    // 2026-10-26 14:30:15 本地时间：各段补零，避免出现 cosight-harness-0.1.0-20261026-9305 这种顺排序会错的名字。
    const stamp = artifactTimestamp(new Date(2026, 9, 26, 4, 5, 6));
    assert.equal(stamp, '20261026-040506');

    const base = artifactBaseName('9.9.9', stamp);
    assert.equal(base, `${ARTIFACT_SLUG}-9.9.9-${stamp}`);

    const paths = artifactPaths('9.9.9', stamp);
    assert.equal(paths.base, base);
    assert.ok(paths.tarball.endsWith(`${base}.tar.gz`));
    assert.ok(paths.zip.endsWith(`${base}.zip`));
  });

  it('布局里声明的用户侧脚本都真的存在', () => {
    const sourceDir = path.join(MODULE_ROOT, ARTIFACT_LAYOUT.scriptSourceDir);
    const names = [
      ARTIFACT_LAYOUT.installSh,
      ARTIFACT_LAYOUT.installCmd,
      ARTIFACT_LAYOUT.startSh,
      ARTIFACT_LAYOUT.startCmd,
      ARTIFACT_LAYOUT.envExample,
    ];

    for (const name of names) {
      assert.ok(fs.existsSync(path.join(sourceDir, name)), `缺少 ${path.join(sourceDir, name)}`);
    }
  });

  it('启动入口就在脚本目录里（打包脚本按这个名字搬运）', () => {
    assert.ok(fs.existsSync(path.join(MODULE_ROOT, 'scripts', ARTIFACT_LAYOUT.entryFile)));
  });

  it('产物里的模块目录名与 start.mjs 里的常量同源', () => {
    // `start.mjs` 是入口脚本，import 就会跑 main()，不能直接引入取常量。
    // 而这两个名字必须一致：打包脚本把模块放进 `modules/`，`start.mjs` 却按
    // 另一个名字去找时，产物里模块明明在、却一个都不会被拉起。
    const source = fs.readFileSync(path.join(MODULE_ROOT, 'scripts', ARTIFACT_LAYOUT.entryFile), 'utf8');
    const match = /const MODULES_DIR_NAME = '([^']+)';/.exec(source);
    assert.ok(match !== null, 'start.mjs 里找不到 MODULES_DIR_NAME');
    assert.equal(match[1], ARTIFACT_LAYOUT.modulesSubdir);
  });

  it('产物里的插件目录名与 start.mjs 里的常量同源', () => {
    const source = fs.readFileSync(path.join(MODULE_ROOT, 'scripts', ARTIFACT_LAYOUT.entryFile), 'utf8');
    const match = /const PLUGINS_DIR_NAME = '([^']+)';/.exec(source);
    assert.ok(match !== null, 'start.mjs 里找不到 PLUGINS_DIR_NAME');
    assert.equal(match[1], ARTIFACT_LAYOUT.pluginsSubdir);
  });
});
