/**
 * 服务端进程入口。
 *
 * 启动顺序：读配置 → 建目录 → 开库并迁移 → 首次种子 → 装配 → 监听。
 * 退出时显式关闭 HTTP 与数据库连接：libsql 的连接不关会让进程吊住不退，
 * 而"Ctrl-C 之后进程还在"是最容易被忽略、又最影响日常开发的问题。
 */

import { MODULE_FACE_BASE_PATH } from 'harness-shared/module-models';

import { buildApp } from './app';
import { loadConfig } from './config/env';
import { checkSecretFileMode } from './lib/file-mode';
import { seedDefaultRagKnowledge, seedDefaultWorkspace, seedPresetExperts } from './seed/seed';
import { closeServices, createServices } from './services/container';

/**
 * 监听 `0.0.0.0` / `::` 时不能用它拼访问 URL——那是通配地址，不是可路由的目的地，
 * 浏览器会直接拦截。日志里拆成两段：监听地址照实打（`0.0.0.0:4300`），
 * 可点开的地址换成回环。
 */
function reachableHost(host: string): string {
  return host === '0.0.0.0' || host === '::' ? '127.0.0.1' : host;
}

async function main(): Promise<void> {
  const config = loadConfig();
  const services = await createServices({ config });

  // 只在表为空时写入（见 seed.ts）。返回值用于日志，不阻断启动。
  const seed = await seedPresetExperts(services);

  const app = await buildApp({ services });

  /*
   * 默认工作区：一个都没有时建一个并设为当前，让用户开箱就有地方放会话。
   *
   * 放在 buildApp 之后是为了用 app.log（预置专家那一步还没有 logger 可用）。
   * **失败不阻断启动**：建目录可能因为权限、磁盘满失败，而"没有默认工作区"只是
   * 少一层便利——用户仍可以在界面上新建。真实原因必须留在日志里，别吞掉。
   */
  try {
    const workspaceSeed = await seedDefaultWorkspace(services);
    if (workspaceSeed.created) {
      app.log.info(
        { workspaceId: workspaceSeed.workspace?.id, directory: workspaceSeed.workspace?.directory },
        '已创建默认工作区',
      );
    }
  } catch (error: unknown) {
    app.log.warn({ err: error }, '创建默认工作区失败，可在界面上手工新建');
  }

  /*
   * 默认知识库路由：一条都没有时写入出厂那条，并设为当前可用。
   *
   * 与默认工作区同样"失败不阻断启动"：写密钥文件可能因权限失败，而缺一条默认路由
   * 只是少一层便利（侧栏「知识库」会直接把人送到设置里的新增表单）。
   */
  try {
    const ragSeed = await seedDefaultRagKnowledge(services);
    if (ragSeed.created) {
      app.log.info({ baseId: ragSeed.base?.id, routeUrl: ragSeed.base?.routeUrl }, '已创建默认知识库路由');
    }
  } catch (error: unknown) {
    app.log.warn({ err: error }, '创建默认知识库路由失败，可在设置里手工新增');
  }

  let shuttingDown = false;
  const shutdown = async (signal: string): Promise<void> => {
    if (shuttingDown) {
      return;
    }
    shuttingDown = true;
    app.log.info({ signal }, '收到退出信号，正在关闭');
    try {
      await app.close();
      await closeServices(services);
      process.exit(0);
    } catch (error: unknown) {
      app.log.error({ err: error }, '关闭过程出错');
      process.exit(1);
    }
  };

  process.on('SIGINT', () => {
    void shutdown('SIGINT');
  });
  process.on('SIGTERM', () => {
    void shutdown('SIGTERM');
  });

  await app.listen({ host: config.host, port: config.port });

  if (seed.inserted > 0) {
    app.log.info({ inserted: seed.inserted }, '已写入预置专家');
  }
  app.log.info(
    `监听 ${config.host}:${config.port}；API 文档：http://${reachableHost(config.host)}:${config.port}/api/docs`,
  );

  /*
   * 绑全部网卡时把代价说清楚。本服务没有登录鉴权（D25 假定本机单用户），
   * 模型配置里是明文密钥；工作区文件浏览那几个接口虽然只放行回环来源，
   * 但这也是唯一一道闸。启动日志里就该看见这句话，而不是等出事再回头翻文档。
   */
  if (config.host === '0.0.0.0' || config.host === '::') {
    app.log.warn(
      `监听全部地址（${config.host}）且服务无登录鉴权，模型密钥为明文；仅限可信网络，只需本机访问时设 COSIGHT_HOST=127.0.0.1`,
    );
  }

  /*
   * 模块面接口已就绪，**这里只打路径，永远不打令牌值**。
   *
   * 打路径是有必要的：模块作者（以及排查"为什么一直 401"的人）需要知道去哪拿令牌，
   * 而 `$COSIGHT_HOME` 在开发机上经常被指向别处，光看代码猜不出来。
   */
  app.log.info(
    {
      moduleTokenFile: services.paths.moduleToken,
      moduleApi: `http://${reachableHost(config.host)}:${config.port}${MODULE_FACE_BASE_PATH}`,
    },
    '模块面接口已就绪（models / workspaces，需 Authorization: Bearer <令牌文件内容>）',
  );

  /*
   * 工作区根目录也打一条。它与 `$COSIGHT_HOME` 可以被拆开（`COSIGHT_WORKSPACES_ROOT`），
   * 而"用户文件到底被建到哪去了"是这套东西里唯一会让人真的去找磁盘的问题——
   * 提前把答案写进启动日志，比事后从配置里反推快得多。
   */
  app.log.info({ workspacesRoot: services.paths.workspaces }, '工作区根目录');

  /*
   * 权限自检。`ensureDirectory` 在非 POSIX 文件系统上会吞掉 chmod 失败
   * （见 `config/paths.ts`），所以这里实测一次而不是相信"我们设了 0600"。
   * 只警告不阻断：这与既有取舍一致（权限收紧失效不该让服务起不来），
   * 但必须让人在启动日志里看得见。
   *
   * 判定本身在 lib/file-mode.ts，因为要区分"权限太宽"与"这个平台根本没有
   * POSIX 权限位"：Windows 上 `statSync().mode` 对普通文件恒为 0o666，
   * 两者混在一起会变成每次启动都刷一条假告警。
   */
  const modeCheck = checkSecretFileMode(services.moduleToken.fileMode(), process.platform);
  if (modeCheck.status === 'permissive') {
    app.log.warn(
      { moduleTokenFile: services.paths.moduleToken, mode: modeCheck.mode.toString(8) },
      '模块面令牌文件权限不是 0600，同机其他用户可能读到它',
    );
  } else if (modeCheck.status === 'not-applicable') {
    app.log.info(
      { moduleTokenFile: services.paths.moduleToken },
      '当前平台不用 POSIX 权限位（Windows 由 ACL 控制访问），令牌文件权限自检跳过',
    );
  }
}

main().catch((error: unknown) => {
  // 启动失败时 Fastify 的 logger 可能尚未初始化，直接写 stderr。
  const detail = error instanceof Error ? (error.stack ?? error.message) : String(error);
  process.stderr.write(`服务启动失败：${detail}\n`);
  process.exit(1);
});
