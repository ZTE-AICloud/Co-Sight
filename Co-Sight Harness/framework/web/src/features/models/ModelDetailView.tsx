/**
 * 模型只读详情。
 *
 * 在这之前，"这条模型配了什么"只有一个入口——点「编辑」进表单。那有两个问题：
 * 表单里每个字段都带着输入框和提示语，看一列值要在十几个控件之间找；而且**只读的
 * 查看会连带把状态切成"正在编辑"**，用户看完不点「取消」就离开时，面板还停在一个
 * 未保存的表单上。
 *
 * 所以详情与列表、表单三者互斥（同一个 `viewing` / `editing` / `creating` 状态机）。
 *
 * 密钥一栏只说"是否已配置"：明文从不回传到浏览器（D26），这是浏览器面的硬契约，
 * 详情视图不例外。想换密钥就进编辑表单重新填一个。
 */

import type { ModelConfig } from 'harness-shared';

import { formatDateTime } from '../../lib/formatDateTime';
import { useI18n } from '../../i18n/useI18n';
import { Button } from '../../components/ui/Button';
import { Tag } from '../../components/ui/Tag';
import styles from '../config/config.module.css';

export interface ModelDetailViewProps {
  model: ModelConfig;
  onBack: () => void;
  onEdit: () => void;
}

/** 一个"术语 → 值"行。空值统一显示为一个不含歧义的占位符。 */
function Field({ term, value }: { term: string; value: string }) {
  return (
    <>
      <dt className={styles.extraTerm}>{term}</dt>
      <dd className={styles.extraValue}>{value}</dd>
    </>
  );
}

export function ModelDetailView({ model, onBack, onEdit }: ModelDetailViewProps) {
  const { t, locale } = useI18n();

  /** 数值型的可空字段：留空表示"跟随默认"，不该显示成 `null`。 */
  const orUnset = (value: number | null): string =>
    value === null ? t('settings.model.detail.unset') : String(value);
  const orUnlimited = (value: number | null): string =>
    value === null ? t('settings.model.detail.unlimited') : String(value);

  const createdAt = formatDateTime(model.createdAt, locale);
  const updatedAt = formatDateTime(model.updatedAt, locale);

  return (
    <div className={styles.detail}>
      <div className={styles.detailHead}>
        <span className={styles.detailTitle} title={model.label}>
          {model.label}
        </span>
        {model.isActive ? <Tag tone="brand">{t('settings.model.activeBadge')}</Tag> : null}
      </div>

      <dl className={styles.extraList}>
        <Field term={t('settings.model.field.provider')} value={t(`settings.model.provider.${model.provider}`)} />
        <Field term={t('settings.model.field.modelName')} value={model.modelName} />
        <Field term={t('settings.model.field.baseUrl')} value={model.baseUrl ?? t('settings.model.baseUrlDefault')} />
        <Field
          term={t('settings.model.field.apiKey')}
          value={model.hasApiKey ? t('settings.model.keyConfigured') : t('settings.model.keyMissing')}
        />

        <Field term={t('settings.model.advanced.temperature')} value={String(model.temperature)} />
        <Field term={t('settings.model.advanced.topP')} value={String(model.topP)} />
        <Field term={t('settings.model.advanced.maxOutputTokens')} value={orUnlimited(model.maxOutputTokens)} />
        <Field term={t('settings.model.advanced.contextWindow')} value={orUnset(model.contextWindow)} />
        <Field term={t('settings.model.advanced.timeoutSeconds')} value={String(model.timeoutSeconds)} />

        {/*
         * 时间用 `<time dateTime>`：值是给人看的本地时间，`dateTime` 属性放回机器可读的
         * ISO 串。`title` 再补一次原始值——复现问题时人想复制的是原始时间戳。
         */}
        <dt className={styles.extraTerm}>{t('settings.model.detail.createdAt')}</dt>
        <dd className={styles.extraValue}>
          {createdAt === null ? (
            t('settings.model.detail.unset')
          ) : (
            <time dateTime={model.createdAt} title={model.createdAt}>
              {createdAt}
            </time>
          )}
        </dd>

        <dt className={styles.extraTerm}>{t('settings.model.detail.updatedAt')}</dt>
        <dd className={styles.extraValue}>
          {updatedAt === null ? (
            t('settings.model.detail.unset')
          ) : (
            <time dateTime={model.updatedAt} title={model.updatedAt}>
              {updatedAt}
            </time>
          )}
        </dd>
      </dl>

      <p className={styles.extraHint}>{t('settings.model.detail.keyHint')}</p>

      <div className={styles.detailActions}>
        <Button onClick={onBack}>{t('settings.model.detail.back')}</Button>
        <Button variant="primary" onClick={onEdit}>
          {t('settings.form.edit')}
        </Button>
      </div>
    </div>
  );
}
