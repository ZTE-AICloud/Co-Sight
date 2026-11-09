import { useEffect, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import type { Agent } from '../../../shared/api/agents';
import { workspacesApi } from '../../../shared/api/workspaces';
import { AgentAvatar } from '../../../shared/components/AgentAvatar';
import { Icon } from '../../../shared/components/Icon';
import { formatTime, timeAgo } from '../../../shared/time';
import { sourceLabel } from '../display';
import { Dialog } from './Dialog';

interface AgentDetailDialogProps {
  agent: Agent;
  onClose: () => void;
}

/**
 * 智能体详情（2026-10-20 起是**只读信息层**）。点卡片打开。
 *
 * 2026-10-18 那版底部还挂着删除 / 编辑 / 设计 / 评估 / 使用；2026-10-20 卡片按新参考稿
 * 把这组动作搬回了卡面，于是这里**不再有动作条** —— 同一组动作仍然只有一处入口。
 * 现在它回答的是卡面放不下的问题：
 *
 * - **760px 双栏**：左栏读简介与全部标签，右栏是查询用的基本信息。
 * - **工作区 / ID / 目录**：目录与 ID 各带一颗复制键 —— 排查问题时不用手选 38 个字符。
 *   工作区名是经 `workspacesApi` 现查的（接口只给 uuid），查不到就只显示 uuid。
 * - **状态徽标撤了**：按 2026-10-18 的评审意见，详情不显示状态。
 *
 * 关闭是右上角那颗 ×，外加**点弹窗外的空白**（`dismissOnBackdrop`；详情没有可丢的输入，
 * 读信息时随手点外面收掉最省事）。顶部不再铺封面 banner（2026-10-19 撤掉）：弹窗直接从头像 + 名称开始。
 */
export function AgentDetailDialog({ agent, onClose }: AgentDetailDialogProps) {
  const { t, locale } = useI18n();
  /**
   * 工作区名。`Agent` 里只有 `workspaceId`（uuid），名字在框架那边，
   * 经本服务的只读代理取。取不到就保持 `null`，界面退成只显示 uuid。
   */
  const [workspaceName, setWorkspaceName] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setWorkspaceName(null);
    // 内置智能体不属于任何工作区：没必要为它拉一次工作区清单
    if (agent.workspaceId === null) return undefined;

    workspacesApi
      .list()
      .then((result) => {
        if (cancelled) return;
        setWorkspaceName(result.items.find((item) => item.id === agent.workspaceId)?.name ?? null);
      })
      .catch(() => {
        // 名字只是锦上添花：框架没起、令牌不对时 uuid 已经够定位了，不打扰用户
      });

    return () => {
      cancelled = true;
    };
  }, [agent.workspaceId]);

  /** 标签就是用户写的分类；来源是 `agent.source` 字段，摆到右栏的基本信息里。 */
  const tags = agent.tags;

  return (
    <Dialog onDismiss={onClose} dismissOnBackdrop className="al-dialog--detail">
      <div className="al-detail">
        <div className="al-detail-hero">
          <button
            type="button"
            className="al-detail-close"
            onClick={onClose}
            aria-label={t('agentList.detail.close')}
          >
            <Icon name="close" size={14} />
          </button>

          <div className="al-detail-identity">
            <div className="al-detail-avatar">
              <AgentAvatar icon={agent.icon} name={agent.name} seed={agent.id} size={80} />
            </div>

            <div className="al-detail-idtext">
              <h2 className="al-detail-name" title={agent.name}>
                {agent.name}
              </h2>
              <p className="al-detail-byline">
                {workspaceName !== null && (
                  <>
                    <span>{workspaceName}</span>
                    <span className="al-detail-sep" />
                  </>
                )}
                <span>
                  {t('agentList.detail.updated', { time: timeAgo(agent.updatedAt, locale) })}
                </span>
              </p>
            </div>
          </div>
        </div>

        <div className="al-detail-body">
          <div className="al-detail-grid">
            <div>
              <section className="al-detail-section">
                <h3 className="al-detail-section-title">{t('agentList.detail.description')}</h3>
                <p
                  className={`al-detail-desc${agent.description === '' ? ' al-detail-desc--empty' : ''}`}
                >
                  {agent.description === '' ? t('agentList.detail.noDescription') : agent.description}
                </p>
              </section>

              <section className="al-detail-section">
                <h3 className="al-detail-section-title">{t('agentList.detail.tags')}</h3>
                {tags.length === 0 ? (
                  <p className="al-detail-empty">{t('agentList.detail.noTags')}</p>
                ) : (
                  <div className="al-detail-tags">
                    {tags.map((tag) => (
                      <span key={tag} className="al-tag" title={tag}>
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </section>
            </div>

            <section className="al-detail-section">
              <h3 className="al-detail-section-title">{t('agentList.detail.basic')}</h3>
              <dl className="al-facts">
                <div className="al-facts-row">
                  <dt>{t('agentList.detail.source')}</dt>
                  <dd>{sourceLabel(agent.source, t)}</dd>
                </div>
                <div className="al-facts-row">
                  <dt>{t('agentList.detail.workspace')}</dt>
                  <dd className="al-facts-stack">
                    {workspaceName !== null && <span>{workspaceName}</span>}
                    <span className="al-facts-uuid">
                      {agent.workspaceId ?? t('agentList.detail.noWorkspace')}
                    </span>
                  </dd>
                </div>
                <div className="al-facts-row">
                  <dt>ID</dt>
                  <dd className="al-facts-copyline">
                    <code>{agent.id}</code>
                    <CopyButton value={agent.id} label={t('agentList.detail.copyId')} />
                  </dd>
                </div>
                <div className="al-facts-row">
                  <dt>{t('agentList.detail.dir')}</dt>
                  <dd className="al-facts-copyline">
                    <code>{agent.dir}</code>
                    <CopyButton value={agent.dir} label={t('agentList.detail.copyDir')} />
                  </dd>
                </div>
                <div className="al-facts-row">
                  <dt>{t('agentList.detail.created')}</dt>
                  <dd>{formatTime(agent.createdAt, locale)}</dd>
                </div>
                <div className="al-facts-row">
                  <dt>{t('agentList.detail.updatedAt')}</dt>
                  <dd>{formatTime(agent.updatedAt, locale)}</dd>
                </div>
              </dl>
            </section>
          </div>
        </div>
      </div>
    </Dialog>
  );
}

/**
 * 复制一颗值（ID / 目录）。
 *
 * 优先 `navigator.clipboard`（需要安全上下文）；被拒时退回隐藏 textarea ——
 * 本模块开发态是 `http://localhost`，算安全上下文，但被嵌进框架、或将来部署成
 * 内网 IP 时就可能落到 `http://` 的非安全上下文，别让复制键在那儿变成哑巴。
 *
 * 成功后的对勾只亮 1.4s：它表示「这一下复制成功了」，不是把按钮永久改成 check 图标。
 */
function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!(await copyText(value))) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <button
      type="button"
      className={`al-copy${copied ? ' al-copy--done' : ''}`}
      onClick={() => void copy()}
      aria-label={label}
      title={label}
    >
      <Icon name={copied ? 'check' : 'copy'} size={12} />
    </button>
  );
}

async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    // 非安全上下文 / 没授权：落到下面的老办法
  }

  const area = document.createElement('textarea');
  area.value = value;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.top = '-9999px';
  document.body.appendChild(area);
  area.select();

  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    area.remove();
  }
}
