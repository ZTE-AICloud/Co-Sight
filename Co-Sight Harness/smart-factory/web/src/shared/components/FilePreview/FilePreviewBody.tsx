/**
 * 预览面板的内容区：按扩展名分流渲染。
 *
 * | 类型 | 渲染 |
 * |---|---|
 * | `.md` | 复用 `<Markdown>`（相对链接 / 图片按**被预览文件所在目录**解析） |
 * | `.html` | `<iframe>` 真渲染；`sandbox` 里**绝不放 allow-same-origin**，脚本能跑但拿不到父页面 |
 * | 图片 / `.svg` | `<img src="/fs/raw/...">` |
 * | 其它文本 | `<pre>` 源码 |
 * | 二进制 / 超大 | 不预览，给下载 |
 *
 * 读取走 `/fs/read`（UTF-8、2 MiB 上限），原始字节走 `/fs/raw`。415（二进制）与
 * 413（过大）都降级成下载出口，不白屏。
 */

import { useEffect, useMemo, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import type { MessageKey, MessageParams } from '../../../i18n/types';
import { isBackendDown } from '../../api/agents';
import { ApiError } from '../../api/client';
import { fsApi } from '../../api/fs';
import type { FsFile } from '../../api/fs';
import {
  classify,
  extensionOf,
  isHtml,
  isMarkdown,
  isTextual,
  labelOf,
} from '../../file-kind';
import { resolveToAbsolute } from '../../file-ref';
import { Icon } from '../Icon';
import { Markdown } from '../Markdown/Markdown';
import { useFilePreview } from './FilePreviewProvider';

export interface FilePreviewBodyProps {
  /** 绝对路径 */
  path: string;
  /** 已由父级读好的内容（FileViewer 复用自己那次 artifacts 读取），不传则自己走 `/fs/read` */
  content?: string;
  /** md / html 的展示方式；其它类型忽略 */
  view?: 'preview' | 'source';
  /** 重新读取信号：变化时重拉一次（图片也跟着换 URL） */
  reloadKey?: number;
  /** 内容区根节点附加类名 */
  className?: string;
}

interface ReadState {
  loading: boolean;
  error: string | null;
  file: FsFile | null;
}

export function FilePreviewBody({
  path,
  content,
  view = 'preview',
  reloadKey = 0,
  className,
}: FilePreviewBodyProps) {
  const { t } = useI18n();
  const preview = useFilePreview();
  const [state, setState] = useState<ReadState>({ loading: false, error: null, file: null });
  const [internalNonce, setInternalNonce] = useState(0);
  const [imageBroken, setImageBroken] = useState(false);

  const kind = classify(path);
  const textual = isTextual(path);
  const rawSrc = fsApi.rawUrl(path);

  /** md 预览里的相对链接按**这个文件所在目录**解析，而不是会话 cwd */
  const baseDir = useMemo(() => {
    const index = path.lastIndexOf('/');
    return index <= 0 ? '/' : path.slice(0, index);
  }, [path]);

  useEffect(() => {
    setImageBroken(false);
    if (!textual || content !== undefined) {
      setState({ loading: false, error: null, file: null });
      return;
    }

    let cancelled = false;
    setState({ loading: true, error: null, file: null });
    void fsApi.read(path).then(
      (file) => {
        if (!cancelled) setState({ loading: false, error: null, file });
      },
      (cause: unknown) => {
        if (!cancelled) {
          setState({ loading: false, error: describeError(cause, path, t), file: null });
        }
      },
    );

    return () => {
      cancelled = true;
    };
  }, [path, textual, content, reloadKey, internalNonce, t]);

  const retry = () => {
    setInternalNonce((current) => current + 1);
    setImageBroken(false);
  };

  const rootClass = `fp-body${className === undefined ? '' : ` ${className}`}`;

  // 图片 / SVG：直接给原始流，不读文本
  if (kind === 'image' || kind === 'svg') {
    if (imageBroken) {
      return (
        <ErrorState
          message={t('filePreview.imageFailed')}
          path={path}
          download={rawSrc}
          onRetry={retry}
          className={rootClass}
        />
      );
    }
    return (
      <div className={`${rootClass} fp-body--image`}>
        <img
          // reloadKey 进 URL：点「重新读取」时浏览器不会拿缓存里的旧图
          src={reloadKey === 0 && internalNonce === 0 ? rawSrc : `${rawSrc}?v=${reloadKey + internalNonce}`}
          alt={path}
          onError={() => setImageBroken(true)}
        />
      </div>
    );
  }

  if (kind === 'binary') {
    return (
      <div className={`${rootClass} fp-empty`}>
        <Icon name="file" size={26} />
        <p>{t('filePreview.binary')}</p>
        <a className="fp-btn" href={rawSrc} download>
          <Icon name="download" size={13} />
          {t('filePreview.download')}
        </a>
      </div>
    );
  }

  // 到这里只剩文本类；`content` 优先（父级已经读过一份）
  const text = content ?? state.file?.content;

  if (content === undefined && state.loading) {
    return (
      <div className={`${rootClass} fp-empty`} aria-busy="true">
        <span className="fp-spinner" aria-hidden="true" />
        <p>{t('filePreview.loading')}</p>
      </div>
    );
  }

  if (content === undefined && state.error !== null) {
    return (
      <ErrorState
        message={state.error}
        path={path}
        download={rawSrc}
        onRetry={retry}
        className={rootClass}
      />
    );
  }

  if (text === undefined) {
    return <div className={`${rootClass} fp-empty`} />;
  }

  if (text === '') {
    return (
      <div className={`${rootClass} fp-empty`}>
        <Icon name="file" size={26} />
        <p>{t('filePreview.empty')}</p>
      </div>
    );
  }

  if (isMarkdown(path) && view === 'preview') {
    return (
      <div className={`${rootClass} fp-body--md`}>
        <Markdown
          text={withFrontmatterBlock(text)}
          fileMentions={{
            // 面板里没有「本轮产物集合」：行内代码保持纯文本，只让显式链接可点
            resolve: () => undefined,
            // 相对链接按被预览文件的目录解析；绝对路径由 resolveToAbsolute 原样放行
            open: (raw) => preview.open(resolveToAbsolute(raw, baseDir) || raw),
            baseDir,
            urlOf: (absolute) => fsApi.rawUrl(absolute),
          }}
        />
      </div>
    );
  }

  if (isHtml(path) && view === 'preview') {
    return (
      <div className={`${rootClass} fp-body--html`}>
        {/*
          allow-same-origin 绝不能加：加了就是「脚本 + 同源 = 可访问父页面」，
          sandbox 等于白设。allow-downloads 让本地报告里的导出按钮可用。
        */}
        <iframe
          key={`${path}:${String(reloadKey)}:${String(internalNonce)}`}
          src={rawSrc}
          title={path}
          sandbox="allow-scripts allow-forms allow-popups allow-downloads"
        />
      </div>
    );
  }

  return (
    <div className={`${rootClass} fp-body--code`}>
      <div className="fp-code-bar">
        <span className="fp-lang">{labelOf(path)}</span>
        <span className="fp-ext">{extensionOf(path) || 'text'}</span>
      </div>
      <pre className="fp-code">{text}</pre>
    </div>
  );
}

/**
 * YAML frontmatter 先包成围栏代码块再交给 Markdown。
 *
 * 不这样做的话：`---` 会被当成分隔线 / setext 标题下划线，整段 `name: xxx`
 * 变成一个大号标题 —— agent 产物里的 `SKILL.md`、`build-plan.md` 几乎都带 frontmatter，
 * 这是预览里最常看到的一种文件。包里之后它就是一段普通的 yaml 代码块。
 *
 * 只认文件**开头**、且能找到配对 `---` 行的；普通正文里的水平线不受影响。
 */
function withFrontmatterBlock(text: string): string {
  const normalized = text.replace(/\r\n/gu, '\n');
  // 配对行必须自己占一行（`---` 后面除了换行没有别的东西）
  const match = /^---\n([\s\S]*?)\n---(?:\n|$)/u.exec(normalized);
  if (match === null) return text;

  return `\`\`\`yaml\n${match[1]}\n\`\`\`\n\n${normalized.slice(match[0].length)}`;
}

/* ---------- 错误态 ---------- */

type Translate = (key: MessageKey, params?: MessageParams) => string;

function describeError(cause: unknown, path: string, t: Translate): string {
  if (cause instanceof ApiError) {
    if (isBackendDown(cause)) return t('filePreview.serviceDown');
    if (cause.status === 404) return t('filePreview.missing', { path });
    if (cause.status === 413) return t('filePreview.tooLarge');
    if (cause.status === 415) return t('filePreview.binary');
    return t('filePreview.readFailed', { message: cause.message, status: cause.status });
  }
  return cause instanceof Error ? cause.message : t('filePreview.readFailedGeneric');
}

function ErrorState({
  message,
  path,
  download,
  onRetry,
  className,
}: {
  message: string;
  path: string;
  download: string;
  onRetry: () => void;
  className: string;
}) {
  const { t } = useI18n();
  return (
    <div className={`${className} fp-empty fp-empty--error`} role="alert">
      <Icon name="alert" size={22} />
      <p>{message}</p>
      <code className="fp-error-path" title={path}>
        {path}
      </code>
      <div className="fp-empty-actions">
        <button type="button" className="fp-btn" onClick={onRetry}>
          <Icon name="refresh" size={13} />
          {t('filePreview.retry')}
        </button>
        <a className="fp-btn" href={download} download>
          <Icon name="download" size={13} />
          {t('filePreview.download')}
        </a>
      </div>
    </div>
  );
}
