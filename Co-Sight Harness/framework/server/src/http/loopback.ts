/**
 * 回环判定（模块面门禁的第一道检查）。
 *
 * ## 它防的是什么
 *
 * **DNS rebinding**。本地 HTTP 服务的经典攻击面：恶意站点把自己控制的域名解析到
 * `127.0.0.1`，浏览器于是认为它在跟**同源**通信——CORS 完全不介入，`Origin` 头也
 * 没有任何异常。此时唯一露馅的地方就是 `Host`：浏览器发的是攻击者的域名，不是
 * `localhost`。
 *
 * 所以模块面**不能**只靠 CORS 或 `Origin` 判断。真正挡住浏览器的是**令牌**
 * （页面读不到本机文件），`Host` 检查是叠在它上面的纵深防御。
 *
 * ## 这一层依赖 `trustProxy: false`
 *
 * `app.ts` 里 `Fastify({ trustProxy: false })` 决定了 `request.ip` 取的是 **socket
 * 地址**，而不是可以随手伪造的 `X-Forwarded-For`。**如果有人"顺手"打开 trustProxy，
 * 下面的 `isLoopbackAddress` 会静默失效**——攻击者加一个 `X-Forwarded-For: 127.0.0.1`
 * 就绕过去了。改那行之前请先回到这里。
 *
 * `isLoopbackHost` 不受它有影响（`Host` 是客户端直接写的头），所以两道检查要一起用。
 */

/**
 * 从 `Host` 头里取出主机名（丢掉端口，解掉 IPv6 的方括号）。
 *
 * 拿不准就返回 null，调用方据此判为不通过——这里宁可漏判成"拒绝"，
 * 也不能错判成"放行"。
 */
export function hostnameFromHostHeader(raw: string | undefined): string | null {
  if (raw === undefined) {
    return null;
  }
  const host = raw.trim().toLowerCase();
  if (host === '') {
    return null;
  }

  if (host.startsWith('[')) {
    // IPv6 字面量必然带方括号：[::1]:4300 / [::1]
    const end = host.indexOf(']');
    return end === -1 ? null : host.slice(1, end);
  }

  const firstColon = host.indexOf(':');
  if (firstColon === -1) {
    return host;
  }
  // 多于一个冒号 = 没带方括号的 IPv6 字面量，整串都是地址，没有端口可切
  if (host.indexOf(':', firstColon + 1) !== -1) {
    return host;
  }
  return host.slice(0, firstColon);
}

/** `127.0.0.0/8` 整段都是回环，不只是 `127.0.0.1`。 */
function isLoopbackIpv4(value: string): boolean {
  const parts = value.split('.');
  if (parts.length !== 4 || parts[0] !== '127') {
    return false;
  }
  return parts.every((part) => /^\d{1,3}$/.test(part) && Number(part) <= 255);
}

export function isLoopbackHost(rawHost: string | undefined): boolean {
  const hostname = hostnameFromHostHeader(rawHost);
  if (hostname === null) {
    return false;
  }
  if (hostname === 'localhost' || hostname === '::1') {
    return true;
  }
  return isLoopbackIpv4(hostname);
}

/**
 * 判定一个 socket 地址是不是回环。
 *
 * 双栈 socket 上 Node 可能把 IPv4 回环报成 IPv4-mapped 的 `::ffff:127.0.0.1`，
 * 所以要先剥掉那个前缀再判——漏了这一条，本地 IPv4 调用会被误拒。
 */
export function isLoopbackAddress(ip: string | undefined): boolean {
  if (ip === undefined) {
    return false;
  }
  const normalized = ip.trim().toLowerCase();
  if (normalized === '') {
    return false;
  }
  if (normalized === '::1') {
    return true;
  }
  const mapped = normalized.startsWith('::ffff:') ? normalized.slice('::ffff:'.length) : normalized;
  return isLoopbackIpv4(mapped);
}
