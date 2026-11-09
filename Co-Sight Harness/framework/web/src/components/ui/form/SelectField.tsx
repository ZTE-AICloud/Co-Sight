import { cn } from '../../../lib/cn';
import { Icon } from '../Icon';
import { describedBy, FieldShell } from './Field';
import styles from './form.module.css';

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  hint?: string | undefined;
  error?: string | undefined;
  disabled?: boolean;
  /** `string | undefined` 而非 `string`，理由同 `FieldShellProps.className`。 */
  className?: string | undefined;
}

/**
 * 下拉选择。
 *
 * 用**原生** `<select>` 而不是自绘的弹出层：选项数量不定（供应商 5 个、
 * 安全分析器 3 个），原生控件在键盘、读屏、触屏、以及"选项很多时自动滚动"
 * 这四件事上都已经是对的，自绘一个只为了改外观，代价是这四件事各自都要自己实现
 * 一遍并且很难测。这里只把外观接到设计令牌上。
 *
 * `value` 不匹配任何选项时原生 `<select>` 会显示空白——对"从后端拿到一个
 * 已下线的枚举值"这种情况，空白反而是诚实的，比悄悄选中第一项好（同
 * Segmented 那条注释的取向，但这里没有 Tab 序列问题，不需要回退）。
 */
export function SelectField({
  id,
  label,
  value,
  onChange,
  options,
  hint,
  error,
  disabled = false,
  className,
}: SelectFieldProps) {
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} className={className}>
      <span className={styles.selectWrapper}>
        <select
          id={id}
          className={cn(styles.input, styles.select)}
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
          }}
          disabled={disabled}
          aria-invalid={error === undefined ? undefined : true}
          aria-describedby={describedBy(id, hint, error)}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <Icon name="chevronDown" size={16} className={styles.selectChevron} />
      </span>
    </FieldShell>
  );
}
