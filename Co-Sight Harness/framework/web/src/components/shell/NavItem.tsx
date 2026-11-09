import { NavLink, useLocation, useNavigate } from 'react-router';

import { cn } from '../../lib/cn';
import { Icon, type IconName } from '../ui/Icon';
import { useI18n } from '../../i18n/useI18n';
import type { MessageKey } from '../../i18n/types';
import { useNewChatStore } from '../../stores/newChat';
import { useObservabilityReloadStore } from '../../stores/observabilityReload';
import styles from './NavItem.module.css';

export interface NavItemProps {
  labelKey: Extract<MessageKey, `nav.${string}`>;
  to: string;
  icon: IconName;
  /** 折叠态只显示图标。 */
  collapsed: boolean;
}

export function NavItem({ labelKey, to, icon, collapsed }: NavItemProps) {
  const { t } = useI18n();
  const label = t(labelKey);
  const location = useLocation();
  const navigate = useNavigate();
  const requestNewChat = useNewChatStore((state) => state.requestNewChat);
  const requestObservabilityReload = useObservabilityReloadStore((state) => state.requestReload);

  return (
    <NavLink
      to={to}
      onClick={(event) => {
        /*
         * 「新建对话」就是首页路由。已经在这一页时，Link 导航到同一个 location
         * 是 no-op，iframe 不会重建，用户看到的就是”点菜单没反应”。
         * 这里拦下这次导航，显式请求对话模块重建一次（ModuleHost 换 key）。
         * 从别的页面点进来不走这个分支，仍按普通导航处理。
         */
        if (to === '/' && location.pathname === '/') {
          event.preventDefault();
          /*
           * 从侧栏「最近」点进来的地址带着 `?agentRuntimeSessionId=`。只换 nonce
           * 不够：参数还在，重建出来的 iframe 会再次恢复同一场会话。先回到干净的
           * `/`，再请模块重建——两件事在同一次事件里，ModuleHost 只重挂一次。
           */
          if (location.search !== '') {
            void navigate('/');
          }
          requestNewChat();
        }
        /*
         * 「观测」模块同理。已经在 /observability 时再次点击，触发模块重载，
         * 回到会话列表页（模块的默认路由）。
         */
        if (to === '/observability' && location.pathname === '/observability') {
          event.preventDefault();
          requestObservabilityReload();
        }
      }}
      /*
       * 只有首页需要精确匹配。不加 `end` 的话 `/` 会匹配到所有路由，
       * 于是"新建对话"在任何页面上都显示为选中——两个导航项同时高亮。
       */
      end={to === '/'}
      /*
       * 折叠后文字没了，标题就是唯一的名称来源（鼠标悬停与读屏软件都读它）。
       * 未折叠时不设 title：文字已经写着，再弹一个同样的气泡只是噪音。
       */
      {...(collapsed ? { title: label } : {})}
      className={({ isActive }) => cn(styles.item, isActive && styles.active, collapsed && styles.collapsed)}
    >
      <Icon name={icon} size={16} className={styles.icon} />
      {collapsed ? null : <span className={styles.label}>{label}</span>}
    </NavLink>
  );
}
