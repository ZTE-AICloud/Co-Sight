import { cn } from '../../../lib/cn';
import { describedBy, fieldErrorId, fieldHintId } from './Field';
import styles from './form.module.css';

export interface SwitchFieldProps {
  id: string;
  label: string;
  hint?: string | undefined;
  error?: string | undefined;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  /** `string | undefined` 而非 `string`，理由同 `FieldShellProps.className`。 */
  className?: string | undefined;
}

/**
 * 开关行（左侧标签、右侧开关）。
 *
 * 为什么开关是 `<button role="switch">` 而不是 `<input type="checkbox">`：
 * 复选框的语义是"选中这一项"，开关的语义是"打开/关闭一个设置"，两者在读屏下
 * 念出来的词不同；而且按钮天然获得 Space/Enter 激活，不需要自己接键盘事件。
 *
 * 名称通过 `aria-labelledby` 指到左侧那段文字上，而不是另写一份 `aria-label`：
 * 同一句话写两处，改一处忘一处就会让读屏念的和眼睛看到的不是一回事。
 */
export function SwitchField({
  id,
  label,
  hint,
  error,
  checked,
  onChange,
  disabled = false,
  className,
}: SwitchFieldProps) {
  const labelId = `${id}-label`;

  return (
    <div className={cn(styles.switchRow, className)}>
      <span>
        <span className={styles.label} id={labelId}>
          {label}
        </span>
        {hint === undefined ? null : (
          <p className={styles.hint} id={fieldHintId(id)}>
            {hint}
          </p>
        )}
        {error === undefined ? null : (
          <p className={styles.error} id={fieldErrorId(id)} role="alert">
            {error}
          </p>
        )}
      </span>

      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={describedBy(id, hint, error)}
        disabled={disabled}
        className={styles.switch}
        onClick={() => {
          onChange(!checked);
        }}
      >
        {/* 滑块是纯装饰：状态由 `aria-checked` 表达，读屏不必再念一次。 */}
        <span className={styles.switchThumb} aria-hidden="true" />
      </button>
    </div>
  );
}
