import type { PageResult } from '../types';
import { API_BASE_URL, createApiClient } from './client';

/**
 * 评估报告的数据入口。正本是 `server/docs/04-api/4.09-评估报告.md`，
 * 服务端实现 `server/src/modules/evaluation/`。
 *
 * 报告由评估技能写在 `<agentRoot>/evaluation/` 下的 e2e-test-* 目录里，服务端把它们
 * 归一化成这里的 DTO（哪份最新、什么算完成、两套分怎么算都在服务端定死）；原始文件
 * 仍可用 artifacts API 按 `stage=evaluation` + DTO 给出的相对路径浏览。
 *
 * 「结果质量」（scores，四维）与「轨迹合规」（audit，五维）是**两套分**，前端永远
 * 不要把它们合成一个数 —— 这个口径由服务端固定（4.09 §5.3）。
 */

export type EvaluationReportStatus = 'pending' | 'running' | 'completed' | 'partial' | 'failed';
export type EvaluationStepState = 'pending' | 'running' | 'done' | 'failed';

export interface EvaluationStep {
  state: EvaluationStepState;
  /** 该步骤完成 / 失败的时间；未完成或无法判断为 null */
  at: string | null;
}

export interface EvaluationAuditSummary {
  /** 审计平均总分 0–5 */
  average: number | null;
  /** 总分最低那条用例的 grade（「最差一条决定总体等级」） */
  grade: string | null;
  /** 参与审计的用例数 */
  evaluated: number;
  /** 审计执行失败的用例数（不是测试失败数，测试失败看 counts.failed） */
  failed: number;
  /** 未通过检查的去重 checkId 数 */
  failedChecks: number;
}

export interface EvaluationReportSummary {
  reportId: string;
  agentId: string;
  title: string;
  status: EvaluationReportStatus;
  createdAt: string;
  updatedAt: string;
  /** 相对 evaluation 根的目录，直接喂给 artifacts API */
  dir: string;
  pipeline: {
    plan: EvaluationStep;
    run: EvaluationStep;
    score: EvaluationStep;
    audit: EvaluationStep;
  };
  counts: {
    total: number;
    valid: number;
    /** 已评分但没评出结果 */
    invalid: number;
    /** 还没评分（生成 / 执行阶段） */
    pending: number;
    passed: number;
    failed: number;
    expectedTotal: number;
    expectedHit: number;
    expectedMiss: number;
  };
  scores: {
    weightedAverage: number | null;
    /** 0–1 */
    passRate: number | null;
    dimensions: {
      correctness: number | null;
      completeness: number | null;
      formatCompliance: number | null;
      actionability: number | null;
    };
    weights: {
      correctness: number;
      completeness: number;
      formatCompliance: number;
      actionability: number;
    };
  };
  thresholds: {
    weighted: number | null;
    correctness: number | null;
    completeness: number | null;
    met: boolean | null;
  };
  audit: EvaluationAuditSummary | null;
  /** 报告生成后开发产物变过，建议重跑 */
  stale: boolean | null;
  warnings: string[];
}

export interface EvaluationReportDetail extends EvaluationReportSummary {
  tools: {
    generate: { name: string | null; version: string | null };
    evaluate: { name: string | null; version: string | null };
    audit: { name: string | null; version: string | null; rubricVersion: string | null };
  };
  judge: {
    model: string | null;
    mainAgentModel: string | null;
  };
  coverage: {
    tier: string | null;
    target: number | null;
    actual: number | null;
    fromGwt: number | null;
    fromLlm: number | null;
    repairRounds: number | null;
    dimensions: { key: string; name: string; weight: number; count: number }[];
    rejected: { sourceRef: string; reason: string }[];
  } | null;
  auditDetails: {
    dimensions: { key: string; name: string; weight: number; average: number | null; scoredCount: number }[];
    /** 全部检查项，通过与未通过都在；前端按 passed 过滤 */
    checks: {
      caseId: string;
      dimension: string;
      checkId: string;
      passed: boolean;
      severity: string;
      expected: unknown;
      actual: unknown;
      evidence: string | null;
    }[];
  } | null;
  environment: {
    generatedAt: string | null;
    auditedAt: string | null;
    concurrency: number | null;
    rubric: { file: string | null; sha256: string | null };
    inputSeed: string | null;
    agentSha256: string | null;
    agentShaMatches: boolean | null;
    isolation: string | null;
  };
  /** 相对报告目录的文件路径；用 artifacts/file?path={report.dir}/{file} 读 */
  files: {
    generatedReportMd: string | null;
    reportMd: string | null;
    auditReportMd: string | null;
    seedJsonl: string | null;
  };
}

export type EvaluationCaseStatus = 'passed' | 'failed' | 'invalid';

export interface EvaluationCaseSummary {
  caseId: string;
  /** seed.jsonl 中的顺序，从 0 开始 */
  index: number;
  dimension: string;
  dimensionLabel: string;
  capabilityRef: string | null;
  input: string;
  status: EvaluationCaseStatus;
  /** false = 还没评分（生成 / 执行阶段），与「评了但失败」的 invalid 区分 */
  scored: boolean;
  weightedScore: number | null;
  scores: {
    correctness: number | null;
    completeness: number | null;
    formatCompliance: number | null;
    actionability: number | null;
  };
  expected: { total: number; hit: number; miss: number };
  /** 评估工具单条用例的执行结果，与服务端 Run.status（succeeded/failed/…）不是一个枚举 */
  run: {
    status: 'passed' | 'failed' | 'error' | 'timeout' | 'unknown' | null;
    elapsedMs: number | null;
    turns: number | null;
    exitCode: number | null;
    attempts: number;
  };
  audit: { totalScore: number | null; grade: string | null } | null;
  warnings: string[];
}

export interface EvaluationCaseDetail extends EvaluationCaseSummary {
  precondition: string | null;
  expectedItems: { text: string; verdict: 'hit' | 'miss' | 'unknown'; note: string | null }[];
  reasoning: string | null;
  /** run 输出预览，超 4000 字符截断 */
  resultPreview: string | null;
  usage: { inputTokens: number | null; outputTokens: number | null; costUsd: number | null } | null;
  auditDetails: {
    verdict: string | null;
    dimensions: {
      key: string;
      name: string | null;
      weight: number | null;
      score: number | null;
      weightedScore: number | null;
      label: string | null;
      summary: string | null;
      failedTasks: string[];
    }[];
    checks: {
      dimension: string;
      checkId: string;
      passed: boolean;
      severity: string;
      expected: unknown;
      actual: unknown;
      evidence: string | null;
    }[];
  } | null;
  files: {
    result: string | null;
    timing: string | null;
    stdout: string | null;
    stderr: string | null;
    session: string | null;
    auditReportMd: string | null;
    auditReportJson: string | null;
  };
}

const BASE_URL = import.meta.env.VITE_AGENTS_API_BASE_URL ?? `${API_BASE_URL}/smart-factory/v1`;
const client = createApiClient(BASE_URL);

function search(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded === '' ? '' : `?${encoded}`;
}

export interface EvaluationCaseListQuery {
  status?: EvaluationCaseStatus;
  dimension?: string;
  page?: number;
  pageSize?: number;
}

export const evaluationsApi = {
  /** 报告列表，reportId 降序（字典序即时间序）。没有报告时返回空页，不报错。 */
  list(
    agentId: string,
    status?: EvaluationReportStatus,
    page?: number,
    pageSize?: number,
  ): Promise<PageResult<EvaluationReportSummary>> {
    return client.get<PageResult<EvaluationReportSummary>>(
      `/evaluations/list${search({ agentId, status, page, pageSize })}`,
    );
  },

  /** 一份报告的完整概览。报告目录不存在是 404。 */
  detail(agentId: string, reportId: string): Promise<EvaluationReportDetail> {
    return client.get<EvaluationReportDetail>(`/evaluations/detail${search({ agentId, reportId })}`);
  },

  /** 报告内的用例摘要，index 升序；可按结果 / 维度过滤。 */
  casesList(
    agentId: string,
    reportId: string,
    query: EvaluationCaseListQuery = {},
  ): Promise<PageResult<EvaluationCaseSummary>> {
    return client.get<PageResult<EvaluationCaseSummary>>(
      `/evaluations/cases/list${search({
        agentId,
        reportId,
        status: query.status,
        dimension: query.dimension,
        page: query.page,
        pageSize: query.pageSize,
      })}`,
    );
  },

  /** 单条用例详情。 */
  caseDetail(agentId: string, reportId: string, caseId: string): Promise<EvaluationCaseDetail> {
    return client.get<EvaluationCaseDetail>(
      `/evaluations/cases/detail${search({ agentId, reportId, caseId })}`,
    );
  },
};
