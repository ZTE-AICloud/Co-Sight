/**
 * 启动脚本与冒烟脚本共用的进程 / HTTP 工具。
 *
 * 单独成文件的原因：这两件事（等端口就绪、按信号干净退出）是"能跑通"和
 * "跑得干净"的分界线，两边逻辑必须一致，否则会出现"启动脚本能收 Ctrl-C、
 * 冒烟脚本却留下孤儿进程"这种只影响机器的差别。
 */

import net from 'node:net';

/** 默认探活间隔。取 250ms：本机启动通常在 1 秒内完成，再密只是浪费 CPU。 */
const DEFAULT_INTERVAL_MS = 250;

/**
 * 试绑一次端口，判断 `host:port` 现在能不能监听。
 *
 * 为什么不在 `spawn` 之后等子进程报错：服务端绑不上会打印一大段栈，而真正
 * 要告诉用户的只有一句"端口被占了"。先试绑一次，失败时能直接给出地址与处理办法。
 *
 * 有竞态（试绑成功后释放，真正启动前别人可能占上），这里只用来把**大概率**
 * 的失败提前说清楚；真正的失败仍由子进程退出兜底。
 *
 * @param {string} host
 * @param {number} port
 * @param {{timeoutMs?: number}} [options]
 * @returns {Promise<{ok: boolean, detail: string|null}>}
 */
export function checkTcpBind(host, port, options = {}) {
  const timeoutMs = options.timeoutMs ?? 1000;
  return new Promise((resolve) => {
    const server = net.createServer();
    let settled = false;
    let timer = null;

    const finish = (result) => {
      if (settled) {
        return;
      }
      settled = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
      resolve(result);
    };

    timer = setTimeout(() => {
      server.close();
      finish({ ok: false, detail: `${Math.round(timeoutMs / 1000)}s 内未能绑定` });
    }, timeoutMs);

    server.once('error', (error) => {
      finish({
        ok: false,
        detail:
          error.code === 'EADDRINUSE'
            ? '端口已被占用'
            : `${error.code ?? '错误'}：${error.message}`,
      });
    });

    server.listen({ host, port, exclusive: true }, () => {
      server.close(() => finish({ ok: true, detail: null }));
    });
  });
}

/**
 * 带超时的 HTTP GET。
 *
 * 用 AbortSignal.timeout 而不是自己包一层 Promise.race：前者会真正取消底层
 * 连接，后者只是"不再等"，被遗弃的 socket 仍会挂着。
 *
 * 返回 content-type：冒烟检查要区分"拿到前端 HTML"和"拿到 API 的 JSON"，
 * 只比对正文内容的话，一个恰好返回 HTML 片段的错误页也会被判成通过。
 *
 * @returns {Promise<{ok: boolean, status: number, contentType: string, body: string, error: string|null}>}
 */
export async function httpGet(url, timeoutMs = 3000) {
  try {
    const response = await fetch(url, {
      signal: AbortSignal.timeout(timeoutMs),
      redirect: 'manual',
      headers: { accept: '*/*' },
    });
    const body = await response.text();
    return {
      ok: response.ok,
      status: response.status,
      contentType: response.headers.get('content-type') ?? '',
      body,
      error: null,
    };
  } catch (error) {
    return { ok: false, status: 0, contentType: '', body: '', error: describeError(error) };
  }
}

export function describeError(error) {
  if (error instanceof Error) {
    // undici 把网络失败包在 cause 里，直接取 message 会得到无信息量的
    // "fetch failed"。这里展开一层，让输出里能看到 ECONNREFUSED 之类的原因。
    const cause = /** @type {any} */ (error).cause;
    const detail = cause instanceof Error ? (cause.code ?? cause.message) : null;
    return detail ? `${error.message} (${detail})` : error.message;
  }
  return String(error);
}

/**
 * 轮询直到探活返回 2xx。
 * @returns {Promise<{ready: boolean, attempts: number, lastError: string|null}>}
 */
export async function waitForHttpOk(url, options = {}) {
  const timeoutMs = options.timeoutMs ?? 30_000;
  const intervalMs = options.intervalMs ?? DEFAULT_INTERVAL_MS;
  const deadline = Date.now() + timeoutMs;
  let attempts = 0;
  let lastError = null;

  while (Date.now() < deadline) {
    attempts += 1;
    const result = await httpGet(url, Math.min(3000, Math.max(500, deadline - Date.now())));
    if (result.ok) {
      return { ready: true, attempts, lastError: null };
    }
    lastError = result.error ?? `HTTP ${result.status}`;
    await sleep(intervalMs);
  }

  return { ready: false, attempts, lastError };
}

/**
 * 轮询直到**任意一个**候选地址探活返回 2xx。
 *
 * 为什么要多个候选：本机 vite 在 `server.host` 未设置时只绑 IPv6 回环 `[::1]`，
 * 这时 `http://127.0.0.1:4310` 是连接被拒、`http://localhost:4310` 才通（浏览器两个都试，
 * 所以人肉访问没问题，只有探活脚本会被骗）。只探 127.0.0.1 会把"其实已经起来了"
 * 报成超时——这是实测踩到的，不是理论风险。
 *
 * @param {readonly string[]} urls 候选地址，每轮按顺序各试一次
 * @returns {Promise<{ready: boolean, attempts: number, url: string|null, lastError: string|null}>}
 */
export async function waitForAnyHttpOk(urls, options = {}) {
  const timeoutMs = options.timeoutMs ?? 30_000;
  const intervalMs = options.intervalMs ?? DEFAULT_INTERVAL_MS;
  const deadline = Date.now() + timeoutMs;
  let attempts = 0;
  let lastError = null;

  while (Date.now() < deadline) {
    // 调用方可以给一个"别再等了"的判据。启动脚本用它处理**启动即退出**的模块：
    // 干等一分钟既慢，又会把"进程已经没了"说成"未就绪"。
    if (options.shouldStop?.() === true) {
      return { ready: false, attempts, url: null, stopped: true, lastError };
    }
    attempts += 1;
    for (const url of urls) {
      // 单次请求也压在同一个 deadline 内：候选变多时不该把总等待时间乘以候选数。
      const perRequest = Math.min(3000, Math.max(500, deadline - Date.now()));
      const result = await httpGet(url, perRequest);
      if (result.ok) {
        return { ready: true, attempts, url, stopped: false, lastError: null };
      }
      lastError = result.error ?? `HTTP ${result.status}`;
    }
    await sleep(intervalMs);
  }

  return { ready: false, attempts, url: null, stopped: false, lastError };
}

export function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

/**
 * 逐行给子进程输出加 `[标签]` 前缀后转发。
 *
 * 不用 `stdio: 'inherit'`：总编排脚本同时管五个进程，继承 stdio 会让五路日志互相穿插，
 * 分不清哪行是谁的。`width` 传最长标签的长度即可对齐，终端里能竖着扫。
 *
 * @param {{stdout: import('node:stream').Readable|null, stderr: import('node:stream').Readable|null}} child
 * @param {{label: string, width?: number}} options
 * @returns {() => void} 停止转发
 */
export function pumpPrefixed(child, options) {
  const { label } = options;
  const width = options.width ?? label.length;
  const prefix = `[${label}]${' '.repeat(Math.max(1, width - label.length + 1))}`;

  const disposers = [];

  for (const [stream, out] of [
    [child.stdout, process.stdout],
    [child.stderr, process.stderr],
  ]) {
    if (!stream) {
      continue;
    }
    let pending = '';
    const flush = (line) => {
      // 去掉行尾 \r：子进程在伪终端下会输出 \r\n，转发后会多出一个回车符。
      out.write(`${prefix}${line.replace(/\r$/, '')}\n`);
    };
    const onData = (chunk) => {
      pending += chunk;
      let index = pending.indexOf('\n');
      while (index !== -1) {
        flush(pending.slice(0, index));
        pending = pending.slice(index + 1);
        index = pending.indexOf('\n');
      }
    };
    const onEnd = () => {
      if (pending.length > 0) {
        flush(pending);
      }
      pending = '';
    };

    stream.setEncoding('utf8');
    stream.on('data', onData);
    stream.on('end', onEnd);
    disposers.push(() => {
      stream.off('data', onData);
      stream.off('end', onEnd);
    });
  }

  return () => {
    for (const dispose of disposers) {
      dispose();
    }
  };
}

/**
 * 把子进程的 stdout / stderr **原样**转发到当前进程的同名流（不加前缀、不拆行）。
 *
 * 看起来与 `stdio: 'inherit'` 等价，但在 Windows 上不等价：`detached: true` 的子进程
 * 继承了父进程所在**控制台**的句柄，而它已经不在那个控制台会话里，第一次写日志就
 * `EBADF`——Node 把它当成未捕获的 'error' 事件，进程随即以退出码 1 结束，**一个字都
 * 打不出来**。现象是"服务进程在就绪前退出，日志见上方，而上方什么都没有"。
 *
 * 控制台句柄只在**真终端**里出问题：冒烟与 CI 的 stdio 本来就是管道，所以这条在
 * 自动化里完全看不出来，只能靠"用户双击 start.cmd"暴露。改走管道再转发就没有句柄继承
 * 这一步（模块服务一直这么干）。
 *
 * `pumpPrefixed` 与它的区别只有一个：那个要按行加 `[标签]` 才能分清五路日志。
 *
 * @param {{stdout: import('node:stream').Readable|null, stderr: import('node:stream').Readable|null}} child
 * @param {{stdout?: import('node:stream').Writable, stderr?: import('node:stream').Writable}} [targets]
 *   转发目标，默认当前进程的同名流；测试用它观察转发的字节，不想去替换 `process.stdout`。
 * @returns {() => void} 停止转发
 */
export function forwardVerbatim(child, targets = {}) {
  const disposers = [];

  for (const [stream, out] of [
    [child.stdout, targets.stdout ?? process.stdout],
    [child.stderr, targets.stderr ?? process.stderr],
  ]) {
    if (!stream) {
      continue;
    }
    // 不 setEncoding、不按行切：字节原样过去，\r\n、ANSI 颜色、进度条都保持原样。
    stream.pipe(out, { end: false });
    disposers.push(() => {
      stream.unpipe(out);
    });
  }

  return () => {
    for (const dispose of disposers) {
      dispose();
    }
  };
}

/**
 * 把父进程收到的终止信号转发给子进程，并在子进程退出后以同样的退出码结束自己。
 *
 * 这段逻辑必须在两个脚本里表现一致，否则会出现"Ctrl-C 之后服务还活着"——
 * 用户以为停了、端口却被占着，下一次启动直接失败。
 *
 * @returns {{dispose: () => void}}
 */
export function supervise(child, options = {}) {
  const label = options.label ?? '子进程';
  let terminating = false;

  const signals = ['SIGINT', 'SIGTERM'];
  const handlers = new Map();

  for (const signal of signals) {
    const handler = () => {
      if (terminating) {
        // 第二次 Ctrl-C 说明子进程没在配合退出，此时再等就是卡住用户。
        process.stderr.write(`\n[${label}] 再次收到 ${signal}，强制退出\n`);
        child.kill('SIGKILL');
        return;
      }
      terminating = true;
      process.stderr.write(`\n[${label}] 收到 ${signal}，正在转发给服务进程…\n`);
      child.kill(signal);
    };
    handlers.set(signal, handler);
    process.on(signal, handler);
  }

  return {
    dispose() {
      for (const [signal, handler] of handlers) {
        process.off(signal, handler);
      }
    },
  };
}

/**
 * 子进程是否还活着。
 *
 * `exitCode === null && signalCode === null` 是 Node 在 'exit' 事件**之前**的状态：
 * 此时进程可能已经死了但事件还没派发。这类"半死"状态不能当成活着，否则 `stopAll`
 * 会对着一个已经退出的句柄等满整个宽限期——Ctrl-C 之后卡十秒，看着像脚本挂了。
 *
 * @param {import('node:child_process').ChildProcess} child
 */
function isAlive(child) {
  return child.exitCode === null && child.signalCode === null;
}

/**
 * 给整个进程组发信号，进程组不在了就退回单进程。
 *
 * 这里**刻意不判断直接子进程是否还活着**：直接子进程是 `pnpm` / `npm`，
 * 它退出不等于它的孙进程（真正占端口的 vite / tsx watch）退出。对着一个已死的
 * pid 发组信号只会得到 ESRCH 并被这里吞掉，而漏发则等于放出孤儿。
 *
 * @param {import('node:child_process').ChildProcess} child
 * @param {NodeJS.Signals} signal
 */
function signalGroup(child, signal) {
  if (child.pid === undefined) {
    return;
  }
  try {
    // 负 PID 表示"整个进程组"。以 detached 启动的进程是组长，组 ID 就等于它的 PID。
    process.kill(-child.pid, signal);
  } catch {
    // 进程组已经不在了（或平台不支持负 PID）就退回单进程；这里再抛只会盖住真正的错误。
    try {
      child.kill(signal);
    } catch {
      // 已经退出了。
    }
  }
}

/**
 * 同时监督多个子进程，把终止信号变成**一次有序收尾**。
 *
 * `supervise()` 管一个子进程，够 `start.mjs` 用；总编排脚本要管五个，额外需要两件事：
 *
 *  1. **逆序停止**——后起的先停（模块先于宿主）。正序停会让下游先死，上游刷一屏
 *     "连接被拒"，看着像启动脚本自己出错了。
 *  2. **按进程组回收**——子进程以 `detached: true` 启动、自成进程组。只 kill 直接子进程
 *     会留下 vite / tsx watch 的孙进程继续占着端口，下一次启动直接失败。这是这套机制里
 *     最容易写错、也最烦人的一处，所以验证里专门有一条"Ctrl-C 之后端口一个不剩"。
 *
 * @param {Array<{label: string, child: import('node:child_process').ChildProcess}>} entries 按**启动顺序**给
 * @param {{graceMs?: number, onAllStopped?: (code: number) => void}} options
 * @returns {{stopAll: (code?: number) => Promise<void>, dispose: () => void}}
 */
export function superviseAll(entries, options = {}) {
  const graceMs = options.graceMs ?? 10_000;
  const onAllStopped = options.onAllStopped ?? ((code) => process.exit(code));

  let stopping = false;

  const waitForExit = async (deadline) => {
    while (Date.now() < deadline && entries.some((entry) => isAlive(entry.child))) {
      await sleep(100);
    }
  };

  const stopAll = async (code = 0) => {
    if (stopping) {
      return;
    }
    stopping = true;

    const started = entries.filter((entry) => isAlive(entry.child)).toReversed();
    if (started.length > 0) {
      process.stdout.write(`\n正在按逆序停止 ${started.length} 个服务…\n`);
      for (const entry of started) {
        process.stdout.write(`  停止 ${entry.label}\n`);
        signalGroup(entry.child, 'SIGTERM');
      }

      const deadline = Date.now() + graceMs;
      await waitForExit(deadline);

      // 强制阶段对**每一个**条目发组信号，不再按"直接子进程是否还活着"过滤：
      // 孙进程比直接子进程活得久是常态，漏掉它端口就一直被占着。
      // 对着已消失的进程组发信号会抛 ESRCH，已被 signalGroup 吞掉，没有副作用。
      for (const entry of started) {
        if (isAlive(entry.child)) {
          process.stdout.write(`  ${entry.label} 未在 ${Math.round(graceMs / 1000)}s 内退出，强制结束\n`);
        }
        signalGroup(entry.child, 'SIGKILL');
      }
      await waitForExit(Date.now() + 2000);

      process.stdout.write('全部已停止。\n');
    }

    // 一个服务都没起来时（例如端口预检就失败了）不打印"已停止"——那会让人以为
    // 已经有一批服务在跑然后被停了。
    onAllStopped(code);
  };

  const handlers = new Map();

  for (const signal of ['SIGINT', 'SIGTERM']) {
    const handler = () => {
      if (stopping) {
        // 第二次说明有人在宽限期内等不及了，此时再等就是卡住用户。
        process.stderr.write(`\n再次收到 ${signal}，强制退出\n`);
        for (const entry of entries) {
          signalGroup(entry.child, 'SIGKILL');
        }
        process.exit(130);
      }
      process.stderr.write(`\n收到 ${signal}，正在收尾…\n`);
      void stopAll(0);
    };
    handlers.set(signal, handler);
    process.on(signal, handler);
  }

  // 兜底：任何走到 process.exit 的路径（未捕获异常、致命错误分支）都不能留下孤儿。
  // 这里只能用同步操作——'exit' 回调里做不了异步等待。
  //
  // 即使 `stopping` 为真也要扫一遍：`stopAll` 开始时对 entries 做了快照，而启动流程
  // 可能在那之后又拉起了新的服务（实测：冒烟在框架就绪后立刻发 SIGINT，延迟模块的
  // web 代理正好在快照之后 spawn，于是成了孤儿）。entries 是实时数组，这里能看到它。
  // 对已经退出的进程组发信号只会得到 ESRCH，已被 signalGroup 吞掉。
  const onExit = () => {
    for (const entry of entries) {
      signalGroup(entry.child, 'SIGKILL');
    }
  };
  process.on('exit', onExit);

  return {
    stopAll,
    // 供启动流程在 spawn 之前判断是否已经在收尾：收尾期间再起新服务，
    // 它不会被 stopAll 的快照覆盖，只会白起一次再被 exit 兜底杀掉。
    isStopping: () => stopping,
    dispose() {
      for (const [signal, handler] of handlers) {
        process.off(signal, handler);
      }
      process.off('exit', onExit);
    },
  };
}
