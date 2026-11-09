// SPDX-License-Identifier: Apache-2.0
/**
 * @file wire.ts
 * @description 附件 → 会话服务线上形状。
 *
 * local-path 只会产生 `{ path }`；upload 分支按云端契约输出
 * `{ fileId }` / `{ url }`。UI 与 `useChatSession` 都只调用这里。
 */

import type { AttachmentRef, AttachmentWire } from "./types";

export function toWire(refs: AttachmentRef[]): AttachmentWire[] {
  const wires: AttachmentWire[] = [];
  for (const ref of refs) {
    if (ref.source === "upload") {
      if (ref.fileId !== undefined) wires.push({ fileId: ref.fileId });
      else if (ref.url !== undefined) wires.push({ url: ref.url });
      continue;
    }
    if (ref.path !== undefined) wires.push({ path: ref.path });
  }
  return wires;
}
