import { createServer, type Server } from 'node:http';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { createApp } from './app.js';
import { settleOnBoot } from './boot-settle.js';
import { config } from './config/index.js';
import { resolveEngineAdapter } from './shared/engine/registry.js';
import { attachWsGateway, type WsGateway } from './shared/live/ws-gateway.js';
import { liveHub } from './shared/live/live-hub.js';
import { disconnect, prisma } from './shared/prisma/client.js';
import { messagesRepo } from './shared/store/messages.repo.js';
import { syncBundledBuiltinAgents } from './shared/workspace/bundled-builtin.js';
import { sessionService } from './modules/session/index.js';
import { agentService } from './modules/agent/index.js';

/** 退出兜底：在途连接可能挂住 close 回调，超时即强退。 */
const SHUTDOWN_TIMEOUT_MS = 10_000;

/** 已进入关闭序的标记：再次收到信号立即强退，不重跑收口。 */
let shuttingDown = false;

/**
 * 关闭序：先结算挂起，再断开实时连接、停止接收连接，最后断开数据库。
 *
 * 收口不保证完成：超时强退、再次收到信号立即强退，两路都以非零码结束。
 */
async function shutdown(server: Server, gateway: WsGateway, signal: string): Promise<void> {
  if (shuttingDown) {
    console.error(`[smart-factory] 再次收到 ${signal}，立即退出`);
    process.exit(1);
  }
  shuttingDown = true;
  console.log(`[smart-factory] 收到 ${signal}，正在退出…`);

  setTimeout(() => {
    console.error(`[smart-factory] 退出超时（${SHUTDOWN_TIMEOUT_MS}ms），强制退出`);
    process.exit(1);
  }, SHUTDOWN_TIMEOUT_MS).unref();

  const pending = await messagesRepo.abortAllPending('abort');
  for (const message of pending) {
    liveHub.settle(message.id, { decision: 'aborted' });
  }
  gateway.close();
  // 在途连接不会被 server.close 等到，直接断掉才能让 close 回调落地
  server.closeAllConnections();
  server.close(() => {
    void disconnect().then(() => process.exit(0));
  });
}

async function main(): Promise<void> {
  // 启动前校验引擎取值：不合法直接拒绝启动
  resolveEngineAdapter(config.engine);

  await prisma.$connect();
  await settleOnBoot();
  // 收养盘上已有、表里没有的智能体目录（幂等）：必须在开始接请求前完成，
  // 否则这段时间里 sessions/create 会把存量智能体判成 404
  await agentService.adoptExistingDirs();
  // 先把随模块分发的专家定义补进定义根（幂等，只刷定义文件），再由 seed 登记。
  // 顺序不能反：seed 只认定义根，盘上没有就当特性缺席。
  const bundled = syncBundledBuiltinAgents();
  const written = bundled.synced.filter((item) => item.files > 0);
  if (written.length > 0) {
    console.log(`[smart-factory] 内置专家定义同步：${written.map((item) => `${item.id}（${item.files} 个文件）`).join('、')}`);
  }
  // 登记内置智能体（幂等，按定义目录清单）：同样必须在接请求前完成
  await agentService.seedBuiltinAgents();
  // 技能库根目录：目录会话的 cwd（{skillsRoot}）必须存在；失败只记日志不阻断启动（10-skill-library.md §5）
  try {
    mkdirSync(join(config.skillsRoot, 'output', 'skills'), { recursive: true });
  } catch (error) {
    console.error('[smart-factory] 技能库目录初始化失败：', error);
  }

  const server = createServer(createApp());
  const gateway = attachWsGateway(server, {
    send: (input) => sessionService.sendMessage(input),
    abortRun: (input) => sessionService.abortRun(input.runId),
    respond: (input) => sessionService.respondMessage(input),
    respondApproval: (input) => sessionService.respondApproval(input),
    respondTool: (input) => sessionService.respondTool(input),
    switchModel: (input) => sessionService.switchModel(input),
    switchMode: (input) => sessionService.switchMode(input),
    switchEffort: (input) => sessionService.switchEffort(input),
    history: (input) => sessionService.history(input),
    subscribeInfo: (sessionId) => sessionService.subscribeInfo(sessionId),
  });

  server.listen(config.port, config.host, () => {
    // 通配地址下本机访问用回环（不用 localhost：部分机器会先解析到 ::1）；其它情况监听地址即访问地址。
    const wildcard = config.host === '0.0.0.0' || config.host === '::';
    const host = wildcard ? '127.0.0.1' : config.host;
    const base = `http://${host}:${config.port}`;
    console.log(`[smart-factory] server 已启动：监听 ${config.host}:${config.port}（本机 ${base}）`);
    console.log(`[smart-factory] 健康检查：${base}/api/smart-factory/v1/health`);
    console.log(`[smart-factory] 实时通道：ws://${host}:${config.port}${config.wsPath}`);
    console.log(`[smart-factory] 运行模式：${config.nodeEnv}`);
    if (wildcard) {
      console.log('[smart-factory] ⚠️ 监听全部地址且服务无鉴权，/fs/* 可浏览整机；仅限可信网络，只需本机访问时设 HOST=127.0.0.1');
    }
  });

  for (const signal of ['SIGINT', 'SIGTERM'] as const) {
    process.on(signal, () => {
      void shutdown(server, gateway, signal);
    });
  }
}

main().catch((error: unknown) => {
  console.error('[smart-factory] 启动失败：', error instanceof Error ? error.message : error);
  process.exit(1);
});
