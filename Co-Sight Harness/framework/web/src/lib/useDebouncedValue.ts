import { useEffect, useState } from 'react';

/**
 * 延迟跟随一个值。
 *
 * 用在搜索框上：输入框本身**必须**立即响应（受控组件，晚一帧都会让光标跳），
 * 而"拿这个值去发请求"要等用户停手。做法是让输入框直接读 state，
 * 请求读 debounce 之后的值——两者共用一个源，不存在不同步。
 *
 * 不要在输入框组件里做防抖（见 SearchInput.tsx 的说明）：同一个输入框换个用法
 * （本地过滤）就不需要防抖了，把策略放在使用方更灵活。
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => {
      setSettled(value);
    }, delayMs);
    // 依赖里的 value 一变就清掉上一个定时器，于是只有"最后一次改动"会落地。
    return () => {
      clearTimeout(timer);
    };
  }, [value, delayMs]);

  return settled;
}
