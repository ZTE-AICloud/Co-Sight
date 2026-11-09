/**
 * 工坊首条消息的拼装（`docs/capability-routing.md` §3.3）。
 *
 * 纯函数、不碰 React：这是这一页唯一一条「产品约定」—— 命令由页面拼，正文由用户写，
 * 只在**这一场的第一条**加。放在这里是为了能单独验（也方便以后换命令 / 改命名规则）。
 *
 * - 创建场用 `/agent-genesis:skill-foundry`，**不带 `--mode`**：模式由 skill-foundry
 *   从输入语义判定，伪造参数会把它带进另一条分支（它的 SKILL.md 就是这么约定的）。
 * - 优化场用 `/skill-optimizer:skill_optimize --mode optimize`（命令与 mode 在
 *   `SKILL_OPTIMIZE` 里，见 preset-commands）：技能路径按它的 `--skill-path` 传，
 *   正文按 `--expert-guidance` 传 —— 那是它唯一认的自然语言入参，写在命令后面
 *   的裸文本它不解析。
 * - 优化目标是**绝对路径**（`<path>/<version>/SKILL.md`，没有版本目录时少一层）：
 *   两路来源可能同名，名字选不中唯一的那一个。
 * - 创建场的正文允许为空（首页可以只挂附件就把这句话交过来）。
 */

import type { Skill } from '../../shared/api/skills';
import { SKILL_OPTIMIZE } from '../../shared/commands/preset-commands';

/** 创建场的命令。它是一段 prompt，不是 UI 文案，所以不进 i18n 词表 */
export const SKILL_FOUNDRY_COMMAND = '/agent-genesis:skill-foundry';

export type WorkshopMode = 'create' | 'optimize';

/** 优化时传给 skill_optimize 的 SKILL.md 绝对路径（路径尾的 `/` 先去掉，免得拼出 `//`） */
export function skillMdPath(skill: Pick<Skill, 'path' | 'version'>): string {
  const base = skill.path.replace(/\/+$/u, '');
  return skill.version === '' ? `${base}/SKILL.md` : `${base}/${skill.version}/SKILL.md`;
}

/**
 * 把一个值包成命令行参数。
 *
 * 路径可能带空格，正文更是随用户写：换行折成空格（留在参数里会把后半句切成另一个
 * 参数），`\` 与 `"` 转义 —— 否则「改成 "先结论" 的格式」会在第一个引号处截断。
 */
function quoteArg(value: string): string {
  const flat = value.replace(/\s*\n\s*/gu, ' ');
  return `"${flat.replace(/\\/gu, '\\\\').replace(/"/gu, '\\"')}"`;
}

/**
 * 优化这一场要发的那句话：命令 + 目标 + 要求。
 *
 * 三个入口共用一份：工坊的首条消息、首页「优化」落到智能体设计页的 replay、
 * 技能库卡「优化」的 replay。三处各写一遍必然漂移（曾经就是一处写命令、
 * 一处写「优化这个技能：<path>」）。
 *
 * 要求可以为空（只选技能不写要求是合法的一次发送）—— 这时不带 `--expert-guidance`。
 */
export function composeOptimizeMessage(mdPath: string, body: string): string {
  const head = `${SKILL_OPTIMIZE} --skill-path ${quoteArg(mdPath)}`;
  const text = body.trim();
  return text === '' ? head : `${head} --expert-guidance ${quoteArg(text)}`;
}

/** 这一场的第一条消息。`skill` 为 null 时按创建场处理 */
export function composeFirstMessage(
  mode: WorkshopMode,
  body: string,
  skill: Pick<Skill, 'path' | 'version'> | null,
): string {
  const text = body.trim();

  if (mode === 'optimize' && skill !== null) return composeOptimizeMessage(skillMdPath(skill), text);

  // 只挂附件、没写正文时不要把「：」留在句尾（会跟着附件一起发出去）
  return text === '' ? `${SKILL_FOUNDRY_COMMAND} 创建一个新技能` : `${SKILL_FOUNDRY_COMMAND} 创建一个新技能：${text}`;
}

/**
 * 会话名（`sessions/create` 的 `name`，建后不可改）。
 *
 * 创建场取正文前 20 字；为空时退回「新建技能」（首页只挂附件时）。优化场固定
 * `优化 <name>` —— 技能库的「历史」就按这个名字筛这一场。
 */
export function sessionNameFor(
  mode: WorkshopMode,
  body: string,
  skill: Pick<Skill, 'name'> | null,
): string {
  if (mode === 'optimize' && skill !== null) return `优化 ${skill.name}`;

  const text = body.trim().replace(/\s+/gu, ' ');
  if (text === '') return '新建技能';
  return `新建技能：${text.length > 20 ? `${text.slice(0, 20)}…` : text}`;
}
