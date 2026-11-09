/**
 * harness-create 首条消息的拼装与改写。
 *
 * 知识检索是一个**命令参数**（`--knowledge-workflow-id RAG_Workflow_xxx`），
 * 不是独立接口：它必须和需求一起出现在消息里，harness-create 才会执行 Step 1b
 * 注入 `rag-knowledge-search`。
 *
 * 参数的值来自智能体自己的配置（`Agent.knowledgeWorkflowId`，可改 / 可取消），
 * 所以这里除了「拼」还要能「改写」：见 `withKnowledgeFlag`。首页、生产会话与取名逻辑
 * 共用同一份规则。
 */

import { HARNESS_CREATE } from './preset-commands';

const FLAG = '--knowledge-workflow-id';
/** 与注入器同一把尺子：这个值会被写进 Python 字面量。 */
const WORKFLOW_ID = /^[A-Za-z0-9_-]{1,128}$/;
/** 命令之后紧跟的参数段；只认一处，且只在开头的命令后面。 */
const LEADING_FLAG = new RegExp(`^\\s+${FLAG}\\s+[A-Za-z0-9_-]{1,128}`, 'u');

/**
 * 首页：命令 + 可选参数 + 需求。
 *
 * `demand` 为空时只回命令（调用方通常已拦住「空需求 + 知识检索」）。
 */
export function composeHarnessPrompt(demand: string, workflowId: string | null): string {
  const head =
    workflowId === null || workflowId === ''
      ? HARNESS_CREATE
      : `${HARNESS_CREATE} ${FLAG} ${workflowId}`;
  const text = demand.trim();
  return text === '' ? head : `${head} ${demand}`;
}

/**
 * 生产会话：把消息开头的参数**改写成当前选择**，只动「以 harness-create 开头」的消息。
 *
 * 与「补参数」的差别在两点，都是为了取消能真正生效：
 *
 * - 消息里已有参数（如创建时的原话被重新补发）→ **换掉**，不是保留旧值；
 * - 当前选择为空 → **删掉**旧参数，而不是原样放过。
 *
 * 普通消息（「再改一下开场白」）原样发出 —— 它不是一次新的 harness-create 调用，
 * 参数放进去只会变成模型要解释的噪音。
 */
export function withKnowledgeFlag(text: string, workflowId: string | null): string {
  const at = text.indexOf(HARNESS_CREATE);
  if (at < 0 || text.slice(0, at).trim() !== '') return text;

  const valid = workflowId !== null && WORKFLOW_ID.test(workflowId);
  const head = `${text.slice(0, at)}${HARNESS_CREATE}`;
  const rest = text.slice(at + HARNESS_CREATE.length).replace(LEADING_FLAG, '');
  return valid ? `${head} ${FLAG} ${workflowId}${rest}` : `${head}${rest}`;
}

/**
 * 「移除知识检索并重建」的请求正文。
 *
 * 只用 harness-create **现有的入口接口**：不拼 `--knowledge-workflow-id`（本次不注入），
 * 用自然语言要求按 create 重建。agent-genesis 不在可修改范围内，所以没有专用移除参数；
 * 产物里的知识章节能不能清掉，取决于它现有的重建流程。
 */
export function composeKnowledgeRebuildPrompt(): string {
  return (
    `${HARNESS_CREATE} ` +
    '按 create 重建流程重新生成这个智能体的完整产物（不是增量优化）：' +
    '移除知识检索能力，其余能力、流程与交互保持不变。'
  );
}

/**
 * 展示用：剥掉开头那条 slash 命令与知识检索参数。
 *
 * 取名与卡片摘要用它，否则名字会变成 `--knowledge-workflow-id RAG…`。
 * 形态与 `create-agent.ts` 原来的 `LEAD_COMMAND` 一致，只多认一段可选参数。
 */
const LEAD_COMMAND = /^\/[A-Za-z0-9._-]+(?::[A-Za-z0-9._-]+)?(?:\s+--knowledge-workflow-id\s+[A-Za-z0-9_-]+)?\s+/u;

export function stripHarnessCommand(text: string): string {
  return text.replace(LEAD_COMMAND, '').trim();
}
