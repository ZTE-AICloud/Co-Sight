/**
 * 知识库路由面板（设置 → 知识库路由设置）。
 *
 * 结构与 `AgentProxySettingsPanel` 一致（列表与表单互斥、失败行 `role="alert"`、
 * 删除走确认框），差异都在数据语义上：
 *
 * - 生效项**全局只有一个**，所以「设为可用」调 `POST /:id/activate`（语义是切换），
 *   已经是可用项的行不再显示这个按钮；
 * - 打开这条地址的入口在**侧栏**（`KnowledgeNavItem`），不在列表行上：
 *   同一个动作只留一个入口，否则"设置里点一下"和"菜单里点一下"迟早会漂成两种行为；
 * - 删掉可用项不会自动补位（仓储层就是这么定的），确认语里要补一句后果。
 *
 * 两种「打开新增」的来源，行为差别只在**初始是否勾上「设为可用」**：
 * - 面板里的「新增」按钮：用户可能只是想先把地址存下来，默认不勾；
 * - 侧栏「知识库」在一条可用路由都没有时打开这里（`settingsCreateRequested`）：
 *   本来就是因为没有可用项才走到这一步，默认勾上，保存后菜单立刻就能点开页面。
 */

import { useEffect, useState } from 'react';
import type { RagKnowledgeBase } from 'harness-shared';

import { useApiErrorMessage } from '../../api/useApiErrorMessage';
import {
  useActivateRagKnowledge,
  useCreateRagKnowledge,
  useDeleteRagKnowledge,
  useRagKnowledgeList,
  useUpdateRagKnowledge,
} from '../../api/ragKnowledge';
import { useI18n } from '../../i18n/useI18n';
import { useUiStore } from '../../stores/ui';
import { Button } from '../../components/ui/Button';
import { ConfigList, ConfigRow } from '../../components/ui/ConfigList';
import { StatusPanel } from '../../components/ui/StatusPanel';
import { Tag } from '../../components/ui/Tag';
import { ConfirmDelete } from '../config/ConfirmDelete';
import { ConfigRowSkeleton } from '../config/ConfigRowSkeleton';
// 组件名带 `Config`、逻辑模块不带：两个文件名只差大小写会在 Windows/macOS 上撞名
// （理由与守卫见 `AgentProxyConfigForm` 的开头）。
import { RagKnowledgeConfigForm } from './RagKnowledgeConfigForm';
import {
  ragKnowledgeCreatePayload,
  ragKnowledgeUpdatePayload,
  type RagKnowledgeDraft,
} from './ragKnowledgeForm';
import styles from '../config/config.module.css';

/** 骨架行数（同模型/代理面板）。 */
const SKELETON_ROWS = 3;

/**
 * 列表行里显示的地址与说明的长度上限。
 *
 * 地址最长 2048 字符、说明最长 256 字符，整段塞进行里会被 `.meta` 的省略号截掉
 * （看不出问题），但读屏会把每一行的全文都念一遍。所以在**进入 DOM 之前**截断，
 * 完整内容留在 `title` 里供鼠标悬停与浏览器查找使用。
 */
const META_TEXT_LENGTH = 80;

function shorten(text: string): string {
  return text.length <= META_TEXT_LENGTH ? text : `${text.slice(0, META_TEXT_LENGTH)}…`;
}

export function RagKnowledgeSettingsPanel() {
  const { t } = useI18n();
  const describeError = useApiErrorMessage();

  const list = useRagKnowledgeList();
  const createKb = useCreateRagKnowledge();
  const updateKb = useUpdateRagKnowledge();
  const activateKb = useActivateRagKnowledge();
  const deleteKb = useDeleteRagKnowledge();

  const [editing, setEditing] = useState<RagKnowledgeBase | null>(null);
  const [creating, setCreating] = useState(false);
  /**
   * 这次「新增」是不是从侧栏「知识库」进来的（没有任何可用路由）。
   * 是的话表单初始勾上「设为可用」——见文件头的两种来源说明。
   */
  const [createDefaultsActive, setCreateDefaultsActive] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<RagKnowledgeBase | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const createRequested = useUiStore((state) => state.settingsCreateRequested);
  const clearCreateRequest = useUiStore((state) => state.clearSettingsCreateRequest);

  /*
   * 侧栏「知识库」在没有可用路由时，通过 store 请求"打开设置并直接新增"。
   * 消费后立刻清掉请求：它只对这一次打开有效，否则下次普通打开设置会莫名其妙
   * 停在一个空表单上。setState 函数是稳定的，不放进依赖里。
   */
  useEffect(() => {
    if (!createRequested) {
      return;
    }
    setActionError(null);
    setEditing(null);
    setCreateDefaultsActive(true);
    setCreating(true);
    clearCreateRequest();
  }, [createRequested, clearCreateRequest]);

  const bases = list.data ?? [];
  const formOpen = creating || editing !== null;
  const saving = createKb.isPending || updateKb.isPending;

  function openCreate(defaultActive: boolean): void {
    setActionError(null);
    setEditing(null);
    setCreateDefaultsActive(defaultActive);
    setCreating(true);
  }

  function closeForm(): void {
    setCreating(false);
    setEditing(null);
    setCreateDefaultsActive(false);
  }

  function handleSubmit(draft: RagKnowledgeDraft): void {
    setActionError(null);
    const target = editing;

    const onError = (error: unknown): void => {
      setActionError(t('settings.form.saveFailed', { reason: describeError(error) }));
    };

    if (target === null) {
      createKb.mutate(ragKnowledgeCreatePayload(draft), { onSuccess: closeForm, onError });
      return;
    }

    updateKb.mutate(
      { id: target.id, patch: ragKnowledgeUpdatePayload(draft) },
      { onSuccess: closeForm, onError },
    );
  }

  function handleActivate(base: RagKnowledgeBase): void {
    setActionError(null);
    activateKb.mutate(base.id, {
      onError: (error) => {
        setActionError(t('settings.form.actionFailed', { reason: describeError(error) }));
      },
    });
  }

  function handleDelete(): void {
    const target = deleteTarget;
    if (target === null) {
      return;
    }
    setActionError(null);
    deleteKb.mutate(target.id, {
      // 失败时同样关掉确认框：错误已经由面板上那一行 `role="alert"` 说明。
      onSuccess: () => {
        setDeleteTarget(null);
      },
      onError: (error) => {
        setDeleteTarget(null);
        setActionError(t('settings.form.deleteFailed', { reason: describeError(error) }));
      },
    });
  }

  return (
    <div className={styles.panel}>
      {actionError === null ? null : (
        <p className={styles.alert} role="alert">
          {actionError}
        </p>
      )}

      {formOpen ? (
        <>
          <div className={styles.sectionHead}>
            <h3 className={styles.sectionTitle}>
              {t(
                editing === null
                  ? 'settings.ragKnowledge.createTitle'
                  : 'settings.ragKnowledge.editTitle',
              )}
            </h3>
          </div>
          <RagKnowledgeConfigForm
            base={editing}
            defaultActive={createDefaultsActive}
            pending={saving}
            onSubmit={handleSubmit}
            onCancel={closeForm}
          />
        </>
      ) : (
        <>
          <div className={styles.sectionHead}>
            <h3 className={styles.sectionTitle}>{t('settings.ragKnowledge.listSection')}</h3>
            <Button
              variant="primary"
              onClick={() => {
                openCreate(false);
              }}
            >
              {t('settings.ragKnowledge.create')}
            </Button>
          </div>

          {list.isPending ? (
            <ConfigList ariaLabel={t('settings.ragKnowledge.loading')}>
              {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                <ConfigRowSkeleton key={index} />
              ))}
            </ConfigList>
          ) : null}

          {/* 失败时不渲染空态（理由同模型面板）。 */}
          {list.isError ? (
            <StatusPanel
              icon="alert"
              role="alert"
              title={t('settings.ragKnowledge.error.title')}
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
          ) : null}

          {!list.isPending && !list.isError && bases.length === 0 ? (
            <StatusPanel
              icon="empty"
              title={t('settings.ragKnowledge.empty.title')}
              hint={t('settings.ragKnowledge.empty.hint')}
            />
          ) : null}

          {bases.length === 0 ? null : (
            <ConfigList ariaLabel={t('settings.ragKnowledge.listSection')}>
              {bases.map((base) => (
                <ConfigRow
                  key={base.id}
                  title={base.name}
                  badges={
                    base.isActive ? (
                      <Tag tone="brand">{t('settings.ragKnowledge.activeBadge')}</Tag>
                    ) : null
                  }
                  meta={
                    <>
                      <span title={base.routeUrl}>{shorten(base.routeUrl)}</span>
                      {/* 只显示账号；密码按 D26 永不回显，连掩码都不进这一行。 */}
                      {base.username === null ? null : (
                        <>
                          {' · '}
                          <span>
                            {t('settings.ragKnowledge.metaAccount', { username: base.username })}
                          </span>
                        </>
                      )}
                      {base.description === null ? null : (
                        <>
                          {' · '}
                          <span title={base.description}>{shorten(base.description)}</span>
                        </>
                      )}
                    </>
                  }
                  actions={
                    <div
                      className={styles.rowActions}
                      role="group"
                      aria-label={t('settings.ragKnowledge.action.ariaLabel', { name: base.name })}
                    >
                      {/* 已经是可用项的行不显示「设为可用」（理由同模型/代理面板）。 */}
                      {base.isActive ? null : (
                        <Button
                          size="sm"
                          disabled={activateKb.isPending}
                          aria-label={t('settings.ragKnowledge.action.activate', {
                            name: base.name,
                          })}
                          onClick={() => {
                            handleActivate(base);
                          }}
                        >
                          {t('settings.ragKnowledge.activate')}
                        </Button>
                      )}

                      <Button
                        size="sm"
                        aria-label={t('settings.ragKnowledge.action.edit', { name: base.name })}
                        onClick={() => {
                          setCreating(false);
                          setEditing(base);
                        }}
                      >
                        {t('settings.form.edit')}
                      </Button>

                      <Button
                        size="sm"
                        aria-label={t('settings.ragKnowledge.action.remove', { name: base.name })}
                        onClick={() => {
                          setDeleteTarget(base);
                        }}
                      >
                        {t('settings.form.delete')}
                      </Button>
                    </div>
                  }
                />
              ))}
            </ConfigList>
          )}
        </>
      )}

      {deleteTarget === null ? null : (
        <ConfirmDelete
          title={t('settings.form.deleteConfirmTitle')}
          message={
            deleteTarget.isActive
              ? // 删的是可用项：补一句后果（不会自动把别的一条改成可用）。
                `${t('settings.form.deleteConfirmMessage', { name: deleteTarget.name })} ${t('settings.ragKnowledge.deleteActiveWarning')}`
              : t('settings.form.deleteConfirmMessage', { name: deleteTarget.name })
          }
          confirmLabel={t('settings.form.delete')}
          cancelLabel={t('settings.form.cancel')}
          closeLabel={t('settings.close')}
          pending={deleteKb.isPending}
          onConfirm={handleDelete}
          onCancel={() => {
            setDeleteTarget(null);
          }}
        />
      )}
    </div>
  );
}
