/**
 * ZIP 归档读写器（deflate）。
 *
 * 为什么自己写：与 tar 同理——不依赖系统 `zip` 命令，且能在同进程读回校验。
 * ZIP 的字节格式比 tar 啰嗦（本地头 + 中央目录 + 目录尾三处），但并不复杂。
 *
 * 三处结构：
 *   本地文件头 0x04034b50 + 文件名 + 数据
 *   中央目录项 0x02014b50 + 文件名   （保存权限位与本地头偏移）
 *   目录结束   0x06054b50            （指向中央目录）
 *
 * 两个刻意的取舍：
 *  1. **不用数据描述符**（flag bit 3）。描述符是为了流式写入时把尺寸后置，
 *     代价是尺寸字段先写 0、读取方要回退解析。这里每个文件都先在内存里压缩，
 *     尺寸已知，写死更简单也更难写错。
 *  2. **符号链接照原样表达**（S_IFLNK + 内容为链接目标）。pnpm 的 node_modules
 *     里 230 个条目是符号链接，若不表达，ZIP 产物在解压后根本跑不起来。
 *     注意：Info-ZIP unzip 会还原符号链接，但 Windows 自带解压器不会——
 *     这一点写进了产物 README。
 *
 * 不实现 ZIP64：本产物的单文件与总量都远低于 4 GiB 边界，但写入口会显式
 * 断言这一点，以免将来产物变大后静默产出一个坏包。
 */

import fs from 'node:fs';
import zlib from 'node:zlib';

const LOCAL_HEADER_SIG = 0x04034b50;
const CENTRAL_HEADER_SIG = 0x02014b50;
const EOCD_SIG = 0x06054b50;

const LOCAL_HEADER_SIZE = 30;
const CENTRAL_HEADER_SIZE = 46;
const EOCD_SIZE = 22;

const METHOD_STORE = 0;
const METHOD_DEFLATE = 8;
/** 位 11：文件名按 UTF-8 解释。 */
const FLAG_UTF8 = 0x0800;
/** 高字节 3 = UNIX，低字节 = 规格版本 3.0。解压方据此解读外部属性里的权限位。 */
const VERSION_MADE_BY_UNIX = 0x031e;
const VERSION_NEEDED = 20;

const S_IFREG = 0o100000;
const S_IFDIR = 0o040000;
const S_IFLNK = 0o120000;

const ZIP_SIZE_LIMIT = 0xffffffff;
const ZIP_ENTRY_LIMIT = 0xffff;

/**
 * DOS 日期时间字段。固定写成 1980-01-01 00:00:00：
 * ZIP 的该字段没有"无时间"的表示，用固定值换取可复现的产物字节。
 */
const DOS_DATE = 0x0021;
const DOS_TIME = 0;

function crc32(buffer) {
  // Node 22.2+ 提供的 zlib.crc32；engines 已要求 ^22.19 || >=24，无需自行实现查表。
  return zlib.crc32(buffer) >>> 0;
}

function dosAttributesFor(kind) {
  // MS-DOS 属性字节：目录置目录位。其余位（归档/只读）对本产物无意义。
  return kind === 'dir' ? 0x10 : 0x00;
}

function externalAttributesFor(entry) {
  const typeBits = entry.kind === 'dir' ? S_IFDIR : entry.kind === 'symlink' ? S_IFLNK : S_IFREG;
  return (((typeBits | (entry.mode & 0o7777)) << 16) | dosAttributesFor(entry.kind)) >>> 0;
}

/**
 * @param {Array<{path: string, kind: 'file'|'dir'|'symlink', mode: number, linkTarget?: string, read?: () => Buffer}>} entries
 * @returns {Buffer}
 */
export function writeZip(entries, options = {}) {
  const level = options.level ?? 6;
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;

  if (entries.length > ZIP_ENTRY_LIMIT) {
    throw new Error(`ZIP 条目数 ${entries.length} 超过 ${ZIP_ENTRY_LIMIT}，需要 ZIP64，本写入器未实现`);
  }

  for (const entry of entries) {
    const isDir = entry.kind === 'dir';
    // 目录名以 '/' 结尾是 ZIP 的惯例，Windows 资源管理器据此识别目录。
    const name = isDir ? `${entry.path}/` : entry.path;
    const nameBytes = Buffer.from(name, 'utf8');

    // 文件内容只读一次：大产物里重复读盘会让打包时间成倍增长。
    let raw = null;
    let method;
    let payload;
    if (isDir) {
      method = METHOD_STORE;
      payload = Buffer.alloc(0);
    } else if (entry.kind === 'symlink') {
      // 链接目标直接当内容存：这是 ZIP 里表达符号链接的唯一方式。
      method = METHOD_STORE;
      payload = Buffer.from(entry.linkTarget ?? '', 'utf8');
    } else {
      raw = entry.read();
      // 压缩后反而变大时不值得压缩（少见，主要是已压缩的二进制与极短文件）。
      const deflated = zlib.deflateRawSync(raw, { level });
      method = deflated.length < raw.length ? METHOD_DEFLATE : METHOD_STORE;
      payload = method === METHOD_DEFLATE ? deflated : raw;
    }

    if (payload.length > ZIP_SIZE_LIMIT) {
      throw new Error(`${entry.path} 压缩后超过 4 GiB，需要 ZIP64，本写入器未实现`);
    }

    const size = raw === null ? payload.length : raw.length;
    const checksum = crc32(raw ?? payload);

    const local = Buffer.alloc(LOCAL_HEADER_SIZE);
    local.writeUInt32LE(LOCAL_HEADER_SIG, 0);
    local.writeUInt16LE(VERSION_NEEDED, 4);
    local.writeUInt16LE(FLAG_UTF8, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt16LE(DOS_TIME, 10);
    local.writeUInt16LE(DOS_DATE, 12);
    local.writeUInt32LE(checksum, 14);
    local.writeUInt32LE(payload.length, 18);
    local.writeUInt32LE(size, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    local.writeUInt16LE(0, 28); // 无扩展字段

    localChunks.push(local, nameBytes, payload);

    const central = Buffer.alloc(CENTRAL_HEADER_SIZE);
    central.writeUInt32LE(CENTRAL_HEADER_SIG, 0);
    central.writeUInt16LE(VERSION_MADE_BY_UNIX, 4);
    central.writeUInt16LE(VERSION_NEEDED, 6);
    central.writeUInt16LE(FLAG_UTF8, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt16LE(DOS_TIME, 12);
    central.writeUInt16LE(DOS_DATE, 14);
    central.writeUInt32LE(checksum, 16);
    central.writeUInt32LE(payload.length, 20);
    central.writeUInt32LE(size, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt16LE(0, 30); // 无扩展字段
    central.writeUInt16LE(0, 32); // 无注释
    central.writeUInt16LE(0, 34); // 起始磁盘号
    central.writeUInt16LE(0, 36); // 内部属性
    central.writeUInt32LE(externalAttributesFor(entry), 38);
    central.writeUInt32LE(offset, 42);

    centralChunks.push(central, nameBytes);

    offset += LOCAL_HEADER_SIZE + nameBytes.length + payload.length;
    if (offset > ZIP_SIZE_LIMIT) {
      throw new Error('ZIP 总量超过 4 GiB，需要 ZIP64，本写入器未实现');
    }
  }

  const centralDirectory = Buffer.concat(centralChunks);
  const eocd = Buffer.alloc(EOCD_SIZE);
  eocd.writeUInt32LE(EOCD_SIG, 0);
  eocd.writeUInt16LE(0, 4); // 本磁盘号
  eocd.writeUInt16LE(0, 6); // 中央目录起始磁盘号
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(centralDirectory.length, 12);
  eocd.writeUInt32LE(offset, 16);
  eocd.writeUInt16LE(0, 20); // 无注释

  return Buffer.concat([...localChunks, centralDirectory, eocd]);
}

/**
 * 读回 ZIP：从尾部找 EOCD，再沿中央目录逐项解析。
 * 只取校验需要的字段，不还原文件内容。
 */
export function readZip(buffer) {
  let eocdOffset = -1;
  // 注释最长 65535 字节，因此 EOCD 只可能落在末尾这一段内。
  for (let index = buffer.length - EOCD_SIZE; index >= Math.max(0, buffer.length - EOCD_SIZE - 0xffff); index -= 1) {
    if (buffer.readUInt32LE(index) === EOCD_SIG) {
      eocdOffset = index;
      break;
    }
  }
  if (eocdOffset === -1) {
    throw new Error('ZIP 里找不到中央目录结束记录，文件已损坏');
  }

  const count = buffer.readUInt16LE(eocdOffset + 10);
  let cursor = buffer.readUInt32LE(eocdOffset + 16);
  const entries = [];

  for (let index = 0; index < count; index += 1) {
    if (buffer.readUInt32LE(cursor) !== CENTRAL_HEADER_SIG) {
      throw new Error(`第 ${index + 1} 个中央目录项签名不对，文件已损坏`);
    }
    const flags = buffer.readUInt16LE(cursor + 8);
    const method = buffer.readUInt16LE(cursor + 10);
    const compressedSize = buffer.readUInt32LE(cursor + 20);
    const uncompressedSize = buffer.readUInt32LE(cursor + 24);
    const nameLength = buffer.readUInt16LE(cursor + 28);
    const extraLength = buffer.readUInt16LE(cursor + 30);
    const commentLength = buffer.readUInt16LE(cursor + 32);
    const externalAttributes = buffer.readUInt32LE(cursor + 38);
    const localOffset = buffer.readUInt32LE(cursor + 42);
    const rawName = buffer.subarray(cursor + CENTRAL_HEADER_SIZE, cursor + CENTRAL_HEADER_SIZE + nameLength);
    const name = rawName.toString((flags & FLAG_UTF8) !== 0 ? 'utf8' : 'latin1');

    const unixMode = externalAttributes >>> 16;
    const typeBits = unixMode & 0o170000;
    const kind = name.endsWith('/')
      ? 'dir'
      : typeBits === S_IFLNK
        ? 'symlink'
        : typeBits === S_IFREG
          ? 'file'
          : 'other';

    let linkTarget = '';
    if (kind === 'symlink' && method === METHOD_STORE && compressedSize > 0) {
      // 本地头长度固定，数据紧跟文件名之后。
      const localNameLength = buffer.readUInt16LE(localOffset + 26);
      const localExtraLength = buffer.readUInt16LE(localOffset + 28);
      const dataStart = localOffset + LOCAL_HEADER_SIZE + localNameLength + localExtraLength;
      linkTarget = buffer.subarray(dataStart, dataStart + compressedSize).toString('utf8');
    }

    entries.push({
      path: kind === 'dir' ? name.slice(0, -1) : name,
      kind,
      size: kind === 'file' ? uncompressedSize : 0,
      // 外部属性的低 16 位是 DOS 位，高 16 位是 st_mode；这里只保留权限位。
      mode: unixMode & 0o7777,
      linkTarget,
    });

    cursor += CENTRAL_HEADER_SIZE + nameLength + extraLength + commentLength;
  }

  return entries;
}

export function writeZipFile(entries, outPath, options = {}) {
  const buffer = writeZip(entries, options);
  fs.writeFileSync(outPath, buffer);
  return buffer.length;
}
