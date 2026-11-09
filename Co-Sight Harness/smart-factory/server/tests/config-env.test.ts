import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/** server/ 根目录：子进程探针的 cwd，保证 tsx 与 .env 都按仓库位置解析。 */
const serverDir = fileURLToPath(new URL('..', import.meta.url));
const KEY = 'TEST_POSITIVE_NUM';

const { positiveNumberFromEnv } = await import('../src/config/index.js');

interface ProbeResult {
  cosightHome: string;
  home: string;
  databaseUrl: string;
  frameworkBaseUrl: string;
}

const PROBE_KEYS = ['COSIGHT_HOME', 'FRAMEWORK_BASE_URL', 'SMART_FACTORY_HOME', 'DATABASE_URL'] as const;

/**
 * 在子进程里加载 config 并回传解析结果。
 *
 * config 在 import 时读环境，进程内只能测一次默认值之外的组合；子进程还避开 .env：
 * DOTENV_CONFIG_PATH 指向不存在的文件，DOTENV_CONFIG_QUIET 关掉 dotenv 的输出。
 */
function probeConfig(overrides: Record<string, string> = {}): ProbeResult {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    DOTENV_CONFIG_QUIET: 'true',
    DOTENV_CONFIG_PATH: join(serverDir, '.env.probe-absent'),
  };
  for (const key of PROBE_KEYS) delete env[key];
  Object.assign(env, overrides);

  const probe =
    "const m = await import('./src/config/index.js'); const c = m.config; " +
    'process.stdout.write(JSON.stringify({ cosightHome: c.cosightHome, home: c.home, databaseUrl: c.databaseUrl, frameworkBaseUrl: c.frameworkBaseUrl }));';
  const stdout = execFileSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', probe], {
    cwd: serverDir,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    env,
  });
  return JSON.parse(stdout) as ProbeResult;
}

function sqliteUrl(home: string): string {
  return `file:${join(home, 'smart-factory.db').replaceAll('\\', '/')}`;
}

after(() => {
  delete process.env[KEY];
});

test('缺省环境变量：回落到 fallback', () => {
  delete process.env[KEY];
  assert.equal(positiveNumberFromEnv(KEY, 42), 42);
});

test('合法值：原样采用', () => {
  process.env[KEY] = '5000';
  assert.equal(positiveNumberFromEnv(KEY, 42), 5000);
});

for (const raw of ['abc', '0', '-1', ' ', '']) {
  test(`非法值 ${JSON.stringify(raw)}：抛错并指明键名`, () => {
    process.env[KEY] = raw;
    assert.throws(() => positiveNumberFromEnv(KEY, 42), (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, new RegExp(KEY));
      return true;
    });
  });
}

test('启动 fail-fast：WS_HEARTBEAT_MS 非法时进程拒绝启动', () => {
  // 子进程探针：只 import config 并打印解析结果，不启服务、不连库
  const probe = "const m = await import('./src/config/index.js'); process.stdout.write(String(m.config.wsHeartbeatMs));";
  assert.throws(
    () =>
      execFileSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', probe], {
        cwd: serverDir,
        encoding: 'utf8',
        // stderr 也收进管道：探针的预期失败堆栈不该原样泼进测试输出
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, WS_HEARTBEAT_MS: 'abc' },
      }),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /WS_HEARTBEAT_MS/);
      return true;
    },
  );
});

test('COSIGHT_HOME 缺省：homedir 下的 .cosight-harness', () => {
  const result = probeConfig();
  const expected = join(homedir(), '.cosight-harness');

  assert.equal(result.cosightHome, expected);
  assert.equal(result.home, expected);
  assert.equal(result.databaseUrl, sqliteUrl(expected));
});

test('COSIGHT_HOME 相对路径：按进程 cwd 用 path.resolve 解析', () => {
  const result = probeConfig({ COSIGHT_HOME: '.tmp/probe-home' });

  assert.equal(result.cosightHome, resolve(serverDir, '.tmp/probe-home'));
});

test('COSIGHT_HOME 不展开 ~', () => {
  const result = probeConfig({ COSIGHT_HOME: '~/.cosight-harness' });

  assert.equal(result.cosightHome, resolve(serverDir, '~/.cosight-harness'));
  assert.notEqual(result.cosightHome, join(homedir(), '.cosight-harness'));
});

test('SMART_FACTORY_HOME 不再参与解析', () => {
  const result = probeConfig({ SMART_FACTORY_HOME: resolve(serverDir, '.tmp', 'legacy-home') });

  assert.equal(result.cosightHome, join(homedir(), '.cosight-harness'));
});

test('databaseUrl 固定落在 {COSIGHT_HOME}/smart-factory.db', () => {
  const home = resolve(serverDir, '.tmp/probe-db');
  const result = probeConfig({ COSIGHT_HOME: home });

  assert.equal(result.databaseUrl, sqliteUrl(home));
});

test('FRAMEWORK_BASE_URL 缺省指向本机 4300', () => {
  assert.equal(probeConfig().frameworkBaseUrl, 'http://127.0.0.1:4300');
});

test('FRAMEWORK_BASE_URL 可覆盖', () => {
  assert.equal(probeConfig({ FRAMEWORK_BASE_URL: 'http://127.0.0.1:4999' }).frameworkBaseUrl, 'http://127.0.0.1:4999');
});
