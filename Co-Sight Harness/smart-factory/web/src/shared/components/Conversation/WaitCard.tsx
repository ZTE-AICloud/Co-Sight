/**
 * 等待用户应答的卡片：工具审批 / AskUserQuestion。
 *
 * 它内联在助手这一轮的消息流里（过程折叠区之后、最终回答之前），不是输入框上方的浮层 ——
 * 一条挂起消息对应一张卡，同一轮里可以有多张，服务端本来也允许一个 run 同时挂起多条。
 *
 * 提交约定（与 `useLiveSession.respond` 对齐）：
 *   - action() 返回 true  = 已结算 / 已被别处结算，按钮保持禁用，等同 id 的结算快照替换整张卡；
 *   - action() 返回 false = 可恢复失败（提示已由 Hook 弹出），这里把按钮放开让用户重试。
 *
 * 卡片本身不出网：回调从 Conversation 一路传下来，它只负责收集答案。
 */

import { useMemo, useRef, useState } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import type { MessageKey, MessageParams } from '../../../i18n/types';
import { Icon } from '../Icon';
import { QuestionCard } from './QuestionCard';
import type { WaitDecision, WaitRequest } from './types';
import './WaitCard.css';

/** 参数预览的长度上限：再长就截断，不让一段 JSON 把对话框撑成文档 */
const INPUT_LIMIT = 4000;

export interface WaitCardProps {
  messageId: string;
  wait: WaitRequest;
  /** 不传 = 只读视图 */
  onApproval?: (messageId: string, decision: WaitDecision) => Promise<boolean>;
  onAnswers?: (messageId: string, answers: Record<string, string[]>) => Promise<boolean>;
}

export function WaitCard({ messageId, wait, onApproval, onAnswers }: WaitCardProps) {
  const { t } = useI18n();
  const [submitting, setSubmitting] = useState(false);
  /** 同一次渲染里的连点会双双读到 submitting=false，必须用 ref 挡 */
  const submittingRef = useRef(false);

  /** 参数序列化可能很贵（大工具入参），只在 input 变的时候算一次 */
  const argsText = useMemo(
    () => (wait.kind === 'approval' ? formatInput(wait.input, t) : null),
    [wait, t],
  );

  async function run(action: (() => Promise<boolean>) | undefined) {
    if (action === undefined || submittingRef.current) return;

    submittingRef.current = true;
    setSubmitting(true);

    let settled = false;
    try {
      settled = await action();
    } catch {
      settled = false;
    }

    // 成功时别急着恢复：结算快照马上会把整张卡换掉；恢复反而会闪一下可点态
    if (!settled) {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  const title =
    wait.kind === 'approval'
      ? wait.title || t('conversation.wait.needApproval')
      : t('conversation.wait.needAnswer');
  const allowAll = wait.kind === 'approval' && wait.allowAll !== false;

  return (
    <div className="conversation__wait" role="group" aria-label={title} aria-busy={submitting}>
      <div className="conversation__wait-head">
        <span className="conversation__wait-icon">
          <Icon name={wait.kind === 'approval' ? 'shield' : 'message'} size={14} />
        </span>
        <span className="conversation__wait-title">{title}</span>
        <span className="conversation__wait-kind">
          {wait.kind === 'approval'
            ? t('conversation.wait.kindApproval')
            : t('conversation.wait.kindQuestion')}
        </span>
      </div>

      {wait.kind === 'approval' ? (
        <>
          <div className="conversation__wait-body">
            {wait.toolName !== undefined && wait.toolName !== '' && (
              <div className="conversation__wait-tool">
                <b>{wait.toolName}</b>
              </div>
            )}
            {wait.description !== undefined && wait.description !== '' && (
              <p className="conversation__wait-desc">{wait.description}</p>
            )}
            {argsText !== null && (
              <pre
                className="conversation__wait-args"
                tabIndex={0}
                aria-label={t('conversation.wait.toolArgs')}
              >
                {argsText}
              </pre>
            )}
          </div>

          {onApproval !== undefined && (
            <div className="conversation__wait-foot">
              <button
                type="button"
                className="conversation__wait-btn conversation__wait-btn--primary"
                disabled={submitting}
                onClick={() => void run(() => onApproval(messageId, 'approved'))}
              >
                {t('conversation.wait.allowOnce')}
              </button>
              <button
                type="button"
                className="conversation__wait-btn"
                disabled={submitting || !allowAll}
                title={
                  allowAll
                    ? t('conversation.wait.allowAllHint')
                    : t('conversation.wait.allowAllDisabled')
                }
                onClick={() => void run(() => onApproval(messageId, 'approved_all'))}
              >
                {t('conversation.wait.allowAll')}
              </button>
              <button
                type="button"
                className="conversation__wait-btn conversation__wait-btn--danger"
                disabled={submitting}
                onClick={() => void run(() => onApproval(messageId, 'rejected'))}
              >
                {t('conversation.wait.reject')}
              </button>
            </div>
          )}
        </>
      ) : (
        <QuestionCard
          questions={wait.questions}
          submitting={submitting}
          onSubmit={
            onAnswers === undefined
              ? undefined
              : (answers) => {
                  void run(() => onAnswers(messageId, answers));
                }
          }
        />
      )}
    </div>
  );
}

/**
 * 工具入参的展示文本。
 *
 * `undefined` / `null` / 空对象都没有可看的东西，直接不渲染 —— 空 <pre> 只会占一块灰底。
 * JSON.stringify 对函数之类的入参会返回 undefined，所以留了 String() 兜底。
 */
function formatInput(
  input: unknown,
  t: (key: MessageKey, params?: MessageParams) => string,
): string | null {
  if (input === undefined || input === null) return null;
  if (typeof input === 'object' && !Array.isArray(input) && Object.keys(input).length === 0) {
    return null;
  }

  let text: string;
  try {
    text = JSON.stringify(input, null, 2) ?? String(input);
  } catch {
    text = String(input);
  }

  return text.length > INPUT_LIMIT
    ? `${text.slice(0, INPUT_LIMIT)}\n${t('conversation.wait.truncated')}`
    : text;
}
