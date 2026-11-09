import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdirSync, readdirSync, rmSync, statSync, writeFileSync, type Dirent } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

// 以本文件位置为锚定位建库脚本，不依赖运行 cwd。
const dbScript = join(fileURLToPath(new URL('../../', import.meta.url)), 'scripts', 'db.mjs');

export interface TestEnv {
  home: string;
  workspaceDir: string;
  databaseUrl: string;
}

/** 一天前的历史测试目录：进程被杀时不会回收，长期累积占盘。 */
const STALE_MS = 24 * 60 * 60 * 1000;

/** 探活：0 号信号只检查进程是否存在；EPERM 表示存在但无权限探测，按存活处理。 */
function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== 'ESRCH';
  }
}

/**
 * 清掉陈旧的测试目录：属主进程已退出的 `<name>-<pid>` 目录，或超过一天未更新的目录。
 * 当前进程的目录不动；清理失败静默忽略，不影响测试。
 */
function pruneStaleDirs(root: string): void {
  const cutoff = Date.now() - STALE_MS;
  let entries: Dirent[];
  try {
    entries = readdirSync(root, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const owner = /-(\d+)$/.exec(entry.name)?.[1];
    const ownerPid = owner === undefined ? null : Number(owner);
    // 当前进程的目录马上重建，不在清理范围
    if (ownerPid === process.pid) continue;
    const path = join(root, entry.name);
    try {
      // 属主已退出，或一天未更新（PID 被复用的兜底）：都不会有测试还在使用
      const stale =
        (ownerPid !== null && !isProcessAlive(ownerPid)) || statSync(path).mtimeMs < cutoff;
      if (stale) rmSync(path, { recursive: true, force: true });
    } catch {
      // 并发运行的测试可能刚好删掉同一目录
    }
  }
}

/**
 * 每个测试文件一个隔离的 COSIGHT_HOME 与空库。
 *
 * 必须在 import 任何 src 模块之前调用：config 与 PrismaClient 都在 import 时读环境。
 * 返回后测试用动态 `await import(...)` 引入被测模块。
 * 同时准备框架模块令牌与一个工作区目录，供后续依赖框架的用例使用。
 */
export function prepareTestEnv(name: string): TestEnv {
  const root = join(process.cwd(), '.tmp', 'test');
  mkdirSync(root, { recursive: true });
  pruneStaleDirs(root);
  const home = join(root, `${name}-${process.pid}`);
  rmSync(home, { recursive: true, force: true });
  mkdirSync(home, { recursive: true });

  const workspaceDir = join(home, 'workspace');
  mkdirSync(workspaceDir, { recursive: true });
  writeFileSync(join(home, '.module-token'), `${randomBytes(32).toString('base64url')}\n`, { mode: 0o600 });

  process.env.COSIGHT_HOME = home;
  process.env.ENGINE = 'fake';
  // 创建后的自动命名默认关闭：否则每个建智能体的用例都会去打真模型地址。
  // 专测自动命名的用例在 import 前自行改成 '1' 并把模型 baseUrl 指向本地桩。
  process.env.AUTO_META = '0';
  const databaseUrl = `file:${join(home, 'smart-factory.db')}`;
  process.env.DATABASE_URL = databaseUrl;
  process.env.XDG_CACHE_HOME = join(root, 'cache');
  // 隔离 Claude 配置目录：本机装的插件（含产品运行时能力 drive）会进智能体详情的可执行清单，
  // 不隔离的话「没装插件 = 不列」的断言随开发机环境飘。
  process.env.CLAUDE_CONFIG_DIR = join(home, 'claude-config');

  execFileSync(process.execPath, [dbScript, 'sync'], {
    stdio: 'pipe',
    env: { ...process.env, DATABASE_URL: databaseUrl, XDG_CACHE_HOME: process.env.XDG_CACHE_HOME },
  });

  return { home, workspaceDir, databaseUrl };
}
