/**
 * 工作区文件的**只读**浏览：列一层目录、读一个文本文件、读一张图片。
 *
 * ## 为什么单独一个服务，而不是塞进 `services/workspaces.ts`
 *
 * `workspaces.ts` 管的是**记录**（重名、建目录、切换生效项），它碰磁盘只有一处：
 * 按工作区名派生目录名。这里管的是**用户目录里的内容**，是这个框架第一次
 * 去读工作区里的东西。两者的失败模式、安全面、上限都不一样，混在一个类里
 * 会让"哪些方法会读用户文件"变成需要逐行看才能回答的问题。
 *
 * ## 安全模型：路径是唯一的输入，也是唯一要防的东西
 *
 * 请求里**没有绝对路径**——根目录由服务端按工作区 id 从库里取（`Workspace.directory`），
 * 客户端只说"根下面的哪一段"。这把攻击面收到一个字符串上，而这个字符串要过三关：
 *
 * 1. **分段拒绝**（`normalizeRelativePath`）：绝对路径、`..`、`\`、NUL 一律拒。
 *    这一关挡的是"写错/手改地址栏"，是廉价的；
 * 2. **`realpath` 后判包含**（`#resolve`）：先把路径解析成磁盘上的**真实**路径，
 *    再用 `isInside` 按路径段比较。这一关才是真正的防线——工作区里放一个指向
 *    `/etc` 的软链，字符串前缀比对完全看不出来，`realpath` 之后才露馅。
 *    顺序不能反：先比字符串再 realpath，等于没比；
 * 3. **不跟随软链**（`#resolve` 里对末段 `lstat` 的判定）：末段本身是软链就拒。
 *    这是**与 dsh 的刻意分叉**——dsh 的 `read` 明确允许读到工作区外（它的消费方是
 *    cc 的资源地址），我们不是那个场景，第 2 关已经能挡住逃逸，第 3 关是把
 *    "读的是哪个文件"这件事变得**不用推理**：路径指向什么就读什么。
 *
 * ## 只读
 *
 * 这个文件里没有 `writeFile` / `unlink` / `mkdir` / `rename`，将来也不该有。
 * `docs/workspace-design.md` 的「只读浏览」一节把这条写成了对外的承诺。
 *
 * ## 上限都是具名常量
 *
 * 测试直接引用它们，所以"上限是多少"只有一个定义处；散在代码里的字面量会让
 * 测试断言一个和实现对不上的数。
 */

import fs from 'node:fs';
import path from 'node:path';

import {
  AppError,
  WORKSPACE_FILE_LIMITS,
  type Workspace,
  type WorkspaceFileEntry,
  type WorkspaceFileImage,
  type WorkspaceFileListing,
  type WorkspaceFileText,
} from 'harness-shared';

import { isInside } from '../config/paths';

/**
 * 二进制探测只看开头这么多字节。
 *
 * 三个客户端看得见的上限（条目数、文本字节、图片字节）定义在契约里
 * （`shared/src/contracts/workspace-file.ts`），因为前端要用同一组数把
 * "只显示了前面多少"说准。这一个不上契约：它只影响服务端的判定过程，
 * 客户端从响应里看不出它是 8 KiB 还是 16 KiB。
 */
const SNIFF_BYTES = 8 * 1024;

/**
 * 这个服务只需要"按 id 找到工作区"这一件事。
 *
 * 声明成窄接口而不是直接收 `WorkspaceService`：它读的是**记录**，不是用户文件，
 * 让依赖面在类型上就是可见的；测试也只需要给一个返回固定记录的假对象。
 */
export interface WorkspaceLocator {
  findById(id: string): Promise<Workspace | null>;
}

export interface WorkspaceFileServiceOptions {
  workspaces: WorkspaceLocator;
}

export class WorkspaceFileService {
  readonly #workspaces: WorkspaceLocator;

  constructor(options: WorkspaceFileServiceOptions) {
    this.#workspaces = options.workspaces;
  }

  /**
   * 列一层目录。
   *
   * `root === null`（工作区没绑目录）走 `200` 而不是 `404`：那是**正常状态**，
   * 与 `GET /workspaces/active` 没有生效项时返回 `data: null` 是同一条既有口径。
   * 而"目录绑定过、磁盘上却没了"是 `404`——用户以为文件还在，必须如实说。
   */
  async list(workspaceId: string, rawPath: string): Promise<WorkspaceFileListing> {
    const { root } = await this.#locate(workspaceId);
    if (root === null) {
      return { root: null, path: '', entries: [], truncated: false };
    }

    const relative = normalizeRelativePath(rawPath);
    const target = this.#resolve(root, relative);
    if (!target.info.isDirectory()) {
      throw new AppError(
        'BAD_REQUEST',
        'error.bad_request.workspace_not_a_directory',
        `路径不是一个目录：${relative}`,
      );
    }

    const entries = fs
      .readdirSync(target.real, { withFileTypes: true })
      .map((dirent) => toEntry(target.real, dirent));
    /*
     * 按名字排一遍再截断。`readdirSync` 的顺序由文件系统决定（ext4 上是哈希序），
     * 不排的话"第 2001 项是谁"每次重启都可能变，截断就不可复现了。
     * 这里用的是朴素的名字序，不是界面上的显示序——显示序（目录优先、数字感知）
     * 由前端用 `Intl.Collator` 做，它比服务端更懂用户的语言环境。
     */
    const ordered = entries.toSorted((left, right) => compareNames(left.name, right.name));

    const truncated = ordered.length > WORKSPACE_FILE_LIMITS.maxEntries;
    return {
      root,
      path: relative,
      entries: truncated ? ordered.slice(0, WORKSPACE_FILE_LIMITS.maxEntries) : ordered,
      truncated,
    };
  }

  /** 读一个文本文件的前 `maxTextBytes` 字节。 */
  async readText(workspaceId: string, rawPath: string): Promise<WorkspaceFileText> {
    const { real, relative, info } = await this.#resolveFile(workspaceId, rawPath);

    const size = info.size;
    const truncated = size > WORKSPACE_FILE_LIMITS.maxTextBytes;
    const buffer = readAtMost(real, truncated ? WORKSPACE_FILE_LIMITS.maxTextBytes : size);

    return { path: relative, size, text: decodeText(buffer, truncated), truncated };
  }

  /** 读一张图片，内联成 data URL。 */
  async readImage(workspaceId: string, rawPath: string): Promise<WorkspaceFileImage> {
    const { real, relative, info } = await this.#resolveFile(workspaceId, rawPath);

    if (info.size > WORKSPACE_FILE_LIMITS.maxImageBytes) {
      throw imageTooLarge(relative);
    }

    // 上限已经判过，这里整读；`statSync` 与 `readFileSync` 之间文件若变大，
    // `readFileSync` 会读到更多——所以读回来再按实际长度判一次，别信 stat 的那个数。
    const buffer = fs.readFileSync(real);
    if (buffer.byteLength > WORKSPACE_FILE_LIMITS.maxImageBytes) {
      throw imageTooLarge(relative);
    }

    const contentType = sniffImageType(buffer);
    if (contentType === null) {
      throw notPreviewable(relative);
    }

    return {
      path: relative,
      size: buffer.byteLength,
      contentType,
      dataUrl: `data:${contentType};base64,${buffer.toString('base64')}`,
    };
  }

  /**
   * 找到工作区，以及它目录的**真实**路径（没绑目录则是 `null`）。
   *
   * 目录在库里存的就是 `realpath` 过的值，但磁盘随时可能变（被删、被换成软链、
   * 被挂载点换掉），所以这里以**磁盘当前状态**为准再解析一次。不这么做的话，
   * 一个"库里有、磁盘上没有"的绑定会让后面每一关都在赌旧值的有效性。
   */
  async #locate(workspaceId: string): Promise<{ workspace: Workspace; root: string | null }> {
    const workspace = await this.#workspaces.findById(workspaceId);
    if (workspace === null) {
      throw AppError.notFound('工作区', workspaceId);
    }
    if (workspace.directory === null) {
      return { workspace, root: null };
    }

    let real: string;
    try {
      real = fs.realpathSync(workspace.directory);
    } catch (error) {
      throw missingDirectory(workspace, error);
    }
    if (!fs.statSync(real).isDirectory()) {
      throw missingDirectory(workspace, undefined);
    }
    return { workspace, root: real };
  }

  /** 解析到一个**普通文件**上。路径存在但不是普通文件 → `400`。 */
  async #resolveFile(
    workspaceId: string,
    rawPath: string,
  ): Promise<{ real: string; relative: string; info: fs.Stats }> {
    const { workspace, root } = await this.#locate(workspaceId);
    if (root === null) {
      // 没绑目录，任何相对路径都无从谈起。说得具体一点，不然用户看到的是
      // "工作区里没有这个文件"，而他真正的待办是去给工作区绑一个目录。
      throw new AppError(
        'NOT_FOUND',
        'error.not_found.workspace_directory',
        `工作区「${workspace.name}」还没有绑定目录`,
      );
    }

    const relative = normalizeRelativePath(rawPath);
    const target = this.#resolve(root, relative);
    if (!target.info.isFile()) {
      throw new AppError(
        'BAD_REQUEST',
        'error.bad_request.workspace_not_a_file',
        `路径不是一个普通文件：${relative}`,
      );
    }
    return { real: target.real, relative, info: target.info };
  }

  /**
   * 相对路径 → 磁盘上已验证的真实路径。**两道关都在这里**，别处不再拼路径。
   *
   * 顺序是刻意的：先 `lstat` 看末段是不是软链（是就拒），再 `realpath` 解掉
   * 中间各段，最后判包含。反过来先 `realpath` 的话，末段软链已经被解掉了，
   * 就再也分不出"用户点的是个软链"还是"用户点的是那个文件"。
   */
  #resolve(root: string, relative: string): { real: string; info: fs.Stats } {
    const absolute = relative === '' ? root : path.join(root, relative);

    let link: fs.Stats;
    try {
      link = fs.lstatSync(absolute);
    } catch (error) {
      throw missingPath(relative, error);
    }
    if (link.isSymbolicLink()) {
      throw new AppError(
        'FORBIDDEN',
        'error.forbidden.workspace_file',
        `工作区文件浏览不跟随软链：${relative}`,
      );
    }

    let real: string;
    try {
      real = fs.realpathSync(absolute);
    } catch (error) {
      throw missingPath(relative, error);
    }
    if (!isInside(root, real)) {
      /*
       * 中间某一段是软链，指到了工作区外。**消息里只回显用户自己给的那段相对路径**，
       * 不回显解析出来的真实路径：那是服务端的文件系统布局，用户没问就不该看，
       * 更不该让它有机会出现在别人的页面里。
       */
      throw new AppError(
        'FORBIDDEN',
        'error.forbidden.workspace_file',
        `这个路径不在工作区内，已拒绝：${relative}`,
      );
    }

    return { real, info: fs.statSync(real) };
  }
}

/**
 * 工作区相对路径的规范化。
 *
 * 只用 `/` 分段——**`\` 一律拒**，不做平台适配。理由：`path.join` 在 Windows 上
 * 会把 `\` 当分隔符，于是 `a\..\..\x` 就成了一次跨目录跳转；一个"在哪套规则下
 * 解析"取决于运行平台的安全检查是不可接受的。代价是 POSIX 上文件名里真带 `\`
 * 的文件点不开（现实里几乎不存在），换来的是"这个函数的行为与平台无关"。
 *
 * `.` 段静默丢掉（它不改变指向），`..` 段一律拒——**即使它最终会绕回工作区内**
 * （`a/../b`）。只认"看不出意图"这一种差别没有意义，一条规则更容易被审计。
 */
export function normalizeRelativePath(raw: string): string {
  if (raw.includes('\0') || raw.includes('\\') || path.isAbsolute(raw)) {
    throw rejectPath(raw);
  }

  const segments: string[] = [];
  for (const segment of raw.split('/')) {
    if (segment === '' || segment === '.') {
      continue;
    }
    if (segment === '..' || DRIVE_LETTER.test(segment)) {
      throw rejectPath(raw);
    }
    segments.push(segment);
  }
  return segments.join('/');
}

/** `C:` 这种盘符段。POSIX 上它不是绝对路径，所以 `path.isAbsolute` 拦不住它。 */
const DRIVE_LETTER = /^[a-z]:$/i;

function rejectPath(raw: string): AppError {
  return new AppError(
    'FORBIDDEN',
    'error.forbidden.workspace_file',
    `不像是一条工作区相对路径，已拒绝：${raw}`,
  );
}

function missingDirectory(workspace: Workspace, cause: unknown): AppError {
  return new AppError(
    'NOT_FOUND',
    'error.not_found.workspace_directory',
    // 这里回显目录**是可以的**：它就是 `GET /workspaces/:id` 本来就返回的字段，
    // 用户自己在设置里填的，不是我们解析出来的内部布局。
    `工作区「${workspace.name}」绑定的目录不存在：${workspace.directory ?? '(未绑定)'}`,
    cause === undefined ? {} : { cause },
  );
}

function missingPath(relative: string, cause: unknown): AppError {
  const code = (cause as NodeJS.ErrnoException).code;
  if (code === 'ENOENT' || code === 'ENOTDIR') {
    return new AppError(
      'NOT_FOUND',
      'error.not_found.workspace_file',
      `工作区里没有这个路径：${relative}`,
      { cause },
    );
  }
  // EACCES / ELOOP / ENAMETOOLONG 这些不是"不存在"，别一律说成 404——
  // 那会让一次权限问题看起来像文件被删了。
  return new AppError('INTERNAL', 'error.internal', `读取工作区路径失败：${relative}`, { cause });
}

function notPreviewable(subject: string): AppError {
  return new AppError(
    'UNSUPPORTED_MEDIA_TYPE',
    'error.unsupported_media_type.workspace_file',
    `这个文件不是能预览的文本或图片：${subject}`,
  );
}

function imageTooLarge(relative: string): AppError {
  return new AppError(
    'PAYLOAD_TOO_LARGE',
    'error.payload_too_large.workspace_image',
    `图片超过预览上限（${WORKSPACE_FILE_LIMITS.maxImageBytes} 字节）：${relative}`,
  );
}

/** 目录项 → 契约里的条目。软链、FIFO、socket 一律 `other`（界面点了不会有反应）。 */
function toEntry(parent: string, dirent: fs.Dirent): WorkspaceFileEntry {
  if (dirent.isDirectory()) {
    return { name: dirent.name, type: 'directory' };
  }
  if (!dirent.isFile()) {
    return { name: dirent.name, type: 'other' };
  }
  // 大小只是给界面看的装饰，读不到（竞态：刚被删、权限不足）就不报，不因此让整个列表失败。
  try {
    return { name: dirent.name, type: 'file', size: fs.statSync(path.join(parent, dirent.name)).size };
  } catch {
    return { name: dirent.name, type: 'file' };
  }
}

/** 名字序。刻意不用 `localeCompare`：服务端没有用户的语言环境，这是给截断用的稳定序。 */
function compareNames(left: string, right: string): number {
  if (left === right) {
    return 0;
  }
  return left < right ? -1 : 1;
}

/**
 * 读**至多** `length` 字节，文件短了就返回短的。
 *
 * 不用 `readFileSync` 再切：一个 10 GB 的日志文件会先把内存吃满再被切掉。
 */
function readAtMost(file: string, length: number): Buffer {
  if (length === 0) {
    return Buffer.alloc(0);
  }

  const buffer = Buffer.allocUnsafe(length);
  const fd = fs.openSync(file, 'r');
  let offset = 0;
  try {
    while (offset < length) {
      const read = fs.readSync(fd, buffer, offset, length - offset, offset);
      if (read === 0) {
        break; // 读到这里文件就没了（stat 之后被截短）
      }
      offset += read;
    }
  } finally {
    fs.closeSync(fd);
  }
  return offset === length ? buffer : buffer.subarray(0, offset);
}

/**
 * 缓冲区 → 文本；不是文本就抛 `415`。
 *
 * 两条判据：开头 `sniffBytes` 里有 NUL 字节（文本文件不会有，而二进制文件极难避免），
 * 以及整段按 UTF-8 解不开。
 *
 * **截断时的诊断是这里唯一绕的地方**：长度是我们硬切出来的，末尾可能正好落在
 * 一个多字节字符中间，直接致命解码会把它误判成"不是文本"——一个中文文件读到
 * 512 KiB 就报错，用户会以为文件坏了。所以截断时依次试着丢掉尾部 1–3 个字节，
 * 能解出来就说明"只是被切断了"。**容忍范围仅限这一次重试**：整段用非致命解码
 * 会让真正的二进制内容带着一堆替换字符显示出来，那才是更糟的失败。
 */
function decodeText(buffer: Buffer, truncated: boolean): string {
  const sniffed = buffer.subarray(0, Math.min(buffer.length, SNIFF_BYTES));
  if (sniffed.includes(0)) {
    throw notPreviewable('(含 NUL 字节)');
  }

  const strict = new TextDecoder('utf-8', { fatal: true });
  try {
    return strict.decode(buffer);
  } catch {
    if (!truncated) {
      throw notPreviewable('(不是 UTF-8 文本)');
    }
    for (let drop = 1; drop <= 3 && drop < buffer.length; drop += 1) {
      try {
        return strict.decode(buffer.subarray(0, buffer.length - drop));
      } catch {
        // 再丢一个字节继续试；三次都不行就是真的二进制。
      }
    }
    throw notPreviewable('(不是 UTF-8 文本)');
  }
}

/** 各格式的魔数。按**内容**认，不按扩展名——扩展名是用户随手改的。 */
const IMAGE_SIGNATURES: readonly { contentType: string; bytes: readonly number[] }[] = [
  { contentType: 'image/png', bytes: [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a] },
  { contentType: 'image/jpeg', bytes: [0xff, 0xd8, 0xff] },
  { contentType: 'image/gif', bytes: [0x47, 0x49, 0x46, 0x38] }, // "GIF8"
  { contentType: 'image/bmp', bytes: [0x42, 0x4d] },
  { contentType: 'image/x-icon', bytes: [0x00, 0x00, 0x01, 0x00] },
];

/**
 * 认图片格式，认不出返回 `null`。
 *
 * SVG 没有魔数，只能看文本前缀。它进 `<img src="data:image/svg+xml;...">` 是安全的：
 * `<img>` 里的 SVG **不执行脚本、不加载外部资源**，这是浏览器规范行为，不是我们的假设。
 */
export function sniffImageType(buffer: Buffer): string | null {
  for (const signature of IMAGE_SIGNATURES) {
    if (startsWith(buffer, signature.bytes)) {
      return signature.contentType;
    }
  }
  // WebP 是 RIFF 容器："RIFF"+4 字节长度+"WEBP"。只看开头 4 字节会把 .wav/.avi 也认成 WebP。
  if (startsWith(buffer, [0x52, 0x49, 0x46, 0x46]) && startsWith(buffer.subarray(8), [0x57, 0x45, 0x42, 0x50])) {
    return 'image/webp';
  }
  return looksLikeSvg(buffer) ? 'image/svg+xml' : null;
}

function startsWith(buffer: Buffer, bytes: readonly number[]): boolean {
  if (buffer.length < bytes.length) {
    return false;
  }
  return bytes.every((byte, index) => buffer[index] === byte);
}

/**
 * 前缀里带 `<svg>` 就算。只读开头 1 KiB，一个巨大的 SVG 也认得出。
 *
 * `\s` 在 JS 里包含 U+FEFF 这个码位（ECMAScript 白名单的定义），所以 BOM 不用单独处理。
 * 这里写码位而不是那个字符本身：一个混在注释里的不可见字符，lint 会当成异常空白报出来。
 * 认不出来只意味着"打不开"，不是"显示错了"——把非 SVG 认成 SVG 才是错的方向。
 */
function looksLikeSvg(buffer: Buffer): boolean {
  return /^\s*(?:<\?xml[^>]*\?>\s*)?<svg[\s>]/i.test(buffer.subarray(0, 1024).toString('utf8'));
}
