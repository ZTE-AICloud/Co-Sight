/**
 * Conversation 的纯计算部分：分组、折叠摘要、展开态的 key。
 *
 * 刻意不碰 React —— 这几件事都能单独讲清楚（也就能单独验），
 * 放进组件里就只剩「渲染出来看着对」这一种验证方式了。
 */

import type { ConversationMessage, ConversationTurn, TurnEntry } from './types';

/** 折叠体里先露几条，超出的进「还有 N 步」（对齐设计稿的 PROC_VISIBLE） */
export const PROC_VISIBLE = 6;

/* ---------- 展开态的 key ---------- */

/*
 * 三种可展开的东西共用一个 Set<string>，所以 key 必须自带命名空间：
 * 一条消息的折叠条、它的「还有 N 步」、以及其中某一条条目 —— 三者可以同时展开，
 * 也是三种互不相干的记忆。id 一律用**消息** id：折叠条是按消息挂的，
 * 一轮里可能有好几条助手消息，各有各的折叠条。
 */

export const foldKey = (id: string) => `fold:${id}`;
export const moreKey = (id: string) => `more:${id}`;
export const entryKey = (id: string, index: number) => `entry:${id}:${index}`;

/* ---------- 分组 ---------- */

/**
 * 把一维消息列表切成「一轮一轮」。
 *
 * 规则只有一条：**用户消息起一轮，后面紧跟的助手消息都归这一轮**。
 * 会话开头（或任何拿不到归属的地方）直接就是助手消息时，它自己起一轮、没有 ask ——
 * 预览阶段的 mock 就是这种形状，别为了凑成一个完整的一轮把它丢掉。
 *
 * 先建对象再补字段，而不是写成带可选属性的字面量：`ask` 只在有用户消息时才该**存在**，
 * 而不是存在且为 undefined。
 */
export function groupTurns(messages: ConversationMessage[]): ConversationTurn[] {
  const turns: ConversationTurn[] = [];

  for (const message of messages) {
    const last = turns[turns.length - 1];
    if (message.role === 'user' || last === undefined) {
      const turn: ConversationTurn = { id: message.id, replies: [] };
      if (message.role === 'user') turn.ask = message;
      else turn.replies.push(message);
      turns.push(turn);
      continue;
    }
    last.replies.push(message);
  }

  return turns;
}

/* ---------- 折叠摘要 ---------- */

export type FoldState = 'running' | 'done' | 'failed';

export interface FoldSummary {
  state: FoldState;
  /** 过程条目总数（折叠条右侧的「N 步」） */
  steps: number;
  /** 其中失败的条数（状态为 failed 时折叠条上的「N 步失败」） */
  failed: number;
  /** 这条消息自己的时刻（`14:06`），空串表示没有 */
  time: string;
}

function entriesOf(message: ConversationMessage): TurnEntry[] {
  return message.entries ?? [];
}

/**
 * 一条助手消息的折叠摘要；没有过程条目时返回 null —— 那就只是一句回答，
 * 不该给它配一条空折叠条（今天的 p2 / e2 就是这种消息，以及被中断的那条）。
 *
 * 状态取「最坏的那个」：有失败的步骤就报失败，否则有在跑的就报在跑，都没有才是完成。
 * 这样折叠着的时候也能一眼看出这一轮到底成没成。
 */
export function foldOf(message: ConversationMessage, active = false): FoldSummary | null {
  const entries = entriesOf(message);
  if (entries.length === 0) return null;

  const failed = entries.filter((entry) => entry.status === 'failed').length;
  const state: FoldState = active
    ? 'running'
    : failed > 0
      ? 'failed'
      : entries.some((entry) => entry.status === 'running')
        ? 'running'
        : 'done';

  // 文案留给渲染层拼（这里保持纯函数、与语言无关）。
  return { state, steps: entries.length, failed, time: message.time };
}
