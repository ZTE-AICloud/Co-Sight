/**
 * 右侧文件预览面板的状态：打开了哪些 tab、当前是哪个。
 *
 * 为什么是页面级 context 而不是某个组件自己的 state：
 * 对话里的四处入口（行内代码、Markdown 链接、工具条目、附件 chip）都要能开文件，
 * 面板本身又挂在页面根上。状态放在两者共同的祖先，入口只管 `open(path)`。
 *
 * **tab 的 id 就是绝对路径**：同一文件点两次天然去重。相对路径在 `open` 里当场
 * 解析成绝对路径（基址是 Provider 的 `baseDir`）—— 之后切阶段、换目录都不会
 * 把已经打开的 tab 解释到别处去。
 *
 * `baseDir` 为 null（详情还没回来）时，相对路径打不开，但绝对路径仍然可以 ——
 * 已发附件 chip 本来就是绝对路径，不该被「智能体详情还在加载」挡住。
 */

import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { resolveToAbsolute } from '../../file-ref';

export interface FilePreviewContextValue {
  /** 相对路径的解析基址：会话 cwd（`<agentDir>/<stage>`）；null = 还不知道 */
  baseDir: string | null;
  /** Provider 真的挂上了（没有 Provider 的 demo / 首页里 FileChip 保持原样） */
  enabled: boolean;
  /** 基址已就绪：行内代码的文件引用只在这之后启用 */
  ready: boolean;
  tabs: readonly string[];
  active: string | null;
  /** 打开一个文件（绝对路径原样，相对路径按 baseDir 解析）；已有的只聚焦 */
  open: (path: string) => void;
  /** 不带参数 = 关掉整个面板（清空 tab）；带路径 = 只关那个 tab */
  close: (path?: string) => void;
  /** 聚焦一个已经打开的 tab；没打开则打开 */
  focus: (path: string) => void;
}

const NOOP = () => {
  // 没有 Provider 时的空实现：FileChip 等在首页 / demo 里保持纯展示
};

const DEFAULT_VALUE: FilePreviewContextValue = {
  baseDir: null,
  enabled: false,
  ready: false,
  tabs: [],
  active: null,
  open: NOOP,
  close: NOOP,
  focus: NOOP,
};

const FilePreviewContext = createContext<FilePreviewContextValue>(DEFAULT_VALUE);

export function useFilePreview(): FilePreviewContextValue {
  return useContext(FilePreviewContext);
}

/**
 * 造一份 Provider 的值。
 *
 * 单独一个 hook 而不是让 Provider 自己持有状态：页面根 `.ac` 要根据
 * 「有没有打开的文件」挂 `ac--dock-open`（给内容让出右侧宽度），而页面本身
 * 在 Provider 外面 —— 只能先有值、再包 Provider。
 */
export function useFilePreviewState(baseDir: string | null): FilePreviewContextValue {
  const [tabs, setTabs] = useState<string[]>([]);
  const [active, setActive] = useState<string | null>(null);

  const open = useCallback(
    (raw: string) => {
      const absolute = resolveToAbsolute(raw, baseDir ?? '');
      if (absolute === '') return;

      setTabs((previous) =>
        previous.includes(absolute) ? previous : [...previous, absolute],
      );
      setActive(absolute);
    },
    [baseDir],
  );

  const close = useCallback(
    (path?: string) => {
      if (path === undefined) {
        setTabs([]);
        setActive(null);
        return;
      }

      const index = tabs.indexOf(path);
      if (index < 0) return;
      const next = tabs.filter((tab) => tab !== path);
      setTabs(next);
      setActive((current) =>
        current === path ? (next[Math.min(index, next.length - 1)] ?? null) : current,
      );
    },
    [tabs],
  );

  const focus = useCallback((path: string) => {
    setTabs((previous) => (previous.includes(path) ? previous : [...previous, path]));
    setActive(path);
  }, []);

  return useMemo(
    () => ({
      baseDir,
      enabled: true,
      ready: baseDir !== null,
      tabs,
      active,
      open,
      close,
      focus,
    }),
    [baseDir, tabs, active, open, close, focus],
  );
}

export function FilePreviewProvider({
  value,
  children,
}: {
  value: FilePreviewContextValue;
  children: ReactNode;
}) {
  return <FilePreviewContext.Provider value={value}>{children}</FilePreviewContext.Provider>;
}
