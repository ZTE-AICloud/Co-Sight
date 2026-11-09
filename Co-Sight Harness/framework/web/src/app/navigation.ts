/**
 * 侧栏导航表。
 *
 * 单独成文件而不是写在 Sidebar 里，是因为"有哪些导航项、各自去哪"这份信息
 * 还要被别处用到（面包屑、未知路由回退、后续按 capability 找导航项），
 * 塞进组件会让那些地方只能重新声明一遍。
 *
 * 顺序即视觉顺序：新建对话 / 专家·技能 / Harness工程构建 / 知识库 / 观测。
 */

import type { IconName } from '../components/ui/Icon';
import type { MessageKey } from '../i18n/types';

/** 只允许 nav 命名空间下的键——写错段落是编译错误。 */
type NavLabelKey = Extract<MessageKey, `nav.${string}`>;

export interface NavItemDef {
  labelKey: NavLabelKey;
  /** 宿主路由。模块自身的内部路由由模块自己管，宿主只认这一个入口。 */
  to: string;
  icon: IconName;
}

export const NAV_ITEMS: readonly NavItemDef[] = [
  { labelKey: 'nav.newChat', to: '/', icon: 'newChat' },
  { labelKey: 'nav.experts', to: '/experts', icon: 'experts' },
  { labelKey: 'nav.agentDev', to: '/agent-dev', icon: 'agentDev' },
  /*
   * 侧栏把「知识库」渲染成外链：有生效路由时在**新标签页**打开配置的地址。
   * 这里的 `to` 是直接访问时那条内嵌页的落点，也是「每条 to 都有落点」这条
   * 一致性测试的锚点（见 `app/routes.tsx` 的 `knowledge` 子路由）。
   */
  { labelKey: 'nav.knowledge', to: '/knowledge', icon: 'knowledge' },
  { labelKey: 'nav.observability', to: '/observability', icon: 'observability' },
];
