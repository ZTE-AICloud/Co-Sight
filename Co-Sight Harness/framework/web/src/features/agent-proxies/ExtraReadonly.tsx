/**
 * 模块私有配置（`extra`）的只读展示。
 *
 * 这里是**模块自己读写**的透传字段（见 agent-proxy 契约的开头）：框架既不知道
 * 有哪些键、也不知道值的含义，所以只能显示。展示成只读有一处特别要紧——
 * 用户看到输入框就会去改，改完保存却发现键没了（框架不认识它们，`PATCH` 里
 * 也送不回去），那比"这里不给改"难解释得多。因此这里不是"禁用的输入框"，
 * 而是**根本不是输入框**。
 *
 * 空对象时**整块不渲染**：一个只有标题、没有任何内容的区块，会让人以为加载坏了。
 */

import { Fragment } from 'react';

import { useI18n } from '../../i18n/useI18n';
import panelStyles from '../config/config.module.css';

export interface ExtraReadonlyProps {
  extra: Record<string, unknown>;
}

/**
 * 把任意一个 JSON 值显示成一行文字。
 *
 * 值来自模块，类型是 `unknown`（契约里就是 `z.unknown()`）：可能是字符串、数字，
 * 也可能是嵌套对象。字符串原样显示而不是加引号——那是最常见的一种，加了引号
 * 反而像是数据里真的有引号。其余一律走 `JSON.stringify`，它给出的才是模块
 * 存进去的那份结构。
 */
export function formatExtraValue(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  if (value === null) {
    return 'null';
  }
  const json = JSON.stringify(value);
  // `JSON.stringify` 对函数与 undefined 返回 undefined（它们本来也不是 JSON 值）。
  return json ?? String(value);
}

export function ExtraReadonly({ extra }: ExtraReadonlyProps) {
  const { t } = useI18n();

  /*
   * 键排序：同一份配置每次打开的顺序一致，读起来才像同一块内容。
   * 用 `toSorted` 而不是 `sort`：`Object.entries` 每次都给新数组，但 `sort` 会就地
   * 改它——现在无害，将来有人把这份 entries 挪到别处复用就成了隔空改数据。
   */
  const entries = Object.entries(extra).toSorted(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));

  if (entries.length === 0) {
    return null;
  }

  return (
    <section className={panelStyles.extra}>
      <h4 className={panelStyles.extraTitle}>{t('settings.agentProxy.extra.title')}</h4>
      <p className={panelStyles.extraHint}>{t('settings.agentProxy.extra.hint')}</p>
      {/*
       * `dt`/`dd` 直接是 `<dl>` 的子元素，外面**不包**一层 div：`.extraList` 的两列
       * 栅格是挂在这两个元素上的，中间多一层盒子会把它们各自的列宽规则一起吃掉。
       * 需要 key 的话用 `Fragment`——它不产生 DOM 节点。
       */}
      <dl className={panelStyles.extraList}>
        {entries.map(([key, value]) => (
          <Fragment key={key}>
            <dt className={panelStyles.extraTerm}>{key}</dt>
            <dd className={panelStyles.extraValue}>{formatExtraValue(value)}</dd>
          </Fragment>
        ))}
      </dl>
    </section>
  );
}
