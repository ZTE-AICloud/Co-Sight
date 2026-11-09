/**
 * 侧栏「知识库」菜单项。
 *
 * 它与其余导航项不是一类东西：别的项跳到宿主里的固定页面，这一项打开
 * **用户自己配的地址**（设置 → 知识库路由设置里「当前可用」的那一条）。因此：
 *
 * - 配好之后渲染成普通外链，在**新的浏览器标签页**里打开那个地址。知识库是另一个
 *   站点，不留在宿主的嵌套路由里；`rel="noopener noreferrer"` 让新页面拿不到
 *   `window.opener`。地址虽然是用户填的，但契约层已限定它是 http(s) 绝对地址、
 *   且不得内嵌账号密码（`ragKnowledgeRouteUrlSchema`），可以安全地当 href 用；
 * - 外链永远不会是"当前页"，所以它不参与 `NavLink` 的高亮（不会出现 `aria-current`）；
 * - 没配时没有页面可开：**直接打开设置里的「新增」表单**。用户点菜单的意图是
 *   "看知识库"，先弹一句"还没配置"再让他点一次「去设置」只是多一步；
 * - 读取失败时不能假装"没配置"：地址可能配得好好的，只是后端没起来，所以仍然
 *   弹一个带「重试」的提示；
 * - 生效项来自 `useActiveRagKnowledge()`。设置里保存 / 切换 / 删除都会让
 *   `ragKnowledgeKeys.all` 整组失效，这个查询随即重取——所以「设置完立即生效」
 *   不需要重启，也不需要在这里额外轮询。
 */

import { useState } from 'react';

import { useActiveRagKnowledge } from '../../api/ragKnowledge';
import { useApiErrorMessage } from '../../api/useApiErrorMessage';
import { useI18n } from '../../i18n/useI18n';
import type { MessageKey } from '../../i18n/types';
import { cn } from '../../lib/cn';
import { useUiStore } from '../../stores/ui';
import { Icon, type IconName } from '../ui/Icon';
import { ConfirmDialog } from './ConfirmDialog';
import styles from './NavItem.module.css';

type NavLabelKey = Extract<MessageKey, `nav.${string}`>;

export interface KnowledgeNavItemProps {
  labelKey: NavLabelKey;
  icon: IconName;
  /** 折叠态只显示图标。 */
  collapsed: boolean;
}

export function KnowledgeNavItem({ labelKey, icon, collapsed }: KnowledgeNavItemProps) {
  const { t } = useI18n();
  const label = t(labelKey);
  const describeError = useApiErrorMessage();
  const active = useActiveRagKnowledge();
  const openSettings = useUiStore((state) => state.openSettings);
  const [loadErrorOpen, setLoadErrorOpen] = useState(false);

  const content = (
    <>
      <Icon name={icon} size={16} className={styles.icon} />
      {collapsed ? null : <span className={styles.label}>{label}</span>}
    </>
  );
  // 折叠后文字没了，`title` 是悬停与读屏软件唯一能拿到的名称。
  const collapsedTitle = collapsed ? { title: label } : {};

  if (active.data !== null && active.data !== undefined) {
    return (
      /*
       * 不写成 `NavLink`：目标在宿主之外，宿主路由表里没有它，也不该有。
       * `noopener noreferrer` 是新标签页的必带项——否则对方页面能通过
       * `window.opener` 反向导航宿主，`noreferrer` 同时避免把工作台地址泄给它。
       */
      <a
        href={active.data.routeUrl}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(styles.item, collapsed && styles.collapsed)}
        {...collapsedTitle}
      >
        {content}
      </a>
    );
  }

  function handleClick(): void {
    /*
     * 首次取数还没回来（本机接口，正常只有几十毫秒）。此时既不能把「还没读到」
     * 说成「没配置」，也不能直接把用户送去设置。让这次点击只负责再取一次，
     * 用户再点一下就好。
     */
    if (active.isPending) {
      void active.refetch();
      return;
    }

    if (active.isError) {
      setLoadErrorOpen(true);
      return;
    }

    /*
     * 一条可用路由都没有：直接打开「知识库路由设置」并展开新增表单。
     * 该表单在这条路径下**默认勾上「设为可用」**（见 RagKnowledgeSettingsPanel）：
     * 本来就是因为没有可用项才走到这里，再加一条不生效的等于原地踏步。
     */
    openSettings('ragKnowledge', { create: true });
  }

  return (
    <>
      <button
        type="button"
        className={cn(styles.item, collapsed && styles.collapsed)}
        onClick={handleClick}
        /*
         * 首次取数期间标成忙碌：读屏软件不会把"还没读到"念成一个可点的死按钮，
         * 测试也能据此等到状态落定，而不是靠猜。
         */
        aria-busy={active.isPending ? true : undefined}
        {...collapsedTitle}
      >
        {content}
      </button>

      {loadErrorOpen ? (
        <ConfirmDialog
          title={t('knowledgeRoute.loadFailedTitle')}
          message={t('knowledgeRoute.loadFailedHint', { reason: describeError(active.error) })}
          confirmLabel={t('error.retry')}
          cancelLabel={t('settings.form.cancel')}
          closeLabel={t('settings.close')}
          onConfirm={() => {
            setLoadErrorOpen(false);
            void active.refetch();
          }}
          onCancel={() => {
            setLoadErrorOpen(false);
          }}
        />
      ) : null}
    </>
  );
}
