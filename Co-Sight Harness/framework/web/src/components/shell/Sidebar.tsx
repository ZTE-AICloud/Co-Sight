import { useState } from 'react';
import { NavLink, useNavigate } from 'react-router';

import { cn } from '../../lib/cn';
import { SIDEBAR_COLLAPSED_WIDTH } from '../../lib/sidebarWidth';
import { NAV_ITEMS } from '../../app/navigation';
import { RecentSessions } from '../../features/recent-sessions';
import { useI18n } from '../../i18n/useI18n';
import { useUiStore } from '../../stores/ui';
import { IconButton } from '../ui/Button';
import { Icon } from '../ui/Icon';
import { KnowledgeNavItem } from './KnowledgeNavItem';
import { NavItem } from './NavItem';
import { SIDEBAR_PANEL_ID, SidebarResizer } from './SidebarResizer';
import { WorkspaceEntry } from './WorkspaceEntry';
import styles from './Sidebar.module.css';

export function Sidebar() {
  const { t } = useI18n();
  const collapsed = useUiStore((state) => state.sidebarCollapsed);
  const toggleSidebar = useUiStore((state) => state.toggleSidebar);
  const sidebarWidth = useUiStore((state) => state.sidebarWidth);
  const setSidebarWidth = useUiStore((state) => state.setSidebarWidth);
  const openSettings = useUiStore((state) => state.openSettings);
  const navigate = useNavigate();

  /*
   * 是否正在拖拽宽度。这是**这一个组件**的瞬时状态（松手就没了），所以用 useState
   * 而不是塞进 store：唯一的作用是在拖拽期间关掉侧栏的宽度过渡（见 .resizing）。
   */
  const [resizing, setResizing] = useState(false);

  return (
    <aside
      id={SIDEBAR_PANEL_ID}
      className={cn(styles.sidebar, collapsed && styles.collapsed, resizing && styles.resizing)}
      /*
       * 宽度写在这里而不是 CSS 里：它有三个取值来源（折叠、拖拽、默认），
       * 集中在一处换算比在 CSS 里猜 `.collapsed` 与内联样式谁赢更清楚。
       */
      style={{ width: collapsed ? SIDEBAR_COLLAPSED_WIDTH : sidebarWidth }}
    >
      <div className={cn(styles.brand, collapsed && styles.collapsedBrand)}>
        {collapsed ? null : (
          <div className={styles.brandText}>
            <span className={styles.wordmark}>{t('app.wordmark')}</span>
            <span className={styles.subtitle}>{t('app.subtitle')}</span>
          </div>
        )}
        {/*
         * 折叠与展开共用同一个图标（需求 UX-1：与 deepseek-harness 对齐，它三处用的都是
         * 这个 "左三分之一被分栏的方框"）。按钮的无障碍名固定为「切换侧栏」，所以
         * 状态不靠图标传达——按钮就在侧栏里，侧栏本身是展开还是窄条一眼就能看出来。
         */}
        <IconButton icon="panelLeft" label={t('app.toggleSidebar')} onClick={toggleSidebar} />
      </div>

      <div className={styles.scroll}>
        <nav className={styles.nav} aria-label={t('app.navLabel')}>
          {NAV_ITEMS.map((item) =>
            /*
             * 「知识库」去的是用户在设置里配的外部地址，不是宿主里的 `/knowledge`。
             * 它在导航表里仍然占一行（顺序与文案都归那张表），只是渲染成另一种东西：
             * 配好了是**新标签页打开**的外链，没配是弹出去设置的提示
             * （见 `KnowledgeNavItem`）。
             */
            item.labelKey === 'nav.knowledge' ? (
              <KnowledgeNavItem
                key={item.labelKey}
                labelKey={item.labelKey}
                icon={item.icon}
                collapsed={collapsed}
              />
            ) : (
              <NavItem
                key={item.to}
                labelKey={item.labelKey}
                to={item.to}
                icon={item.icon}
                collapsed={collapsed}
              />
            ),
          )}
        </nav>

        {/*
         * 「最近」与导航共用这一个滚动区（`.scroll` 的注释就是为它留的位置）：
         * 会话多起来时列表跟着滚，导航不会被挤出去。
         *
         * 跳转规则留在壳层：「最近」只回传选中的会话 id，它不知道对话页的路由，也不
         * 认识 `agentRuntimeSessionId`。宿主把它原样转进 iframe 地址，对话模块据此恢复。
         */}
        <RecentSessions
          collapsed={collapsed}
          onOpenSession={(sessionId) => {
            void navigate({
              pathname: '/',
              search: `?agentRuntimeSessionId=${encodeURIComponent(sessionId)}`,
            });
          }}
        />
      </div>

      <div className={styles.footer}>
        <WorkspaceEntry collapsed={collapsed} />

        {/*
         * 「使用说明」：换的是主面板里的页面，所以是链接而不是按钮——中键、新标签页
         * 都能正常打开。放在设置上方：两行都是全局入口，但说明是"看"，设置是"改"。
         */}
        <NavLink
          to="/guide"
          className={cn(styles.guideRow, collapsed && styles.collapsedGuideRow)}
          aria-label={t('guide.navLabel')}
          {...(collapsed ? { title: t('guide.navLabel') } : {})}
        >
          <Icon name="help" size={16} className={styles.guideIcon} />
          {collapsed ? null : <span className={styles.guideLabel}>{t('guide.navLabel')}</span>}
        </NavLink>

        {/*
         * 这里原先是一个「本地用户」行（头像 + 用户名 + 齿轮）。
         * v1 没有登录（D25 本地单用户），那一行上的头像与用户名是**没有信息的装饰**：
         * 永远同一个头像、永远同一串"本地用户"，占着底部最显眼的位置却点不出任何区别。
         * 换成直接的「设置」入口——齿轮 + 文字，收起态只剩齿轮。
         */}
        <button
          type="button"
          className={cn(styles.settingsRow, collapsed && styles.collapsedSettingsRow)}
          onClick={() => {
            openSettings();
          }}
          {...(collapsed ? { title: t('user.openSettings') } : {})}
          aria-label={t('user.openSettings')}
        >
          <Icon name="settings" size={16} className={styles.settingsIcon} />
          {collapsed ? null : <span className={styles.settingsLabel}>{t('settings.title')}</span>}
        </button>
      </div>

      {/*
       * 拖拽手柄只在展开态出现。折叠态是定宽的窄条，拖它没有意义；
       * 参考实现 deepseek-harness 的窄条态同样不给手柄。
       */}
      {collapsed ? null : (
        <SidebarResizer
          width={sidebarWidth}
          onResize={setSidebarWidth}
          onDraggingChange={setResizing}
          label={t('app.resizeSidebar')}
          valueText={t('app.resizeValue', { width: sidebarWidth })}
        />
      )}
    </aside>
  );
}
