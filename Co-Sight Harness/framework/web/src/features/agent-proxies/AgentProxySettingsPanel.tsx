/**
 * Agent 代理配置面板（设置 → Agent 代理配置）。
 *
 * 本期只展示**一个**代理：smart-factory 正在跑的 Claude Code。
 * 数据直接取模块的 `GET /engine/detail`（见 `engineDetail.ts`），
 * 不读框架的 `/api/agent-proxies` 多代理配置 —— 多 Agent 代理暂未开放，
 * 那套列表 / 编辑 / 删除界面也一并收起。
 *
 * 原来按多代理做的 `AgentProxyConfigForm` / `agentProxyForm` / `ExtraReadonly`
 * 与 `api/agentProxies.ts` 仍保留：`useAgentProxyList` 还被工作区表单使用，
 * 其余等恢复多代理时再接回来。
 */

import type { MessageKey } from '../../i18n/types';
import { useI18n } from '../../i18n/useI18n';
import { Button } from '../../components/ui/Button';
import { ConfigList } from '../../components/ui/ConfigList';
import { StatusPanel } from '../../components/ui/StatusPanel';
import { ConfigRowSkeleton } from '../config/ConfigRowSkeleton';
import { useEngineDetail, type EngineDetail } from './engineDetail';
import styles from '../config/config.module.css';

/** 引擎标识 → 展示名。未知引擎原样显示标识，不编一个名字出来。 */
const ENGINE_LABELS: Record<string, MessageKey> = {
  'claude-cli': 'settings.agentProxy.engine.claudeAgentSdk',
  fake: 'settings.agentProxy.engine.fake',
};

/**
 * 响应是**未校验的裸 JSON**：engine 可能缺失、不是字符串，甚至正好撞上
 * `Object.prototype` 的键名（`constructor` / `toString`）—— 普通对象查表会拿到
 * 一个函数，交给 `t()` 会在 `split('.')` 上直接抛出去、把整个设置弹窗打崩。
 * 所以只认自有键，其余一律原样显示（或 `—`）。
 */
function engineLabelOf(engine: unknown): MessageKey | undefined {
  if (typeof engine !== 'string') return undefined;
  return Object.hasOwn(ENGINE_LABELS, engine) ? ENGINE_LABELS[engine] : undefined;
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** 一组「术语 → 值」：复用模块私有配置那段只读样式。 */
function EngineDetailList({ detail }: { detail: EngineDetail }) {
  const { t } = useI18n();
  const engine = typeof detail.engine === 'string' ? detail.engine : '';
  const engineLabel = engineLabelOf(detail.engine);
  // 老版本不报版本号（空串），缺字段时同样按"没报"处理，不渲染一个空格子
  const version = typeof detail.version === 'string' ? detail.version.trim() : '';

  return (
    <dl className={styles.extraList}>
      <dt className={styles.extraTerm}>{t('settings.agentProxy.field.engine')}</dt>
      <dd className={styles.extraValue}>
        {engineLabel !== undefined ? t(engineLabel) : engine === '' ? '—' : engine}
      </dd>

      <dt className={styles.extraTerm}>{t('settings.agentProxy.field.version')}</dt>
      <dd className={styles.extraValue}>{version === '' ? '—' : version}</dd>
    </dl>
  );
}

export function AgentProxySettingsPanel({ active = true }: { active?: boolean }) {
  const { t } = useI18n();
  const detail = useEngineDetail(active);

  return (
    <div className={styles.panel}>
      <div className={styles.sectionHead}>
        <h3 className={styles.sectionTitle}>{t('settings.agentProxy.currentSection')}</h3>
      </div>

      {detail.isPending ? (
        <ConfigList ariaLabel={t('settings.agentProxy.loading')}>
          <ConfigRowSkeleton />
        </ConfigList>
      ) : null}

      {detail.isError ? (
        <StatusPanel
          icon="alert"
          role="alert"
          title={t('settings.agentProxy.error.title')}
          hint={describeError(detail.error)}
          action={
            <Button
              icon="retry"
              onClick={() => {
                void detail.refetch();
              }}
            >
              {t('error.retry')}
            </Button>
          }
        />
      ) : null}

      {detail.data === undefined ? null : detail.data.available === false ? (
        <StatusPanel
          icon="alert"
          title={t('settings.agentProxy.engineUnavailable.title')}
          hint={`${t('settings.agentProxy.engineUnavailable.hint')} ${detail.data.installHint ?? ''}`}
        />
      ) : (
        <EngineDetailList detail={detail.data} />
      )}
    </div>
  );
}
