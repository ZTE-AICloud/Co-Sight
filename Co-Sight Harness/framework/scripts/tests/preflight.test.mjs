/**
 * 前置检查骨架与基础检查项。
 *
 * 这里刻意只测**纯逻辑与只读探测**：跑检查不建目录、不写文件、不碰
 * `~/.claude`。需要子进程的 Claude Code 检查在 claude-cli.test.mjs 里，
 * 需要打包产物的部分在 smoke:package 里。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, describe, it } from 'node:test';

import { configCheck, dataDirCheck, diskSpaceCheck, webDistCheck } from '../lib/checks/env.mjs';
import { nodeCheck } from '../lib/checks/node.mjs';
import { platformCheck } from '../lib/checks/platform.mjs';
import {
  defineCheck,
  EXIT_PREFLIGHT,
  exitCodeFor,
  renderReport,
  runChecks,
  SUPPORTED_PLATFORMS,
} from '../lib/preflight.mjs';

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-preflight-test-'));
after(() => fs.rmSync(scratch, { recursive: true, force: true }));

function makeAppDir(engines) {
  const dir = fs.mkdtempSync(path.join(scratch, 'app-'));
  fs.writeFileSync(
    path.join(dir, 'package.json'),
    JSON.stringify({ name: 'harness-server', version: '0.0.0-test', engines }),
  );
  return dir;
}

describe('检查骨架', () => {
  it('defineCheck 拒绝缺字段与非法 level', () => {
    assert.throws(() => defineCheck({ id: 'x', label: 'X' }), /缺少 run/);
    assert.throws(
      () => defineCheck({ id: 'x', label: 'X', run: () => ({ ok: true }), level: 'fatal' }),
      /只能是 block \/ warn/,
    );
  });

  it('runChecks 顺序执行，并把抛错收敛成一条失败', async () => {
    const order = [];
    const results = await runChecks([
      defineCheck({ id: 'a', label: 'A', run: () => (order.push('a'), { ok: true, detail: 'a' }) }),
      defineCheck({
        id: 'b',
        label: 'B',
        run: () => {
          order.push('b');
          throw new Error('访问被拒绝');
        },
      }),
      defineCheck({ id: 'c', label: 'C', level: 'warn', run: () => (order.push('c'), { ok: false, detail: 'c' }) }),
    ]);

    assert.deepEqual(order, ['a', 'b', 'c']);
    assert.equal(results[1].ok, false);
    assert.match(results[1].detail, /检查本身出错.*访问被拒绝/);
    assert.equal(results[2].level, 'warn');
  });

  it('只有 block 级失败才产生退出码 10', async () => {
    const warnOnly = await runChecks([
      defineCheck({ id: 'w', label: 'W', level: 'warn', run: () => ({ ok: false, detail: 'w' }) }),
    ]);
    assert.equal(exitCodeFor(warnOnly), 0);

    const blocked = await runChecks([
      defineCheck({ id: 'b', label: 'B', run: () => ({ ok: false, detail: 'b' }) }),
    ]);
    assert.equal(exitCodeFor(blocked), EXIT_PREFLIGHT);
  });

  it('单项可以把失败降为 warn（版本行解析失败但能力仍在的兜底）', async () => {
    const [result] = await runChecks([
      defineCheck({ id: 'x', label: 'X', run: () => ({ ok: false, level: 'warn', detail: '格式变了' }) }),
    ]);
    assert.equal(result.level, 'warn');
    assert.equal(result.ok, false);
    assert.equal(exitCodeFor([result]), 0);
    assert.match(renderReport([result]), /\[WARN\]/);
  });

  it('报告包含四段与固定状态标记，且不用 Unicode 勾叉', async () => {
    const results = await runChecks([
      defineCheck({ id: 'ok', label: '平台', run: () => ({ ok: true, detail: 'linux-x64' }) }),
      defineCheck({
        id: 'bad',
        label: 'Claude Code',
        run: () => ({
          ok: false,
          detail: '未找到',
          remedy: ['装一个', '或者把已有的加入 PATH'],
          impact: '插件装不进去',
        }),
      }),
      defineCheck({ id: 'warn', label: '磁盘空间', level: 'warn', run: () => ({ ok: false, detail: '可用 10 MB' }) }),
    ]);

    const report = renderReport(results, { title: '测试报告', context: ['数据目录  /tmp/x'] });
    assert.match(report, /^测试报告\n/);
    assert.match(report, /\[OK\]/);
    assert.match(report, /\[FAIL\]/);
    assert.match(report, /\[WARN\]/);
    assert.match(report, /处理：装一个\n\s+或者把已有的加入 PATH/);
    assert.match(report, /影响：插件装不进去/);
    assert.match(report, /结论：1 项失败.*退出码 10/);
    assert.doesNotMatch(report, /✓|✗/);
  });

  it('全部通过时结论是"可以继续"', async () => {
    const results = await runChecks([
      defineCheck({ id: 'ok', label: '平台', run: () => ({ ok: true, detail: 'ok' }) }),
    ]);
    assert.match(renderReport(results), /结论：可以继续。/);
  });
});

describe('平台检查', () => {
  it('受支持的平台通过，其余失败并给出替代方案', async () => {
    const [supported] = await runChecks([
      platformCheck({ platform: 'linux', arch: 'x64', supported: SUPPORTED_PLATFORMS }),
    ]);
    assert.equal(supported.ok, true);
    assert.equal(supported.detail, 'linux-x64');

    const [unsupported] = await runChecks([
      platformCheck({ platform: 'darwin', arch: 'arm64', supported: SUPPORTED_PLATFORMS }),
    ]);
    assert.equal(unsupported.ok, false);
    assert.match(unsupported.detail, /darwin-arm64/);
    assert.match(unsupported.remedy.join('\n'), /linux-x64/);
  });
});

describe('Node 检查', () => {
  it('满足区间时通过', async () => {
    const appDir = makeAppDir({ node: '^22.19.0 || >=24.0.0' });
    const [result] = await runChecks([nodeCheck({ appDir, currentVersion: '22.22.2' })]);
    assert.equal(result.ok, true);
    assert.match(result.detail, /满足 \^22\.19\.0/);
  });

  it('版本过低时失败，并给出要求与下载地址', async () => {
    const appDir = makeAppDir({ node: '^22.19.0 || >=24.0.0' });
    const [result] = await runChecks([
      nodeCheck({ appDir, currentVersion: '20.11.0', downloadUrl: 'https://example.invalid/node' }),
    ]);
    assert.equal(result.ok, false);
    assert.match(result.detail, /20\.11\.0/);
    assert.match(result.remedy.join('\n'), /https:\/\/example\.invalid\/node/);
  });

  it('清单没写 engines.node 时放行', async () => {
    const appDir = makeAppDir(undefined);
    const [result] = await runChecks([nodeCheck({ appDir, currentVersion: '18.0.0' })]);
    assert.equal(result.ok, true);
    assert.match(result.detail, /未声明 engines\.node/);
  });

  it('读不到服务端清单时由 runChecks 收敛成失败', async () => {
    const [result] = await runChecks([nodeCheck({ appDir: path.join(scratch, 'missing') })]);
    assert.equal(result.ok, false);
    assert.match(result.detail, /读不到服务端清单/);
  });
});

describe('环境检查', () => {
  it('数据目录：可写目录通过，同名文件失败', async () => {
    const dir = fs.mkdtempSync(path.join(scratch, 'home-'));
    const [okResult] = await runChecks([dataDirCheck({ home: dir })]);
    assert.equal(okResult.ok, true);

    const file = path.join(scratch, 'not-a-dir');
    fs.writeFileSync(file, 'x');
    const [badResult] = await runChecks([dataDirCheck({ home: file })]);
    assert.equal(badResult.ok, false);
    assert.match(badResult.detail, /不是目录/);
  });

  it('配置：解析错误会拦住，关闭时不读文件', async () => {
    const base = { disabled: false, exists: true, filePath: '/tmp/cosight.env', entryCount: 2, applied: [] };

    const [broken] = await runChecks([configCheck({ config: { ...base, error: new Error('第 3 行：非法') } })]);
    assert.equal(broken.ok, false);
    assert.match(broken.detail, /第 3 行：非法/);

    const [disabled] = await runChecks([
      configCheck({ config: { ...base, disabled: true, error: new Error('不该被看到') } }),
    ]);
    assert.equal(disabled.ok, true);
  });

  it('前端产物：null 合法，目录不存在时失败', async () => {
    const [none] = await runChecks([webDistCheck({ webDir: null })]);
    assert.equal(none.ok, true);

    const [missing] = await runChecks([webDistCheck({ webDir: path.join(scratch, 'no-dist') })]);
    assert.equal(missing.ok, false);
    assert.match(missing.remedy.join('\n'), /pnpm build/);
  });

  it('磁盘空间：阈值调到不可能满足时只产生 warn', async () => {
    const home = fs.mkdtempSync(path.join(scratch, 'disk-'));
    const [result] = await runChecks([diskSpaceCheck({ home, minFreeBytes: Number.MAX_SAFE_INTEGER })]);
    assert.equal(result.level, 'warn');
    assert.equal(exitCodeFor([result]), 0);
  });
});
