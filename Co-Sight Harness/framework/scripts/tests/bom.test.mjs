/**
 * 手写 JSON 清单与用户手改的配置：开头的 UTF-8 BOM 必须被吃掉。
 *
 * Windows 记事本里选"UTF-8"写出来的文件**带 BOM**（`EF BB BF`，即 U+FEFF），
 * 而读取方全部走 `JSON.parse`——它碰到 BOM 直接抛。用户看到的现象是
 * "我明明写对了，它就是没生效"，错在一个看不见的字节上。
 *
 * 这里对**每个真实读取路径**各跑一遍，而不是只测那个剥 BOM 的小函数：
 * 小函数对了但没接上，等于没修。每条都先断言"文件里真的有 BOM 字节"，
 * 免得哪天转义写丢、测试照样绿。
 */

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, it } from 'node:test';

import { readLaunchEntry } from '../lib/module-launch.mjs';
import { scanModuleManifests } from '../lib/module-probe.mjs';
import { stripBom } from '../lib/text.mjs';

const BOM = '\uFEFF';
const BOM_BYTES = Buffer.from([0xef, 0xbb, 0xbf]);

let scratch;

beforeEach(() => {
  scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-bom-'));
});

afterEach(() => {
  fs.rmSync(scratch, { recursive: true, force: true });
});

/** 写文件并断言它确实以 BOM 开头——测试数据本身也要立得住。 */
function writeWithBom(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, BOM + text, 'utf8');
  assert.deepEqual(fs.readFileSync(file).subarray(0, 3), BOM_BYTES, `${file} 应当以 BOM 开头`);
}

describe('stripBom', () => {
  it('剥掉开头那一个，只剥一个', () => {
    assert.equal(stripBom(`${BOM}abc`), 'abc');
    assert.equal(stripBom(`${BOM}${BOM}abc`), `${BOM}abc`, '第二个 BOM 是内容，不是编码产物');
  });

  it('没有 BOM 的文本原样返回（含空串）', () => {
    assert.equal(stripBom('abc'), 'abc');
    assert.equal(stripBom(''), '');
  });

  it('不顺手 trim：开头的换行是内容', () => {
    assert.equal(stripBom(`${BOM}\nabc`), '\nabc');
  });
});

describe('带 BOM 的 module.json（$COSIGHT_HOME/modules/<id>/）', () => {
  it('照常解析出 id / entry / healthcheck，不报"清单无法解析"', () => {
    writeWithBom(
      path.join(scratch, 'agent-dev', 'module.json'),
      JSON.stringify({ id: 'agent-dev', name: { 'zh-CN': 'Agent 开发' }, entry: 'http://127.0.0.1:5174/' }),
    );

    const [manifest] = scanModuleManifests(scratch);
    assert.equal(manifest.problem, null);
    assert.equal(manifest.id, 'agent-dev');
    assert.equal(manifest.entry, 'http://127.0.0.1:5174/');
    assert.equal(manifest.label, 'Agent 开发');
  });
});

describe('带 BOM 的 launch.json（docs/modules/<id>.launch.json）', () => {
  it('照常读出清单，不报"读不出启动清单"', () => {
    const file = path.join(scratch, 'probe-mod.launch.json');
    writeWithBom(
      file,
      JSON.stringify({
        schemaVersion: 1,
        id: 'probe-mod',
        moduleRoot: '.',
        priority: 1,
        services: [
          { name: 'server', cwd: '.', command: ['node', '-v'], port: 4321, readyPath: '/health', readyTimeoutMs: 1000 },
        ],
      }),
    );

    const entry = readLaunchEntry(file, { repoRoot: scratch, live: false });
    assert.equal(entry.id, 'probe-mod');
    assert.equal(entry.services[0].port, 4321);
  });
});
