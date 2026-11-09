// SPDX-License-Identifier: Apache-2.0
/**
 * @file useAttachmentPicker.tsx
 * @description 附件选择器的模式适配层。
 *
 * 开源版本地单机：`local-path` —— 弹自研文件选择器，返回真实绝对路径。
 * 商用云容器版：`upload` —— 浏览器 `<input type="file">` + 云端上传，
 * 返回 `{ fileId/path/url }`。本次只留扩展点，不实现上传。
 *
 * 调用方（ChatComposer）只认 `pick(max)` 与 `element`，不关心模式。
 */

import { useCallback, useRef, useState } from "react";
import type { ReactNode } from "react";
import { FilePickerDialog } from "../components/chat/FilePickerDialog";
import type { PickedFile } from "../components/chat/FilePickerDialog";
import type { AttachmentMode, AttachmentRef } from "./types";

/** 运行时注入；缺省按本地单机处理。 */
function attachmentMode(): AttachmentMode {
  const injected = (window as { __ATTACHMENT_MODE__?: unknown }).__ATTACHMENT_MODE__;
  return injected === "upload" ? "upload" : "local-path";
}

export function useAttachmentPicker(): {
  /** 打开选择器；取消返回空数组。 */
  pick: (max: number) => Promise<AttachmentRef[]>;
  /** 挂在页面任意位置即可（自带 portal） */
  element: ReactNode;
} {
  const [open, setOpen] = useState(false);
  const maxRef = useRef(20);
  const resolveRef = useRef<((files: AttachmentRef[]) => void) | null>(null);
  const mode = attachmentMode();

  const pick = useCallback(
    (max: number) => {
      if (mode === "upload") {
        // TODO(commercial): <input type="file" multiple> → 云端上传接口 →
        // { source: "upload", fileId/path/url, name }。
        return Promise.reject(new Error("upload attachment mode is not implemented yet"));
      }
      return new Promise<AttachmentRef[]>((resolve) => {
        resolveRef.current = resolve;
        maxRef.current = Math.max(0, max);
        setOpen(true);
      });
    },
    [mode],
  );

  const settle = useCallback((files: PickedFile[] | null) => {
    const resolve = resolveRef.current;
    resolveRef.current = null;
    setOpen(false);
    resolve?.(
      files === null
        ? []
        : files.map((file) => ({
            id: file.path,
            name: file.path,
            source: "local-path" as const,
            path: file.path,
          })),
    );
  }, []);

  const element =
    mode === "local-path" ? (
      <FilePickerDialog
        open={open}
        max={maxRef.current}
        onCancel={() => settle(null)}
        onConfirm={(files) => settle(files)}
      />
    ) : null;

  return { pick, element };
}
