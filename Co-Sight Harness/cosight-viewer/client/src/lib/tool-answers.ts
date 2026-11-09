// SPDX-License-Identifier: Apache-2.0
/**
 * @file tool-answers.ts
 * @description AskUserQuestion 答案的界面草稿与线上载荷之间的纯函数。
 *
 * 与 smart-factory 的 `QuestionCard` 保持同一套语义：
 * - 单选：选项与「其他」互斥，「其他」里的文本替代选项；
 * - 多选：选项与「其他」并存，「其他」里的文本追加在选项后面；
 * - 没有选项时，「其他」输入框就是唯一答案。
 *
 * 草稿按问题原文存放（`toolAnswers[toolCallId][question]`），提交时再收敛成
 * `string[]`：服务端接受字符串数组，空数组表示“这题没有回答”。
 */

/** 一道题在界面上的草稿。 */
export interface ToolAnswerDraft {
  /** 已选中的 option label */
  picked: string[];
  /** 是否勾了「其他」 */
  otherOn: boolean;
  /** 「其他」里填的内容 */
  other: string;
}

/**
 * 用户回答。
 *
 * `string` / `string[]` 是旧版纯选项答案，保留是为了兼容既有调用方与测试；
 * 新版界面统一写 `ToolAnswerDraft`。
 */
export type ToolAnswerValue = string | string[] | ToolAnswerDraft;

/** 只用到答题卡片关心的字段，避免和页面层类型互相依赖。 */
export interface AnswerableQuestion {
  question: string;
  multiSelect: boolean;
  options: ReadonlyArray<{ label: string }>;
}

const EMPTY_DRAFT: ToolAnswerDraft = { picked: [], otherOn: false, other: "" };

/** 读出可安全修改的草稿：旧版答案是纯标签，等价于“选了这些选项、没填其他”。 */
export function answerDraftOf(value: ToolAnswerValue | undefined): ToolAnswerDraft {
  if (value === undefined) return { ...EMPTY_DRAFT };
  if (typeof value === "string") {
    return { picked: value === "" ? [] : [value], otherOn: false, other: "" };
  }
  if (Array.isArray(value)) {
    return { picked: value.filter((item) => item !== ""), otherOn: false, other: "" };
  }
  return { picked: [...value.picked], otherOn: value.otherOn, other: value.other };
}

/** 草稿 → 提交给服务端的答案数组（空数组 = 这题未回答）。 */
export function answerValuesOf(
  question: AnswerableQuestion,
  draft: ToolAnswerDraft,
): string[] {
  const other = draft.other.trim();
  const picked = draft.picked.filter((label) => label !== "");

  let values: string[];
  if (question.options.length === 0) {
    values = other === "" ? [] : [other];
  } else if (!question.multiSelect) {
    values = draft.otherOn ? (other === "" ? [] : [other]) : picked.slice(0, 1);
  } else {
    values = draft.otherOn && other !== "" ? [...picked, other] : picked;
  }
  return [...new Set(values)];
}

/** 这道题是否已经能提交（与服务端“空数组 = 未回答”保持一致）。 */
export function isQuestionAnswered(
  question: AnswerableQuestion,
  draft: ToolAnswerDraft,
): boolean {
  const other = draft.other.trim();
  if (question.options.length === 0) return other !== "";
  if (question.multiSelect) {
    return draft.picked.length > 0 || (draft.otherOn && other !== "");
  }
  return draft.otherOn ? other !== "" : draft.picked.length === 1;
}
