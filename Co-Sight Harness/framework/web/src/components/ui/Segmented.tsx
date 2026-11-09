import { cn } from '../../lib/cn';
import { useRovingFocus } from '../../lib/rovingFocus';
import styles from './Segmented.module.css';

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

export interface SegmentedProps<T extends string> {
  options: readonly SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** 整组的无障碍名称（如「专家筛选」）。 */
  ariaLabel: string;
}

/**
 * 单选分段控件。
 *
 * 用 `radiogroup` / `radio` 而不是 `tablist` / `tab`：这几个选项是**筛选条件**，
 * 结果都渲染在下方同一个网格里。`tablist` 的语义是"每个 tab 对应一个独立的
 * tabpanel"，用在这里会让读屏软件期待出现并不存在的面板切换。
 * （设置弹窗那边的页签确实各自对应一块内容，所以那边用的是 tablist。）
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: SegmentedProps<T>) {
  const values = options.map((option) => option.value);
  const roving = useRovingFocus(values, onChange);
  /*
   * 整组只留一个 Tab 停靠点。但 `value` 可能不匹配任何选项——调用方从 URL 查询串
   * 之类未经校验的地方取初值时就会这样（后端下发的筛选项改了名也会）。此时必须
   * 回退到第一项，否则每个选项都是 `tabIndex={-1}`，整组在 Tab 序列里彻底消失，
   * 键盘用户根本进不来（radio 不像 input 那样会自己成为停靠点）。
   */
  const selectedIndex = values.indexOf(value);
  const tabStopIndex = selectedIndex === -1 ? 0 : selectedIndex;

  return (
    <div className={styles.group} role="radiogroup" aria-label={ariaLabel}>
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            ref={roving.register(option.value)}
            type="button"
            role="radio"
            aria-checked={selected}
            // 未选中项不进 Tab 序列，整组只有一个停靠点。
            tabIndex={index === tabStopIndex ? 0 : -1}
            className={cn(styles.option, selected && styles.selected)}
            onClick={() => {
              onChange(option.value);
            }}
            onKeyDown={(event) => {
              roving.onKeyDown(event, index);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
