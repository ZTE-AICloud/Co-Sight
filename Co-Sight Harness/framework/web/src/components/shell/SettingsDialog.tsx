import { SUPPORTED_LOCALES, type Locale } from 'harness-shared';

import { cn } from '../../lib/cn';
import { useRovingFocus } from '../../lib/rovingFocus';
import { useI18n } from '../../i18n/useI18n';
import { SETTINGS_TABS, useUiStore, type SettingsTab } from '../../stores/ui';
import { useHealth } from '../../api/system';
// 两个配置面板在设置打开时才可能被渲染（AppShell 里 `settingsOpen ? … : null`）。
import { AgentProxySettingsPanel } from '../../features/agent-proxies/AgentProxySettingsPanel';
import { ModelSettingsPanel } from '../../features/models/ModelSettingsPanel';
import { ObservationSettingsPanel } from '../../features/observability/ObservationSettingsPanel';
import { RagKnowledgeSettingsPanel } from '../../features/rag-knowledge/RagKnowledgeSettingsPanel';
import { Segmented } from '../ui/Segmented';
import { Dialog } from './Dialog';
import styles from './SettingsDialog.module.css';

/**
 * 语言名称**不翻译**：中文用户找 "English"、英文用户找 "简体中文"，
 * 把 "English" 译成 "英语" 只会让英文用户在自己的界面里找不到自己的语言。
 */
const LOCALE_LABELS: Record<Locale, string> = {
  'zh-CN': '简体中文',
  'en-US': 'English',
};

const LOCALE_OPTIONS = SUPPORTED_LOCALES.map((locale) => ({
  value: locale,
  label: LOCALE_LABELS[locale],
}));

const tabId = (tab: SettingsTab): string => `settings-tab-${tab}`;
const panelId = (tab: SettingsTab): string => `settings-panel-${tab}`;

/**
 * 设置弹窗（需求 1.3；底部设置模块，视觉参照 OpenHands）。
 *
 * 遮罩、标题栏、焦点管理都在 `Dialog` 里，这里只剩"有哪些页签、每个页签是什么"。
 */
export function SettingsDialog() {
  const { t, locale, setLocale } = useI18n();
  const tab = useUiStore((state) => state.settingsTab);
  const setSettingsTab = useUiStore((state) => state.setSettingsTab);
  const closeSettings = useUiStore((state) => state.closeSettings);
  const health = useHealth();
  const roving = useRovingFocus(SETTINGS_TABS, setSettingsTab);

  return (
    <Dialog
      title={t('settings.title')}
      titleId="settings-title"
      onClose={closeSettings}
      closeLabel={t('settings.close')}
    >
      <div className={styles.body}>
        <div className={styles.nav} role="tablist" aria-orientation="vertical">
          {SETTINGS_TABS.map((value, index) => {
            const selected = value === tab;
            return (
              <button
                key={value}
                ref={roving.register(value)}
                type="button"
                role="tab"
                id={tabId(value)}
                aria-selected={selected}
                aria-controls={panelId(value)}
                tabIndex={selected ? 0 : -1}
                className={cn(styles.tab, selected && styles.tabActive)}
                onClick={() => {
                  setSettingsTab(value);
                }}
                onKeyDown={(event) => {
                  roving.onKeyDown(event, index);
                }}
              >
                {t(`settings.nav.${value}`)}
              </button>
            );
          })}
        </div>

        <div className={styles.content}>
          <section
            role="tabpanel"
            id={panelId('general')}
            aria-labelledby={tabId('general')}
            hidden={tab !== 'general'}
          >
            <h3 className={styles.sectionTitle}>{t('settings.general.title')}</h3>

            <div className={styles.field}>
              <div>
                <div className={styles.fieldLabel}>{t('settings.general.language')}</div>
                <p className={styles.fieldHint}>{t('settings.general.languageHint')}</p>
              </div>
              <Segmented
                options={LOCALE_OPTIONS}
                value={locale}
                onChange={setLocale}
                ariaLabel={t('settings.general.language')}
              />
            </div>

            <hr className={styles.divider} />

            <h3 className={styles.sectionTitle}>{t('settings.general.dataSection')}</h3>

            <div className={styles.field}>
              <div>
                <div className={styles.fieldLabel}>{t('settings.general.dataHome')}</div>
                <p className={styles.fieldHint}>{t('settings.general.dataHomeHint')}</p>
              </div>
              {/*
               * 显示的是服务端**实际生效**的目录，不是前端猜的或配置模板里的默认值。
               * 用户把 COSIGHT_HOME 配错时，这里是唯一能一眼看出问题的地方。
               */}
              <span className={styles.fieldValue} title={health.data?.cosightHome}>
                {health.data?.cosightHome ?? '—'}
              </span>
            </div>

            <div className={styles.field}>
              <div className={styles.fieldLabel}>{t('settings.general.version')}</div>
              <span className={styles.fieldValue}>{health.data?.version ?? '—'}</span>
            </div>

            <hr className={styles.divider} />

            <h3 className={styles.sectionTitle}>{t('settings.general.aboutSection')}</h3>
            <p className={styles.fieldHint}>{t('settings.general.about')}</p>
          </section>

          {/*
           * 模型设置（需求 2.3）、知识库路由设置与 Agent 代理配置（需求 2.3-1）。
           *
           * 这几个面板**常挂**在同一批 `<section hidden>` 里，不做"切到哪个页签才渲染
           * 哪个"：常挂的代价是打开设置时多几次列表请求（这些列表在执行页里也要用，
           * 多数情况下已经命中同一个 React Query 缓存），换来的是表单在半途切页签
           * 再切回来时**还在**。按需挂载会在切页签的那一刻把整个表单卸载掉，
           * 用户刚敲的十几个字段会静默消失，而这里没有任何"未保存"的提示途径。
           *
           * 隐藏的面板不会污染外层 `Dialog`：它的焦点查询用 `closest('[hidden]')`
           * 过滤，`hidden` 的 `<section>` 里的控件一个都进不了 Tab 序列；
           * 读屏同理，`hidden` 的内容不在可访问性树里。
           *
           * 例外是 Agent 代理面板：它的数据不是普通列表，而是让 smart-factory 起一个
           * Claude Code 探测进程（1–2 秒、200MB+）。面板照旧常挂（保住表单状态），
           * 但 `active` 只在页签真的被选中时才为真 —— 打开设置本身不该替用户起进程。
           */}
          <section
            role="tabpanel"
            id={panelId('model')}
            aria-labelledby={tabId('model')}
            hidden={tab !== 'model'}
          >
            <ModelSettingsPanel />
          </section>

          <section
            role="tabpanel"
            id={panelId('ragKnowledge')}
            aria-labelledby={tabId('ragKnowledge')}
            hidden={tab !== 'ragKnowledge'}
          >
            <RagKnowledgeSettingsPanel />
          </section>

          <section
            role="tabpanel"
            id={panelId('agentProxy')}
            aria-labelledby={tabId('agentProxy')}
            hidden={tab !== 'agentProxy'}
          >
            <AgentProxySettingsPanel active={tab === 'agentProxy'} />
          </section>

          <section
            role="tabpanel"
            id={panelId('observation')}
            aria-labelledby={tabId('observation')}
            hidden={tab !== 'observation'}
          >
            <ObservationSettingsPanel />
          </section>
        </div>
      </div>
    </Dialog>
  );
}
