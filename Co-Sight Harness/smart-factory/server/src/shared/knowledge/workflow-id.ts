/**
 * harness-create 首条消息里的知识检索参数。
 *
 * 该参数是创建智能体时拼进首条消息的（形态见 `web/src/shared/commands/harness-prompt.ts`）：
 *
 *   /agent-genesis:harness-create --knowledge-workflow-id RAG_Workflow_xxx 需求……
 *
 * 智能体要把它当**自己的配置**记住（能改、能取消），所以创建时从 `init.input` 解析一次落库；
 * 本模块只做解析与形态校验，不碰 HTTP、不碰数据库。
 *
 * 与前端同一把尺子：id 会被写进产物脚本的 Python 字面量，只允许 `[A-Za-z0-9_-]`。
 */

/** 允许的工作流 id 形态。 */
export const KNOWLEDGE_WORKFLOW_ID_RE = /^[A-Za-z0-9_-]{1,128}$/;

/**
 * 知识检索技能在产物里的目录名（harness-create Step 1b 由注入器写入）。
 *
 * 与 `agent-genesis/scripts/inject-input-assets.py` 的 `SKILL_NAME` 必须一致 ——
 * 它同时是 `/` 命令名与技能目录名，详情里的 `knowledgeInjected` 就按它判断。
 */
export const KNOWLEDGE_SKILL_NAME = 'rag-knowledge-search';

/** 首条消息里的参数；与前端 `parseKnowledgeWorkflowId` 同形。 */
const FLAG_RE = /--knowledge-workflow-id\s+([A-Za-z0-9_-]{1,128})/u;

/** 没有参数时返回空串（与 `description` / `icon` 的「空串 = 没有」同一口径）。 */
export function parseKnowledgeWorkflowId(text: string): string {
  return FLAG_RE.exec(text)?.[1] ?? '';
}

/** 单个 id 的形态校验：空串是合法取值（表示未启用 / 已取消）。 */
export function isKnowledgeWorkflowId(value: string): boolean {
  return value === '' || KNOWLEDGE_WORKFLOW_ID_RE.test(value);
}
