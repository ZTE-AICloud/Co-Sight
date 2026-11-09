/**
 * 启动前的端口试绑，以及 `superviseAll` 的收尾语义。
 *
 * 只碰回环地址与临时端口，不依赖本机是否已经有服务在跑；子进程用 `node -e`
 * 起一个空转循环，测完一律回收。
 */

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import net from 'node:net';
import { Writable } from 'node:stream';
import { describe, it } from 'node:test';

import { checkTcpBind, forwardVerbatim, superviseAll } from '../lib/runtime.mjs';

/** 先拿一个空闲端口，然后立刻释放，交给被测函数去试绑。 */
function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

describe('checkTcpBind', () => {
  it('空闲端口可以绑定', async () => {
    const port = await freePort();
    const result = await checkTcpBind('127.0.0.1', port);
    assert.equal(result.ok, true, result.detail);
  });

  it('被占用的端口明确说是被占用', async () => {
    const server = net.createServer();
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const { port } = server.address();

    try {
      const result = await checkTcpBind('127.0.0.1', port);
      assert.equal(result.ok, false);
      assert.match(result.detail, /端口已被占用/);
    } finally {
      await new Promise((resolve) => server.close(resolve));
    }
  });

  it('不可用的地址不会挂住', async () => {
    // TEST-NET-3 地址，本机不持有；listen 会以 EADDRNOTAVAIL 失败。
    const result = await checkTcpBind('203.0.113.1', 1, { timeoutMs: 2000 });
    assert.equal(result.ok, false);
    assert.notEqual(result.detail, null);
  });
});

describe('forwardVerbatim', () => {
  it('原样转发子进程的 stdout / stderr：不加前缀、不拆行、不改行尾', async () => {
    // 回归：Windows 真终端里 detached 子进程继承 stdio 会 EBADF（退出码 1、零输出），
    // 所以框架服务改走管道，靠这个函数把日志原样转回去。转发一旦加了前缀、或者把
    // \r 吃掉，用户看到的就不再是服务端自己打的那份日志。
    // 转发目标是可注入的：替换 `process.stdout.write` 会把测试报告自己也吞进去。
    const captured = { stdout: '', stderr: '' };
    const sink = (name) => {
      const stream = new Writable({
        write(chunk, _encoding, callback) {
          captured[name] += chunk.toString();
          callback();
        },
      });
      return stream;
    };
    const targets = { stdout: sink('stdout'), stderr: sink('stderr') };

    const child = spawn(
      process.execPath,
      ['-e', "process.stdout.write('out-1\\r\\n'); process.stderr.write('err-1\\n')"],
      { detached: true, stdio: ['ignore', 'pipe', 'pipe'] },
    );
    const stop = forwardVerbatim(child, targets);
    // 'close' 比 'exit' 晚：它保证管道里的数据已经派发完，不用猜多久才够。
    const code = await new Promise((resolve) => child.once('close', resolve));
    stop();

    assert.equal(code, 0);
    assert.equal(captured.stdout, 'out-1\r\n');
    assert.equal(captured.stderr, 'err-1\n');
  });
});

/** 一个什么都不做、只占着进程组的子进程，用来观察信号。 */
function spawnSleeper() {
  return spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], {
    detached: true,
    stdio: 'ignore',
  });
}

function waitExit(child, timeoutMs) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve(child.signalCode ?? child.exitCode);
      return;
    }
    const timer = setTimeout(() => resolve('timeout'), timeoutMs);
    child.once('exit', (code, signal) => {
      clearTimeout(timer);
      resolve(signal ?? code);
    });
  });
}

describe('superviseAll', () => {
  it('收尾开始后新登记的子进程仍会被 exit 兜底回收', async () => {
    // 回归：冒烟在框架就绪后立刻发 SIGINT，延迟模块的 web 代理正好在
    // stopAll 的快照之后 spawn，曾经因为 onExit 提前返回而变成孤儿。
    const entries = [];
    const before = new Set(process.listeners('exit'));
    const supervision = superviseAll(entries, { graceMs: 2000, onAllStopped: () => {} });
    const exitListeners = process.listeners('exit').filter((listener) => !before.has(listener));
    assert.equal(exitListeners.length, 1, '退出兜底应当正好注册一次');

    const early = spawnSleeper();
    entries.push({ label: '早起的', child: early });
    assert.equal(supervision.isStopping(), false);

    try {
      await supervision.stopAll(0);
      assert.equal(supervision.isStopping(), true);

      // 快照之后才出现的进程：stopAll 已经不认它，只有 exit 兜底能收。
      const late = spawnSleeper();
      entries.push({ label: '后起的', child: late });

      // 直接跑已注册的 exit 回调，等价于进程马上 exit（不能在测试里真退出）。
      exitListeners[0](0);

      assert.equal(await waitExit(late, 3000), 'SIGKILL');
    } finally {
      supervision.dispose();
      for (const entry of entries) {
        try {
          process.kill(-entry.child.pid, 'SIGKILL');
        } catch {
          // 已经退出了。
        }
      }
    }
  });

  it('重复 stopAll 只走一次收尾，dispose 摘掉退出兜底', async () => {
    const before = process.listeners('exit').length;
    const entries = [];
    let calls = 0;
    const supervision = superviseAll(entries, {
      graceMs: 1000,
      onAllStopped: () => {
        calls += 1;
      },
    });
    assert.equal(process.listeners('exit').length, before + 1);

    try {
      await supervision.stopAll(0);
      await supervision.stopAll(0);
      assert.equal(calls, 1);
    } finally {
      supervision.dispose();
    }
    // 兜底必须能被摘掉：否则同一进程里连开两次监督（真实场景是重跑编排）
    // 会积累回调，互相给对方的子进程发信号。
    assert.equal(process.listeners('exit').length, before);
  });
});
