/**
 * 服务端配置的唯一入口。
 *
 * 所有环境变量都在这里解析并校验一次，其余模块只消费 `ServerConfig`。
 * 这样做的原因：散落的 `process.env.X` 会让"某个配置没设"变成运行期的
 * undefined 事故，而在这里 fail-fast 能在启动瞬间报出来。
 */

import os from 'node:os';
import path from 'node:path';

import { defaultWorkspacesRoot } from './paths';

export interface ServerConfig {
  /**
   * 监听地址。默认 `0.0.0.0`（所有网卡），便于容器端口映射与局域网访问。
   *
   * 注意这只是**监听面**，不提供任何访问控制：D25 的前提仍然是"本机单用户、
   * 无登录"，模型密钥在工作区配置里是明文。要收窄回只绑本机，设
   * `COSIGHT_HOST=127.0.0.1`。
   */
  host: string;
  port: number;
  /** 数据根目录（D26 = A）。 */
  cosightHome: string;
  /**
   * 工作区根目录（D32）。
   *
   * 默认 `$COSIGHT_HOME/workspaces`，可用 `COSIGHT_WORKSPACES_ROOT` 整体挪走——
   * 工作区里装的是用户的项目文件，有人会希望它跟框架的私有数据分开放
   * （换个盘、放进已有的工程目录）。
   *
   * 解析口径与 `COSIGHT_HOME` **逐字一致**：`path.resolve`、不展开 `~`、
   * 相对路径按进程 cwd 解析。不在这里为它破例做波浪号展开——否则同一份配置里
   * 两个路径变量的行为不一致，而"哪个支持 `~`"是记不住的。
   */
  workspacesRoot: string;
  /** libsql 连接串，形如 `file:/abs/path.sqlite`。 */
  databaseUrl: string;
  /** 前端构建产物目录；为 null 表示只跑 API（开发态由 Vite 服务前端）。 */
  webDistDir: string | null;
  /**
   * 允许跨源访问的源。
   * 开发态是 Vite dev server；文件型 URL 上跑的前端会带 `null` 源，
   * 因此这里也接受显式的 `null` 字面量。
   */
  corsOrigins: string[];
  /**
   * 宿主前端的源，用于模块清单的跨源校验（D24 = A）。
   *
   * 必须是**前端**的源，不是 API 的源：开发态前端跑在 Vite（:4310），API 在 :4300，
   * 此时"宿主"是 :4310。默认取 API 自身的源，生产态两者一致故无需配置；
   * 开发态或反代场景由 COSIGHT_HOST_ORIGIN 显式给出。
   */
  hostOrigin: string;
  logLevel: LogLevel;
  isProduction: boolean;
  /**
   * 知识库 Agent API Key 的服务端默认（`CO_KNOWLEDGE_API_KEY`）。
   *
   * 设置里的每条路由可以自己配一枚；没配的用这一枚。它只从环境变量来，
   * **不落库、不回显**：浏览器面只被告知"有没有"（`hasDefaultApiKey`），
   * 模块面才会拿到明文。为 null 表示没配。
   *
   * 先读 `COSIGHT_KNOWLEDGE_API_KEY`（框架自己的命名空间），再读
   * `CO_KNOWLEDGE_API_KEY`（模块 smart-factory 的同名变量）——这样一份
   * `cosight.env` 只写一行就能同时预置框架与模块。
   */
  ragKnowledgeApiKey: string | null;
}

export const LOG_LEVELS = ['fatal', 'error', 'warn', 'info', 'debug', 'trace', 'silent'] as const;

export type LogLevel = (typeof LOG_LEVELS)[number];

export const DEFAULT_PORT = 4300;
export const DEFAULT_HOST = '0.0.0.0';
export const DEFAULT_COSIGHT_HOME = path.join(os.homedir(), '.cosight-harness');

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}

function readPort(raw: string | undefined): number {
  if (raw === undefined || raw === '') {
    return DEFAULT_PORT;
  }
  const port = Number.parseInt(raw, 10);
  if (!Number.isInteger(port) || port < 1 || port > 65_535) {
    throw new ConfigError(`COSIGHT_PORT 必须是 1..65535 的整数，收到 ${raw}`);
  }
  return port;
}

function readLogLevel(raw: string | undefined): LogLevel {
  if (raw === undefined || raw === '') {
    return 'info';
  }
  if (!(LOG_LEVELS as readonly string[]).includes(raw)) {
    throw new ConfigError(`COSIGHT_LOG_LEVEL 必须是 ${LOG_LEVELS.join(' | ')}，收到 ${raw}`);
  }
  return raw as LogLevel;
}

function readOrigins(raw: string | undefined): string[] {
  /*
   * 默认值 = 开发态前端（Vite）的源 + 各模块自己的源。两个写法都列上是因为
   * `localhost` 与 `127.0.0.1` 在浏览器看来是**不同的源**，只列一个会让另一种
   * 写法的访问被 CORS 拒掉。
   *
   * 4310 而不是 Vite 默认的 5173：全仓开发端口统一在 4xxx 段按模块划分
   * （框架 43xx、smart-factory 41xx、cosight-viewer 48xx），避免与大量使用
   * Vite 默认端口的项目撞车。端口定义在 `framework/web/vite.config.ts` 的
   * `WEB_PORT`，改那里要同步改这里。
   *
   * 4830 = `cosight-viewer` 模块的源（`docs/modules/cosight-viewer.module.json` 的
   * `entry`）。模块以 iframe 挂载、**从自己的源**调用 `/api/*`，所以它必须在白名单里；
   * 否则模块内的请求会被 CORS 拦掉（`credentials: true` 时预检即被拒，后端日志里
   * 连请求都看不到，只在浏览器控制台留一条 CORS 报错）。
   */
  const defaults = [
    'http://localhost:4310',
    'http://127.0.0.1:4310',
    'http://localhost:4830',
    'http://127.0.0.1:4830',
  ];
  if (raw === undefined || raw === '') {
    return defaults;
  }
  return raw
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item !== '');
}

/**
 * 解析宿主源，并**归一化成纯源**（丢掉路径/查询串/尾斜杠）。
 * 归一化是必须的：`hostOrigin` 会与 `new URL(...).origin` 做全等比较，
 * 若这里留着路径，比较永远不相等，跨源校验就会静默失去作用。
 */
function readHostOrigin(raw: string | undefined, host: string, port: number): string {
  const fallback = `http://${host === '0.0.0.0' ? '127.0.0.1' : host}:${port}`;
  if (raw === undefined || raw === '') {
    return fallback;
  }
  try {
    return new URL(raw).origin;
  } catch {
    throw new ConfigError(`COSIGHT_HOST_ORIGIN 不是合法 URL，收到 ${raw}`);
  }
}

function readWebDist(raw: string | undefined, isProduction: boolean): string | null {
  if (raw !== undefined && raw !== '') {
    return path.resolve(raw);
  }
  // 生产态默认从包内 dist 提供前端；开发态交给 Vite，不设默认值。
  return isProduction ? path.resolve(process.cwd(), 'public') : null;
}

/**
 * 按顺序取第一个**非空白**的候选值；都空则 `null`。
 *
 * 空白（或只有空格）一律当"没配"，避免 `KEY=` 这种写法变成一个空密钥。
 * 逐个判断而不是 `a ?? b`：`COSIGHT_KNOWLEDGE_API_KEY=`（显式留空）时，
 * `??` 会停在空串上，把另一枚本来能用的 `CO_KNOWLEDGE_API_KEY` 挡掉。
 */
function readOptionalSecret(...candidates: (string | undefined)[]): string | null {
  for (const raw of candidates) {
    const value = raw?.trim() ?? '';
    if (value !== '') {
      return value;
    }
  }
  return null;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): ServerConfig {
  const isProduction = env['NODE_ENV'] === 'production';
  const cosightHome = path.resolve(env['COSIGHT_HOME'] ?? DEFAULT_COSIGHT_HOME);
  const workspacesRoot = path.resolve(
    env['COSIGHT_WORKSPACES_ROOT'] ?? defaultWorkspacesRoot(cosightHome),
  );
  const databaseUrl = env['COSIGHT_DATABASE_URL'] ?? `file:${path.join(cosightHome, 'sqlite.db')}`;
  const host = env['COSIGHT_HOST'] ?? DEFAULT_HOST;
  const port = readPort(env['COSIGHT_PORT']);

  return {
    host,
    port,
    cosightHome,
    workspacesRoot,
    databaseUrl,
    webDistDir: readWebDist(env['COSIGHT_WEB_DIST'], isProduction),
    corsOrigins: readOrigins(env['COSIGHT_CORS_ORIGINS']),
    hostOrigin: readHostOrigin(env['COSIGHT_HOST_ORIGIN'], host, port),
    logLevel: readLogLevel(env['COSIGHT_LOG_LEVEL']),
    isProduction,
    ragKnowledgeApiKey: readOptionalSecret(
      env['COSIGHT_KNOWLEDGE_API_KEY'],
      env['CO_KNOWLEDGE_API_KEY'],
    ),
  };
}
