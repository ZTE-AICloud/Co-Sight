/**
 * 折叠体里的一条过程条目：技能轨迹 / 工具调用 / 思考。
 *
 * 行本身是个按钮：短摘要直接显示在行上（单行省略），完整内容点开才铺在下面。
 * 这是相对旧版的一处有意的取舍 —— 旧版把 detail 恒显，四条轨迹时信息更全，
 * 四十条时整栏被撑爆。折叠本就是这一版的目的，所以按后者选。
 *
 * 工具调用的摘要优先取 `command` / `file_path` 这类人一眼能认的字段；展开后才给完整
 * 入参与输出。输出可能是字符串，也可能是 SDK 的 `[{type:'text',text}]` 内容块数组，
 * 所以不能直接 `String(output)`。
 */

import { useI18n } from '../../../i18n/useI18n';
import type { MessageKey, MessageParams } from '../../../i18n/types';
import { pathOfToolInput } from '../../file-ref';
import { Icon } from '../Icon';
import { useFilePreview } from '../FilePreview/FilePreviewProvider';
import type { StepStatus, TurnEntry } from './types';

type Translate = (key: MessageKey, params?: MessageParams) => string;

/**
 * 这些工具的 `path` 参数指的是**目录**（或根本不产出文件）：摘要不接预览。
 * `Read` / `Write` / `Edit` / `NotebookEdit` 用的是 `file_path` / `notebook_path`，不受影响。
 */
const DIRECTORY_TOOLS = new Set(['Glob', 'Grep', 'LS', 'GlobTool', 'GrepTool', 'List']);

export interface EntryProps {
  entry: TurnEntry;
  /** 明细是否展开 */
  open: boolean;
  onToggle: () => void;
}

export function Entry({ entry, open, onToggle }: EntryProps) {
  const { t } = useI18n();
  const preview = useFilePreview();
  // 没有明细就没什么可展开的：这一行退化成纯展示，不给它按不动的按钮观感
  const expandable = hasDetail(entry);
  const summary = summaryOf(entry);

  /**
   * 工具调用里如果有路径（`file_path` / `path` / `notebook_path`），摘要变成可点链接。
   *
   * 只有 Provider 挂上时才接：首页 / demo 里 Entry 保持纯展示。
   * 排除「`path` 参数是目录」的工具（Glob / Grep / LS）：点开一个目录只会得到
   * 后端的「不是文件」400，不如不做链接。
   */
  const filePath =
    entry.kind === 'tool' && preview.enabled && !DIRECTORY_TOOLS.has(entry.toolName)
      ? pathOfToolInput(entry.input)
      : undefined;

  const lineClass = `conversation__entry-line conversation__entry-line--${entry.status}`;
  const inner = (
    <>
      <span className="conversation__entry-lead">{lead(entry.status)}</span>
      <span className="conversation__entry-name">{nameOf(entry, t)}</span>
      {summary !== undefined &&
        (filePath === undefined ? (
          <span className="conversation__entry-text">{summary}</span>
        ) : (
          <button
            type="button"
            className="conversation__entry-text conversation__entry-file"
            title={filePath}
            onClick={(event) => {
              // 整行是折叠条：开文件不能顺带把过程展开 / 收起
              event.stopPropagation();
              preview.open(filePath);
            }}
          >
            {summary}
          </button>
        ))}
      {expandable && (
        <span className="conversation__caret">
          <Icon name="chevronDown" size={12} />
        </span>
      )}
    </>
  );

  return (
    <div className="conversation__entry">
      {filePath === undefined ? (
        <button
          type="button"
          className={lineClass}
          aria-expanded={expandable ? open : undefined}
          disabled={!expandable}
          onClick={onToggle}
        >
          {inner}
        </button>
      ) : (
        /*
         * 有文件路径时外层改成 div + role="button"：里面还要放一个真正的按钮，
         * 按钮不能嵌套按钮。键盘操作在这里补（Enter / Space 仍然折叠）。
         */
        <div
          className={lineClass}
          role="button"
          tabIndex={0}
          aria-expanded={expandable ? open : undefined}
          onClick={onToggle}
          onKeyDown={(event) => {
            // 只在折叠条本体上响应：里面还有一个文件按钮，它的 Enter / Space 会冒泡到这里，
            // 不挡就会「点开文件顺带把过程折叠一次」
            if (event.target !== event.currentTarget) return;
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            onToggle();
          }}
        >
          {inner}
        </div>
      )}

      {expandable && open && (
        <div
          className={`conversation__entry-detail${
            entry.kind === 'tool' ? ' conversation__entry-detail--tool' : ''
          }`}
        >
          {detailOf(entry, t)}
        </div>
      )}
    </div>
  );
}

/**
 * 条目左侧的状态引导件。
 *
 * 沿用旧版 ac-trace-status 的四态语义（绿勾 / 红叉 / 转圈 / 灰点），只是颜色改走
 * global.css 的状态 token —— 共享组件里不该再写死 #10b981 这种 feature 方言。
 */
function lead(status: StepStatus) {
  if (status === 'done') return <Icon name="check" size={13} />;
  if (status === 'failed') return <Icon name="close" size={13} />;
  if (status === 'running') return <span className="conversation__spin" />;
  return <span className="conversation__entry-dot" />;
}

function nameOf(entry: TurnEntry, t: Translate): string {
  if (entry.kind === 'skill') return entry.skill;
  if (entry.kind === 'thinking') return t('conversation.entry.thinking');
  return entry.toolName;
}

/** 行上的单行摘要 */
function summaryOf(entry: TurnEntry): string | undefined {
  if (entry.kind === 'skill') return entry.detail;
  if (entry.kind === 'thinking') return collapse(entry.text) || undefined;
  return summarizeInput(entry.input) ?? summarizeOutput(entry.output);
}

function hasDetail(entry: TurnEntry): boolean {
  if (entry.kind === 'skill') return entry.detail !== undefined && entry.detail !== '';
  if (entry.kind === 'thinking') return entry.text !== '';
  return entry.input !== undefined || entry.output !== undefined;
}

function detailOf(entry: TurnEntry, t: Translate) {
  if (entry.kind === 'skill') return entry.detail;

  if (entry.kind === 'thinking') {
    return <pre className="conversation__entry-pre">{entry.text}</pre>;
  }

  return (
    <>
      {entry.input !== undefined && (
        <div className="conversation__entry-block">
          <span className="conversation__entry-block-label">{t('conversation.entry.input')}</span>
          <pre className="conversation__entry-pre">{safeStringify(entry.input)}</pre>
        </div>
      )}

      {entry.output !== undefined && (
        <div className="conversation__entry-block">
          <span className="conversation__entry-block-label">
            {entry.isError === true
              ? t('conversation.entry.errorOutput')
              : t('conversation.entry.output')}
          </span>
          <pre
            className={`conversation__entry-pre${
              entry.isError === true ? ' conversation__entry-pre--error' : ''
            }`}
          >
            {outputText(entry.output)}
          </pre>
        </div>
      )}
    </>
  );
}

/** 工具入参里最适合当摘要的字段，按「一眼能认出在干什么」排序 */
const SUMMARY_KEYS = ['command', 'file_path', 'path', 'pattern', 'url', 'query', 'description'];

function summarizeInput(input: unknown): string | undefined {
  if (input === undefined || input === null) return undefined;
  if (typeof input === 'string') return collapse(input) || undefined;
  if (typeof input !== 'object') return String(input);

  const record = input as Record<string, unknown>;
  for (const key of SUMMARY_KEYS) {
    const value = record[key];
    if (typeof value === 'string' && value.trim() !== '') return collapse(value);
  }

  const json = safeStringify(input);
  return json.length > 140 ? `${json.slice(0, 140)}…` : json;
}

function summarizeOutput(output: unknown): string | undefined {
  const text = collapse(outputText(output));
  if (text === '') return undefined;
  return text.length > 140 ? `${text.slice(0, 140)}…` : text;
}

/**
 * 工具输出的可读文本。
 *
 * SDK 的 `tool_result.content` 有两种长相：纯字符串，或内容块数组
 * （`[{ type: 'text', text: '...' }]`）。后者直接 JSON.stringify 会把正文埋进
 * `{"type":"text","text":...}` 里，读起来很糟，所以先把 text 块抽出来。
 */
function outputText(output: unknown): string {
  if (typeof output === 'string') return output;

  if (Array.isArray(output)) {
    return output
      .map((block) => {
        if (typeof block === 'string') return block;
        if (block !== null && typeof block === 'object' && 'text' in block) {
          const text = (block as { text: unknown }).text;
          if (typeof text === 'string') return text;
        }
        return safeStringify(block);
      })
      .join('\n');
  }

  if (output !== null && typeof output === 'object' && 'text' in output) {
    const text = (output as { text: unknown }).text;
    if (typeof text === 'string') return text;
  }

  return safeStringify(output);
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

function collapse(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}
