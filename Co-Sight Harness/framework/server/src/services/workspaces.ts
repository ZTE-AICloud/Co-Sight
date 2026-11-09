/**
 * 工作区服务：把「工作区」这件事的三条不变量收到一处（D16 = A 的落地，D32 修订）。
 *
 * ## 为什么需要这一层（此前没有）
 *
 * 在只有一个面（浏览器）的时候，路由直接调仓储是够的。现在模块面
 * （`/api/framework/v1/workspaces`）要提供同一套 CRUD，于是三件事会立刻出现
 * 第二份实现：
 *
 * 1. **名字唯一性检查**——`POST` 与 `PATCH` 各一处，两个面就是四份拷贝；
 * 2. **「删掉的正好是当前工作区时清指针」**——原来在 `routes/workspace.ts` 的
 *    DELETE 里一处，读取端的自愈在 `GET /active` 里第二处，再接一个面就是第三处。
 *    这几处一旦不一致，表现是 `/active` 长期悬空、前端拿到 null 却不知道为什么；
 * 3. **建目录**——`POST` 独有，但两个面都得有。
 *
 * 所以把这三条提到服务层，路由退化成"校验入参 + 调服务 + 包信封"。
 * 领域错误（重名 409、不存在 404）由服务抛 `AppError`，路由不自行判断——
 * 否则两个面又要各判一次。
 *
 * ## 磁盘行为（哪一步动盘、哪一步不动）
 *
 * | 操作 | 磁盘 |
 * |---|---|
 * | `create`，`directory` 为空 | **建** `<工作区根>/<slug>`，绑定它的 realpath |
 * | `create`，`directory` 是用户填的绝对路径 | **不建**、不要求存在，只绑定 |
 * | `update`（含改名） | 不动。目录在创建时绑定，之后稳定，改名不重命名目录 |
 * | `deleteById` | **删**框架自己创建的直接子目录；用户外部绑定的目录保留 |
 *
 * 删除的边界刻意画在「工作区根的直接子目录」上：只有这类目录确定是框架按工作区名
 * 建出来的，删掉它不会碰到用户的既有项目。用户填绝对路径绑定的目录（例如
 * `/srv/projects/existing`）只解除记录，绝不 `rm -rf`——那个目录里是用户自己的文件。
 * `_public` 是框架保留空间，即使被某条记录绑定也不删。
 *
 * 完整的取舍与理由见 `docs/workspace-design.md`。
 */

import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import {
  AppError,
  type CreateWorkspaceInput,
  type UpdateWorkspaceInput,
  type Workspace,
} from 'harness-shared';

import { ACTIVE_WORKSPACE_KEY, type AppStateRepository } from '../repositories/app-state.repository';
import type { WorkspaceRepository } from '../repositories/workspace.repository';
import { PUBLIC_WORKSPACE_DIR_NAME } from '../config/paths';
import { directorySlugAttempt, toDirectorySlug } from '../lib/slug';

/**
 * 冲突重试上限。撞到第 99 个同名目录后改用随机后缀——现实里到不了，
 * 但"上限 + 明确的兜底"比"无限循环"和"直接抛错"都好：
 * 前者在极端情况下挂死，后者在一个其实还能救的场景里报错。
 */
const MAX_SLUG_ATTEMPTS = 99;

/** 随机后缀的重试次数。同样只是防死循环。 */
const MAX_RANDOM_ATTEMPTS = 5;

export interface WorkspaceOverview {
  items: Workspace[];
  /**
   * 当前生效的工作区 id。列表里**没有** `isActive` 字段——生效项是全局唯一状态
   * （`app_state` 表），放进每一项会让"改一个工作区"变成"可能改到别人的标记"。
   * 消费方本来就要拿这个值做预选，一起返回省掉一次调用与一个竞态。
   */
  activeId: string | null;
}

/** 删除工作区时，绑定目录发生了什么。路由据此写日志，测试据此断言。 */
export type WorkspaceDirectoryDisposition =
  /** 框架创建的工作区目录已连同内容删除。 */
  | 'deleted'
  /** 目录本来就不在了（用户手工删过）。 */
  | 'absent'
  /** 绑定在工作区根之外，是用户自己的目录，只解除绑定。 */
  | 'external'
  /** 这条工作区没有绑定目录。 */
  | 'unbound'
  /** 那个路径已经不是一个目录（被替换成文件等），不删。 */
  | 'not-directory';

export interface DeleteWorkspaceResult {
  /** 被删掉的那条记录（删除前的快照）。 */
  workspace: Workspace;
  directory: string | null;
  directoryDisposition: WorkspaceDirectoryDisposition;
}

export interface WorkspaceServiceOptions {
  repository: WorkspaceRepository;
  appState: AppStateRepository;
  /** 工作区根目录（`config.workspacesRoot`）。 */
  workspacesRoot: string;
}

export class WorkspaceService {
  readonly #repository: WorkspaceRepository;
  readonly #appState: AppStateRepository;
  readonly #root: string;

  constructor(options: WorkspaceServiceOptions) {
    this.#repository = options.repository;
    this.#appState = options.appState;
    this.#root = options.workspacesRoot;
  }

  async list(): Promise<Workspace[]> {
    return this.#repository.list();
  }

  async findById(id: string): Promise<Workspace | null> {
    return this.#repository.findById(id);
  }

  /**
   * 当前工作区，读不到就顺手把指针清掉。
   *
   * 自愈写在这里而不是只在路由里：指针悬空（工作区被删、库被换过）是个脏状态，
   * 任何读它的人都该顺手清，否则它会一直留在库里、每个面都要自己处理一遍 null。
   */
  async findActive(): Promise<Workspace | null> {
    const id = await this.#appState.get(ACTIVE_WORKSPACE_KEY);
    if (id === null) {
      return null;
    }
    const workspace = await this.#repository.findById(id);
    if (workspace === null) {
      await this.#appState.delete(ACTIVE_WORKSPACE_KEY);
      return null;
    }
    return workspace;
  }

  async overview(): Promise<WorkspaceOverview> {
    const [items, active] = await Promise.all([this.#repository.list(), this.findActive()]);
    return { items, activeId: active?.id ?? null };
  }

  /** 建工作区。重名抛 409；`directory` 为空时**在框架自己的工作区根下建目录**。 */
  async create(input: CreateWorkspaceInput): Promise<Workspace> {
    await this.#assertNameAvailable(input.name, null);
    const directory = await this.#bindDirectory(input);
    return this.#repository.create({ ...input, directory });
  }

  /**
   * 部分更新。不存在返回 null（让路由抛 404）。
   *
   * **改名不重命名目录**：目录名是创建那一刻从当时的工作区名派生的一次性快照。
   * 跟着改名走意味着"用户改个显示名，磁盘上少了一个目录、多了一个目录"，
   * 而任何指向旧路径的东西（编辑器、终端、另一个模块记下的路径）会当场失效。
   */
  async update(id: string, patch: UpdateWorkspaceInput): Promise<Workspace | null> {
    if (patch.name !== undefined) {
      await this.#assertNameAvailable(patch.name, id);
    }
    return this.#repository.update(id, patch);
  }

  async activate(id: string): Promise<Workspace | null> {
    const workspace = await this.#repository.findById(id);
    if (workspace === null) {
      return null;
    }
    await this.#appState.set(ACTIVE_WORKSPACE_KEY, workspace.id);
    return workspace;
  }

  /**
   * 删记录，并同步删掉**框架自己创建**的工作区目录。
   *
   * 顺序是"先目录、后记录"：目录删不掉（权限、被占用）时记录还在，用户可以重试；
   * 反过来会留下"记录没了、目录还在"的脏状态。外部绑定的目录不删——那条路径
   * 是用户自己准备的，框架没有资格替用户做 `rm -rf`。
   *
   * 返回 `null` 表示记录不存在；否则返回删除前的快照与目录处置结果。
   */
  async deleteById(id: string): Promise<DeleteWorkspaceResult | null> {
    const existing = await this.#repository.findById(id);
    if (existing === null) {
      return null;
    }

    const directoryDisposition = this.#removeManagedDirectory(existing.directory);

    const deleted = await this.#repository.deleteById(id);
    if (!deleted) {
      // 查到之后、删之前被并发删掉了。当作不存在处理，不是错误。
      return null;
    }
    // 删掉的正好是当前工作区时，指针必须一起清掉，否则 /active 会一直悬空。
    // 读取端也有自愈逻辑，这里是写入端就该做的事，两层都要。
    const active = await this.#appState.get(ACTIVE_WORKSPACE_KEY);
    if (active === id) {
      await this.#appState.delete(ACTIVE_WORKSPACE_KEY);
    }
    return { workspace: existing, directory: existing.directory, directoryDisposition };
  }

  /**
   * 只删框架管理的工作区目录：工作区根下的**直接子目录**，且不是 `_public`。
   *
   * 为什么不按"记录里的 directory 一律删"：`POST`/`PATCH` 允许绑定任意绝对路径
   * （`/srv/projects/existing` 这种）。对那条路径做递归删除等于把用户的项目目录
   * 交给一次 HTTP DELETE 决定，误删不可逆。直接子目录是框架按工作区名亲手建的，
   * 语义明确，才在删除范围内。
   *
   * 不跟随符号链接：如果目录被替换成链接，只删链接本身（`unlink`），
   * 指向的外部内容原样保留。
   */
  #removeManagedDirectory(directory: string | null): WorkspaceDirectoryDisposition {
    if (directory === null) {
      return 'unbound';
    }

    const target = path.resolve(directory);
    const root = this.#rootRealPath();

    // 根被配成文件系统根（`/` 或 `C:\`）时，任何直接子目录都不再"确定是框架建的"。
    // 这属于误配置，宁可保留也不删。
    if (root === path.parse(root).root) {
      return 'external';
    }
    if (
      path.dirname(target) !== root ||
      path.basename(target).toLowerCase() === PUBLIC_WORKSPACE_DIR_NAME.toLowerCase()
    ) {
      return 'external';
    }

    let stat: fs.Stats;
    try {
      stat = fs.lstatSync(target);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return 'absent';
      }
      throw error;
    }

    if (stat.isSymbolicLink()) {
      fs.unlinkSync(target);
      return 'deleted';
    }
    if (!stat.isDirectory()) {
      return 'not-directory';
    }

    /*
     * `recursive` 删内容；`force: true` 只忽略"路径已不存在"，不会吞掉权限错误。
     * 删除失败时抛给路由，记录因此保留，用户修好权限后可以再次删除。
     */
    fs.rmSync(target, { recursive: true, force: true });
    return 'deleted';
  }

  /**
   * 决定这条工作区绑定哪个目录。
   *
   * 用户填了绝对路径 → 原样返回，**不创建、不要求存在**。
   * 理由：`POST` 的入参来自 HTTP 请求，对任意绝对路径执行 `mkdir -p` 等于把一个
   * 写原语交给调用方去碰用户整台机器，而且它会静默造出多层父目录。
   * 「框架只管自己那一亩三分地」这条边界比"顺手帮用户建好"更值得守；
   * 契约注释里那句"绑定目录时也不要求目录已存在（创建与使用解耦）"也依然成立。
   */
  async #bindDirectory(input: CreateWorkspaceInput): Promise<string | null> {
    if (input.directory !== null) {
      return input.directory;
    }
    return this.#createWorkspaceDirectory(input.name);
  }

  async #createWorkspaceDirectory(name: string): Promise<string> {
    // 根目录由 `ensureDataPaths` 在启动时建好；这里再建一次是幂等的兜底，
    // 覆盖"测试传入 preparePaths: false"与"根目录被手工删掉"两种情形。
    // 不用 `ensureDirectory`：那会 chmod，而这里不该对根目录的权限发挥任何意见。
    fs.mkdirSync(this.#root, { recursive: true });

    const taken = await this.#takenDirectoryNames();
    const slug = toDirectorySlug(name);

    for (let index = 1; index <= MAX_SLUG_ATTEMPTS; index += 1) {
      const candidate = directorySlugAttempt(slug, index);
      if (taken.has(candidate.toLowerCase())) {
        continue;
      }
      const created = this.#tryCreate(candidate);
      if (created !== null) {
        return created;
      }
    }

    for (let attempt = 0; attempt < MAX_RANDOM_ATTEMPTS; attempt += 1) {
      const candidate = `${slug.slice(0, 32)}-${randomSuffix()}`;
      const created = this.#tryCreate(candidate);
      if (created !== null) {
        return created;
      }
    }

    throw AppError.conflict(
      'workspace',
      `工作区根目录下「${slug}」的同名目录过多，无法再分配新目录：${this.#root}`,
    );
  }

  /**
   * 真的去建，成功返回规范化的路径、`EEXIST` 返回 null 让调用方换下一个候选。
   *
   * 为什么靠 `EEXIST` 而不是只靠上面那个 `taken` 集合：`readdir` 与 `mkdir` 之间
   * 存在一个真实的 TOCTOU 窗口（同机两个进程、或一个进程两次并发请求）。
   * `mkdir` 不带 `recursive` 时对已存在的路径**必然**抛 `EEXIST`，这是内核给的原子的
   * 判重，比任何"先查再建"都强。`taken` 集合的作用是让常见情况一次就选中，
   * 不是正确性的依据。
   */
  #tryCreate(candidate: string): string | null {
    const target = path.join(this.#root, candidate);
    try {
      /*
       * 不传 mode：用进程 umask 的默认值。工作区目录装的是用户的内容，
       * 不该由框架收紧权限；根目录本身在 `ensureDataPaths` 里已经按
       * "是否位于 $COSIGHT_HOME 之内"决定过策略了。
       */
      fs.mkdirSync(target);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'EEXIST') {
        return null;
      }
      throw error;
    }
    // 存 realpath 而不是拼出来的字符串：符号链接、尾斜杠、大小写
    // （macOS 上 `/Users/x` 与 `/users/x` 是同一个目录）都收敛成一个规范形式，
    // 于是"两条记录指向同一个目录"这种判重在字符串比较下也成立。
    return fs.realpathSync(target);
  }

  /**
   * 已占用的目录名，**小写化后**比较。
   *
   * 小写化是因为大小写不敏感的文件系统（macOS APFS、Windows NTFS、部分网络挂载）
   * 上 `周报` 与 `周报` 是同一个目录而 `Report` 与 `report` 也是——但 SQLite 的
   * 文本 `=` 是**大小写敏感**的，库里的重名检查挡不住这一层。
   * 单一来源（`existsSync` 只探一个点）同样不够：它探不出"另一个大小写变体已存在"。
   *
   * 两个来源都要看：磁盘（目录真的在）与库（目录被手工删了、记录还在）。
   */
  async #takenDirectoryNames(): Promise<Set<string>> {
    const taken = new Set<string>();

    for (const entry of fs.readdirSync(this.#root)) {
      taken.add(entry.toLowerCase());
    }

    const rootPrefix = this.#rootRealPath();
    for (const workspace of await this.#repository.list()) {
      if (workspace.directory === null || path.dirname(workspace.directory) !== rootPrefix) {
        continue;
      }
      taken.add(path.basename(workspace.directory).toLowerCase());
    }

    return taken;
  }

  /** 根目录的规范化路径；根目录还不存在（如测试关掉 preparePaths）时退回原值。 */
  #rootRealPath(): string {
    try {
      return fs.realpathSync(this.#root);
    } catch {
      return this.#root;
    }
  }

  /**
   * 名字唯一性。`exceptId` 用于 `PATCH`：改到自己身上不算冲突。
   *
   * 仓储层没有唯一索引（`workspace.repository.ts:1-7` 解释了为什么），所以这条
   * 检查是**唯一**一道，不是锦上添花。放在服务里，两个面共用。
   */
  async #assertNameAvailable(name: string, exceptId: string | null): Promise<void> {
    const existing = await this.#repository.findByName(name);
    if (existing !== null && existing.id !== exceptId) {
      throw AppError.conflict('workspace', `工作区名「${name}」已存在`);
    }
  }
}

function randomSuffix(): string {
  /*
   * 6 个十六进制字符 = 24 位。够到"撞不上"，短到不破坏目录名的可读性。
   *
   * 用 `node:crypto` 而不是 `Math.random`：这里不需要密码学强度（它只是个
   * 消歧后缀，不是令牌），但仓里凡是"生成一个名字"的地方都走 crypto
   * （`lib/id.ts`、`bridge/session.ts`、`credentials/module-token.ts`），
   * 保持同一种写法，将来 grep 的时候不会漏掉一处。
   */
  return randomBytes(3).toString('hex');
}
