/**
 * 通用内联图标集。
 *
 * 骨架期不引图标库：统一 24×24 viewBox + 1.7 stroke 描边，颜色走 currentColor，
 * 尺寸由 size 控制。原本长在 features/home 下，首页和智能体创建页都要用，
 * 按 docs/architecture.md 的约定上升到 shared。
 */

export type IconName =
  // 领域语义
  | 'message'
  | 'sparkle'
  | 'blocks'
  | 'flow'
  | 'book'
  | 'plug'
  | 'terminal'
  | 'prompt'
  | 'play'
  | 'pause'
  | 'activity'
  | 'list'
  | 'search'
  | 'clock'
  | 'shield'
  | 'chart'
  | 'server'
  | 'cloud'
  | 'code'
  | 'bug'
  | 'gauge'
  | 'layers'
  | 'database'
  | 'wand'
  | 'gitBranch'
  // 文件
  | 'file'
  | 'fileCode'
  | 'folder'
  | 'folderOpen'
  | 'paperclip'
  // 界面
  | 'plus'
  | 'close'
  | 'check'
  | 'alert'
  | 'chevronRight'
  | 'chevronDown'
  | 'arrowUp'
  | 'arrowLeft'
  | 'refresh'
  | 'download'
  | 'copy'
  | 'edit'
  | 'trash'
  | 'eye'
  | 'zap';

/** 每条线一个 path，多段子路径用 M 分隔，保持单标签好维护。 */
const PATHS: Record<IconName, string> = {
  message: 'M4 4h16v12h-8l-4 4v-4H4V4z',
  sparkle:
    'M11 3l1.7 4.6L17.3 9.3l-4.6 1.7L11 15.6 9.3 11 4.7 9.3 9.3 7.6 11 3zM18 15l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7.7-1.9z',
  blocks: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  flow: 'M5 4h5v4H5zM14 16h5v4h-5zM7.5 8v6a2 2 0 0 0 2 2H14',
  book: 'M5 4h13v16H5zM9 4v16',
  plug: 'M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0V8zM12 17v4',
  terminal: 'M4 5h16v14H4zM8 10l3 2.5-3 2.5M13 15h3',
  prompt: 'M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h3',
  play: 'M8 5l11 7-11 7V5z',
  pause: 'M9 5v14M15 5v14',
  activity: 'M3 12h4l3-7 4 14 3-7h4',
  list: 'M4 6h16M4 12h16M4 18h9',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM16.5 16.5L21 21',
  clock: 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 7.5V12l3 2',
  shield: 'M12 3l7 3v6c0 4.2-3 7.4-7 9-4-1.6-7-4.8-7-9V6l7-3z',
  chart: 'M5 20V10M12 20V4M19 20v-7',
  server: 'M3 5h18v5H3zM3 14h18v5H3zM7 7.5h1M7 16.5h1',
  cloud: 'M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z',
  code: 'M8 8l-4 4 4 4M16 8l4 4-4 4M13.5 5l-3 14',
  bug: 'M8 8a4 4 0 0 1 8 0v5a4 4 0 0 1-8 0V8zM3 11h3M18 11h3M3 16h4M17 16h4M5 6l3 2M19 6l-3 2',
  gauge: 'M4 18a8 8 0 1 1 16 0M12 14l4-4',
  layers: 'M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17l9 5 9-5',
  database: 'M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
  wand: 'M4 20l11-11M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1 1-2zM19 12l.7 1.3 1.3.7-1.3.7-.7 1.3-.7-1.3-1.3-.7 1.3-.7.7-1.3z',
  gitBranch: 'M7 4v10a3 3 0 0 0 3 3h4M7 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5M17 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5M17 7v4',
  file: 'M6 3h8l4 4v14H6zM14 3v4h4',
  fileCode: 'M6 3h8l4 4v14H6zM14 3v4h4M10 12l-2 2 2 2M14 12l2 2-2 2',
  folder: 'M3 6h6l2 2h10v11H3z',
  folderOpen: 'M3 6h6l2 2h10v3M3 6v13h18l-2-9H3z',
  paperclip: 'M20.4 11.5l-8.6 8.6a5.3 5.3 0 0 1-7.5-7.5l8.6-8.6a3.5 3.5 0 0 1 5 5l-8.6 8.6a1.8 1.8 0 0 1-2.5-2.5l7.6-7.6',
  plus: 'M12 5v14M5 12h14',
  close: 'M6 6l12 12M18 6L6 18',
  check: 'M4 12.5L9.5 18 20 6.5',
  alert: 'M12 4l9 16H3l9-16zM12 10v5M12 18h.01',
  chevronRight: 'M9 6l6 6-6 6',
  chevronDown: 'M6 9l6 6 6-6',
  arrowUp: 'M12 19V5M6 11l6-6 6 6',
  arrowLeft: 'M19 12H5M11 6l-6 6 6 6',
  refresh: 'M20 12a8 8 0 1 1-2.3-5.7M20 4v4h-4',
  download: 'M12 4v11M7 11l5 5 5-5M4 20h16',
  copy: 'M8 8h12v12H8zM4 16V4h12',
  edit: 'M4 20h4L19.4 8.6a2.2 2.2 0 0 0-3.1-3.1L5 17l-1 3zM14.9 7.1l3.1 3.1',
  trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6',
  eye: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  zap: 'M13 3L5 14h6l-1 7 8-11h-6l1-7z',
};

/**
 * 取某个图标的一段 path。
 *
 * 给「没有 React 渲染通道、只能手搓 DOM」的地方用：发送框的行内附件 chip 要直接插进
 * contenteditable（见 Composer.tsx），那里的 SVG 只能拿字符串拼。
 * 只吐 d 属性，不吐整个 <svg> —— 线宽、命名空间由调用方照 Icon 的样子补。
 */
export function iconPath(name: IconName): string {
  return PATHS[name];
}

/*
 * 这里曾经有 `hasIcon` / `pickIcon`：把后端返回的一串图标名兜成图标集里认识的某个名字。
 *
 * 随 `Agent.icon` 从「图标名」改成「封面图的 HTTP 地址」（契约 5.01）一起删掉了 ——
 * 现在后端的 icon 不是图标集里的名字，没有「认不认识这个名字」这回事。
 * 拿不到图时的兜底是「名称首字」，在 shared/components/AgentAvatar 里。
 */

interface IconProps {
  name: IconName;
  /** 渲染边长，默认 16 */
  size?: number;
}

export function Icon({ name, size = 16 }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
