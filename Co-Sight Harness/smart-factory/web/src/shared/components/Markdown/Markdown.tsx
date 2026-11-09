/**
 * 消息正文的 Markdown 渲染。
 *
 * 模型回复一律是 Markdown（标题、列表、表格、代码块），旧版把 `text` 直接塞进
 * `white-space: pre-wrap` 的 div 里，于是 `### 标题` 和 `**加粗**` 都按字面显示 ——
 * 这个组件只做一件事：把那段文本按 Markdown 渲染成可读的排版。
 *
 * 为什么引 react-markdown 而不是手写解析：
 *   - 要的不只是「几行正则」：嵌套列表、GFM 表格、任务列表、代码围栏的边界情况
 *     都容易在流式输出（文本随时可能截断在半条语法里）下露馅；
 *   - 它把 Markdown 转成 **React 元素**而不是 HTML 字符串，天然没有 innerHTML 注入面，
 *     URL 还会过一遍 `defaultUrlTransform`（`javascript:` 之类会被抹成空串）；
 *     模型输出里的原始 HTML（`<script>`、`<br>`）按字面文本显示 —— **没接 rehype-raw**，
 *     这是有意的安全默认值。这几条是手写渲染器最容易做漏的地方。
 *
 * 只给助手正文用：用户的提问是他自己敲的纯文本（见 Turn.tsx 的 Ask），
 * 按 Markdown 解释会把 `*`、`#` 这类字符吃掉；结算行同理，它是一句系统文案。
 *
 * 流式输出每来一帧就整段重解析一次。react-markdown 是同步的，截断的语法（比如还没
 * 闭合的 ``` 围栏）会按「剩余内容都是代码块」渲染，不会抛错；代价是长回复时每帧
 * 有一点解析开销，相对它的正确性，这个取舍是划算的。用 memo 挡住「展开/收起过程」
 * 这种与正文无关的重渲染，避免重复解析。
 */

import { memo, useEffect, useMemo, useRef, useState } from 'react';
import type { ComponentPropsWithoutRef, ReactElement, ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components, ExtraProps } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useI18n } from '../../../i18n/useI18n';
import { resolveToAbsolute } from '../../file-ref';
import { Icon } from '../Icon';
import './Markdown.css';

/**
 * 文件引用接入。
 *
 * 不传时组件完全保持旧行为（demo / 首页的 Markdown 不受影响）；
 * 传了才把「本地链接」「命中的行内代码」「相对图片」变成可点 / 可加载的东西。
 */
export interface MarkdownFileMentions {
  /**
   * 行内代码 → 目标绝对路径。返回 undefined 表示「保持纯文本」。
   *
   * 判定不在 Markdown 里做：调用方手里才有「本轮写过的文件」集合（见 file-ref.ts）。
   */
  resolve(value: string): string | undefined;
  /** 打开一个文件。入参是链接原文 / `resolve` 的返回值，解析由调用方负责 */
  open(raw: string): void;
  /** 相对图片 / 链接的解析基准：被预览文件所在目录 */
  baseDir?: string;
  /** 绝对路径 → 可访问 URL（预览面板里是 `/fs/raw/...`），用于相对图片 */
  urlOf?: (path: string) => string;
}

export interface MarkdownProps {
  /** Markdown 源文本 */
  text: string;
  /** 附加在外层 div 上的类名，用来承接调用处的排版基线 */
  className?: string;
  /** 文件引用接入；不传 = 纯 Markdown */
  fileMentions?: MarkdownFileMentions;
}

/**
 * 插件表放在模块级：数组一旦每次渲染重建，react-markdown 内部就认不出「插件没变」，
 * 等于每帧都重新初始化一遍解析器。
 */
const REMARK_PLUGINS = [remarkGfm];

export const Markdown = memo(function Markdown({ text, className, fileMentions }: MarkdownProps) {
  /*
   * components 只在有 fileMentions 时才另造一份。对象身份变了 react-markdown 不会重新
   * 初始化解析器（插件表才影响初始化），所以这里用 useMemo 只是省掉每帧新建三个函数。
   */
  const components = useMemo(
    () =>
      fileMentions === undefined
        ? COMPONENTS
        : {
            ...COMPONENTS,
            a: linkComponent(fileMentions),
            code: codeComponent(fileMentions),
            img: imageComponent(fileMentions),
          },
    [fileMentions],
  );

  return (
    <div className={className === undefined ? 'md' : `md ${className}`}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
});

/* ---------- 元素映射 ---------- */

const COMPONENTS: Components = {
  // 外链新开一页：对话栏是应用主区域，点个文档链接把整个会话顶掉不合适。
  // 相对链接在没有 fileMentions 时保持原样（demo 里的 Markdown 不该改变行为）。
  a: ({ node: _node, href, children, ...rest }) => {
    const external = typeof href === 'string' && /^https?:\/\//i.test(href);
    return (
      <a
        href={href}
        {...rest}
        {...(external ? { target: '_blank', rel: 'noreferrer noopener' } : {})}
      >
        {children}
      </a>
    );
  },

  // 代码块换成「语言标签 + 复制」的头 + 可横向滚动的 pre。
  // 只在 pre 这层动手：行内 code 没有外面这个 pre，默认渲染即可。
  pre: Pre,

  // 表格给一层横向滚动容器：窄栏（创建页可以拖到 300px）下宽表格不许把对话栏顶破
  table: ({ node: _node, children, ...rest }) => (
    <div className="md-table">
      <table {...rest}>{children}</table>
    </div>
  ),

  img: Image,
};

/**
 * 本地链接：渲染成文件按钮，点击交给面板。
 *
 * 显式链接**不再查产物集合** —— 用户 / 模型明确写了链接就按它打开，路径错由后端 404 兜底。
 * 以前相对链接被原样放行，会触发 SPA 路由跳转，被 `*` 兜底静默送回首页（见 App.tsx 的警告）。
 * `#L24` 这类片段先剥掉，本期不做行号定位。
 */
function linkComponent(fileMentions: MarkdownFileMentions): NonNullable<Components['a']> {
  return ({ node: _node, href, children, ...rest }) => {
    if (isLocalHref(href)) {
      const target = href.replace(/#.*$/u, '');
      if (target !== '') {
        return (
          <button
            type="button"
            className="md-file-mention md-file-mention--link"
            title={href}
            onClick={() => fileMentions.open(target)}
          >
            <Icon name="file" size={11} />
            {children}
          </button>
        );
      }
    }

    const external = typeof href === 'string' && /^https?:\/\//i.test(href);
    return (
      <a
        href={href}
        {...rest}
        {...(external ? { target: '_blank', rel: 'noreferrer noopener' } : {})}
      >
        {children}
      </a>
    );
  };
}

/**
 * 行内代码：命中本轮产物才变成文件按钮。
 *
 * react-markdown 对行内 code 与代码块里的 code 用同一个组件，且不给「是不是行内」的标记。
 * 判据按方案定的：**没有 `language-` 类、且内容不含换行**才算行内。代价是「单行、没写语言」
 * 的围栏块理论上会被误判 —— 但它还得同时命中产物集合，实际不会发生。
 */
function codeComponent(fileMentions: MarkdownFileMentions): NonNullable<Components['code']> {
  return ({ node: _node, className, children, ...rest }) => {
    const text = textOf(children);
    const hasLanguage = typeof className === 'string' && /(?:^|\s)language-/u.test(className);

    if (!hasLanguage && !text.includes('\n')) {
      const target = fileMentions.resolve(text);
      if (target !== undefined) {
        return (
          <button
            type="button"
            className="md-file-mention"
            title={target}
            onClick={() => fileMentions.open(target)}
          >
            <Icon name="file" size={11} />
            {children}
          </button>
        );
      }
    }

    return (
      <code className={className} {...rest}>
        {children}
      </code>
    );
  };
}

/** 相对图片改写成本地原始流地址（`/fs/raw/...`）；外链 / data URL 原样保留 */
function imageComponent(fileMentions: MarkdownFileMentions): NonNullable<Components['img']> {
  return ({ node: _node, src, alt, ...rest }) => {
    const resolved =
      typeof src === 'string' &&
      isRelativeSrc(src) &&
      fileMentions.baseDir !== undefined &&
      fileMentions.urlOf !== undefined
        ? fileMentions.urlOf(resolveToAbsolute(src, fileMentions.baseDir))
        : src;
    return <img {...rest} src={resolved} alt={alt ?? ''} loading="lazy" />;
  };
}

function Image({ node: _node, alt, ...rest }: ComponentPropsWithoutRef<'img'> & ExtraProps) {
  // alt 缺失时给空串：装饰性图片对读屏器报文件名反而更吵
  return <img {...rest} alt={alt ?? ''} loading="lazy" />;
}

/** 不是外链 / 锚点 / data: 的链接就是本地路径；`file://` 也算本地 */
function isLocalHref(href: string | undefined): href is string {
  if (typeof href !== 'string' || href === '') return false;
  if (href.startsWith('#')) return false;
  if (href.startsWith('//')) return false;

  const scheme = /^([a-z][a-z0-9+.-]*):/iu.exec(href)?.[1]?.toLowerCase();
  if (scheme === undefined) return true;
  return scheme === 'file';
}

function isRelativeSrc(src: string): boolean {
  if (src.startsWith('/') || src.startsWith('//')) return false;
  return !/^[a-z][a-z0-9+.-]*:/iu.test(src);
}

/* ---------- 代码块 ---------- */

type PreProps = ComponentPropsWithoutRef<'pre'> & ExtraProps;

function Pre({ node: _node, children, ...rest }: PreProps) {
  const language = languageOf(children);
  const text = textOf(children);

  return (
    <div className="md-code">
      <div className="md-code__bar">
        <span className="md-code__lang">{language ?? 'text'}</span>
        {text !== '' && <CopyButton text={text} />}
      </div>
      <pre {...rest} className="md-code__pre">
        {children}
      </pre>
    </div>
  );
}

const COPY_RESET_MS = 1500;

function CopyButton({ text }: { text: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  // 卸载时清掉待触发的复位定时器：流式输出里代码块可能整块被重排掉
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  function copy() {
    void navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        if (timer.current !== null) window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => setCopied(false), COPY_RESET_MS);
      })
      .catch(() => {
        // 非安全上下文下剪贴板不可用：静默失败，不改按钮文案
      });
  }

  return (
    <button type="button" className="md-code__copy" onClick={copy}>
      <Icon name={copied ? 'check' : 'copy'} size={11} />
      {copied ? t('common.copied') : t('common.copy')}
    </button>
  );
}

/** 从 `<pre><code className="language-ts">…` 里取语言；没写围栏语言时给 undefined */
function languageOf(children: ReactNode): string | undefined {
  const code = Array.isArray(children) ? children[0] : children;
  if (code === null || typeof code !== 'object' || !('props' in code)) return undefined;

  const className = (code as ReactElement<{ className?: string }>).props.className;
  if (typeof className !== 'string') return undefined;

  return /(?:^|\s)language-([\w+-]+)/.exec(className)?.[1];
}

/**
 * 把 React 子树还原成纯文本（剪贴板要的是源码，不是渲染结果）。
 *
 * 代码块只会包含字符串 / 数字 / 元素 / 数组这几种节点，递归够用；注释之类不会出现在这里。
 */
function textOf(node: ReactNode): string {
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  if (node !== null && typeof node === 'object' && 'props' in node) {
    return textOf((node as ReactElement<{ children?: ReactNode }>).props.children);
  }
  return '';
}
