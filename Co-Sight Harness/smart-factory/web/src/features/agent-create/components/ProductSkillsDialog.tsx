import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../i18n/useI18n';
import { agentSkillsApi } from '../../../shared/api/agent-skills';
import type { AgentSkill, AgentSkillsResponse } from '../../../shared/api/agent-skills';
import { ApiError } from '../../../shared/api/client';
import { Icon } from '../../../shared/components/Icon';
import { composeOptimizeMessage } from '../../skill-workshop/compose-prompt';
import './product-skills.css';

interface ProductSkillsDialogProps {
  agentId: string;
  onClose: () => void;
  /** 把优化命令放回发送框（不自动发） */
  onOptimize: (text: string) => void;
}

/** 产物里的技能目录直接拼 SKILL.md：产物技能没有 vN 层（那是技能库的布局）。 */
function productSkillMdPath(path: string): string {
  return `${path.replace(/\/+$/u, '')}/SKILL.md`;
}

/**
 * 设计页「产物技能」弹层。
 *
 * 列表就是产物 `.claude/skills` 的内容（构建生成的与装配进来的同构，不记来源）。
 * 动作只有两个：优化（把命令放回发送框，原地改这一份）与删除（移除目录）。
 * 装配入口在技能库 tab —— 这里只给一条跳转，避免同一页塞两套选择器。
 */
export function ProductSkillsDialog({ agentId, onClose, onOptimize }: ProductSkillsDialogProps) {
  const { t } = useI18n();
  const navigate = useNavigate();

  const [data, setData] = useState<AgentSkillsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmName, setConfirmName] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void agentSkillsApi
      .list(agentId)
      .then((result) => {
        if (alive) setData(result);
      })
      .catch((cause: unknown) => {
        if (!alive) return;
        setError(
          cause instanceof ApiError
            ? t('agentSkills.listFailed', { message: cause.message })
            : t('agentSkills.listFailed', { message: String(cause) }),
        );
      });
    return () => {
      alive = false;
    };
  }, [agentId, t]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  async function remove(name: string): Promise<void> {
    setRemoving(name);
    setError(null);
    try {
      await agentSkillsApi.remove(agentId, name);
      setData((current) =>
        current === null
          ? current
          : { ...current, items: current.items.filter((item) => item.name !== name) },
      );
      setConfirmName(null);
    } catch (cause) {
      setError(
        t('agentSkills.removeFailed', {
          message: cause instanceof ApiError ? cause.message : String(cause),
        }),
      );
    } finally {
      setRemoving(null);
    }
  }

  function optimize(skill: AgentSkill): void {
    onOptimize(composeOptimizeMessage(productSkillMdPath(skill.path), ''));
    onClose();
  }

  const items = data?.items ?? [];

  return (
    <div className="ps-overlay" role="presentation" onClick={onClose}>
      <div
        className="ps-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ps-title"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="ps-head">
          <div className="ps-head-main">
            <h2 id="ps-title">{t('agentSkills.panelTitle')}</h2>
            {data !== null && (
              <span className="ps-count">{t('agentSkills.panelCount', { count: items.length })}</span>
            )}
          </div>
          <p className="ps-sub">{t('agentSkills.panelSub')}</p>
          {data?.product != null && (
            <p className="ps-product">
              <code>
                {data.product.agentName} / {data.product.version}
              </code>
            </p>
          )}
          <button type="button" className="ps-close" aria-label={t('agentSkills.close')} onClick={onClose}>
            <Icon name="close" size={14} />
          </button>
        </header>

        <div className="ps-body">
          {error !== null && (
            <p className="ps-error" role="alert">
              <Icon name="alert" size={13} />
              {error}
            </p>
          )}

          {data === null ? (
            error === null && <p className="ps-hint">{t('agentSkills.loading')}</p>
          ) : !data.ready ? (
            <div className="ps-empty">
              <Icon name="alert" size={18} />
              <p>{t('agentSkills.notReady', { reason: data.reasons.join('；') })}</p>
            </div>
          ) : items.length === 0 ? (
            <div className="ps-empty">
              <Icon name="layers" size={18} />
              <p>{t('agentSkills.empty')}</p>
              <p className="ps-empty-hint">{t('agentSkills.emptyHint')}</p>
            </div>
          ) : (
            <ul className="ps-list">
              {items.map((skill) => (
                <li key={skill.name} className="ps-row">
                  <div className="ps-row-main">
                    <span className="ps-row-name">{skill.displayName}</span>
                    {skill.version !== '' && <span className="ps-version">{skill.version}</span>}
                    <span className="ps-actions">
                      <button type="button" className="al-card-action" onClick={() => optimize(skill)}>
                        {t('agentSkills.optimize')}
                      </button>
                      <span className="al-card-sep" aria-hidden="true">
                        ·
                      </span>
                      <button
                        type="button"
                        className="al-card-action al-card-action--danger"
                        onClick={() => setConfirmName(skill.name)}
                      >
                        {t('agentSkills.remove')}
                      </button>
                    </span>
                  </div>
                  {skill.description !== '' && <p className="ps-row-desc">{skill.description}</p>}

                  {confirmName === skill.name && (
                    <div className="ps-confirm" role="alertdialog">
                      <span>{t('agentSkills.removeConfirm', { name: skill.displayName })}</span>
                      <button
                        type="button"
                        className="al-btn al-btn--sm"
                        disabled={removing === skill.name}
                        onClick={() => setConfirmName(null)}
                      >
                        {t('agentSkills.removeCancel')}
                      </button>
                      <button
                        type="button"
                        className="al-btn al-btn--sm al-btn--primary"
                        disabled={removing === skill.name}
                        onClick={() => void remove(skill.name)}
                      >
                        {t('agentSkills.remove')}
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <footer className="ps-foot">
          <button
            type="button"
            className="al-btn al-btn--sm"
            onClick={() => {
              onClose();
              navigate('/agents?tab=skills');
            }}
          >
            <Icon name="layers" size={12} />
            {t('agentSkills.fromLibrary')}
          </button>
        </footer>
      </div>
    </div>
  );
}
