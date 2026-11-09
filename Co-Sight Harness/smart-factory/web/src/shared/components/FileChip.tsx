/**
 * 附件 chip：**同一个文件在全站只有一种长相**。
 *
 * 三处会显示一条本地路径 —— 首页发送框（行内 token）、设计页发送框（正文外一行）、
 * 对话气泡下方（已发出的消息）。位置和字号不同，但「紫色文件徽标 + 文件名 + 悬停看全路径」
 * 这条规则一样，所以标记、文件名规则和样式都从这里出，别在页面里各写一份。
 *
 * 行内 token 不能用 React 渲染（它在 contenteditable 里，见 Composer 文件头），
 * 所以徽标的 SVG 同时以字符串形态导出（FILE_BADGE_SVG），DOM 那边直接 innerHTML。
 */

import { fileNameOf } from '../file-name';
import { useFilePreview } from './FilePreview/FilePreviewProvider';
import { Icon } from './Icon';
import './FileChip.css';

/** 徽标骨架与 Icon 的 `file` 同源：紫色文档 + 白色括号 */
const BADGE_BODY = 'M6 3h8l4 4v14H6z';
const BADGE_GLYPH = 'M10.6 11.5L9 13l1.6 1.5M13.4 11.5L15 13l-1.6 1.5';
const BADGE_COLOR = '#8c75ff';

/** 字符串形态：行内 token 在 DOM 上自己拼，用不了 JSX（见文件头） */
export const FILE_BADGE_SVG =
  '<svg class="file-badge" width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">' +
  `<path d="${BADGE_BODY}" fill="${BADGE_COLOR}" />` +
  `<path d="${BADGE_GLYPH}" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />` +
  '</svg>';

export function FileBadge({ size = 15 }: { size?: number }) {
  return (
    <svg className="file-badge" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d={BADGE_BODY} fill={BADGE_COLOR} />
      <path
        d={BADGE_GLYPH}
        fill="none"
        stroke="#fff"
        strokeWidth={1.7}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export interface FileChipProps {
  /** **绝对路径**：显示只用最后一段，完整路径挂 title */
  path: string;
  /** md = 发送框里的待发附件；sm = 对话气泡下方的已发附件 */
  size?: 'md' | 'sm';
  className?: string;
  /** 待发附件的移除按钮；已发出的消息没有它 */
  remove?: { label: string; disabled?: boolean; onRemove: () => void };
}

export function FileChip({ path, size = 'md', className, remove }: FileChipProps) {
  const preview = useFilePreview();
  /** 已发出的附件（对话气泡下那条）在预览面板挂上时可点开；待发附件仍只负责移除 */
  const clickable = remove === undefined && preview.enabled;

  const content = (
    <>
      <FileBadge size={size === 'sm' ? 12 : 14} />
      <span className="file-chip__name">{fileNameOf(path)}</span>
      {remove !== undefined && (
        <button
          type="button"
          className="file-chip__x"
          aria-label={remove.label}
          disabled={remove.disabled}
          onClick={remove.onRemove}
        >
          <Icon name="close" size={12} />
        </button>
      )}
    </>
  );

  if (clickable) {
    return (
      <button
        type="button"
        className={`file-chip file-chip--${size} file-chip--button${className ? ` ${className}` : ''}`}
        title={path}
        onClick={() => preview.open(path)}
      >
        {content}
      </button>
    );
  }

  return (
    <span
      className={`file-chip file-chip--${size}${className ? ` ${className}` : ''}`}
      title={path}
    >
      {content}
    </span>
  );
}
