// SPDX-License-Identifier: Apache-2.0
/**
 * @file session-files.js
 * @description 会话文件只读接口：按**绝对路径**读取文本 / 原始字节。
 *
 * 为什么由 viewer 自己的 server 提供，而不是调 smart-factory：
 * - 会话页里的文件引用是 viewer 自己在渲染，读文件也由 viewer 负责，少一层耦合；
 * - 会话服务将来可能替换（商业版 / 其他运行时），文件读取不受影响；
 * - Windows 盘符路径在这里按统一规则处理，不再依赖上游的 `/fs/raw`。
 *
 * 只读：没有写 / 删 / 改名入口。
 *
 * 安全模型：
 * - 默认允许跨机访问（局域网页面可直接读取正文引用的文件）；
 *   设置 `VIEWER_FS_LOCAL_ONLY=1` 后只允许回环地址。
 * - 只接受绝对路径（`~/` 由服务端展开），相对路径一律 400。
 * - 文本上限 2 MiB；按 BOM 解码 UTF-8 / UTF-16（LE/BE），**解码后**仍含 NUL 才视为
 *   二进制返回 415 —— Windows 上被 PowerShell 等写成 UTF-16 的 `.ini` / `.reg`
 *   不应因为"每隔一个字节是 0"就被判成不支持预览。
 * - 原始流用 `sendFile`，按扩展名给 Content-Type；dotfiles 放行（产物里常有 `.env`）。
 * - HTML / SVG 原始流加 CSP `sandbox`；PDF 例外（sandbox 会让浏览器内置查看器
 *   拒绝渲染）。
 */

const express = require("express");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { allowRequest } = require("../lib/access-control");

const router = express.Router();

/** 文本预览上限；与 smart-factory `/fs/read` 同口径。 */
const MAX_TEXT_BYTES = 2 * 1024 * 1024;

/** UTF-16 无 BOM 时用于猜字节序的采样长度。 */
const UTF16_SNIFF_BYTES = 4096;

class FileError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "FileError";
    this.status = status;
    this.code = code;
  }
}

function localOnly(req, res, next) {
  if (allowRequest(req)) return next();
  return res.status(403).json({
    error: { code: "FORBIDDEN", message: "文件读取只允许本机访问" },
  });
}

function fail(res, error) {
  if (error instanceof FileError) {
    return res.status(error.status).json({
      error: { code: error.code, message: error.message },
    });
  }
  console.error("[session-files] 读取文件失败：", error);
  return res.status(500).json({
    error: { code: "INTERNAL", message: "读取文件失败" },
  });
}

/** 一次批量解析最多多少个路径（前端按去重后的链接数发，正常远小于这个数）。 */
const RESOLVE_MAX_ITEMS = 50;
/** 单条路径 / 单个根的长度上限。 */
const RESOLVE_MAX_PATH_LENGTH = 4096;

/**
 * 相对路径 + 候选根 → 磁盘上真实存在的绝对路径（不存在返回 null）。
 *
 * 为什么需要候选根：正文里的相对路径是自由文本，**基准不一定等于会话 cwd**
 * （可能是 agent 根、`development/`、工作区根）。这里按顺序试，第一个真实存在的
 * 胜出；一个都不存在就不出链接。`raw` 本身是绝对路径时直接用，不拼根。
 *
 * 相对路径限制在候选根内（`..` 逃逸一律不认）：读取接口本身不设边界，但"解析"只是
 * 为了把用户写的相对链接落到它该在的目录，不该顺手把 `../../x` 变成别处的文件。
 */
function resolveAgainstRoots(raw, roots) {
  if (typeof raw !== "string") return null;
  const value = expandHome(raw.trim());
  if (value === "" || value.includes("\u0000") || value.length > RESOLVE_MAX_PATH_LENGTH) {
    return null;
  }

  const tryFile = (candidate) => {
    try {
      const real = fs.realpathSync(candidate);
      return fs.statSync(real).isFile() ? real : null;
    } catch {
      return null;
    }
  };

  if (path.isAbsolute(value)) return tryFile(value);

  for (const root of roots) {
    if (typeof root !== "string") continue;
    const rootValue = expandHome(root.trim());
    if (rootValue === "" || !path.isAbsolute(rootValue)) continue;

    const candidate = path.resolve(rootValue, value);
    const rel = path.relative(path.resolve(rootValue), candidate);
    if (rel === "" || rel.startsWith("..") || path.isAbsolute(rel)) continue;

    const real = tryFile(candidate);
    if (real !== null) return real;
  }
  return null;
}

/**
 * 批量解析正文里的相对路径。
 *
 * body: `{ items: [{ path: string, roots: string[] }] }`
 * 响应: `{ items: [{ path: string, resolved: string | null }] }`（顺序与入参一致）
 *
 * 单条失败不影响其它条目 —— 前端一次问一批，某条畸形不该让整批变成错误态。
 */
router.post("/resolve", localOnly, (req, res) => {
  const items = req.body?.items;
  if (!Array.isArray(items) || items.length === 0) {
    return res.status(400).json({
      error: { code: "BAD_REQUEST", message: "items 必须是非空数组" },
    });
  }
  if (items.length > RESOLVE_MAX_ITEMS) {
    return res.status(400).json({
      error: { code: "BAD_REQUEST", message: `一次最多解析 ${RESOLVE_MAX_ITEMS} 条路径` },
    });
  }

  const resolved = items.map((item) => {
    const raw = typeof item?.path === "string" ? item.path : "";
    const roots = Array.isArray(item?.roots) ? item.roots : [];
    return { path: raw, resolved: resolveAgainstRoots(raw, roots) };
  });

  return res.json({ items: resolved });
});

/** `~/...` 展开成主目录；其它路径原样返回。 */
function expandHome(value) {
  if (value === "~") return os.homedir();
  if (value.startsWith("~/") || value.startsWith("~\\")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

/**
 * 入参 → 磁盘上的真实文件。
 *
 * Windows / POSIX 都只认绝对路径：`C:/...`、`C:\...`、`/...`、`~/...`。
 * `realpathSync` 统一解掉软链，返回值可以直接用于读取 / sendFile。
 */
function resolveInputPath(raw) {
  if (typeof raw !== "string" || raw.trim() === "") {
    throw new FileError(400, "BAD_REQUEST", "path 必填");
  }
  if (raw.includes("\u0000")) {
    throw new FileError(400, "BAD_REQUEST", "path 非法");
  }

  const value = expandHome(raw.trim());
  if (!path.isAbsolute(value)) {
    throw new FileError(400, "BAD_REQUEST", `path 必须是绝对路径：${raw}`);
  }

  let real;
  try {
    real = fs.realpathSync(value);
  } catch (error) {
    const code = error && error.code;
    if (code === "ENOENT" || code === "ENOTDIR") {
      throw new FileError(404, "NOT_FOUND", `文件不存在：${raw}`);
    }
    throw new FileError(500, "INTERNAL", `读取路径失败：${raw}`);
  }

  let stat;
  try {
    stat = fs.statSync(real);
  } catch {
    throw new FileError(404, "NOT_FOUND", `文件不存在：${raw}`);
  }
  if (!stat.isFile()) {
    throw new FileError(400, "BAD_REQUEST", `不是普通文件：${raw}`);
  }

  return { real, stat };
}

/** 偶数长度（UTF-16 解码前丢掉落单的最后一个字节）。 */
function evenLength(length) {
  return length % 2 === 0 ? length : length - 1;
}

/** UTF-16BE → 字符串：先换字节序再按 LE 解（Node 不直接支持 be）。 */
function utf16beToString(body) {
  const aligned = Buffer.from(body.subarray(0, evenLength(body.length)));
  return aligned.swap16().toString("utf16le");
}

/**
 * 无 BOM 的 UTF-16 猜测：ASCII 占比高的文本，其"空字节"会稳定落在高字节位。
 *
 * 只在高零字节占比 > 60%、另一侧 < 10% 时下结论，宁可漏判（退回二进制）
 * 也不把真正的二进制解成乱码。
 */
function guessUtf16ByteOrder(buffer) {
  const sample = buffer.subarray(0, Math.min(buffer.length, UTF16_SNIFF_BYTES));
  const pairs = Math.floor(sample.length / 2);
  if (pairs < 4) return null;

  let zeroEven = 0;
  let zeroOdd = 0;
  for (let i = 0; i < pairs * 2; i += 2) {
    if (sample[i] === 0) zeroEven += 1;
    if (sample[i + 1] === 0) zeroOdd += 1;
  }
  if (zeroOdd / pairs > 0.6 && zeroEven / pairs < 0.1) return "le";
  if (zeroEven / pairs > 0.6 && zeroOdd / pairs < 0.1) return "be";
  return null;
}

/**
 * 字节 → 文本：按 BOM 识别 UTF-8 / UTF-16LE / UTF-16BE；无 BOM 时先做一次
 * 保守的 UTF-16 猜测，最后才按 UTF-8 解。
 */
function decodeTextBuffer(buffer) {
  if (buffer.length >= 3 && buffer[0] === 0xef && buffer[1] === 0xbb && buffer[2] === 0xbf) {
    return buffer.subarray(3).toString("utf8");
  }
  if (buffer.length >= 2 && buffer[0] === 0xff && buffer[1] === 0xfe) {
    return buffer.subarray(2).toString("utf16le");
  }
  if (buffer.length >= 2 && buffer[0] === 0xfe && buffer[1] === 0xff) {
    return utf16beToString(buffer.subarray(2));
  }

  const byteOrder = guessUtf16ByteOrder(buffer);
  if (byteOrder === "le") {
    return buffer.subarray(0, evenLength(buffer.length)).toString("utf16le");
  }
  if (byteOrder === "be") {
    return utf16beToString(buffer.subarray(0, evenLength(buffer.length)));
  }
  return buffer.toString("utf8");
}

/** 读一个文本文件：UTF-8 / UTF-16（BOM 或启发式）、2 MiB 上限、解码后二进制 415。 */
router.get("/read", localOnly, (req, res) => {
  try {
    const { real, stat } = resolveInputPath(req.query.path);
    if (stat.size > MAX_TEXT_BYTES) {
      throw new FileError(
        413,
        "PAYLOAD_TOO_LARGE",
        `文件超过预览上限（${MAX_TEXT_BYTES} 字节）`
      );
    }

    const content = decodeTextBuffer(fs.readFileSync(real));
    // 解码之后还有 NUL，才是真正的二进制（UTF-16 文本已在上一步还原）
    if (content.includes("\u0000")) {
      throw new FileError(415, "UNSUPPORTED_MEDIA_TYPE", "不是可预览的文本文件");
    }

    res.json({
      path: real,
      name: path.basename(real),
      size: stat.size,
      mtime: stat.mtime.toISOString(),
      content,
    });
  } catch (error) {
    return fail(res, error);
  }
});

/**
 * 原始字节流（图片、二进制下载）。
 *
 * 路径走**分段**而不是 `?path=`：图片 / HTML 里的相对资源只有这样才会落在
 * 同一目录下。Express 4 的 `*` 通配把匹配到的部分放在 `req.params[0]`。
 *
 * 盘符路径（`C:/...`）原样使用；POSIX 的分段丢了开头的 `/`，这里补回来。
 * 不要像旧版 smart-factory 那样对盘符也补 `/`，否则 Windows 上会变成 `/C:/...`。
 */
router.get("/raw/*", localOnly, (req, res, next) => {
  try {
    let joined = req.params[0] ?? "";
    if (!joined.startsWith("~") && !/^[A-Za-z]:[\\/]/.test(joined)) {
      joined = `/${joined}`;
    }

    const { real } = resolveInputPath(joined);
    res.set({
      "Content-Disposition": "inline",
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "no-store",
    });
    /*
     * PDF 走浏览器内置查看器：`sandbox` 会阻止它加载（Chrome 会显示空白 /
     * “Failed to load PDF document”），所以 PDF 不加 CSP；HTML / SVG 等仍加，
     * 防止本机文件在 viewer 源下执行脚本。
     */
    if (path.extname(real).toLowerCase() !== ".pdf") {
      res.set(
        "Content-Security-Policy",
        "sandbox allow-scripts allow-forms allow-popups allow-downloads"
      );
    }
    res.sendFile(real, { dotfiles: "allow" }, (error) => {
      if (error !== undefined) next(error);
    });
  } catch (error) {
    return fail(res, error);
  }
});

module.exports = router;
module.exports.MAX_TEXT_BYTES = MAX_TEXT_BYTES;
