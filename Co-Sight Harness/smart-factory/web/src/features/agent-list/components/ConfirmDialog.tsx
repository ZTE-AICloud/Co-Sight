import { useI18n } from '../../../i18n/useI18n';
import type { Agent } from '../../../shared/api/agents';
import { Dialog } from './Dialog';

interface ConfirmDialogProps {
  agent: Agent;
  /** 删除请求在途：禁用两个按钮并拦下 Esc */
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * 删除的二次确认。
 *
 * 用模态而不是卡片内联确认条：新增/编辑那边反正要一个模态，两个交互模型不划算，
 * 复用一个 Dialog 壳也让焦点陷阱/Esc 只有一处实现。
 *
 * 措辞是**破坏性**的，别照抄上一版那套「只从列表数据里移除、不动磁盘」——
 * 真后端是库与盘一起删（contract 5.01 的 `/agents/{id}/delete`），说轻了会让人点下去才发现。
 */
export function ConfirmDialog({ agent, busy, onCancel, onConfirm }: ConfirmDialogProps) {
  const { t } = useI18n();
  return (
    <Dialog onDismiss={busy ? undefined : onCancel} className="al-dialog--narrow">
      <div className="al-form">
        <h2 className="al-dialog-title">{t('agentList.confirm.title', { name: agent.name })}</h2>
        <p className="al-dialog-note">
          <b>{t('agentList.confirm.irreversible')}</b>
          {t('agentList.confirm.body', { dir: agent.dir, id: agent.id })}
        </p>
        <p className="al-dialog-note">{t('agentList.confirm.running')}</p>

        <div className="al-dialog-actions">
          <button type="button" className="al-btn" onClick={onCancel} disabled={busy}>
            {t('agentList.confirm.cancel')}
          </button>
          <button type="button" className="al-btn al-btn--danger" onClick={onConfirm} disabled={busy}>
            {busy ? t('agentList.confirm.deleting') : t('agentList.confirm.delete')}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
