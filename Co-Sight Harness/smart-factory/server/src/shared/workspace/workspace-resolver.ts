import { BadGatewayError, NotFoundError } from '../errors.js';
import { fetchWorkspace } from '../framework/client.js';
import { agentsRepo } from '../store/agents.repo.js';
import { builtinAgentDir } from './builtin-agents.js';
import { agentRoot } from './dir-resolver.js';
import type { AgentSource } from '../types/index.js';

export { agentRoot } from './dir-resolver.js';

/**
 * 智能体归属工作区后的路径解析。
 *
 * 顺序固定三步：按 `agentId` 查 `agents` 表取 `workspaceId`，再调框架
 * `GET /api/framework/v1/workspaces/{id}` 取 `directory`，最后拼出 agentRoot。
 * 工作区不存在、`directory` 为 null、框架不可达都明确报错，不猜路径。
 *
 * 内置智能体（source=builtin）不走这条链：没有 workspaceId，目录就是定义目录本身，
 * 不发起任何框架调用（框架不可达不影响内置智能体的列表与运行）。
 */

export interface AgentWorkspace {
  /** 内置智能体恒为 null */
  workspaceId: string | null;
  /** 普通智能体=工作区目录（agentRoot 的拼接基数）；内置智能体=定义目录本身（就是 agentRoot） */
  directory: string;
  /** 来源：调用方据此决定 cwd 与阶段门禁（内置仅 runtime） */
  source: AgentSource;
}

/**
 * 工作区 id → 绝对目录。
 *
 * 框架把「工作区不存在」映射成 404，但本服务对外把解析失败统一报 502：
 * 这是上游数据不可用，不是调用方访问了一个不存在的本地资源。
 */
export async function resolveWorkspaceDirectory(workspaceId: string): Promise<string> {
  let workspace;
  try {
    workspace = await fetchWorkspace(workspaceId);
  } catch (error) {
    if (error instanceof NotFoundError)
      throw new BadGatewayError(`工作区 ${workspaceId} 不存在`, 'error.bad_gateway.workspace_missing', {
        workspaceId,
      });
    throw error;
  }

  const directory = workspace.directory?.trim() ?? '';
  if (directory === '')
    throw new BadGatewayError(`工作区 ${workspaceId} 未绑定目录`, 'error.bad_gateway.workspace_unbound', {
      workspaceId,
    });
  return directory;
}

/** agent → workspaceId → directory；未知 agent 404。内置 agent → 定义目录（零框架调用）。 */
export async function resolveAgentWorkspace(agentId: string): Promise<AgentWorkspace> {
  const agent = await agentsRepo.findById(agentId);
  if (!agent) throw new NotFoundError(`智能体 ${agentId}`, 'error.not_found.agent', { agentId });
  if (agent.source === 'builtin') return { workspaceId: null, directory: builtinAgentDir(agent.id), source: 'builtin' };
  return { workspaceId: agent.workspaceId, directory: await resolveWorkspaceDirectory(agent.workspaceId!), source: 'user' };
}

/** 智能体的绝对根目录；解析失败按 502 / 404 抛错。内置智能体的根就是定义目录本身。 */
export async function resolveAgentRoot(agentId: string): Promise<string> {
  const workspace = await resolveAgentWorkspace(agentId);
  return workspace.source === 'builtin' ? workspace.directory : agentRoot(workspace.directory, agentId);
}
