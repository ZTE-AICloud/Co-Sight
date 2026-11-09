/**
 * 落一行 agents，让 `sessions/create` 的 agentId 校验过得去。
 *
 * `agents` 表是智能体存在的唯一权威（08-agent.md §1），所以需要「某个 agentId 存在」的测试
 * 都得先建行 - **直接写库，不走 create 端点**：这些测试要的是可控的 id（`api-flow` 这类
 * 可读名字），而端点只会发 `agt_<uuid>`。
 *
 * 幂等：同一个 agentId 反复调不报错（同一测试文件里 before 与用例都调也安全）。
 * 必须在 `prepareTestEnv()` 之后调用。
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

/** 测试缺省工作区 id；需要解析工作区目录的用例应让框架桩返回同一个 id。 */
export const TEST_WORKSPACE_ID = '8b1f0c2d-4e5a-4b6c-9d7e-1f2a3b4c5d6e';

/** 工作区默认模型可用的测试工作区 id。 */
export const TEST_WORKSPACE_DEFAULT_ID = '9c2a1d3e-5f6b-4c7d-8e9f-0a1b2c3d4e5f';

/** 工作区默认模型已被删除（详情 404）的测试工作区 id。 */
export const TEST_WORKSPACE_BROKEN_ID = 'ad3b2e4f-6071-4d8c-9fa0-1b2c3d4e5f60';

/** 工作区内的智能体根目录约定；与生产代码同形，测试里只按约定拼。 */
export function agentRootIn(workspaceDir: string, agentId: string): string {
  return join(workspaceDir, '.smart-factory', 'agents', agentId);
}

/** 起 run 前 development 目录必须存在：直接写库的智能体没有 create 端点代劳，由测试补上。 */
export function seedDevelopmentDir(workspaceDir: string, agentId: string): void {
  mkdirSync(join(agentRootIn(workspaceDir, agentId), 'development'), { recursive: true });
}

/**
 * 生产过程状态 + 交付门禁：preview / runtime / evaluation 前必须「流程收尾且门禁 PASS/CONCERNS」。
 *
 * 状态文件按 full 车道写（`pipeline: agent-creation`）；`status=COMPLETED` 时
 * 顺带补一份 `step-4-implementation.json`（verdict=PASS），与 executor 实际落盘一致。
 */
export function seedPipelineState(agentRoot: string, name: string, status = 'COMPLETED'): void {
  const work = join(agentRoot, 'development', '.agent-genesis', 'work', name);
  mkdirSync(join(work, 'gate-results'), { recursive: true });
  writeFileSync(
    join(work, 'orchestrator-state.yaml'),
    [
      'pipeline: agent-creation',
      `pipeline_status: ${status}`,
      'current_step: step-5-readiness-verification',
      'last_update: 2026-01-01T00:00:00Z',
      'total_retry_count: 0',
      'pipeline_retry_budget: 5',
      'steps:',
      '  - step_id: step-4-implementation',
      '',
    ].join('\n'),
  );
  if (status === 'COMPLETED') {
    writeFileSync(join(work, 'gate-results', 'step-4-implementation.json'), JSON.stringify({ verdict: 'PASS', concerns: [] }));
  }
}

export async function seedAgent(
  agentId: string,
  name = agentId,
  workspaceId = TEST_WORKSPACE_ID,
): Promise<void> {
  const { prisma } = await import('../../src/shared/prisma/client.js');
  await prisma.agent.upsert({
    where: { id: agentId },
    create: { id: agentId, workspaceId, name, description: '', icon: '' },
    update: {},
  });
}

/** 批量版：给 before() 用。 */
export async function seedAgents(...agentIds: string[]): Promise<void> {
  for (const agentId of agentIds) await seedAgent(agentId);
}
