import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync } from 'node:fs';
import { rename } from 'node:fs/promises';
import { extname, isAbsolute, join, relative, resolve } from 'node:path';
import { config } from '../../config/index.js';
import { BadRequestError, NotFoundError } from '../../shared/errors.js';

/**
 * 上传文件的存储名：`fil_<uuid>` + 可选消毒后的扩展名。
 *
 * 存储名即对外 id（4.08 文件 §3）：id 进路径、Content-Type 按扩展名映射，都不依赖数据库。
 * 形态校验是读取的唯一安全边界，边界收在 FILE_ID_PATTERN —— 它放行的字符集不可能拼出路径穿越。
 */
const FILE_ID_PATTERN = /^fil_[0-9a-f-]{36}(\.[a-z0-9]{1,10})?$/;

/** 扩展名消毒：去点、小写、只留字母数字、最长 10 段；洗不出合法形态就不带扩展名。 */
function sanitizeExtension(originalName: string): string {
  const raw = extname(originalName).replace(/^\./, '').toLowerCase();
  const cleaned = raw.replace(/[^a-z0-9]/g, '').slice(0, 10);
  return cleaned === '' ? '' : `.${cleaned}`;
}

/** 常见扩展名 → Content-Type；不在表内一律 application/octet-stream。 */
const CONTENT_TYPES: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.bmp': 'image/bmp',
  '.avif': 'image/avif',
  '.pdf': 'application/pdf',
  '.txt': 'text/plain; charset=utf-8',
  '.json': 'application/json',
  '.mp4': 'video/mp4',
  '.mp3': 'audio/mpeg',
  '.zip': 'application/zip',
};

/** 上传根目录的约定位置：`{home}/files/`。只给路径，不建目录。 */
export function filesRoot(): string {
  return join(config.home, 'files');
}

export interface UploadedFile {
  /** 存储名（含扩展名），同时是对外 id */
  name: string;
  /** 前端可直接使用的访问 URL（相对路径，经 vite 代理同源） */
  url: string;
  /** 字节数 */
  size: number;
}

/** 保存一个已由 multer 落盘的临时文件：改名挪进 `files/`，返回对外形状。 */
export async function saveUploaded(tempPath: string, originalName: string, size: number): Promise<UploadedFile> {
  const name = `fil_${randomUUID()}${sanitizeExtension(originalName)}`;
  mkdirSync(filesRoot(), { recursive: true });
  await rename(tempPath, join(filesRoot(), name));
  return { name, url: `${config.apiPrefix}/files/${name}`, size };
}

export interface StoredFile {
  absolutePath: string;
  contentType: string;
}

/** 存储名 → 磁盘绝对路径 + Content-Type；形态非法 400、合法但不存在 404（4.02 通用规范 §11 分界口径）。 */
export function readStored(name: string): StoredFile {
  if (typeof name !== 'string' || !FILE_ID_PATTERN.test(name)) {
    throw new BadRequestError(`文件存储名形态非法：${JSON.stringify(name)}`);
  }
  const root = resolve(filesRoot());
  const absolutePath = resolve(root, name);
  /*
   * 双保险：形态校验已排除分隔符，这里再挡一次 resolve 后逃逸出根目录的形态。
   *
   * 必须用 `relative()` 判断，不能拼 `root + '/'` —— Windows 上 `resolve()` 给的是反斜杠，
   * 拼正斜杠后永远不会相等，合法文件名（包括所有上传的图标）都会被判成非法。
   */
  const rel = relative(root, absolutePath);
  if (rel === '' || rel.startsWith('..') || isAbsolute(rel)) {
    throw new BadRequestError(`文件存储名形态非法：${JSON.stringify(name)}`);
  }
  if (!existsSync(absolutePath)) {
    throw new NotFoundError(`文件 ${name}`, 'error.not_found.file', { name });
  }
  return { absolutePath, contentType: CONTENT_TYPES[extname(name)] ?? 'application/octet-stream' };
}

/** 对外服务入口；模块内聚导出形状与 agent/artifact 模块的 `xxxService` 一致。 */
export const filesService = { saveUploaded, readStored };
