/**
 * 工作区的新建 / 编辑表单（需求 2.1）。
 *
 * 新建与编辑共用一份组件：字段、校验、脏检查完全一样，分成两份只会让"编辑时
 * 少校验了一个字段"这种差异出现，而它恰好是最不容易发现的。
 *
 * 表单自己持有字段状态，并**只把"是否脏"这一位**报给外面（`onDirtyChange`）：
 * 弹窗需要它来决定"关闭时要不要先问一句"，但它不需要知道用户敲了什么。
 */

import { absolutePathSchema, type CreateWorkspaceInput, type Workspace } from 'harness-shared';
import { useEffect, useState, type FormEvent } from 'react';

import { useAgentProxyList } from '../../api/agentProxies';
import { useModelList } from '../../api/models';
import { useApiErrorMessage } from '../../api/useApiErrorMessage';
import { usePickDirectory } from '../../api/workspaces';
import { useI18n } from '../../i18n/useI18n';
import { Button } from '../../components/ui/Button';
import { FormActions } from '../../components/ui/form/FormActions';
import { SelectField, type SelectOption } from '../../components/ui/form/SelectField';
import { TextField } from '../../components/ui/form/TextField';
import formStyles from '../../components/ui/form/form.module.css';

export interface WorkspaceFormProps {
  /** 编辑时的原值；新建时传 null。 */
  initial: Workspace | null;
  /** 提交中：按钮禁用，避免连点建出两个工作区。 */
  pending: boolean;
  /** 保存失败的原因（已翻译），显示在操作栏上方。字段级错误不在这里。 */
  error: string | null;
  onSubmit: (input: CreateWorkspaceInput) => void;
  onCancel: () => void;
  onDirtyChange: (dirty: boolean) => void;
}

interface FormValues {
  name: string;
  directory: string;
  /** 空串表示「跟随全局」；表单里不用 null，因为 `<select>` 的 value 只能是字符串。 */
  defaultModelId: string;
  defaultAgentId: string;
}

interface FieldErrors {
  name?: string;
  directory?: string;
}

/**
 * 「跟随全局」在 `<select>` 里必须有一个**非空**的 value。
 * 用 `''` 而不是 `'__global__'` 这类哨兵串：`''` 不可能与 uuid 撞车，
 * 而哨兵串一旦被谁当成 id 传出去，服务端只会回一个"参数校验未通过"。
 */
const FOLLOW_GLOBAL = '';

function toValues(initial: Workspace | null): FormValues {
  return {
    name: initial?.name ?? '',
    directory: initial?.directory ?? '',
    defaultModelId: initial?.defaultModelId ?? FOLLOW_GLOBAL,
    defaultAgentId: initial?.defaultAgentId ?? FOLLOW_GLOBAL,
  };
}

export function WorkspaceForm({
  initial,
  pending,
  error,
  onSubmit,
  onCancel,
  onDirtyChange,
}: WorkspaceFormProps) {
  const { t } = useI18n();
  const [values, setValues] = useState<FormValues>(() => toValues(initial));
  const [errors, setErrors] = useState<FieldErrors>({});

  const models = useModelList();
  const agents = useAgentProxyList();
  const pickDirectory = usePickDirectory();
  const describeError = useApiErrorMessage();
  /**
   * 目录选择器自己的失败**不塞进 `fields.directory`**：那会让输入框描红并带上
   * `aria-invalid`，而用户填的值一点问题也没有——坏的是"这台机器弹不出对话框"。
   * 两件事在同一行说出来就够，别让读屏用户以为自己的路径写错了。
   */
  const [pickError, setPickError] = useState<string | null>(null);

  const base = toValues(initial);
  const isDirty =
    values.name !== base.name ||
    values.directory !== base.directory ||
    values.defaultModelId !== base.defaultModelId ||
    values.defaultAgentId !== base.defaultAgentId;

  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  function setField<K extends keyof FormValues>(key: K, value: FormValues[K]): void {
    setValues((previous) => ({ ...previous, [key]: value }));
  }

  /**
   * 校验只拦"服务端一定会拒"的两件事：名称非空、目录是绝对路径。
   * 路径规则**直接复用契约里的 zod schema**，不在这里重写一遍正则——
   * 重写的那份迟早会与服务端放宽/收紧后的版本不一致，而表现是"前端放行、
   * 服务端 422"，最难查。
   */
  function validate(current: FormValues): FieldErrors {
    const next: FieldErrors = {};
    if (current.name.trim() === '') {
      next.name = t('settings.form.required', { field: t('workspace.field.name') });
    }
    const directory = current.directory.trim();
    if (directory !== '' && !absolutePathSchema.safeParse(directory).success) {
      next.directory = t('workspace.field.directoryInvalid');
    }
    return next;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const found = validate(values);
    setErrors(found);
    if (found.name !== undefined || found.directory !== undefined) {
      return;
    }
    const directory = values.directory.trim();
    onSubmit({
      name: values.name.trim(),
      directory: directory === '' ? null : directory,
      defaultModelId: values.defaultModelId === FOLLOW_GLOBAL ? null : values.defaultModelId,
      defaultAgentId: values.defaultAgentId === FOLLOW_GLOBAL ? null : values.defaultAgentId,
    });
  }

  /**
   * 打开系统目录选择器。
   *
   * 起点取输入框里已有的值：用户常常先手输了一半，或者想从同一个父目录里换个兄弟目录。
   * 取消（`path === null`）什么都不改——那是正常结果，不是失败。
   */
  function handlePick(): void {
    setPickError(null);
    const start = values.directory.trim();
    pickDirectory.mutate(start === '' ? null : start, {
      onSuccess: (result) => {
        if (result.path === null) {
          return;
        }
        setField('directory', result.path);
        // 选出来的路径一定是绝对路径，把上一次提交留下的"不是绝对路径"清掉，
        // 否则用户选了目录、输入框却还红着。
        setErrors((previous) => {
          const next = { ...previous };
          delete next.directory;
          return next;
        });
      },
      onError: (cause) => {
        setPickError(describeError(cause));
      },
    });
  }

  const modelOptions: SelectOption[] = [
    { value: FOLLOW_GLOBAL, label: t('workspace.followsGlobal') },
    ...(models.data ?? []).map((model) => ({ value: model.id, label: model.label })),
  ];
  const agentOptions: SelectOption[] = [
    { value: FOLLOW_GLOBAL, label: t('workspace.followsGlobal') },
    ...(agents.data ?? []).map((agent) => ({ value: agent.id, label: agent.name })),
  ];

  return (
    /*
     * noValidate：校验与提示口径全由这里出，不要浏览器再冒一份本地化的气泡。
     *
     * autoComplete="off"：浏览器会把**以前在这个框里敲过的值**列成下拉历史
     * （用户看到的就是"默认工作区"这四个字），而工作区名是一份配置、不是一次
     * 搜索。字段级也各自再写一遍：只写在 <form> 上有实现会忽略。
     */
    <form className={formStyles.grid} noValidate autoComplete="off" onSubmit={handleSubmit}>
      <TextField
        id="workspace-name"
        className={formStyles.wide}
        label={t('workspace.field.name')}
        value={values.name}
        onChange={(value) => {
          setField('name', value);
        }}
        placeholder={t('workspace.field.namePlaceholder')}
        autoComplete="off"
        required
        error={errors.name}
      />

      {/*
       * 目录与「选择目录」包在同一个栅格单元里：选择器自己的失败信息要贴着这一行，
       * 而不是漂到下一行去（见 `pickError` 的注释）。
       */}
      <div className={formStyles.wide}>
        <TextField
          id="workspace-directory"
          label={t('workspace.field.directory')}
          hint={t('workspace.field.directoryHint')}
          value={values.directory}
          onChange={(value) => {
            setField('directory', value);
          }}
          placeholder={t('workspace.field.directoryPlaceholder')}
          autoComplete="off"
          error={errors.directory}
          // 空框点一下就打开选择器：这是这个字段最常见的下一步。
          // 已经有值时只当作普通点击（继续手输/改），不然想微调路径的人每次都会被对话框拦住。
          onInputClick={() => {
            if (values.directory.trim() === '') {
              handlePick();
            }
          }}
          trailing={
            <Button
              variant="secondary"
              size="md"
              icon="workspace"
              disabled={pending || pickDirectory.isPending}
              onClick={handlePick}
            >
              {pickDirectory.isPending
                ? t('workspace.field.directoryPicking')
                : t('workspace.field.directoryPick')}
            </Button>
          }
        />
        {pickError === null ? null : (
          <p className={formStyles.error} role="alert">
            {pickError}
          </p>
        )}
      </div>

      <SelectField
        id="workspace-default-model"
        label={t('workspace.field.defaultModel')}
        hint={t('workspace.field.followGlobalHint')}
        value={values.defaultModelId}
        onChange={(value) => {
          setField('defaultModelId', value);
        }}
        options={modelOptions}
        disabled={models.isPending}
        // 选不到东西时把原因说出来（加载失败 / 还在加载），否则用户只会看到一个
        // 只有一个选项的下拉框，以为功能没做。
        {...(models.isError
          ? { error: t('settings.model.error.title') }
          : models.isPending
            ? { hint: t('settings.model.loading') }
            : {})}
      />

      <SelectField
        id="workspace-default-agent"
        label={t('workspace.field.defaultAgent')}
        hint={t('workspace.field.followGlobalHint')}
        value={values.defaultAgentId}
        onChange={(value) => {
          setField('defaultAgentId', value);
        }}
        options={agentOptions}
        disabled={agents.isPending}
        {...(agents.isError
          ? { error: t('settings.agentProxy.error.title') }
          : agents.isPending
            ? { hint: t('settings.agentProxy.loading') }
            : {})}
      />

      <div className={formStyles.wide}>
        {error === null ? null : (
          <p className={formStyles.error} role="alert">
            {error}
          </p>
        )}
        <FormActions>
          <Button variant="secondary" onClick={onCancel} disabled={pending}>
            {t('settings.form.cancel')}
          </Button>
          <Button type="submit" variant="primary" disabled={pending}>
            {pending ? t('settings.form.saving') : t('settings.form.save')}
          </Button>
        </FormActions>
      </div>
    </form>
  );
}
