#!/usr/bin/env node
/**
 * 模块前端的静态托管 + 同源反向代理。
 *
 * ── 为什么需要这一层 ────────────────────────────────────────────────────
 *
 * 有的模块（smart-factory）在开发态是 Vite dev server：页面在 4110、接口在 4100，
 * 靠 Vite proxy 抹平跨源。产物里没有 Vite，而前端代码已经写死了**同源相对路径**
 * （`/api/smart-factory/v1/...`，包括 WebSocket），直接开一个静态服务器会让所有
 * 接口 404。所以这里把两件事合成一个端口：
 *
 *     GET /api/*      → 反代到模块后端
 *     WS  /api/*      → 反代 Upgrade（WebSocket）
 *     其他 GET/HEAD   → web/dist 里的文件；找不到且像页面时回 index.html（SPA）
 *
 * 同源还有一个硬理由：模块前端返回的文件地址是根相对的（`/api/.../files/x`），
 * 页面在 4110、文件在 4100 时，这些 URL 会被解析到静态服务器上，永远取不到。
 *
 * ── 边界 ────────────────────────────────────────────────────────────────
 *
 * - 默认监听所有网卡（0.0.0.0），与框架服务端一致；只允许本机访问时传 `--host 127.0.0.1`。
 *   注意这一层不做任何鉴权，暴露面完全由 --host 决定。
 * - 静态路径解析后必须仍在 `--root` 之内，挡住 `../` 与编码变体。
 * - 只代理 `/api/` 前缀，别的路径一律当静态资源处理。
 * - 不打印请求体、请求头或查询串：模块地址里可能带令牌，日志只记方法与路径。
 *
 * 用法：
 *   node module-web-server.mjs --root web/dist --port 4110 --api http://127.0.0.1:4100
 */

import fs from 'node:fs';
import http from 'node:http';
import net from 'node:net';
import path from 'node:path';

/*
 * 与框架服务端一致：默认绑所有网卡，容器端口映射与同网段访问才进得来。
 * 只影响产物里模块前端的静态托管；`--api` 仍指回环（模块后端与它同机）。
 */
const DEFAULT_HOST = '0.0.0.0';
const API_PREFIX = '/api/';

const CONTENT_TYPES = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.mjs', 'text/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.map', 'application/json; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.gif', 'image/gif'],
  ['.webp', 'image/webp'],
  ['.ico', 'image/x-icon'],
  ['.woff', 'font/woff'],
  ['.woff2', 'font/woff2'],
  ['.ttf', 'font/ttf'],
  ['.txt', 'text/plain; charset=utf-8'],
  ['.wasm', 'application/wasm'],
]);

function usage() {
  return [
    '用法：node module-web-server.mjs --root <目录> --port <端口> --api <http://host:port> [--host 0.0.0.0]',
    '',
    '  --root  静态文件根目录（通常是 web/dist）',
    '  --port  监听端口',
    '  --api   模块后端基址；/api/* 与 WebSocket 升级都会转发到这里',
    '  --host  监听地址；默认 0.0.0.0（所有网卡），只允许本机访问时传 127.0.0.1',
    '',
  ].join('\n');
}

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function parseArgs(argv) {
  const options = { root: '', port: null, api: '', host: DEFAULT_HOST };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    const takeValue = () => {
      const value = argv[index + 1];
      if (value === undefined || value.startsWith('--')) {
        fail(`${arg} 缺少取值`);
      }
      index += 1;
      return value;
    };

    if (arg === '--help' || arg === '-h') {
      process.stdout.write(usage());
      process.exit(0);
    } else if (arg === '--root') {
      options.root = takeValue();
    } else if (arg === '--port') {
      options.port = Number(takeValue());
    } else if (arg === '--api') {
      options.api = takeValue();
    } else if (arg === '--host') {
      options.host = takeValue();
    } else {
      fail(`未知参数：${arg}\n\n${usage()}`);
    }
  }

  if (options.root === '') {
    fail('缺少 --root');
  }
  if (!Number.isInteger(options.port) || options.port < 1 || options.port > 65_535) {
    fail('--port 必须是 1..65535 的整数');
  }
  if (options.api === '') {
    fail('缺少 --api');
  }

  const root = path.resolve(options.root);
  if (!fs.existsSync(root) || !fs.statSync(root).isDirectory()) {
    fail(`--root 不是目录：${root}`);
  }

  let api;
  try {
    api = new URL(options.api);
  } catch {
    fail(`--api 不是合法 URL：${options.api}`);
  }
  if (api.protocol !== 'http:') {
    // 模块后端在产物里就是本机 HTTP；支持 https 需要额外一套 TLS socket，
    // 而"本地模块走 TLS"没有实际场景，明确拒绝比半支持好。
    fail(`--api 必须是 http://（收到 ${api.protocol}）；本机模块不经过 TLS`);
  }

  return {
    root,
    port: options.port,
    host: options.host,
    api: {
      hostname: api.hostname,
      port: Number(api.port === '' ? 80 : api.port),
      host: api.host,
    },
  };
}

/** 请求路径 → 解码后的 pathname；非法编码返回 null（当作 400）。 */
function requestPathname(rawUrl) {
  try {
    return new URL(rawUrl ?? '/', 'http://localhost').pathname;
  } catch {
    return null;
  }
}

/**
 * 把 URL 路径映射到 `root` 内的绝对路径。
 *
 * `decodeURIComponent` 可能抛（`%E0%A4%A` 这类），并且解码后才出现 `..`。
 * 两道检查都要有：先解码，再 `path.resolve` 后比对前缀。
 *
 * @returns {string|null} 越界或编码非法时返回 null
 */
function resolveStaticPath(root, pathname) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return null;
  }
  if (decoded.includes('\0')) {
    return null;
  }

  const absolute = path.resolve(root, `.${decoded.startsWith('/') ? decoded : `/${decoded}`}`);
  const relative = path.relative(root, absolute);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    return null;
  }
  return absolute;
}

function contentTypeFor(filePath) {
  return CONTENT_TYPES.get(path.extname(filePath).toLowerCase()) ?? 'application/octet-stream';
}

function isFile(filePath) {
  try {
    return fs.statSync(filePath).isFile();
  } catch {
    return false;
  }
}

/** 带扩展名的路径缺文件时返回 404；页面路径才回退到 index.html。 */
function looksLikeAsset(pathname) {
  return path.posix.extname(pathname) !== '';
}

function sendText(response, statusCode, text) {
  const body = Buffer.from(`${text}\n`, 'utf8');
  response.writeHead(statusCode, {
    'content-type': 'text/plain; charset=utf-8',
    'content-length': body.length,
  });
  response.end(body);
}

function sendFile(request, response, filePath, { immutable }) {
  let stat;
  try {
    stat = fs.statSync(filePath);
  } catch {
    sendText(response, 404, 'Not Found');
    return;
  }

  response.writeHead(200, {
    'content-type': contentTypeFor(filePath),
    'content-length': stat.size,
    // 带哈希的构建产物可以长期缓存；index.html 必须每次回源，
    // 否则用户会一直拿到指向旧 bundle 的页面。
    'cache-control': immutable ? 'public, max-age=31536000, immutable' : 'no-cache',
  });

  if (request.method === 'HEAD') {
    response.end();
    return;
  }

  const stream = fs.createReadStream(filePath);
  stream.on('error', () => {
    // 响应头已经发出去了，只能断开；不要把磁盘路径写进响应。
    response.destroy();
  });
  stream.pipe(response);
}

/** 代理用：去掉逐跳头，避免把一条连接的语义带到另一条连接上。 */
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

function forwardHeaders(headers, apiHost) {
  const forwarded = {};
  for (const [key, value] of Object.entries(headers)) {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      forwarded[key] = value;
    }
  }
  forwarded.host = apiHost;
  return forwarded;
}

/**
 * 升级请求用的头：`Connection` 与 `Upgrade` **必须保留**。
 *
 * 普通代理要剥掉逐跳头，但 WebSocket 握手恰恰靠这两个头：剥掉之后上游会
 * 把请求当成普通 GET（实测收到的就是 200 而不是 101）。其余逐跳头照旧去掉。
 */
function upgradeHeaders(headers, apiHost) {
  const forwarded = {};
  for (const [key, value] of Object.entries(headers)) {
    const lower = key.toLowerCase();
    if (lower === 'connection') {
      forwarded.connection = 'Upgrade';
      continue;
    }
    if (lower === 'upgrade') {
      forwarded.upgrade = value;
      continue;
    }
    if (!HOP_BY_HOP.has(lower)) {
      forwarded[key] = value;
    }
  }
  forwarded.host = apiHost;
  return forwarded;
}

function proxyHttp(request, response, api, rawUrl) {
  const upstream = http.request(
    {
      hostname: api.hostname,
      port: api.port,
      path: rawUrl,
      method: request.method,
      headers: forwardHeaders(request.headers, api.host),
    },
    (upstreamResponse) => {
      const headers = { ...upstreamResponse.headers };
      for (const key of Object.keys(headers)) {
        if (HOP_BY_HOP.has(key)) {
          delete headers[key];
        }
      }
      response.writeHead(upstreamResponse.statusCode ?? 502, headers);
      upstreamResponse.pipe(response);
    },
  );

  upstream.on('error', () => {
    if (!response.headersSent) {
      sendText(response, 502, 'Bad Gateway');
    } else {
      response.destroy();
    }
  });

  request.pipe(upstream);
}

/**
 * WebSocket 升级：把原始请求行与头写进上游 socket，然后双向 pipe。
 *
 * 不用 `http.request` 的 upgrade 事件，是因为需要在握手前改 `Host`、并原样
 * 保留 `Sec-WebSocket-*`；直接写字节最不容易丢掉扩展协商。
 */
function proxyUpgrade(request, socket, head, api, rawUrl) {
  const upstream = net.connect(api.port, api.hostname, () => {
    const lines = [`${request.method} ${rawUrl} HTTP/1.1`];
    const headers = upgradeHeaders(request.headers, api.host);
    for (const [key, value] of Object.entries(headers)) {
      for (const item of Array.isArray(value) ? value : [value]) {
        lines.push(`${key}: ${item}`);
      }
    }
    upstream.write(`${lines.join('\r\n')}\r\n\r\n`);
    if (head.length > 0) {
      upstream.write(head);
    }
    upstream.pipe(socket);
    socket.pipe(upstream);
  });

  upstream.setTimeout(30_000, () => upstream.destroy());
  upstream.on('connect', () => upstream.setTimeout(0));
  upstream.on('error', () => socket.destroy());
  socket.on('error', () => upstream.destroy());
  // 一端关闭时把另一端也收掉：只在 error 上挂清理会漏掉"正常关闭"，
  // 结果是一条已断的 WebSocket 在上游留下一个永不释放的 socket。
  socket.on('close', () => upstream.destroy());
  upstream.on('close', () => socket.destroy());
}

function createServer(options) {
  const indexPath = path.join(options.root, 'index.html');

  const server = http.createServer((request, response) => {
    const pathname = requestPathname(request.url);
    if (pathname === null) {
      sendText(response, 400, 'Bad Request');
      return;
    }

    const rawUrl = request.url ?? '/';
    if (pathname === '/api' || pathname.startsWith(API_PREFIX)) {
      proxyHttp(request, response, options.api, rawUrl);
      return;
    }

    if (request.method !== 'GET' && request.method !== 'HEAD') {
      sendText(response, 405, 'Method Not Allowed');
      return;
    }

    const target = resolveStaticPath(options.root, pathname);
    if (target === null) {
      sendText(response, 403, 'Forbidden');
      return;
    }

    if (isFile(target)) {
      // `/assets/index-<hash>.js` 这类带哈希的文件名可以长期缓存。
      sendFile(request, response, target, { immutable: pathname.startsWith('/assets/') });
      return;
    }

    if (isFile(indexPath) && !looksLikeAsset(pathname)) {
      sendFile(request, response, indexPath, { immutable: false });
      return;
    }

    sendText(response, 404, 'Not Found');
  });

  server.on('upgrade', (request, socket, head) => {
    const pathname = requestPathname(request.url);
    if (pathname === null || !(pathname === '/api' || pathname.startsWith(API_PREFIX))) {
      socket.destroy();
      return;
    }
    proxyUpgrade(request, socket, head, options.api, request.url ?? '/');
  });

  return server;
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const server = createServer(options);

  server.on('error', (error) => {
    process.stderr.write(`静态代理服务启动失败：${error.message}\n`);
    process.exit(1);
  });

  server.listen(options.port, options.host, () => {
    // `0.0.0.0` / `::` 是通配监听地址，不是可路由目的地；日志里分开写。
    const wildcard = options.host === '0.0.0.0' || options.host === '::';
    const reachable = wildcard ? '127.0.0.1' : options.host;
    process.stdout.write(
      `模块前端已启动：监听 ${options.host}:${options.port}（本机 http://${reachable}:${options.port}/）→ ${options.api.host}\n`,
    );
    if (wildcard) {
      process.stdout.write(
        '⚠️ 模块前端监听全部地址且无鉴权；仅限可信网络，只需本机访问时传 --host 127.0.0.1\n',
      );
    }
  });

  const shutdown = () => {
    server.close(() => process.exit(0));
    // 连接池里的 WebSocket 不会让 close() 回调触发，给一个短兜底。
    setTimeout(() => process.exit(0), 2_000).unref();
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

main();
