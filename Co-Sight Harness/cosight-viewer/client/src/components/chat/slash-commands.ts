// SPDX-License-Identifier: Apache-2.0
/**
 * @file slash-commands.ts
 * @description `/` 菜单的纯逻辑：识别触发上下文、合并命令与技能、过滤。
 *
 * 为什么只认**首 token**：引擎只在消息开头识别斜杠命令，写在正文中间的
 * `/build` 只是一段普通文字。菜单如果在任意位置弹出，用户会选中一个
 * “看起来是命令、实际不会执行”的词，比不弹更糟。
 *
 * 命令与技能都以 `/<name>` 调用：
 * - 项目命令：`.claude/commands/**\/*.md` 的文件名；
 * - 技能：`.claude/skills/<name>`（插件技能自带 `plugin:` 前缀）。
 * 同名时命令优先（显式命令比技能更具体），菜单里只保留一条。
 */

import type { AgentCommand, AgentSkill } from "../../api/agent-api";

export interface SlashContext {
  /** `/` 在文本中的下标 */
  start: number;
  /** `/` 后面的查询词（不含 `/`） */
  query: string;
}

export type SlashCommandKind = "command" | "skill";

/** 菜单项：命令与技能共用一个形状，`kind` 只用于分组展示 */
export interface SlashCommandItem {
  kind: SlashCommandKind;
  /** 命令名（`/<name>`），也是插入 prompt 的字面量 */
  name: string;
  description: string;
}

/**
 * 光标前是否是一个“首 token 的 `/query`”。
 *
 * 允许前面有空白（发送前会 `trim()`）；命令 token 内部不能有空白。
 * 调用方还需保证光标在文本末尾（见 `ChatComposer`），避免用户在 token
 * 中间编辑时插入到错误位置。
 */
export function slashContextAt(text: string, caret: number): SlashContext | null {
  if (caret < 0 || caret > text.length) return null;
  const before = text.slice(0, caret);
  const match = /^\s*\/([^\s]*)$/u.exec(before);
  if (match === null) return null;

  const query = match[1] ?? "";
  return { start: caret - query.length - 1, query };
}

/** 菜单主文本，也是插入 prompt 的斜杠命令字面量。 */
export function commandLabel(command: { name: string }): string {
  return `/${command.name}`;
}

/**
 * 合并智能体详情里的命令与技能。
 *
 * 顺序固定为“命令 → 技能”，同名时保留命令；菜单分组渲染依赖这个顺序。
 * 空名字（扫描异常）直接跳过，避免出现一条点了没反应的 `/`。
 */
export function buildSlashCommands(
  commands: readonly AgentCommand[] = [],
  skills: readonly AgentSkill[] = []
): SlashCommandItem[] {
  const seen = new Set<string>();
  const items: SlashCommandItem[] = [];

  for (const command of commands) {
    if (command.name === "" || seen.has(command.name)) continue;
    seen.add(command.name);
    items.push({
      kind: "command",
      name: command.name,
      description: command.description,
    });
  }

  for (const skill of skills) {
    if (skill.name === "" || seen.has(skill.name)) continue;
    seen.add(skill.name);
    items.push({
      kind: "skill",
      name: skill.name,
      description: skill.description,
    });
  }

  return items;
}

/**
 * 引擎 `/` 菜单条目 → 菜单项。
 *
 * 引擎不区分命令与技能（技能也按一条 `/` 命令注册），统一归到 `command` 分组；
 * 空名字去重，避免出现点了没反应的条目。
 */
export function buildEngineSlashCommands(
  items: readonly { name: string; description: string }[] = []
): SlashCommandItem[] {
  const seen = new Set<string>();
  const result: SlashCommandItem[] = [];

  for (const item of items) {
    if (item.name === "" || seen.has(item.name)) continue;
    seen.add(item.name);
    result.push({
      kind: "command",
      name: item.name,
      description: item.description,
    });
  }

  return result;
}

function rank(item: SlashCommandItem, needle: string): number {
  const name = item.name.toLowerCase();
  if (name.startsWith(needle)) return 0;
  if (name.includes(needle)) return 1;
  if (item.description.toLowerCase().includes(needle)) return 2;
  return -1;
}

/**
 * 过滤 + 排序：前缀命中 > 名字包含 > 说明包含；同档保持传入顺序。
 * 空查询 = 全量（刚输入 `/` 时把命令与技能都摆出来）。
 */
export function filterSlashCommands(
  items: readonly SlashCommandItem[],
  query: string
): SlashCommandItem[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return [...items];

  return items
    .map((item, index) => ({ item, index, rank: rank(item, needle) }))
    .filter((entry) => entry.rank >= 0)
    .sort((left, right) => left.rank - right.rank || left.index - right.index)
    .map((entry) => entry.item);
}

/**
 * 按分组过滤：命令一段、技能一段，各自排序后拼起来。
 * 菜单的键盘高亮在这个扁平数组上移动，视觉上仍是两个分组。
 */
export function groupSlashCommands(
  items: readonly SlashCommandItem[],
  query: string
): SlashCommandItem[] {
  const commands = filterSlashCommands(
    items.filter((item) => item.kind === "command"),
    query
  );
  const skills = filterSlashCommands(
    items.filter((item) => item.kind === "skill"),
    query
  );
  return [...commands, ...skills];
}
