import { after, test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, type ChildProcess } from 'node:child_process';
import { connect, createServer, type AddressInfo, type Socket } from 'node:net';
import { fileURLToPath } from 'node:url';
import { prepareTestEnv } from './helpers/test-db.js';

// Windows 无 POSIX 信号投递语义（kill 直接终止进程），本文件整体跳过
const isWindows = process.platform === 'win32';
const serverDir = fileURLToPath(new URL('..', import.meta.url));
/** 退出判定窗口：兜底超时是 10s，优雅路径应在秒级完成，5s 足够区分「挂住」与「正常退出」 */
const EXIT_WINDOW_MS = 5_000;

const env = prepareTestEnv('shutdown');

const children: ChildProcess[] = [];

interface ServerChild {
  proc: ChildProcess;
  log: () => string;
  waitExit: Promise<number | null>;
}

const delay = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

const base = (port: number): string => `http://127.0.0.1:${port}`;

async function freePort(): Promise<number> {
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, '127.0.0.1', resolve));
  const port = (probe.address() as AddressInfo).port;
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  return port;
}

/** 起真服务子进程：tsx 直跑 src/index.ts，环境与集成测试一致，只换端口。 */
async function startServer(port: number): Promise<ServerChild> {
  const proc = spawn(process.execPath, ['--import', 'tsx', 'src/index.ts'], {
    cwd: serverDir,
    env: { ...process.env, COSIGHT_HOME: env.home, ENGINE: 'fake', PORT: String(port) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  children.push(proc);
  let log = '';
  const collect = (chunk: Buffer): void => {
    log += chunk.toString();
  };
  proc.stdout!.on('data', collect);
  proc.stderr!.on('data', collect);
  const waitExit = new Promise<number | null>((resolve) => proc.once('exit', (code) => resolve(code)));

  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) throw new Error(`服务子进程提前退出（${proc.exitCode}）：${log}`);
    const ready = await fetch(`${base(port)}/api/smart-factory/v1/health`)
      .then((response) => response.ok)
      .catch(() => false);
    if (ready) return { proc, log: () => log, waitExit };
    await delay(150);
  }
  proc.kill('SIGKILL');
  throw new Error(`服务未在 30s 内就绪：${log}`);
}

/** 等退出；窗口内没退就强杀并断言失败，不留孤儿进程。 */
async function exitWithin(child: ServerChild, windowMs: number): Promise<number | null> {
  const outcome = await Promise.race([child.waitExit, delay(windowMs).then(() => 'timeout' as const)]);
  if (outcome === 'timeout') {
    child.proc.kill('SIGKILL');
    throw new Error(`进程未在 ${windowMs}ms 内退出：${child.log()}`);
  }
  return outcome;
}

/** 挂一条在途连接：请求头写全、请求体只写一半，服务端会一直等剩余 body。 */
function holdInFlightConnection(port: number): Socket {
  const socket = connect(port, '127.0.0.1');
  socket.on('error', () => {
    /* 服务端强断时会 ECONNRESET，属预期 */
  });
  socket.write(
    'POST /api/smart-factory/v1/health HTTP/1.1\r\n' +
      `Host: 127.0.0.1:${port}\r\n` +
      'Content-Type: application/json\r\n' +
      'Content-Length: 100000\r\n' +
      '\r\n' +
      '{"half":',
  );
  return socket;
}

after(async () => {
  for (const proc of children) {
    if (proc.exitCode === null && proc.signalCode === null) proc.kill('SIGKILL');
  }
});

test('SIGTERM：在途连接挂住时也限时退出', { skip: isWindows }, async () => {
  const port = await freePort();
  const child = await startServer(port);
  const socket = holdInFlightConnection(port);
  try {
    await delay(200);
    child.proc.kill('SIGTERM');
    const code = await exitWithin(child, EXIT_WINDOW_MS);
    assert.equal(code, 0, `优雅退出应返回 0：${child.log()}`);
  } finally {
    socket.destroy();
    child.proc.kill('SIGKILL');
  }
});

// 同种标准信号在毫秒级连发可能被内核合并成一次投递，故用 SIGTERM + SIGINT 验证「再次收到信号立即强退」
test('再次收到信号：立即强退（非零码，不等收口）', { skip: isWindows }, async () => {
  const port = await freePort();
  const child = await startServer(port);
  const socket = holdInFlightConnection(port);
  try {
    await delay(200);
    child.proc.kill('SIGTERM');
    child.proc.kill('SIGINT');
    const code = await exitWithin(child, EXIT_WINDOW_MS);
    assert.equal(code, 1, `再次收到信号应立即以非零码退出：${child.log()}`);
  } finally {
    socket.destroy();
    child.proc.kill('SIGKILL');
  }
});
