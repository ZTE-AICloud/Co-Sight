import { useEffect, useId, useRef, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import { Icon } from '../../../shared/components/Icon';

export interface FilterSelectOption<T extends string> {
  value: T;
  label: string;
  /** 选项的补充说明，悬停时给出（来源组用它解释「自定义」是什么） */
  hint?: string;
}

interface FilterSelectProps<T extends string> {
  /** 维度名（「来源」/「状态」）：拼在触发器上，也作下拉的无障碍名称 */
  label: string;
  value: T;
  /** 第一项约定是「全部」—— 触发器据此决定要不要亮成「已筛」 */
  options: FilterSelectOption<T>[];
  onChange: (value: T) => void;
}

/**
 * 工具条上的单选手持下拉（来源 / 状态）。
 *
 * 2026-10-29 从一排 chip 换成下拉：两组 chip 并排、都以「全部」打头，
 * 既占掉一整行，又分不清哪颗属于哪一组。现在与标签筛选长成同一款下拉，
 * 触发器始终写着当前取值 —— 收起后这是唯一能看出筛了什么的地方。
 *
 * 交互与 `TagFilter` 一致：点外部（`mousedown`）或 Esc 关闭，Esc 后焦点还给触发器；
 * 选中后关闭，焦点同样还给触发器；选项是原生 `button`，键盘行为自带。
 */
export function FilterSelect<T extends string>({
  label,
  value,
  options,
  onChange,
}: FilterSelectProps<T>) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  /** 同一页上有两颗（来源 / 状态），关联 id 不能像标签那样写死常量 */
  const listId = useId();

  const current = options.find((option) => option.value === value) ?? options[0];
  /** 没在「全部」上就是筛着的 —— 触发器要保持白药丸，扫一眼工具条就知道有筛选 */
  const applied = value !== options[0].value;

  /** 点外部 / Esc 关闭。用 mousedown 与 `TagFilter`、Composer 的菜单保持同一时机。 */
  useEffect(() => {
    if (!open) return;

    function onDocMouseDown(event: MouseEvent) {
      if (rootRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return;
      setOpen(false);
      triggerRef.current?.focus();
    }

    document.addEventListener('mousedown', onDocMouseDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  function choose(next: T) {
    onChange(next);
    setOpen(false);
    triggerRef.current?.focus();
  }

  return (
    <div className="al-menu-root" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={`al-chip al-menu-trigger${open || applied ? ' al-chip--on' : ''}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((currentOpen) => !currentOpen)}
      >
        {t('agentList.filterTrigger', { label, value: current.label })}
        <Icon name="chevronDown" size={12} />
      </button>

      {open && (
        <div className="al-menu al-menu--select">
          <div className="al-menu__list" id={listId} role="listbox" aria-label={label}>
            {options.map((option) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={value === option.value}
                className={`al-menu__option${value === option.value ? ' al-menu__option--on' : ''}`}
                title={option.hint}
                onClick={() => choose(option.value)}
              >
                <span className="al-menu__option-label">{option.label}</span>
                {value === option.value && <Icon name="check" size={13} />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
