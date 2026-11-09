/**
 * ustar 归档读写器（自带 gzip 包装）。
 *
 * 为什么自己写而不是调系统 `tar`：
 *  1. 打包脚本要跨平台可跑，而 Windows 10 起才自带 bsdtar、且参数不完全兼容；
 *  2. ustar 是定长 512 字节头 + 512 对齐数据块的字节格式，规则小且确定，
 *     自己实现后可以**在同一个进程里把写出来的东西读回来校验**——
 *     这是"看起来正常的坏包"唯一的防线；
 *  3. 可复现：条目顺序、mtime 全部固定，同一份输入产出同一串字节。
 *
 * 覆盖范围只到本仓库需要的那部分：普通文件、目录、符号链接，以及超长路径的
 * GNU `@LongLink` 兜底。不实现硬链接、稀疏文件、PAX 扩展头。
 *
 * 头布局（POSIX.1-1988）：
 *   0 name[100] 100 mode[8] 108 uid[8] 116 gid[8] 124 size[12] 136 mtime[12]
 *   148 chksum[8] 156 typeflag[1] 157 linkname[100] 257 magic[6] 263 version[2]
 *   265 uname[32] 297 gname[32] 329 devmajor[8] 337 devminor[8] 345 prefix[155]
 *   500 padding[12]
 */

import fs from 'node:fs';
import zlib from 'node:zlib';

const BLOCK_SIZE = 512;
const NAME_SIZE = 100;
const PREFIX_SIZE = 155;
/** ustar 的 name+prefix 上限：155 + 1 + 100。超出就必须用 GNU 长名条目。 */
const USTAR_PATH_LIMIT = PREFIX_SIZE + 1 + NAME_SIZE;
/** 12 字节八进制字段的可表示上限（11 位八进制）。 */
const MAX_OCTAL_12 = 8 ** 11 - 1;

const TYPE_FILE = '0';
const TYPE_SYMLINK = '2';
const TYPE_DIR = '5';
/** GNU 扩展：本条目内容是"下一个条目的名字"（'K' 则是它的链接目标）。 */
const TYPE_LONGNAME = 'L';
const TYPE_LONGLINK = 'K';
const GNU_LONGNAME_HINT = '././@LongLink';

/**
 * 写八进制数字段：length-1 位数字补零，末尾留一个 NUL。
 * 这是 POSIX 规定的写法；直接写满 length 位数字会让 `tar` 报 "checksum error"。
 */
function writeOctal(buffer, offset, length, value) {
  const text = value.toString(8).padStart(length - 1, '0');
  if (text.length > length - 1) {
    throw new Error(`字段放不下：值 ${value} 需要 ${text.length} 位八进制，只有 ${length - 1} 位`);
  }
  buffer.write(text, offset, length - 1, 'ascii');
}

function writeString(buffer, offset, length, value) {
  const bytes = Buffer.from(value, 'utf8');
  if (bytes.length > length) {
    throw new Error(`字段放不下：${value} 需要 ${bytes.length} 字节，只有 ${length} 字节`);
  }
  bytes.copy(buffer, offset);
}

/**
 * 按字节截断，且不退到多字节字符的中间。
 *
 * 归档头里出现超长值时，读取方会用 GNU 占位条目里的值整体替换掉头里的字段，
 * 所以头里放什么其实没人看——但**必须放得下**，否则写头这一步直接抛错。
 */
function truncateUtf8(value, maxBytes) {
  const bytes = Buffer.from(value, 'utf8');
  if (bytes.length <= maxBytes) {
    return value;
  }
  let end = maxBytes;
  // UTF-8 的续字节形如 10xxxxxx；命中说明正好切在字符中间，往前退到字符边界。
  while (end > 0 && (bytes[end] & 0xc0) === 0x80) {
    end -= 1;
  }
  return bytes.subarray(0, end).toString('utf8');
}

/**
 * 把路径拆成 ustar 的 name/prefix 两段。
 * 从最靠前的 '/' 开始试：只要后半段放得进 name、前半段放得进 prefix 就采用。
 * 返回 null 表示 ustar 装不下，调用方要退回 GNU 长名。
 */
function splitUstarPath(archivePath) {
  const total = Buffer.byteLength(archivePath, 'utf8');
  if (total <= NAME_SIZE) {
    return { name: archivePath, prefix: '' };
  }
  if (total > USTAR_PATH_LIMIT) {
    return null;
  }
  // 直接算切点容易在 UTF-8 多字节字符中间切开，这里按 '/' 位置逐个尝试。
  for (let index = archivePath.indexOf('/'); index !== -1; index = archivePath.indexOf('/', index + 1)) {
    const prefix = archivePath.slice(0, index);
    const name = archivePath.slice(index + 1);
    if (Buffer.byteLength(prefix, 'utf8') <= PREFIX_SIZE && Buffer.byteLength(name, 'utf8') <= NAME_SIZE) {
      return { name, prefix };
    }
  }
  return null;
}

/** 目录名在归档里以 '/' 结尾，否则部分实现会把目录当成空文件。 */
function archivePathOf(entry) {
  return entry.kind === 'dir' ? `${entry.path}/` : entry.path;
}

/**
 * @param {{name: string, prefix: string}} split 由调用方算好。装不下时调用方要
 *   先写 GNU 长名占位条目，并在这里传入一个"仅占位、会被读取方丢弃"的截断值。
 */
function buildHeader(entry, size, mtime, split) {
  const header = Buffer.alloc(BLOCK_SIZE);
  const isDir = entry.kind === 'dir';
  const isLink = entry.kind === 'symlink';

  const typeflag = isDir ? TYPE_DIR : isLink ? TYPE_SYMLINK : TYPE_FILE;

  writeString(header, 0, NAME_SIZE, split.name);
  // 只保留所有者读写位，权限的其余部分由 mode 的 group/other 位表达。
  writeOctal(header, 100, 8, entry.mode & 0o7777);
  writeOctal(header, 108, 8, 0); // uid：归档不携带所有者身份
  writeOctal(header, 116, 8, 0); // gid
  writeOctal(header, 124, 12, size);
  writeOctal(header, 136, 12, mtime);
  header.write('        ', 148, 8, 'ascii'); // 校验和计算时该字段视作 8 个空格
  header.write(typeflag, 156, 1, 'ascii');
  if (isLink) {
    // linkname 没有 prefix 那样的兜底字段，只能截断；真实值由前面的 'K' 占位条目携带。
    writeString(header, 157, NAME_SIZE, truncateUtf8(entry.linkTarget, NAME_SIZE));
  }
  writeString(header, 257, 6, 'ustar\0');
  writeString(header, 263, 2, '00');
  writeString(header, 265, 32, 'root');
  writeString(header, 297, 32, 'root');
  writeString(header, 345, PREFIX_SIZE, split.prefix);

  let sum = 0;
  for (const byte of header) {
    sum += byte;
  }
  // 校验和固定写成 6 位八进制 + NUL + 空格，这是所有实现里的通用形式。
  header.write(`${sum.toString(8).padStart(6, '0')}\0 `, 148, 8, 'ascii');
  return header;
}

/**
 * GNU 长字段占位头。
 *
 * typeflag 'L' 表示"下一个条目的名字"，'K' 表示"下一个条目的链接目标"。
 * 两者都要有：linkname 字段同样只有 100 字节且**没有 prefix 兜底**，
 * 而 pnpm 的符号链接目标会长到 100 字节以上（`.pnpm/../../../@scope+pkg@1.2.3/...`）。
 */
function buildLongFieldHeader(typeflag, value, mtime) {
  const header = Buffer.alloc(BLOCK_SIZE);
  writeString(header, 0, NAME_SIZE, GNU_LONGNAME_HINT);
  writeOctal(header, 100, 8, 0o644);
  writeOctal(header, 108, 8, 0);
  writeOctal(header, 116, 8, 0);
  writeOctal(header, 124, 12, Buffer.byteLength(value, 'utf8') + 1);
  writeOctal(header, 136, 12, mtime);
  header.write('        ', 148, 8, 'ascii');
  header.write(typeflag, 156, 1, 'ascii');
  writeString(header, 257, 6, 'ustar\0');
  writeString(header, 263, 2, '00');
  let sum = 0;
  for (const byte of header) {
    sum += byte;
  }
  header.write(`${sum.toString(8).padStart(6, '0')}\0 `, 148, 8, 'ascii');
  return header;
}

/** 数据块之后的补齐；size 恰好 512 对齐时不需要补任何字节。 */
function paddingFor(size) {
  const remainder = size % BLOCK_SIZE;
  return remainder === 0 ? 0 : BLOCK_SIZE - remainder;
}

/**
 * 把一组条目写成 tar（可选 gzip）。
 *
 * @param {Array<{path: string, kind: 'file'|'dir'|'symlink', mode: number, linkTarget?: string, read?: () => Buffer, size?: number}>} entries
 * @param {{mtime?: number}} [options]
 * @returns {Buffer}
 */
export function writeTar(entries, options = {}) {
  // mtime 默认取 0：归档只做传输，携带打包时刻会让"同样输入产出同样字节"失效。
  const mtime = options.mtime ?? 0;
  const chunks = [];

  for (const entry of entries) {
    let size = 0;
    let data = null;

    if (entry.kind === 'file') {
      data = entry.read();
      size = data.length;
      if (size > MAX_OCTAL_12) {
        throw new Error(`${entry.path} 超过 ustar 单文件上限（${MAX_OCTAL_12} 字节）`);
      }
    }

    const archivePath = archivePathOf(entry);
    const split = splitUstarPath(archivePath);
    const longFields = [];
    if (split === null) {
      longFields.push({ typeflag: TYPE_LONGNAME, value: archivePath });
    }
    // 链接目标放不进 100 字节的 linkname 字段时同样要占位（头里原有的内容会被读取方丢弃）。
    if (entry.kind === 'symlink' && Buffer.byteLength(entry.linkTarget, 'utf8') > NAME_SIZE) {
      longFields.push({ typeflag: TYPE_LONGLINK, value: entry.linkTarget });
    }

    for (const field of longFields) {
      chunks.push(buildLongFieldHeader(field.typeflag, field.value, mtime));
      const valueBytes = Buffer.byteLength(field.value, 'utf8') + 1;
      chunks.push(Buffer.from(`${field.value}\0`, 'utf8'));
      const pad = paddingFor(valueBytes);
      if (pad > 0) {
        chunks.push(Buffer.alloc(pad));
      }
    }

    chunks.push(buildHeader(entry, size, mtime, split ?? { name: truncateUtf8(archivePath, NAME_SIZE), prefix: '' }));
    if (data !== null) {
      chunks.push(data);
      const pad = paddingFor(size);
      if (pad > 0) {
        chunks.push(Buffer.alloc(pad));
      }
    }
  }

  // 归档尾：两个全零块。
  chunks.push(Buffer.alloc(BLOCK_SIZE * 2));
  return Buffer.concat(chunks);
}

export function gzip(archive, level = 6) {
  return zlib.gzipSync(archive, { level });
}

/**
 * 读回 tar。同时接受裸 tar 与 gzip 过的 tar——校验产物时不必先判断格式。
 * 只解析出校验需要的字段，不还原文件内容。
 *
 * @returns {Array<{path: string, kind: 'file'|'dir'|'symlink'|'other', size: number, mode: number, linkTarget: string}>}
 */
export function readTar(input) {
  // gzip 的魔数是 1f 8b；先解压再按裸 tar 解析。
  const buffer = input[0] === 0x1f && input[1] === 0x8b ? zlib.gunzipSync(input) : input;
  const entries = [];
  let offset = 0;
  let pendingLongName = null;
  let pendingLongLink = null;

  while (offset + BLOCK_SIZE <= buffer.length) {
    const header = buffer.subarray(offset, offset + BLOCK_SIZE);
    // 全零块代表归档结束。
    if (header.every((byte) => byte === 0)) {
      break;
    }

    const rawName = header.toString('utf8', 0, NAME_SIZE).replace(/\0.*$/, '');
    const prefix = header.toString('utf8', 345, 345 + PREFIX_SIZE).replace(/\0.*$/, '');
    const size = Number.parseInt(header.toString('ascii', 124, 136).replace(/\0.*$/, '').trim() || '0', 8);
    const mode = Number.parseInt(header.toString('ascii', 100, 108).replace(/\0.*$/, '').trim() || '0', 8);
    const typeflag = header.toString('ascii', 156, 157);
    const linkTarget = header.toString('utf8', 157, 157 + NAME_SIZE).replace(/\0.*$/, '');

    offset += BLOCK_SIZE;
    const dataStart = offset;
    offset += size + paddingFor(size);

    // 两种占位条目都不产生归档条目，只影响紧随其后的那一个。
    if (typeflag === TYPE_LONGNAME || typeflag === TYPE_LONGLINK) {
      const value = buffer.toString('utf8', dataStart, dataStart + size).replace(/\0.*$/, '');
      if (typeflag === TYPE_LONGNAME) {
        pendingLongName = value;
      } else {
        pendingLongLink = value;
      }
      continue;
    }

    const rawPath = pendingLongName ?? (prefix === '' ? rawName : `${prefix}/${rawName}`);
    const resolvedLink = pendingLongLink ?? linkTarget;
    pendingLongName = null;
    pendingLongLink = null;

    const kind =
      typeflag === TYPE_DIR ? 'dir' : typeflag === TYPE_SYMLINK ? 'symlink' : typeflag === TYPE_FILE ? 'file' : 'other';
    // 写入时给目录名加了结尾 '/'，读回来去掉——与 zip 读取器保持同一种形态，
    // 否则同一个目录在两种归档里的路径不一样，跨格式比对就没有意义了。
    const path = kind === 'dir' && rawPath.endsWith('/') ? rawPath.slice(0, -1) : rawPath;

    entries.push({ path, kind, size, mode, linkTarget: resolvedLink });
  }

  return entries;
}

/** 便捷入口：按扩展名决定是否 gzip，直接落盘。 */
export function writeTarFile(entries, outPath, options = {}) {
  const archive = writeTar(entries, options);
  const payload = outPath.endsWith('.gz') ? gzip(archive, options.level) : archive;
  fs.writeFileSync(outPath, payload);
  return payload.length;
}
