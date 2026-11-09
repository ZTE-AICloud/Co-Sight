#!/usr/bin/env node
/**
 * Smart Factory 开发脚本（Node 单入口，零依赖、跨平台）：
 *
 *   node scripts/dev.mjs setup    首次：装依赖、生成 server/.env、prisma generate、建数据目录与库
 *   node scripts/dev.mjs start    后台启动前后端，返回后服务继续运行（日志 .run/logs/）
 *   node scripts/dev.mjs stop     停止由 start 后台拉起的前后端
 *   node scripts/dev.mjs restart  先停后起（stop + start）
 *   node scripts/dev.mjs status   查看前后端运行状态与端口可达性
 *   node scripts/dev.mjs e2e      临时起一个后端（独立数据目录）跑 tests/e2e/session-flow.mjs
 */
import { spawn, spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, openSync, closeSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { connect } from 'node:net';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = dirname(dirname(fileURLToPath(import.meta.url)));
const serverDir = join(rootDir, 'server');
const webDir = join(rootDir, 'web');
const runDir = join(rootDir, '.run');
const logDir = join(runDir, 'logs');
const dbScript = join(serverDir, 'scripts', 'db.mjs');

// 端口：优先读 SMART_FACTORY_*，否则用默认值。显式设置 SMART_FACTORY_SERVER_PORT 时透传 PORT 给后端，
// 保证「脚本端口」与「实际监听端口」一致（web/vite.config.ts 同样读这两个变量，proxy 目标随之对齐）。
const serverPort = process.env.SMART_FACTORY_SERVER_PORT ?? '4100';
const webPort = process.env.SMART_FACTORY_WEB_PORT ?? '4110';
const serverUrl = `http://127.0.0.1:${serverPort}`;
const webUrl = `http://127.0.0.1:${webPort}`;
// 探活路径：必须与 server/src/app.ts 的 API_PREFIX 一致，改前缀时两处同批改。
const healthPath = '/api/smart-factory/v1/health';
const wsPath = '/api/smart-factory/v1/ws';

const color = (code) => (process.stdout.isTTY ? `\x1b[${code}m` : '');
const reset = process.stdout.isTTY ? '\x1b[0m' : '';
const logInfo = (message) => console.log(`${color(36)}[smart-factory]${reset} ${message}`);
const logWarn = (message) => console.error(`${color(33)}[smart-factory]${reset} ${message}`);
const logError = (message) => console.error(`${color(31)}[smart-factory]${reset} ${message}`);

/** 终止执行：错误信息已打（进 stderr），由顶层统一收口退出码 1，不用 process.exit 以免截断已缓冲的输出。 */
function die(message) {
  logError(message);
  const error = new Error(message);
  error.handled = true;
  throw error;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---- 平台原语：平台差异只允许出现在这三个函数里 ----

/** 起工具子进程。Windows 上 npm 是 npm.cmd，不经 shell 找不到；POSIX 一律数组直起，无 shell 解析。 */
function spawnTool(cmd, args, options = {}) {
  const shell = process.platform === 'win32' && cmd === 'npm';
  return spawn(cmd, args, { ...options, shell });
}

/** 结束进程树。Windows 用 taskkill 打整棵树；POSIX 杀整个进程组（负 pid），TERM 宽限后 KILL 兜底。 */
async function killTree(pid) {
  if (!isAlive(pid)) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
    return;
  }
  try {
    process.kill(-pid, 'SIGTERM');
  } catch {
    try { process.kill(pid, 'SIGTERM'); } catch { /* 已退出 */ }
  }
  for (let waited = 0; waited < 10_000 && isAlive(pid); waited += 200) await sleep(200);
  if (isAlive(pid)) {
    logWarn(`进程 ${pid} 未在 10s 内退出，强制结束`);
    try {
      process.kill(-pid, 'SIGKILL');
    } catch {
      try { process.kill(pid, 'SIGKILL'); } catch { /* 已退出 */ }
    }
  }
}

/** 进程是否存活。EPERM 说明进程在但没权限发信号，仍算活。 */
function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

// ---- 工具进程与后台服务 ----

/** 前台跑工具进程并等退出，返回退出码。 */
function runTool(cmd, args, { cwd, env } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawnTool(cmd, args, { cwd, env, stdio: 'inherit' });
    child.on('error', (error) => {
      reject(error.code === 'ENOENT' ? new Error(`未找到命令 ${cmd}，请先安装 Node.js >= 20（含 npm）`) : error);
    });
    child.on('exit', (code) => resolve(code ?? 1));
  });
}

/** 跑工具进程，非零退出即终止脚本。 */
async function mustRun(cmd, args, options) {
  const code = await runTool(cmd, args, options);
  if (code !== 0) die(`命令失败（退出码 ${code}）：${cmd} ${args.join(' ')}`);
}

/** 后台起一个进程：日志重定向用文件 fd（不靠 shell 重定向），detached 使其在父进程退出后继续运行。 */
function spawnBackground(cmd, args, { cwd, env, logPath, label }) {
  mkdirSync(dirname(logPath), { recursive: true });
  const fd = openSync(logPath, 'w');
  const child = spawnTool(cmd, args, { cwd, env, detached: true, stdio: ['ignore', fd, fd] });
  closeSync(fd);
  child.on('error', () => {}); // 起不来的情况统一走下面的 pid 检查，这里只兜住 error 事件避免裸奔
  if (child.pid === undefined) die(`启动 ${label} 失败（命令不存在？）：${cmd} ${args.join(' ')}`);
  child.unref();
  return child;
}

/** 读 pidfile（JSON：pid/cmd/startedAt）；文件缺失、内容坏或进程已死都返回 null，顺手清掉死文件。 */
function readPid(pidPath) {
  if (!existsSync(pidPath)) return null;
  let record;
  try {
    record = JSON.parse(readFileSync(pidPath, 'utf8'));
  } catch {
    rmSync(pidPath, { force: true });
    return null;
  }
  if (Number.isInteger(record.pid) && isAlive(record.pid)) return record;
  rmSync(pidPath, { force: true });
  return null;
}

/** 后台启动一个服务并写 pidfile；已在运行则跳过。 */
function startDetached(name, cmd, args, { cwd, env }) {
  const pidPath = join(runDir, `${name}.pid`);
  const record = readPid(pidPath);
  if (record) {
    logWarn(`${name} 已在运行（pid ${record.pid}），跳过启动`);
    return;
  }
  const logPath = join(logDir, `${name}.log`);
  const child = spawnBackground(cmd, args, { cwd, env, logPath, label: name });
  writeFileSync(pidPath, `${JSON.stringify({ pid: child.pid, cmd: `${cmd} ${args.join(' ')}`, startedAt: new Date().toISOString() })}\n`);
  logInfo(`${name} 已启动（pid ${child.pid}）→ 日志：${logPath}`);
}

/** 停止一个后台服务：先 TERM 整组，宽限后 KILL 兜底，清 pidfile。 */
async function stopDetached(name) {
  const pidPath = join(runDir, `${name}.pid`);
  const record = readPid(pidPath);
  if (!record) {
    logInfo(`${name} 未在运行`);
    return;
  }
  await killTree(record.pid);
  rmSync(pidPath, { force: true });
  logInfo(`${name} 已停止`);
}

// ---- 探活 ----

/** 探活候选地址：服务可能只绑到 ::1（如 vite 默认的 localhost），只探 127.0.0.1 会误报不可达；反之 localhost 又可能被代理截走，两种写法都试。 */
function probeCandidates(url) {
  if (url.includes('127.0.0.1')) return [url, url.replace('127.0.0.1', 'localhost')];
  if (url.includes('localhost')) return [url, url.replace('localhost', '127.0.0.1')];
  return [url];
}

/** 探一个 URL，返回可达的候选地址；都不可达返回 null。 */
async function probe(url) {
  for (const candidate of probeCandidates(url)) {
    try {
      const response = await fetch(candidate, { signal: AbortSignal.timeout(2000) });
      if (response.ok) return candidate;
    } catch {
      // 不可达，试下一个候选
    }
  }
  return null;
}

/** 试连单个地址，端口有监听者即返回 true。 */
function canConnect(host, port) {
  return new Promise((resolve) => {
    const socket = connect({ port: Number(port), host });
    const done = (result) => {
      socket.destroy();
      resolve(result);
    };
    socket.once('connect', () => done(true));
    socket.once('error', () => done(false));
    socket.setTimeout(1000, () => done(false));
  });
}

/**
 * 端口是否已有监听者：只做 TCP 连接，不看 HTTP 响应。
 *
 * 探活成功不代表「我们刚拉起的进程在服务」——旧进程同样能回 200。
 * 两种地址都试：服务可能只绑 127.0.0.1，也可能只绑 ::1（vite 默认 localhost）。
 */
async function portInUse(port) {
  for (const host of ['127.0.0.1', '::1']) {
    if (await canConnect(host, port)) return true;
  }
  return false;
}

/**
 * 拉起前确认端口归本脚本所有。
 *
 * pidfile 之外的进程（手工启动、旧会话遗留）占着端口时，新子进程会 EADDRINUSE 退出，
 * 而下面的探活会命中旧进程，`start` 看起来成功、实际跑的还是旧代码。
 */
async function assertPortFree(name, port) {
  if (readPid(join(runDir, `${name}.pid`))) return; // 本脚本拉起的：startDetached 会跳过
  if (!(await portInUse(port))) return;
  die(`端口 ${port} 已被占用，且占用者不是本脚本启动的（没有对应 pidfile）。先停止它（Linux：ss -ltnp 'sport = :${port}' 查 pid）再 start，否则新进程会 EADDRINUSE，旧代码继续服务`);
}

/** 等 HTTP 就绪，返回是否就绪。 */
async function waitForHttp(url, name, timeoutSec = 30, intervalMs = 1000) {
  const deadline = Date.now() + timeoutSec * 1000;
  for (;;) {
    const hit = await probe(url);
    if (hit) {
      logInfo(`${name} 已就绪：${hit}`);
      return true;
    }
    if (Date.now() >= deadline) break;
    await sleep(intervalMs);
  }
  logWarn(`${name} 在 ${timeoutSec}s 内未就绪（${url}），请查看日志`);
  return false;
}

// ---- 子命令 ----

function requireNode() {
  const major = Number(process.versions.node.split('.')[0]);
  if (major < 20) die(`Node.js 版本过低（当前 v${process.versions.node}），需要 >= 20`);
}

/** 依赖未安装时给出明确指引，而不是让 npm 报一堆找不到模块。 */
function ensureDeps(dir, name) {
  if (!existsSync(join(dir, 'node_modules'))) {
    die(`${name} 依赖未安装，请先执行：node scripts/dev.mjs setup`);
  }
}

/** 从后端 config 读一个配置值（如 home），保证脚本与代码同源，不在脚本里重算路径规则。 */
function configValue(key) {
  const probeSource = `const { config } = await import('./src/config/index.js'); process.stdout.write(String(config.${key}));`;
  const result = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', probeSource], { cwd: serverDir, encoding: 'utf8' });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    process.stderr.write(result.stderr ?? '');
    die(`读取后端配置失败：${key}`);
  }
  return result.stdout;
}

/** 建库 / 同步 schema：统一走 server/scripts/db.mjs（db push + bootstrap.sql），不在脚本里重算连接串。 */
async function dbSync(env = process.env) {
  const code = await runTool(process.execPath, [dbScript, 'sync'], { cwd: serverDir, env });
  if (code !== 0) die('建库失败（server/scripts/db.mjs sync）');
}

async function setup() {
  requireNode();

  logInfo(`安装后端依赖：${serverDir}`);
  await mustRun('npm', ['install'], { cwd: serverDir });
  logInfo(`安装前端依赖：${webDir}`);
  await mustRun('npm', ['install'], { cwd: webDir });

  const envPath = join(serverDir, '.env');
  if (!existsSync(envPath)) {
    copyFileSync(join(serverDir, '.env.example'), envPath);
    logInfo('已生成 server/.env（来自 .env.example）');
  }

  logInfo('生成 Prisma Client');
  await mustRun('npm', ['run', 'prisma:generate'], { cwd: serverDir });

  const home = configValue('home');
  mkdirSync(home, { recursive: true });
  logInfo(`数据目录：${home}`);

  logInfo('应用数据库结构（db push + bootstrap.sql）');
  await dbSync();

  logInfo('依赖安装完成。启动：node scripts/dev.mjs start');
}

async function start() {
  requireNode();
  ensureDeps(serverDir, '后端');
  ensureDeps(webDir, '前端');
  mkdirSync(logDir, { recursive: true });

  // 端口先行检查：否则旧进程占着端口时新子进程 EADDRINUSE 退出，探活却命中旧进程
  await assertPortFree('server', serverPort);
  await assertPortFree('web', webPort);

  await dbSync();

  // 先起后端：前端 vite proxy 依赖后端在监听
  const serverEnv = process.env.SMART_FACTORY_SERVER_PORT ? { ...process.env, PORT: serverPort } : process.env;
  startDetached('server', 'npm', ['run', 'dev'], { cwd: serverDir, env: serverEnv });
  await waitForHttp(`${serverUrl}${healthPath}`, '后端', 30);

  startDetached('web', 'npm', ['run', 'dev'], { cwd: webDir });
  await waitForHttp(webUrl, '前端', 30);

  console.log();
  logInfo('启动完成');
  logInfo(`  前端：${webUrl}`);
  logInfo(`  后端：${serverUrl}${healthPath}`);
  logInfo(`  日志：${logDir}/{server,web}.log`);
  logInfo('  查看状态：node scripts/dev.mjs status   停止：node scripts/dev.mjs stop');
}

async function restart() {
  await stop();
  await start();
}

async function stop() {
  await stopDetached('web');
  await stopDetached('server');

  // pidfile 只覆盖本脚本拉起的进程：手工启动 / 旧会话遗留的进程仍会占着端口，
  // 下次 start 的探活会命中它们（看起来「重启成功」，实际跑的还是旧代码）。
  const occupied = [];
  if (await portInUse(serverPort)) occupied.push(`后端 :${serverPort}`);
  if (await portInUse(webPort)) occupied.push(`前端 :${webPort}`);
  if (occupied.length) {
    die(`${occupied.join('、')} 仍被占用，且占用者不是本脚本启动的（没有对应 pidfile）。按端口找到并停止它（Linux：ss -ltnp 'sport = :${serverPort}'）再 start`);
  }
}

async function report(name, url) {
  const record = readPid(join(runDir, `${name}.pid`));
  const pidState = record ? `运行中（pid ${record.pid}）` : '未运行';
  const hit = await probe(url);
  console.log(`  ${name.padEnd(8)} ${(hit ?? url).padEnd(48)} ${pidState} / ${hit ? 'HTTP 正常' : '不可达'}`);
}

async function status() {
  console.log('Smart Factory 服务状态：');
  await report('server', `${serverUrl}${healthPath}`);
  await report('web', webUrl);
}

/**
 * e2e 用最小框架桩：提供工作区清单与详情，让路径解析有目录可用。
 *
 * 不校验令牌、不读取真实令牌内容；令牌文件只保证后端能通过形状校验。
 */
function startFrameworkStub(workspace) {
  const server = createServer((req, res) => {
    const path = new URL(req.url ?? '/', 'http://127.0.0.1').pathname;
    const send = (status, data) => {
      res.writeHead(status, { 'content-type': 'application/json' });
      const body = status === 200
        ? { success: true, data, error: null, meta: null }
        : { success: false, data: null, error: { code: 'NOT_FOUND', message: '资源不存在' }, meta: null };
      res.end(JSON.stringify(body));
    };
    if (req.method !== 'GET') {
      send(405, null);
      return;
    }
    if (path === '/api/framework/v1/workspaces') {
      send(200, { items: [workspace], activeId: workspace.id });
      return;
    }
    if (path === `/api/framework/v1/workspaces/${workspace.id}`) {
      send(200, workspace);
      return;
    }
    if (path === '/api/framework/v1/models') {
      send(200, { items: [], activeId: null });
      return;
    }
    send(404, null);
  });

  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      resolve({
        url: `http://127.0.0.1:${server.address().port}`,
        close: () => new Promise((done) => {
          server.closeAllConnections();
          server.close(() => done());
        }),
      });
    });
  });
}

async function e2e() {
  requireNode();
  ensureDeps(serverDir, '后端');

  const port = process.env.SF_E2E_PORT ?? '3199';
  const home = process.env.COSIGHT_HOME ?? join(serverDir, '.tmp', 'e2e-home');
  const base = `http://127.0.0.1:${port}`;

  // 默认临时目录每次重建：e2e 本就是一次性环境，旧库与当前 schema 漂移时 db push（不重置）会拒绝执行；
  // 显式指定的 COSIGHT_HOME 归调用方所有，不动（schema 漂移时让建库失败报出来）
  if (!process.env.COSIGHT_HOME) rmSync(home, { recursive: true, force: true });
  mkdirSync(home, { recursive: true });

  // 临时令牌只用于通过形状校验；已存在时绝不覆盖调用方的文件
  const tokenPath = join(home, '.module-token');
  if (!existsSync(tokenPath)) writeFileSync(tokenPath, `${randomUUID().replaceAll('-', '')}\n`, { mode: 0o600 });

  const workspaceDir = join(home, 'workspace');
  mkdirSync(workspaceDir, { recursive: true });
  const workspace = {
    id: randomUUID(),
    name: 'e2e 工作区',
    directory: workspaceDir,
    defaultModelId: null,
    defaultAgentId: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  const framework = await startFrameworkStub(workspace);
  // ENGINE 从环境继承，未设置则 fake（默认提示词即触发 fake 审批链）
  const env = {
    ...process.env,
    PORT: port,
    COSIGHT_HOME: home,
    ENGINE: process.env.ENGINE ?? 'fake',
    FRAMEWORK_BASE_URL: framework.url,
  };

  let exitCode = 1;
  try {
    logInfo(`准备数据库：${home}`);
    await dbSync(env);

    logInfo(`启动临时后端：${base}（ENGINE=${env.ENGINE}，框架桩 ${framework.url}）`);
    const serverLog = join(serverDir, '.tmp', 'e2e-server.log');
    const child = spawnBackground(process.execPath, ['--import', 'tsx', 'src/index.ts'], { cwd: serverDir, env, logPath: serverLog, label: 'e2e 后端' });
    try {
      if (await waitForHttp(`${base}${healthPath}`, 'e2e 后端', 30, 500)) {
        exitCode = await runTool(process.execPath, ['tests/e2e/session-flow.mjs'], {
          cwd: serverDir,
          env: { ...env, SF_BASE: base, SF_WS: `ws://127.0.0.1:${port}${wsPath}` },
        });
      } else {
        logError('e2e 后端未就绪，日志尾部：');
        process.stderr.write(`${tailLog(serverLog)}\n`);
      }
    } finally {
      await killTree(child.pid);
    }
  } finally {
    await framework.close();
  }
  process.exitCode = exitCode; // 退出码透传
}

/** 读日志尾部若干行，用于启动失败时给出原因。 */
function tailLog(path, lines = 20) {
  try {
    return readFileSync(path, 'utf8').split('\n').slice(-lines).join('\n');
  } catch {
    return '（日志不可读）';
  }
}

// ---- 入口 ----

const commands = { setup, start, stop, restart, status, e2e };
const command = process.argv[2];

if (!Object.hasOwn(commands, command)) {
  process.stdout.write(
    [
      '用法：node scripts/dev.mjs <setup|start|stop|restart|status|e2e>',
      '  setup   首次：装前后端依赖、生成 server/.env、prisma generate、建数据目录与库',
      '  start   后台启动前后端（日志写 .run/logs/）',
      '  stop    停止由 start 拉起的服务',
      '  restart 先停后起（stop + start）',
      '  status  查看前后端运行状态与端口可达性',
      '  e2e     临时起一个后端跑 tests/e2e/session-flow.mjs（ENGINE 未设置则用 fake）',
      '',
    ].join('\n'),
  );
  process.exitCode = 1;
} else {
  try {
    await commands[command]();
  } catch (error) {
    if (!error?.handled) logError(error?.message ?? String(error));
    process.exitCode = 1;
  }
}
