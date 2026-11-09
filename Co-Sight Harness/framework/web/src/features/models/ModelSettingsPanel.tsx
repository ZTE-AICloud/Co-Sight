/**
 * 模型设置面板（设置 → 模型设置）。
 *
 * 列表与表单**互斥**（点「编辑」「新增」后表单顶掉列表，取消再换回来），而不是
 * 表单追加在列表下方：十几个字段会把设置弹窗的内容区拉得很长，而滚动容器是
 * `Dialog` 内部的 `.content`、不归这里控制，用户点完「编辑」很可能看不到表单的
 * 第一行。互斥还有个副作用是好的——表单打开时列表里的「删除」不可达，于是
 * "正在编辑的那条被删掉"这种状态根本不存在。
 *
 * 三件事刻意**不做**：
 * - 不做「测试连接」：服务端 `POST /models/:id/probe` 的实现是 notImplemented
 *   （探测要由服务端去请求用户填的地址，等于一条 SSRF 通道，见 `api/models.ts`）。
 *   放一个点了只报"尚未实现"的按钮比没有按钮更糟。
 * - 删掉当前生效的模型时**不自动切换**到别的模型：这是替用户做决定，而且服务端
 *   也没有这个语义。改由确认框里那句 `deleteActiveWarning` 把后果说清楚。
 * - 不在列表里回显密钥：读侧只有 `hasApiKey`（D26）。
 */

import { useState } from 'react';
import type { ModelConfig } from 'harness-shared';

import { useApiErrorMessage } from '../../api/useApiErrorMessage';
import { useActivateModel, useCreateModel, useDeleteModel, useModelList, useUpdateModel } from '../../api/models';
import { useI18n } from '../../i18n/useI18n';
import { Button } from '../../components/ui/Button';
import { ConfigList, ConfigRow } from '../../components/ui/ConfigList';
import { StatusPanel } from '../../components/ui/StatusPanel';
import { Tag } from '../../components/ui/Tag';
import { ConfirmDelete } from '../config/ConfirmDelete';
import { ConfigRowSkeleton } from '../config/ConfigRowSkeleton';
import { ModelConfigForm } from './ModelConfigForm';
import { ModelDetailView } from './ModelDetailView';
import { ModuleAccessCard } from './ModuleAccessCard';
import { modelCreatePayload, modelUpdatePayload, type ModelDraft } from './modelForm';
import styles from '../config/config.module.css';

/** 骨架行数。取 3 行：够撑住面板高度，又不至于刷新时整块换成一个空列表。 */
const SKELETON_ROWS = 3;

export function ModelSettingsPanel() {
  const { t } = useI18n();
  const describeError = useApiErrorMessage();

  const list = useModelList();
  const createModel = useCreateModel();
  const updateModel = useUpdateModel();
  const activateModel = useActivateModel();
  const deleteModel = useDeleteModel();

  /** 正在编辑的那条；`null` 且 `creating` 为假时显示列表。 */
  const [editing, setEditing] = useState<ModelConfig | null>(null);
  const [creating, setCreating] = useState(false);
  /**
   * 正在**查看**的那条（只读详情）。与 `editing` 互斥，而不是给详情加一个
   * "编辑中"的标记：详情页上那两下点击（返回 / 编辑）本来就是两个不同的去处，
   * 用一个状态加分支表示只会让"现在到底能不能改"取决于另一个字段。
   */
  const [viewing, setViewing] = useState<ModelConfig | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ModelConfig | null>(null);
  /*
   * 写操作失败的那一句。放在面板级而不是表单级：删除与激活都不经过表单，
   * 而"上一次删除失败了"这件事不该因为用户又点开了表单就消失。
   */
  const [actionError, setActionError] = useState<string | null>(null);

  const models = list.data ?? [];
  const formOpen = creating || editing !== null;
  const saving = createModel.isPending || updateModel.isPending;

  /*
   * 新增表单里「设为当前使用」的初值：**只有确定当前没有生效模型时**才默认打开。
   *
   * 首次配置（一条都没有）时，新建的这条就是平台唯一可用的模型，默认打开省掉
   * "保存完还得再点一次「设为当前使用」"；已有生效模型时默认关闭，不悄悄顶掉
   * 用户正在用的那条。全部被停用时同样默认打开——此时平台本来就没有可用模型，
   * 打不打开都不会顶掉谁。
   *
   * 依据取 `list.data` 而不是 `models`：列表还没回来或读取失败时 `models` 也是
   * 空数组，照它猜"没有"会让新建的一条顶掉正在用的模型；猜"有"最坏只是用户
   * 手动拨一下开关。
   */
  const defaultActive = list.data !== undefined && !list.data.some((model) => model.isActive);

  function closeForm(): void {
    setCreating(false);
    setEditing(null);
  }

  /** 从详情切进表单：关掉详情，否则两个视图会叠在一起。 */
  function editFromDetail(model: ModelConfig): void {
    setViewing(null);
    setCreating(false);
    setEditing(model);
  }

  function handleSubmit(draft: ModelDraft): void {
    setActionError(null);
    const target = editing;

    const onError = (error: unknown): void => {
      setActionError(t('settings.form.saveFailed', { reason: describeError(error) }));
    };

    if (target === null) {
      createModel.mutate(modelCreatePayload(draft), {
        onSuccess: closeForm,
        onError,
      });
      return;
    }

    updateModel.mutate(
      { id: target.id, patch: modelUpdatePayload(draft) },
      { onSuccess: closeForm, onError },
    );
  }

  function handleActivate(model: ModelConfig): void {
    setActionError(null);
    activateModel.mutate(model.id, {
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
    deleteModel.mutate(target.id, {
      // 失败时也关掉确认框：错误已经交给面板上那一行 `role="alert"` 了，
      // 留着一个"要不要再按一次"的框只会让人以为第一次没点下去。
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
              {t(editing === null ? 'settings.model.createTitle' : 'settings.model.editTitle')}
            </h3>
          </div>
          <ModelConfigForm
            model={editing}
            defaultActive={defaultActive}
            pending={saving}
            onSubmit={handleSubmit}
            onCancel={closeForm}
          />
        </>
      ) : viewing === null ? (
        <>
          <div className={styles.sectionHead}>
            <h3 className={styles.sectionTitle}>{t('settings.model.listSection')}</h3>
            <Button
              variant="primary"
              onClick={() => {
                setEditing(null);
                setCreating(true);
              }}
            >
              {t('settings.model.create')}
            </Button>
          </div>

          {list.isPending ? (
            <ConfigList ariaLabel={t('settings.model.loading')}>
              {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                <ConfigRowSkeleton key={index} />
              ))}
            </ConfigList>
          ) : null}

          {/*
           * 失败时**不**渲染空态：`models` 在失败时恒为空数组，两个分支都放着的话
           * 会同时出现"加载失败"和"还没有模型配置"——后者会让用户以为数据没了。
           */}
          {list.isError ? (
            <StatusPanel
              icon="alert"
              role="alert"
              title={t('settings.model.error.title')}
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

          {!list.isPending && !list.isError && models.length === 0 ? (
            <StatusPanel
              icon="empty"
              title={t('settings.model.empty.title')}
              hint={t('settings.model.empty.hint')}
            />
          ) : null}

          {models.length === 0 ? null : (
            <ConfigList ariaLabel={t('settings.model.listSection')}>
              {models.map((model) => (
                <ConfigRow
                  key={model.id}
                  title={model.label}
                  onSelect={() => {
                    setViewing(model);
                  }}
                  selectLabel={t('settings.model.action.view', { name: model.label })}
                  badges={
                    model.isActive ? (
                      <Tag tone="brand">{t('settings.model.activeBadge')}</Tag>
                    ) : null
                  }
                  meta={
                    <>
                      {/* 词条键与契约枚举一一对应：`provider` 的取值直接接在键名后面。 */}
                      {t(`settings.model.provider.${model.provider}`)}
                      {' · '}
                      {model.modelName}
                      {' · '}
                      {/*
                       * 网关地址进次要信息行：不填时"用哪个地址"是用户排查
                       * "为什么连不上"时第一个要看的东西，而在此之前它只在
                       * 编辑表单里能看到。
                       */}
                      {model.baseUrl ?? t('settings.model.baseUrlDefault')}
                      {' · '}
                      {model.hasApiKey
                        ? t('settings.model.keyConfigured')
                        : t('settings.model.keyMissing')}
                    </>
                  }
                  actions={
                    <div
                      className={styles.rowActions}
                      role="group"
                      aria-label={t('settings.model.action.ariaLabel', { name: model.label })}
                    >
                      <Button
                        size="sm"
                        aria-label={t('settings.model.action.edit', { name: model.label })}
                        onClick={() => {
                          setCreating(false);
                          setEditing(model);
                        }}
                      >
                        {t('settings.form.edit')}
                      </Button>

                      {/*
                       * 已经是当前使用的行不显示「设为当前使用」：一个点下去不改变
                       * 任何状态的按钮，会让人怀疑刚才那一下没生效。
                       */}
                      {model.isActive ? null : (
                        <Button
                          size="sm"
                          // 一次只有一个激活请求在飞，所以用同一个 pending 状态禁掉所有行的这个按钮。
                          disabled={activateModel.isPending}
                          aria-label={t('settings.model.action.activate', { name: model.label })}
                          onClick={() => {
                            handleActivate(model);
                          }}
                        >
                          {t('settings.model.activate')}
                        </Button>
                      )}

                      <Button
                        size="sm"
                        aria-label={t('settings.model.action.remove', { name: model.label })}
                        onClick={() => {
                          setDeleteTarget(model);
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
      ) : (
        <>
          <div className={styles.sectionHead}>
            <h3 className={styles.sectionTitle}>{t('settings.model.detail.title')}</h3>
          </div>
          <ModelDetailView
            model={viewing}
            onBack={() => {
              setViewing(null);
            }}
            onEdit={() => {
              editFromDetail(viewing);
            }}
          />
        </>
      )}

      {/*
       * 接入卡只在浏览态（列表 / 详情）出现：它是一个"怎么接"的说明，
       * 与"正在改这条配置"是两件事，挤在表单下面只会把表单的保存按钮推得更远。
       */}
      {formOpen ? null : <ModuleAccessCard />}

      {deleteTarget === null ? null : (
        <ConfirmDelete
          title={t('settings.form.deleteConfirmTitle')}
          message={
            deleteTarget.isActive
              ? // 删的是当前生效的那个：补一句后果（不会自动切换到别的模型）。
                `${t('settings.form.deleteConfirmMessage', { name: deleteTarget.label })} ${t('settings.model.deleteActiveWarning')}`
              : t('settings.form.deleteConfirmMessage', { name: deleteTarget.label })
          }
          confirmLabel={t('settings.form.delete')}
          cancelLabel={t('settings.form.cancel')}
          closeLabel={t('settings.close')}
          pending={deleteModel.isPending}
          onConfirm={handleDelete}
          onCancel={() => {
            setDeleteTarget(null);
          }}
        />
      )}
    </div>
  );
}
