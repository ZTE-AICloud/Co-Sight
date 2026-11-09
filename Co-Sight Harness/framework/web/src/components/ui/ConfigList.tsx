/**
 * 配置列表的行样式：工作区 / 模型配置 / Agent 代理配置三处共用。
 *
 * 只共享**行的骨架**（标题 + 徽标 + 次要信息 + 右侧操作），不共享状态切换逻辑。
 * 那三块的状态分支（加载中 / 失败 / 空 / 有内容）各自只有几行 JSX，封装成
 * 「传十个 props 的通用面板」反而让每个调用点更难读；真正会漂移的是行高、圆角、
 * 徽标间距这类视觉细节，所以把边界画在样式这一层。
 */

import type { ReactNode } from 'react';

import styles from './ConfigList.module.css';

export interface ConfigListProps {
  /** 列表的无障碍名称。列表本身没有可见标题时（弹窗里的小节标题不在列表内）这是唯一的语义来源。 */
  ariaLabel: string;
  children: ReactNode;
}

export function ConfigList({ ariaLabel, children }: ConfigListProps) {
  return (
    <ul className={styles.list} aria-label={ariaLabel}>
      {children}
    </ul>
  );
}

export interface ConfigRowProps {
  /** 主标题，如模型名称 / 工作区名称 / 代理名称。 */
  title: string;
  /** 标题右侧的徽标（「当前使用」「默认」「已停用」…），用 `<Tag>`。 */
  badges?: ReactNode;
  /** 标题下面的次要信息行（供应商 · 模型标识 / 绑定目录 …）。 */
  meta?: ReactNode;
  /** 右侧操作区，通常是若干 `<Button size="sm">`。 */
  actions: ReactNode;
  /**
   * 有这一项时，标题变成按钮，点它打开该行的只读详情。
   *
   * 为什么让标题本身可点，而不是再加一个「详情」按钮：右侧已经挤着三四个
   * 同尺寸按钮，第四个会让人逐个读过去才知道要点哪个；而"点名字看详情"是
   * 列表的通用手势。做成真正的 `<button>` 而不是给 `<li>` 挂 onClick——
   * 后者键盘 Tab 不到，读屏也念不出来。
   */
  onSelect?: (() => void) | undefined;
  /** 标题按钮的可访问名，如「查看「X」的详情」。`onSelect` 存在时必填。 */
  selectLabel?: string | undefined;
}

export function ConfigRow({ title, badges, meta, actions, onSelect, selectLabel }: ConfigRowProps) {
  /*
   * `title` 属性补全被省略号截断的长名字（工作区名可到 64 字符）。
   * 标题是按钮时那个属性挪到按钮上——`title` 要挂在真正被悬停的元素上。
   */
  const titleNode =
    onSelect === undefined ? (
      <span className={styles.title} title={title}>
        {title}
      </span>
    ) : (
      /*
       * `aria-label` 用「查看「X」的详情」这类模板，而可见文字就是 X 本身。
       * WCAG 2.5.3（标签包含于名称）要求可访问名里包含可见文字——调用方给的
       * 模板必须带上 `{name}`，这一点写在 `selectLabel` 的文档里而不是运行时校验，
       * 因为它是文案约定，不是能在这里兜住的东西。
       */
      <button
        type="button"
        className={styles.titleButton}
        title={title}
        aria-label={selectLabel ?? title}
        onClick={onSelect}
      >
        {title}
      </button>
    );

  return (
    <li className={styles.row}>
      <div className={styles.main}>
        <div className={styles.titleRow}>
          {titleNode}
          {badges}
        </div>
        {meta === undefined ? null : <div className={styles.meta}>{meta}</div>}
      </div>
      <div className={styles.actions}>{actions}</div>
    </li>
  );
}
