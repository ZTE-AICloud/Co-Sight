/**
 * 工作区文件浏览接口（只读）。
 *
 * 与 `api/workspaces.ts` 的分工：那边管工作区**记录**（建/切/删），这里管记录所指向
 * **目录里的内容**。分开的理由不是"文件多"，而是这两组接口的失败模式完全不同——
 * 记录坏了是"配置问题"，读不到文件是"这个文件不存在 / 不是文本 / 太大"，
 * 混在一起会让调用方对同一个 `404` 给出两种解释。
 *
 * 缓存键里带上**相对路径**：目录是逐个展开、逐个请求的，key 不带路径的话，
 * 展开第二个目录会直接命中第一个目录的缓存。
 *
 * 这里**不做乐观更新、不做轮询**：磁盘上的文件是别的进程在改，前端猜不准。
 * 只有面板上的刷新按钮与重新挂载会重取（`staleTime: 0`）。
 */

import type { WorkspaceFileImage, WorkspaceFileListing, WorkspaceFileText } from 'harness-shared';
import { useQuery } from '@tanstack/react-query';

import { requestData } from './client';

export const workspaceFileKeys = {
  all: ['workspaceFiles'] as const,
  directory: (workspaceId: string, path: string) =>
    ['workspaceFiles', workspaceId, 'directory', path] as const,
  text: (workspaceId: string, path: string) => ['workspaceFiles', workspaceId, 'text', path] as const,
  image: (workspaceId: string, path: string) => ['workspaceFiles', workspaceId, 'image', path] as const,
};

export const workspaceFilesApi = {
  /** 列一层目录。`path` 为空串表示工作区根。 */
  directory: (workspaceId: string, path: string, signal?: AbortSignal) =>
    requestData<WorkspaceFileListing>(`/workspaces/${workspaceId}/files`, {
      query: { path },
      signal,
    }),

  text: (workspaceId: string, path: string, signal?: AbortSignal) =>
    requestData<WorkspaceFileText>(`/workspaces/${workspaceId}/files/content`, {
      query: { path },
      signal,
    }),

  image: (workspaceId: string, path: string, signal?: AbortSignal) =>
    requestData<WorkspaceFileImage>(`/workspaces/${workspaceId}/files/image`, {
      query: { path },
      signal,
    }),
};

/**
 * 列目录。
 *
 * **懒加载是结构性的，不靠这个 hook 的开关**：没展开的目录节点根本不渲染，
 * 不渲染就没有这个 query，也就没有请求。整棵树一次性拉平（先递归列出所有子目录）
 * 会让打开一个代码仓库变成几百个请求，而用户通常只翻一层。
 *
 * `workspaceId` 允许为 `null`（当前没有工作区，或 `/workspaces/active` 还在路上）：
 * 这时候不发请求，但 query key 仍要有一个稳定的形状，所以空 id 落成空串。
 */
export function useWorkspaceDirectory(workspaceId: string | null, path: string) {
  return useQuery({
    queryKey: workspaceFileKeys.directory(workspaceId ?? '', path),
    queryFn: ({ signal }) => workspaceFilesApi.directory(workspaceId ?? '', path, signal),
    enabled: workspaceId !== null,
  });
}

/**
 * 读文本 / 读图片。
 *
 * 两个 hook 都收 `enabled`，因为**预览一次只可能是其中一种**：按扩展名选定走哪个
 * 端点后，另一个必须是关的——不关的话每点开一个文件都会同时发两个请求，其中一个
 * 注定 415，然后在控制台留下一条谁也解释不清的失败。
 */
export function useWorkspaceFileText(workspaceId: string | null, path: string, enabled: boolean) {
  return useQuery({
    queryKey: workspaceFileKeys.text(workspaceId ?? '', path),
    queryFn: ({ signal }) => workspaceFilesApi.text(workspaceId ?? '', path, signal),
    enabled: enabled && workspaceId !== null,
  });
}

export function useWorkspaceFileImage(workspaceId: string | null, path: string, enabled: boolean) {
  return useQuery({
    queryKey: workspaceFileKeys.image(workspaceId ?? '', path),
    queryFn: ({ signal }) => workspaceFilesApi.image(workspaceId ?? '', path, signal),
    enabled: enabled && workspaceId !== null,
  });
}
