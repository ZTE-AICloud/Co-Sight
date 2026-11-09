/**
 * 一轮：提问 + 它的应答。
 *
 * 分组只为间距 —— 提问和应答挨得比两轮之间更近（滚动区 gap 20px，轮内 10px）。
 * 一轮里的助手消息**可以有好几条**：每条都是一次独立的应答，各带各的折叠条与回答
 * （mock 的 g2、g3 就是连着两条）。设计稿里一轮只有一条 `.say`，那是因为它的数据
 * 一轮只有一次应答，不是因为结构上只允许一条。
 */

import { useMemo } from 'react';
import { FileChip } from '../FileChip';
import { useFilePreview } from '../FilePreview/FilePreviewProvider';
import { Icon } from '../Icon';
import { Markdown } from '../Markdown/Markdown';
import type { MarkdownFileMentions } from '../Markdown/Markdown';
import { useI18n } from '../../../i18n/useI18n';
import { producedPathsOf, resolveMention } from '../../file-ref';
import { TurnProcess } from './TurnProcess';
import { WaitCard } from './WaitCard';
import { foldKey, foldOf } from './turns';
import type { FoldState } from './turns';
import type { ConversationMessage, ConversationTurn, WaitDecision } from './types';

export interface TurnProps {
  turn: ConversationTurn;
  /** 这一轮就是此刻在跑的那一轮（Conversation 按 running + 最后一轮算出） */
  active: boolean;
  /**
   * 运行中那一轮里「折叠条要顶成正在执行」的那条消息；null = 没有可顶的过程消息。
   * 由 Conversation 算好再传下来：自动展开与这里的转圈必须指向同一条，
   * 两边各判一次迟早判出两种结果。
   */
  activeReplyId: string | null;
  openKeys: ReadonlySet<string>;
  onToggle: (key: string) => void;
  /** 应答挂起的审批 / 提问；不传则卡片只读 */
  onApproval?: (messageId: string, decision: WaitDecision) => Promise<boolean>;
  onAnswers?: (messageId: string, answers: Record<string, string[]>) => Promise<boolean>;
}

export function Turn({
  turn,
  active,
  activeReplyId,
  openKeys,
  onToggle,
  onApproval,
  onAnswers,
}: TurnProps) {
  const { t } = useI18n();
  /**
   * 本轮写过的文件。行内代码只在这些路径里找 —— 判定依据是「真的写过」，
   * 不是「这串字符像文件名」（见 file-ref.ts 文件头）。
   *
   * 按轮算一次、往下传给每条应答：同一轮里的多条助手消息共享同一份产物集合。
   */
  const produced = useMemo(() => producedPathsOf(turn), [turn]);
  const lastReply = turn.replies[turn.replies.length - 1];
  /**
   * 转圈放在哪儿：
   *   - 最后一条是过程消息 → 转圈在它的折叠条上（activeReplyId 指的就是它），这里不补
   *   - 最后一条是结算行 / 正文 / 回执还没回来 → 补一条「正在执行」占位条
   *   - 最后一条是挂起的审批 / 提问卡 → 不补：此刻等的是用户，转圈会让人以为机器还在忙
   */
  const showTail = active && activeReplyId === null && lastReply?.wait === undefined;

  return (
    <article className="conversation__turn">
      {turn.ask && <Ask message={turn.ask} />}

      {turn.replies.map((reply) => (
        <Reply
          key={reply.id}
          message={reply}
          active={reply.id === activeReplyId}
          produced={produced}
          openKeys={openKeys}
          onToggle={onToggle}
          onApproval={onApproval}
          onAnswers={onAnswers}
        />
      ))}

      {showTail && (
        <div className="conversation__reply">
          <span className="conversation__avatar">AI</span>
          <div className="conversation__body">
            {/* 不是按钮：这是一个只表示「还在跑」的尾巴，里面没有东西可展开 */}
            <div
              className="conversation__procbar conversation__procbar--static"
              data-state="running"
            >
              <span className="conversation__procbar-icon">
                <span className="conversation__spin" />
              </span>
              <span>
                <b>{t('conversation.running')}</b>
              </span>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

/** 用户提问：气泡，右对齐。附件贴在气泡下面（端侧服务下它就是一条本地路径） */
function Ask({ message }: { message: ConversationMessage }) {
  const { t } = useI18n();
  return (
    <div className="conversation__ask">
      <span className="conversation__avatar conversation__avatar--user">{t('conversation.user')}</span>
      <div className="conversation__body">
        {/* 纯附件消息（服务端允许空正文）没有气泡：空胶囊比只留 chip 更像渲染错误 */}
        {message.text.trim() !== '' && (
          <div className="conversation__bubble">{message.text}</div>
        )}

        {message.files !== undefined && message.files.length > 0 && (
          <div className="conversation__files">
            {message.files.map((file) => (
              // 与首页 / 设计页发送框同一个 chip（FileChip）：只写文件名，完整路径挂 title
              <FileChip key={file.id} path={file.name} size="sm" />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** 助手应答：折叠条 → 折叠体 → 分隔线 → 回答 */
function Reply({
  message,
  active,
  produced,
  openKeys,
  onToggle,
  onApproval,
  onAnswers,
}: {
  message: ConversationMessage;
  /** 这条属于此刻还在跑的那一轮：折叠条顶成「正在执行」，转圈别停 */
  active: boolean;
  /** 本轮写过的文件（见 Turn）：行内代码的文件引用只在其中匹配 */
  produced: readonly string[];
  openKeys: ReadonlySet<string>;
  onToggle: (key: string) => void;
  onApproval?: (messageId: string, decision: WaitDecision) => Promise<boolean>;
  onAnswers?: (messageId: string, answers: Record<string, string[]>) => Promise<boolean>;
}) {
  const { t } = useI18n();
  const preview = useFilePreview();
  const fold = foldOf(message, active);

  /**
   * 流式中的那段不加 mention 解析（`live-` 前缀）：它每帧都在变，
   * 把此刻匹配到的 handler 固化进渲染没有意义；落库定型后才出现按钮。
   */
  const live = message.id.startsWith('live-');
  const fileMentions = useMemo<MarkdownFileMentions | undefined>(() => {
    if (!preview.enabled || !preview.ready || preview.baseDir === null || live) {
      return undefined;
    }
    return {
      resolve: (value) => resolveMention(value, produced),
      open: preview.open,
      baseDir: preview.baseDir,
    };
  }, [preview.enabled, preview.ready, preview.baseDir, preview.open, produced, live]);
  const open = openKeys.has(foldKey(message.id));
  const hasText = message.text !== '';

  const foldText =
    fold === null
      ? ''
      : fold.state === 'failed'
        ? t('conversation.fold.failed', { count: fold.failed })
        : fold.state === 'running'
          ? t('conversation.fold.running')
          : t('conversation.fold.done');
  const foldMeta =
    fold === null
      ? ''
      : fold.time === ''
        ? t('conversation.fold.steps', { count: fold.steps })
        : t('conversation.fold.stepsWithTime', { count: fold.steps, time: fold.time });

  return (
    <div className="conversation__reply">
      <span className="conversation__avatar">AI</span>
      <div className="conversation__body">
        {fold && (
          <button
            type="button"
            className="conversation__procbar"
            data-state={fold.state}
            aria-expanded={open}
            onClick={() => onToggle(foldKey(message.id))}
          >
            <span className="conversation__procbar-icon">{foldLead(fold.state)}</span>
            <span>
              <b>{foldText}</b>
              <span className="conversation__sep"> · </span>
              {foldMeta}
            </span>
            <span className="conversation__caret">
              <Icon name="chevronDown" size={13} />
            </span>
          </button>
        )}

        {fold && open && (
          <TurnProcess message={message} openKeys={openKeys} onToggle={onToggle} />
        )}

        {/* 挂起时正文是空的，这条消息的可视内容就是这张卡；结算后 wait 消失、正文出现 */}
        {message.wait !== undefined && (
          <WaitCard
            messageId={message.id}
            wait={message.wait}
            onApproval={onApproval}
            onAnswers={onAnswers}
          />
        )}

        {/* 有过程才划这条线：没有过程时它只是一句回答，划一条线反而像少了半截 */}
        {fold && hasText && <div className="conversation__rule" />}

        {/* 模型回复是 Markdown；结算行是系统文案，仍按纯文本走 */}
        {hasText &&
          (message.waitSettled === true ? (
            <div className="conversation__wait-settled">{message.text}</div>
          ) : (
            <Markdown
              className="conversation__answer"
              text={message.text}
              fileMentions={fileMentions}
            />
          ))}
      </div>
    </div>
  );
}

/** 折叠条上的状态图标。比条目那套多半档：这里的「失败」是「这一轮有步骤挂了」，用警示三角 */
function foldLead(state: FoldState) {
  if (state === 'done') return <Icon name="check" size={14} />;
  if (state === 'failed') return <Icon name="alert" size={14} />;
  return <span className="conversation__spin" />;
}
