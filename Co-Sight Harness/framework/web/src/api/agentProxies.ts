/**
 * Agent 代理配置接口（需求 2.3-1：配置与显示）。
 *
 * 范围提醒：框架**不运行** Agent，只把「用哪个代理、连哪个地址、给什么额度、
 * 开哪些能力」存下来并显示。因此这里没有 invoke / run 之类的接口，
 * 将来也不该有——那是各模块自己的事。
 *
 * 令牌与模型密钥同规则（D26 只写不读）：
 * 读只给 `tokenMasked` / `hasToken`，写用 `undefined` = 保持 / `null` = 清除 / 字符串 = 覆盖。
 */

import type { AgentProxyConfig, CreateAgentProxyInput, UpdateAgentProxyInput } from 'harness-shared';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { requestData } from './client';

export const agentProxyKeys = {
  all: ['agent-proxies'] as const,
  list: () => ['agent-proxies', 'list'] as const,
  defaultOne: () => ['agent-proxies', 'default'] as const,
  detail: (id: string) => ['agent-proxies', 'detail', id] as const,
};

export const agentProxiesApi = {
  list: (signal?: AbortSignal) => requestData<AgentProxyConfig[]>('/agent-proxies', { signal }),

  /** 全局默认代理；一个都没配时为 `null`。 */
  findDefault: (signal?: AbortSignal) =>
    requestData<AgentProxyConfig | null>('/agent-proxies/default', { signal }),

  create: (input: CreateAgentProxyInput) =>
    requestData<AgentProxyConfig>('/agent-proxies', { method: 'POST', body: input }),

  update: (id: string, patch: UpdateAgentProxyInput) =>
    requestData<AgentProxyConfig>(`/agent-proxies/${id}`, { method: 'PATCH', body: patch }),

  setDefault: (id: string) =>
    requestData<AgentProxyConfig>(`/agent-proxies/${id}/default`, { method: 'POST' }),

  remove: (id: string) =>
    requestData<{ id: string; deleted: true }>(`/agent-proxies/${id}`, { method: 'DELETE' }),
};

export function useAgentProxyList() {
  return useQuery({
    queryKey: agentProxyKeys.list(),
    queryFn: ({ signal }) => agentProxiesApi.list(signal),
  });
}

export function useDefaultAgentProxy() {
  return useQuery({
    queryKey: agentProxyKeys.defaultOne(),
    queryFn: ({ signal }) => agentProxiesApi.findDefault(signal),
  });
}

function useAgentProxyMutation<TVariables, TData>(
  mutationFn: (variables: TVariables) => Promise<TData>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    // 同模型：`isDefault` 互斥，列表与 `/default` 会同时变，整组失效。
    onSuccess: () => client.invalidateQueries({ queryKey: agentProxyKeys.all }),
  });
}

export function useCreateAgentProxy() {
  return useAgentProxyMutation((input: CreateAgentProxyInput) => agentProxiesApi.create(input));
}

export function useUpdateAgentProxy() {
  return useAgentProxyMutation((variables: { id: string; patch: UpdateAgentProxyInput }) =>
    agentProxiesApi.update(variables.id, variables.patch),
  );
}

export function useSetDefaultAgentProxy() {
  return useAgentProxyMutation((id: string) => agentProxiesApi.setDefault(id));
}

export function useDeleteAgentProxy() {
  return useAgentProxyMutation((id: string) => agentProxiesApi.remove(id));
}
