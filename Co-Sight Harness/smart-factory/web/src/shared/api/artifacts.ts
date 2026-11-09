/**
 * 产物浏览的数据入口（后端契约见 `server/docs/03-architecture/07-artifact.md`）。
 *
 * 四个 stage 根都在 `<workspace.directory>/.smart-factory/agents/{agentId}/` 之下：
 * `development/`、`preview/`、`evaluation/`，以及嵌在开发产物里的 `runtime`（最新 `vN` 版本目录）。
 * 后端只提供只读能力 —— 列目录、读文本、下载原始流，写方是会话里的引擎，前端不碰。
 *
 * ── path 是相对 **stage 根** 的 ────────────────────────────────────────────
 *
 * 这是最容易拼错的一处：`path` 从 stage 根算起，**不是**从工作区算起、也不带 `agentId`
 * —— 服务端已经按 `agentId` 解析到了这个智能体的 agentRoot，再进对应 stage 目录。
 * 所以智能体根下的 `CLAUDE.md` 就是 `path=CLAUDE.md`，列根目录则省略 `path`。
 * `agentId` 参数只做形态校验与工作区解析，**不参与目录拼接**。
 */

import type { PageResult } from '../types';
import { API_BASE_URL, createApiClient } from './client';
import type { InstanceStage } from './sessions';

/** 目录项。`size` 是字节；目录恒为 0。 */
export interface ArtifactEntry {
  name: string;
  type: 'dir' | 'file';
  size: number;
  mtime: string;
}

/** 文本文件内容。仅 UTF-8，超过上限（默认 2 MiB）后端回 413。 */
export interface ArtifactFile {
  name: string;
  size: number;
  mtime: string;
  content: string;
}

export interface ArtifactListQuery {
  stage: InstanceStage;
  agentId: string;
  /** 相对 **stage 根** 的路径；缺省/空串是 stage 根本身 */
  path?: string;
}

export interface ArtifactFileQuery {
  stage: InstanceStage;
  agentId: string;
  /** 相对 stage 根的**文件**路径，必填 */
  path: string;
}

const BASE_URL = import.meta.env.VITE_ARTIFACTS_API_BASE_URL ?? `${API_BASE_URL}/smart-factory/v1`;

const client = createApiClient(BASE_URL);

function queryString(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, value);
  }
  return search.toString();
}

export const artifactsApi = {
  /**
   * 列目录。目录项平铺返回、不分页；排序（目录在前、名称升序）由后端给，前端不重排。
   *
   * 路径不存在是 404 `NOT_FOUND` —— 目录在会话/运行首次用到时才会被建出来，
   * 「还没有工作空间」是常态，调用方应把它当成空目录而不是故障。
   */
  list(input: ArtifactListQuery): Promise<PageResult<ArtifactEntry>> {
    const search = queryString({
      stage: input.stage,
      agentId: input.agentId,
      path: input.path,
    });
    return client.get<PageResult<ArtifactEntry>>(`/artifacts/list?${search}`);
  },

  /**
   * 读文本文件。后端只按 UTF-8 解码：二进制文件会被解成乱码，
   * 所以调用方要先按扩展名挡住二进制（见 FileViewer 的 classify）。
   */
  file(input: ArtifactFileQuery): Promise<ArtifactFile> {
    const search = queryString({
      stage: input.stage,
      agentId: input.agentId,
      path: input.path,
    });
    return client.get<ArtifactFile>(`/artifacts/file?${search}`);
  },

  /**
   * 原始下载地址，直接给 `<a href>` / `<img src>` 用。
   *
   * 下载端点不受文本大小上限约束，二进制文件与超过 2 MiB 的文本都走它。
   * 与 REST 同一个 base，开发态经 vite 的 `/api` 代理。
   */
  downloadUrl(input: ArtifactFileQuery): string {
    const search = queryString({
      stage: input.stage,
      agentId: input.agentId,
      path: input.path,
    });
    return `${BASE_URL}/artifacts/download?${search}`;
  },
};
