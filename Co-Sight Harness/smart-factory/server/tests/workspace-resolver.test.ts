/**
 * 工作区解析：agent -> workspaceId -> 框架工作区 -> directory -> agentRoot。
 *
 * 三种失败都必须明确报错，不猜路径、不回退默认目录：
 * 未知 agent（404）、directory 为 null / 工作区不存在（502）、框架不可达（502）。
 */
import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { startFrameworkStub, type StubWorkspace } from './helpers/framework-stub.js';

const env = prepareTestEnv('workspace-resolver');

const WS_ID = '8b1f0c2d-4e5a-4b6c-9d7e-1f2a3b4c5d6e';
const WS_NO_DIR = '2b3c4d5e-6f70-4a8b-9c0d-1e2f3a4b5c6d';
const WS_ABSENT = 'ffffffff-ffff-4fff-8fff-ffffffffffff';
/** 从未请求过、因而不会被 60 秒目录缓存命中的工作区，用于验证连接被拒。 */
const WS_OFFLINE = '7e7e7e7e-7e7e-4e7e-8e7e-7e7e7e7e7e7e';

const TIMESTAMP = '2026-01-01T00:00:00.000Z';

function workspace(id: string, directory: string | null): StubWorkspace {
  return { id, name: `工作区 ${id.slice(0, 4)}`, directory, defaultAgentId: null, createdAt: TIMESTAMP, updatedAt: TIMESTAMP };
}

const TOKEN = readFileSync(join(env.home, '.module-token'), 'utf8').trim();
const stub = await startFrameworkStub({ token: TOKEN, workspaces: [workspace(WS_ID, env.workspaceDir), workspace(WS_NO_DIR, null), workspace(WS_OFFLINE, env.workspaceDir)], activeWorkspaceId: WS_ID });
process.env.FRAMEWORK_BASE_URL = stub.url;

const { prisma } = await import('../src/shared/prisma/client.js');
const { resolveAgentRoot, resolveWorkspaceDirectory } = await import('../src/shared/workspace/workspace-resolver.js');
const { agentService } = await import('../src/modules/agent/agent.service.js');

let stubClosed = false;

after(async () => {
  if (!stubClosed) await stub.close();
  await prisma.$disconnect();
});

async function seedAgent(id: string, workspaceId: string): Promise<void> {
  await prisma.agent.create({
    data: { id, workspaceId, name: id, description: '', icon: '' },
  });
}

test('resolveAgentRoot：agent -> workspaceId -> directory，路径按约定拼接', async () => {
  await seedAgent('ws-agent', WS_ID);

  const root = await resolveAgentRoot('ws-agent');
  assert.equal(root, join(env.workspaceDir, '.smart-factory', 'agents', 'ws-agent'));
});

test('resolveAgentRoot：未知 agent → 404，不触碰框架', async () => {
  await assert.rejects(
    resolveAgentRoot('missing-agent'),
    (error: any) => error.status === 404 && error.message === '智能体 missing-agent 不存在',
  );
});

test('resolveWorkspaceDirectory：directory 为 null → 502，不猜路径', async () => {
  await assert.rejects(
    resolveWorkspaceDirectory(WS_NO_DIR),
    (error: any) => error.status === 502 && error.message === `工作区 ${WS_NO_DIR} 未绑定目录`,
  );
});

test('resolveWorkspaceDirectory：框架里不存在的工作区 → 502（不是 404）', async () => {
  await assert.rejects(
    resolveWorkspaceDirectory(WS_ABSENT),
    (error: any) => error.status === 502 && error.message === `工作区 ${WS_ABSENT} 不存在`,
  );
});

test('框架不可达：解析 502，启动收养整轮跳过且不抛错', async () => {
  await stub.close();
  stubClosed = true;

  await seedAgent('offline-agent', WS_OFFLINE);
  await assert.rejects(
    resolveAgentRoot('offline-agent'),
    (error: any) => error.status === 502 && error.message.includes('框架请求失败'),
  );

  mkdirSync(join(env.workspaceDir, '.smart-factory', 'agents', 'unreachable-dir'), { recursive: true });
  assert.equal(await agentService.adoptExistingDirs(), 0);
  assert.equal(await prisma.agent.count({ where: { id: 'unreachable-dir' } }), 0);
});
