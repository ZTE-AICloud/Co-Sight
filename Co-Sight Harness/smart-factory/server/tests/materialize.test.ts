/**
 * 产物定位与 preview / evaluation 物化。
 *
 * 规则见 03-architecture/03-session-run.md §1.4 与 07-artifact.md §2、§3：
 * 生产过程状态必须 COMPLETED，产物根固定为 output/agents，最新 v* 作为源，源 mtime 未变则跳过。
 */
import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, statSync, utimesSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';

const env = prepareTestEnv('materialize');

const { ConflictError, NotFoundError } = await import('../src/shared/errors.js');
const { agentRoot, stageDir, stateDir } = await import('../src/shared/workspace/dir-resolver.js');
const { ensureMaterialized, locateProducedAgent, resolveStageCwd } = await import('../src/shared/workspace/materialize.js');

after(() => {
  // 无需断开 Prisma：本文件不导入 client
});

let sequence = 0;

/** 每个用例一颗独立的 agentRoot，避免互相污染。 */
function freshRoot(): string {
  sequence += 1;
  const id = `mat-${sequence}`;
  const root = agentRoot(env.workspaceDir, id);
  mkdirSync(join(root, 'development'), { recursive: true });
  return root;
}

function write(path: string, content: string): void {
  mkdirSync(join(path, '..'), { recursive: true });
  writeFileSync(path, content);
}

/** 生产过程状态 + 交付门禁：状态文件必须收尾，gate-results 里的 verdict 必须是 PASS/CONCERNS。 */
function writeState(root: string, name: string, status = 'COMPLETED'): void {
  const work = join(root, 'development', '.agent-genesis', 'work', name);
  write(
    join(work, 'orchestrator-state.yaml'),
    [
      'pipeline: agent-creation',
      `pipeline_status: ${status}`,
      'current_step: step-5-readiness-verification',
      'total_retry_count: 0',
      'pipeline_retry_budget: 5',
      'steps:',
      '  - step_id: step-4-implementation',
      '',
    ].join('\n'),
  );
  if (status === 'COMPLETED') {
    write(join(work, 'gate-results', 'step-4-implementation.json'), JSON.stringify({ verdict: 'PASS', concerns: [] }));
  }
}

test('locateProducedAgent：output/agents 下唯一智能体目录 + 最新 vN', () => {
  const root = freshRoot();
  const development = stageDir(root, 'development');
  write(join(development, 'output', 'agents', 'demo', 'v1', 'a.txt'), 'v1');
  write(join(development, 'output', 'agents', 'demo', 'v2', 'a.txt'), 'v2');
  write(join(development, 'output', 'agents', 'demo', 'v10', 'a.txt'), 'v10');
  writeState(root, 'demo');

  const produced = locateProducedAgent(development);
  assert.equal(produced.agentName, 'demo');
  assert.equal(produced.version, 'v10');
  assert.equal(produced.dir, join(development, 'output', 'agents', 'demo', 'v10'));
  assert.equal(readFileSync(join(produced.dir, 'a.txt'), 'utf8'), 'v10');
});

test('locateProducedAgent：只认 output/agents，不再回退旧布局', () => {
  const root = freshRoot();
  const development = stageDir(root, 'development');
  write(join(development, 'output', 'demo', 'v1', 'a.txt'), 'old');
  writeState(root, 'demo');

  assert.throws(() => locateProducedAgent(development), (error: unknown) => error instanceof NotFoundError);
});

test('locateProducedAgent：无候选、候选下多子目录、无 v* 版本都明确报错', () => {
  const none = freshRoot();
  assert.throws(() => locateProducedAgent(stageDir(none, 'development')), (error: unknown) => error instanceof NotFoundError);

  const ambiguous = freshRoot();
  write(join(stageDir(ambiguous, 'development'), 'output', 'agents', 'a', 'v1', 'x.txt'), 'x');
  write(join(stageDir(ambiguous, 'development'), 'output', 'agents', 'b', 'v1', 'x.txt'), 'x');
  writeState(ambiguous, 'a');
  assert.throws(
    () => locateProducedAgent(stageDir(ambiguous, 'development')),
    (error: unknown) => error instanceof ConflictError && /恰好一个/.test(error.message),
  );

  const noVersion = freshRoot();
  write(join(stageDir(noVersion, 'development'), 'output', 'agents', 'demo', 'draft', 'x.txt'), 'x');
  writeState(noVersion, 'demo');
  assert.throws(
    () => locateProducedAgent(stageDir(noVersion, 'development')),
    (error: unknown) => error instanceof ConflictError && /v\*/.test(error.message),
  );
});

test('locateProducedAgent：缺生产状态、pipeline_status 未完成、状态文件不唯一都拒绝', () => {
  const missing = freshRoot();
  write(join(stageDir(missing, 'development'), 'output', 'agents', 'demo', 'v1', 'x.txt'), 'x');
  assert.throws(
    () => locateProducedAgent(stageDir(missing, 'development')),
    (error: unknown) => error instanceof NotFoundError && /orchestrator-state\.yaml/.test(error.message),
  );

  const running = freshRoot();
  write(join(stageDir(running, 'development'), 'output', 'agents', 'demo', 'v1', 'x.txt'), 'x');
  writeState(running, 'demo', 'RUNNING');
  assert.throws(
    () => locateProducedAgent(stageDir(running, 'development')),
    (error: unknown) => error instanceof ConflictError && /pipeline_status/.test(error.message),
  );

  const ambiguous = freshRoot();
  write(join(stageDir(ambiguous, 'development'), 'output', 'agents', 'demo', 'v1', 'x.txt'), 'x');
  writeState(ambiguous, 'other');
  writeState(ambiguous, 'another');
  assert.throws(
    () => locateProducedAgent(stageDir(ambiguous, 'development')),
    (error: unknown) => error instanceof ConflictError && /状态不唯一/.test(error.message),
  );
});

test('locateProducedAgent：fast 车道以 step-f1 收尾 + 交付门禁判定完成', () => {
  const root = freshRoot();
  const development = stageDir(root, 'development');
  const work = join(development, '.agent-genesis', 'work', 'demo');
  write(join(development, 'output', 'agents', 'demo', 'v1', 'CLAUDE.md'), '# demo');
  write(
    join(work, 'orchestrator-state.yaml'),
    ['pipeline: agent-creation-fast', 'pipeline_status: IN_PROGRESS', 'current_step: step-f1-fast-build', 'steps:', '  - step_id: step-f1-fast-build', ''].join('\n'),
  );
  write(join(work, 'gate-results', 'step-f1-fast-build.json'), JSON.stringify({ verdict: 'PASS', concerns: [] }));

  // fast 驱动不写 COMPLETED：收尾 step + 门禁 PASS 同样放行
  assert.equal(locateProducedAgent(development).version, 'v1');
  assert.equal(ensureMaterialized({ agentRoot: root, stage: 'preview' }).skipped, false);
});

test('ensureMaterialized：整体拷贝版本内容，标记写在 .state/，源不变则跳过', () => {
  const root = freshRoot();
  const produced = join(stageDir(root, 'development'), 'output', 'agents', 'demo', 'v1');
  write(join(produced, 'notes', 'plan.md'), 'v1');
  writeState(root, 'demo');

  const first = ensureMaterialized({ agentRoot: root, stage: 'preview' });
  assert.equal(first.skipped, false);
  assert.equal(first.target, stageDir(root, 'preview'));
  assert.equal(readFileSync(join(first.target, 'notes', 'plan.md'), 'utf8'), 'v1');
  assert.ok(existsSync(join(stateDir(root), 'preview.json')), '标记放 agentRoot/.state/');

  const markerBefore = statSync(join(stateDir(root), 'preview.json')).mtimeMs;
  const second = ensureMaterialized({ agentRoot: root, stage: 'preview' });
  assert.equal(second.skipped, true);
  assert.equal(statSync(join(stateDir(root), 'preview.json')).mtimeMs, markerBefore, '跳过时不重写标记');
});

test('ensureMaterialized：evaluation 复制 preview 的沙箱内容', () => {
  const root = freshRoot();
  const development = stageDir(root, 'development');
  write(join(development, 'output', 'agents', 'demo', 'v1', 'app.txt'), 'v1');
  writeState(root, 'demo');

  const preview = ensureMaterialized({ agentRoot: root, stage: 'preview' });
  write(join(preview.target, 'preview-only.txt'), 'preview');

  const evaluation = ensureMaterialized({ agentRoot: root, stage: 'evaluation' });
  assert.equal(evaluation.source, stageDir(root, 'preview'));
  assert.equal(evaluation.target, join(stageDir(root, 'evaluation'), 'agent'), '副本收进沙箱根的 agent/');
  assert.equal(readFileSync(join(evaluation.target, 'preview-only.txt'), 'utf8'), 'preview');
  assert.equal(readFileSync(join(evaluation.target, 'app.txt'), 'utf8'), 'v1');
});

test('ensureMaterialized：源 mtime 变化后清空目标再整体拷贝；evaluation 复制 preview', () => {
  const root = freshRoot();
  const produced = join(stageDir(root, 'development'), 'output', 'agents', 'demo', 'v1');
  write(join(produced, 'app.txt'), 'v1');
  writeState(root, 'demo');

  ensureMaterialized({ agentRoot: root, stage: 'preview' });
  write(join(stageDir(root, 'preview'), 'stale.txt'), 'stale');
  mkdirSync(join(stageDir(root, 'preview'), 'stale-dir'), { recursive: true });

  // 明确把源文件 mtime 推到未来，避免同毫秒内写入导致「未变」判定
  const future = new Date(Date.now() + 5_000);
  utimesSync(join(produced, 'app.txt'), future, future);
  writeFileSync(join(produced, 'extra.txt'), 'new');

  const refreshed = ensureMaterialized({ agentRoot: root, stage: 'preview' });
  assert.equal(refreshed.skipped, false);
  assert.equal(readFileSync(join(refreshed.target, 'app.txt'), 'utf8'), 'v1');
  assert.equal(readFileSync(join(refreshed.target, 'extra.txt'), 'utf8'), 'new');
  assert.ok(!existsSync(join(refreshed.target, 'stale.txt')), '旧文件应被清掉');
  assert.ok(!existsSync(join(refreshed.target, 'stale-dir')), '旧目录应被清掉');

  const evaluation = ensureMaterialized({ agentRoot: root, stage: 'evaluation' });
  assert.equal(evaluation.source, stageDir(root, 'preview'));
  assert.equal(readFileSync(join(evaluation.target, 'app.txt'), 'utf8'), 'v1');
  assert.ok(existsSync(join(stateDir(root), 'evaluation.json')));
});

test('ensureMaterialized：评估报告与副本同级；重拷时旧报告随旧源版本作废', () => {
  const root = freshRoot();
  const produced = join(stageDir(root, 'development'), 'output', 'agents', 'demo', 'v1');
  write(join(produced, 'app.txt'), 'v1');
  writeState(root, 'demo');

  const evaluation = ensureMaterialized({ agentRoot: root, stage: 'evaluation' });
  const report = join(stageDir(root, 'evaluation'), 'e2e-test-20261020-000000');
  write(join(report, 'eval_datasets', 'report.md'), '# report');

  // 源未变：跳过，报告原样保留
  assert.equal(ensureMaterialized({ agentRoot: root, stage: 'evaluation' }).skipped, true);
  assert.ok(existsSync(join(report, 'eval_datasets', 'report.md')), '跳过硬拷不得动报告');

  // 源变了：整个评估根重来，报告与副本一起作废
  const future = new Date(Date.now() + 5_000);
  utimesSync(join(produced, 'app.txt'), future, future);
  const refreshed = ensureMaterialized({ agentRoot: root, stage: 'evaluation' });
  assert.equal(refreshed.skipped, false);
  assert.ok(!existsSync(report), '旧报告属于旧源版本，应被清掉');
  assert.ok(existsSync(join(refreshed.target, 'app.txt')), '新副本已就位');
});

test('ensureMaterialized：旧平铺布局就地升级进 agent/，已有报告原地保留', () => {
  const root = freshRoot();
  const produced = join(stageDir(root, 'development'), 'output', 'agents', 'demo', 'v1');
  write(join(produced, 'app.txt'), 'v1');
  writeState(root, 'demo');

  ensureMaterialized({ agentRoot: root, stage: 'preview' });
  ensureMaterialized({ agentRoot: root, stage: 'evaluation' });

  // 退回旧布局：副本平铺在沙箱根、没有 agent/，标记退回 v1；再放一份历史报告
  const evaluation = stageDir(root, 'evaluation');
  const agentDir = join(evaluation, 'agent');
  for (const name of readdirSync(agentDir)) renameSync(join(agentDir, name), join(evaluation, name));
  rmSync(agentDir, { recursive: true, force: true });
  const markerFile = join(stateDir(root), 'evaluation.json');
  const marker = JSON.parse(readFileSync(markerFile, 'utf8'));
  writeFileSync(markerFile, JSON.stringify({ ...marker, version: 1 }));
  const report = join(evaluation, 'e2e-test-20261020-000000', 'eval_datasets', 'report.md');
  write(report, '# report');

  const upgraded = ensureMaterialized({ agentRoot: root, stage: 'evaluation' });
  assert.equal(upgraded.skipped, false, '旧布局升级要走一次拷贝');
  assert.equal(upgraded.target, agentDir);
  assert.equal(readFileSync(join(agentDir, 'app.txt'), 'utf8'), 'v1');
  assert.ok(existsSync(report), '升级不得动历史报告');
  assert.ok(!existsSync(join(evaluation, 'app.txt')), '平铺副本已清掉');
  assert.equal(JSON.parse(readFileSync(markerFile, 'utf8')).version, 2, '标记升到 v2');
});

test('ensureMaterialized：源缺失报错，不拿空目录兜底', () => {
  const root = freshRoot();
  assert.throws(() => ensureMaterialized({ agentRoot: root, stage: 'preview' }), (error: unknown) => error instanceof NotFoundError);
  assert.ok(!existsSync(stageDir(root, 'preview')), '失败时不得留下空目标目录');
});

test('resolveStageCwd：development 要求目录存在；runtime 指向最新产物；preview 先物化', () => {
  const root = freshRoot();
  const development = stageDir(root, 'development');
  assert.equal(resolveStageCwd(root, 'development'), development);

  const missing = freshRoot();
  rmSync(stageDir(missing, 'development'), { recursive: true, force: true });
  assert.throws(() => resolveStageCwd(missing, 'development'), /development/);

  write(join(development, 'output', 'agents', 'demo', 'v2', 'app.txt'), 'x');
  writeState(root, 'demo');
  assert.equal(resolveStageCwd(root, 'runtime'), join(development, 'output', 'agents', 'demo', 'v2'));

  const preview = resolveStageCwd(root, 'preview');
  assert.equal(preview, stageDir(root, 'preview'));
  assert.equal(readFileSync(join(preview, 'app.txt'), 'utf8'), 'x');

  const evaluation = resolveStageCwd(root, 'evaluation');
  assert.equal(evaluation, join(stageDir(root, 'evaluation'), 'agent'));
  assert.equal(readFileSync(join(evaluation, 'app.txt'), 'utf8'), 'x');
});
