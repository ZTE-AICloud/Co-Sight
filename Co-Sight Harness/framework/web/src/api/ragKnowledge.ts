/**
 * 知识库跳转路由接口（设置 → 知识库路由设置）。
 *
 * 形状照 `agentProxies.ts`：键工厂 + api 对象 + hooks。两点不同：
 *
 * - 「设为可用」走 `/activate`，语义是**切换**（旧的自动变回未生效），
 *   所以写操作后要失效**整组**键，列表与 `/active` 必须一起刷新；
 * - `/active` 在"没配置"时返回 `null` 而不是 404，因此它是个正常的查询，
 *   不需要把它当"可能失败的资源"处理。
 */

import type {
  CreateRagKnowledgeBaseInput,
  RagKnowledgeBase,
  RagKnowledgeDefaults,
  UpdateRagKnowledgeBaseInput,
} from 'harness-shared';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { requestData } from './client';

export const ragKnowledgeKeys = {
  all: ['rag-knowledge'] as const,
  list: () => ['rag-knowledge', 'list'] as const,
  active: () => ['rag-knowledge', 'active'] as const,
  defaults: () => ['rag-knowledge', 'defaults'] as const,
  detail: (id: string) => ['rag-knowledge', 'detail', id] as const,
};

export const ragKnowledgeApi = {
  list: (signal?: AbortSignal) => requestData<RagKnowledgeBase[]>('/rag-knowledge', { signal }),

  /** 当前生效的一条；一条都没配时为 `null`（正常态，不是错误）。 */
  findActive: (signal?: AbortSignal) =>
    requestData<RagKnowledgeBase | null>('/rag-knowledge/active', { signal }),

  /**
   * 服务端有没有预置默认 API Key。
   *
   * 只有布尔：默认值本身是从服务端环境变量来的，**任何浏览器面都不回传明文**
   * （D26），这里拿到的信息只够把"留空会怎样"说清楚。
   */
  defaults: (signal?: AbortSignal) =>
    requestData<RagKnowledgeDefaults>('/rag-knowledge/defaults', { signal }),

  create: (input: CreateRagKnowledgeBaseInput) =>
    requestData<RagKnowledgeBase>('/rag-knowledge', { method: 'POST', body: input }),

  update: (id: string, patch: UpdateRagKnowledgeBaseInput) =>
    requestData<RagKnowledgeBase>(`/rag-knowledge/${id}`, { method: 'PATCH', body: patch }),

  activate: (id: string) =>
    requestData<RagKnowledgeBase>(`/rag-knowledge/${id}/activate`, { method: 'POST' }),

  remove: (id: string) =>
    requestData<{ id: string; deleted: true }>(`/rag-knowledge/${id}`, { method: 'DELETE' }),
};

export function useRagKnowledgeList() {
  return useQuery({
    queryKey: ragKnowledgeKeys.list(),
    queryFn: ({ signal }) => ragKnowledgeApi.list(signal),
  });
}

export function useActiveRagKnowledge() {
  return useQuery({
    queryKey: ragKnowledgeKeys.active(),
    queryFn: ({ signal }) => ragKnowledgeApi.findActive(signal),
  });
}

export function useRagKnowledgeDefaults() {
  return useQuery({
    queryKey: ragKnowledgeKeys.defaults(),
    queryFn: ({ signal }) => ragKnowledgeApi.defaults(signal),
  });
}

function useRagKnowledgeMutation<TVariables, TData>(
  mutationFn: (variables: TVariables) => Promise<TData>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    // 「生效」是互斥的：一次切换会让列表里两行同时改变。整组失效一次覆盖完，
    // 不会出现"列表显示已生效、别处仍读旧值"。
    onSuccess: () => client.invalidateQueries({ queryKey: ragKnowledgeKeys.all }),
  });
}

export function useCreateRagKnowledge() {
  return useRagKnowledgeMutation((input: CreateRagKnowledgeBaseInput) =>
    ragKnowledgeApi.create(input),
  );
}

export function useUpdateRagKnowledge() {
  return useRagKnowledgeMutation((variables: { id: string; patch: UpdateRagKnowledgeBaseInput }) =>
    ragKnowledgeApi.update(variables.id, variables.patch),
  );
}

export function useActivateRagKnowledge() {
  return useRagKnowledgeMutation((id: string) => ragKnowledgeApi.activate(id));
}

export function useDeleteRagKnowledge() {
  return useRagKnowledgeMutation((id: string) => ragKnowledgeApi.remove(id));
}
