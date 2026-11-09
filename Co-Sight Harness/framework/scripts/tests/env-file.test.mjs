/**
 * `cosight.env` 的解析与优先级。
 *
 * 这份文件是用户在产物里**唯一会手改的东西**，它错的方式都很安静：
 * 写错的名字被忽略（"我明明配了"）、不该覆盖的覆盖了（"我临时设的没用"）。
 * 所以这里把两条语义分别钉死：解析规则、以及"真实环境变量优先"。
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { applyEnvFile, parseEnvFile } from '../lib/env-file.mjs';

describe('配置文件解析', () => {
  it('认 KEY=VALUE，忽略空行与注释', () => {
    const entries = parseEnvFile(
      ['# 注释', '', 'COSIGHT_PORT=4399', '   ', '\tCOSIGHT_HOST=127.0.0.1  '].join('\n'),
    );
    assert.deepEqual(entries, [
      { key: 'COSIGHT_PORT', value: '4399', line: 3 },
      { key: 'COSIGHT_HOST', value: '127.0.0.1', line: 5 },
    ]);
  });

  it('允许 export 前缀（写惯 sh 的人会这么写）', () => {
    assert.deepEqual(parseEnvFile('export COSIGHT_PORT=4399'), [
      { key: 'COSIGHT_PORT', value: '4399', line: 1 },
    ]);
  });

  it('带空格的值用引号包住，引号本身不算值的一部分', () => {
    const [entry] = parseEnvFile('COSIGHT_HOME="/data/my dir"');
    assert.equal(entry.value, '/data/my dir');
    assert.equal(parseEnvFile("COSIGHT_HOME='/data/my dir'")[0].value, '/data/my dir');
  });

  it('值是空串是合法的（等于显式设为空）', () => {
    assert.equal(parseEnvFile('COSIGHT_LOG_LEVEL=')[0].value, '');
  });

  it('键不合法时报错并带上行号与文件名，不静默跳过', () => {
    assert.throws(
      () => parseEnvFile('# 注释\nCOSIGHT-PORT=4399', '/tmp/x/cosight.env'),
      /\/tmp\/x\/cosight\.env 第 2 行的变量名不合法/,
    );
  });

  it('少了等号也报错，而不是当成没有这一行', () => {
    assert.throws(() => parseEnvFile('COSIGHT_PORT'), /第 1 行不是 KEY=VALUE/);
  });

  it('开头带 UTF-8 BOM 照常解析（记事本存的"UTF-8"就带 BOM）', () => {
    // 不剥的话第一行的键会变成 "\uFEFFCOSIGHT_PORT"，报错指着一个看着完全正确的名字。
    assert.deepEqual(parseEnvFile('\uFEFFCOSIGHT_PORT=4399'), [{ key: 'COSIGHT_PORT', value: '4399', line: 1 }]);
  });
});

describe('优先级：真实环境变量 > 配置文件', () => {
  it('只写空缺的键，已存在的原样不动', () => {
    const env = { COSIGHT_PORT: '8080' };
    const applied = applyEnvFile(parseEnvFile('COSIGHT_PORT=4399\nCOSIGHT_HOST=0.0.0.0'), env);

    assert.equal(env.COSIGHT_PORT, '8080', '真实环境变量应当赢');
    assert.equal(env.COSIGHT_HOST, '0.0.0.0');
    // 返回"实际写进去的键"，启动日志据此如实说明配置生效了几条——
    // 上一步的实测里，显示的就是"生效 0 条"。
    assert.deepEqual(applied, ['COSIGHT_HOST']);
  });

  it('值为空串的键也算存在，不会被文件里的值顶掉', () => {
    const env = { COSIGHT_LOG_LEVEL: '' };
    assert.deepEqual(applyEnvFile(parseEnvFile('COSIGHT_LOG_LEVEL=debug'), env), []);
    assert.equal(env.COSIGHT_LOG_LEVEL, '');
  });
});
