/**
 * 观测设置面板（设置 → 观测设置）。
 *
 * 配置 cosight-viewer 模块的会话自动清理行为。
 * 服务不可用时显示友好提示，禁用配置表单。
 */

import { useState, useEffect } from 'react';
import { useI18n } from '../../i18n/useI18n';
import { Button } from '../../components/ui/Button';
import dialogStyles from '../../components/shell/SettingsDialog.module.css';
import styles from './observability.module.css';

/** cosight-viewer 默认地址 */
const COSIGHT_VIEWER_URL = 'http://localhost:4830';

interface AutoCleanupConfig {
  enabled: boolean;
  abandon_hours: number;
  purge_days: number;
  last_run: {
    time: string;
    type: 'manual' | 'auto';
    purged_sessions: number;
    purged_events: number;
    purged_agents: number;
    purged_runs: number;
  } | null;
}

type ServiceStatus = 'checking' | 'available' | 'unavailable';

/**
 * 探活：模块服务在不在。
 *
 * 放在组件外是因为它不读组件里的任何东西——每次渲染都重新造一个函数没有意义，
 * 在 `useEffect` 的依赖里也会变成一个永远不变却又"看着像会变"的值。
 */
async function checkService(): Promise<boolean> {
  try {
    const response = await fetch(`${COSIGHT_VIEWER_URL}/health`, {
      method: 'GET',
      mode: 'cors',
    });
    return response.ok;
  } catch {
    return false;
  }
}

export function ObservationSettingsPanel() {
  const { t } = useI18n();
  const [status, setStatus] = useState<ServiceStatus>('checking');
  const [config, setConfig] = useState<AutoCleanupConfig>({
    // 默认启用：与 cosight-viewer 服务端「无配置时按 90 天保留策略执行」保持一致。
    enabled: true,
    abandon_hours: 24,
    purge_days: 90,
    last_run: null,
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // 检测服务是否可用
  useEffect(() => {
    let cancelled = false;
    checkService().then((available) => {
      if (!cancelled) {
        setStatus(available ? 'available' : 'unavailable');
        if (available) {
          loadConfig();
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function loadConfig() {
    try {
      const response = await fetch(`${COSIGHT_VIEWER_URL}/settings/auto-cleanup`, {
        method: 'GET',
        mode: 'cors',
      });
      if (!response.ok) throw new Error('Failed to load config');
      const data = await response.json();
      setConfig({
        enabled: data.enabled ?? true,
        abandon_hours: data.abandon_hours ?? 24,
        purge_days: data.purge_days ?? 90,
        last_run: data.last_run ?? null,
      });
    } catch {
      setMessage({
        type: 'error',
        text: t('settings.observation.loadFailed'),
      });
    }
  }

  async function handleSave() {
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch(`${COSIGHT_VIEWER_URL}/settings/auto-cleanup`, {
        method: 'POST',
        mode: 'cors',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: config.enabled,
          abandon_hours: config.abandon_hours,
          purge_days: config.purge_days,
        }),
      });
      if (!response.ok) throw new Error('Failed to save config');
      const data = await response.json();
      setConfig((prev) => ({
        ...prev,
        enabled: data.enabled,
        abandon_hours: data.abandon_hours,
        purge_days: data.purge_days,
        last_run: data.last_run ?? prev.last_run,
      }));
      setMessage({ type: 'success', text: t('settings.observation.saveSuccess') });
    } catch {
      setMessage({
        type: 'error',
        text: t('settings.observation.saveFailed'),
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleRetry() {
    setStatus('checking');
    const available = await checkService();
    setStatus(available ? 'available' : 'unavailable');
    if (available) {
      await loadConfig();
    }
  }

  // 服务检测中
  if (status === 'checking') {
    return (
      <div className={dialogStyles.panel}>
        <h3 className={dialogStyles.sectionTitle}>{t('settings.observation.title')}</h3>
        <p className={dialogStyles.fieldHint}>{t('settings.observation.checking')}</p>
      </div>
    );
  }

  // 服务不可用
  if (status === 'unavailable') {
    return (
      <div className={dialogStyles.panel}>
        <h3 className={dialogStyles.sectionTitle}>{t('settings.observation.title')}</h3>
        <div className={styles.errorBox}>
          <p className={styles.errorTitle}>🔌 {t('settings.observation.serviceUnavailable')}</p>
          <p className={styles.errorMessage}>{t('settings.observation.serviceUnavailableHint')}</p>
          <Button onClick={handleRetry} variant="secondary" size="sm">
            {t('settings.observation.retry')}
          </Button>
        </div>
      </div>
    );
  }

  // 服务可用，显示配置表单
  return (
    <div className={dialogStyles.panel}>
      <h3 className={dialogStyles.sectionTitle}>{t('settings.observation.title')}</h3>
      <p className={dialogStyles.fieldHint}>{t('settings.observation.description')}</p>

      <div className={dialogStyles.field}>
        <div>
          <div className={dialogStyles.fieldLabel}>{t('settings.observation.abandonHours')}</div>
          <p className={dialogStyles.fieldHint}>{t('settings.observation.abandonHoursHint')}</p>
        </div>
        <input
          type="number"
          min="1"
          max="8760"
          value={config.abandon_hours}
          onChange={(e) =>
            setConfig({
              ...config,
              abandon_hours: Math.max(1, parseInt(e.target.value) || 24),
            })
          }
          className={styles.input}
          disabled={saving}
        />
      </div>

      <div className={dialogStyles.field}>
        <div>
          <div className={dialogStyles.fieldLabel}>{t('settings.observation.purgeDays')}</div>
          <p className={dialogStyles.fieldHint}>{t('settings.observation.purgeDaysHint')}</p>
        </div>
        <input
          type="number"
          min="1"
          max="365"
          value={config.purge_days}
          onChange={(e) =>
            setConfig({
              ...config,
              purge_days: Math.max(1, parseInt(e.target.value) || 90),
            })
          }
          className={styles.input}
          disabled={saving}
        />
      </div>

      <div className={dialogStyles.field}>
        <div>
          <div className={dialogStyles.fieldLabel}>{t('settings.observation.autoCleanup')}</div>
          <p className={dialogStyles.fieldHint}>{t('settings.observation.autoCleanupHint')}</p>
        </div>
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={config.enabled}
            onChange={(e) => setConfig({ ...config, enabled: e.target.checked })}
            disabled={saving}
          />
          <span className={styles.toggleSlider} />
        </label>
      </div>

      <div className={styles.actions}>
        <Button onClick={handleSave} variant="primary" disabled={saving}>
          {saving ? t('settings.form.saving') : t('settings.form.save')}
        </Button>
        {message && (
          <span
            className={message.type === 'success' ? styles.successMessage : styles.errorMessage}
          >
            {message.text}
          </span>
        )}
      </div>

      {config.last_run && (
        <>
          <hr className={dialogStyles.divider} />
          <div className={dialogStyles.field}>
            <div>
              <div className={dialogStyles.fieldLabel}>{t('settings.observation.lastRun')}</div>
              <p className={dialogStyles.fieldHint}>
                {new Date(config.last_run.time).toLocaleString()} ·{' '}
                {config.last_run.type === 'auto'
                  ? t('settings.observation.lastRunAuto')
                  : t('settings.observation.lastRunManual')}
              </p>
              <p className={dialogStyles.fieldHint}>
                {t('settings.observation.lastRunDetail', {
                  sessions: config.last_run.purged_sessions,
                  events: config.last_run.purged_events,
                  agents: config.last_run.purged_agents,
                })}
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
