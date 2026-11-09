/**
 * 服务容器：把配置、连接、仓储、桥接会话一次性装配好。
 *
 * 为什么不走 Fastify 装饰器逐个注册：装配顺序在这里是显式的（建目录 → 开库 →
 * 迁移 → 建仓储），一眼能看出依赖关系；而装饰器注册顺序是隐式的，
 * 新增一个仓储时很容易被加到错误的位置。
 */

import { BridgeSessionService } from '../bridge/session';
import type { ServerConfig } from '../config/env';
import { ensureDataPaths, resolveDataPaths, type DataPaths } from '../config/paths';
import { ModuleTokenStore } from '../credentials/module-token';
import { CredentialStore } from '../credentials/store';
import { createDatabase, type DatabaseHandle } from '../db/client';
import { runMigrations } from '../db/migrate';
import { AgentProxyRepository } from '../repositories/agent-proxy.repository';
import { AppStateRepository } from '../repositories/app-state.repository';
import { ExpertRepository } from '../repositories/expert.repository';
import { ModelConfigRepository } from '../repositories/model-config.repository';
import { RagKnowledgeRepository } from '../repositories/rag-knowledge.repository';
import { WorkspaceRepository } from '../repositories/workspace.repository';
import { DirectoryPickerService } from './directory-picker';
import { ModuleModelService } from './module-models';
import { ModuleRagKnowledgeService } from './module-rag-knowledge';
import { WorkspaceFileService } from './workspace-files';
import { WorkspaceService } from './workspaces';

export interface Services {
  config: ServerConfig;
  paths: DataPaths;
  handle: DatabaseHandle;
  credentials: CredentialStore;
  /** 模块面门禁（`routes/module-face.ts`）用的令牌存储。 */
  moduleToken: ModuleTokenStore;
  bridge: BridgeSessionService;
  appState: AppStateRepository;
  /**
   * 工作区服务（不是仓储）。两个面共用同一份"重名检查 / 建目录 / 删当前项清指针"
   * 的逻辑，见 `services/workspaces.ts` 的文件头。
   */
  workspaces: WorkspaceService;
  /**
   * 工作区文件浏览（**只读**）。与 `workspaces` 分开：它读的是用户目录里的内容，
   * 不是记录，见 `services/workspace-files.ts` 的文件头。
   */
  workspaceFiles: WorkspaceFileService;
  /**
   * 系统目录选择器：在本机桌面上弹原生对话框，见 `services/directory-picker.ts`。
   * 没有放进 `workspaces`：它不碰记录，也与模块面无关（只给浏览器面用）。
   */
  directoryPicker: DirectoryPickerService;
  experts: ExpertRepository;
  models: ModelConfigRepository;
  agentProxies: AgentProxyRepository;
  /** RAG 知识库跳转路由；两个面共用，模块面只挂只读路由。 */
  ragKnowledge: RagKnowledgeRepository;
  /** 模块面模型服务：会读出明文密钥，**只给模块面路由用**。 */
  moduleModels: ModuleModelService;
  /** 模块面知识库服务：会读出明文密码，**只给模块面路由用**。 */
  moduleRagKnowledge: ModuleRagKnowledgeService;
}

export interface CreateServicesOptions {
  config: ServerConfig;
  /** 是否创建数据目录结构。测试会自备临时目录，可关掉。 */
  preparePaths?: boolean;
  /** 是否执行迁移。默认执行；测试若已手工建表可关掉。 */
  migrate?: boolean;
  /** 覆盖迁移目录（默认包内 `drizzle/`）。 */
  migrationsFolder?: string;
}

export async function createServices(options: CreateServicesOptions): Promise<Services> {
  const { config } = options;
  const paths = resolveDataPaths(config.cosightHome, config.workspacesRoot);

  if (options.preparePaths !== false) {
    ensureDataPaths(paths);
  }

  /*
   * 令牌在**启动时**备好，而不是等第一次请求再懒生成。
   *
   * 两个理由：一是模块作者要知道去哪拿令牌，文件在启动后就该存在（它本身就是
   * 接入线索）；二是懒生成会把"文件内容非法"这个错误推迟到运行期，变成一个
   * 莫名其妙的 401，而不是启动时点明文件与期望格式的失败。
   *
   * 放在 `preparePaths` 分支内：关掉建目录的调用方（测试自备目录、或把框架嵌进
   * 别的宿主）不该被写进一个意外的文件。此时令牌不存在，模块面 fail closed 到 401。
   */
  const moduleToken = new ModuleTokenStore(paths.moduleToken);
  if (options.preparePaths !== false) {
    moduleToken.ensure();
  }

  const handle = createDatabase(config.databaseUrl);
  if (options.migrate !== false) {
    await runMigrations(handle.db, options.migrationsFolder);
  }

  const credentials = new CredentialStore(paths.credentials);
  // 提成局部变量：模块面服务要复用同一个仓储实例，不该各建一个。
  const models = new ModelConfigRepository(handle.db, credentials);
  const ragKnowledge = new RagKnowledgeRepository(handle.db, credentials);
  const appState = new AppStateRepository(handle.db);
  const workspaces = new WorkspaceService({
    repository: new WorkspaceRepository(handle.db),
    appState,
    // 用 `paths.workspaces` 而不是 `config.workspacesRoot`：布局只有
    // `config/paths.ts` 一处定义，服务消费那个结果。
    workspacesRoot: paths.workspaces,
  });

  return {
    config,
    paths,
    handle,
    credentials,
    moduleToken,
    bridge: new BridgeSessionService(),
    appState,
    workspaces,
    // 只依赖工作区服务的 `findById`（`WorkspaceLocator`）：文件浏览不需要
    // "建目录 / 切生效项"那些能力，依赖面写窄一点，将来才看得清谁在读用户文件。
    workspaceFiles: new WorkspaceFileService({ workspaces }),
    // 平台与 timeout 都走默认值（读 `process`）：容器不应该替它决定"要不要弹窗"。
    directoryPicker: new DirectoryPickerService(),
    experts: new ExpertRepository(handle.db),
    models,
    agentProxies: new AgentProxyRepository(handle.db, credentials),
    ragKnowledge,
    moduleModels: new ModuleModelService(models, credentials),
    // 默认 API Key 属于服务端配置，交给模块面服务做"路由自己的优先、否则回落"。
    moduleRagKnowledge: new ModuleRagKnowledgeService(
      ragKnowledge,
      credentials,
      config.ragKnowledgeApiKey,
    ),
  };
}

/** 关闭底层连接。libsql 的连接必须显式关闭，否则进程无法干净退出。 */
export async function closeServices(services: Services): Promise<void> {
  services.handle.client.close();
}
