/**
 * 模型配置接口（需求 2.3；前端表单见 3.2）。
 *
 * 密钥遵循 D26「只写不读」：
 * - 响应里**没有**任何明文密钥字段，只有 `apiKeyMasked`（固定掩码或 null）与
 *   `hasApiKey`。表单要判断"是否已配置"，看的是 `hasApiKey`，不是掩码字符串。
 * - 请求侧三态（见 harness-shared 的 `updateModelConfigInputSchema`）：
 *   `undefined` = 保持原密钥、`null` = 清除、字符串 = 覆盖。
 *   表单里"留空"要映射成 `undefined`（改）或 `null`（新建），**不能**映射成空串——
 *   空串会被服务端按 `min(1)` 判成 422，用户看到的是"参数校验未通过"这种没有指向的错。
 */

import type { CreateModelConfigInput, ModelConfig, UpdateModelConfigInput } from 'harness-shared';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { requestData } from './client';

export const modelKeys = {
  all: ['models'] as const,
  list: () => ['models', 'list'] as const,
  active: () => ['models', 'active'] as const,
  detail: (id: string) => ['models', 'detail', id] as const,
};

export const modelsApi = {
  list: (signal?: AbortSignal) => requestData<ModelConfig[]>('/models', { signal }),

  /** 全局当前生效的模型；一个都没配时为 `null`。 */
  active: (signal?: AbortSignal) => requestData<ModelConfig | null>('/models/active', { signal }),

  create: (input: CreateModelConfigInput) =>
    requestData<ModelConfig>('/models', { method: 'POST', body: input }),

  update: (id: string, patch: UpdateModelConfigInput) =>
    requestData<ModelConfig>(`/models/${id}`, { method: 'PATCH', body: patch }),

  activate: (id: string) => requestData<ModelConfig>(`/models/${id}/activate`, { method: 'POST' }),

  remove: (id: string) => requestData<{ id: string; deleted: true }>(`/models/${id}`, { method: 'DELETE' }),

  /*
   * 这里**刻意没有** `probe`。
   *
   * 服务端 `POST /models/:id/probe` 存在，但实现是 `AppError.notImplemented`
   * （见 routes/model.ts 的注释）：探测要由服务端去请求用户填的地址，等于开了一条
   * SSRF 通道，得先有地址白名单才能上。前端因此不放「测试连接」按钮——
   * 一个点了只报"尚未实现"的按钮比没有按钮更糟。契约里的 `ModelProbeResult`
   * 是为将来准备的，接口做出来的那天在这里补一个 `probe` 即可。
   */
};

export function useModelList() {
  return useQuery({
    queryKey: modelKeys.list(),
    queryFn: ({ signal }) => modelsApi.list(signal),
  });
}

/**
 * 当前生效的模型。
 *
 * `enabled` 供"只在需要时才订阅"的调用方使用：模型宿主页（Agent 开发/评估）
 * 要按它决定是否刷新 iframe，而会话、观测等宿主不需要为此多发一次请求。
 * 关掉时仍会读到缓存里已有的值——同一个 key 的查询是共享的。
 */
export function useActiveModel(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: modelKeys.active(),
    queryFn: ({ signal }) => modelsApi.active(signal),
    enabled: options.enabled ?? true,
  });
}

function useModelMutation<TVariables, TData>(
  mutationFn: (variables: TVariables) => Promise<TData>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    /*
     * 让整组模型缓存失效：`isActive` 是互斥的（激活 A 会把 B 置为 false），
     * 列表和 `/active` 的返回都会变，逐个失效要写两处、漏一处就出现两个"当前使用"。
     */
    onSuccess: () => client.invalidateQueries({ queryKey: modelKeys.all }),
  });
}

export function useCreateModel() {
  return useModelMutation((input: CreateModelConfigInput) => modelsApi.create(input));
}

export function useUpdateModel() {
  return useModelMutation((variables: { id: string; patch: UpdateModelConfigInput }) =>
    modelsApi.update(variables.id, variables.patch),
  );
}

export function useActivateModel() {
  return useModelMutation((id: string) => modelsApi.activate(id));
}

export function useDeleteModel() {
  return useModelMutation((id: string) => modelsApi.remove(id));
}
