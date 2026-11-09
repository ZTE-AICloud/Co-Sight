/**
 * RAG 知识库表单（新增与编辑共用一份）。
 *
 * 文件名里的 `Config` 不是修辞：同目录的纯逻辑模块叫 `ragKnowledgeForm.ts`，
 * 两者主干只差大小写，而**大小写不敏感的文件系统（Windows/macOS）上
 * `import './RagKnowledgeForm'` 会先命中 `ragKnowledgeForm.ts`**，报 TS2305。
 * 形状与 `features/agent-proxies/` 的 `AgentProxyConfigForm.tsx` + `agentProxyForm.ts`
 * 一致，守卫见 `server/tests/source-file-casing.test.ts`。改名时别把 `Config` 去掉。
 *
 * 与代理表单的一处**刻意的不同**：生效开关只在新建时出现。编辑一条已有记录时，
 * 切换可用项是列表行上的独立动作（`POST /:id/activate`），而 `PATCH` 不带 `isActive`
 * ——表单里放一个改了也不生效的开关，比不放更糟。
 */

import { useState, type FormEvent } from 'react';
import type { RagKnowledgeBase } from 'harness-shared';

import { useRagKnowledgeDefaults } from '../../api/ragKnowledge';
import { useI18n } from '../../i18n/useI18n';
import type { MessageKey } from '../../i18n/types';
import { Button } from '../../components/ui/Button';
import { FormActions } from '../../components/ui/form/FormActions';
import { SwitchField } from '../../components/ui/form/SwitchField';
import { TextArea } from '../../components/ui/form/TextArea';
import { TextField } from '../../components/ui/form/TextField';
import formStyles from '../../components/ui/form/form.module.css';
import {
  hasIssues,
  reportIssues,
  useIssueReporter,
  type FieldIssues,
  type IssueMessageKeys,
} from '../config/issues';
import { SecretInput } from '../config/SecretInput';
import panelStyles from '../config/config.module.css';
import {
  draftFromRagKnowledge,
  emptyRagKnowledgeDraft,
  validateRagKnowledgeDraft,
  type RagKnowledgeDraft,
  type RagKnowledgeField,
} from './ragKnowledgeForm';

/** 字段的本地化名，用于拼错误文案；与界面标签共用同一批词条（理由同模型表单）。 */
const FIELD_LABELS: Record<RagKnowledgeField, MessageKey> = {
  name: 'settings.ragKnowledge.field.name',
  routeUrl: 'settings.ragKnowledge.field.routeUrl',
  username: 'settings.ragKnowledge.field.username',
  password: 'settings.ragKnowledge.field.password',
  apiKey: 'settings.ragKnowledge.field.apiKey',
  description: 'settings.ragKnowledge.field.description',
};

const ISSUE_MESSAGES: IssueMessageKeys = {
  range: 'settings.ragKnowledge.invalidRange',
  tooLong: 'settings.ragKnowledge.invalidLength',
};

const ID = {
  name: 'rag-knowledge-form-name',
  routeUrl: 'rag-knowledge-form-route-url',
  username: 'rag-knowledge-form-username',
  password: 'rag-knowledge-form-password',
  apiKey: 'rag-knowledge-form-api-key',
  description: 'rag-knowledge-form-description',
  isActive: 'rag-knowledge-form-is-active',
};

export interface RagKnowledgeConfigFormProps {
  /** 编辑的那一条；新建时为 `null`。 */
  base: RagKnowledgeBase | null;
  /**
   * 新建时「设为可用」的初始值（编辑态忽略）。
   *
   * 从侧栏「知识库」进来时传 `true`：那条路径本来就只在"没有任何可用路由"时出现，
   * 用户要的就是补上能用的那一条。面板里主动点「新增」时仍默认 `false`——那可能
   * 只是先存个地址，替用户激活会悄悄换掉正在用的那条。
   */
  defaultActive?: boolean;
  /** 提交中：按钮禁用、文案换成"保存中…"。 */
  pending: boolean;
  onSubmit: (draft: RagKnowledgeDraft) => void;
  onCancel: () => void;
}

export function RagKnowledgeConfigForm({
  base,
  defaultActive = false,
  pending,
  onSubmit,
  onCancel,
}: RagKnowledgeConfigFormProps) {
  const { t } = useI18n();
  const report = useIssueReporter(ISSUE_MESSAGES);
  /*
   * 只用来把"留空会怎样"说准：服务端配了默认密钥时，留空不是"不设置"，
   * 而是"用默认那一枚"。查询失败按没有默认处理——那只会让提示语退回通用说法，
   * 不影响保存。
   */
  const defaults = useRagKnowledgeDefaults();
  const hasDefaultApiKey = defaults.data?.hasDefaultApiKey === true;

  // 初值只在挂载时算一次（理由同模型表单：列表刷新不该覆盖正在敲的内容）。
  const [draft, setDraft] = useState<RagKnowledgeDraft>(() =>
    base === null
      ? { ...emptyRagKnowledgeDraft(), isActive: defaultActive }
      : draftFromRagKnowledge(base),
  );
  const [errors, setErrors] = useState<FieldIssues<RagKnowledgeField>>({});

  /** 写值并清掉这一栏上一次的错误。 */
  function patch(next: Partial<RagKnowledgeDraft>, field: RagKnowledgeField | null): void {
    setDraft((current) => ({ ...current, ...next }));
    if (field === null) {
      return;
    }
    setErrors((current) => {
      if (current[field] === undefined) {
        // 引用不变：没有错误可清时不为一次无谓的重渲染换对象。
        return current;
      }
      const cleared = { ...current };
      delete cleared[field];
      return cleared;
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    // 挡掉 `<form>` 的默认提交（它会真的导航）。
    event.preventDefault();

    const issues = validateRagKnowledgeDraft(draft);
    if (hasIssues(issues)) {
      setErrors(reportIssues(issues, report, (field) => t(FIELD_LABELS[field])));
      return;
    }

    setErrors({});
    onSubmit(draft);
  }

  return (
    <form className={panelStyles.form} noValidate onSubmit={handleSubmit}>
      <div className={formStyles.grid}>
        <TextField
          id={ID.name}
          label={t('settings.ragKnowledge.field.name')}
          placeholder={t('settings.ragKnowledge.field.namePlaceholder')}
          value={draft.name}
          onChange={(value) => {
            patch({ name: value }, 'name');
          }}
          error={errors.name}
          required
          disabled={pending}
        />

        <TextField
          id={ID.routeUrl}
          type="url"
          label={t('settings.ragKnowledge.field.routeUrl')}
          placeholder={t('settings.ragKnowledge.field.routeUrlPlaceholder')}
          hint={t('settings.ragKnowledge.field.routeUrlHint')}
          value={draft.routeUrl}
          onChange={(value) => {
            patch({ routeUrl: value }, 'routeUrl');
          }}
          error={errors.routeUrl}
          required
          disabled={pending}
          className={formStyles.wide}
        />

        {/*
         * 账号密码是"打开这个地址时用什么身份"，与地址本身并列，不塞进 URL。
         * 两栏各占一行（`wide`）：并排放时，密码框的"已配置 / 清除"按钮和账号的提示语
         * 会挤在同一行里互相打架，也容易把账号敲进相邻的密码栏。
         */}
        <TextField
          id={ID.username}
          label={t('settings.ragKnowledge.field.username')}
          placeholder={t('settings.ragKnowledge.field.usernamePlaceholder')}
          hint={t('settings.ragKnowledge.field.usernameHint')}
          value={draft.username}
          onChange={(value) => {
            patch({ username: value }, 'username');
          }}
          error={errors.username}
          disabled={pending}
          className={formStyles.wide}
        />

        <SecretInput
          id={ID.password}
          label={t('settings.ragKnowledge.field.password')}
          labels={{
            set: t('settings.ragKnowledge.field.passwordSet'),
            unset: t('settings.ragKnowledge.field.passwordUnset'),
            clear: t('settings.ragKnowledge.field.clearPassword'),
            clearPending: t('settings.ragKnowledge.field.clearPasswordPending'),
          }}
          draft={draft.password}
          onChange={(password) => {
            patch({ password }, 'password');
          }}
          // 编辑态才谈得上"已配置"；新建时永远按"尚未配置"提示。
          configured={base !== null && base.hasPassword}
          disabled={pending}
          error={errors.password}
          className={formStyles.wide}
        />

        {/*
         * API Key 与密码不同：它是给**模块**调知识服务用的，不是登录网页用的。
         * 服务端可以用环境变量预置一枚默认密钥，因此"留空"有两种含义，
         * 提示语得看 `hasDefaultApiKey` 才能说准（见 `apiKeyUnsetDefault`）。
         */}
        <SecretInput
          id={ID.apiKey}
          label={t('settings.ragKnowledge.field.apiKey')}
          labels={{
            set: t('settings.ragKnowledge.field.apiKeySet'),
            unset: hasDefaultApiKey
              ? t('settings.ragKnowledge.field.apiKeyUnsetDefault')
              : t('settings.ragKnowledge.field.apiKeyUnset'),
            clear: t('settings.ragKnowledge.field.clearApiKey'),
            clearPending: t('settings.ragKnowledge.field.clearApiKeyPending'),
          }}
          hint={t('settings.ragKnowledge.field.apiKeyHint')}
          draft={draft.apiKey}
          onChange={(apiKey) => {
            patch({ apiKey }, 'apiKey');
          }}
          configured={base !== null && base.hasApiKey}
          disabled={pending}
          error={errors.apiKey}
          className={formStyles.wide}
        />

        <TextArea
          id={ID.description}
          label={t('settings.ragKnowledge.field.description')}
          placeholder={t('settings.ragKnowledge.field.descriptionPlaceholder')}
          value={draft.description}
          onChange={(value) => {
            patch({ description: value }, 'description');
          }}
          error={errors.description}
          disabled={pending}
          className={formStyles.wide}
        />
      </div>

      {/* 编辑态不显示开关：`PATCH` 不改 `isActive`，切换在列表行上（见文件头）。 */}
      {base === null ? (
        <div className={formStyles.grid}>
          <SwitchField
            id={ID.isActive}
            label={t('settings.ragKnowledge.field.isActive')}
            hint={t('settings.ragKnowledge.field.isActiveHint')}
            checked={draft.isActive}
            onChange={(checked) => {
              patch({ isActive: checked }, null);
            }}
            disabled={pending}
          />
        </div>
      ) : null}

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
