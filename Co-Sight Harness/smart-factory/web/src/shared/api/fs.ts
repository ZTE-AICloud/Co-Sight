/**
 * 本机文件浏览（发送框「添加文件」的数据源）。
 *
 * 端侧形态：前端与 Claude Code 同机，**没有上传** —— 用户选中的就是一个绝对路径，
 * 发送时随消息带去给引擎自己读。所以这里只有只读端点（列目录 / 读文本 / 原始流），
 * 没有写入口。
 *
 * 浏览范围不设限：整机任意绝对路径都能列。`roots` 只是快捷入口（主目录 + 框架登记的工作区），
 * 不是边界；路径是否合法由服务端判定，前端不自己拼路径、也不自己判断越界：
 * `400` / `404` 直接照后端原话提示。
 */

import { API_BASE_URL, createApiClient } from './client';

/** 一个快捷入口（不是可浏览范围的边界）。`workspaceId` 为 null 表示主目录 */
export interface FsRoot {
  label: string;
  /** 真实绝对路径（服务端已解掉 symlink） */
  path: string;
  workspaceId: string | null;
  /** 是否框架当前生效的工作区 */
  active: boolean;
}

/** 目录项。`path` 是绝对路径，选中后原样回传 */
export interface FsEntry {
  name: string;
  path: string;
  type: 'dir' | 'file';
  size: number;
  mtime: string;
}

export interface FsListing {
  path: string;
  /** 上一级；已在文件系统根上时为 null */
  parent: string | null;
  items: FsEntry[];
  /** 目录条目超过服务端上限：`items` 只是前面一部分，当前目录搜索也只在这部分里找 */
  truncated: boolean;
}

/** `/fs/read` 读回来的文本文件（形状与 `artifacts/file` 对齐，多一个绝对路径） */
export interface FsFile {
  /** 真实绝对路径（服务端已解 symlink） */
  path: string;
  name: string;
  size: number;
  mtime: string;
  content: string;
}

const BASE_URL = import.meta.env.VITE_FS_API_BASE_URL ?? `${API_BASE_URL}/smart-factory/v1`;

const client = createApiClient(BASE_URL);

export const fsApi = {
  /** 快捷入口：主目录在前，工作区在后 */
  roots(): Promise<{ items: FsRoot[] }> {
    return client.get<{ items: FsRoot[] }>('/fs/roots');
  },

  /**
   * 列一层目录。不传 `path` 时由服务端退回主目录。
   *
   * 目录项由服务端排好序（目录在前、名称升序），前端不重排。
   */
  list(input: { path?: string } = {}): Promise<FsListing> {
    const search = input.path === undefined ? '' : `?path=${encodeURIComponent(input.path)}`;
    return client.get<FsListing>(`/fs/list${search}`);
  },

  /**
   * 读一个文本文件给预览面板。
   *
   * `415` = 二进制、`413` = 超过文本上限、`404` = 不存在；这三种都由调用方按
   * 「给下载出口」处理，不要在这里吞掉。
   */
  read(path: string): Promise<FsFile> {
    return client.get<FsFile>(`/fs/read?path=${encodeURIComponent(path)}`);
  },

  /**
   * 原始字节流的地址，直接给 `<img src>` / `<iframe src>`。
   *
   * 路径走**分段**而不是 `?path=`：HTML 里的 `./style.css` 只有这样才会落到
   * `/fs/raw/.../style.css`，否则会被解析成应用根下的路径。
   */
  rawUrl(path: string): string {
    // Windows 与 POSIX 两种分隔符都要认：端侧也可能跑在 Windows 上，
    // 只按 `/` 分段会把 `C:\a\b` 当成一个整段（后端解出来的路径是断的）。
    const segments = path.split(/[\\/]+/u).map(encodeURIComponent).join('/');
    // POSIX 绝对路径自带开头的 `/`；盘符路径（`C:/...`）与 `~/...` 没有，补一个分隔符。
    // `~` 的展开在后端做；盘符不能补前导 `/`（后端 raw 路由同样不为盘符补）。
    return `${BASE_URL}/fs/raw${segments.startsWith('/') ? '' : '/'}${segments}`;
  },
};
