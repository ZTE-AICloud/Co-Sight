// SPDX-License-Identifier: Apache-2.0
/**
 * @file fs.js
 * @description 本机文件浏览接口：发送框「添加文件 → 本地文件」的数据源。
 *
 * 为什么由 viewer 自己的 server 提供，而不是调 smart-factory：
 * - 文件选择是 viewer 自己的能力，不依赖会话服务（商业版会换运行时）；
 * - 只列目录、不读内容、不写入；
 * - 工程里没有任何外部命令：Windows 盘符用 Node 的 `fs.stat` 探测，
 *   macOS / Linux 用 `/`、`/Volumes`、`/mnt`、`/media`。
 *
 * 安全模型：
 * - 默认允许跨机访问（服务监听 0.0.0.0，局域网页面可直接浏览文件）；
 *   设置 `VIEWER_FS_LOCAL_ONLY=1` 后只允许回环地址。
 * - 只接受绝对路径（`~/` 由服务端展开），相对路径一律 400。
 * - 只列一层，条目上限 2000；不做递归。
 */

const express = require("express");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");

const { allowRequest } = require("../lib/access-control");

const router = express.Router();

/** 一次最多返回多少条：主目录里动辄几万个条目，全量回给前端既费带宽也费渲染。 */
const LIST_LIMIT = 2000;

/** 盘符 / 根目录列表缓存时间：打开选择器时不必每次都重扫。 */
const ROOTS_TTL_MS = 20_000;

/** 探测单个盘符的超时：断开的网络驱动器不该把整次请求拖住。 */
const DRIVE_PROBE_TIMEOUT_MS = 800;

class FsError extends Error {
  constructor(status, code, message) {
    super(message);
    this.name = "FsError";
    this.status = status;
    this.code = code;
  }
}

function localOnly(req, res, next) {
  if (allowRequest(req)) return next();
  return res.status(403).json({
    error: { code: "FORBIDDEN", message: "文件浏览只允许本机访问" },
  });
}

/** 错误 → HTTP：形态非法 400、不存在 404、无权限 403，其余 500。 */
function fail(res, error) {
  if (error instanceof FsError) {
    return res.status(error.status).json({
      error: { code: error.code, message: error.message },
    });
  }
  const code = error && error.code;
  if (code === "ENOENT" || code === "ENOTDIR") {
    return res.status(404).json({
      error: { code: "NOT_FOUND", message: "目录不存在" },
    });
  }
  if (code === "EACCES" || code === "EPERM") {
    return res.status(403).json({
      error: { code: "FORBIDDEN", message: "没有权限访问该目录" },
    });
  }
  console.error("[fs] 列出目录失败：", error);
  return res.status(500).json({
    error: { code: "INTERNAL", message: "读取目录失败" },
  });
}

/** `~/...` 展开成主目录；其它路径原样返回。 */
function expandHome(value) {
  if (value === "~") return os.homedir();
  if (value.startsWith("~/") || value.startsWith("~\\")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      const timer = setTimeout(() => reject(new Error("timeout")), ms);
      if (typeof timer.unref === "function") timer.unref();
    }),
  ]);
}

async function exists(target) {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}

/** 目录自身是不是文件系统根（`C:\\` 或 `/`）。 */
function isFsRoot(target) {
  return path.parse(target).root === target;
}

/** 上一级；根目录返回 null，前端据此禁用「上一级」。 */
function parentOf(target) {
  return isFsRoot(target) ? null : path.dirname(target);
}

/** 探一个盘符；不存在或超时返回 null。 */
async function probeDrive(letter) {
  const root = `${letter}:\\`;
  try {
    // 与 /fs/list 同口径：realpath 失败（断开的映射盘）就不列出来，避免点进去才 404。
    const real = await withTimeout(fs.realpath(root), DRIVE_PROBE_TIMEOUT_MS);
    const stats = await withTimeout(fs.stat(real), DRIVE_PROBE_TIMEOUT_MS);
    if (!stats.isDirectory()) return null;

    // 有些映射盘 realpath / stat 能过、真正 readdir 却失败（例如当前机器的 T:）。
    // 读一个条目确认可列目录，避免用户点进根目录才看到「目录不存在」。
    const dir = await withTimeout(fs.opendir(real), DRIVE_PROBE_TIMEOUT_MS);
    try {
      await withTimeout(dir.read(), DRIVE_PROBE_TIMEOUT_MS);
    } finally {
      await dir.close();
    }
    return { label: `${letter}:`, path: real, kind: "drive" };
  } catch {
    return null;
  }
}

/** POSIX 挂载点：只列一层，失败就跳过（`/Volumes` 在 Linux 上通常不存在）。 */
async function listMounts(base, kind) {
  try {
    const entries = await fs.readdir(base, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isDirectory())
      .map((entry) => ({
        label: entry.name,
        path: path.join(base, entry.name),
        kind,
      }));
  } catch {
    return [];
  }
}

/** 可浏览的根：常用目录在前，盘符 / 挂载点在后。 */
async function buildRoots() {
  const home = os.homedir();
  const items = [];

  const quick = [
    ["主目录", home, "home"],
    ["桌面", path.join(home, "Desktop"), "desktop"],
    ["下载", path.join(home, "Downloads"), "downloads"],
    ["文档", path.join(home, "Documents"), "documents"],
  ];
  for (const [label, target, kind] of quick) {
    if (await exists(target)) items.push({ label, path: target, kind });
  }

  if (process.platform === "win32") {
    const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
    const drives = await Promise.all(letters.map(probeDrive));
    items.push(...drives.filter(Boolean));
  } else {
    items.push({ label: "根目录", path: "/", kind: "root" });
    items.push(...(await listMounts("/Volumes", "mount")));
    items.push(...(await listMounts("/mnt", "mount")));
    items.push(...(await listMounts("/media", "mount")));
  }

  // 同一个目录只留一条（主目录与盘符不会重复，但挂载点可能）
  const seen = new Set();
  return items.filter((item) => {
    const key = item.path.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

let rootsCache = null;

/** 可浏览的根（带短缓存）。 */
router.get("/roots", localOnly, async (_req, res) => {
  try {
    const now = Date.now();
    if (rootsCache === null || rootsCache.expiresAt <= now) {
      rootsCache = { value: await buildRoots(), expiresAt: now + ROOTS_TTL_MS };
    }
    res.set("Cache-Control", "no-store");
    res.json({ items: rootsCache.value });
  } catch (error) {
    return fail(res, error);
  }
});

/** 列一层目录。 */
/**
 * 浏览边界：列表请求带了 `root` 时，`path` 必须落在它里面。
 *
 * 会话工作区面板用这个参数把浏览范围限定在会话自己的工作区（产品语义），
 * 而不是整机。附件选择器不传 `root`，保持原来的整机可浏览。
 */
function assertWithinRoot(root, requested) {
  const relativePath = path.relative(root, requested);
  if (relativePath === "" || (!relativePath.startsWith("..") && !path.isAbsolute(relativePath))) {
    return;
  }
  throw new FsError(403, "FORBIDDEN", `超出工作区范围：${requested}`);
}

router.get("/list", localOnly, async (req, res) => {
  try {
    const rawRoot = typeof req.query.root === "string" ? req.query.root.trim() : "";
    const root = rawRoot === "" ? null : expandHome(rawRoot);
    if (root !== null) {
      if (root.includes("\u0000")) {
        throw new FsError(400, "BAD_REQUEST", "root 非法");
      }
      if (!path.isAbsolute(root)) {
        throw new FsError(400, "BAD_REQUEST", `root 必须是绝对路径：${root}`);
      }
    }

    const raw = typeof req.query.path === "string" ? req.query.path : "";
    const requested = raw.trim() === "" ? (root ?? os.homedir()) : expandHome(raw.trim());

    if (requested.includes("\u0000")) {
      throw new FsError(400, "BAD_REQUEST", "path 非法");
    }
    if (!path.isAbsolute(requested)) {
      throw new FsError(400, "BAD_REQUEST", `path 必须是绝对路径：${requested}`);
    }

    let real = null;
    if (root !== null) {
      // 两段都先 realpath 再比：root 可能是软链，字符串前缀会误判
      let realRoot;
      try {
        realRoot = await fs.realpath(root);
      } catch {
        throw new FsError(404, "NOT_FOUND", `工作区目录不存在：${root}`);
      }
      try {
        real = await fs.realpath(requested);
      } catch {
        throw new FsError(404, "NOT_FOUND", `路径不存在：${requested}`);
      }
      assertWithinRoot(realRoot, real);
    }

    real ??= await fs.realpath(requested);
    const stats = await fs.stat(real);
    if (!stats.isDirectory()) {
      throw new FsError(400, "BAD_REQUEST", `不是目录：${requested}`);
    }

    const dirents = await fs.readdir(real, { withFileTypes: true });
    const hinted = dirents.slice().sort((a, b) => {
      if (a.isDirectory() !== b.isDirectory()) return a.isDirectory() ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    const kept = hinted.slice(0, LIST_LIMIT);

    // 分批 stat：一次 32 个，既不让线程池排队太长，也不至于串行等上千次 IO。
    const items = [];
    const BATCH = 32;
    for (let index = 0; index < kept.length; index += BATCH) {
      const batch = kept.slice(index, index + BATCH);
      const entries = await Promise.all(
        batch.map(async (dirent) => {
          const full = path.join(real, dirent.name);
          try {
            const entryStats = await fs.stat(full);
            const isDir = entryStats.isDirectory();
            // 软链按目标路径回给前端：发送时服务端会 realpath，路径不一致会让
            // 乐观消息与回执对不上（同一句话出现两条气泡）。
            const entryPath = dirent.isSymbolicLink() ? await fs.realpath(full) : full;
            return {
              name: dirent.name,
              path: entryPath,
              type: isDir ? "dir" : "file",
              size: isDir ? 0 : entryStats.size,
              mtime: entryStats.mtime.toISOString(),
            };
          } catch {
            // 读不到 stat 的条目（权限 / 竞态删除）直接跳过，不制造半条数据
            return null;
          }
        }),
      );
      for (const entry of entries) {
        if (entry !== null) items.push(entry);
      }
    }

    items.sort((a, b) => {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });

    res.set("Cache-Control", "no-store");
    res.json({
      path: real,
      parent: parentOf(real),
      items,
      truncated: hinted.length > LIST_LIMIT,
    });
  } catch (error) {
    return fail(res, error);
  }
});

/**
 * 附件来源能力。
 *
 * 开源版本地单机用 `local-path`（选择器返回真实路径）；
 * 商用云容器版将来返回 `upload`，客户端据此切换到上传实现。
 */
router.get("/capabilities", localOnly, (_req, res) => {
  res.json({ attachmentMode: "local-path" });
});

module.exports = router;
module.exports.LIST_LIMIT = LIST_LIMIT;
