/**
 * 应用装配（D4 = A：Fastify + zod + OpenAPI）。
 *
 * 插件注册顺序有两处是**有意为之**，改动前请先读完注释：
 *
 * 1. `installErrorHandler` 必须在任何 `register` **之前**调用。之后调用的话，
 *    带 prefix 的路由插件已经建立了各自的子上下文，异常会落到 Fastify 默认
 *    处理器上——表现是校验失败返回 400（而非 422）、抛出的领域错误返回 500
 *    （而非 404/409），且响应体不带信封。这一条曾经实际踩过。
 * 2. `@fastify/swagger` 必须在所有路由之前注册，否则它收集不到 route schema，
 *    文档页会是空的。zod schema 经 `jsonSchemaTransform` 转成 JSON Schema。
 *
 * 关于**响应 schema**：这里只声明请求侧（params/querystring/body）的 schema。
 * 响应统一走信封（success/data/error/meta），若逐条声明 response schema，
 * 就要为每个接口重复一遍信封结构，且 fastify 的序列化器会按 schema 裁剪字段——
 * 契约字段一多就变成持续维护负担。代价是文档页里响应体只有通用信封说明，
 * 这是 v1 明确的取舍，已记入 architecture.md 的已知缺口。
 */

import path from 'node:path';

import cookie from '@fastify/cookie';
import cors from '@fastify/cors';
import rateLimit from '@fastify/rate-limit';
import fastifyStatic from '@fastify/static';
import swagger from '@fastify/swagger';
import swaggerUi from '@fastify/swagger-ui';
import Fastify, { type FastifyInstance } from 'fastify';
import {
  jsonSchemaTransform,
  serializerCompiler,
  validatorCompiler,
  type ZodTypeProvider,
} from 'fastify-type-provider-zod';
import { MODULE_FACE_BASE_PATH } from 'harness-shared/module-models';

import { installErrorHandler } from './plugins/error-handler';
import { decorateServices } from './plugins/services';
import { agentProxyRoutes } from './routes/agent-proxy';
import { bridgeRoutes } from './routes/bridge';
import { expertRoutes } from './routes/expert';
import { healthRoutes } from './routes/health';
import { modelRoutes } from './routes/model';
import { moduleFaceRoutes } from './routes/module-face';
import { moduleRoutes } from './routes/modules';
import { ragKnowledgeRoutes } from './routes/rag-knowledge';
import { workspaceRoutes } from './routes/workspace';
import { workspaceFileRoutes } from './routes/workspace-files';
import { workspacePickerRoutes } from './routes/workspace-picker';
import type { Services } from './services/container';

/** 单窗口请求上限。取值偏宽：本机单用户，前端滚动加载是正常流量。 */
const RATE_LIMIT_MAX = 600;
const RATE_LIMIT_WINDOW = '1 minute';

export interface BuildAppOptions {
  services: Services;
  /** false 关闭日志（测试用），或传入级别覆盖配置值。 */
  logger?: boolean;
}

export async function buildApp(options: BuildAppOptions): Promise<FastifyInstance> {
  const { services } = options;
  const { config } = services;

  const app = Fastify({
    logger:
      options.logger === false
        ? false
        : {
            level: config.logLevel,
            // 原始请求头里可能带 Authorization，日志只保留方法/路径/状态码。
            redact: ['req.headers.authorization', 'req.headers.cookie'],
          },
    trustProxy: false,
  }).withTypeProvider<ZodTypeProvider>();

  app.setValidatorCompiler(validatorCompiler);
  app.setSerializerCompiler(serializerCompiler);

  decorateServices(app, services);

  // 错误处理器必须在任何 register 之前装到根实例上。
  // 之后装的话，子上下文（每个带 prefix 的路由插件）已经建立，异常会落到
  // Fastify 默认处理器上：校验失败变 400、抛出的领域错误变 500，且都不带信封。
  const serveSpa = config.webDistDir !== null;
  installErrorHandler(app, { serveSpa });

  await app.register(cors, {
    origin: config.corsOrigins,
    credentials: true,
  });

  await app.register(cookie, {
    // 不启用签名：会话 id 本身就是 256 位随机凭据，再加一层 HMAC 只是换个
    // 对称密钥存到别处，没有增加实际安全性。
    hook: 'onRequest',
  });

  await app.register(rateLimit, {
    max: RATE_LIMIT_MAX,
    timeWindow: RATE_LIMIT_WINDOW,
  });

  await app.register(swagger, {
    openapi: {
      info: {
        title: 'Co-Sight Harness 框架 API',
        description: 'AI 工程使能中心框架后端：工作区、专家、模型、Agent 代理、模块与桥接。',
        version: '0.1.0',
      },
      servers: [{ url: `http://${config.host}:${config.port}` }],
      tags: [
        { name: 'health', description: '健康检查' },
        { name: 'workspace', description: '工作区（需求 2.1）' },
        {
          name: 'workspace-file',
          description: '工作区文件浏览（只读；额外要求来源为本机回环，见 workspace-design.md）',
        },
        {
          name: 'workspace-picker',
          description: '系统目录选择（服务端弹原生对话框；额外要求来源为本机回环）',
        },
        { name: 'expert', description: '专家（需求 2.2）' },
        { name: 'model', description: '模型配置（需求 2.3）' },
        { name: 'agent-proxy', description: 'Agent 代理配置（需求 2.3-1）' },
        { name: 'rag-knowledge', description: 'RAG 知识库跳转路由（单条生效）' },
        { name: 'module', description: '模块清单（C2 嵌入机制）' },
        { name: 'bridge', description: '模块桥接（D25）' },
        {
          name: 'framework-module',
          description:
            '模块面（对外，需本机令牌）：模型配置（含明文密钥，可读写）、工作区（可读写）与 RAG 知识库（只读）',
        },
      ],
    },
    transform: jsonSchemaTransform,
  });

  await app.register(swaggerUi, { routePrefix: '/api/docs' });

  await app.register(healthRoutes, { prefix: '/api' });
  await app.register(workspaceRoutes, { prefix: '/api/workspaces' });
  /*
   * 工作区文件浏览与上面同前缀，但**单独一个插件**——它的 `onRequest` 比其他浏览器面
   * 多一道回环校验（它吐的是用户文件内容，见该文件头）。合成一个插件的话，
   * 那道门禁要么管得比该管的宽，要么得在插件里按路径分支，两种都更容易写漏。
   */
  await app.register(workspaceFileRoutes, { prefix: '/api/workspaces' });
  /*
   * 系统目录选择，同样单独一个插件：它自带回环门禁（会在桌面上弹模态窗口，
   * 并把选中路径回给调用方，理由见 routes/workspace-picker.ts）。
   */
  await app.register(workspacePickerRoutes, { prefix: '/api/workspaces' });
  await app.register(expertRoutes, { prefix: '/api/experts' });
  await app.register(modelRoutes, { prefix: '/api/models' });
  await app.register(agentProxyRoutes, { prefix: '/api/agent-proxies' });
  await app.register(moduleRoutes, { prefix: '/api/modules' });
  await app.register(ragKnowledgeRoutes, { prefix: '/api/rag-knowledge' });
  await app.register(bridgeRoutes, { prefix: '/api/bridge' });
  /*
   * 模块面（对外）。与上面 `/api/models`、`/api/workspaces` 是**同一份数据的两个面**：
   * 浏览器面永不回传明文密钥，模块面带明文密钥但要求本机令牌。分开注册而不是给
   * 浏览器面挂条件分支，是为了让"密钥只从这一个前缀出去"在路由表上肉眼可查。
   *
   * 只注册一个 `moduleFaceRoutes`（它自己再挂 `/models`、`/workspaces`、`/rag-knowledge`），
   * 门禁就在那个插件的 `onRequest` 上——新加一个子树会自动继承，见其文件头。
   * 这里**不要**改成逐个注册子路由：那样每加一个面都要记得重新挂一遍门禁。
   */
  await app.register(moduleFaceRoutes, { prefix: MODULE_FACE_BASE_PATH });

  if (config.webDistDir !== null) {
    await app.register(fastifyStatic, {
      root: config.webDistDir,
      // 交给 404 处理器决定单页回退，静态插件不自行兜底，
      // 否则未命中的路径会被它直接判 404，SPA 深链接刷新就白屏。
      wildcard: false,
      /*
       * 产物里的文件 mtime 统一是 1970（打包追求可复现），而静态插件默认的
       * ETag 是「字节数 + mtime」。于是**新旧两版 index.html 只要字节数相同**，
       * ETag 就完全相同：浏览器回源时带上旧 ETag，服务端回 304，浏览器继续用
       * 指向旧 bundle 的缓存页面，旧资源又已被删掉 → 整页白屏且很难看出原因。
       * 关掉这两个校验器，缓存行为完全由下面的 cache-control 决定。
       */
      etag: false,
      lastModified: false,
      setHeaders(reply, filePath) {
        // 带哈希的构建产物内容变了文件名就变，可以永久缓存；
        // 其余文件（尤其 index.html）每次都回源，避免页面指向已删除的旧 bundle。
        const hashed = path.basename(path.dirname(filePath)) === 'assets';
        reply.header(
          'cache-control',
          hashed ? 'public, max-age=31536000, immutable' : 'no-cache',
        );
      },
    });
  }

  return app;
}
