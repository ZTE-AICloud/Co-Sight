/**
 * 对话区外壳：提示条 + Conversation，以及三个阶段共用的两小块状态展示。
 *
 * 三个阶段的外观必须是同一套（消息、折叠过程、审批卡、提问卡都由 shared/Conversation
 * 渲染），差别只在标题、placeholder、空态文案 —— 一律从 props 进，组件不知道自己在哪个阶段。
 *
 * `LinkPill` / `BootState` 放在这里而不是页面：三个阶段都是真会话，这两块对它们
 * 完全一致，差别只在空态文案（`BootCopy`）。
 */

import type { ReactNode } from 'react';
import { useCallback } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import type { MessageKey, MessageParams } from '../../../i18n/types';
import { attachmentOfPath } from '../../../shared/components/Composer';
import type { ComposerCommand, ComposerModel } from '../../../shared/components/Composer';
import { Conversation } from '../../../shared/components/Conversation/Conversation';
import { useFilePicker } from '../../../shared/components/FilePicker';
import { Icon } from '../../../shared/components/Icon';
import type { CreationChat, CreationLink } from '../useCreationChat';

export interface ConversationPaneProps {
  chat: CreationChat;
  /** 对话头标题；不传则用 Conversation 默认的「创建助手」 */
  title?: string;
  /** 对话头右侧；不传则用组件自带的「在线」圆点 */
  status?: ReactNode;
  /** 一条消息都没有时替换滚动区 */
  empty?: ReactNode;
  placeholder?: string;
  /** 右下角模型选择器；不传则不渲染 */
  model?: ComposerModel;
  /**
   * `/` 菜单词表；不传 = 这个阶段的对话不支持 `/`。
   * 各阶段传什么由阶段自己决定：生成 / 评估用前端预设，预览要等「查智能体技能」的接口。
   */
  commands?: ComposerCommand[];
  /** 没有可用模型等外部条件挡住发送的原因（只锁发送，不锁编辑） */
  sendBlockedReason?: string | null;
  /** 发送框工具栏左侧的附加控件（生成阶段的知识检索 chip），见 Composer 同名 prop */
  accessory?: ReactNode;
  /** 外层的附加类名（预览阶段用 `ac-conv--single` 做居中） */
  className?: string;
}

export function ConversationPane({
  chat,
  title,
  status,
  empty,
  placeholder,
  model,
  commands,
  sendBlockedReason,
  accessory,
  className,
}: ConversationPaneProps) {
  const { t } = useI18n();
  /*
   * 「添加文件」的选择器由外壳统一持有：三个阶段共用同一份对话区，
   * 把弹窗挂在这里，各阶段不必各摆一个（也不会出现两份 dialog 同时存在）。
   */
  const picker = useFilePicker();
  const pickFile = useCallback(async () => {
    const path = await picker.pickFile();
    return path === null ? null : attachmentOfPath(path);
  }, [picker.pickFile]);

  return (
    <div className={className ? `ac-conv ${className}` : 'ac-conv'}>
      {chat.link.notice !== null && (
        <div className="ac-note" role="status">
          <Icon name="alert" size={14} />
          <span>{chat.link.notice}</span>
          <button
            type="button"
            className="ac-note-close"
            aria-label={t('create.pane.dismissNotice')}
            onClick={chat.link.dismissNotice}
          >
            <Icon name="close" size={14} />
          </button>
        </div>
      )}

      <Conversation
        messages={chat.messages}
        running={chat.running}
        onSend={chat.send}
        onStop={chat.stop}
        hasOlder={chat.hasOlder}
        loadingOlder={chat.loadingOlder}
        onLoadOlder={chat.loadOlder}
        // 审批 / 提问卡内联在对话流里；演示阶段是 no-op，但传 no-op 比到处判阶段省事
        onApproval={chat.respondApproval}
        onAnswers={chat.respondAnswers}
        title={title}
        status={status}
        empty={empty}
        composerProps={{
          placeholder,
          status: chat.running ? t('create.pane.generating') : undefined,
          model,
          commands,
          sendBlockedReason,
          pickFile,
          accessory,
          // 首轮补发失败时把原话 + 附件放回发送框（见 CreationChat.replay）
          replay: chat.replay,
        }}
      />

      {/* 弹窗自带 dialog，挂在这里即可（关闭时不渲染任何节点） */}
      {picker.element}
    </div>
  );
}

/**
 * 对话头右侧的通道状态：这是「这一刻到底能不能说话」的唯一表示。
 *
 * 组件自带的那个「在线」圆点是演示期的装饰（永远绿），真会话不能再用它 ——
 * 连不上却写着「在线」，用户会以为丢消息是自己的问题。
 */
export function LinkPill({ link }: { link: CreationLink }) {
  const { t } = useI18n();
  const open = link.conn === 'ready' && link.phase === 'ready';
  if (link.phase === 'failed') {
    return (
      <span className="ac-link ac-link--bad">
        <Icon name="alert" size={12} />
        {t('create.pane.linkFailed')}
      </span>
    );
  }

  const text = open
    ? t('create.pane.connected')
    : link.phase === 'preparing'
      ? t('create.pane.preparing')
      : link.conn === 'closed'
        ? t('create.pane.reconnecting')
        : t('create.pane.connecting');

  return (
    <span className={open ? 'ac-link ac-link--ok' : 'ac-link ac-link--wait'}>
      <span className="ac-link-dot" />
      {text}
    </span>
  );
}

/** 空态文案。生产与预览的差别只在「在哪个目录、为什么来这里」 */
export interface BootCopy {
  failTitle: string;
  readyTitle: string;
  readyDesc: string;
  preparingTitle: string;
  preparingDesc: string;
  connectingDesc: string;
}

type Translate = (key: MessageKey, params?: MessageParams) => string;

function bootCopy(prefix: string, t: Translate): BootCopy {
  const key = (name: string) => `${prefix}.${name}` as MessageKey;
  return {
    failTitle: t(key('failTitle')),
    readyTitle: t(key('readyTitle')),
    readyDesc: t(key('readyDesc')),
    preparingTitle: t(key('preparingTitle')),
    preparingDesc: t(key('preparingDesc')),
    connectingDesc: t(key('connectingDesc')),
  };
}

export function workspaceBootCopy(t: Translate): BootCopy {
  return bootCopy('create.boot.workspace', t);
}

export function previewBootCopy(t: Translate): BootCopy {
  return bootCopy('create.boot.preview', t);
}

export function evaluationBootCopy(t: Translate): BootCopy {
  return bootCopy('create.boot.evaluation', t);
}

/**
 * 一条消息都没有时，对话区显示什么。
 *
 * 这一屏是创建页的常态：新会话没有历史，所以它不是「空态兜底」，而是要说清两件事：
 * 会话准备好没有、接下来该做什么。文案按阶段传（见上面的两份 BootCopy）。
 */
export function BootState({
  link,
  copy,
}: {
  link: CreationLink;
  copy?: BootCopy;
}) {
  const { t } = useI18n();
  const shownCopy = copy ?? workspaceBootCopy(t);
  const failed = link.phase === 'failed';
  /*
   * 通道断了（closed 且还没就绪）：**要跟「正在连」分开**。
   * 客户端会自己退避重连，可能一直连不上 —— 那种情况下只写「正在连接本地服务」，
   * 用户会一直等一个不会来的东西，也没有出口。这里给一句实话 + 一个重试。
   */
  const disconnected = !failed && link.conn === 'closed';

  if (failed || disconnected) {
    return (
      <div className="ac-boot" role="alert">
        <Icon name="alert" size={22} />
        <p className="ac-boot-title">
          {failed ? shownCopy.failTitle : t('create.pane.disconnectedTitle')}
        </p>
        <p className="ac-boot-desc">
          {failed
            ? (link.error ?? t('create.pane.failedReason'))
            : t('create.pane.disconnectedDesc')}
        </p>
        <button type="button" className="ac-btn ac-btn--primary" onClick={link.retry}>
          {t('create.pane.retry')}
        </button>
      </div>
    );
  }

  return (
    <div className="ac-boot" aria-busy={link.phase !== 'ready'}>
      <Icon name={link.phase === 'ready' ? 'message' : 'clock'} size={22} />
      <p className="ac-boot-title">
        {link.phase === 'ready' ? shownCopy.readyTitle : shownCopy.preparingTitle}
      </p>
      <p className="ac-boot-desc">
        {link.phase === 'ready'
          ? shownCopy.readyDesc
          : link.phase === 'preparing'
            ? shownCopy.preparingDesc
            : shownCopy.connectingDesc}
      </p>
    </div>
  );
}
