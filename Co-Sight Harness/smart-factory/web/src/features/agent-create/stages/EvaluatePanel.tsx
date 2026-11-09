import { useEffect, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import type { MessageKey } from '../../../i18n/types';
import { evaluationsApi } from '../../../shared/api/evaluations';
import type {
  EvaluationCaseDetail,
  EvaluationCaseSummary,
  EvaluationReportDetail,
} from '../../../shared/api/evaluations';
import { Icon } from '../../../shared/components/Icon';
import type { IconName } from '../../../shared/components/Icon';
import '../eval-report.css';

/**
 * 评估阶段的右侧工作区正文：真实评估报告（数据来自 `/evaluations/*` 端点）。
 *
 * 信息层级（沿用原设计预览的取舍）：
 *   1. 结论先于明细 —— 分数、通过率、阈值是否达标一眼可见；
 *   2. 「结果质量」与「轨迹合规」是两套分，不合成一个数（口径在服务端，4.09 §5.3）；
 *   3. 未通过的用例能直接看到「哪条期望没命中 + 裁判为什么这么判」；
 *   4. 覆盖缺口（计数为 0 的维度）显眼。
 *
 * 用例期望项 / 裁判理由在用例详情里，卡片**展开时才拉** `cases/detail`（懒加载）。
 * 报告还没跑完（status = running / pending）只给结论区与流水线，不摆假明细。
 */

export interface EvaluatePanelProps {
  agentId: string;
  /** 最新一轮报告；还没有任何报告时为 null */
  report: EvaluationReportDetail | null;
  /** 这份报告的用例摘要 */
  cases: EvaluationCaseSummary[];
  loading: boolean;
  /** 取数失败的人话原因 */
  error: string | null;
  /** 左侧评估会话是否正在跑（空态与「进行中」文案要用） */
  running: boolean;
  /** 「让助手修复」：把未通过的用例交给左侧评估会话（真发送） */
  onCaseRetry: (task: string) => void;
}

type TabId = 'cases' | 'coverage' | 'audit' | 'env';
type FilterId = 'all' | 'passed' | 'missed' | 'failed';

const RESULT_DIMENSIONS: {
  key: 'correctness' | 'completeness' | 'formatCompliance' | 'actionability';
  label: MessageKey;
  short: MessageKey;
}[] = [
  { key: 'correctness', label: 'eval.dimension.correctness', short: 'eval.dimensionShort.correctness' },
  {
    key: 'completeness',
    label: 'eval.dimension.completeness',
    short: 'eval.dimensionShort.completeness',
  },
  {
    key: 'formatCompliance',
    label: 'eval.dimension.formatCompliance',
    short: 'eval.dimensionShort.formatCompliance',
  },
  {
    key: 'actionability',
    label: 'eval.dimension.actionability',
    short: 'eval.dimensionShort.actionability',
  },
];

/**
 * 覆盖维度的人话名：key 已知时用词表，未知（评估工具新增维度）时退回服务端给的 name。
 */
function coverageDimensionName(
  key: string,
  fallback: string,
  t: (key: MessageKey) => string,
): string {
  switch (key) {
    case 'functional':
    case 'boundary':
    case 'tool_use':
    case 'instruction':
    case 'safety':
    case 'failure':
      return t(`eval.coverageDimension.${key}`);
    default:
      return fallback;
  }
}

/** 结果维度里带独立阈值的两项（阈值三项：总分/正确性/完整性，§5.3）。 */
const DIMENSION_THRESHOLD: Partial<Record<string, number>> = { correctness: 3, completeness: 3 };

function pct(passRate: number | null): string {
  return passRate === null ? '—' : `${Math.round(passRate * 100)}%`;
}

function score(value: number | null): string {
  return value === null ? '—' : value.toFixed(2);
}

function Meter({
  value,
  max = 5,
  tone = 'primary',
  threshold,
}: {
  value: number;
  max?: number;
  tone?: 'primary' | 'danger';
  threshold?: number;
}) {
  const { t } = useI18n();
  const valuePct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className={`er-meter er-meter--${tone}`} role="img" aria-label={`${value} / ${max}`}>
      <span className="er-meter-fill" style={{ width: `${valuePct}%` }} />
      {threshold !== undefined && (
        <span
          className="er-meter-tick"
          style={{ left: `${(threshold / max) * 100}%` }}
          title={t('eval.thresholdTick', { threshold })}
        />
      )}
    </div>
  );
}

function StatusBadge({ status, label }: { status: 'pass' | 'warn' | 'fail'; label: string }) {
  const icon: IconName = status === 'fail' ? 'close' : status === 'warn' ? 'alert' : 'check';
  return (
    <span className={`er-status er-status--${status}`}>
      <Icon name={icon} size={12} />
      {label}
    </span>
  );
}

function TabButton({
  id,
  active,
  label,
  count,
  onClick,
}: {
  id: string;
  active: boolean;
  label: string;
  count?: string;
  onClick: (id: string) => void;
}) {
  return (
    <button
      type="button"
      className={`er-tab${active ? ' er-tab--active' : ''}`}
      aria-current={active ? 'page' : undefined}
      onClick={() => onClick(id)}
    >
      {label}
      {count !== undefined && <span className="er-tab-count">{count}</span>}
    </button>
  );
}

export function EvaluatePanel({
  agentId,
  report,
  cases,
  loading,
  error,
  running,
  onCaseRetry,
}: EvaluatePanelProps) {
  const { t } = useI18n();
  const [tab, setTab] = useState<TabId>('cases');
  const [filter, setFilter] = useState<FilterId>('all');
  /** 展开的用例；展开时才拉 cases/detail（期望项与裁判理由在那里） */
  const [openIds, setOpenIds] = useState<Record<string, boolean>>({});
  const [details, setDetails] = useState<Record<string, EvaluationCaseDetail | 'loading'>>({});

  // 换报告（重评 / 换智能体）后旧展开态与旧详情一起作废
  useEffect(() => {
    setOpenIds({});
    setDetails({});
  }, [report?.reportId]);

  function toggle(caseId: string) {
    setOpenIds((current) => ({ ...current, [caseId]: !current[caseId] }));
    if (details[caseId] === undefined && agentId !== '' && report !== null) {
      setDetails((current) => ({ ...current, [caseId]: 'loading' }));
      void evaluationsApi
        .caseDetail(agentId, report.reportId, caseId)
        .then((detail) => setDetails((current) => ({ ...current, [caseId]: detail })))
        .catch(() =>
          setDetails((current) => {
            const next = { ...current };
            delete next[caseId];
            return next;
          }),
        );
    }
  }

  if (loading) {
    return (
      <div className="er">
        <div className="er-empty" aria-busy="true">
          <Icon name="clock" size={20} />
          <p>{t('eval.loading')}</p>
        </div>
      </div>
    );
  }

  if (error !== null) {
    return (
      <div className="er">
        <div className="er-empty" role="alert">
          <Icon name="alert" size={20} />
          <p>{error}</p>
        </div>
      </div>
    );
  }

  if (report === null) {
    return (
      <div className="er">
        <div className="er-empty">
          <Icon name="chart" size={20} />
          <p>{running ? t('eval.emptyRunning') : t('eval.emptyIdle')}</p>
        </div>
      </div>
    );
  }

  const { counts, scores, thresholds } = report;
  const audit = report.audit;
  const passed = thresholds.met === true;
  const inProgress = report.status === 'running' || report.status === 'pending';

  // 还没评分的用例（生成 / 执行阶段）不算「未通过」，否则运行中途整页都是红的
  const filterCounts = {
    all: cases.length,
    passed: cases.filter((item) => item.status === 'passed').length,
    missed: cases.filter((item) => item.expected.miss > 0).length,
    failed: cases.filter((item) => item.scored && item.status !== 'passed').length,
  };
  const shown = cases.filter((item) => {
    if (filter === 'passed') return item.status === 'passed';
    if (filter === 'missed') return item.expected.miss > 0;
    if (filter === 'failed') return item.scored && item.status !== 'passed';
    return true;
  });

  // 轨迹审计的检查项按 checkId 去重：失败取第一条的严重度与证据，通过的只留 id
  const allChecks = report.auditDetails?.checks ?? [];
  const failedChecks = new Map<string, { severity: string; evidence: string | null; expected: unknown }>();
  const passedCheckIds: string[] = [];
  for (const check of allChecks) {
    if (check.checkId === '') continue;
    if (check.passed) {
      if (!passedCheckIds.includes(check.checkId)) passedCheckIds.push(check.checkId);
    } else if (!failedChecks.has(check.checkId)) {
      failedChecks.set(check.checkId, {
        severity: check.severity,
        evidence: check.evidence,
        expected: check.expected,
      });
    }
  }

  // 已跑出结果的用例数：生成 / 执行阶段还没有评分，counts.valid（评分成功数）恒为 0，
  // 拿它当分母会一直是 0/0。执行进度只看 run.status 有没有落下来。
  const executed = cases.filter((item) => item.run.status !== null).length;

  const pipeline = [
    {
      // 生成测试集看的是「生成了几条」，不是「评出了几条」：后者在评分开始前恒为 0
      label: t('eval.pipeline.generate'),
      state: report.pipeline.plan.state,
      stat: t('eval.count', { count: counts.total }),
    },
    {
      label: t('eval.pipeline.execute'),
      state: report.pipeline.run.state,
      stat: `${executed}/${counts.total}`,
    },
    {
      label: t('eval.pipeline.score'),
      state: report.pipeline.score.state,
      stat: t('eval.count', { count: counts.valid }),
    },
    {
      label: t('eval.pipeline.audit'),
      state: report.pipeline.audit.state,
      stat: t('eval.count', { count: audit?.evaluated ?? 0 }),
    },
  ];
  const coverage = report.coverage;
  const maxCoverage = Math.max(1, ...(coverage?.dimensions.map((item) => item.count) ?? [1]));

  return (
    <div className="er">
      {/* ── 结论 ─────────────────────────────────────────────────────── */}
      <section className="er-summary" aria-label={t('eval.summaryLabel')}>
        <div className="er-summary-head">
          <div className="er-verdict">
            <span className={`er-verdict-icon${passed ? '' : ' er-verdict-icon--bad'}`}>
              <Icon name={passed ? 'check' : 'alert'} size={18} />
            </span>
            <div>
              <h1>
                {inProgress
                  ? t('eval.verdict.inProgress')
                  : passed
                    ? t('eval.verdict.passed')
                    : t('eval.verdict.failed')}
              </h1>
              <p>
                {counts.pending > 0
                  ? t('eval.summaryLineInProgress', {
                      total: counts.total,
                      valid: counts.valid,
                      pending: counts.pending,
                      invalid: counts.invalid,
                    })
                  : t('eval.summaryLine', {
                      valid: counts.valid,
                      total: counts.total,
                      rate: pct(scores.passRate),
                      miss: counts.expectedMiss,
                      invalid: counts.invalid,
                    })}
              </p>
            </div>
          </div>
          <div className="er-hero">
            <em className="er-hero-kicker">{t('eval.resultQuality')}</em>
            <div className="er-hero-value">
              <b>{score(scores.weightedAverage)}</b>
              <span>/ 5</span>
            </div>
            <em>
              {t('eval.weightedAverage', { threshold: thresholds.weighted ?? '—' })}
            </em>
          </div>
        </div>

        <div className="er-meta-line">
          <span>
            <Icon name="file" size={12} />
            {report.reportId}
          </span>
          <span>
            <Icon name="clock" size={12} />
            {report.createdAt}
          </span>
          <span>
            <Icon name="wand" size={12} />
            {report.tools.evaluate.name ?? '—'}
            {report.tools.evaluate.version !== null ? ` · ${report.tools.evaluate.version}` : ''}
          </span>
          <span>
            <Icon name="layers" size={12} />
            {t('eval.judge', { model: report.judge.model ?? '—' })}
          </span>
        </div>

        <div className="er-pipeline" aria-label={t('eval.pipelineLabel')}>
          {pipeline.map((item, index) => (
            <div className="er-pipe" key={item.label}>
              {index > 0 && <span className="er-pipe-link" aria-hidden="true" />}
              <span className={`er-pipe-node er-pipe-node--${item.state}`}>
                <Icon
                  name={item.state === 'done' ? 'check' : item.state === 'failed' ? 'close' : 'activity'}
                  size={10}
                />
              </span>
              <span className="er-pipe-label">{item.label}</span>
              <span className="er-pipe-stat">{item.stat}</span>
            </div>
          ))}
        </div>

        <div className="er-dims">
          {RESULT_DIMENSIONS.map((dim) => {
            const value = scores.dimensions[dim.key];
            const threshold = DIMENSION_THRESHOLD[dim.key];
            return (
              <div className="er-dim" key={dim.key}>
                <div className="er-dim-top">
                  <span className="er-dim-name">{t(dim.label)}</span>
                  <span className="er-dim-weight">
                    {t('eval.weight', { percent: Math.round(scores.weights[dim.key] * 100) })}
                  </span>
                  <b>{value === null ? '—' : value.toFixed(2)}</b>
                </div>
                {value !== null && <Meter value={value} threshold={threshold} />}
                <div className="er-dim-foot">
                  {threshold === undefined
                    ? t('eval.noThreshold')
                    : thresholds.met === true
                      ? t('eval.thresholdMet', { threshold: threshold.toFixed(1) })
                      : t('eval.threshold', { threshold: threshold.toFixed(1) })}
                </div>
              </div>
            );
          })}
        </div>

        {audit !== null && audit.failedChecks > 0 && (
          <button type="button" className="er-attention" onClick={() => setTab('audit')}>
            <Icon name="alert" size={14} />
            <span>
              {t('eval.auditAttention', {
                score: audit.average === null ? '—' : audit.average.toFixed(2),
                grade: audit.grade ?? '—',
                failed: audit.failedChecks,
              })}
            </span>
            <span className="er-attention-more">
              {t('eval.auditMore')}
              <Icon name="chevronRight" size={12} />
            </span>
          </button>
        )}
        {report.warnings.length > 0 && (
          <p className="er-footnote" role="status">
            {report.warnings.join(t('common.clauseSeparator'))}
          </p>
        )}
      </section>

      {/* ── 分页 ─────────────────────────────────────────────────────── */}
      <nav className="er-tabs" aria-label={t('eval.tabsLabel')}>
        <TabButton
          id="cases"
          active={tab === 'cases'}
          label={t('eval.tab.cases')}
          count={String(filterCounts.all)}
          onClick={(id) => setTab(id as TabId)}
        />
        <TabButton
          id="coverage"
          active={tab === 'coverage'}
          label={t('eval.tab.coverage')}
          onClick={(id) => setTab(id as TabId)}
        />
        <TabButton
          id="audit"
          active={tab === 'audit'}
          label={t('eval.tab.audit')}
          onClick={(id) => setTab(id as TabId)}
        />
        <TabButton
          id="env"
          active={tab === 'env'}
          label={t('eval.tab.env')}
          onClick={(id) => setTab(id as TabId)}
        />
      </nav>

      {tab === 'cases' && (
        <section className="er-panel" aria-label={t('eval.tab.cases')}>
          <div className="er-filters">
            {(
              [
                ['all', t('eval.filter.all'), filterCounts.all],
                ['passed', t('eval.filter.passed'), filterCounts.passed],
                ['missed', t('eval.filter.missed'), filterCounts.missed],
                ['failed', t('eval.filter.failed'), filterCounts.failed],
              ] as [FilterId, string, number][]
            ).map(([id, label, count]) => (
              <button
                key={id}
                type="button"
                className={`er-filter${filter === id ? ' er-filter--active' : ''}`}
                aria-pressed={filter === id}
                onClick={() => setFilter(id)}
              >
                {label}
                <span>{count}</span>
              </button>
            ))}
            <span className="er-filters-hint">{t('eval.filterHint')}</span>
          </div>

          {shown.length === 0 ? (
            <div className="er-empty">
              <Icon name={running ? 'clock' : 'check'} size={20} />
              <p>{running ? t('eval.casesRunning') : t('eval.noCases')}</p>
            </div>
          ) : (
            <div className="er-cases">
              {shown.map((item) => (
                <CaseCard
                  key={item.caseId}
                  summary={item}
                  detail={details[item.caseId]}
                  open={!!openIds[item.caseId]}
                  onToggle={() => toggle(item.caseId)}
                  onRetry={() =>
                    onCaseRetry(
                      t('eval.caseRetryPrompt', { caseId: item.caseId, input: item.input }),
                    )
                  }
                />
              ))}
            </div>
          )}
        </section>
      )}

      {tab === 'coverage' && (
        <section className="er-panel" aria-label={t('eval.tab.coverage')}>
          {coverage === null ? (
            <div className="er-empty">
              <Icon name="list" size={20} />
              <p>{t('eval.noCoverage')}</p>
            </div>
          ) : (
            <>
              <div className="er-section-head">
                <div>
                  <h3>{t('eval.generationTitle')}</h3>
                  <p>{t('eval.generationDesc')}</p>
                </div>
                {coverage.tier !== null && <span className="er-tier">Tier {coverage.tier}</span>}
              </div>

              <div className="er-kpis">
                <div className="er-kpi">
                  <b>{coverage.actual ?? '—'}</b>
                  <span>{t('eval.actualCount', { target: coverage.target ?? '—' })}</span>
                </div>
                <div className="er-kpi">
                  <b>{coverage.fromGwt ?? '—'}</b>
                  <span>{t('eval.fromGwt')}</span>
                </div>
                <div className="er-kpi">
                  <b>{coverage.fromLlm ?? '—'}</b>
                  <span>{t('eval.fromLlm')}</span>
                </div>
                <div className="er-kpi">
                  <b>{coverage.repairRounds ?? '—'}</b>
                  <span>{t('eval.repairRounds')}</span>
                </div>
              </div>

              <div className="er-coverage">
                {coverage.dimensions.map((dim) => {
                  const uncovered = dim.count === 0;
                  return (
                    <div className={`er-cov${uncovered ? ' er-cov--empty' : ''}`} key={dim.key}>
                      <div className="er-cov-top">
                        <span className="er-cov-name">
                          {coverageDimensionName(dim.key, dim.name, t)}
                        </span>
                        <span className="er-cov-weight">
                          {t('eval.dimWeight', { weight: dim.weight })}
                        </span>
                        <b>{dim.count}</b>
                      </div>
                      <div className="er-meter er-meter--coverage">
                        <span
                          className="er-meter-fill"
                          style={{ width: `${(dim.count / maxCoverage) * 100}%` }}
                        />
                      </div>
                      <div className="er-cov-foot">
                        {uncovered
                          ? t('eval.uncovered')
                          : t('eval.dimCount', { count: dim.count })}
                      </div>
                    </div>
                  );
                })}
              </div>

              {coverage.rejected.length > 0 && (
                <div className="er-rejected">
                  <h4>
                    <Icon name="alert" size={13} />
                    {t('eval.rejected', { count: coverage.rejected.length })}
                  </h4>
                  {coverage.rejected.map((item) => (
                    <p key={item.sourceRef}>
                      <code>{item.sourceRef}</code>
                      {item.reason}
                    </p>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      )}

      {tab === 'audit' && (
        <section className="er-panel" aria-label={t('eval.tab.audit')}>
          {audit === null || report.auditDetails === null ? (
            <div className="er-empty">
              <Icon name="shield" size={20} />
              <p>{t('eval.noAudit')}</p>
            </div>
          ) : (
            <>
              <div className="er-section-head">
                <div>
                  <h3>{t('eval.auditTitle')}</h3>
                  <p>
                    {report.tools.audit.name ?? 'traceaudit'}
                    {report.tools.audit.rubricVersion !== null
                      ? ` · rubric ${report.tools.audit.rubricVersion}`
                      : ''}{' '}
                    {t('eval.auditDesc')}
                  </p>
                </div>
                <div className="er-audit-score">
                  <b>{audit.average === null ? '—' : audit.average.toFixed(2)}</b>
                  <span>/ 5 · {audit.grade ?? '—'}</span>
                </div>
              </div>

              <div className="er-audit-dims">
                {report.auditDetails.dimensions.map((dim) => {
                  const bad = dim.average !== null && dim.average < 3;
                  return (
                    <div className={`er-audit-dim${bad ? ' er-audit-dim--bad' : ''}`} key={dim.key}>
                      <div className="er-dim-top">
                        <span className="er-dim-name">
                          {bad && <Icon name="alert" size={12} />}
                          {dim.name}
                        </span>
                        <span className="er-dim-weight">
                          {t('eval.weight', { percent: Math.round(dim.weight * 100) })}
                        </span>
                        <b>{dim.average === null ? '—' : dim.average.toFixed(1)}</b>
                      </div>
                      {dim.average !== null && (
                        <Meter value={dim.average} tone={bad ? 'danger' : 'primary'} threshold={3} />
                      )}
                      <div className="er-dim-foot">
                        {t('eval.auditScored', { count: dim.scoredCount })}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="er-alert-box">
                <h4>
                  <Icon name="alert" size={14} />
                  {t('eval.failedChecks', { count: failedChecks.size })}
                </h4>
                <div className="er-checks">
                  {[...failedChecks.entries()].map(([id, info]) => (
                    <div className="er-check er-check--fail" key={id}>
                      <span className="er-check-icon">
                        <Icon name="close" size={11} />
                      </span>
                      <div>
                        <p className="er-check-id">
                          {id}
                          <span className="er-severity">{info.severity}</span>
                        </p>
                        <p className="er-check-evidence">
                          {t('eval.evidence', {
                            evidence: info.evidence ?? t('eval.noEvidence'),
                            expected: String(info.expected),
                          })}
                        </p>
                      </div>
                    </div>
                  ))}
                  {passedCheckIds.map((id) => (
                    <div className="er-check" key={id}>
                      <span className="er-check-icon er-check-icon--pass">
                        <Icon name="check" size={11} />
                      </span>
                      <div>
                        <p className="er-check-id">{id}</p>
                        <p className="er-check-evidence">{t('eval.passed')}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <p className="er-footnote">
                {t('eval.auditNote')}
              </p>
            </>
          )}
        </section>
      )}

      {tab === 'env' && (
        <section className="er-panel" aria-label={t('eval.tab.env')}>
          <div className="er-section-head">
            <div>
              <h3>{t('eval.envTitle')}</h3>
              <p>{t('eval.envDesc')}</p>
            </div>
          </div>

          <dl className="er-env">
            {(
              [
                [
                  t('eval.env.tool'),
                  `${report.tools.evaluate.name ?? '—'}${report.tools.evaluate.version !== null ? `/${report.tools.evaluate.version}` : ''}`,
                ],
                [t('eval.env.judgeModel'), report.judge.model ?? '—'],
                [t('eval.env.testedModel'), report.judge.mainAgentModel ?? '—'],
                [
                  t('eval.env.concurrency'),
                  report.environment.concurrency === null
                    ? '—'
                    : String(report.environment.concurrency),
                ],
                [
                  t('eval.env.weightedThreshold'),
                  thresholds.weighted === null ? '—' : `≥ ${thresholds.weighted}`,
                ],
                [
                  t('eval.env.correctnessThreshold'),
                  `≥ ${thresholds.correctness ?? '—'} / ≥ ${thresholds.completeness ?? '—'}`,
                ],
                [t('eval.env.rubric'), report.environment.rubric.file ?? '—'],
                [t('eval.env.inputSeed'), report.environment.inputSeed ?? '—'],
                [
                  t('eval.env.artifactCheck'),
                  report.environment.agentShaMatches === null
                    ? '—'
                    : report.environment.agentShaMatches
                      ? t('eval.env.shaMatch')
                      : t('eval.env.shaMismatch'),
                ],
                [t('eval.env.isolation'), report.environment.isolation ?? '—'],
                [t('eval.env.generatedAt'), report.environment.generatedAt ?? '—'],
                [t('eval.env.auditedAt'), report.environment.auditedAt ?? '—'],
              ] as [string, string][]
            ).map(([key, value]) => (
              <div className="er-env-row" key={key}>
                <dt>{key}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>

          <div className="er-formula">
            <h4>{t('eval.scoringTitle')}</h4>
            <p>
              {t('eval.scoringFormula', {
                parts: RESULT_DIMENSIONS.map(
                  (dim) => `${t(dim.short)} ${Math.round(scores.weights[dim.key] * 100)}%`,
                ).join(' + '),
              })}
            </p>
            <p>{t('eval.scoringNote')}</p>
          </div>
        </section>
      )}
    </div>
  );
}

/** 一张用例卡：折叠态只给结论，展开才拉 cases/detail 看期望项与裁判理由。 */
function CaseCard({
  summary,
  detail,
  open,
  onToggle,
  onRetry,
}: {
  summary: EvaluationCaseSummary;
  detail: EvaluationCaseDetail | 'loading' | undefined;
  open: boolean;
  onToggle: () => void;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  // 还没评分的用例是「等待」，不是失败：执行完但未评分 → 待评分；连执行记录都没有 → 待执行
  const pending = !summary.scored;
  const invalid = summary.status === 'invalid';
  const missed = summary.expected.miss;
  const cardStatus: 'pass' | 'warn' | 'fail' =
    pending ? 'warn' : invalid || summary.status === 'failed' ? 'fail' : missed > 0 ? 'warn' : 'pass';
  const elapsed = summary.run.elapsedMs === null ? '—' : `${(summary.run.elapsedMs / 1000).toFixed(1)}s`;

  return (
    <article
      className={`er-case${open ? ' er-case--open' : ''}${cardStatus === 'fail' ? ' er-case--fail' : ''}`}
    >
      <header className="er-case-head">
        <StatusBadge
          status={cardStatus}
          label={
            pending
              ? summary.run.status === null
                ? t('eval.case.pendingRun')
                : t('eval.case.pendingScore')
              : invalid
                ? t('eval.case.scoreFailed')
                : summary.status === 'failed'
                  ? t('eval.case.failed')
                  : cardStatus === 'warn'
                    ? t('eval.case.passedMissed')
                    : t('eval.case.passed')
          }
        />
        <div className="er-case-title">
          <code>{summary.caseId}</code>
          <span className="er-chip er-chip--ghost">
            {coverageDimensionName(summary.dimension, summary.dimensionLabel, t)}
          </span>
          {summary.capabilityRef !== null && <span className="er-chip er-chip--ghost">{summary.capabilityRef}</span>}
        </div>
        <div className="er-case-score">
          <b>{summary.weightedScore === null ? '—' : summary.weightedScore.toFixed(2)}</b>
          <span>{t('eval.case.weighted')}</span>
        </div>
        <button
          type="button"
          className="er-case-toggle"
          aria-expanded={open}
          aria-label={open ? t('eval.case.collapse') : t('eval.case.expand')}
          onClick={onToggle}
        >
          <Icon name={open ? 'chevronDown' : 'chevronRight'} size={14} />
        </button>
      </header>

      <div className="er-case-input">
        <span>{t('eval.case.input')}</span>
        <code>{summary.input}</code>
      </div>

      <div className="er-case-sub">
        <span className="er-case-sub-item">
          <Icon name="check" size={12} />
          {t('eval.case.expectedHits', {
            hit: summary.expected.hit,
            total: summary.expected.total,
          })}
        </span>
        <span className="er-case-sub-item">
          <Icon name="clock" size={12} />
          {elapsed}
        </span>
        {summary.run.turns !== null && (
          <span className="er-case-sub-item">
            <Icon name="activity" size={12} />
            {t('eval.case.turns', { count: summary.run.turns })}
          </span>
        )}
        {missed > 0 && (
          <span className="er-case-sub-item er-case-sub-item--warn">
            <Icon name="alert" size={12} />
            {t('eval.case.missed', { count: missed })}
          </span>
        )}
        <span className="er-case-chevron-hint">
          {open ? t('eval.case.hideExpected') : t('eval.case.showExpected')}
        </span>
      </div>

      {open && (
        <div className="er-case-body">
          {detail === undefined || detail === 'loading' ? (
            <p className="er-reason" aria-busy="true">
              {detail === 'loading' ? t('eval.case.loadingDetail') : t('eval.case.detailFailed')}
            </p>
          ) : (
            <>
              <div className="er-block">
                <h4 className="er-block-title">{t('eval.case.expects')}</h4>
                <ul className="er-expects">
                  {detail.expectedItems.map((expect, index) => (
                    <li key={`${expect.text}-${index}`} className={`er-expect er-expect--${expect.verdict}`}>
                      <span className="er-expect-mark">
                        <Icon name={expect.verdict === 'hit' ? 'check' : 'close'} size={11} />
                      </span>
                      <div className="er-expect-body">
                        <p className="er-expect-text">
                          {index + 1}. {expect.text}
                          <span className="er-expect-verdict">
                            {expect.verdict === 'hit'
                              ? t('eval.case.hit')
                              : expect.verdict === 'miss'
                                ? t('eval.case.miss')
                                : t('eval.case.undecided')}
                          </span>
                        </p>
                        {expect.note !== null && <p className="er-expect-note">{expect.note}</p>}
                      </div>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="er-block">
                <h4 className="er-block-title">{t('eval.case.fourScores')}</h4>
                <div className="er-score-row">
                  {RESULT_DIMENSIONS.map((dim) => {
                    const value = detail.scores[dim.key];
                    return (
                      <span className="er-score" key={dim.key}>
                        <span>{t(dim.label)}</span>
                        <b className={value !== null && value < 3 ? 'er-score--low' : ''}>
                          {value === null ? '—' : value}
                        </b>
                      </span>
                    );
                  })}
                  <span className="er-score-formula">{t('eval.case.formula')}</span>
                </div>
              </div>

              {detail.reasoning !== null && (
                <div className="er-block">
                  <h4 className="er-block-title">{t('eval.case.reasoning')}</h4>
                  <p className="er-reason">{detail.reasoning}</p>
                </div>
              )}

              <div className="er-run">
                <span>
                  {t('eval.case.running', { status: detail.run.status ?? '—' })}
                </span>
                {detail.run.exitCode !== null && <span>exit {detail.run.exitCode}</span>}
                {detail.run.elapsedMs !== null && <span>{(detail.run.elapsedMs / 1000).toFixed(1)}s</span>}
                {detail.run.turns !== null && (
                  <span>{t('eval.case.turns', { count: detail.run.turns })}</span>
                )}
                {detail.usage !== null && detail.usage.costUsd !== null && (
                  <span>${detail.usage.costUsd.toFixed(2)}</span>
                )}
                <span>{t('eval.case.attempts', { count: detail.run.attempts })}</span>
              </div>

              {missed > 0 && (
                <div className="er-case-actions">
                  <button type="button" className="er-btn er-btn--primary" onClick={onRetry}>
                    <Icon name="wand" size={12} />
                    {t('eval.case.fix')}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </article>
  );
}
