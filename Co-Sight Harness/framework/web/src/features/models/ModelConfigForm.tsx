/**
 * 模型配置表单（新增与编辑共用一份）。
 *
 * 共用而不是两份：两者字段完全相同，差别只有"初值从哪来"和"提交到哪个接口"，
 * 后者由面板决定（表单只把草稿交出去）。分成两个组件的话，加一个字段要改两处，
 * 而漏改的那一处通常要等到"编辑时这个新字段被清空了"才会被发现。
 *
 * 表单**内联**在设置面板里展开，不起二级弹窗。三条理由，按重要程度：
 *
 * 1. 二级弹窗会嵌套两层焦点陷阱。外层 `Dialog` 用 `panel.querySelectorAll(...)` 算
 *    自己的 Tab 序列，它会穿过嵌套的弹窗，把内层最后一个按钮当成自己的末项，
 *    于是从那里按 Tab 焦点会被丢到被遮罩挡住的外层关闭按钮上；
 * 2. 设置弹窗本身只有 720px，再压一个 720px 的弹窗，视觉上像渲染错误；
 * 3. 也不把表单**追加在列表下方**：十几个字段会把内容区拉得很长，而滚动容器在
 *    `Dialog` 内部的 `.content` 上、不归这里控制，用户点完「编辑」很可能看不到
 *    表单的第一行。表单直接顶掉列表，取消再换回来。
 *
 * 代价是 Esc 会关掉整个设置弹窗（等同于点「取消」，表单里没保存的内容随之丢失）。
 * 这一点由「取消」按钮兜住：表单始终在视野内，用户不会被一个看不见的"返回"卡住。
 */

import { useRef, useState, type FormEvent } from 'react';
import type { ModelConfig } from 'harness-shared';

import type { MessageKey } from '../../i18n/types';
import { useI18n } from '../../i18n/useI18n';
import { Button } from '../../components/ui/Button';
import { FormActions } from '../../components/ui/form/FormActions';
import { SelectField } from '../../components/ui/form/SelectField';
import { SwitchField } from '../../components/ui/form/SwitchField';
import { TextField } from '../../components/ui/form/TextField';
import formStyles from '../../components/ui/form/form.module.css';
import { cn } from '../../lib/cn';
// eslint-disable-next-line import/no-unresolved -- CSS Modules 由 Vite 解析
import { hasIssues, reportIssues, useIssueReporter, type FieldIssues, type IssueMessageKeys } from '../config/issues';
import { SecretInput } from '../config/SecretInput';
import panelStyles from '../config/config.module.css';
import {
  ADVANCED_MODEL_FIELDS,
  EDITABLE_PROVIDER_KINDS,
  MODEL_NUMBER_LIMITS,
  draftFromModel,
  emptyModelDraft,
  validateModelDraft,
  type ModelDraft,
  type ModelField,
} from './modelForm';

/**
 * 字段的本地化名，用于拼错误文案（"请填写名称"里的"名称"由这里来）。
 *
 * 与界面上的标签共用同一批词条，而不是另写一份"用于报错的字段名"：两处各写一份的话，
 * 改了标签忘了改报错，用户就会看到"请填写全名"指向一个叫"名称"的输入框。
 */
const FIELD_LABELS: Record<ModelField, MessageKey> = {
  label: 'settings.model.field.label',
  modelName: 'settings.model.field.modelName',
  baseUrl: 'settings.model.field.baseUrl',
  apiKey: 'settings.model.field.apiKey',
  temperature: 'settings.model.advanced.temperature',
  topP: 'settings.model.advanced.topP',
  maxOutputTokens: 'settings.model.advanced.maxOutputTokens',
  contextWindow: 'settings.model.advanced.contextWindow',
  timeoutSeconds: 'settings.model.advanced.timeoutSeconds',
};

const ISSUE_MESSAGES: IssueMessageKeys = {
  range: 'settings.model.invalidRange',
  tooLong: 'settings.model.invalidLength',
};

/** 输入框 id 固定写死（同屏只会有一份表单），便于测试与人工核对 label 的指向。 */
const ID = {
  provider: 'model-form-provider',
  label: 'model-form-label',
  modelName: 'model-form-model-name',
  baseUrl: 'model-form-base-url',
  apiKey: 'model-form-api-key',
  isActive: 'model-form-is-active',
  temperature: 'model-form-temperature',
  topP: 'model-form-top-p',
  maxOutputTokens: 'model-form-max-output-tokens',
  contextWindow: 'model-form-context-window',
  timeoutSeconds: 'model-form-timeout-seconds',
};

export interface ModelConfigFormProps {
  /** 编辑的那一条；新建时为 `null`。 */
  model: ModelConfig | null;
  /**
   * 新建时「设为当前使用」的初始状态：面板发现**当前没有任何生效模型**时传 `true`。
   *
   * 首次配置（或所有模型都被停用）时，新建的这条就是平台唯一的候选，默认打开
   * 省掉"保存完还得再点一次「设为当前使用」"这一步；已有生效模型时为 `false`，
   * 不悄悄顶掉用户正在用的那条。开关仍然可手动切换。
   */
  defaultActive?: boolean;
  /** 提交中：按钮禁用、文案换成"保存中…"。 */
  pending: boolean;
  onSubmit: (draft: ModelDraft) => void;
  onCancel: () => void;
}

export function ModelConfigForm({
  model,
  defaultActive = false,
  pending,
  onSubmit,
  onCancel,
}: ModelConfigFormProps) {
  const { t } = useI18n();
  const report = useIssueReporter(ISSUE_MESSAGES);

  /*
   * 初值只在**挂载时**算一次。面板打开表单时就把"在编辑哪一条"定死了，之后不会中途
   * 换对象；跟着 props 走的话，列表刷新（每次保存后都会失效重取）会让用户正在敲的
   * 内容被服务端的旧值覆盖回一半。
   *
   * `defaultActive` 同理：列表首次加载完成与否会改变它，跟着变会让用户眼前的开关
   * 自己跳一下。编辑态下用 `draftFromModel`，这个入参不参与。
   */
  const [draft, setDraft] = useState<ModelDraft>(() =>
    model === null ? emptyModelDraft({ isActive: defaultActive }) : draftFromModel(model),
  );
  const [errors, setErrors] = useState<FieldIssues<ModelField>>({});

  /*
   * 「推理参数」那一节，用来在提交失败时把它撑开（见 handleSubmit）。
   *
   * 这里**不引入一份 useState**：展开状态本来就是 DOM 自己的（`<details open>`），
   * 再用 state 镜像一遍就得处理"用户点开、React 又拿旧 state 把它合上"这类同步问题。
   * 需要读的时候直接读 DOM，是这里最省事也最不容易错的写法。
   */
  const advancedSection = useRef<HTMLDetailsElement>(null);

  /** 写值并清掉这一栏上一次的错误——那条错误说的是"上一次提交里这一栏不对"。 */
  function patch(next: Partial<ModelDraft>, field: ModelField): void {
    setDraft((current) => ({ ...current, ...next }));
    setErrors((current) => {
      if (current[field] === undefined) {
        // 引用不变：这里在没有错误可清时也要避免制造一次无谓的重渲染。
        return current;
      }
      const cleared = { ...current };
      delete cleared[field];
      return cleared;
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    // `<form>` 的默认提交会真的去导航（jsdom 里表现为一次未处理的提交），必须挡掉。
    event.preventDefault();

    const issues = validateModelDraft(draft);
    if (hasIssues(issues)) {
      /*
       * 错误若落在折起来的「推理参数」里，光挂上去等于没报——用户看不到任何红字，
       * 只觉得"点了保存没反应"。用户在收起状态下提交的唯一途径是"先改错、再合上"，
       * 但那恰恰是最需要被明确告知的一次操作。所以这里主动撑开它。
       */
      if (ADVANCED_MODEL_FIELDS.some((field) => issues[field] !== undefined)) {
        if (advancedSection.current !== null) {
          advancedSection.current.open = true;
        }
      }
      setErrors(reportIssues(issues, report, (field) => t(FIELD_LABELS[field])));
      // 校验不通过就到此为止：一个必然被服务端驳回的请求不该发出去。
      return;
    }

    setErrors({});
    onSubmit(draft);
  }

  const isEditing = model !== null;

  return (
    <form className={panelStyles.form} noValidate onSubmit={handleSubmit}>
      {/*
        单列（`stacked`）：模型表单每一栏的内容都偏长（网关地址、模型标识、密钥），
        并排两列会把它们各切一半，"一行一个输入框"反而更好扫。见 `form.module.css`。
      */}
      <div className={cn(formStyles.grid, formStyles.stacked)}>
        <SelectField
          id={ID.provider}
          label={t('settings.model.field.provider')}
          hint={t('settings.model.field.providerHint')}
          value={draft.provider}
          onChange={(value) => {
            // 值受限于可选项清单，`SelectField` 的 value 是 string；这里收窄回枚举成员。
            const provider = EDITABLE_PROVIDER_KINDS.find((kind) => kind === value);
            if (provider !== undefined) {
              setDraft((current) => ({ ...current, provider }));
            }
          }}
          // 选项只取表单允许的清单（当前仅 Anthropic），不直接照抄契约枚举。
          options={EDITABLE_PROVIDER_KINDS.map((provider) => ({
            value: provider,
            label: t(`settings.model.provider.${provider}`),
          }))}
          disabled={pending}
        />

        <TextField
          id={ID.label}
          label={t('settings.model.field.label')}
          placeholder={t('settings.model.field.labelPlaceholder')}
          value={draft.label}
          onChange={(value) => {
            patch({ label: value }, 'label');
          }}
          error={errors.label}
          required
          disabled={pending}
        />

        <TextField
          id={ID.modelName}
          label={t('settings.model.field.modelName')}
          placeholder={t('settings.model.field.modelNamePlaceholder')}
          hint={t('settings.model.field.modelNameHint')}
          value={draft.modelName}
          onChange={(value) => {
            patch({ modelName: value }, 'modelName');
          }}
          error={errors.modelName}
          required
          disabled={pending}
        />

        <TextField
          id={ID.baseUrl}
          type="url"
          label={t('settings.model.field.baseUrl')}
          placeholder={t('settings.model.field.baseUrlPlaceholder')}
          hint={t('settings.model.field.baseUrlHint')}
          value={draft.baseUrl}
          onChange={(value) => {
            patch({ baseUrl: value }, 'baseUrl');
          }}
          error={errors.baseUrl}
          disabled={pending}
        />

        <SecretInput
          id={ID.apiKey}
          label={t('settings.model.field.apiKey')}
          labels={{
            set: t('settings.model.field.apiKeySet'),
            unset: t('settings.model.field.apiKeyUnset'),
            clear: t('settings.model.field.clearKey'),
            clearPending: t('settings.model.field.clearKeyPending'),
          }}
          draft={draft.secret}
          onChange={(secret) => {
            patch({ secret }, 'apiKey');
          }}
          // 编辑态才谈得上"已配置"；新建时永远按"尚未配置"提示。
          configured={isEditing && model.hasApiKey}
          disabled={pending}
          error={errors.apiKey}
        />

        <SwitchField
          id={ID.isActive}
          label={t('settings.model.advanced.isActive')}
          hint={t('settings.model.advanced.isActiveHint')}
          checked={draft.isActive}
          onChange={(checked) => {
            setDraft((current) => ({ ...current, isActive: checked }));
          }}
          disabled={pending}
        />
      </div>

      {/*
        推理参数默认收起：这五个值绝大多数人不动，摊开来会把「保存」推出一屏，
        而它们又不像上面几栏那样"必须填"。`<details>` 不带 `open` 就是收起。
        `<summary>` 后面那句说明解释了为什么可以不管它——只留一个标题的话，
        收起更像"还有东西没填完"。
      */}
      <details className={panelStyles.disclosure} ref={advancedSection}>
        <summary className={panelStyles.disclosureSummary}>
          {t('settings.model.advanced.title')}
          <span className={panelStyles.disclosureHint}>
            {t('settings.model.advanced.collapsedHint')}
          </span>
        </summary>
        {/*
          分组语义（`<fieldset>/<legend>`）保留在 `<details>` 里面：读屏软件在字段之间
          跳转时仍会念出"推理参数"。`<summary>` 已经把这个名字显示出来了，所以 legend
          只给读屏用，不能再画一遍。
        */}
        <fieldset className={panelStyles.group}>
          <legend className="visually-hidden">{t('settings.model.advanced.title')}</legend>
          <div className={cn(formStyles.grid, formStyles.stacked)}>
          <TextField
            id={ID.temperature}
            type="number"
            label={t('settings.model.advanced.temperature')}
            hint={t('settings.model.advanced.temperatureHint')}
            value={draft.temperature}
            onChange={(value) => {
              patch({ temperature: value }, 'temperature');
            }}
            error={errors.temperature}
            min={MODEL_NUMBER_LIMITS.temperature.min}
            max={MODEL_NUMBER_LIMITS.temperature.max}
            step={0.1}
            disabled={pending}
          />

          <TextField
            id={ID.topP}
            type="number"
            label={t('settings.model.advanced.topP')}
            hint={t('settings.model.advanced.topPHint')}
            value={draft.topP}
            onChange={(value) => {
              patch({ topP: value }, 'topP');
            }}
            error={errors.topP}
            min={MODEL_NUMBER_LIMITS.topP.min}
            max={MODEL_NUMBER_LIMITS.topP.max}
            step={0.1}
            disabled={pending}
          />

          <TextField
            id={ID.maxOutputTokens}
            type="number"
            label={t('settings.model.advanced.maxOutputTokens')}
            hint={t('settings.model.advanced.maxOutputTokensHint')}
            value={draft.maxOutputTokens}
            onChange={(value) => {
              patch({ maxOutputTokens: value }, 'maxOutputTokens');
            }}
            error={errors.maxOutputTokens}
            disabled={pending}
          />

          <TextField
            id={ID.contextWindow}
            type="number"
            label={t('settings.model.advanced.contextWindow')}
            hint={t('settings.model.advanced.contextWindowHint')}
            value={draft.contextWindow}
            onChange={(value) => {
              patch({ contextWindow: value }, 'contextWindow');
            }}
            error={errors.contextWindow}
            disabled={pending}
          />

          <TextField
            id={ID.timeoutSeconds}
            type="number"
            label={t('settings.model.advanced.timeoutSeconds')}
            value={draft.timeoutSeconds}
            onChange={(value) => {
              patch({ timeoutSeconds: value }, 'timeoutSeconds');
            }}
            error={errors.timeoutSeconds}
            min={MODEL_NUMBER_LIMITS.timeoutSeconds.min}
            max={MODEL_NUMBER_LIMITS.timeoutSeconds.max}
            disabled={pending}
          />
          </div>
        </fieldset>
      </details>

      <FormActions>
        <Button onClick={onCancel} disabled={pending}>
          {t('settings.form.cancel')}
        </Button>
        <Button type="submit" variant="primary" disabled={pending}>
          {pending ? t('settings.form.saving') : t('settings.form.save')}
        </Button>
      </FormActions>
    </form>
  );
}
