// SPDX-License-Identifier: Apache-2.0
/**
 * @file run-reasons.ts
 * @description 运行终止原因的服务端原文 → 界面语言。
 *
 * 原因来自 smart-factory 的自由文本（`runs.repo.ts` 的「服务重启」、
 * `chat.aborted` 的「用户中止」，以及引擎透传的任意错误）。这里只翻译**已知**的几条，
 * 未知值原样返回 —— 诊断信息不能被吞掉。
 */

import type { TFunction } from "i18next";

/** 已知固定原因 → i18n key。新增已知原因时在这里补一行即可。 */
const KNOWN_RUN_REASONS: Readonly<Record<string, string>> = {
  "服务重启": "run.serverRestart",
  "用户中止": "run.userAborted",
};

/** 已知原因本地化；空值返回 null（由调用方决定兜底文案）。 */
export function localizeRunReason(reason: unknown, t: TFunction): string | null {
  if (typeof reason !== "string" || reason.trim() === "") return null;
  const key = KNOWN_RUN_REASONS[reason.trim()];
  return key === undefined ? reason : t(key);
}
