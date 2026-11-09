/**
 * 工作区弹窗（P3 / 需求 2.1：新建、切换、删除）。
 *
 * 三件事都在这里：
 *
 * 1. **列表**——一列工作区，当前那个带「当前使用」徽标；
 * 2. **表单**——与列表**同一个弹窗内**换视图，不是再叠一层弹窗：
 *    两层遮罩叠加会把背景压得更黑，而这里要展示的就那么四个字段，
 *    多一层弹窗带来的视觉与焦点复杂度换不到任何东西；
 * 3. **两个确认框**（删除、放弃修改）——它们是**兄弟节点**而不是嵌在弹窗外壳里。
 *    这样 Esc 只会关掉最上面那个：React 事件沿 React 树冒泡，焦点在确认框里时
 *    那条路径上根本没有主弹窗的遮罩，`Dialog` 里的 `stopPropagation` 与
 *    `tabbable(panel)` 的局部性都不需要额外配合。`ConfirmDialog` 自己把初始焦点
 *    放在「取消」上，所以删除与放弃这两个不可逆动作的默认值都是最安全的那个。
 *
 * 「当前工作区」不在这个组件里存副本：它是服务端状态（`/workspaces/active`），
 * 这里只负责把它读出来做高亮，写走 `activate` 接口。
 */

import type { CreateWorkspaceInput, Workspace } from 'harness-shared';
import { useState } from 'react';

import {
  useActivateWorkspace,
  useActiveWorkspace,
  useCreateWorkspace,
  useDeleteWorkspace,
  useUpdateWorkspace,
  useWorkspaceList,
} from '../../api/workspaces';
import { useApiErrorMessage } from '../../api/useApiErrorMessage';
import { useI18n } from '../../i18n/useI18n';
import { useUiStore } from '../../stores/ui';
import { Button } from '../../components/ui/Button';
import { ConfigList, ConfigRow } from '../../components/ui/ConfigList';
import { Skeleton } from '../../components/ui/Skeleton';
import { StatusPanel } from '../../components/ui/StatusPanel';
import { Tag } from '../../components/ui/Tag';
import { ConfirmDialog } from '../../components/shell/ConfirmDialog';
import { Dialog } from '../../components/shell/Dialog';
import { WorkspaceForm } from './WorkspaceForm';
import styles from './WorkspaceDialog.module.css';

type Editing = { mode: 'create' } | { mode: 'edit'; workspace: Workspace };

/**
 * 加载中的骨架行。下标当 key 无所谓：这是一个**静态**的占位列表，不会重排、
 * 不会增删，用随机 key 反而每次渲染都重建节点。
 */
const SKELETON_ROWS = [0, 1, 2];

export function WorkspaceDialog() {
  const { t } = useI18n();
  const describeError = useApiErrorMessage();
  const closeWorkspace = useUiStore((state) => state.closeWorkspace);

  const list = useWorkspaceList();
  const active = useActiveWorkspace();
  const create = useCreateWorkspace();
  const update = useUpdateWorkspace();
  const activate = useActivateWorkspace();
  const remove = useDeleteWorkspace();

  const [editing, setEditing] = useState<Editing | null>(null);
  const [formDirty, setFormDirty] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Workspace | null>(null);
  /** 列表视图里的一行失败提示（保存/切换/删除）。表单内的失败走表单自己的 error。 */
  const [actionError, setActionError] = useState<string | null>(null);

  const activeId = active.data?.id ?? null;
  const workspaces = list.data ?? [];
  const saving = create.isPending || update.isPending;

  function leaveForm(): void {
    setEditing(null);
    setFormDirty(false);
  }

  /**
   * 关闭是**逐层**的：表单 → 列表 → 关掉弹窗，而且表单里有未保存内容时先问一句。
   *
   * 不分层的话，用户在表单里按一下 Esc 整个弹窗就没了、刚敲的名字也一并没了；
   * 这是"静默丢失用户输入"，比多按一次 Esc 糟得多。
   */
  function handleRequestClose(): void {
    if (editing !== null) {
      if (formDirty) {
        setDiscardOpen(true);
        return;
      }
      leaveForm();
      return;
    }
    closeWorkspace();
  }

  function startCreate(): void {
    setActionError(null);
    setEditing({ mode: 'create' });
  }

  function startEdit(workspace: Workspace): void {
    setActionError(null);
    setEditing({ mode: 'edit', workspace });
  }

  async function handleSubmit(input: CreateWorkspaceInput): Promise<void> {
    setActionError(null);
    try {
      if (editing !== null && editing.mode === 'edit') {
        await update.mutateAsync({ id: editing.workspace.id, patch: input });
        leaveForm();
        return;
      }

      const created = await create.mutateAsync(input);
      leaveForm();
      /*
       * 新建后立刻切过去。
       *
       * 新建一个工作区却不切过去，用户下一步几乎必然是要点「切换到此工作区」——
       * 那一步是为"切换已存在的工作区"设计的，不该让新建流程也走一遍。
       * 失败时**不谎报**成"保存失败"：工作区确实建好了，只是没切过去，
       * 所以单独一句文案说清两件事各是什么结果。
       */
      try {
        await activate.mutateAsync(created.id);
      } catch (error) {
        setActionError(t('workspace.createdNotActivated', { reason: describeError(error) }));
      }
    } catch (error) {
      setActionError(t('settings.form.saveFailed', { reason: describeError(error) }));
    }
  }

  async function handleActivate(id: string): Promise<void> {
    setActionError(null);
    try {
      await activate.mutateAsync(id);
    } catch (error) {
      setActionError(t('settings.form.actionFailed', { reason: describeError(error) }));
    }
  }

  async function confirmDelete(): Promise<void> {
    if (pendingDelete === null) {
      return;
    }
    setActionError(null);
    try {
      await remove.mutateAsync(pendingDelete.id);
      setPendingDelete(null);
    } catch (error) {
      // 失败也要关掉确认框：否则用户看到的是一个"点了没反应"的弹窗，
      // 而真正的失败信息被压在它后面根本看不见。
      setPendingDelete(null);
      setActionError(t('settings.form.deleteFailed', { reason: describeError(error) }));
    }
  }

  const deleteMessage =
    pendingDelete === null
      ? ''
      : [
          t('settings.form.deleteConfirmMessage', { name: pendingDelete.name }),
          // 有目录时把磁盘后果说清楚：框架建的那个会删，外部绑定的只解绑。
          // 不区分两者是因为界面拿不到"这个目录是谁建的"的元信息；文案把两种
          // 情况都写明，用户就不会误以为一定会（或一定不会）删目录。
          pendingDelete.directory === null ? null : t('workspace.deleteDirectoryNote'),
          // 删的正好是当前工作区时说清后果：服务端会一并清掉当前指针，
          // 用户回到列表时会看到「未选择工作区」。
          pendingDelete.id === activeId ? t('workspace.deleteActiveNote') : null,
        ]
          .filter((part): part is string => part !== null)
          .join(' ');

  const title =
    editing === null
      ? t('workspace.title')
      : editing.mode === 'edit'
        ? t('workspace.editTitle')
        : t('workspace.createTitle');

  return (
    <>
      <Dialog
        title={title}
        titleId="workspace-dialog-title"
        onClose={handleRequestClose}
        closeLabel={t('workspace.close')}
      >
        <div className={styles.body}>
          {editing === null ? (
            <>
              {actionError === null ? null : (
                <p className={styles.actionError} role="alert">
                  {actionError}
                </p>
              )}

              <div className={styles.listHeader}>
                <h3 className={styles.sectionTitle}>{t('workspace.listSection')}</h3>
                <Button size="sm" variant="primary" onClick={startCreate}>
                  {t('workspace.create')}
                </Button>
              </div>

              {list.isPending ? (
                <div className={styles.loadingList}>
                  {SKELETON_ROWS.map((row) => (
                    <Skeleton key={row} height={56} />
                  ))}
                </div>
              ) : list.isError ? (
                <StatusPanel
                  icon="alert"
                  role="alert"
                  title={t('workspace.error.title')}
                  hint={describeError(list.error)}
                  action={
                    <Button
                      icon="retry"
                      onClick={() => {
                        void list.refetch();
                      }}
                    >
                      {t('error.retry')}
                    </Button>
                  }
                />
              ) : workspaces.length === 0 ? (
                <StatusPanel
                  icon="workspace"
                  title={t('workspace.empty.title')}
                  hint={t('workspace.empty.hint')}
                />
              ) : (
                <ConfigList ariaLabel={t('workspace.listSection')}>
                  {workspaces.map((workspace) => (
                    <ConfigRow
                      key={workspace.id}
                      title={workspace.name}
                      badges={
                        workspace.id === activeId ? (
                          <Tag tone="brand">{t('workspace.activeBadge')}</Tag>
                        ) : null
                      }
                      meta={
                        // 目录可能很长，用 title 补全被省略号截断的部分。
                        <span
                          {...(workspace.directory === null ? {} : { title: workspace.directory })}
                        >
                          {workspace.directory ?? t('workspace.unboundDirectory')}
                        </span>
                      }
                      actions={
                        <>
                          {workspace.id === activeId ? null : (
                            <Button
                              size="sm"
                              disabled={activate.isPending}
                              onClick={() => {
                                void handleActivate(workspace.id);
                              }}
                            >
                              {t('workspace.switchTo')}
                            </Button>
                          )}
                          <Button size="sm" variant="ghost" onClick={() => startEdit(workspace)}>
                            {t('settings.form.edit')}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setPendingDelete(workspace);
                            }}
                          >
                            {t('settings.form.delete')}
                          </Button>
                        </>
                      }
                    />
                  ))}
                </ConfigList>
              )}
            </>
          ) : (
            <WorkspaceForm
              initial={editing.mode === 'edit' ? editing.workspace : null}
              pending={saving}
              error={actionError}
              onSubmit={(input) => {
                void handleSubmit(input);
              }}
              onCancel={handleRequestClose}
              // setState 本身是稳定引用，直接透传即可：`WorkspaceForm` 的 effect
              // 依赖它，传一个每次渲染都新建的箭头函数会让那个 effect 每次都跑。
              onDirtyChange={setFormDirty}
            />
          )}
        </div>
      </Dialog>

      {pendingDelete === null ? null : (
        <ConfirmDialog
          title={t('settings.form.deleteConfirmTitle')}
          message={deleteMessage}
          confirmLabel={t('settings.form.delete')}
          cancelLabel={t('settings.form.cancel')}
          closeLabel={t('workspace.close')}
          destructive
          pending={remove.isPending}
          onConfirm={() => {
            void confirmDelete();
          }}
          onCancel={() => {
            setPendingDelete(null);
          }}
        />
      )}

      {discardOpen ? (
        <ConfirmDialog
          title={t('settings.form.discardTitle')}
          message={t('settings.form.discardMessage')}
          confirmLabel={t('settings.form.discardConfirm')}
          cancelLabel={t('settings.form.cancel')}
          closeLabel={t('workspace.close')}
          destructive
          onConfirm={() => {
            setDiscardOpen(false);
            leaveForm();
          }}
          onCancel={() => {
            setDiscardOpen(false);
          }}
        />
      ) : null}
    </>
  );
}
