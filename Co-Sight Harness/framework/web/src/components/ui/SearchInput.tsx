import { useRef, type ChangeEvent } from 'react';

import { cn } from '../../lib/cn';
import { Icon } from './Icon';
import { IconButton } from './Button';
import styles from './SearchInput.module.css';

export interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel: string;
  /** 有内容时才出现的清空按钮的标题。 */
  clearLabel: string;
  className?: string;
}

/**
 * 受控搜索框。
 *
 * **不做防抖**：防抖属于"什么时候发请求"的策略，是调用方（P4 的专家列表 hook）
 * 的事。放在输入框里会让它同时承担两件事，且同一个框换个用法（比如本地过滤
 * 而非远程查询）就得改组件。这里只保证"每敲一个字就报一次"。
 */
export function SearchInput({
  value,
  onChange,
  placeholder,
  ariaLabel,
  clearLabel,
  className,
}: SearchInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  function handleChange(event: ChangeEvent<HTMLInputElement>): void {
    onChange(event.target.value);
  }

  return (
    <div className={cn(styles.wrapper, className)}>
      <Icon name="search" className={styles.icon} />
      <input
        ref={inputRef}
        className={styles.input}
        type="search"
        // type="search" 在部分浏览器里自带一个原生清空按钮，和下面自绘的重复。
        // 该伪元素没有标准写法，只能按 webkit 前缀关掉。
        value={value}
        onChange={handleChange}
        placeholder={placeholder}
        aria-label={ariaLabel}
        autoComplete="off"
      />
      {value === '' ? null : (
        <IconButton
          className={cn(styles.clear)}
          icon="close"
          label={clearLabel}
          onClick={() => {
            onChange('');
            // 清空是人删掉条件继续找，焦点留在框里才顺手。
            inputRef.current?.focus();
          }}
        />
      )}
    </div>
  );
}
