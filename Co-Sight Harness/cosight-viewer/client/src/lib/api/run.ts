// SPDX-License-Identifier: Apache-2.0
/**
 * @file run.ts
 * @description 仅保留新建会话弹窗需要的工作目录建议；CLI run 的
 * start/send/kill 已随续聊链路迁到 `/chat` 的 WebSocket。
 */

import { request } from "./core";

export interface CwdSuggestion {
  kind: "dashboard" | "home" | "recent";
  path: string;
  label: string;
}

export const runApi = {
  cwds: () => request<{ items: CwdSuggestion[] }>("/run/cwds"),
};
