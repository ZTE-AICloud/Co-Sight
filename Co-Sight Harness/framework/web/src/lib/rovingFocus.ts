/**
 * 单选组 / 页签组的键盘行为（roving tabindex）。
 *
 * 抽出来是因为设置弹窗的左侧页签栏与专家页的分段控件需要**完全相同**的键盘约定，
 * 差别只在视觉方向。复制一份的代价不是这 30 行，而是将来某天有人只改了其中一份
 * ——于是同一个应用里两个"看起来一样"的选择控件，方向键行为不一样。
 *
 * 约定（WAI-ARIA 单选组）：
 * - 整组只有一个 Tab 停靠点（选中项 tabIndex=0，其余 -1），进入后按方向键切换；
 * - 方向键**同时**移动选中与焦点，不需要先移动焦点再按空格；
 * - Home / End 跳到首尾；两端循环。
 * - 上下与左右都接受：控件横竖两种排布都用同一套键，用户不需要知道它是横的还是竖的。
 */

import { useRef, type KeyboardEvent } from 'react';

export interface RovingFocus<T extends string> {
  /** 作为元素的 ref 使用：`ref={roving.register(value)}`。 */
  register: (value: T) => (node: HTMLElement | null) => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>, index: number) => void;
}

export function useRovingFocus<T extends string>(
  values: readonly T[],
  select: (value: T) => void,
): RovingFocus<T> {
  const refs = useRef(new Map<T, HTMLElement>());

  function move(from: number, step: number): void {
    const count = values.length;
    if (count === 0) {
      return;
    }
    const target = values[(from + step + count) % count];
    if (target === undefined) {
      return;
    }
    select(target);
    refs.current.get(target)?.focus();
  }

  return {
    register(value) {
      return (node) => {
        if (node === null) {
          refs.current.delete(value);
        } else {
          refs.current.set(value, node);
        }
      };
    },
    onKeyDown(event, index) {
      switch (event.key) {
        case 'ArrowRight':
        case 'ArrowDown':
          event.preventDefault();
          move(index, 1);
          break;
        case 'ArrowLeft':
        case 'ArrowUp':
          event.preventDefault();
          move(index, -1);
          break;
        case 'Home':
          event.preventDefault();
          move(0, 0);
          break;
        case 'End':
          event.preventDefault();
          move(values.length - 1, 0);
          break;
        default:
          break;
      }
    },
  };
}
