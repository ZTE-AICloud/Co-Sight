/**
 * 智能体的**来源**：标出这个智能体是谁建的，用来把用户建的与内置的区分开。
 *
 * 它是接口上的一个字段（契约 5.01 的 `Agent.source`），不是标签：
 * 只读、仅 runtime、没有工作区这些行为都由它派生，服务端说了算。
 * 早先的设计把来源塞进 `tags`（`自定义` / `内置` 两颗），问题有三个：
 * 用户可编辑的数据不能决定服务端行为、标签的精确匹配只能靠 JSON 串 `contains`、
 * 收养出来的存量智能体两颗标签都没有导致筛选漏。2026-10-21 收敛成字段。
 *
 * 现在 `tags` 只放用户写的分类；`内置` / `自定义` 是**保留字**，前后端都拒绝写入。
 */

/** 来源取值，与后端 `Agent.source` 一致。 */
export type AgentSource = 'user' | 'builtin';

/** 保留标签：它们曾经是来源的载体，现在只允许由 `source` 字段表达。 */
export const RESERVED_TAGS: readonly string[] = ['内置', '自定义'];

/** 是不是保留标签（编辑弹窗拒绝手工输入，给后端的 400 提前把话说在用户手边）。 */
export function isReservedTag(tag: string): boolean {
  return RESERVED_TAGS.includes(tag);
}
