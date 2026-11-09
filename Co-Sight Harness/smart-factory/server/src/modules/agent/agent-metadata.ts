import { basename } from 'node:path';
import { config } from '../../config/index.js';
import { ConflictError } from '../../shared/errors.js';
import { requestText } from '../../shared/llm/anthropic-messages.js';
import { agentsRepo, type AgentUpdateData } from '../../shared/store/agents.repo.js';
import type { AgentRow } from '../../shared/types/index.js';
import { resolveModelConfig } from '../model/model.service.js';
import { DESCRIPTION_MAX, TAGS_FORBIDDEN, TAGS_MAX, TAG_MAX, isReservedTag } from './agent-fields.js';

/**
 * 创建后的元数据自动刷新（「会话自动改标题」的智能体版）。
 *
 * 创建那一刻先用兜底值（首页 `deriveName` 的正则名字、需求截断、空标签），后台立刻
 * 拿用户那句需求生成一次 name / description / tags 并落库；失败就保持兜底值。
 * **只跑一次、不由前端触发、不新增 HTTP 端点。**
 *
 * 三条边界：
 * - 落库用 `updatedAt` 条件更新：生成的那几秒里用户手改了任何字段就放弃，绝不覆盖手改；
 * - 名字撞同一工作区时挂 4 位短码（与首页 `create-agent.ts` 同一约定），唯一索引仍是兜底；
 * - 三个字段与现值完全一致时不写库，避免无意义地刷新 `updatedAt`、把卡片顶到最前。
 */

/** 卡片标题的宽度上限；接口上限是 40（`NAME_MAX`），AI 名字照首页口径收在 24。 */
const AUTO_NAME_MAX = 24;

const MAX_TOKENS = 800;
const DEMAND_MAX = 4000;
const VOCABULARY_MAX = 30;
const ATTACHMENTS_MAX = 20;

/**
 * 首页拼在正文前的命令（`/agent-genesis:harness-create `）与知识检索参数
 * （`--knowledge-workflow-id <id>`）；名字与描述不该出现它们。
 *
 * 与前端 `web/src/shared/commands/harness-prompt.ts` 的 `LEAD_COMMAND` 同一形态；
 * 两个包各自维护一份，改一边时记得改另一边。
 */
const LEAD_COMMAND = /^\/[A-Za-z0-9._-]+(?::[A-Za-z0-9._-]+)?(?:\s+--knowledge-workflow-id\s+[A-Za-z0-9_-]+)?\s+/u;

export interface MetadataSuggestion {
  name: string;
  description: string;
  tags: string[];
}

export interface MetadataContext {
  currentName: string;
  currentDescription: string;
  demand: string;
  attachments: string[];
  vocabulary: string[];
}

/** 后台入口：不阻塞请求，失败只记日志。`AUTO_META=0` 时整体关闭（测试默认关闭）。 */
export function scheduleMetadataRefresh(agentId: string, modelId: string): void {
  if (!config.autoMetaEnabled) return;
  void refreshMetadata(agentId, modelId).catch((error: unknown) => {
    console.warn(
      `[smart-factory] 自动命名失败（${agentId}）：${error instanceof Error ? error.message : String(error)}`,
    );
  });
}

export async function refreshMetadata(agentId: string, modelId: string): Promise<void> {
  const agent = await agentsRepo.findById(agentId);
  if (agent === null || agent.source !== 'user') return;

  const demand = stripLeadCommand(agent.initialInput).trim();
  const attachments = agent.initialAttachments.slice(0, ATTACHMENTS_MAX).map((path) => basename(path));
  // 既没正文也没附件：没有可依据的内容，不花这次调用
  if (demand === '' && attachments.length === 0) return;

  const vocabulary = topTags(await agentsRepo.listTags(agent.workspaceId ?? undefined));
  const { system, user } = buildMetadataPrompt({
    currentName: agent.name,
    currentDescription: agent.description,
    demand: truncate(demand, DEMAND_MAX),
    attachments,
    vocabulary,
  });

  const model = await resolveModelConfig(modelId);
  const text = await requestText({
    model,
    system,
    user,
    maxTokens: MAX_TOKENS,
    timeoutMs: config.metadataTimeoutMs,
  });

  const suggestion = sanitizeSuggestion(text);
  if (suggestion === null) throw new Error('模型输出不是可用的元数据 JSON');

  await persist(agent, suggestion);
}

/* ── 上下文与提示词 ─────────────────────────────────────────────────────── */

export function stripLeadCommand(text: string): string {
  return text.replace(LEAD_COMMAND, '').trim();
}

function topTags(rows: string[][]): string[] {
  const counts = new Map<string, number>();
  for (const tags of rows) for (const tag of tags) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  return [...counts]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, VOCABULARY_MAX)
    .map(([tag]) => tag);
}

export function buildMetadataPrompt(context: MetadataContext): { system: string; user: string } {
  const system = [
    '你是智能体目录的元数据编辑。根据给定资料生成展示名称、一句话描述和分类标签。',
    '只输出一个 JSON 对象，不要 Markdown 代码块、不要解释、不要多余字段：',
    '{"name": "...", "description": "...", "tags": ["..."]}',
    '',
    '规则：',
    '- name：2–16 个汉字（外文同义），名词短语，不带引号 / 书名号，不以「这是一个」开头；',
    `- description：一句话，不超过 ${DESCRIPTION_MAX} 字，说清「给谁、做什么、产出什么」；`,
    `- tags：3–5 个分类短词，每个不超过 ${TAG_MAX} 字，不含标点、引号、反斜杠、% 或 _，不要用「内置」「自定义」；`,
    '- 优先复用【已有标签】里的词，没有合适的再新造；',
    '- 语言与用户需求一致；只依据资料，不编造资料里没有的能力。',
  ].join('\n');

  const sections: string[] = [];
  if (context.currentName !== '') sections.push(`【当前名称】${context.currentName}`);
  if (context.currentDescription !== '') sections.push(`【当前描述】${context.currentDescription}`);
  if (context.demand !== '') sections.push(`【用户需求原文】${context.demand}`);
  if (context.attachments.length > 0) sections.push(`【附件文件名】${context.attachments.join('、')}`);
  if (context.vocabulary.length > 0) sections.push(`【已有标签】${context.vocabulary.join('、')}`);

  return { system, user: sections.join('\n\n') };
}

/* ── 解析与清洗 ─────────────────────────────────────────────────────────── */

/** 剥掉代码围栏 / 前后解释，取第一个 `{` 到最后一个 `}`；不可解析返回 null。 */
export function parseJsonObject(text: string): Record<string, unknown> | null {
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  try {
    const parsed: unknown = JSON.parse(text.slice(start, end + 1));
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** 模型文本 → 可落库的元数据。name 不可用即整体失败；description / tags 允许缺省。 */
export function sanitizeSuggestion(text: string): MetadataSuggestion | null {
  const raw = parseJsonObject(text);
  if (raw === null) return null;

  const name = truncate(cleanName(raw.name), AUTO_NAME_MAX);
  if (name === '') return null;

  return {
    name,
    description: truncate(cleanText(raw.description), DESCRIPTION_MAX),
    tags: sanitizeTags(raw.tags),
  };
}

function cleanName(value: unknown): string {
  if (typeof value !== 'string') return '';
  return cleanText(value)
    .replace(/^[「『"'（(【[]+/u, '')
    .replace(/[」』"'）)】\]]+$/u, '')
    .replace(/[。！？.!?]+$/u, '')
    .trim();
}

function cleanText(value: unknown): string {
  if (typeof value !== 'string') return '';
  return value.replace(/\s+/gu, ' ').trim();
}

function sanitizeTags(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const tags: string[] = [];
  for (const item of value) {
    if (typeof item !== 'string') continue;
    const tag = item.trim().replace(/^#+/u, '').trim();
    if (tag === '' || tag.length > TAG_MAX || TAGS_FORBIDDEN.test(tag) || isReservedTag(tag)) continue;
    if (!tags.includes(tag)) tags.push(tag);
    if (tags.length >= TAGS_MAX) break;
  }
  return tags;
}

/** 按码点退到边界再截断（`slice` 会把代理对劈成半个 emoji），长度仍按 UTF-16 码元算。 */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  let head = '';
  for (const char of text) {
    if (head.length + char.length > max - 1) break;
    head += char;
  }
  return `${head}…`;
}

/* ── 落库 ───────────────────────────────────────────────────────────────── */

async function persist(agent: AgentRow, suggestion: MetadataSuggestion): Promise<void> {
  const tags = suggestion.tags.length > 0 ? suggestion.tags : undefined;
  const description = suggestion.description !== '' ? suggestion.description : undefined;
  if (
    suggestion.name === agent.name &&
    (description === undefined || description === agent.description) &&
    (tags === undefined || sameTags(tags, agent.tags))
  ) {
    return;
  }

  const data: AgentUpdateData = {
    name: suggestion.name,
    ...(description === undefined ? {} : { description }),
    ...(tags === undefined ? {} : { tags }),
  };

  try {
    if (await write(agent, data)) logApplied(agent.id, data.name ?? '', suggestion.tags.length);
  } catch (error) {
    if (!(error instanceof ConflictError)) throw error;
    // 同一工作区已有同名：挂短码再试一次（唯一索引兜底，短码撞上的概率约百万分之一）
    const retry = { ...data, name: withShortCode(suggestion.name) };
    if (await write(agent, retry)) {
      logApplied(agent.id, retry.name ?? '', suggestion.tags.length, '（重名，已挂短码）');
    }
  }
}

/** 条件更新：基线是生成开始时的 `updatedAt`；期间被改过 / 已删就不写，返回 false（放弃）。 */
async function write(agent: AgentRow, data: AgentUpdateData): Promise<boolean> {
  return (await agentsRepo.updateIfUnchanged(agent.id, data, agent.updatedAt)) !== null;
}

function logApplied(agentId: string, name: string, tagCount: number, note = ''): void {
  console.log(`[smart-factory] 自动命名 ${agentId} → ${name}（${tagCount} 个标签）${note}`);
}

function sameTags(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((tag, index) => tag === b[index]);
}

function withShortCode(base: string): string {
  const tail = ` ${Math.random().toString(36).slice(2, 6).padEnd(4, '0')}`;
  return `${truncate(base, AUTO_NAME_MAX - tail.length)}${tail}`;
}
