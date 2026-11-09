/**
 * Agent 代理配置表单（只用于**编辑**已有的一条，新增入口已取消；表单位置的取舍见
 * `ModelConfigForm` 的开头）。
 *
 * 文件名里的 `Config` 不是修辞：同目录的纯逻辑模块叫 `agentProxyForm.ts`，
 * 两者主干只差大小写，而**大小写不敏感的文件系统（Windows/macOS）上
 * `import './AgentProxyForm'` 会先命中 `agentProxyForm.ts`**，报 TS2305
 * （Windows 上真实踩过的坑）。形状与 `features/models/` 的
 * `ModelConfigForm.tsx` + `modelForm.ts` 一致，守卫见
 * `server/tests/source-file-casing.test.ts`。改名时别把 `Config` 去掉。
 *
 * 分组照「用户此刻在想什么」切，不照契约的字段顺序切：先"这个代理是什么"
 * （名称、描述、类型、地址、令牌），再"它一次能跑多远"（运行与额度），
 * 最后是几个开关键。
 *
 * `extra` 只读块**放在表单里**而不是列表行上：它是这一条配置的一部分，
 * 贴近底部的操作栏，用户改完上面的字段顺手就能确认它没被动过。
 */

import { useState, type FormEvent } from 'react';
import { SECURITY_ANALYZERS, type AgentProxyConfig } from 'harness-shared';

import { useI18n } from '../../i18n/useI18n';
import type { MessageKey } from '../../i18n/types';
import { Button } from '../../components/ui/Button';
import { FormActions } from '../../components/ui/form/FormActions';
import { SelectField } from '../../components/ui/form/SelectField';
import { SwitchField } from '../../components/ui/form/SwitchField';
import { TextArea } from '../../components/ui/form/TextArea';
import { TextField } from '../../components/ui/form/TextField';
import formStyles from '../../components/ui/form/form.module.css';
import { hasIssues, reportIssues, useIssueReporter, type FieldIssues, type IssueMessageKeys } from '../config/issues';
import { SecretInput } from '../config/SecretInput';
import panelStyles from '../config/config.module.css';
import { ExtraReadonly } from './ExtraReadonly';
import {
  AGENT_PROXY_NUMBER_LIMITS,
  draftFromAgentProxy,
  validateAgentProxyDraft,
  type AgentProxyDraft,
  type AgentProxyField,
} from './agentProxyForm';

/** 字段的本地化名，用于拼错误文案；与界面标签共用同一批词条（理由见 `ModelConfigForm`）。 */
const FIELD_LABELS: Record<AgentProxyField, MessageKey> = {
  name: 'settings.agentProxy.field.name',
  description: 'settings.agentProxy.field.description',
  agentType: 'settings.agentProxy.field.agentType',
  endpoint: 'settings.agentProxy.field.endpoint',
  token: 'settings.agentProxy.field.token',
  maxIterations: 'settings.agentProxy.runtime.maxIterations',
  parallelism: 'settings.agentProxy.runtime.parallelism',
  timeoutSeconds: 'settings.agentProxy.runtime.timeoutSeconds',
};

const ISSUE_MESSAGES: IssueMessageKeys = {
  range: 'settings.agentProxy.invalidRange',
  tooLong: 'settings.agentProxy.invalidLength',
};

const ID = {
  name: 'agent-proxy-form-name',
  description: 'agent-proxy-form-description',
  agentType: 'agent-proxy-form-agent-type',
  endpoint: 'agent-proxy-form-endpoint',
  token: 'agent-proxy-form-token',
  maxIterations: 'agent-proxy-form-max-iterations',
  parallelism: 'agent-proxy-form-parallelism',
  timeoutSeconds: 'agent-proxy-form-timeout-seconds',
  enabled: 'agent-proxy-form-enabled',
  isDefault: 'agent-proxy-form-is-default',
  memoryEnabled: 'agent-proxy-form-memory-enabled',
  condensationEnabled: 'agent-proxy-form-condensation-enabled',
  securityAnalyzer: 'agent-proxy-form-security-analyzer',
};

export interface AgentProxyConfigFormProps {
  /** 正在编辑的那一条。没有"新建"形态（新增入口已取消），所以不可为空。 */
  proxy: AgentProxyConfig;
  /** 提交中：按钮禁用、文案换成"保存中…"。 */
  pending: boolean;
  onSubmit: (draft: AgentProxyDraft) => void;
  onCancel: () => void;
}

export function AgentProxyConfigForm({
  proxy,
  pending,
  onSubmit,
  onCancel,
}: AgentProxyConfigFormProps) {
  const { t } = useI18n();
  const report = useIssueReporter(ISSUE_MESSAGES);

  // 初值只在挂载时算一次（理由同 `ModelConfigForm`：列表刷新不该覆盖正在敲的内容）。
  const [draft, setDraft] = useState<AgentProxyDraft>(() => draftFromAgentProxy(proxy));
  const [errors, setErrors] = useState<FieldIssues<AgentProxyField>>({});

  /** 写值并清掉这一栏上一次的错误。 */
  function patch(next: Partial<AgentProxyDraft>, field: AgentProxyField | null): void {
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

    const issues = validateAgentProxyDraft(draft);
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
          label={t('settings.agentProxy.field.name')}
          placeholder={t('settings.agentProxy.field.namePlaceholder')}
          value={draft.name}
          onChange={(value) => {
            patch({ name: value }, 'name');
          }}
          error={errors.name}
          required
          disabled={pending}
        />

        <TextField
          id={ID.agentType}
          label={t('settings.agentProxy.field.agentType')}
          hint={t('settings.agentProxy.field.agentTypeHint')}
          value={draft.agentType}
          onChange={(value) => {
            patch({ agentType: value }, 'agentType');
          }}
          error={errors.agentType}
          required
          disabled={pending}
        />

        <TextArea
          id={ID.description}
          label={t('settings.agentProxy.field.description')}
          placeholder={t('settings.agentProxy.field.descriptionPlaceholder')}
          value={draft.description}
          onChange={(value) => {
            patch({ description: value }, 'description');
          }}
          error={errors.description}
          disabled={pending}
          className={formStyles.wide}
        />

        <TextField
          id={ID.endpoint}
          type="url"
          label={t('settings.agentProxy.field.endpoint')}
          placeholder={t('settings.agentProxy.field.endpointPlaceholder')}
          hint={t('settings.agentProxy.field.endpointHint')}
          value={draft.endpoint}
          onChange={(value) => {
            patch({ endpoint: value }, 'endpoint');
          }}
          error={errors.endpoint}
          disabled={pending}
          className={formStyles.wide}
        />

        <SecretInput
          id={ID.token}
          label={t('settings.agentProxy.field.token')}
          labels={{
            set: t('settings.agentProxy.field.tokenSet'),
            unset: t('settings.agentProxy.field.tokenUnset'),
            clear: t('settings.agentProxy.field.clearToken'),
            clearPending: t('settings.agentProxy.field.clearTokenPending'),
          }}
          draft={draft.token}
          onChange={(token) => {
            patch({ token }, 'token');
          }}
          // 令牌只写不读（D26）：只有"已配置 / 尚未配置"这一位，明文永远回不来。
          configured={proxy.hasToken}
          disabled={pending}
          error={errors.token}
          className={formStyles.wide}
        />
      </div>

      <fieldset className={panelStyles.group}>
        <legend className={panelStyles.groupTitle}>{t('settings.agentProxy.runtime.title')}</legend>
        <div className={formStyles.grid}>
          <TextField
            id={ID.maxIterations}
            type="number"
            label={t('settings.agentProxy.runtime.maxIterations')}
            hint={t('settings.agentProxy.runtime.maxIterationsHint')}
            value={draft.maxIterations}
            onChange={(value) => {
              patch({ maxIterations: value }, 'maxIterations');
            }}
            error={errors.maxIterations}
            min={AGENT_PROXY_NUMBER_LIMITS.maxIterations.min}
            max={AGENT_PROXY_NUMBER_LIMITS.maxIterations.max}
            disabled={pending}
          />

          <TextField
            id={ID.parallelism}
            type="number"
            label={t('settings.agentProxy.runtime.parallelism')}
            hint={t('settings.agentProxy.runtime.parallelismHint')}
            value={draft.parallelism}
            onChange={(value) => {
              patch({ parallelism: value }, 'parallelism');
            }}
            error={errors.parallelism}
            min={AGENT_PROXY_NUMBER_LIMITS.parallelism.min}
            max={AGENT_PROXY_NUMBER_LIMITS.parallelism.max}
            disabled={pending}
          />

          <TextField
            id={ID.timeoutSeconds}
            type="number"
            label={t('settings.agentProxy.runtime.timeoutSeconds')}
            hint={t('settings.agentProxy.runtime.timeoutSecondsHint')}
            value={draft.timeoutSeconds}
            onChange={(value) => {
              patch({ timeoutSeconds: value }, 'timeoutSeconds');
            }}
            error={errors.timeoutSeconds}
            min={AGENT_PROXY_NUMBER_LIMITS.timeoutSeconds.min}
            max={AGENT_PROXY_NUMBER_LIMITS.timeoutSeconds.max}
            disabled={pending}
          />
        </div>
      </fieldset>

      <fieldset className={panelStyles.group}>
        <legend className={panelStyles.groupTitle}>{t('settings.agentProxy.switches.title')}</legend>
        <div className={formStyles.grid}>
          <SwitchField
            id={ID.enabled}
            label={t('settings.agentProxy.switches.enabled')}
            hint={t('settings.agentProxy.switches.enabledHint')}
            checked={draft.enabled}
            onChange={(checked) => {
              patch({ enabled: checked }, null);
            }}
            disabled={pending}
          />

          <SwitchField
            id={ID.isDefault}
            label={t('settings.agentProxy.switches.isDefault')}
            hint={t('settings.agentProxy.switches.isDefaultHint')}
            checked={draft.isDefault}
            onChange={(checked) => {
              patch({ isDefault: checked }, null);
            }}
            disabled={pending}
          />

          <SwitchField
            id={ID.memoryEnabled}
            label={t('settings.agentProxy.switches.memoryEnabled')}
            checked={draft.memoryEnabled}
            onChange={(checked) => {
              patch({ memoryEnabled: checked }, null);
            }}
            disabled={pending}
          />

          <SwitchField
            id={ID.condensationEnabled}
            label={t('settings.agentProxy.switches.condensationEnabled')}
            checked={draft.condensationEnabled}
            onChange={(checked) => {
              patch({ condensationEnabled: checked }, null);
            }}
            disabled={pending}
          />

          <SelectField
            id={ID.securityAnalyzer}
            label={t('settings.agentProxy.switches.securityAnalyzer')}
            hint={t('settings.agentProxy.switches.securityAnalyzerHint')}
            value={draft.securityAnalyzer}
            onChange={(value) => {
              // 值是契约枚举，`SelectField` 的 value 是 string；这里收窄回枚举成员。
              const analyzer = SECURITY_ANALYZERS.find((kind) => kind === value);
              if (analyzer !== undefined) {
                patch({ securityAnalyzer: analyzer }, null);
              }
            }}
            // 选项顺序照契约枚举走（`SECURITY_ANALYZERS`），不另排一份。
            options={SECURITY_ANALYZERS.map((analyzer) => ({
              value: analyzer,
              label: t(`settings.agentProxy.analyzer.${analyzer}`),
            }))}
            disabled={pending}
          />
        </div>
      </fieldset>

      {/* 没有模块私有配置时，`ExtraReadonly` 自己会整块不渲染。 */}
      <ExtraReadonly extra={proxy.extra} />

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
