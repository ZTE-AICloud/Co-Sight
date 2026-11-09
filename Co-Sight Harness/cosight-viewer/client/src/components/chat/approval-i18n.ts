// SPDX-License-Identifier: Apache-2.0
/**
 * @file approval-i18n.ts
 * @description 审批卡的界面文案：按钮按语义值取 i18n，标题识别服务端默认形态后本地化。
 *
 * 为什么要这层：按钮与标题都是 smart-factory 下发的数据 ——
 *   按钮：`{ value, label: '允许', enLabel: 'Allow' }`（服务端同时给了中英）；
 *   标题：`允许执行 ${toolName}？`（服务端拼好的中文）。
 * 界面文案归 viewer，所以这里统一按 `value` / 默认标题形态映射；
 * agent 自定义的标题、未知的选项值保持原文，不猜。
 */

import type { TFunction } from "i18next";

/** 服务端审批选项的最小形状（与 `ApprovalRequest['options'][number]` 同构）。 */
export interface ApprovalOptionLike {
  value: string;
  label: string;
  enLabel?: string;
}

/** 语义值 → i18n key（优先于服务端下发的中英文 label）。 */
const OPTION_KEYS: Readonly<Record<string, string>> = {
  approved: "run.approve",
  approved_all: "run.approveAll",
  rejected: "run.reject",
};

/**
 * 选项按钮文案。
 *
 * 已知语义值走 i18n（新增语言时不用等服务端补 `enLabel`）；
 * 未知值按界面语言优先 `enLabel`，再回退服务端原文。
 */
export function approvalOptionLabel(
  option: ApprovalOptionLike,
  language: string | undefined,
  t: TFunction
): string {
  const key = OPTION_KEYS[option.value];
  if (key !== undefined) return t(key);

  const isEnglish = (language ?? "").toLowerCase().startsWith("en");
  return isEnglish && option.enLabel !== undefined && option.enLabel !== ""
    ? option.enLabel
    : option.label;
}

/** 服务端默认标题：`允许执行 <toolName>？`（`claude-adapter.ts`）。 */
const DEFAULT_APPROVAL_TITLE_RE = /^允许执行 (.+)？$/;

/**
 * 审批卡标题。
 *
 * 命中默认形态时用本地化模板重新渲染（保留工具名）；
 * 其余标题（agent 自定义）原样返回；空标题回落到 `needApproval`。
 */
export function approvalTitle(
  title: string | undefined,
  t: TFunction
): string {
  const text = (title ?? "").trim();
  const match = DEFAULT_APPROVAL_TITLE_RE.exec(text);
  if (match !== null) {
    return t("run.approvalTitle", { toolName: match[1] });
  }
  return text !== "" ? text : t("run.needApproval");
}
