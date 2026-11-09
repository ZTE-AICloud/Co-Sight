// SPDX-License-Identifier: Apache-2.0
/**
 * @file types.ts
 * @description 附件来源的公共契约。
 *
 * 开源版本地单机用 `local-path`：选择器返回真实绝对路径，零拷贝。
 * 商用云容器版将来用 `upload`：浏览器选文件、上传到云端，返回云端引用。
 *
 * UI（菜单 / chips / 发送 / 消息渲染）只依赖 `AttachmentRef`，
 * 不感知具体来源 —— 商用版实现一个新的 `AttachmentProvider` 即可。
 */

export type AttachmentMode = "local-path" | "upload";

/** 一次选择得到的附件。 */
export interface AttachmentRef {
  /** 前端 chip 的稳定 id（本地路径 / 云端文件 id） */
  id: string;
  /** 展示名；local-path 模式存绝对路径，渲染时取 basename */
  name: string;
  source: AttachmentMode;
  /** local-path 模式：真实绝对路径 */
  path?: string;
  /** upload 模式：云端文件 id / URL */
  fileId?: string;
  url?: string;
}

/** 发给会话服务的线上形状；具体字段由各模式的后端契约决定。 */
export interface AttachmentWire {
  path?: string;
  fileId?: string;
  url?: string;
}

/** 消息落库后的附件形状（服务端 `content.files`）。 */
export interface MessageFile {
  id: string;
  name: string;
}

/**
 * 商用版扩展点。
 *
 * 实现 `pick()`（选择 + 上传）和 `toWire()`（映射成云端会话服务要的形状），
 * 在 `useAttachmentPicker` 里按 mode 切换即可，不用改 UI。
 */
export interface AttachmentProvider {
  pick(options: { max: number }): Promise<AttachmentRef[]>;
  toWire(refs: AttachmentRef[]): AttachmentWire[];
}
