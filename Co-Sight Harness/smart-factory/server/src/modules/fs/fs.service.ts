import type { Dirent, Stats } from 'node:fs';
import { readFileSync, statSync } from 'node:fs';
import { readdir, stat } from 'node:fs/promises';
import { basename, dirname, join } from 'node:path';
import { config } from '../../config/index.js';
import {
  BadRequestError,
  NotFoundError,
  PayloadTooLargeError,
  UnsupportedMediaTypeError,
} from '../../shared/errors.js';
import { localRoots, resolveLocalTarget, type LocalRoot } from '../../shared/workspace/local-path.js';

/**
 * 本机文件浏览：给发送框的「添加文件」提供**真实路径**，给对话里的文件引用提供只读预览。
 *
 * 端侧形态下前端与 Claude Code 同机，没有上传 —— 选中的文件就是一个绝对路径，
 * 之后进引擎 prompt 由引擎自己读。所以这里只读，没有任何写入口。
 *
 * 路径校验在 `shared/workspace/local-path.ts`（发送时校验附件用的是同一份），
 * 本文件只管「把目录摆成前端的形状」与「把文件读出来」。浏览范围不设限：整机任意绝对路径都能列，
 * `roots` 只是快捷入口。
 *
 * `read` / `raw` 是对话里文件引用（行内代码、Markdown 链接、工具条目、附件 chip）的落点。
 * 它们和 `/artifacts/*` 的分界见 `fs.routes.ts` 文件头：artifacts 绑 stage + agentId，
 * fs 按绝对路径看整机；对话里经常出现 stage 之外的路径（如 node_modules 里的 README）。
 */

/** 目录项。`path` 是绝对路径，前端选中后原样回传。 */
export interface FsEntry {
  name: string;
  path: string;
  type: 'dir' | 'file';
  size: number;
  mtime: string;
}

export interface FsListing {
  /** 当前目录的真实绝对路径（已解 symlink） */
  path: string;
  /** 上一级；已在文件系统根上时为 null（前端据此禁用「上一级」） */
  parent: string | null;
  items: FsEntry[];
  /** 目录条目超过上限时为 true：`items` 只是前面一部分（搜索也只在其中找） */
  truncated: boolean;
}

/**
 * 一次最多返回多少条。
 *
 * 主目录里动辄几万个条目（node_modules 这类更夸张）：全量回给前端既费带宽也费渲染，
 * 先把上限卡在服务端。超出部分不 stat —— 大目录的成本主要就花在逐项 stat 上。
 */
const LIST_LIMIT = 2000;

/** 取不到时间时不编一个假值，给空串让前端不显示 */
const UNKNOWN_TIME = '';

/** 二进制判定只看开头这么多字节：扩展名挡不住的（无后缀的可执行文件等）靠它兜底 */
const BINARY_PROBE_BYTES = 8 * 1024;

/** 预览端点的文本响应：与 `/artifacts/file` 同形，多一个绝对路径给前端拼相对链接 */
export interface FsFile {
  /** 真实绝对路径（已解 symlink） */
  path: string;
  name: string;
  size: number;
  mtime: string;
  content: string;
}

async function safeStat(path: string): Promise<Stats | null> {
  try {
    return await stat(path);
  } catch {
    return null;
  }
}

/**
 * 目录项 → 展示形状。
 *
 * 目录类型**跟随 symlink**：把 `~/project` 做成软链是很常见的用法，按链接自身判成文件
 * 会让整个工程点不进去。真的越界也无所谓 —— 进目录时会再走一次 realpath 校验。
 */
async function toEntry(dir: string, dirent: Dirent): Promise<FsEntry> {
  const path = join(dir, dirent.name);
  const stats = await safeStat(path);
  const type = stats?.isDirectory() ? 'dir' : 'file';
  return {
    name: dirent.name,
    path,
    type,
    size: type === 'dir' ? 0 : (stats?.size ?? 0),
    mtime: stats?.mtime.toISOString() ?? UNKNOWN_TIME,
  };
}

/** 「上一级」一直给到文件系统根：浏览不设范围，只有到顶（dirname 等于自身）才没有上一级。 */
function parentOf(dir: string): string | null {
  const parent = dirname(dir);
  return parent === dir ? null : parent;
}

export const fsService = {
  /** 可浏览的根：主目录 + 框架登记的工作区（当前生效的带 `active`）。 */
  async roots(): Promise<{ items: LocalRoot[] }> {
    return { items: await localRoots() };
  },

  /**
   * 列一层目录。
   *
   * 只列一层、不递归：真实工程里 `node_modules` 这类目录递归一遍代价太大，
   * 前端展开时再请求（与 `artifacts/list` 同口径）。
   */
  async list(input: { path?: unknown }): Promise<FsListing> {
    const roots = await localRoots();
    const requested = input.path === undefined || input.path === '' ? (roots[0]?.path ?? '') : input.path;
    if (requested === '') throw new BadRequestError('path 必填：没有任何可访问的目录');

    const dir = resolveLocalTarget(requested, 'dir');

    let dirents: Dirent[];
    try {
      dirents = await readdir(dir, { withFileTypes: true });
    } catch {
      throw new NotFoundError(`目录 ${String(requested)}`);
    }

    /*
     * 先按 dirent 自带的类型排一次（不 stat）：上限之外的部分直接丢掉，
     * 不让一次目录浏览把几千个 stat 甩给线程池。symlink 的真实类型要 stat 后才知道，
     * 所以下面拿到结果后再按最终类型排一次。
     */
    const hinted = dirents
      .map((dirent) => ({ dirent, isDir: dirent.isDirectory() }))
      .sort((a, b) => {
        if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
        return a.dirent.name.localeCompare(b.dirent.name);
      });
    const kept = hinted.slice(0, LIST_LIMIT).map((item) => item.dirent);

    // 分批 stat：一次 32 个，既不让线程池排队太长，也不至于串行等上千次 IO
    const items: FsEntry[] = [];
    const BATCH = 32;
    for (let index = 0; index < kept.length; index += BATCH) {
      const batch = kept.slice(index, index + BATCH);
      items.push(...(await Promise.all(batch.map((dirent) => toEntry(dir, dirent)))));
    }
    items.sort((a, b) => {
      if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
      return a.name.localeCompare(b.name);
    });

    return {
      path: dir,
      parent: parentOf(dir),
      items,
      truncated: hinted.length > LIST_LIMIT,
    };
  },

  /**
   * 读一个文本文件给预览面板。
   *
   * 口径与 `artifactService.file` 一致：UTF-8、去 BOM、超过 `artifactMaxFileBytes` 给 413。
   * 额外做一次二进制探测（前 8 KiB 有 NUL 就 415）：前端会按扩展名先挡一层，
   * 这里兜的是「后缀写着 .md、内容其实是二进制」这类。
   */
  async read(input: { path: unknown }): Promise<FsFile> {
    const real = resolveLocalTarget(input.path, 'file');
    let stats;
    try {
      stats = statSync(real);
    } catch {
      // 校验与读取之间被删掉：按 404 回，不让 ENOENT 变成 500
      throw new NotFoundError(`路径 ${real}`);
    }
    if (stats.size > config.artifactMaxFileBytes) {
      throw new PayloadTooLargeError(
        `文件 ${real} 超过大小上限 ${config.artifactMaxFileBytes} 字节`,
      );
    }

    const buffer = readFileSync(real);
    if (buffer.subarray(0, BINARY_PROBE_BYTES).includes(0)) {
      throw new UnsupportedMediaTypeError(`文件 ${real} 是二进制，不能按文本读取`);
    }

    const text = buffer.toString('utf8');
    return {
      path: real,
      name: basename(real),
      size: stats.size,
      mtime: stats.mtime.toISOString(),
      // 与 artifactService.file 同口径去掉 BOM；用码点判断比在源码里写一个不可见字符稳
      content: text.charCodeAt(0) === 0xfeff ? text.slice(1) : text,
    };
  },

  /**
   * 原始字节流（`/fs/raw/*`）：图片、HTML、PDF 等不适合作文本读的文件。
   *
   * 不套 `artifactMaxFileBytes`：文本上限是给「读进内存再 JSON」定的，
   * raw 走 `res.sendFile` 流式发送，大文件由它自己处理。
   */
  async raw(input: { path: unknown }): Promise<string> {
    return resolveLocalTarget(input.path, 'file');
  },
};
