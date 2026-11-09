import { useEffect, useMemo, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import { agentSkillsApi } from '../../../shared/api/agent-skills';
import type { AgentSkillsResponse } from '../../../shared/api/agent-skills';
import { agentsApi, isBackendDown, backendDownHint } from '../../../shared/api/agents';
import type { Agent } from '../../../shared/api/agents';
import { ApiError } from '../../../shared/api/client';
import type { Skill } from '../../../shared/api/skills';
import { AgentAvatar } from '../../../shared/components/AgentAvatar';
import { Icon } from '../../../shared/components/Icon';
import './assemble-dialog.css';

interface AssembleDialogProps {
  skill: Skill;
  /** 当前工作区；没有工作区时不发请求，直接给空态 */
  workspaceId: string | undefined;
  onClose: () => void;
  onDone: (agent: Agent, skill: Skill) => void;
}

/**
 * 「装配到智能体」弹层（2026-10-26 最小模型）。
 *
 * 只做一件事：把选中的技能**复制**进目标智能体当前产物的 `.claude/skills`。
 * 选定智能体后现拉一次它的产物技能清单，用于三件事：
 * 1. 预判同名冲突（服务端仍会再判一次，这里只是别让用户白点）；
 * 2. 显示产物是否就绪（未就绪不能装配）；
 * 3. 展示已有多少项产物技能。
 *
 * 复制完与技能库无关：不钉版、不同步、不记来源。
 */
export function AssembleDialog({ skill, workspaceId, onClose, onDone }: AssembleDialogProps) {
  const { t } = useI18n();

  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [agentsError, setAgentsError] = useState<string | null>(null);
  const [pickedId, setPickedId] = useState<string>('');
  /** 目标智能体的产物技能清单（选中后现拉） */
  const [target, setTarget] = useState<AgentSkillsResponse | null>(null);
  const [targetLoading, setTargetLoading] = useState(false);
  const [targetError, setTargetError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape' && !submitting) onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose, submitting]);

  useEffect(() => {
    let alive = true;
    if (workspaceId === undefined) {
      setAgents([]);
      return () => {
        alive = false;
      };
    }
    void agentsApi
      .list({ workspaceId, source: 'user', pageSize: 200 })
      .then((page) => {
        if (!alive) return;
        setAgents(page.items);
        setPickedId((current) =>
          current !== '' || page.items.length === 0 ? current : page.items[0]!.id,
        );
      })
      .catch((error: unknown) => {
        if (!alive) return;
        setAgents([]);
        setAgentsError(
          isBackendDown(error)
            ? backendDownHint()
            : error instanceof ApiError
              ? error.message
              : t('agentSkills.agentsFailed'),
        );
      });
    return () => {
      alive = false;
    };
  }, [workspaceId, t]);

  /** 选中智能体 → 现拉它产物里的技能，用于预判同名与就绪状态 */
  useEffect(() => {
    if (pickedId === '') {
      setTarget(null);
      return;
    }
    let alive = true;
    setTarget(null);
    setTargetLoading(true);
    setTargetError(null);
    void agentSkillsApi
      .list(pickedId)
      .then((result) => {
        if (alive) setTarget(result);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        setTarget(null);
        setTargetError(error instanceof ApiError ? error.message : t('agentSkills.agentsFailed'));
      })
      .finally(() => {
        if (alive) setTargetLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [pickedId, t]);

  const picked = useMemo(
    () => agents?.find((agent) => agent.id === pickedId) ?? null,
    [agents, pickedId],
  );

  const conflict = target?.items.some(
    (item) => item.name === skill.name || item.displayName === skill.name,
  ) ?? false;
  const notReady = target !== null && !target.ready;
  const canSubmit = picked !== null && target !== null && target.ready && !conflict && !submitting;

  async function submit(): Promise<void> {
    if (picked === null || !canSubmit) return;
    setSubmitting(true);
    setFailure(null);
    try {
      await agentSkillsApi.attach(picked.id, {
        path: skill.path,
        ...(skill.version === '' ? {} : { version: skill.version }),
      });
      onDone(picked, skill);
    } catch (error) {
      setFailure(
        t('agentSkills.failed', {
          message: error instanceof ApiError ? error.message : String(error),
        }),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="as-overlay" role="presentation" onClick={onClose}>
      <div
        className="as-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="as-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="as-head">
          <h2 id="as-title">{t('agentSkills.dialogTitle')}</h2>
          <p className="as-sub">
            <strong>{skill.name}</strong>
            {skill.version !== '' && <span className="as-version">{skill.version}</span>}
            <span>{t('agentSkills.dialogSubtitle')}</span>
          </p>
        </header>

        <div className="as-body">
          <p className="as-label">{t('agentSkills.pickAgent')}</p>

          {agents === null ? (
            <p className="as-hint">{t('agentSkills.agentsLoading')}</p>
          ) : agentsError !== null ? (
            <p className="as-hint as-hint--bad">{agentsError}</p>
          ) : agents.length === 0 ? (
            <p className="as-hint">{t('agentSkills.noAgents')}</p>
          ) : (
            <div className="as-agents" role="radiogroup">
              {agents.map((agent) => {
                const on = agent.id === pickedId;
                return (
                  <button
                    key={agent.id}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    className={`as-agent${on ? ' as-agent--on' : ''}`}
                    onClick={() => setPickedId(agent.id)}
                  >
                    <AgentAvatar icon={agent.icon} name={agent.name} seed={agent.id} size={26} />
                    <span className="as-agent-body">
                      <span className="as-agent-name">{agent.name}</span>
                      {agent.description !== '' && (
                        <span className="as-agent-meta">{agent.description}</span>
                      )}
                    </span>
                    <span className="as-radio" aria-hidden="true" />
                  </button>
                );
              })}
            </div>
          )}

          <div className="as-checks">
            <p className="as-check">
              <i className="as-dot as-dot--ok" />
              {t('agentSkills.sourceExists', { name: `${skill.name} ${skill.version}`.trim() })}
            </p>
            {targetLoading ? (
              <p className="as-check">
                <i className="as-dot as-dot--ok" />
                {t('agentSkills.loadingTarget')}
              </p>
            ) : targetError !== null ? (
              <p className="as-check as-check--bad">
                <i className="as-dot as-dot--bad" />
                {targetError}
              </p>
            ) : notReady ? (
              <p className="as-check as-check--bad">
                <i className="as-dot as-dot--bad" />
                {t('agentSkills.notReady', { reason: target?.reasons.join('；') ?? '' })}
              </p>
            ) : conflict ? (
              <p className="as-check as-check--bad">
                <i className="as-dot as-dot--bad" />
                {t('agentSkills.targetConflict')}
              </p>
            ) : (
              <>
                <p className="as-check">
                  <i className="as-dot as-dot--ok" />
                  {t('agentSkills.targetFree')}
                </p>
                <p className="as-check">
                  <i className="as-dot as-dot--ok" />
                  {t('agentSkills.instant')}
                </p>
              </>
            )}
          </div>

          {failure !== null && (
            <p className="as-failure" role="alert">
              <Icon name="alert" size={13} />
              {failure}
            </p>
          )}
        </div>

        <footer className="as-foot">
          <span className="as-note">{t('agentSkills.dialogSubtitle')}</span>
          <button type="button" className="al-btn al-btn--sm" onClick={onClose}>
            {t('agentSkills.cancel')}
          </button>
          <button
            type="button"
            className="al-btn al-btn--sm al-btn--primary"
            disabled={!canSubmit}
            onClick={() => void submit()}
          >
            {submitting ? t('agentSkills.submitting') : t('agentSkills.confirm')}
          </button>
        </footer>
      </div>
    </div>
  );
}
