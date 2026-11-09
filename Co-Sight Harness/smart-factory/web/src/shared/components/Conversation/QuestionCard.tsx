/**
 * AskUserQuestion 的应答体：多道题、单选 / 多选、每题可「其他」自由填写。
 *
 * 状态按**问题下标**存，不按问题原文 —— 后端把问题原文当 answers 的 key，
 * 若两道题文字恰好相同，按原文做 UI key 会让两题共享一份选择。组装答案时再按原文收敛，
 * 重复的原文后者覆盖前者（这是后端契约本身的限制，不是这里能绕开的）。
 *
 * 控件用原生 radio / checkbox（视觉隐藏、保留可聚焦），而不是手写 role + aria-checked：
 * radio 组的方向键、Tab 顺序、checked 语义都由浏览器负责，自己实现只会更容易出错。
 */

import { useId, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { useI18n } from '../../../i18n/useI18n';
import type { WaitQuestion } from './types';

/** 一道题在界面上的草稿 */
interface AnswerDraft {
  /** 已选中的 option label */
  picked: string[];
  /** 是否勾了「其他」 */
  otherOn: boolean;
  /** 「其他」里填的内容 */
  other: string;
}

const EMPTY: AnswerDraft = { picked: [], otherOn: false, other: '' };

export interface QuestionCardProps {
  questions: WaitQuestion[];
  /** 提交中：控件整体禁用（父组件的提交闸门） */
  submitting: boolean;
  /** 不传 = 只读视图：能看不能答 */
  onSubmit?: (answers: Record<string, string[]>) => void;
}

export function QuestionCard({ questions, submitting, onSubmit }: QuestionCardProps) {
  const { t } = useI18n();
  const id = useId();
  const [drafts, setDrafts] = useState<Record<number, AnswerDraft>>({});
  const otherRefs = useRef<Record<number, HTMLInputElement | null>>({});

  const readonly = onSubmit === undefined;
  const canSubmit =
    !submitting &&
    !readonly &&
    questions.every((question, index) => isAnswered(question, drafts[index]));

  function draftOf(index: number): AnswerDraft {
    return drafts[index] ?? EMPTY;
  }

  function update(index: number, patch: Partial<AnswerDraft>) {
    setDrafts((current) => ({
      ...current,
      [index]: { ...(current[index] ?? EMPTY), ...patch },
    }));
  }

  /** 单选：点一项就替换，并自动取消「其他」 */
  function pickSingle(index: number, label: string) {
    update(index, { picked: [label], otherOn: false });
  }

  /** 多选：在集合里加 / 删，不影响「其他」 */
  function toggleMulti(index: number, label: string) {
    const draft = draftOf(index);
    update(index, {
      picked: draft.picked.includes(label)
        ? draft.picked.filter((item) => item !== label)
        : [...draft.picked, label],
    });
  }

  /** 勾「其他」：单选时会清掉已选 option（两者互斥），多选时并存 */
  function toggleOther(index: number, on: boolean, multi: boolean) {
    update(index, { otherOn: on, ...(multi ? {} : { picked: [] }) });
    if (on) {
      // 等这一帧把输入框渲染出来再聚焦
      requestAnimationFrame(() => otherRefs.current[index]?.focus());
    }
  }

  function assemble(): Record<string, string[]> {
    const answers: Record<string, string[]> = {};
    for (const [index, question] of questions.entries()) {
      const values = [...new Set(valuesOf(question, draftOf(index)))].filter((value) => value !== '');
      if (values.length > 0) answers[question.question] = values;
    }
    return answers;
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    // 回车也能提交，所以不能只靠按钮的 disabled
    if (!canSubmit) return;
    onSubmit?.(assemble());
  }

  return (
    <form className="conversation__question" onSubmit={handleSubmit}>
      {questions.length === 0 ? (
        <p className="conversation__wait-note">{t('conversation.wait.noQuestions')}</p>
      ) : (
        questions.map((question, index) => {
          const draft = draftOf(index);
          const options = question.options ?? [];
          const multi = question.multiSelect === true;
          const name = `${id}-q${String(index)}`;

          return (
            <fieldset
              key={`${String(index)}-${question.question}`}
              className="conversation__question-item"
              disabled={submitting || readonly}
            >
              <legend className="conversation__question-legend">
                {question.header !== '' && (
                  <span className="conversation__wait-tag">{question.header}</span>
                )}
                <span className="conversation__question-text">{question.question}</span>
                {multi && (
                  <span className="conversation__wait-hint">{t('conversation.wait.multiSelect')}</span>
                )}
              </legend>

              <div className="conversation__wait-opts">
                {options.map((option) => (
                  <label
                    key={option.label}
                    className="conversation__wait-opt"
                    data-multi={multi ? 'true' : undefined}
                  >
                    <input
                      className="conversation__wait-radio"
                      type={multi ? 'checkbox' : 'radio'}
                      name={name}
                      value={option.label}
                      // 单选时「其他」与选项互斥：勾了「其他」，这一项就不算选中
                      checked={
                        draft.picked.includes(option.label) && (multi || !draft.otherOn)
                      }
                      onChange={() => {
                        if (multi) toggleMulti(index, option.label);
                        else pickSingle(index, option.label);
                      }}
                    />
                    <span className="conversation__wait-mark" />
                    <span className="conversation__wait-opt-body">
                      <span className="conversation__wait-opt-label">{option.label}</span>
                      {option.description !== undefined && option.description !== '' && (
                        <span className="conversation__wait-opt-desc">{option.description}</span>
                      )}
                    </span>
                  </label>
                ))}

                {/*
                 * 「其他」的输入框**不能**嵌在 label 里：label 会把点击转发给单选/复选控件，
                 * 用户在输入框里点一下就会把勾选切掉。所以这行是 div，label 只包控件和文字。
                 *
                 * 题目没有选项时「其他」就是唯一答案，直接给输入框 —— 再让人先勾一下
                 * 「其他」才出现输入框，是道没必要的坎。
                 */}
                {options.length === 0 ? (
                  <input
                    ref={(node) => {
                      otherRefs.current[index] = node;
                    }}
                    className="conversation__wait-other"
                    type="text"
                    value={draft.other}
                    placeholder={t('conversation.wait.answerPlaceholder')}
                    aria-label={question.question}
                    onChange={(event) => update(index, { other: event.target.value })}
                  />
                ) : (
                  <div
                    className="conversation__wait-opt conversation__wait-opt--other"
                    data-multi={multi ? 'true' : undefined}
                  >
                    <label className="conversation__wait-opt-head">
                      <input
                        className="conversation__wait-radio"
                        type={multi ? 'checkbox' : 'radio'}
                        name={name}
                        checked={draft.otherOn}
                        onChange={(event) => toggleOther(index, event.target.checked, multi)}
                      />
                      <span className="conversation__wait-mark" />
                      <span className="conversation__wait-opt-body">
                        <span className="conversation__wait-opt-label">
                          {t('conversation.wait.other')}
                        </span>
                      </span>
                    </label>

                    {draft.otherOn && (
                      <input
                        ref={(node) => {
                          otherRefs.current[index] = node;
                        }}
                        className="conversation__wait-other"
                        type="text"
                        value={draft.other}
                        placeholder={t('conversation.wait.otherPlaceholder')}
                        aria-label={t('conversation.wait.otherAria', { question: question.question })}
                        onChange={(event) => update(index, { other: event.target.value })}
                      />
                    )}
                  </div>
                )}
              </div>
            </fieldset>
          );
        })
      )}

      <div className="conversation__question-foot">
        {readonly ? (
          <span className="conversation__wait-hint">{t('conversation.wait.readonly')}</span>
        ) : (
          <>
            <button
              type="submit"
              className="conversation__wait-btn conversation__wait-btn--primary"
              disabled={!canSubmit}
            >
              {submitting
                ? t('conversation.wait.submitting')
                : questions.length === 0
                  ? t('conversation.wait.continue')
                  : t('conversation.wait.submit')}
            </button>
            <span className="conversation__wait-hint">{t('conversation.wait.submitHint')}</span>
          </>
        )}
      </div>
    </form>
  );
}

/** 这道题是否已经能提交 */
function isAnswered(question: WaitQuestion, draft: AnswerDraft | undefined): boolean {
  const current = draft ?? EMPTY;
  const other = current.other.trim();
  if (question.options === undefined || question.options.length === 0) {
    // 没有选项时，「其他」就是唯一的回答方式
    return other !== '';
  }
  if (question.multiSelect === true) return current.picked.length > 0 || other !== '';
  return current.otherOn ? other !== '' : current.picked.length === 1;
}

/** 一道题提交上去的字符串数组：单选「其他」替代选项，多选「其他」追加在后面 */
function valuesOf(question: WaitQuestion, draft: AnswerDraft): string[] {
  const other = draft.other.trim();
  // 没有选项时输入框就是唯一答案，与 otherOn 无关
  if (question.options === undefined || question.options.length === 0) {
    return other === '' ? [] : [other];
  }
  if (question.multiSelect !== true) {
    return draft.otherOn ? (other === '' ? [] : [other]) : draft.picked;
  }
  const picked = draft.picked.filter((label) => label !== '');
  return draft.otherOn && other !== '' ? [...picked, other] : picked;
}
