// SPDX-License-Identifier: Apache-2.0
/**
 * @file tool-answers.test.ts
 * @description AskUserQuestion 草稿 → 提交载荷的纯函数。
 *
 * 重点覆盖「其他」的三种语义：单选替代选项、多选追加、没选项时唯一答案；
 * 以及空草稿必须收敛成空数组（不能再伪造空字符串答案）。
 */

import { describe, expect, it } from "vitest";
import {
  answerDraftOf,
  answerValuesOf,
  isQuestionAnswered,
} from "../tool-answers";
import type { AnswerableQuestion, ToolAnswerDraft } from "../tool-answers";

const SINGLE: AnswerableQuestion = {
  question: "Which one?",
  multiSelect: false,
  options: [{ label: "A" }, { label: "B" }],
};

const MULTI: AnswerableQuestion = {
  question: "Which ones?",
  multiSelect: true,
  options: [{ label: "A" }, { label: "B" }],
};

const OPEN: AnswerableQuestion = {
  question: "Describe it",
  multiSelect: false,
  options: [],
};

function draft(patch: Partial<ToolAnswerDraft> = {}): ToolAnswerDraft {
  return { picked: [], otherOn: false, other: "", ...patch };
}

describe("answerDraftOf", () => {
  it("把旧版字符串答案当成一个选项", () => {
    expect(answerDraftOf("B")).toEqual({ picked: ["B"], otherOn: false, other: "" });
  });

  it("把旧版数组答案当成多个选项", () => {
    expect(answerDraftOf(["A", "B"])).toEqual({
      picked: ["A", "B"],
      otherOn: false,
      other: "",
    });
  });

  it("空值得到空草稿", () => {
    expect(answerDraftOf(undefined)).toEqual({ picked: [], otherOn: false, other: "" });
  });

  it("复制草稿，不把内部数组暴露给调用方", () => {
    const source = draft({ picked: ["A"] });
    const copy = answerDraftOf(source);
    copy.picked.push("B");
    expect(source.picked).toEqual(["A"]);
  });
});

describe("answerValuesOf", () => {
  it("单选只取选中的选项", () => {
    expect(answerValuesOf(SINGLE, draft({ picked: ["B"] }))).toEqual(["B"]);
  });

  it("单选勾了「其他」时用文本替代选项", () => {
    expect(
      answerValuesOf(SINGLE, draft({ picked: ["A"], otherOn: true, other: " 自定义 " })),
    ).toEqual(["自定义"]);
  });

  it("单选勾了「其他」但没填内容时为空数组", () => {
    expect(answerValuesOf(SINGLE, draft({ otherOn: true, other: "   " }))).toEqual([]);
  });

  it("多选把「其他」追加在选项后面", () => {
    expect(
      answerValuesOf(MULTI, draft({ picked: ["A", "B"], otherOn: true, other: "C" })),
    ).toEqual(["A", "B", "C"]);
  });

  it("多选取消「其他」后忽略残留文本", () => {
    expect(
      answerValuesOf(MULTI, draft({ picked: ["A"], otherOn: false, other: "C" })),
    ).toEqual(["A"]);
  });

  it("没有选项时输入框就是唯一答案", () => {
    expect(answerValuesOf(OPEN, draft({ other: "一段描述" }))).toEqual(["一段描述"]);
    expect(answerValuesOf(OPEN, draft({ other: "" }))).toEqual([]);
  });
});

describe("isQuestionAnswered", () => {
  it("单选要选中一项或填了「其他」", () => {
    expect(isQuestionAnswered(SINGLE, draft())).toBe(false);
    expect(isQuestionAnswered(SINGLE, draft({ picked: ["A"] }))).toBe(true);
    expect(isQuestionAnswered(SINGLE, draft({ otherOn: true, other: "" }))).toBe(false);
    expect(isQuestionAnswered(SINGLE, draft({ otherOn: true, other: "A" }))).toBe(true);
  });

  it("多选要选中至少一项或勾选「其他」并填写", () => {
    expect(isQuestionAnswered(MULTI, draft())).toBe(false);
    expect(isQuestionAnswered(MULTI, draft({ picked: ["A"] }))).toBe(true);
    expect(isQuestionAnswered(MULTI, draft({ otherOn: true, other: "" }))).toBe(false);
    // 取消「其他」后残留的文本不算答案，和值收敛保持一致
    expect(isQuestionAnswered(MULTI, draft({ otherOn: false, other: "C" }))).toBe(false);
    expect(isQuestionAnswered(MULTI, draft({ otherOn: true, other: "C" }))).toBe(true);
  });

  it("没有选项时必须有文本", () => {
    expect(isQuestionAnswered(OPEN, draft())).toBe(false);
    expect(isQuestionAnswered(OPEN, draft({ other: "  " }))).toBe(false);
    expect(isQuestionAnswered(OPEN, draft({ other: "描述" }))).toBe(true);
  });
});
