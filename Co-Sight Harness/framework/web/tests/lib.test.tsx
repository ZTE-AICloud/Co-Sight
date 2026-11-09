/**
 * src/lib 下的通用工具单测。
 *
 * 这些 hook 都短到"看一眼就懂"，但每一条都有个不显眼的失败模式：
 * 防抖多漏一次值、无限滚动把 observer 重建一次、roving tabindex 忘了环绕——
 * 它们在界面上表现为"偶发"和"手感不对"，靠手工点很难复现。这里用假定时器与
 * 假的 IntersectionObserver 把时序钉死，让"偶发"变成确定性的断言。
 * 真实的布局与滚动行为（哨兵到底会不会进视口）交给 e2e，jsdom 里没有布局，
 * 硬测只会得到一个永远绿或永远红的假信号。
 */

import { act, render, renderHook } from '@testing-library/react';
import type { Locale } from 'harness-shared';
import type { KeyboardEvent } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { cn } from '../src/lib/cn';
import { copyText } from '../src/lib/copyText';
import { formatDateTime } from '../src/lib/formatDateTime';
import { useDebouncedValue } from '../src/lib/useDebouncedValue';
import { useHtmlLang } from '../src/lib/useHtmlLang';
import { useInfiniteScroll } from '../src/lib/useInfiniteScroll';
import { useRovingFocus } from '../src/lib/rovingFocus';

describe('cn', () => {
  it('拼出有效类名，顺序不变', () => {
    expect(cn('card', 'card--wide', 'card--active')).toBe('card card--wide card--active');
  });

  it('剔除 false / null / undefined / 空串，不留多余空格', () => {
    // `isActive && styles.active` 在 false 时求值为 false，模板串拼接会留下
    // 一个字面量 "false" 类名——CSS Modules 里不报错，只是悄悄多一个无用类。
    const isActive = false;
    const className = cn('card', isActive && 'card--active', undefined, null, '', 'card--last');

    expect(className).toBe('card card--last');
    expect(className).not.toContain('false');
  });

  it('没有任何有效片段时返回空串', () => {
    // 返回 '' 而不是 'undefined'：空串交给 React 时不会渲染出 class 属性。
    expect(cn()).toBe('');
    expect(cn(false, null, undefined, '')).toBe('');
  });
});

describe('formatDateTime', () => {
  it('空值返回 null，而不是 "Invalid Date" 或空串', () => {
    // 界面上的"该字段没有值"要由调用方决定怎么显示；返回 "Invalid Date"
    // 会让这串英文原样出现在中文界面上。
    expect(formatDateTime(null, 'zh-CN')).toBeNull();
    expect(formatDateTime(undefined, 'zh-CN')).toBeNull();
    expect(formatDateTime('', 'zh-CN')).toBeNull();
  });

  it('解析不了的字符串返回 null，不抛异常', () => {
    expect(formatDateTime('不是时间', 'zh-CN')).toBeNull();
    expect(formatDateTime('2026-13-45T99:99:99Z', 'zh-CN')).toBeNull();
  });

  it('合法 ISO 串按语言格式化，两种语言结果不同', () => {
    const iso = '2026-01-02T03:04:05.000Z';
    const zh = formatDateTime(iso, 'zh-CN');
    const en = formatDateTime(iso, 'en-US');

    expect(zh).not.toBeNull();
    expect(en).not.toBeNull();
    // 只断言"两种语言给出不同文本"：具体格式随 ICU 版本变，
    // 钉死一个字符串会让用例在换 Node 版本时红，而红的原因与被测行为无关。
    expect(zh).not.toBe(en);
    expect(zh).toContain('2026');
  });
});

describe('copyText', () => {
  const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');

  afterEach(() => {
    vi.unstubAllGlobals();
    if (original === undefined) {
      Reflect.deleteProperty(navigator, 'clipboard');
    } else {
      Object.defineProperty(navigator, 'clipboard', original);
    }
  });

  it('成功时返回 true，并把原文交给剪贴板', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

    await expect(copyText('hello')).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith('hello');
  });

  it('浏览器没有 clipboard API 时返回 false，不抛异常', async () => {
    // 非安全上下文（http 上非 localhost）就是这种情形。
    Reflect.deleteProperty(navigator, 'clipboard');
    await expect(copyText('hello')).resolves.toBe(false);
  });

  it('用户拒绝权限（writeText 抛错）时返回 false', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: {
        writeText: () => Promise.reject(new Error('NotAllowedError')),
      },
      configurable: true,
    });
    await expect(copyText('hello')).resolves.toBe(false);
  });
});

describe('useDebouncedValue', () => {
  beforeEach(() => {
    // 真实等待会把这条测试拖到几百毫秒，还会在慢机器上偶发失败。
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('初值立即可用，延迟内不跟随新值，到点才落地', () => {
    const { result, rerender } = renderHook(({ value }: { value: string }) => useDebouncedValue(value, 300), {
      initialProps: { value: 'kw' },
    });

    expect(result.current).toBe('kw');

    rerender({ value: 'kwa' });
    // 输入框自己读 state 立即响应，只有"拿去发请求"的那份值要等停手。
    expect(result.current).toBe('kw');

    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(result.current).toBe('kw');

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe('kwa');
  });

  it('连续变化只让最后一次值产出', () => {
    const seen: string[] = [];
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => {
        const settled = useDebouncedValue(value, 300);
        seen.push(settled);
        return settled;
      },
      { initialProps: { value: 'a' } },
    );

    rerender({ value: 'ab' });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    rerender({ value: 'abc' });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    rerender({ value: 'abcd' });
    act(() => {
      vi.advanceTimersByTime(300);
    });

    // 依赖数组里 value 一变就清掉上一个定时器，中间值绝不能被观察到——
    // 否则每敲一个字都会发一次请求。
    expect(seen).not.toContain('ab');
    expect(seen).not.toContain('abc');
    expect(result.current).toBe('abcd');
  });

  it('延迟参数本身不可省略：0 也不等于同步更新', () => {
    const { result, rerender } = renderHook(({ value }: { value: string }) => useDebouncedValue(value, 0), {
      initialProps: { value: 'a' },
    });

    rerender({ value: 'b' });
    // 依赖是 value+delay，delay 为 0 时也只是把定时器排到下一个宏任务，
    // 同一帧内仍是旧值——调用方不能指望 delay=0 时同步跟随。
    expect(result.current).toBe('a');

    act(() => {
      vi.advanceTimersByTime(0);
    });
    expect(result.current).toBe('b');
  });
});

describe('useHtmlLang', () => {
  const initialLang = document.documentElement.lang;

  afterEach(() => {
    // lang 是文档级属性，用例改完要还原，否则污染同文件后面的断言。
    document.documentElement.lang = initialLang;
  });

  it('把语言写进 <html lang>，语言变化时跟随更新', () => {
    const { rerender } = renderHook(({ locale }: { locale: Locale }) => useHtmlLang(locale), {
      initialProps: { locale: 'en-US' as Locale },
    });

    // 英文对应 `en` 而不是 `en-US`：这个属性决定读屏用哪种语音合成、
    // 以及浏览器对 CJK 文本的字体回退，写成 locale 值就走偏了。
    expect(document.documentElement.lang).toBe('en');

    rerender({ locale: 'zh-CN' });
    expect(document.documentElement.lang).toBe('zh-CN');
  });

  it('卸载后不回滚 lang', () => {
    // effect 没有 cleanup：`lang` 是文档级属性，同一个页面上可能还有别的
    // 消费方，卸载其中一个就把整页语言改回旧值只会制造错误状态。
    const { unmount } = renderHook(() => useHtmlLang('en-US'));
    expect(document.documentElement.lang).toBe('en');

    unmount();
    expect(document.documentElement.lang).toBe('en');
  });
});

/*
 * tests/setup.ts 里的 IntersectionObserver 桩故意不触发任何回调（jsdom 没有布局）。
 * 这里装一个可观测的版本：把 observe 到的节点与构造时的回调都记下来，
 * 用例再手动"送入视口"，从而把触发链路测成确定性的。
 */
class FakeIntersectionObserver implements IntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];

  readonly root: Element | Document | null = null;
  readonly rootMargin: string;
  readonly thresholds: readonly number[] = [0];
  readonly scrollMargin: string = '0px';
  readonly observed: Element[] = [];
  disconnected = false;

  private readonly callback: IntersectionObserverCallback;

  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.callback = callback;
    this.rootMargin = options?.rootMargin ?? '0px';
    FakeIntersectionObserver.instances.push(this);
  }

  observe(node: Element): void {
    this.observed.push(node);
  }

  unobserve(): void {}

  disconnect(): void {
    this.disconnected = true;
  }

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }

  /** 手动送一次相交事件。 */
  emit(isIntersecting: boolean): void {
    this.callback([{ isIntersecting } as IntersectionObserverEntry], this);
  }
}

const OriginalIntersectionObserver = globalThis.IntersectionObserver;

/**
 * 挂上假 observer 并清空上一次用例留下的实例记录。
 *
 * 这里不能用 `vi.stubGlobal`：setup.ts 的桩是 `Object.defineProperty` 装的，
 * 只给了 `writable: true`、没给 `configurable: true`，vitest 的 redefine 会直接抛
 * "Cannot redefine property: IntersectionObserver"。该属性可写，直接赋值即可；
 * 还原则由本文件自己的 afterEach 负责（`unstubAllGlobals` 管不到手动赋值）。
 */
function installFakeObserver(): void {
  FakeIntersectionObserver.instances = [];
  globalThis.IntersectionObserver = FakeIntersectionObserver;
}

function observerAt(index = 0): FakeIntersectionObserver {
  const instance = FakeIntersectionObserver.instances[index];
  if (instance === undefined) {
    throw new Error(`没有第 ${String(index)} 个 IntersectionObserver：用例前置条件没满足`);
  }
  return instance;
}

/** 把哨兵挂在列表末尾的组件，用法与生产一致（`<div ref={sentinelRef} />`）。 */
function Sentinel({ enabled, onLoadMore }: { enabled: boolean; onLoadMore: () => void }) {
  const sentinelRef = useInfiniteScroll(enabled, onLoadMore);
  return <div ref={sentinelRef} />;
}

/** 只造 hook 用得到的两个成员：key 与 preventDefault。 */
function makeEvent(key: string): {
  event: KeyboardEvent<HTMLElement>;
  preventDefault: ReturnType<typeof vi.fn>;
} {
  const preventDefault = vi.fn();
  return { event: { key, preventDefault } as unknown as KeyboardEvent<HTMLElement>, preventDefault };
}

describe('useInfiniteScroll', () => {
  beforeEach(() => {
    installFakeObserver();
  });

  afterEach(() => {
    // 手动赋值不受 unstubAllGlobals 管，自己还原，避免影响同文件后续用例。
    globalThis.IntersectionObserver = OriginalIntersectionObserver;
  });

  it('哨兵挂上后建立 observer，进入视口时调用 onLoadMore', () => {
    const onLoadMore = vi.fn();
    const view = render(<Sentinel enabled onLoadMore={onLoadMore} />);

    // 回调 ref 在提交阶段就赋值，useEffect（被动阶段）之后才跑，
    // 所以 effect 里读到的 nodeRef.current 已经是真实节点。
    expect(FakeIntersectionObserver.instances).toHaveLength(1);
    const observer = observerAt();
    expect(observer.observed).toStrictEqual([view.container.firstElementChild]);

    act(() => {
      observer.emit(false);
    });
    expect(onLoadMore).not.toHaveBeenCalled();

    act(() => {
      observer.emit(true);
    });
    expect(onLoadMore).toHaveBeenCalledTimes(1);
  });

  it('提前 200px 预取（rootMargin）', () => {
    render(<Sentinel enabled onLoadMore={vi.fn()} />);

    // 等哨兵真的进入视口再请求，用户会看到一段空白加载；工作台用的是本机接口，
    // 200px 足够在滚动到底前拿到数据。
    expect(observerAt().rootMargin).toBe('0px 0px 200px 0px');
  });

  it('enabled 为 false 时不建立 observer，转 true 才建立，再转 false 断开', () => {
    const onLoadMore = vi.fn();
    const view = render(<Sentinel enabled={false} onLoadMore={onLoadMore} />);

    // 调用方把 isFetching / isError 也算进 enabled：加载中或失败后不该再观察，
    // 否则一次失败会变成对同一个失败页签的无限重试。
    expect(FakeIntersectionObserver.instances).toHaveLength(0);

    view.rerender(<Sentinel enabled onLoadMore={onLoadMore} />);
    expect(FakeIntersectionObserver.instances).toHaveLength(1);
    const observer = observerAt();

    view.rerender(<Sentinel enabled={false} onLoadMore={onLoadMore} />);
    expect(observer.disconnected).toBe(true);
    expect(FakeIntersectionObserver.instances).toHaveLength(1);
  });

  it('onLoadMore 换新引用不重建 observer，但触发的是最新回调', () => {
    const first = vi.fn();
    const second = vi.fn();
    const view = render(<Sentinel enabled onLoadMore={first} />);
    const observer = observerAt();

    // 内联箭头函数每次渲染都是新的。若它进了 effect 依赖，这里会多一个 observer
    // （先 disconnect 再 observe），滚动中很容易漏掉一次触发——这正是回调走 ref 的目的。
    view.rerender(<Sentinel enabled onLoadMore={second} />);

    expect(FakeIntersectionObserver.instances).toHaveLength(1);
    expect(observer.observed).toHaveLength(1);
    expect(observer.disconnected).toBe(false);

    act(() => {
      observer.emit(true);
    });
    expect(second).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
  });

  it('哨兵还没挂上时不建立 observer', () => {
    // 挂载顺序反了（或调用方忘了把 ref 传给元素）时不能去 observe(null)。
    renderHook(() => useInfiniteScroll(true, vi.fn()));

    expect(FakeIntersectionObserver.instances).toHaveLength(0);
  });
});

describe('useRovingFocus', () => {
  const VALUES = ['all', 'hot', 'new'] as const;
  type Value = (typeof VALUES)[number];

  function setupRoving(select = vi.fn()) {
    const view = renderHook(() => useRovingFocus(VALUES, select));
    return { select, ...view };
  }

  it('方向键一次性移动选中与焦点，并阻止默认滚动', () => {
    const { result, select } = setupRoving();

    // 上下与左右都接受：横排的分段控件与竖排的设置页签共用同一套键，
    // 用户不需要知道当前控件是横的还是竖的。
    const cases: [key: string, from: number, expected: Value][] = [
      ['ArrowRight', 0, 'hot'],
      ['ArrowDown', 0, 'hot'],
      ['ArrowLeft', 2, 'hot'],
      ['ArrowUp', 2, 'hot'],
    ];

    for (const [key, from, expected] of cases) {
      select.mockClear();
      const { event, preventDefault } = makeEvent(key);

      act(() => {
        result.current.onKeyDown(event, from);
      });

      expect(select).toHaveBeenCalledWith(expected);
      // 方向键在页面里默认是滚动，不阻止的话每按一次列表就跟着跑。
      expect(preventDefault).toHaveBeenCalledTimes(1);
    }
  });

  it('两端环绕', () => {
    const { result, select } = setupRoving();

    act(() => {
      result.current.onKeyDown(makeEvent('ArrowRight').event, VALUES.length - 1);
    });
    expect(select).toHaveBeenCalledWith('all');

    act(() => {
      result.current.onKeyDown(makeEvent('ArrowLeft').event, 0);
    });
    expect(select).toHaveBeenCalledWith('new');
  });

  it('Home / End 跳到首尾', () => {
    const { result, select } = setupRoving();

    act(() => {
      result.current.onKeyDown(makeEvent('End').event, 0);
    });
    expect(select).toHaveBeenCalledWith('new');

    act(() => {
      result.current.onKeyDown(makeEvent('Home').event, VALUES.length - 1);
    });
    expect(select).toHaveBeenCalledWith('all');
  });

  it('焦点跟到目标元素上（不是留在原处）', () => {
    const { result, select } = setupRoving();
    const currentNode = { focus: vi.fn() } as unknown as HTMLElement;
    const targetNode = { focus: vi.fn() } as unknown as HTMLElement;

    act(() => {
      result.current.register('all')(currentNode);
      result.current.register('hot')(targetNode);
      result.current.onKeyDown(makeEvent('ArrowRight').event, 0);
    });

    expect(select).toHaveBeenCalledWith('hot');
    expect(targetNode.focus).toHaveBeenCalledTimes(1);
    expect(currentNode.focus).not.toHaveBeenCalled();
  });

  it('目标元素未注册时只移动选中，不抛错', () => {
    // 整组还没渲染完（或调用方没接 register）时，选中的转移仍应发生，
    // 焦点则交给浏览器/调用方处理。
    const { result, select } = setupRoving();

    act(() => {
      result.current.onKeyDown(makeEvent('ArrowRight').event, 0);
    });

    expect(select).toHaveBeenCalledWith('hot');
  });

  it('注销后不再聚焦到已卸载的元素', () => {
    const { result, select } = setupRoving();
    const node = { focus: vi.fn() } as unknown as HTMLElement;

    act(() => {
      result.current.register('hot')(node);
      // React 卸载时会以 null 调用回调 ref，此时必须从表里删掉，
      // 否则下一次方向键会 focus 到一个已经脱离文档的节点。
      result.current.register('hot')(null);
      result.current.onKeyDown(makeEvent('ArrowRight').event, 0);
    });

    expect(select).toHaveBeenCalledWith('hot');
    expect(node.focus).not.toHaveBeenCalled();
  });

  it('不处理的按键既不移动也不阻止默认行为', () => {
    const { result, select } = setupRoving();

    for (const key of ['Enter', ' ', 'Tab', 'a', 'Escape']) {
      const { event, preventDefault } = makeEvent(key);

      act(() => {
        result.current.onKeyDown(event, 0);
      });

      // 空格/Tab 在单选组里另有语义（Tab 是整组的停靠点），抢掉会破坏键盘导航。
      expect(preventDefault).not.toHaveBeenCalled();
      expect(select).not.toHaveBeenCalled();
    }
  });

  it('空列表不移动也不抛错', () => {
    const select = vi.fn();
    const { result } = renderHook(() => useRovingFocus<string>([], select));

    act(() => {
      result.current.onKeyDown(makeEvent('ArrowRight').event, 0);
      result.current.onKeyDown(makeEvent('Home').event, 0);
    });

    expect(select).not.toHaveBeenCalled();
  });
});
