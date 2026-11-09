import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { createServer, type AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { BadGatewayError } from '../src/shared/errors.js';
import { startFrameworkStub, type StubWorkspace } from './helpers/framework-stub.js';

const WS_ACTIVE = '8b1f0c2d-4e5a-4b6c-9d7e-1f2a3b4c5d6e';
const WS_CACHE = '1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d';

const TIMESTAMP = '2026-01-01T00:00:00.000Z';

const workspaces: StubWorkspace[] = [
  {
    id: WS_ACTIVE,
    name: '周报助手开发',
    directory: '/srv/workspaces/weekly',
    defaultAgentId: null,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
  },
  {
    id: WS_CACHE,
    name: '缓存工作区',
    directory: '/srv/workspaces/cache',
    defaultAgentId: null,
    createdAt: TIMESTAMP,
    updatedAt: TIMESTAMP,
  },
];

/** 取一个刚释放的端口，用于验证连接被拒的场景。 */
async function closedPort(): Promise<number> {
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, '127.0.0.1', resolve));
  const port = (probe.address() as AddressInfo).port;
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  return port;
}

const home = mkdtempSync(join(tmpdir(), 'sf-framework-client-'));
const token = 'test-module-token';
const tokenPath = join(home, '.module-token');
writeFileSync(tokenPath, `${token}\n`);

const stub = await startFrameworkStub({
  token,
  workspaces,
  activeWorkspaceId: WS_ACTIVE,
});

process.env.COSIGHT_HOME = home;
process.env.FRAMEWORK_BASE_URL = stub.url;

const { config } = await import('../src/config/index.js');
const { fetchWorkspace, fetchWorkspaces } = await import('../src/shared/framework/client.js');

after(async () => {
  await stub.close();
  rmSync(home, { recursive: true, force: true });
});

test('fetchWorkspaces：返回精简后的工作区列表与 activeId', async () => {
  const result = await fetchWorkspaces();

  assert.deepEqual(
    result.items.map((item) => item.id),
    [WS_ACTIVE, WS_CACHE],
  );
  assert.equal(result.activeId, WS_ACTIVE);
  assert.deepEqual(stub.requests.at(-1), { method: 'GET', path: '/api/framework/v1/workspaces' });
});

test('fetchWorkspace：返回详情里的工作区目录', async () => {
  const result = await fetchWorkspace(WS_ACTIVE);

  assert.equal(result.directory, '/srv/workspaces/weekly');
  assert.equal(result.name, '周报助手开发');
});

test('工作区目录缓存 60 秒：同一 id 连续两次只请求一次', async () => {
  const path = `/api/framework/v1/workspaces/${WS_CACHE}`;
  const count = (): number => stub.requests.filter((item) => item.path === path).length;
  const before = count();

  await fetchWorkspace(WS_CACHE);
  await fetchWorkspace(WS_CACHE);

  assert.equal(count() - before, 1);
});

test('fetchWorkspaces：列表上游 404 映射 BAD_GATEWAY，不落成 NOT_FOUND', async () => {
  stub.workspacesStatus = 404;
  try {
    await assert.rejects(
      fetchWorkspaces(),
      (error: unknown) => error instanceof BadGatewayError && error.status === 502,
    );
  } finally {
    stub.workspacesStatus = 200;
  }
});

test('上游 401：映射 BAD_GATEWAY 并提示令牌文件路径', async () => {
  writeFileSync(tokenPath, 'wrong-token-0123456789\n');
  try {
    await assert.rejects(
      fetchWorkspaces(),
      (error: unknown) => {
        assert.ok(error instanceof BadGatewayError);
        assert.equal(error.status, 502);
        assert.match(error.message, /401/);
        assert.match(error.message, /\.module-token/);
        return true;
      },
    );
  } finally {
    writeFileSync(tokenPath, `${token}\n`);
  }
});

test('无令牌：映射 BAD_GATEWAY 并给出可操作文案', async () => {
  renameSync(tokenPath, `${tokenPath}.bak`);
  try {
    await assert.rejects(
      fetchWorkspaces(),
      (error: unknown) => {
        assert.ok(error instanceof BadGatewayError);
        assert.match(error.message, /模块令牌/);
        assert.match(error.message, /\.module-token/);
        return true;
      },
    );
  } finally {
    renameSync(`${tokenPath}.bak`, tokenPath);
  }
});

test('上游超时：3 秒后映射 BAD_GATEWAY', async () => {
  stub.delayMs = 3500;
  try {
    await assert.rejects(
      fetchWorkspaces(),
      (error: unknown) => error instanceof BadGatewayError && /超时/.test(error.message),
    );
  } finally {
    stub.delayMs = 0;
  }
});

test('响应体读取超时：映射为超时而不是非 JSON 响应', async () => {
  stub.bodyDelayMs = 3500;
  try {
    await assert.rejects(
      fetchWorkspaces(),
      (error: unknown) => error instanceof BadGatewayError && /超时/.test(error.message),
    );
  } finally {
    stub.bodyDelayMs = 0;
  }
});

test('令牌格式非法：拒绝请求，错误消息不含令牌内容', async () => {
  const before = stub.requests.length;
  writeFileSync(tokenPath, 'secret-token\r\nInjected-Header: value\n');
  try {
    await assert.rejects(fetchWorkspaces(), (error: unknown) => {
      assert.ok(error instanceof BadGatewayError);
      assert.match(error.message, /内容非法/);
      assert.ok(!error.message.includes('secret-token'));
      assert.ok(!error.message.includes('Injected'));
      return true;
    });
    assert.equal(stub.requests.length, before);
  } finally {
    writeFileSync(tokenPath, `${token}\n`);
  }
});

test('无法连接框架：提示检查框架进程与 FRAMEWORK_BASE_URL', async () => {
  const mutable = config as { frameworkBaseUrl: string };
  const original = mutable.frameworkBaseUrl;
  mutable.frameworkBaseUrl = `http://127.0.0.1:${await closedPort()}`;
  try {
    await assert.rejects(fetchWorkspaces(), (error: unknown) => {
      assert.ok(error instanceof BadGatewayError);
      assert.match(error.message, /ECONNREFUSED/);
      assert.match(error.message, /FRAMEWORK_BASE_URL/);
      return true;
    });
  } finally {
    mutable.frameworkBaseUrl = original;
  }
});
