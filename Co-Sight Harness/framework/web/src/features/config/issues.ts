/**
 * 表单校验的公共层：把"哪里不对"翻译成人话。
 *
 * 校验逻辑本身在各自的 `*Form.ts` 里（纯函数、不碰 i18n），这里只负责最后一步：
 * 措辞。分成两层是因为措辞要跟着界面语言走，而"温度不能超过 2"这种事与语言无关——
 * 混在一起写的话，校验就只能靠渲染整个表单才测得了。
 */

import { useCallback } from 'react';

import type { MessageKey } from '../../i18n/types';
import { useI18n } from '../../i18n/useI18n';

/**
 * 字段上出的一种问题。
 *
 * 用具名 kind 而不是直接给一句文案：校验函数因此不需要知道任何一句话，
 * 而"填了 abc"和"填了 5（上限是 2）"在数据上确实是两件事，后者还要把上下限带上，
 * 用户才知道该填多少。
 */
export type FieldIssue =
  | { kind: 'required' }
  | { kind: 'number' }
  | { kind: 'positiveInteger' }
  | { kind: 'url' }
  /**
   * 地址合法但内嵌了账号密码（`https://user:pass@host/`）。
   *
   * 单独成一档而不是复用 `url`：这条地址本身是能打开的，用户要改的只是"别把凭据
   * 写进地址里"；说成"要以 http:// 开头"会把一个已经能用的地址判成格式错误。
   */
  | { kind: 'credentials' }
  | { kind: 'range'; min: number; max: number }
  | { kind: 'tooLong'; max: number };

/** 把问题变成一句可以挂在字段上的文案。`fieldLabel` 是那个字段的本地化名。 */
export type IssueReporter = (issue: FieldIssue, fieldLabel: string) => string;

/** 表单的错误状态：只登记出错的字段，其余为 undefined。 */
export type FieldIssues<Field extends string> = Partial<Record<Field, string>>;

/**
 * 措辞的键。由调用方以模块级常量传入（而不是在这里写死成 `model`/`agentProxy`）：
 * 同一个共用组件将来会被工作区面板也用上，把资源名钉在这个文件里就成了三处都要改的
 * 地方。传常量对象也保证了 `useCallback` 的依赖不会每次渲染都变。
 */
export interface IssueMessageKeys {
  /** 数值越界：`{field}要在 {min} 到 {max} 之间`。 */
  range: MessageKey;
  /** 超长：`{field}不能超过 {max} 个字符`。 */
  tooLong: MessageKey;
}

/**
 * 取出"把 issue 说成人话"的函数。
 *
 * 已填字段的错误只挂一条，与常驻的 hint 叠在同一字段上：hint 说的是"这一栏怎么填"，
 * 错误说的是"刚刚那次提交哪里不对"，两者不能互相顶替。
 */
export function useIssueReporter(keys: IssueMessageKeys): IssueReporter {
  const { t } = useI18n();

  return useCallback<IssueReporter>(
    (issue, fieldLabel) => {
      switch (issue.kind) {
        case 'required':
          return t('settings.form.required', { field: fieldLabel });
        case 'number':
          return t('settings.form.invalidNumber', { field: fieldLabel });
        case 'positiveInteger':
          return t('settings.form.invalidPositiveInteger', { field: fieldLabel });
        case 'url':
          return t('settings.form.invalidUrl', { field: fieldLabel });
        case 'credentials':
          return t('settings.form.invalidUrlCredentials', { field: fieldLabel });
        case 'range':
          return t(keys.range, { field: fieldLabel, min: issue.min, max: issue.max });
        case 'tooLong':
          return t(keys.tooLong, { field: fieldLabel, max: issue.max });
      }
    },
    [t, keys],
  );
}

/**
 * 把 `{ 字段: 问题 }` 翻成 `{ 字段: 文案 }`。
 *
 * `labelOf` 由调用方给，因为字段名是各资源自己的词条（`settings.model.field.*`）；
 * 这里只做"逐个翻译"这件事，避免两个面板各写一遍同样的循环。
 */
export function reportIssues<Field extends string>(
  issues: Partial<Record<Field, FieldIssue>>,
  report: IssueReporter,
  labelOf: (field: Field) => string,
): FieldIssues<Field> {
  const messages: FieldIssues<Field> = {};
  for (const [field, issue] of Object.entries(issues) as [Field, FieldIssue][]) {
    messages[field] = report(issue, labelOf(field));
  }
  return messages;
}

/** 有没有出错的字段。`{}` 与 `{a: undefined}` 的区别在这里被抹平。 */
export function hasIssues<Field extends string>(
  issues: Partial<Record<Field, FieldIssue>>,
): boolean {
  return Object.keys(issues).length > 0;
}
