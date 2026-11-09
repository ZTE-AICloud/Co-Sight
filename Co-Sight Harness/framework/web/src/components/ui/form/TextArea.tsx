import { cn } from '../../../lib/cn';
import { describedBy, FieldShell } from './Field';
import styles from './form.module.css';

export interface TextAreaProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string | undefined;
  hint?: string | undefined;
  error?: string | undefined;
  /** 可见行数，只影响初始高度（用户仍可纵向拉伸）。 */
  rows?: number | undefined;
  /** 语义上的必填；与 `TextField` 同理，不触发浏览器原生气泡。 */
  required?: boolean;
  disabled?: boolean;
  className?: string | undefined;
}

/**
 * 多行文本输入（代理描述这类上限 500 字的字段）。
 *
 * 与 `TextField` 分开而不是给它加个 `multiline` 开关：`<input>` 与 `<textarea>`
 * 在 `value`/`rows`/回车行为上都不是同一套，合成一个组件后每个调用点都要在
 * 脑子里先判一次"这次走的是哪支"。
 */
export function TextArea({
  id,
  label,
  value,
  onChange,
  placeholder,
  hint,
  error,
  rows = 3,
  required = false,
  disabled = false,
  className,
}: TextAreaProps) {
  return (
    <FieldShell id={id} label={label} hint={hint} error={error} className={className}>
      <textarea
        id={id}
        className={cn(styles.input, styles.textarea)}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
        }}
        placeholder={placeholder}
        rows={rows}
        disabled={disabled}
        aria-required={required}
        aria-invalid={error === undefined ? undefined : true}
        aria-describedby={describedBy(id, hint, error)}
      />
    </FieldShell>
  );
}
