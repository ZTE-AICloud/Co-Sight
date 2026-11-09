/**
 * 智能体产物状态：AgentGenesis 过程状态 + 交付门禁 → status / ready。
 *
 * 权威口径：server/docs/04-api/4.10-智能体产物状态.md。
 * 重点覆盖两条完成路径（full 的 COMPLETED、fast 的 step-f1 收尾）与所有不 ready 分支。
 */
import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';

const env = prepareTestEnv('production-status');

const { readProductionStatus, locateProducedAgent } = await import('../src/shared/workspace/production.js');
const { ConflictError } = await import('../src/shared/errors.js');

after(() => {
  // 本文件不导入 Prisma，无需断开连接
});

let sequence = 0;

/** 每个用例一颗独立的 development 目录。 */
function freshDevelopment(): string {
  sequence += 1;
  const dir = join(env.workspaceDir, '.smart-factory', 'agents', `prod-${sequence}`, 'development');
  mkdirSync(dir, { recursive: true });
  return dir;
}

function write(path: string, content: string): void {
  mkdirSync(join(path, '..'), { recursive: true });
  writeFileSync(path, content);
}

interface StateOptions {
  pipeline?: 'agent-creation' | 'agent-creation-fast';
  status?: string;
  step?: string;
}

function writeState(development: string, name: string, options: StateOptions = {}): void {
  const { pipeline = 'agent-creation', status = 'COMPLETED', step = 'step-5-readiness-verification' } = options;
  write(
    join(development, '.agent-genesis', 'work', name, 'orchestrator-state.yaml'),
    [
      `pipeline: ${pipeline}`,
      `pipeline_status: ${status}`,
      `current_step: ${step}`,
      'last_update: 2026-10-20T09:00:00Z',
      'total_retry_count: 1',
      'pipeline_retry_budget: 5',
      'steps:',
      '  - step_id: step-1-requirement-clarification',
      '  - step_id: step-4-implementation',
      '  - step_id: step-4-implementation',
      '',
    ].join('\n'),
  );
}

function writeGate(development: string, name: string, file: string, verdict: string, concerns: unknown[] = []): void {
  write(
    join(development, '.agent-genesis', 'work', name, 'gate-results', file),
    JSON.stringify({ verdict, concerns }),
  );
}

function writeProduct(development: string, name = 'demo', version = 'v1'): void {
  write(join(development, 'output', 'agents', name, version, 'CLAUDE.md'), '# demo\n');
}

test('无状态、无产物、无门禁 → not_started', () => {
  const snapshot = readProductionStatus(freshDevelopment());
  assert.equal(snapshot.status, 'not_started');
  assert.equal(snapshot.ready, false);
  assert.deepEqual(snapshot.reasons, ['尚未开始生成智能体']);
  assert.equal(snapshot.pipeline, null);
  assert.equal(snapshot.product, null);
});

test('生成已启动但没有状态 / 产物 / 门禁（服务重启中断）→ failed，不是 not_started', () => {
  const interrupted = freshDevelopment();
  // 技能一启动就会建 work/{name}/ 并落 env-readiness.yaml，orchestrator-state.yaml 要晚得多
  write(
    join(interrupted, '.agent-genesis', 'work', 'weather-agent', 'env-readiness.yaml'),
    'checked_at: 2026-10-28T03:36:00Z\n',
  );

  const snapshot = readProductionStatus(interrupted);
  assert.equal(snapshot.status, 'failed');
  assert.equal(snapshot.ready, false);
  assert.equal(snapshot.reasons[0], '生成流程已开始但未完成，请重新发起生成');
  assert.equal(snapshot.pipeline, null, '没有状态文件时 pipeline 仍为 null');
  assert.equal(snapshot.product, null);
});

test('work/ 下只有空目录也算开过工：failed 而不是 not_started', () => {
  const interrupted = freshDevelopment();
  mkdirSync(join(interrupted, '.agent-genesis', 'work', 'demo'), { recursive: true });

  const snapshot = readProductionStatus(interrupted);
  assert.equal(snapshot.status, 'failed');
});

test('full 车道：COMPLETED + 交付门禁 PASS/CONCERNS + 产物 → completed', () => {
  const pass = freshDevelopment();
  writeProduct(pass);
  writeState(pass, 'demo');
  writeGate(pass, 'demo', 'step-4-implementation.json', 'PASS');

  const completed = readProductionStatus(pass);
  assert.equal(completed.status, 'completed');
  assert.equal(completed.ready, true);
  assert.equal(completed.lane, 'full');
  assert.equal(completed.pipeline?.status, 'COMPLETED');
  assert.equal(completed.pipeline?.completedSteps, 2, 'steps 去重');
  assert.equal(completed.delivery?.verdict, 'PASS');
  assert.equal(completed.delivery?.source, 'step-4-implementation.json');
  assert.equal(completed.product?.name, 'demo');
  assert.equal(completed.product?.version, 'v1');
  assert.equal(completed.product?.path, 'output/agents/demo/v1');
  assert.deepEqual(completed.reasons, []);
  assert.equal(locateProducedAgent(pass).dir, join(pass, 'output', 'agents', 'demo', 'v1'));

  const concerns = freshDevelopment();
  writeProduct(concerns);
  writeState(concerns, 'demo');
  writeGate(concerns, 'demo', 'step-4-implementation.json', 'CONCERNS', [{ detail: '文件清单偏少' }]);
  const withConcerns = readProductionStatus(concerns);
  assert.equal(withConcerns.status, 'completed', 'CONCERNS 按技能里程碑仍可交付');
  assert.deepEqual(withConcerns.delivery?.concerns, ['文件清单偏少']);
});

test('fast 车道：不写 COMPLETED，step-f1 收尾 + 门禁 PASS 也算 completed', () => {
  const development = freshDevelopment();
  writeProduct(development);
  writeState(development, 'demo', {
    pipeline: 'agent-creation-fast',
    status: 'IN_PROGRESS',
    step: 'step-f1-fast-build',
  });
  writeGate(development, 'demo', 'step-f1-fast-build.json', 'PASS');

  const snapshot = readProductionStatus(development);
  assert.equal(snapshot.lane, 'fast');
  assert.equal(snapshot.pipeline?.status, 'IN_PROGRESS');
  assert.equal(snapshot.status, 'completed');
  assert.equal(snapshot.ready, true);
  assert.equal(snapshot.delivery?.source, 'step-f1-fast-build.json');
  assert.equal(locateProducedAgent(development).version, 'v1');
});

test('fast optimize 车道：step-f2 收尾 + 门禁 PASS 也算 completed', () => {
  const completed = freshDevelopment();
  writeProduct(completed);
  writeState(completed, 'demo', {
    pipeline: 'agent-creation-fast',
    status: 'COMPLETED',
    step: 'step-f2-fast-optimize',
  });
  writeGate(completed, 'demo', 'step-f2-fast-optimize.json', 'PASS');

  const snapshot = readProductionStatus(completed);
  assert.equal(snapshot.lane, 'fast');
  assert.equal(snapshot.status, 'completed');
  assert.equal(snapshot.ready, true);
  assert.equal(snapshot.delivery?.source, 'step-f2-fast-optimize.json');
  assert.equal(locateProducedAgent(completed).version, 'v1');

  // fast 驱动不写 COMPLETED 时，认收尾步本身
  const inProgress = freshDevelopment();
  writeProduct(inProgress);
  writeState(inProgress, 'demo', {
    pipeline: 'agent-creation-fast',
    status: 'IN_PROGRESS',
    step: 'step-f2-fast-optimize',
  });
  writeGate(inProgress, 'demo', 'step-f2-fast-optimize.json', 'PASS');
  assert.equal(readProductionStatus(inProgress).status, 'completed');
});

test('fast 车道未收尾 / 门禁 FAIL：不能进预览评估', () => {
  const running = freshDevelopment();
  writeProduct(running);
  writeState(running, 'demo', { pipeline: 'agent-creation-fast', status: 'IN_PROGRESS', step: 'step-f1-fast-build' });
  assert.equal(readProductionStatus(running).status, 'building');

  const failed = freshDevelopment();
  writeProduct(failed);
  writeState(failed, 'demo', { pipeline: 'agent-creation-fast', status: 'IN_PROGRESS', step: 'step-f1-fast-build' });
  writeGate(failed, 'demo', 'step-f1-fast-build.json', 'FAIL');
  assert.equal(readProductionStatus(failed).status, 'failed');
  assert.deepEqual(readProductionStatus(failed).reasons, ['生成产物未通过质量门禁']);
});

test('development 有活跃 run：即使旧状态与门禁都已完成也按 building', () => {
  const development = freshDevelopment();
  writeProduct(development);
  writeState(development, 'demo');
  writeGate(development, 'demo', 'step-4-implementation.json', 'PASS');

  const snapshot = readProductionStatus(development, { hasActiveRun: true });
  assert.equal(snapshot.status, 'building');
  assert.equal(snapshot.ready, false);
  assert.match(snapshot.reasons[0]!, /正在生成/);
});

test('BLOCKED / FAILED / 门禁 FAIL → 各自的状态，不能进入预览评估', () => {
  const blocked = freshDevelopment();
  writeProduct(blocked);
  writeState(blocked, 'demo', { status: 'BLOCKED' });
  writeGate(blocked, 'demo', 'step-4-implementation.json', 'PASS');
  assert.equal(readProductionStatus(blocked).status, 'blocked');

  const failed = freshDevelopment();
  writeProduct(failed);
  writeState(failed, 'demo', { status: 'FAILED' });
  assert.equal(readProductionStatus(failed).status, 'failed');

  const gateFailed = freshDevelopment();
  writeProduct(gateFailed);
  writeState(gateFailed, 'demo');
  writeGate(gateFailed, 'demo', 'step-4-implementation.json', 'FAIL');
  assert.equal(readProductionStatus(gateFailed).status, 'failed');
});

test('COMPLETED 但缺交付门禁 / 缺产物 → failed（fail-closed）', () => {
  const noGate = freshDevelopment();
  writeProduct(noGate);
  writeState(noGate, 'demo');
  const missingGate = readProductionStatus(noGate);
  assert.equal(missingGate.status, 'failed');
  assert.deepEqual(missingGate.reasons, ['生成流程已结束，但交付门禁未通过']);
  assert.throws(() => locateProducedAgent(noGate), (error: unknown) => error instanceof ConflictError && /pipeline_status/.test(error.message));

  const noProduct = freshDevelopment();
  writeState(noProduct, 'demo');
  writeGate(noProduct, 'demo', 'step-4-implementation.json', 'PASS');
  const missingProduct = readProductionStatus(noProduct);
  assert.equal(missingProduct.status, 'failed');
  assert.deepEqual(missingProduct.reasons, ['生成产物缺失']);
});

test('有产物但缺状态 / 状态不唯一 → failed', () => {
  const noState = freshDevelopment();
  writeProduct(noState);
  const missingState = readProductionStatus(noState);
  assert.equal(missingState.status, 'failed');
  assert.deepEqual(missingState.reasons, ['缺少生成过程状态，无法确认产物完成']);

  const ambiguous = freshDevelopment();
  writeProduct(ambiguous);
  writeState(ambiguous, 'other');
  writeState(ambiguous, 'another');
  const duplicated = readProductionStatus(ambiguous);
  assert.equal(duplicated.status, 'failed');
  assert.match(duplicated.reasons[0]!, /状态不唯一/);
});

test('门禁优先读 g028-exit-sanity.json，其次按车道回落', () => {
  const development = freshDevelopment();
  writeProduct(development);
  writeState(development, 'demo');
  writeGate(development, 'demo', 'step-4-implementation.json', 'FAIL');
  writeGate(development, 'demo', 'g028-exit-sanity.json', 'PASS');

  const snapshot = readProductionStatus(development);
  assert.equal(snapshot.status, 'completed');
  assert.equal(snapshot.delivery?.source, 'g028-exit-sanity.json');
});
