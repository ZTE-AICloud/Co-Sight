import { useActiveWorkspace } from '../../api/workspaces';
import { useI18n } from '../../i18n/useI18n';
import { cn } from '../../lib/cn';
import { useUiStore } from '../../stores/ui';
import { Icon } from '../ui/Icon';
import { Skeleton } from '../ui/Skeleton';
import styles from './Sidebar.module.css';

export interface WorkspaceEntryProps {
  collapsed: boolean;
}

/**
 * 侧栏底部的「当前工作区」入口（P3 / 需求 2.1）。
 *
 * 放在用户行**上方**：两行都是全局上下文，但"我现在在哪个工作区"比"我是谁"
 * 更常被确认，越靠上越省事。
 *
 * 这一行显示的是**服务端**的当前工作区（`/workspaces/active`），本地不留副本：
 * 换个标签页切过工作区之后，这里必须跟着变，否则界面显示的与实际生效的会分叉。
 */
export function WorkspaceEntry({ collapsed }: WorkspaceEntryProps) {
  const { t } = useI18n();
  const active = useActiveWorkspace();
  const openWorkspace = useUiStore((state) => state.openWorkspace);

  const isLoading = active.isPending;
  /*
   * 三种"没有名字"必须分开说，否则都会显示成「未选择工作区」而用户无从判断：
   * 正在加载（骨架）、请求失败（说失败）、确实一个都没选（说未选择）。
   */
  const label = active.isError
    ? t('workspace.error.title')
    : (active.data?.name ?? t('workspace.none'));

  return (
    <button
      type="button"
      className={cn(styles.workspaceRow, collapsed && styles.collapsedWorkspaceRow)}
      // 可访问名里带上工作区名：可见文字就是名字，只写"打开工作区设置"会与
      // 显示的文字不一致，语音控制用户念不出这个按钮（WCAG 2.5.3）。
      aria-label={t('workspace.openNamed', { name: label })}
      aria-haspopup="dialog"
      onClick={openWorkspace}
      {...(collapsed ? { title: t('workspace.open') } : {})}
    >
      <Icon name="workspace" className={styles.workspaceIcon} />
      {collapsed ? null : (
        <>
          {isLoading ? (
            // 宽度取名字的近似长度，避免加载完成时整行跳一下。
            <Skeleton width={92} height={12} />
          ) : (
            <span
              className={cn(
                styles.workspaceName,
                active.data === null || active.isError ? styles.workspaceNameEmpty : null,
              )}
            >
              {label}
            </span>
          )}
          {/* 下拉箭头 = "点了能从一列里挑一个"。用户行用齿轮，因为那里是"打开设置"。 */}
          <Icon name="chevronDown" className={styles.workspaceChevron} />
        </>
      )}
    </button>
  );
}
