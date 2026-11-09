// SPDX-License-Identifier: Apache-2.0
/**
 * @file ChatConversation.tsx
 * @description `/chat` 的对话态消息流:用户/助手气泡、工具调用卡片、在执行的工具、
 * 审批卡与交互问答卡。
 *
 * 复用 `components/conversation/` 里的渲染原语:`MarkdownContent` 渲染助手正文,
 * `ToolCallBlock` 渲染工具调用与结果。刻意**不用** `MessageList` —— 它的入参是
 * `TranscriptMessage`,而 WS 流不产出该形状,且其内部有空态英文硬编码。
 */

import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Loader2, MessageSquare, ShieldAlert } from "lucide-react";
import type { ConnectionState } from "../../api/chat-socket";
import type { TranscriptContent } from "../../lib/types";
import { MarkdownContent } from "../conversation/MarkdownContent";
import type { FileMentions } from "../conversation/MarkdownContent";
import { ToolCallBlock } from "../conversation/ToolCallBlock";
import { FileChip } from "./FileChip";
import { approvalOptionLabel, approvalTitle } from "./approval-i18n";
import type {
  ApprovalRequest,
  ChatMessage,
  InteractiveTool,
  ToolAnswerValue,
  ToolExecution,
} from "../../pages/chat/useChatSession";
import type { SessionFile } from "../../pages/chat/useSessionFiles";
import { writtenPathOfMessage } from "../../pages/chat/useSessionFiles";
import { useResolvedLinks } from "../../pages/chat/useResolvedLinks";
import {
  collectInlineCodePaths,
  comparableBaseName,
  resolveMention,
} from "../../pages/chat/file-mentions";
import { answerDraftOf, isQuestionAnswered } from "../../lib/tool-answers";
import type { ToolAnswerDraft } from "../../lib/tool-answers";
import { styleForTool } from "../conversation/toolStyle";

/** 没传候选根时的稳定空数组：避免每次渲染都换引用，把校验 hook 的依赖打乱。 */
const EMPTY_LINK_ROOTS: readonly string[] = [];

/** 把时间戳格式化成 HH:mm。 */
function formatClock(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * 把本地 tool 消息适配成 ToolCallBlock 需要的 tool_use / tool_result 对。
 *
 * `toolPending` 表示历史里只有调用、没有结果（run 被中止）：传 null 让卡片
 * 显示 pending，而不是伪造一条空结果。
 */
function toToolPair(message: ChatMessage): {
  toolUse: TranscriptContent;
  toolResult: TranscriptContent | null;
} {
  return {
    toolUse: {
      type: "tool_use",
      id: message.id,
      name: message.toolName,
      input: message.toolInput,
    },
    toolResult: message.toolPending
      ? null
      : {
          type: "tool_result",
          id: message.id,
          output:
            typeof message.toolOutput === "string"
              ? message.toolOutput
              : JSON.stringify(message.toolOutput ?? message.content, null, 2),
          is_error: message.toolError,
        },
  };
}

interface MessageRowProps {
  message: ChatMessage;
  onOpenFile?: (path: string) => void;
  fileMentions?: FileMentions;
}

/** 一条已完成的消息。 */
function MessageRow({ message, onOpenFile, fileMentions }: MessageRowProps) {
  const { t } = useTranslation();
  const isUser = message.role === "user";

  /*
   * run 失败：服务端落库的 system/error（或本地兜底）。
   * 必须作为对话内容保留，而不是一闪而过的顶部横幅 —— 刷新/从「最近」重开也要能看到。
   */
  if (message.system && message.systemError) {
    return (
      <div
        role="alert"
        className="mx-auto w-full rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3"
      >
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 flex-shrink-0 text-red-400" />
          <span className="text-xs font-semibold tracking-wide text-red-400">
            {t("run.runFailed")}
          </span>
          <span className="ml-auto flex-shrink-0 text-[11px] text-red-400/70">
            {formatClock(message.timestamp)}
          </span>
        </div>
        <p className="mt-1.5 whitespace-pre-wrap break-words text-sm leading-relaxed text-red-400/90">
          {message.content}
        </p>
      </div>
    );
  }

  // 本地系统事件（连接断开/恢复、上一轮终止原因）：居中灰字，不占气泡
  if (message.system) {
    return (
      <div className="flex items-center justify-center gap-2 px-2 py-0.5 text-xs text-faint">
        <span className="h-1 w-1 flex-shrink-0 rounded-full bg-current opacity-60" />
        <span className="text-center">{message.content}</span>
        <span className="flex-shrink-0">{formatClock(message.timestamp)}</span>
      </div>
    );
  }

  if (message.role === "tool") {
    const { toolUse, toolResult } = toToolPair(message);
    /*
     * 只有成功的 Write/Edit 系工具路径可点：Read/Grep 的 path 不是产物，
     * 点开右侧面板也没有对应文件；失败/挂起的写入同理。
     * 文件类型不限 —— PPTX/PDF 等由面板给出“暂不支持预览 + 下载”。
     */
    const writtenPath = writtenPathOfMessage(message);
    return (
      <div className="pl-1 pr-4 sm:pr-8">
        <ToolCallBlock
          toolUse={toolUse}
          toolResult={toolResult}
          onOpenPath={writtenPath !== null ? onOpenFile : undefined}
        />
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-1.5 ${isUser ? "items-end" : "items-start"}`}>
      <div className="flex items-center gap-2 text-xs text-muted px-1">
        <span className="font-medium">{isUser ? t("run.you") : t("run.aiAssistant")}</span>
        <span className="text-faint">{formatClock(message.timestamp)}</span>
      </div>
      <div
        className={
          isUser
            ? "chat-bubble-user max-w-[min(46rem,88%)] rounded-2xl rounded-br-sm px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words"
            : "chat-bubble-assistant max-w-[min(52rem,92%)] rounded-2xl rounded-bl-sm px-4 py-3"
        }
      >
        {isUser ? (
          <div className="flex flex-col gap-1.5">
            {message.content !== "" && (
              <div className="whitespace-pre-wrap break-words">{message.content}</div>
            )}
            {message.files !== undefined && message.files.length > 0 && (
              <div className="flex flex-wrap justify-end gap-1.5">
                {message.files.map((file) => (
                  <FileChip key={file.id} file={{ name: file.name }} size="sm" />
                ))}
              </div>
            )}
          </div>
        ) : (
          <MarkdownContent text={message.content} fileMentions={fileMentions} />
        )}
      </div>
    </div>
  );
}

interface ApprovalCardProps {
  approval: ApprovalRequest;
  onRespond: (decision: string) => void;
}

/** 审批卡:AI 请求执行工具,等用户裁决。 */
function ApprovalCard({ approval, onRespond }: ApprovalCardProps) {
  const { t, i18n } = useTranslation();

  /** 主操作蓝色实心；全部允许为次要按钮；拒绝只描边 + 红字。 */
  function toneFor(value: string): string {
    if (value === "rejected") {
      return "border border-red-500/40 text-red-600 hover:bg-red-500/10 dark:text-red-400";
    }
    if (value === "approved_all") {
      return "border border-border bg-surface-1 text-primary hover:bg-surface-3";
    }
    return "border border-blue-600 bg-blue-600 text-white hover:bg-blue-500";
  }

  return (
    <div
      role="group"
      aria-label={approvalTitle(approval.title, t)}
      className="w-full max-w-[min(52rem,92%)] overflow-hidden rounded-xl border border-amber-500/30 bg-surface-2"
    >
      <div className="flex items-center gap-2 border-b border-amber-500/20 px-3 py-2">
        <ShieldAlert className="h-4 w-4 flex-shrink-0 text-amber-500" />
        <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-primary">
          {approvalTitle(approval.title, t)}
        </h3>
        <span className="flex-shrink-0 rounded-full border border-amber-500/40 px-2 py-0.5 text-[10px] leading-4 text-amber-600 dark:text-amber-400">
          {t("run.approvalKind")}
        </span>
      </div>

      <div className="space-y-2 px-3 py-2.5">
        {approval.toolName !== "" && (
          <div className="break-words font-mono text-xs font-semibold text-primary">
            {approval.toolName}
          </div>
        )}
        <p className="text-xs leading-relaxed text-muted">
          {approval.description || t("run.approvalRequestDesc", { toolName: approval.toolName })}
        </p>
        {approval.input && (
          <pre className="max-h-[150px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border/60 bg-surface-1 p-2 font-mono text-[11px] leading-relaxed text-secondary">
            {JSON.stringify(approval.input, null, 2)}
          </pre>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 px-3 pb-3">
        {approval.options.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onRespond(option.value)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${toneFor(option.value)}`}
          >
            {approvalOptionLabel(option, i18n.language, t)}
          </button>
        ))}
      </div>
    </div>
  );
}

interface InteractiveCardProps {
  tool: InteractiveTool;
  answers: Record<string, ToolAnswerValue>;
  onAnswerChange: (question: string, value: ToolAnswerValue) => void;
  onSubmit: () => void;
}

/**
 * 交互问答卡(如 AskUserQuestion)：选项 + 「其他」自由输入。
 *
 * 语义与 smart-factory 的 `QuestionCard` 一致：
 * - 单选：选项与「其他」互斥；
 * - 多选：选项与「其他」并存，提交时文本追加在后面；
 * - 每道题都答完才允许提交（空提交不再伪造空字符串答案）。
 * 草稿按问题原文存放，见 `lib/tool-answers.ts`。
 */
function InteractiveCard({ tool, answers, onAnswerChange, onSubmit }: InteractiveCardProps) {
  const { t } = useTranslation();
  const title = tool.toolName === "AskUserQuestion" ? t("run.needAnswer") : tool.toolName;
  const otherRefs = useRef<Record<number, HTMLInputElement | null>>({});

  const drafts = tool.input.questions.map((question) =>
    answerDraftOf(answers[question.question]),
  );
  /** 下标一定来自 `questions.map`，但 noUncheckedIndexedAccess 下仍要兜底。 */
  function draftAt(index: number): ToolAnswerDraft {
    return drafts[index] ?? answerDraftOf(undefined);
  }

  const canSubmit =
    tool.input.questions.length === 0 ||
    tool.input.questions.every((question, index) =>
      isQuestionAnswered(question, draftAt(index)),
    );

  /** 只改这一道题的草稿；其它题（及其它卡片）的答案不受影响。 */
  function updateDraft(
    question: string,
    index: number,
    patch: Partial<ToolAnswerDraft>,
  ): void {
    onAnswerChange(question, { ...draftAt(index), ...patch });
  }

  /** 单选时与「其他」互斥：勾了输入框，选项就不再算选中。 */
  function pickOption(
    index: number,
    question: string,
    label: string,
    checked: boolean,
    multi: boolean,
  ): void {
    if (!multi) {
      updateDraft(question, index, { picked: [label], otherOn: false });
      return;
    }
    const draft = draftAt(index);
    updateDraft(question, index, {
      picked: checked
        ? [...draft.picked.filter((item) => item !== label), label]
        : draft.picked.filter((item) => item !== label),
    });
  }

  function toggleOther(index: number, question: string, on: boolean, multi: boolean): void {
    updateDraft(question, index, {
      otherOn: on,
      ...(multi ? {} : { picked: [] }),
    });
    if (!on) return;
    // 等输入框渲染出来再聚焦
    requestAnimationFrame(() => otherRefs.current[index]?.focus());
  }

  return (
    <div
      role="group"
      aria-label={title}
      className="w-full max-w-[min(52rem,92%)] overflow-hidden rounded-xl border border-amber-500/30 bg-surface-2"
    >
      <div className="flex items-center gap-2 border-b border-amber-500/20 px-3 py-2">
        <MessageSquare className="h-4 w-4 flex-shrink-0 text-amber-500" />
        <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-primary">{title}</h3>
        <span className="flex-shrink-0 rounded-full border border-amber-500/40 px-2 py-0.5 text-[10px] leading-4 text-amber-600 dark:text-amber-400">
          {t("run.questionKind")}
        </span>
      </div>

      <div className="space-y-3 px-3 py-2.5">
        {tool.input.questions.map((question, questionIndex) => {
          const draft = draftAt(questionIndex);
          const multi = question.multiSelect;
          return (
            <div key={question.question} className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                {question.header && (
                  <span className="inline-block rounded bg-blue-500/10 px-2 py-0.5 text-[11px] text-blue-600 dark:text-blue-300">
                    {question.header}
                  </span>
                )}
                <span className="min-w-0 break-words text-sm text-primary">
                  {question.question}
                </span>
                {/* 题目本身常已写「（可多选）」，不重复提示 */}
                {multi && !/多选|multiple|select all/i.test(question.question) && (
                  <span className="text-[11px] text-muted">{t("run.multiSelectHint")}</span>
                )}
              </div>

              <div className="space-y-1.5">
                {question.options.map((option) => {
                  const checked = multi
                    ? draft.picked.includes(option.label)
                    : draft.picked.includes(option.label) && !draft.otherOn;

                  return (
                    <label
                      key={option.label}
                      className={`relative flex cursor-pointer items-start gap-2.5 rounded-lg border px-2.5 py-2 transition-colors ${
                        checked
                          ? "border-blue-500 bg-blue-500/5 dark:border-blue-400 dark:bg-blue-400/15"
                          : "border-border/60 bg-surface-1 hover:border-border"
                      }`}
                    >
                      <input
                        type={multi ? "checkbox" : "radio"}
                        // 每张交互卡各自成组：多张卡同时渲染时同名 radio 会互相取消勾选
                        name={`${tool.toolCallId}-q-${questionIndex}`}
                        checked={checked}
                        onChange={(event) =>
                          pickOption(
                            questionIndex,
                            question.question,
                            option.label,
                            event.target.checked,
                            multi,
                          )
                        }
                        data-multi={multi ? "true" : undefined}
                        className="wait-option-input"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block break-words text-sm text-primary">
                          {option.label}
                        </span>
                        {option.description && (
                          <span className="mt-0.5 block break-words text-xs text-muted">
                            {option.description}
                          </span>
                        )}
                      </span>
                    </label>
                  );
                })}

                {/*
                 * 「其他」的输入框不能嵌在 label 里：label 会把点击转发给单选/复选控件，
                 * 用户在输入框里点一下就会把勾选切掉。所以 label 只包控件和文字。
                 * 题目没有选项时，「其他」就是唯一答案，直接给输入框。
                 */}
                {question.options.length === 0 ? (
                  <input
                    ref={(node) => {
                      otherRefs.current[questionIndex] = node;
                    }}
                    type="text"
                    value={draft.other}
                    placeholder={t("run.answerPlaceholder")}
                    aria-label={question.question}
                    onChange={(event) =>
                      updateDraft(question.question, questionIndex, { other: event.target.value })
                    }
                    className="w-full rounded-lg border border-border/60 bg-surface-1 px-2.5 py-2 text-sm text-primary placeholder:text-muted focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  />
                ) : (
                  <div
                    className={`rounded-lg border px-2.5 py-2 transition-colors ${
                      draft.otherOn
                        ? "border-blue-500 bg-blue-500/5 dark:border-blue-400 dark:bg-blue-400/15"
                        : "border-border/60 bg-surface-1 hover:border-border"
                    }`}
                  >
                    <label className="flex cursor-pointer items-start gap-2.5">
                      <input
                        type={multi ? "checkbox" : "radio"}
                        name={`${tool.toolCallId}-q-${questionIndex}`}
                        checked={draft.otherOn}
                        onChange={(event) =>
                          toggleOther(questionIndex, question.question, event.target.checked, multi)
                        }
                        data-multi={multi ? "true" : undefined}
                        className="wait-option-input"
                      />
                      <span className="min-w-0 flex-1 text-sm text-primary">
                        {t("run.otherOption")}
                      </span>
                    </label>

                    {draft.otherOn && (
                      <input
                        ref={(node) => {
                          otherRefs.current[questionIndex] = node;
                        }}
                        type="text"
                        value={draft.other}
                        placeholder={t("run.otherPlaceholder")}
                        aria-label={t("run.otherAria", { question: question.question })}
                        onChange={(event) =>
                          updateDraft(question.question, questionIndex, { other: event.target.value })
                        }
                        className="mt-2 w-full rounded-md border border-border/60 bg-surface-2 px-2.5 py-1.5 text-sm text-primary placeholder:text-muted focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                      />
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2 px-3 pb-3">
        <button
          type="button"
          onClick={onSubmit}
          disabled={!canSubmit}
          className="rounded-lg border border-blue-600 bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:border-border disabled:bg-surface-3 disabled:text-muted disabled:hover:bg-surface-3"
        >
          {t("run.submit")}
        </button>
      </div>
    </div>
  );
}

interface RunningToolRowProps {
  execution: ToolExecution;
  /** 连接已断开：工具结果可能已经错过，不能再假装还在执行。 */
  stale: boolean;
}

/** 正在执行的工具:一行紧凑提示。 */
function RunningToolRow({ execution, stale }: RunningToolRowProps) {
  const { t } = useTranslation();
  const { Icon } = styleForTool(execution.toolName);

  return (
    <div className="flex items-center gap-2 px-1 text-sm text-muted">
      <Icon className="h-4 w-4 flex-shrink-0" />
      {stale ? (
        <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-current opacity-40" />
      ) : (
        <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />
      )}
      <span>{execution.toolName}</span>
      {stale && <span className="text-xs text-faint">{t("run.toolStatusUnknown")}</span>}
    </div>
  );
}

export interface ChatConversationProps {
  messages: ChatMessage[];
  /**
   * 恢复的历史是否已就绪。恢复期间先订阅、后查历史，审批事件可能先到；
   * 历史落地前不渲染消息与挂起卡片，避免"空白 + 突兀弹窗"。
   */
  historyReady?: boolean;
  streamingContent: string;
  toolExecutions: ToolExecution[];
  /** 全部挂起的审批：服务端可同时挂起多条，逐张渲染，避免先到的被后来的覆盖。 */
  pendingApprovals: ApprovalRequest[];
  /** 全部挂起的交互式提问，规则同上。 */
  interactiveTools: InteractiveTool[];
  /** toolCallId → 问题原文 → 答案，多张交互卡互不干扰。 */
  toolAnswers: Record<string, Record<string, ToolAnswerValue>>;
  /** 对话通道连接状态：非 connected 时工具行标"执行状态未知"。 */
  connectionState: ConnectionState;
  isLoading: boolean;
  /** 本次对话产生/修改的文件（来源见 `pages/chat/useSessionFiles.ts`） */
  producedFiles?: SessionFile[];
  /**
   * 正文里相对链接的候选基准（按优先级；见 `agentLinkRoots`）。
   * 存在性校验通过后才渲染成按钮。请用 `useMemo` 保持引用稳定。
   */
  linkRoots?: readonly string[];
  onAnswerChange: (toolCallId: string, question: string, value: ToolAnswerValue) => void;
  onApprovalRespond: (approvalId: string, decision: string) => void;
  onToolSubmit: (toolCallId: string) => void;
  /** 点击文件（工具卡下方 chip / 末尾汇总）时打开右侧面板 */
  onOpenFile?: (path: string) => void;
}

export function ChatConversation({
  messages,
  historyReady = true,
  streamingContent,
  toolExecutions,
  pendingApprovals,
  interactiveTools,
  toolAnswers,
  connectionState,
  isLoading,
  producedFiles = [],
  linkRoots = EMPTY_LINK_ROOTS,
  onAnswerChange,
  onApprovalRespond,
  onToolSubmit,
  onOpenFile,
}: ChatConversationProps) {
  const { t } = useTranslation();
  const endRef = useRef<HTMLDivElement>(null);

  /** 需要扫描相对链接的正文：历史助手消息 + 流式中的正文。 */
  const linkTexts = useMemo(() => {
    const texts = messages
      .filter((message) => message.role === "assistant")
      .map((message) => message.content);
    if (streamingContent !== "") texts.push(streamingContent);
    return texts;
  }, [messages, streamingContent]);

  /*
   * 相对链接要**先校验存在性**再出按钮：相对路径的基准不一定是会话 cwd，
   * 交给服务端在候选根里逐个试（见 `useResolvedLinks`）。
   */
  /*
   * 行内代码里的相对路径：只把“与本次产物同名”的候选交给服务端校验。
   * 这样 `B/A.pdf`（B 是 Bash 复制出来的，不在产物集合里）能校验成 B，
   * 而 `src/api/client.ts` 这类普通代码引用不会被变成按钮。
   */
  const inlineCandidates = useMemo(() => {
    if (producedFiles.length === 0) return EMPTY_LINK_ROOTS;
    const producedNames = new Set(
      producedFiles.map((file) => comparableBaseName(file.path)),
    );
    return collectInlineCodePaths(linkTexts).filter((value) =>
      producedNames.has(comparableBaseName(value)),
    );
  }, [linkTexts, producedFiles]);

  const resolveRelativeLink = useResolvedLinks(linkTexts, linkRoots, inlineCandidates);

  /*
   * 行内文件引用：命中“本次对话写过的文件”（精确/后缀/唯一 basename）才变成按钮；
   * 显式链接里的相对路径则用上面校验过的结果 —— 脚本生成的图片等产物不会出现在
   * Write/Edit 集合里，只靠产物集合会永远点不开。
   *
   * 用整个会话的产物集合，而不是按轮 —— 工具结果与正文的到达顺序不保证，
   * 按轮切会让同一轮里先到的正文点不开后到的文件。
   */
  const fileMentions = useMemo<FileMentions | undefined>(() => {
    if (onOpenFile === undefined) return undefined;
    const produced = producedFiles.map((file) => file.path);
    return {
      resolve: (value: string) => resolveMention(value, produced),
      resolvePath: resolveRelativeLink,
      open: onOpenFile,
    };
  }, [onOpenFile, producedFiles, resolveRelativeLink]);

  /*
   * 有新内容就贴底。
   *
   * 不能用 `scrollIntoView`：它会**同时滚动所有可滚动祖先**，包括 iframe 的
   * document。审批 / 提问卡出现时内容变高，document 若有一点点可滚动余量，
   * 整页会被一起滚下去，右侧出现两条滚动条、正文被滚出视口。
   * 这里只滚消息区自己（最近的 overflow-y: auto/scroll 祖先）。
   */
  useEffect(() => {
    const end = endRef.current;
    if (end === null) return;

    let container: HTMLElement | null = end.parentElement;
    while (container !== null) {
      const overflowY = getComputedStyle(container).overflowY;
      if (overflowY === "auto" || overflowY === "scroll") break;
      container = container.parentElement;
    }
    if (container === null) return;

    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [
    messages,
    historyReady,
    streamingContent,
    toolExecutions,
    pendingApprovals,
    interactiveTools,
  ]);

  // 恢复期间历史还没落位：用专门的就绪提示，别复用"AI 正在思考"
  const showThinking =
    historyReady && isLoading && !streamingContent && toolExecutions.length === 0;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-4 py-6 sm:px-6">
      {!historyReady && (
        <div className="flex items-center gap-2 px-1 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin text-accent" />
          <span>{t("run.restoring")}</span>
        </div>
      )}

      {historyReady &&
        messages.map((message) => (
          <MessageRow
            key={message.id}
            message={message}
            onOpenFile={onOpenFile}
            fileMentions={fileMentions}
          />
        ))}

      {/* 流式中的助手回复 */}
      {historyReady && streamingContent && (
        <div className="flex flex-col items-start gap-1.5">
          <div className="flex items-center gap-2 px-1 text-xs text-muted">
            <span className="font-medium">{t("run.aiAssistant")}</span>
          </div>
          <div className="max-w-[min(52rem,92%)] rounded-2xl rounded-bl-sm border border-border/50 bg-surface-2/60 px-4 py-3">
            <MarkdownContent text={streamingContent} />
          </div>
        </div>
      )}

      {/* 在执行的工具 */}
      {historyReady && toolExecutions.length > 0 && (
        <div className="flex flex-col gap-1 pl-1">
          {toolExecutions.map((execution) => (
            <RunningToolRow
              key={execution.toolCallId}
              execution={execution}
              stale={connectionState !== "connected"}
            />
          ))}
        </div>
      )}

      {/* 还在等首字节 */}
      {showThinking && (
        <div className="flex items-center gap-2 px-1 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin text-accent" />
          <span>{t("run.thinking")}</span>
        </div>
      )}

      {historyReady &&
        pendingApprovals.map((approval) => (
          <ApprovalCard
            key={approval.approvalId}
            approval={approval}
            onRespond={(decision) => onApprovalRespond(approval.approvalId, decision)}
          />
        ))}

      {historyReady &&
        interactiveTools.map((tool) => (
          <InteractiveCard
            key={tool.toolCallId}
            tool={tool}
            answers={toolAnswers[tool.toolCallId] ?? {}}
            onAnswerChange={(question, value) => onAnswerChange(tool.toolCallId, question, value)}
            onSubmit={() => onToolSubmit(tool.toolCallId)}
          />
        ))}

      <div ref={endRef} />
    </div>
  );
}
