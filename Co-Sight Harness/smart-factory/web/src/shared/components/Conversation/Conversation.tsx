/**
 * Conversation：对话区的一整块 —— 头部 + 对话内容 + 发送框。
 *
 * 为什么把发送框包进来，而不是让页面自己摆一个 Composer 在下面：
 * 「这一轮什么时候发得出去」「运行中主按钮该是停止」「发完草稿要清」这三件事，
 * 只有知道对话现在是什么状态的人才答得上来。拆在两边，页面就得把 running 再传一遍、
 * 自己记草稿、自己判空 —— 那就是同一套逻辑在每个使用点抄一遍。
 *
 * 组件本身**不出网、不持会话**：messages / running / onSend / onStop 全从外面来
 * （见 features/agent-create/useCreationChat.ts 与 shared/live/useLiveSession.ts）。
 * 这样它才能同时服务三个阶段、以及将来那个运行入口 —— 而对它们来说这里只是
 * 一个受控的渲染层。
 *
 * 层叠关系：Conversation > Turn > TurnProcess > Entry。
 * 只有 Conversation 持有状态（展开态、草稿），下面三层全是受控的。
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import { Composer } from '../Composer';
import type {
  ComposerAttachment,
  ComposerCommand,
  ComposerFill,
  ComposerModel,
  ComposerReplay,
  ComposerSubmit,
} from '../Composer';
import { Icon } from '../Icon';
import { Turn } from './Turn';
import { foldKey, foldOf, groupTurns } from './turns';
import type { ConversationMessage, WaitDecision } from './types';
import './Conversation.css';

/** 默认发送框的透传参数，不传 `composer` 时才用得上 */
export interface ConversationComposerOptions {
  placeholder?: string;
  /** 「当前为什么发不出去」，透传给 Composer 的 status，如「正在生成…」 */
  status?: string;
  /** 右下角模型选择器；不传则不渲染 */
  model?: ComposerModel;
  /** 外部条件挡住发送的原因（如没有可用模型），见 Composer 的同名 prop */
  sendBlockedReason?: string | null;
  /** 运行中是否仍允许改下一句（Composer 的同名 prop） */
  editableWhileLocked?: boolean;
  /** 「添加文件」的路径来源（Composer 的同名 prop）；不传则没有 `+` 入口 */
  pickFile?: () => Promise<ComposerAttachment | null>;
  /** `/` 菜单的词表（Composer 的同名 prop）；不传 = 这个对话不支持 `/` */
  commands?: ComposerCommand[];
  /** 把内容放回发送框的一次性请求（首轮补发失败时用），见 Composer 的同名 prop */
  replay?: ComposerReplay | null;
  /** 用一段内容替换发送框的一次性请求（空态示例用），见 Composer 的同名 prop */
  fill?: ComposerFill | null;
  /** 工具栏左侧的附加控件（知识检索），见 Composer 的同名 prop */
  accessory?: ReactNode;
}

export interface ConversationProps {
  /** 对话记录，按时间升序。「一轮」怎么分组由组件自己算，调用方不用先分好 */
  messages: ConversationMessage[];
  /** 这一场会话有没有正在跑的一轮。**按会话**，不是全局 —— 切阶段不该锁住另一个阶段 */
  running: boolean;
  /** 发送一轮；返回 Promise<false> 表示这一轮没出去，发送框会把正文与附件还回来 */
  onSend: (payload: ComposerSubmit) => void | Promise<boolean>;
  onStop: () => void;

  /** 头部标题，默认「创建助手」；传 null 则整条头部不渲染 */
  title?: string | null;
  /** 头部右侧；不传给默认的「在线」圆点，传 null 隐藏 */
  status?: ReactNode;

  /** 一条消息都没有且不在运行时，替换滚动区内容；不传给内置空态，传 null 则连空态也不画 */
  empty?: ReactNode;

  /**
   * 已加载的最早一条之前还有没有更早的消息。
   *
   * 有它对话区才在滚到顶时自己要求续页；不传 = 这个能力关闭（调用方一次给了全部消息）。
   */
  hasOlder?: boolean;
  /** 更早一页正在路上：顶部提示 + 防重复触发 */
  loadingOlder?: boolean;
  /** 滚到顶附近时请求上一页更早的消息；与 `hasOlder` 一起传才生效 */
  onLoadOlder?: () => void;

  /** 覆盖默认发送框（首页那种大输入卡片走这里）；不传则渲染默认的 compact Composer */
  composer?: ReactNode;
  /** 默认发送框的透传参数 */
  composerProps?: ConversationComposerOptions;

  /**
   * 应答一条挂起的审批 / 提问。
   *
   * 卡片按消息内联在对话流里（见 `types.ts` 的 `wait`），所以这两个回调也从这里一路
   * 传到 `WaitCard`；不传则卡片只读 —— 会话历史、只读预览这类消费者不必造 no-op。
   * 返回 `true` 表示已结算（或已被别处结算），卡片会保持禁用等结算快照替换它。
   */
  onApproval?: (messageId: string, decision: WaitDecision) => Promise<boolean>;
  onAnswers?: (messageId: string, answers: Record<string, string[]>) => Promise<boolean>;

  /**
   * 受控草稿。**两个都不传**时组件内部自持 —— 这是默认用法，也是创建页的用法：
   * 打字时只有 Conversation 重渲染，不会把整页（阶段进度条 + 右栏）拖下水。
   * 传了就完全交给调用方，配合 onDraftChange。
   */
  draft?: string;
  onDraftChange?: (text: string) => void;

  /** 挂到最外层：留给调用方做栅格 / 边框这类布局微调 */
  className?: string;
}

export function Conversation({
  messages,
  running,
  onSend,
  onStop,
  title,
  status,
  empty,
  composer,
  composerProps,
  onApproval,
  onAnswers,
  hasOlder = false,
  loadingOlder = false,
  onLoadOlder,
  draft: draftProp,
  onDraftChange,
  className,
}: ConversationProps) {
  const { t } = useI18n();
  // 默认标题也在渲染期取：模块可能在挂载后切语言，默认参数只会求值一次。
  const shownTitle = title === undefined ? t('conversation.defaultTitle') : title;

  /*
   * 草稿默认自持。
   * 不能提到页面上：那样每敲一个字整页都要重渲染一遍（阶段进度条、右栏工作区一起）。
   */
  const [innerDraft, setInnerDraft] = useState('');
  const draft = draftProp ?? innerDraft;
  function setDraft(text: string) {
    if (onDraftChange) onDraftChange(text);
    else setInnerDraft(text);
  }

  /**
   * 全部展开态挤在一个 Set 里，key 自带命名空间（见 turn.ts）。
   *
   * 三个 entry 级的状态互相独立（折叠条 / 还有 N 步 / 单条明细），但都只是布尔记忆，
   * 分三个 useState 只是让「谁管谁」更难看清。真正的理由是：**key 里带消息 id，
   * 切换阶段时不清空也不会串** —— 不同阶段的 mock id 不同嘛。
   */
  const [openKeys, setOpenKeys] = useState<ReadonlySet<string>>(() => new Set<string>());

  const scrollRef = useRef<HTMLDivElement | null>(null);
  /** 用户是不是还贴着底。离底超过一屏的 24px 就当他正在往回翻，别把他拽回底部 */
  const stick = useRef(true);
  /** 要不要摆出「回到最新」按钮 —— 与 `stick` 同源，但这个要触发渲染 */
  const [atBottom, setAtBottom] = useState(true);
  /** 翻上去之后又来了新内容：按钮文案换成「有新消息」 */
  const [unseen, setUnseen] = useState(false);
  /**
   * 续页前记下滚动位置。
   *
   * 更早的消息是**往上插**的：浏览器保持 `scrollTop` 不变，视野就会跟着内容一起往下滑
   * （看起来像「跳到了刚加载的那一页」）。合并后按高度差把 `scrollTop` 补回来，
   * 原来正在读的那条才留在原处。
   */
  const olderAnchor = useRef<{
    scrollTop: number;
    scrollHeight: number;
    /** 请求时列表的第一条；合并后它变了才说明新内容插在上面 */
    firstId: string | null;
  } | null>(null);
  /**
   * 上一次自动补页时的「加载进度」：投影条数 + 首条 id。
   *
   * 不能只认条数。一整页过程消息会被折进**同一条**折叠条（见 `map-message.ts` 的分组），
   * 续上来之后条数不变 —— 拿条数当闸，补一页就再也补不动了（185 步那个会话就是这样）。
   * 首条 id 在每次往上插进一页后都会换（折叠组取组里第一条消息的 id），它才是
   * 「真的多了一页」的信号；请求失败时消息表不动，两个值都不变，也不会退化成失败重试死循环。
   */
  const autoFilledFor = useRef<string | null>(null);
  /** 上一条消息的对象引用：换了才说明「尾巴上」真来了新内容（往前续页不会换它） */
  const lastTail = useRef<ConversationMessage | null>(null);
  /** 上一帧的续页加载态：用来认「这一帧刚好加载结束但消息没变」= 失败或空页 */
  const wasLoadingOlder = useRef(false);

  const turns = useMemo(() => groupTurns(messages), [messages]);
  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : undefined;
  const isEmpty = messages.length === 0 && !running;

  /** 此刻在跑的是最后一轮；它的折叠条（或尾巴）要一直转圈 */
  const activeTurnId = running && lastTurn !== undefined ? lastTurn.id : null;
  /**
   * 运行中那一轮里，折叠条顶成「正在执行」的那条消息 —— 只有最后一条是过程消息时才顶。
   * 最后一条是结算行 / 正文时返回 null，由 Turn 在底下补一条「正在执行」的尾巴。
   *
   * 只在这里判一次：自动展开按它开、转圈也按它转，两边各判一遍迟早判出两种结果。
   */
  const activeReplyId = useMemo(() => {
    if (activeTurnId === null || lastTurn === undefined) return null;
    const last = lastTurn.replies[lastTurn.replies.length - 1];
    return last !== undefined && foldOf(last) !== null ? last.id : null;
  }, [activeTurnId, lastTurn]);

  /*
   * 运行中的折叠条自动摊开。
   *
   * 设计稿是「要看得自己点」，但折叠条写着「正在执行」却把正在执行的东西藏起来，
   * 是相对旧版「轨迹常显」的退步。只自动开、从不自动关 —— 关是用户的决定。
   *
   * `activeReplyId` 也算在「在跑」里：跑着的那一轮哪怕当前没有在途的工具调用
   * （模型在想下一步 / 在写字），折叠条也顶成正在执行，一样该摊开。
   */
  useEffect(() => {
    const auto = turns
      .flatMap((turn) => turn.replies)
      .filter((reply) => foldOf(reply, reply.id === activeReplyId)?.state === 'running')
      .map((reply) => foldKey(reply.id));
    if (auto.length === 0) return;

    setOpenKeys((current) => {
      // 都开着了就原样返回：不然每次渲染都生成新 Set，effect 自己把自己再触发一遍
      if (auto.every((key) => current.has(key))) return current;
      const next = new Set(current);
      for (const key of auto) next.add(key);
      return next;
    });
  }, [turns, activeReplyId]);

  /*
   * 钉底 / 续页后的视野都在这一次布局里处理完。
   *
   * 用 layout effect 而不是 effect：后者要等浏览器画完才调 scrollTop，新内容会先闪一帧在下面。
   * 折叠切换**不**重新钉底：用户刚点开的折叠条不该在脚下滑走。
   */
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el === null) return;

    /*
     * 换会话 / 重开时消息会先清空：上一场留的「翻上去了」与续页锚点都不能带进新一场
     * （否则新会话会停在顶部，或者把旧位置套到新列表上）。顺带把自动补页的闸也复位。
     */
    if (messages.length === 0) {
      olderAnchor.current = null;
      autoFilledFor.current = null;
      stick.current = true;
      setAtBottom(true);
      setUnseen(false);
    }

    const tail = messages.length > 0 ? messages[messages.length - 1] : null;
    const tailChanged = tail !== lastTail.current;
    lastTail.current = tail;

    /*
     * 续页锚点只在「上面真的插进来了一段」时才用，并且要等到那一刻才清掉它。
     * 这一帧只是 loadingOlder 变了（请求刚发出），消息还没变 —— 清早了，等消息真到时
     * 就没有位置可补，视野会跳到 0（实测踩过）。
     * 反过来，加载刚结束而第一条没变，说明失败或空页：这时候再补只会把用户往下推，丢掉即可。
     */
    const loadJustEnded = wasLoadingOlder.current && !loadingOlder;
    wasLoadingOlder.current = loadingOlder;

    const anchor = olderAnchor.current;
    let kept = false;
    if (anchor !== null && messages[0]?.id !== anchor.firstId) {
      olderAnchor.current = null;
      el.scrollTop = anchor.scrollTop + (el.scrollHeight - anchor.scrollHeight);
      kept = true;
    } else if (anchor !== null && loadJustEnded) {
      olderAnchor.current = null;
    }

    if (!kept) {
      if (stick.current) {
        el.scrollTop = el.scrollHeight;
      } else if (tailChanged) {
        // 用户翻上去了，尾巴又变了（新消息或流式正文）：按钮换成「有新消息」
        setUnseen(true);
      }
    }

    /*
     * 内容还没撑满一屏时不会有滚动事件，续页就永远等不到触发 —— 主动补一页。
     * 每落下一页再判一次（见 `autoFilledFor`）：一页过程消息折进同一条折叠条时不会长高，
     * 得一直补，直到内容撑满一屏或拉到尽头。请求失败时消息表没变，不会变成失败重试死循环。
     */
    const progress = `${messages.length}:${messages[0]?.id ?? ''}`;
    let autoFilled = false;
    if (
      hasOlder &&
      !loadingOlder &&
      el.scrollHeight <= el.clientHeight + 1 &&
      autoFilledFor.current !== progress
    ) {
      autoFilledFor.current = progress;
      autoFilled = true;
      // 自动补页是为了把内容撑满：用户本来就在底/无滚动位置可保，补完应该继续贴底
      requestOlder(false);
    }

    /*
     * 续上来的一页如果全是过程消息，它们只会折进同一条折叠条 —— 内容高度几乎不变，
     * 视野就还停在顶部。而顶部再往上滚不会产生 scroll 事件（scrollTop 已经是 0），
     * 那条续页路径就断在这儿：用户一直往上滚，界面毫无反应（185 步的会话就是这样）。
     * 用户本来就在顶部等更早的东西，接着拉 —— 直到内容把视野推离顶部，或拉到尽头。
     */
    if (!autoFilled && kept && el.scrollTop < 72) {
      requestOlder(true);
    }
  }, [messages, running, hasOlder, loadingOlder]);

  /**
   * 要一页更早的消息。
   *
   * `keepView`：用户自己滚上去的要记住当前位置，合并后把视野补回原处；
   * 自动补页（内容撑不满一屏）不记 —— 那时候该继续贴底，而不是把旧内容钉在顶上。
   */
  function requestOlder(keepView: boolean) {
    const el = scrollRef.current;
    if (el === null || onLoadOlder === undefined || !hasOlder || loadingOlder) return;
    olderAnchor.current = keepView
      ? {
          scrollTop: el.scrollTop,
          scrollHeight: el.scrollHeight,
          firstId: messages[0]?.id ?? null,
        }
      : null;
    onLoadOlder();
  }

  function handleScroll() {
    const el = scrollRef.current;
    if (el === null) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    stick.current = bottom;
    setAtBottom(bottom);
    if (bottom) setUnseen(false);
    // 滚到顶附近就续一页。在途 / 到头的闸在调用方与 hook 里，这里不必再判
    if (el.scrollTop < 72) requestOlder(true);
  }

  /** 回到最新：把钉底恢复上，顺带清掉「有新消息」 */
  function jumpToBottom() {
    const el = scrollRef.current;
    if (el === null) return;
    stick.current = true;
    setAtBottom(true);
    setUnseen(false);
    el.scrollTop = el.scrollHeight;
  }

  function toggle(key: string) {
    setOpenKeys((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  function submit(payload: ComposerSubmit) {
    /*
     * 清空必须在 onSend 之前同步发生。
     * Composer 是 contenteditable、以 DOM 为准，它清正文靠的是「外部把 value 改成别的了」
     * 这条回写路径（见 Composer.tsx 文件头）。而它是拿 onSubmit 那一刻的 DOM 快照发的 ——
     * 顺序反了，正文就会留在框里，跟已经发出去的那条消息重复。
     *
     * 也不能挪进会话 Hook：发送框的草稿它看不见。
     */
    setDraft('');
    // 把发送的结果透给 Composer：false 时要把它已经收走的附件还回来
    return onSend(payload);
  }

  return (
    <div className={className ? `conversation ${className}` : 'conversation'}>
      {shownTitle !== null && (
        <div className="conversation__head">
          <h3>{shownTitle}</h3>
          {status === undefined ? (
            <span className="conversation__live">
              <span className="conversation__live-dot" />
              {t('conversation.online')}
            </span>
          ) : (
            status
          )}
        </div>
      )}

      {/* 视口壳：浮在滚动区上的两块（续页提示、回到底部）按它定位，不必猜发送框多高 */}
      <div className="conversation__viewport">
        <div className="conversation__scroll" ref={scrollRef} onScroll={handleScroll}>
          {isEmpty
            ? empty !== undefined
              ? empty
              : (
                <div className="conversation__empty">
                  {/* 不放按钮：空对话唯一能做的那件事，就是下面那个发送框 */}
                  <Icon name="message" size={22} />
                  <p>{t('conversation.empty')}</p>
                </div>
              )
            : turns.map((turn) => (
              <Turn
                key={turn.id}
                turn={turn}
                active={turn.id === activeTurnId}
                activeReplyId={turn.id === activeTurnId ? activeReplyId : null}
                openKeys={openKeys}
                onToggle={toggle}
                onApproval={onApproval}
                onAnswers={onAnswers}
              />
            ))}
        </div>

        {/* 不占滚动区高度（绝对定位）：否则续页提示出现/消失会把锚点算歪 */}
        {loadingOlder && (
          <div className="conversation__older" role="status">
            {t('conversation.loadingOlder')}
          </div>
        )}

        {!isEmpty && !atBottom && (
          <button type="button" className="conversation__jump" onClick={jumpToBottom}>
            {unseen && <span className="conversation__jump-dot" />}
            <Icon name="chevronDown" size={13} />
            {unseen ? t('conversation.newMessages') : t('conversation.scrollToLatest')}
          </button>
        )}
      </div>

      <div className="conversation__foot">
        {composer ?? (
          <Composer
            value={draft}
            onChange={setDraft}
            onSubmit={submit}
            running={running}
            onStop={onStop}
            placeholder={composerProps?.placeholder}
            status={composerProps?.status}
            sendBlockedReason={composerProps?.sendBlockedReason}
            model={composerProps?.model}
            editableWhileLocked={composerProps?.editableWhileLocked}
            pickFile={composerProps?.pickFile}
            commands={composerProps?.commands}
            replay={composerProps?.replay}
            fill={composerProps?.fill}
            accessory={composerProps?.accessory}
          />
        )}
      </div>
    </div>
  );
}
