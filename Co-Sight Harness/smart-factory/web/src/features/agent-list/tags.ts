/**
 * 标签的输入规则 —— **照后端抄的**，正本是 `server/src/modules/agent/agent.service.ts`
 * 的 `readTag` / `readTags`（契约 5.01 的 `Agent.tags`）。
 *
 * 前端先拦一道不是替后端把关（它照样会拦），是为了**把话说在用户手边**：后端报的是
 * `tags[2] 不能含 " \ % _ 这四个字符：a_b` —— 用户根本看不见输入框里哪个字犯了规。
 *
 * 规则只写这一处：输入时的提示与「能不能保存」的判断都用它，免得两边口径分叉。
 */

import { msg } from '../../i18n/useI18n';
import { isReservedTag } from '../../shared/agent-source';

/** 单个标签的长度上限（与后端 `TAG_MAX` 一致：10 是卡面倒推出来的，见那边注释）。 */
export const TAG_MAX = 10;

/** 标签数量上限（与后端 `TAGS_MAX` 一致）。 */
export const TAGS_MAX = 10;

/** 禁用字符：`"` 破坏过滤的引号定界、`\` 是 JSON 转义符、`%` `_` 是 LIKE 的通配符。 */
const FORBIDDEN = /["\\%_]/;

/**
 * `raw` 能不能加进 `tags`：返回不能加的原因，`null` = 可以。
 *
 * `raw` 由调用方 trim 过 —— 空串是「还没输入」不是「一个空标签」，走不到这儿。
 * **不含数量上限那条**：到 `TAGS_MAX` 时输入框直接禁掉（见 EditAgentDialog），
 * 压根不会有踌躇满志的草稿等着被拒。
 */
export function tagProblem(raw: string, tags: string[]): string | null {
  if (raw.length > TAG_MAX)
    return msg('agentList.tagProblem.tooLong', { max: TAG_MAX, length: raw.length });
  if (FORBIDDEN.test(raw)) return msg('agentList.tagProblem.forbidden');
  // 来源由 `Agent.source` 字段表达，不再是一颗标签：`内置` / `自定义` 是保留字，
  // 后端写入侧同样一律 400（见 agent-fields.ts 的 RESERVED_TAGS）。
  if (isReservedTag(raw)) return msg('agentList.tagProblem.source', { tag: raw });
  if (tags.includes(raw)) return msg('agentList.tagProblem.duplicate');
  return null;
}
