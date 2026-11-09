import type { ReactNode } from 'react';

import { describedBy, FieldShell } from './Field';
import styles from './form.module.css';

export type TextFieldType = 'text' | 'password' | 'url' | 'number';

export interface TextFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: TextFieldType;
  placeholder?: string | undefined;
  hint?: string | undefined;
  error?: string | undefined;
  /**
   * 只用于无障碍语义（读屏会念"必填"），**不触发浏览器原生气泡**：
   * 调用方的表单一律带 `noValidate`，校验与文案都由前端自己出，
   * 否则同一个字段会同时冒出浏览器本地化的提示和我们的提示两种口径。
   */
  required?: boolean;
  disabled?: boolean;
  autoComplete?: string | undefined;
  /**
   * 输入框右侧的附加控件（工作区的「选择目录」按钮）。
   *
   * 放在输入框**同一行**而不是标签一侧：它是这个字段的操作，不是另一个字段；
   * 拆出去会多占一行高度，弹窗里每一行都要紧。
   */
  trailing?: ReactNode;
  /** 点击输入框**本身**时触发；`trailing` 里的按钮是独立目标，不会触发它。 */
  onInputClick?: (() => void) | undefined;
  /** 仅 `type="number"` 有意义。 */
  min?: number | undefined;
  max?: number | undefined;
  step?: number | undefined;
  /**
   * 附带类名（表单栅格用 `styles.wide` 让长字段跨两列）。
   *
   * 写成 `string | undefined`：CSS Modules 对未声明的类名给出的是
   * `string | undefined`，调用方直接把它透传下来是常态。在**声明处**放宽一次，
   * 省掉每个调用点都要写的条件展开（理由同 `FieldShellProps.className`）。
   */
  className?: string | undefined;
}

/**
 * 文本 / 密码 / 数字输入框（含标签与错误）。
 *
 * 数字字段的 `value` 刻意是 **string** 而不是 number：
 * 用户清空输入框、或敲到一半（`-`、`1.`）时没有合法数字可表示，若把状态存成
 * number 就得在"空"和"0"之间撒谎。解析与范围校验交给调用方在提交时做，
 * 这样"空 = 用默认值"和"空 = 不设置"两种语义才区分得开。
 */
export function TextField({
  id,
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  hint,
  error,
  required = false,
  disabled = false,
  autoComplete,
  trailing,
  onInputClick,
  min,
  max,
  step,
  className,
}: TextFieldProps) {
  const input = (
    <input
      id={id}
      className={styles.input}
      type={type}
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
      }}
      placeholder={placeholder}
      disabled={disabled}
      aria-required={required}
      aria-invalid={error === undefined ? undefined : true}
      aria-describedby={describedBy(id, hint, error)}
      {...(autoComplete === undefined ? {} : { autoComplete })}
      {...(min === undefined ? {} : { min })}
      {...(max === undefined ? {} : { max })}
      {...(step === undefined ? {} : { step })}
      {...(onInputClick === undefined ? {} : { onClick: onInputClick })}
    />
  );

  return (
    <FieldShell id={id} label={label} hint={hint} error={error} className={className}>
      {/*
       * 没有 `trailing` 时**不套这一层**：多一个 flex 容器会改变输入框的宽度计算，
       * 而绝大多数字段没有附加控件，它们的排版不该为这一处多付代价。
       */}
      {trailing === undefined ? (
        input
      ) : (
        <div className={styles.inputRow}>
          {input}
          {trailing}
        </div>
      )}
    </FieldShell>
  );
}

export type SecretFieldProps = Omit<TextFieldProps, 'type' | 'autoComplete'>;

/**
 * 密钥输入框。
 *
 * 与 `TextField type="password"` 的唯一差别是**固定 `autoComplete="new-password"`**，
 * 这不是装饰：
 *
 * - 密码管理器看到普通密码框会拿"本机存过的密码"来填，界面上就出现一串和密钥无关
 *   的字符，用户会以为我们的密钥被回显出来了（而 D26 的承诺正是"读不到"）；
 * - `new-password` 同时抑制"是否保存此密码"的弹窗——工作台里弹这个很突兀。
 *
 * 组件本身**不保证**"不回显已保存的密钥"，那是调用方的责任：初值一律给空串，
 * 已配置状态由 `hasApiKey`/`hasToken` 这类布尔字段单独表达。
 */
export function SecretField(props: SecretFieldProps) {
  return <TextField {...props} type="password" autoComplete="new-password" />;
}
