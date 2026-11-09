import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { prepareTestEnv } from './helpers/test-db.js';
import { agentRootIn, seedAgent } from './helpers/agents.js';
import { startWorkspaceStub } from './helpers/workspace-stub.js';
import { API, startTestApi, type TestApi } from './helpers/http.js';

/**
 * 评估报告接口验收（4.09-评估报告 §10）。
 *
 * fixture 按「样例报告」的口径构造：4 条用例、加权分 5/5/5/3.85、15 项期望 14 中 1 失、
 * 审计均分 4.4 且两条检查未通过（去重后 failedChecks = 2）。分数断言由 fixture 推导，
 * 与服务端的评分口径（§5.3）互为印证。
 */

const env = prepareTestEnv('evaluation-api');
const stub = await startWorkspaceStub(env);

let api: TestApi;

const AGENT = 'eval-demo';
const AGENT_EMPTY = 'eval-none';
const REPORT = 'e2e-test-20261016-095720';
const REPORT_PARTIAL = 'e2e-test-20261015-000000';
const REPORT_FALLBACK = 'e2e-test-20261014-000000';
const REPORT_RUNNING = 'e2e-test-20261017-000000';

before(async () => {
  api = await startTestApi();
  await seedAgent(AGENT);
  await seedAgent(AGENT_EMPTY);
  seedCompletedReport(join(agentRootIn(env.workspaceDir, AGENT), 'evaluation', REPORT));
  seedPartialReport(join(agentRootIn(env.workspaceDir, AGENT), 'evaluation', REPORT_PARTIAL));
  seedFallbackAuditReport(join(agentRootIn(env.workspaceDir, AGENT), 'evaluation', REPORT_FALLBACK));
  seedRunningReport(join(agentRootIn(env.workspaceDir, AGENT), 'evaluation', REPORT_RUNNING));
});

after(async () => {
  await api.close();
  await stub.close();
});

function write(path: string, content: string | object): void {
  mkdirSync(join(path, '..'), { recursive: true });
  writeFileSync(path, typeof content === 'string' ? content : JSON.stringify(content));
}

function seedJsonl(path: string, rows: object[]): void {
  write(path, rows.map((row) => JSON.stringify(row)).join('\n') + '\n');
}

/** 四条用例的共享骨架：data_id / dimension / 期望项数与命中分布 / run exit_code。 */
const CASES = [
  { id: 'calculator_functional_001', dimension: 'functional', items: 4, miss: 0, weighted: 5, exitCode: 0 },
  { id: 'calculator_boundary_001', dimension: 'boundary', items: 4, miss: 0, weighted: 5, exitCode: 1 },
  { id: 'calculator_functional_002', dimension: 'functional', items: 4, miss: 0, weighted: 5, exitCode: 0 },
  { id: 'calculator_instruction_001', dimension: 'instruction', items: 3, miss: 1, weighted: 3.85, exitCode: 0 },
];

function seedCompletedReport(report: string): void {
  write(join(report, 'generated_datasets', 'manifest.json'), {
    task_id: 'calculator_20261016-095737',
    agent_sha256: 'a'.repeat(64),
    created_at: '2026-10-16T01:59:03.000Z',
    tool_version: 'goldeval-generate/0.1.0',
  });
  write(join(report, 'generated_datasets', 'eval-plan.json'), {
    tier: 'A',
    count_target: 5,
    count_actual: 4,
    totals: { from_gwt: 4, from_llm: 0 },
    repair_rounds: 0,
    coverage: [
      { dimension: 'functional', name: '功能正确性', weight: 3, actual_total: 2 },
      { dimension: 'boundary', name: '边界与鲁棒性', weight: 2, actual_total: 1 },
      { dimension: 'instruction', name: '指令遵循与输出格式', weight: 2, actual_total: 1 },
    ],
    rejected: [{ source_ref: 'pass-criteria.md#3', errors: ['input 短于 4 字符'] }],
  });
  write(join(report, 'generated_datasets', 'report.md'), '# 生成报告\n');
  write(join(report, 'run_datasets', 'run-manifest.json'), { matches: true, isolation: 'per-case-copy' });
  seedJsonl(
    join(report, 'run_datasets', 'seed.jsonl'),
    CASES.map((item) => ({ data_id: item.id, dimension: item.dimension })),
  );
  for (const item of CASES) {
    write(join(report, 'run_datasets', item.id, 'timing.json'), {
      elapsed_seconds: 27.2,
      exit_code: item.exitCode,
      timed_out: false,
    });
    write(join(report, 'run_datasets', item.id, 'result.json'), {
      is_error: false,
      num_turns: 5,
      total_cost_usd: 0.32,
      session_id: `sess-${item.id}`,
      result: '结果: 11',
      usage: { input_tokens: 100, output_tokens: 10 },
    });
  }
  write(join(report, 'eval_datasets', 'eval-manifest.json'), {
    tool_version: 'e2e-test-evaluator/0.1.0',
    input_seed: '/host/abs/eval_datasets/seed.jsonl',
    rubric_path: '/host/abs/runtime-rubric.md',
    rubric_sha256: 'b'.repeat(64),
    concurrency: 2,
    thresholds: { weighted: 3.5, correctness: 3, completeness: 3 },
    dimension_weights: { correctness: 0.4, completeness: 0.3, format_compliance: 0.15, actionability: 0.15 },
    judge: { model: 'judge-model', main_agent_model: 'main-model' },
  });
  seedJsonl(
    join(report, 'eval_datasets', 'seed.jsonl'),
    CASES.map((item) => ({
      data_id: item.id,
      dimension: item.dimension,
      capability_ref: 'C02',
      input: '3+4*2',
      precondition: '被测 Agent 已就绪。',
      expected_output: ['结果为 11'],
      eval: {
        status: 'ok',
        invalid_reason: null,
        attempts: 1,
        items: Array.from({ length: item.items }, (_, index) => ({
          text: `期望 ${index + 1}`,
          verdict: index < item.items - item.miss ? 'hit' : 'miss',
          note: '判定说明。',
        })),
        correctness: 5,
        completeness: 5,
        format_compliance: 5,
        actionability: 5,
        weighted_score: item.weighted,
        passed: true,
        reasoning: '证据充分。',
      },
    })),
  );
  write(join(report, 'eval_datasets', 'report.md'), '# 结果报告\n');

  // 轨迹审计批：线上落点 eval_trace_results/。
  const batch = join(report, 'eval_trace_results', 'batch_20261016T020816Z');
  write(join(batch, 'batch-summary.json'), {
    meta: {
      skill: 'traceaudit',
      generatedAt: '2026-10-16T02:08:16.840Z',
      recordCount: 4,
      failed: 0,
      evaluatorVersion: '0.1.0',
      rubricVersion: 'v2',
    },
    aggregate: {
      evaluatedCount: 4,
      averageTotalScore: 4.4,
      dimensionAverages: {
        processCompliance: { id: 'processCompliance', name: '流程合规性', weight: 0.3, averageScore: 5, scoredCount: 4 },
        ruleCompliance: { id: 'ruleCompliance', name: '规则合规性', weight: 0.15, averageScore: 1, scoredCount: 4 },
      },
    },
    cases: CASES.map((item) => ({ slug: item.id, dataId: item.id, totalScore: 4.4, grade: 'ACCEPTABLE', status: 'ok' })),
  });
  write(join(batch, 'batch-summary.md'), '# 审计汇总\n');
  for (const item of CASES) {
    write(join(batch, 'cases', item.id, 'rubric-scores.json'), {
      meta: { caseId: `sess-${item.id}` },
      scores: {
        processCompliance: {
          score: 5,
          weight: 0.3,
          weightedScore: 1.5,
          label: '完全合规',
          summary: '合规。',
          failedTasks: [],
          checks: [{ checkId: 'workflow_step_order', passed: true, severity: 'medium', expected: '先读后写', actual: [], evidence: '顺序成立' }],
        },
        ruleCompliance: {
          score: 1,
          weight: 0.15,
          weightedScore: 0.15,
          label: '严重违规',
          summary: '主流程直连 Skill。',
          failedTasks: [],
          checks: [
            { checkId: 'no_direct_skill_in_main_flow', passed: false, severity: 'critical', expected: 0, actual: [{ eventIndex: 7 }], evidence: 'Parent flow direct Skill calls: 7' },
            { checkId: 'phase3_no_skill_direct_call', passed: false, severity: 'critical', expected: 0, actual: [{ eventIndex: 9 }], evidence: 'Parent flow direct Skill calls: 7' },
          ],
        },
      },
      totalScore: 4.4,
      grade: 'ACCEPTABLE',
      verdict: '轨迹过程基本可接受，存在少量需改进项。',
    });
    write(join(batch, 'cases', item.id, 'trajectory-report.md'), '# 轨迹报告\n');
    write(join(batch, 'cases', item.id, 'trajectory-report.json'), { verdict: 'ok' });
  }
}

/** 只完成 plan 一步的报告：验证 partial 状态（§6）。 */
function seedPartialReport(report: string): void {
  write(join(report, 'generated_datasets', 'manifest.json'), {
    task_id: 'calculator_20261015-000000',
    created_at: '2026-10-15T00:00:00.000Z',
  });
  write(join(report, 'generated_datasets', 'eval-plan.json'), { tier: 'A' });
}

/** 生成完成、执行未开始：只有 generated seed。评分阶段之前右侧也应当能列出测试集。 */
function seedRunningReport(report: string): void {
  write(join(report, 'generated_datasets', 'manifest.json'), {
    task_id: 'calculator_20261017-000000',
    created_at: '2026-10-17T00:00:00.000Z',
  });
  write(join(report, 'generated_datasets', 'eval-plan.json'), { tier: 'A' });
  seedJsonl(
    join(report, 'generated_datasets', 'seed.jsonl'),
    CASES.map((item) => ({
      data_id: item.id,
      dimension: item.dimension,
      input: '3+4*2',
      expected_output: ['结果为 11'],
    })),
  );
}

/** 审计批放在文档 §2.1 的 eval_results/ 落点：两个落点都认。 */
function seedFallbackAuditReport(report: string): void {
  const batch = join(report, 'eval_results', 'batch_20261014T000000Z');
  write(join(batch, 'batch-summary.json'), {
    meta: { skill: 'traceaudit', generatedAt: '2026-10-14T00:00:00.000Z', recordCount: 1, failed: 0 },
    aggregate: { evaluatedCount: 1, averageTotalScore: 4, dimensionAverages: {} },
    cases: [{ slug: 'c1', totalScore: 4, grade: 'ACCEPTABLE' }],
  });
}

// ── list ────────────────────────────────────────────────────────────────────

test('evaluations/list：降序、completed 摘要与 4.09 的口径一致', async () => {
  const { status, body } = await api.get(`${API}/evaluations/list?agentId=${AGENT}`);
  assert.equal(status, 200);
  assert.equal(body.total, 4);
  const [running, latest, partial, fallback] = body.items;
  assert.equal(running.reportId, REPORT_RUNNING);
  assert.deepEqual(running.counts, {
    total: 4,
    valid: 0,
    invalid: 0,
    pending: 4,
    passed: 0,
    failed: 0,
    expectedTotal: 0,
    expectedHit: 0,
    expectedMiss: 0,
  });
  assert.equal(latest.reportId, REPORT);

  assert.equal(latest.status, 'completed');
  assert.equal(latest.title, 'calculator_20261016-095737');
  assert.equal(latest.createdAt, '2026-10-16T01:59:03.000Z');
  assert.deepEqual(latest.pipeline.plan, { state: 'done', at: '2026-10-16T01:59:03.000Z' });
  assert.equal(latest.pipeline.audit.state, 'done');

  assert.deepEqual(
    { ...latest.counts },
    { total: 4, valid: 4, invalid: 0, pending: 0, passed: 4, failed: 0, expectedTotal: 15, expectedHit: 14, expectedMiss: 1 },
  );
  assert.equal(latest.scores.weightedAverage, 4.71, '(5+5+5+3.85)/4 = 4.7125 → 4.71');
  assert.equal(latest.scores.passRate, 1);
  assert.equal(latest.scores.dimensions.correctness, 5);
  assert.deepEqual(latest.thresholds, { weighted: 3.5, correctness: 3, completeness: 3, met: true });
  assert.deepEqual(latest.audit, { average: 4.4, grade: 'ACCEPTABLE', evaluated: 4, failed: 0, failedChecks: 2 });
  assert.equal(latest.stale, false);
  assert.deepEqual(latest.warnings, []);

  assert.equal(partial.status, 'partial');
  assert.equal(partial.pipeline.plan.state, 'done');
  assert.equal(partial.pipeline.run.state, 'pending');

  // 审计批在文档落点 eval_results/ 下也能被发现
  assert.equal(fallback.reportId, REPORT_FALLBACK);
  assert.equal(fallback.pipeline.audit.state, 'done');
  assert.equal(fallback.audit?.average, 4);
});

test('evaluations/list：没有报告的智能体给 200 空页；未知智能体 404', async () => {
  const empty = await api.get(`${API}/evaluations/list?agentId=${AGENT_EMPTY}`);
  assert.equal(empty.status, 200);
  assert.deepEqual(empty.body, { items: [], total: 0, page: 1, pageSize: 20 });

  const unknown = await api.get(`${API}/evaluations/list?agentId=eval-absent`);
  assert.equal(unknown.status, 404);
});

test('evaluations/list：status 过滤生效，非法枚举 400', async () => {
  const completed = await api.get(`${API}/evaluations/list?agentId=${AGENT}&status=completed`);
  assert.equal(completed.body.total, 1);
  assert.equal(completed.body.items[0].reportId, REPORT);

  const bad = await api.get(`${API}/evaluations/list?agentId=${AGENT}&status=nope`);
  assert.equal(bad.status, 400);
  assert.equal(bad.body.error, 'BAD_REQUEST');
});

// ── detail ──────────────────────────────────────────────────────────────────

test('evaluations/detail：扩展块（tools/judge/coverage/auditDetails/environment/files）', async () => {
  const { status, body } = await api.get(`${API}/evaluations/detail?agentId=${AGENT}&reportId=${REPORT}`);
  assert.equal(status, 200);

  assert.deepEqual(body.tools.generate, { name: 'goldeval-generate', version: '0.1.0' });
  assert.deepEqual(body.tools.evaluate, { name: 'e2e-test-evaluator', version: '0.1.0' });
  assert.equal(body.tools.audit.name, 'traceaudit');
  assert.equal(body.judge.model, 'judge-model');

  assert.equal(body.coverage.tier, 'A');
  assert.equal(body.coverage.fromGwt, 4);
  assert.deepEqual(body.coverage.rejected, [{ sourceRef: 'pass-criteria.md#3', reason: 'input 短于 4 字符' }]);

  // 检查行：4 条用例 × 3 检查 = 12 行，通过的与未通过的都在（§5.2）
  assert.equal(body.auditDetails.checks.length, 12);
  const failedCheckIds = new Set(
    body.auditDetails.checks.filter((check: any) => !check.passed).map((check: any) => check.checkId),
  );
  assert.deepEqual(
    failedCheckIds,
    new Set(['no_direct_skill_in_main_flow', 'phase3_no_skill_direct_call']),
  );
  assert.equal(body.auditDetails.dimensions[0].name, '流程合规性');

  // 绝对路径不下发（§2.3）
  assert.equal(body.environment.inputSeed, 'eval_datasets/seed.jsonl');
  assert.equal(body.environment.rubric.file, 'runtime-rubric.md');
  assert.equal(body.environment.agentShaMatches, true);
  assert.equal(body.environment.isolation, 'per-case-copy');

  assert.equal(body.files.reportMd, 'eval_datasets/report.md');
  assert.equal(body.files.auditReportMd, 'eval_trace_results/batch_20261016T020816Z/batch-summary.md');
});

test('evaluations/detail：reportId 形态非法 400；形态合法但目录不存在 404', async () => {
  const escape = await api.get(`${API}/evaluations/detail?agentId=${AGENT}&reportId=${encodeURIComponent('../x')}`);
  assert.equal(escape.status, 400);

  const missing = await api.get(`${API}/evaluations/detail?agentId=${AGENT}&reportId=e2e-test-19990101-000000`);
  assert.equal(missing.status, 404);
  assert.equal(missing.body.error, 'NOT_FOUND');
});

// ── cases ───────────────────────────────────────────────────────────────────

test('evaluations/cases/list：seed 顺序、run 元数据与审计分逐用例对上', async () => {
  const { status, body } = await api.get(`${API}/evaluations/cases/list?agentId=${AGENT}&reportId=${REPORT}`);
  assert.equal(status, 200);
  assert.equal(body.total, 4);

  const first = body.items[0];
  assert.equal(first.caseId, 'calculator_functional_001');
  assert.equal(first.dimensionLabel, '功能正确性');
  assert.equal(first.status, 'passed');
  assert.equal(first.run.elapsedMs, 27200);
  assert.equal(first.run.status, 'passed');
  assert.deepEqual(first.audit, { totalScore: 4.4, grade: 'ACCEPTABLE' });

  // exit_code 1 → run failed，但评分仍 passed：两个口径不混用（§5.4）
  const boundary = body.items.find((item: any) => item.caseId === 'calculator_boundary_001');
  assert.equal(boundary.run.status, 'failed');
  assert.equal(boundary.status, 'passed');

  const instruction = body.items.find((item: any) => item.caseId === 'calculator_instruction_001');
  assert.deepEqual(instruction.expected, { total: 3, hit: 2, miss: 1 });
  assert.equal(instruction.weightedScore, 3.85);
});

test('evaluations/cases/list：还没评分时从 generated seed 列出测试集，scored=false', async () => {
  const { status, body } = await api.get(
    `${API}/evaluations/cases/list?agentId=${AGENT}&reportId=${REPORT_RUNNING}&page=1&pageSize=200`,
  );
  assert.equal(status, 200);
  assert.equal(body.total, 4);
  assert.deepEqual(
    body.items.map((item: any) => item.caseId),
    CASES.map((item) => item.id),
  );
  assert.ok(body.items.every((item: any) => item.scored === false), '评分前 scored 必须是 false');
  assert.ok(body.items.every((item: any) => item.status === 'invalid'), '未评分沿用 invalid，靠 scored 区分');
  assert.equal(body.items[0].input, '3+4*2');
});

test('evaluations/cases/detail：还没评分时期望项退回 seed，判定 unknown', async () => {
  const { status, body } = await api.get(
    `${API}/evaluations/cases/detail?agentId=${AGENT}&reportId=${REPORT_RUNNING}&caseId=${CASES[0]!.id}`,
  );
  assert.equal(status, 200);
  assert.equal(body.scored, false);
  assert.deepEqual(body.expectedItems, [{ text: '结果为 11', verdict: 'unknown', note: null }]);
});

test('evaluations/cases/list：status / dimension 过滤生效，非法枚举 400', async () => {
  const passed = await api.get(`${API}/evaluations/cases/list?agentId=${AGENT}&reportId=${REPORT}&status=passed`);
  assert.equal(passed.body.total, 4);

  const functional = await api.get(`${API}/evaluations/cases/list?agentId=${AGENT}&reportId=${REPORT}&dimension=functional`);
  assert.equal(functional.body.total, 2);

  const bad = await api.get(`${API}/evaluations/cases/list?agentId=${AGENT}&reportId=${REPORT}&status=nope`);
  assert.equal(bad.status, 400);
});

test('evaluations/cases/detail：期望项、输出预览、usage、审计明细与文件相对路径', async () => {
  const { status, body } = await api.get(
    `${API}/evaluations/cases/detail?agentId=${AGENT}&reportId=${REPORT}&caseId=calculator_instruction_001`,
  );
  assert.equal(status, 200);

  assert.equal(body.precondition, '被测 Agent 已就绪。');
  assert.equal(body.expectedItems.length, 3);
  assert.equal(body.expectedItems.filter((item: any) => item.verdict === 'miss').length, 1);
  assert.equal(body.resultPreview, '结果: 11');
  assert.deepEqual(body.usage, { inputTokens: 100, outputTokens: 10, costUsd: 0.32 });

  assert.equal(body.auditDetails.verdict, '轨迹过程基本可接受，存在少量需改进项。');
  assert.equal(body.auditDetails.dimensions[0].name, '流程合规性');
  assert.equal(body.auditDetails.checks.filter((check: any) => !check.passed).length, 2);

  assert.equal(body.files.result, 'run_datasets/calculator_instruction_001/result.json');
  assert.equal(
    body.files.auditReportMd,
    'eval_trace_results/batch_20261016T020816Z/cases/calculator_instruction_001/trajectory-report.md',
  );
});

test('evaluations/cases/detail：caseId 带路径段 400；不在报告里 404', async () => {
  const escape = await api.get(
    `${API}/evaluations/cases/detail?agentId=${AGENT}&reportId=${REPORT}&caseId=${encodeURIComponent('a/b')}`,
  );
  assert.equal(escape.status, 400);

  const missing = await api.get(
    `${API}/evaluations/cases/detail?agentId=${AGENT}&reportId=${REPORT}&caseId=no_such_case`,
  );
  assert.equal(missing.status, 404);
});
