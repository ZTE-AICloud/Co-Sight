/**
 * 跨契约复用的基础校验片段。
 */

import { z } from 'zod';

/**
 * 只接受 http / https 的 URL。
 *
 * 不能直接用 `z.url()`：它按 RFC 3986 解析，`localhost:8080` 会被判定为
 * 一个 scheme 叫 `localhost` 的合法 URL，`file:` 与 `javascript:` 同样能过。
 * 这些值最终会变成 fetch 目标或 iframe src，必须收紧协议。
 */
export const httpUrlSchema = z.url({ protocol: /^https?$/ });

/**
 * 绝对路径。拒绝相对路径与 `~`（波浪号展开属于上层职责，不应写进数据）。
 * 同时接受 POSIX（`/srv/x`）与 Windows（`D:\x`）形式。
 */
export const absolutePathSchema = z
  .string()
  .trim()
  .min(1)
  .max(1024)
  .refine((value) => value.startsWith('/') || /^[A-Za-z]:[\\/]/.test(value), {
    message: '必须是绝对路径',
  });

/**
 * 路径参数里的资源 id。
 *
 * 统一按 uuid 校验，而不是 `z.string().min(1)`：所有表的主键都是 uuid，
 * 提前在入口挡掉 `../` 这类字符串，比让它走到查询层再返回"未找到"更清楚。
 */
export const idParamsSchema = z.object({ id: z.uuid() });

export type IdParams = z.infer<typeof idParamsSchema>;
