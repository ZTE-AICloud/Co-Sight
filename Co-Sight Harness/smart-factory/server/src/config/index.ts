import 'dotenv/config';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

/**
 * 读正数环境变量：缺省用 fallback，非法值（非数值、0、负数、空串）直接抛错。
 *
 * 「显式优于隐式」：静默生效的非法值难排查（如 WS_HEARTBEAT_MS 退化成每秒忙轮询），
 * 启动即失败并把键名摆到台面上。
 */
export function positiveNumberFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined) return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`环境变量 ${name} 必须是正数，当前值：${JSON.stringify(raw)}`);
  }
  return value;
}

/** 与框架同一口径：COSIGHT_HOME 用 path.resolve，不展开 ~，相对路径按进程 cwd 解析。 */
const cosightHome = resolve(process.env.COSIGHT_HOME ?? join(homedir(), '.cosight-harness'));
// file: URL 统一用正斜杠（Windows 上 join 产出的反斜杠不是合法 URL 形态）
const databaseUrl = `file:${join(cosightHome, 'smart-factory.db').replaceAll('\\', '/')}`;

/** Prisma CLI 与 Client 都从这里读连接串；`.env` 不配置该项。 */
process.env.DATABASE_URL = databaseUrl;

/** 后端进程级配置，集中从环境变量读取，避免散落的 process.env 访问。 */
export const config = {
  host: process.env.HOST ?? '0.0.0.0',
  port: positiveNumberFromEnv('PORT', 4100),
  nodeEnv: process.env.NODE_ENV ?? 'development',
  corsOrigin: process.env.CORS_ORIGIN ?? '*',
  cosightHome,
  /** 数据根目录，与 cosightHome 同值。 */
  home: cosightHome,
  /**
   * 技能工坊根目录（10-skill-library.md §2）：目录会话的 cwd 就是它本身，
   * 技能库在其 `output/skills/` 下；env `SKILLS_ROOT` 可覆盖。
   * 曾定名 `skills/`，2026-10-22 评审改为 `skill-workshop/`（避免 `skills/output/skills` 两段重名）。
   */
  skillsRoot: resolve(process.env.SKILLS_ROOT ?? join(cosightHome, 'smart-factory', 'skill-workshop')),
  /**
   * 自由对话（不选智能体）的兜底目录：框架没有生效工作区时，会话的 cwd 落到这里，
   * 保证「没有工作区也能聊」。按需创建（见 session.service 的 resolveChatCwd）。
   * env `CHAT_ROOT` 可覆盖。
   */
  chatRoot: resolve(process.env.CHAT_ROOT ?? join(cosightHome, 'smart-factory', 'chat')),
  databaseUrl,
  /** 框架模块面基址；只读 GET，令牌从 {cosightHome}/.module-token 现读。 */
  frameworkBaseUrl: process.env.FRAMEWORK_BASE_URL ?? 'http://127.0.0.1:4300',
  /** 框架模块面单次请求超时（毫秒）；模型代理与工作区解析共用。 */
  frameworkTimeoutMs: positiveNumberFromEnv('FRAMEWORK_TIMEOUT_MS', 2000),
  /**
   * 知识库（RAG Studio）服务**根地址**，如 `http://rag-studio.example.com`。
   * 代理自己拼 `/api/co-knowledge/v1/agent/workflows`，所以这里不能带路径。
   * **兜底值**：框架「设置 → 知识库路由设置」有生效路由时用那条的 `routeUrl` origin
   * （见 `modules/knowledge/knowledge-source.ts`）；两边都没有才是空串 → 502 说清楚，不猜默认值。
   */
  coKnowledgeBaseUrl: (process.env.CO_KNOWLEDGE_BASE_URL ?? '').trim().replace(/\/+$/, ''),
  /** 知识库 Agent API Key（形如 `ragk_...`），走 `X-API-Key`；只留在服务端，不下发浏览器。**兜底值**，来源优先级同上一项。 */
  coKnowledgeApiKey: (process.env.CO_KNOWLEDGE_API_KEY ?? '').trim(),
  /** 知识库列表请求超时（毫秒）；上游是内网服务，留足余量。 */
  coKnowledgeListTimeoutMs: positiveNumberFromEnv('CO_KNOWLEDGE_LIST_TIMEOUT_MS', 8000),
  engine: process.env.ENGINE ?? 'claude-cli',
  /**
   * Claude Code CLI 的显式路径（`--claude <path>` 同义）。空串表示按 PATH 解析 `claude` /
   * `claude.exe` / `claude.cmd`。CLI 由用户自行安装，本服务不随包分发。
   */
  claudeCodePath: (process.env.CLAUDE_CODE_PATH ?? '').trim(),
  /** 创建后自动生成名称 / 描述 / 标签；`AUTO_META=0` 关闭（测试默认关闭，避免打真网络）。 */
  autoMetaEnabled: process.env.AUTO_META !== '0',
  /** 自动命名的单轮模型调用超时（毫秒）。 */
  metadataTimeoutMs: positiveNumberFromEnv('METADATA_TIMEOUT_MS', 30_000),
  wsPath: '/api/smart-factory/v1/ws',
  /** 心跳扫描间隔：客户端按此间隔发 `ping` 帧，超过 2 倍没收到任何上行帧即断开（4.06 实时通道 §2）。 */
  wsHeartbeatMs: positiveNumberFromEnv('WS_HEARTBEAT_MS', 30_000),
  wsMaxBufferedBytes: positiveNumberFromEnv('WS_MAX_BUFFERED_BYTES', 4 * 1024 * 1024),
  /** /artifacts/file 读文本的大小上限（字节），超限 413；下载不受限 */
  artifactMaxFileBytes: positiveNumberFromEnv('ARTIFACT_MAX_FILE_BYTES', 2 * 1024 * 1024),
  /** 评估报告必需 JSON/JSONL 的读取上限（字节），超限 413（4.09-评估报告 §9） */
  evaluationMaxJsonBytes: positiveNumberFromEnv('EVALUATION_MAX_JSON_BYTES', 5 * 1024 * 1024),
  /** 单个上传文件的大小上限（字节），超限 413（09-file.md §2） */
  filesMaxFileBytes: positiveNumberFromEnv('FILES_MAX_FILE_BYTES', 10 * 1024 * 1024),
  /** REST 统一前缀（4.02 通用规范 §1）；files 服务拼可访问 URL 也用它 */
  apiPrefix: '/api/smart-factory/v1',
} as const;

export const isProduction = config.nodeEnv === 'production';
