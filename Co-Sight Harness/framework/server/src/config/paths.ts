/**
 * 数据目录布局（D26 = A，工作区部分见 D32）。
 *
 *   $COSIGHT_HOME/
 *   ├── sqlite.db            业务数据
 *   ├── .credentials.yaml    密钥，文件 0600、父目录 0700
 *   ├── .module-token        模块面令牌，文件 0600（见 credentials/module-token.ts）
 *   ├── modules/             模块清单（module.json），一个模块一个子目录
 *   └── workspaces/          工作区根目录（可用 COSIGHT_WORKSPACES_ROOT 整体挪走）
 *       ├── _public/         框架保留的公共空间，**不属于任何具体工作区**
 *       └── <slug>/          一个工作区一个目录，由框架按工作区名派生（见 lib/slug.ts）
 *
 * 密钥与业务数据分文件存放是刻意的：备份或分享 sqlite.db 时不会连带泄漏密钥。
 * `.module-token` 与 `.credentials.yaml` 同理——它俩都**不该进备份、不该进版本控制**。
 *
 * 两者有一个刻意的差异：`.credentials.yaml` 不在启动时创建（没配过密钥就不留空文件），
 * 而 `.module-token` **在启动时创建**——它的存在本身就是"别的模块该怎么接入"的线索。
 *
 * 工作区那棵树与前两者又不同：它装的是**用户的文件**，不是框架的私有状态。
 * 因此有三条与上面几条相反的取舍，改动前请读完 `docs/workspace-design.md`：
 * 1. 目录名由框架从不完全可信的**工作区名**派生，必须 slug 化，绝不能让输入直接进路径；
 * 2. 只有"框架自己那一亩三分地"（工作区根之下）才会被 `mkdir`，用户手填的绝对路径只绑定；
 * 3. 删除工作区只删**框架自己创建的直接子目录**；用户绑定的外部目录不删——
 *    那里是用户的真实文件，误删不可逆。
 */

import fs from 'node:fs';
import path from 'node:path';

import { chmodBestEffort } from '../lib/file-mode';

/** 密钥文件权限：仅所有者可读写。 */
const CREDENTIALS_FILE_MODE = 0o600;
/** 数据目录权限：仅所有者可进入。 */
const DIR_MODE = 0o700;

/** 模块面令牌文件名。定义在这里而不是 `credentials/module-token.ts`：它属于目录布局。 */
export const MODULE_TOKEN_FILE_NAME = '.module-token';

/** 公共工作区空间的目录名。以 `_` 开头，`toDirectorySlug` 会剥掉前导 `_`，故用户永远撞不上。 */
export const PUBLIC_WORKSPACE_DIR_NAME = '_public';

export interface DataPaths {
  home: string;
  database: string;
  credentials: string;
  moduleToken: string;
  modules: string;
  /** 工作区根目录。默认 `$COSIGHT_HOME/workspaces`，可用 `COSIGHT_WORKSPACES_ROOT` 覆盖。 */
  workspaces: string;
  /** 公共工作区空间：`<工作区根>/_public`。 */
  publicWorkspace: string;
}

/**
 * 工作区根目录默认值。
 *
 * 单独导出是因为 `config/env.ts` 与 `services/container.ts` 都要用同一份默认值：
 * 前者在环境变量缺省时算出来，后者在测试等窄入口下兜底。两处各写一遍
 * `path.join(home, 'workspaces')` 将来必然有一天只改了一边。
 */
export function defaultWorkspacesRoot(cosightHome: string): string {
  return path.join(cosightHome, 'workspaces');
}

export function resolveDataPaths(
  cosightHome: string,
  workspacesRoot: string = defaultWorkspacesRoot(cosightHome),
): DataPaths {
  return {
    home: cosightHome,
    database: path.join(cosightHome, 'sqlite.db'),
    credentials: path.join(cosightHome, '.credentials.yaml'),
    moduleToken: path.join(cosightHome, MODULE_TOKEN_FILE_NAME),
    modules: path.join(cosightHome, 'modules'),
    workspaces: workspacesRoot,
    publicWorkspace: path.join(workspacesRoot, PUBLIC_WORKSPACE_DIR_NAME),
  };
}

/**
 * 幂等地建目录，并把权限收紧到 0700。
 *
 * 注意 chmod 是显式做的：`mkdir` 的 mode 会被进程 umask 削掉，
 * 因此不能只靠 mkdir 参数保证权限。
 */
export function ensureDirectory(dir: string, mode: number = DIR_MODE): void {
  fs.mkdirSync(dir, { recursive: true, mode });
  // 非 POSIX 文件系统（如部分挂载的 Windows 盘）不支持 chmod：此时权限收紧失效，
  // 但不应阻断启动。这条策略挪去了 lib/file-mode.ts——原子写令牌那条路径
  // 也要求同一套（那边原来连 try 都没有），一处写两遍必然漂。
  chmodBestEffort(dir, mode);
}

/**
 * 是否 `parent` 自身或它的后代。按**路径段**比较，不用字符串前缀——
 * `path.relative` 已经把 `/a/bc` 对 `/a/b` 这种情况算成 `../bc`，前缀比较则会误判成"在里面"。
 */
export function isInside(parent: string, target: string): boolean {
  const relative = path.relative(parent, target);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

/**
 * 建**框架自己**的目录：在 `$COSIGHT_HOME` 之内就收紧到 0700，之外只创建。
 *
 * 这个分支只为工作区根存在。`COSIGHT_WORKSPACES_ROOT` 允许把工作区放到
 * `/srv/projects`、团队共享盘这类地方，那种目录的权限策略归运维；框架在这里
 * 自作主张 chmod 0700 会把别人原本设好的访问权收掉，而且没有任何提示。
 * 留在 `home` 里的默认位置则照旧收紧，与 `modules/` 同口径。
 */
export function ensureOwnedDirectory(home: string, dir: string): void {
  if (isInside(home, dir)) {
    ensureDirectory(dir);
    return;
  }
  fs.mkdirSync(dir, { recursive: true });
}

export function ensureDataPaths(paths: DataPaths): void {
  ensureDirectory(paths.home);
  ensureDirectory(paths.modules);
  ensureOwnedDirectory(paths.home, paths.workspaces);
  ensureOwnedDirectory(paths.home, paths.publicWorkspace);
}

export function credentialsFileMode(): number {
  return CREDENTIALS_FILE_MODE;
}
