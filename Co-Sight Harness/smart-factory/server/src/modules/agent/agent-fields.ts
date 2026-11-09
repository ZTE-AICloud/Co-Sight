import { BadRequestError } from '../../shared/errors.js';
import { isKnowledgeWorkflowId } from '../../shared/knowledge/workflow-id.js';
import type { AgentProductionStatus, AgentSource } from '../../shared/types/index.js';

/**
 * 智能体可变字段的入参校验。
 *
 * 从 agent.service.ts 原样搬出（无行为改动）：boot seed 的内置清单校验（shared/workspace/builtin-agents.ts）
 * 与 CRUD 入参校验用同一套规则，而 agent.service 反向依赖 session.service，
 * builtin-agents.ts 不能去 import 它，所以抽到这个无依赖的叶子模块。
 */

export const NAME_MAX = 40;
export const DESCRIPTION_MAX = 120;
/** 封面图 URL 的长度上限。给得松是因为它是一条地址（含域名、路径、可能的签名查询串），不是展示文本。 */
export const ICON_MAX = 512;
/** 缺省没有封面：前端据此落到「名称首字」的兜底头像。 */
export const DEFAULT_ICON = '';

/**
 * 单个标签的长度上限。标签是筛选用的短词，不是第二段描述。
 *
 * 10 是展示面倒推出来的（2026-10-16 从 20 收紧）：卡片上标签行只有一行、还要给
 * 「+N」留位置，最窄的一列（栅格 300px 减内边距 = 268px）里，10 字标签约 145px，
 * 和「+N」一起放得下；20 字标签实测 250px，会把「+N」挤出可视区、浮层就点不开了。
 */
export const TAG_MAX = 10;
/** 一个智能体的标签数量上限。多了卡片上排不下，筛选也失去意义。 */
export const TAGS_MAX = 10;

/**
 * 标签里不许出现的四个字符 -每个都对应一个具体的坏法，不是洁癖：
 *
 * - `"`：过滤靠「元素两侧的引号」定界（见 agents.repo 的 tag 过滤），tag 自带引号会破坏边界；
 * - `\`：JSON 转义序列的引入符，`"a\\b"` 让引号定界读不准；
 * - `%` `_`：Prisma 的 contains 在 SQLite 上**不转义 LIKE 通配符**（`contains: '50%'` 发出去就是
 *   `LIKE '%50%%'`，会连 `5000` 一起命中） - 这是 SQLite 上唯一能保住「精确匹配」的办法。
 */
export const TAGS_FORBIDDEN = /["\\%_]/;

/**
 * 保留标签：来源不是标签，这两颗不许由用户写进 `tags`。
 *
 * 「内置」对应 `source='builtin'`、「自定义」对应 `source='user'` —— 它们该由来源字段
 * 派生，而不是让任何写入口打一颗就能冒充。服务端在这里拒绝，前端只负责把话说在输入框手边。
 */
export const RESERVED_TAGS: readonly string[] = ['内置', '自定义'];

/** 是不是保留标签。内置清单也会经过它（作者若把来源写进清单，读清单时剥掉）。 */
export function isReservedTag(tag: string): boolean {
  return RESERVED_TAGS.includes(tag);
}

/** 来源取值；`source` 只由服务端写，列表查询用它做筛选。 */
export const AGENT_SOURCES = ['user', 'builtin'] as const satisfies readonly AgentSource[];

/**
 * 产物状态取值；列表查询用它做筛选（`?status=`）。
 *
 * 与 `AgentProductionStatus` 一一对应，取不到的那个 `null`（读盘失败的降级值）**不在枚举里**：
 * 它是「读不出来」而不是一种状态，既不能传进来筛，也不该被当成可查询的取值。
 */
export const AGENT_STATUSES = ['not_started', 'building', 'blocked', 'failed', 'completed'] as const satisfies readonly AgentProductionStatus[];

/** 展示名：必填、trim 后 1–40 字。 */
export function readName(value: unknown): string {
  if (typeof value !== 'string' || value.trim() === '') throw new BadRequestError('name 必填', 'error.bad_request.required', { name: 'name' });
  const name = value.trim();
  if (name.length > NAME_MAX) throw new BadRequestError(`name 不能超过 ${NAME_MAX} 字`, 'error.bad_request.too_long', { name: 'name', max: NAME_MAX });
  return name;
}

/**
 * 描述：可空。**空串是「清空」而不是「没给」** -update 的两种意图不能混（契约 5.01）。
 */
export function readDescription(value: unknown): string {
  if (typeof value !== 'string') throw new BadRequestError('description 必须是字符串');
  const description = value.trim();
  if (description.length > DESCRIPTION_MAX) throw new BadRequestError(`description 不能超过 ${DESCRIPTION_MAX} 字`, 'error.bad_request.too_long', { name: 'description', max: DESCRIPTION_MAX });
  return description;
}

/**
 * 封面图：一个 HTTP(S) 地址，**不解析、不校验形态、不做枚举**，后端只管长度。
 *
 * 空串是一个**有意义的取值**（「没有封面」，前端落到名称首字的兜底头像），
 * 所以这里不把空白当成「没给」 - 否则 update 就没办法把封面清掉，
 * 而「清掉」正是前端换掉一张图之后会做的动作（与 description 同一口径）。
 */
export function readIcon(value: unknown): string {
  if (typeof value !== 'string') throw new BadRequestError('icon 必须是字符串');
  const icon = value.trim();
  if (icon.length > ICON_MAX) throw new BadRequestError(`icon 不能超过 ${ICON_MAX} 字`, 'error.bad_request.too_long', { name: 'icon', max: ICON_MAX });
  return icon;
}

/**
 * 知识检索工作流 id：**空串是「取消」**（与 description / icon 的空串同一口径），
 * 非空时只允许 `[A-Za-z0-9_-]{1,128}` —— 这个值会被拼进产物脚本的 Python 字面量。
 *
 * 不做「这个 id 在 RAG Studio 里一定存在」的校验：列表在另一个服务，创建 / 更新
 * 不该被它的可用性绑住；前端只从已发布列表里选，写入口保持形态校验。
 */
export function readKnowledgeWorkflowId(value: unknown): string {
  if (typeof value !== 'string') throw new BadRequestError('knowledgeWorkflowId 必须是字符串');
  const id = value.trim();
  if (!isKnowledgeWorkflowId(id)) {
    throw new BadRequestError('knowledgeWorkflowId 形态非法：只允许 [A-Za-z0-9_-]{1,128}');
  }
  return id;
}

/** 单个标签：trim 后 1–10 字、不含禁用字符。`what` 只用来拼报错措辞（`tags[2]` / `tag`）。 */
export function readTag(value: unknown, what: string): string {
  if (typeof value !== 'string') throw new BadRequestError(`${what} 必须是字符串`);
  const tag = value.trim();
  if (tag === '') throw new BadRequestError(`${what} 不能为空`);
  if (isReservedTag(tag)) throw new BadRequestError(`${what} 不能使用保留标签「${tag}」`, 'error.bad_request.reserved_tag', { tag });
  if (tag.length > TAG_MAX) throw new BadRequestError(`${what} 不能超过 ${TAG_MAX} 字：${tag}`);
  if (TAGS_FORBIDDEN.test(tag)) throw new BadRequestError(`${what} 不能含 " \\ % _ 这四个字符：${tag}`);
  return tag;
}

/**
 * 标签数组：逐项校验 → 去重 → 数量上限。
 *
 * 去重按**字节精确**（与 name 的唯一性口径一致：大小写敏感、不做 Unicode 归一），且**保序** -
 * 顺序是调用方给的，后端不重排（卡片上按什么顺序显示是展示决定）。
 *
 * **传 `[]` 是「清空标签」**，与 description / icon 的空串同构：update 的「清空」与「不改」
 * 靠「给没给这个字段」分开，而不是靠「给的值空不空」。
 */
export function readTags(value: unknown): string[] {
  if (!Array.isArray(value)) throw new BadRequestError('tags 必须是字符串数组');

  const tags: string[] = [];
  value.forEach((item, index) => {
    const tag = readTag(item, `tags[${index}]`);
    if (!tags.includes(tag)) tags.push(tag);
  });

  if (tags.length > TAGS_MAX) throw new BadRequestError(`tags 不能超过 ${TAGS_MAX} 个（去重后 ${tags.length} 个）`);
  return tags;
}
