/**
 * 表单字段的外壳：标签 + 提示 + 控件 + 错误。
 *
 * 三个 id 全部从控件 id 派生，而不是各处 `useId()` 一次：标签的 `htmlFor`、
 * `aria-describedby` 里的提示与错误，三者必须指向**同一组**元素，分散生成迟早
 * 会出现"标签指向了另一个字段"这种读屏才暴露的问题。派生规则只有一处，
 * 对不上就是对不上（可以由测试直接断言）。
 */

import type { ReactNode } from 'react';

import { cn } from '../../../lib/cn';
import styles from './form.module.css';

export function fieldHintId(controlId: string): string {
  return `${controlId}-hint`;
}

export function fieldErrorId(controlId: string): string {
  return `${controlId}-error`;
}

/**
 * `aria-describedby` 的值：只列**真的渲染出来**的那几段。
 *
 * 指向一个不存在的 id 不会报错，只是描述读不出来——安静地少一条提示，
 * 所以这里按存在与否拼，而不是固定拼两个 id。
 */
export function describedBy(
  controlId: string,
  hint?: string | undefined,
  error?: string | undefined,
): string | undefined {
  const ids = [
    hint === undefined ? null : fieldHintId(controlId),
    error === undefined ? null : fieldErrorId(controlId),
  ].filter((value): value is string => value !== null);

  return ids.length === 0 ? undefined : ids.join(' ');
}

export interface FieldShellProps {
  /** 控件 id；标签与提示/错误的关联全部由它派生。 */
  id: string;
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
  /**
   * 附加到最外层；表单栅格用 `styles.wide` 让长字段跨两列。
   *
   * 声明成 `string | undefined` 而不是 `string`：调用方常常把它一路透传下来
   * （`TextField` 的 props 就是这个类型），在**声明处**放宽一次，省掉每个中间
   * 组件都要写的条件展开。理由与 `api/client.ts` 的 `signal` 相同。
   */
  className?: string | undefined;
  children: ReactNode;
}

export function FieldShell({ id, label, hint, error, className, children }: FieldShellProps) {
  return (
    <div className={cn(styles.field, className)}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      {hint === undefined ? null : (
        <p className={styles.hint} id={fieldHintId(id)}>
          {hint}
        </p>
      )}
      {children}
      {error === undefined ? null : (
        /*
         * `role="alert"`：校验失败时这句是**对刚刚那次操作的回应**，
         * 读屏用户不该等下次 Tab 到它才发现自己填错了。
         */
        <p className={styles.error} id={fieldErrorId(id)} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
