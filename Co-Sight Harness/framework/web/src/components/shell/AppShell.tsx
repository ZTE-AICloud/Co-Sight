import { Outlet } from 'react-router';

import { useHtmlLang } from '../../lib/useHtmlLang';
import { useI18n } from '../../i18n/useI18n';
import { useUiStore } from '../../stores/ui';
import { WorkspaceDialog } from '../../features/workspace/WorkspaceDialog';
import { SettingsDialog } from './SettingsDialog';
import { Sidebar } from './Sidebar';
import styles from './AppShell.module.css';

/**
 * 应用外壳。
 *
 * 布局在**外壳这一层**就固定下来（侧栏 + 主面板），页面只负责往主面板里填内容：
 * 这样切换页面时侧栏不会重新挂载、滚动位置不丢，也不需要每个页面各自摆一次骨架。
 *
 * 主面板内部滚动，body 不滚动（见 global.css 的 `overflow: hidden`），
 * 避免出现"页面滚动条 + 面板滚动条"两条并存的难看状态。
 *
 * 会话页的「工作区文件」能力已经整合进 cosight-viewer 自己（模块内渲染抽屉），
 * 外壳不再往 iframe 上画悬浮按钮，也不再为面板预留 `padding-right`。
 */
export function AppShell() {
  const { t, locale } = useI18n();
  const settingsOpen = useUiStore((state) => state.settingsOpen);
  const workspaceOpen = useUiStore((state) => state.workspaceOpen);

  // 语言是文档级状态，外壳是唯一的常驻根组件，放这里最省事也最不容易漏。
  useHtmlLang(locale);

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main-content">
        {t('app.skipToContent')}
      </a>

      <Sidebar />

      {/*
       * tabIndex={-1}：让上面那个跳转链接能把焦点送进来（没有 tabIndex 的目标元素
       * 无法被 href="#id" 聚焦）。它不进 Tab 序列，所以不影响顺序导航。
       */}
      <main id="main-content" className={styles.main} tabIndex={-1}>
        <Outlet />
      </main>

      {settingsOpen ? <SettingsDialog /> : null}
      {workspaceOpen ? <WorkspaceDialog /> : null}
    </div>
  );
}
