/**
 * 工作区接口（需求 2.1：新建 / 切换 / 删除）。
 *
 * **「当前工作区」是服务端状态，不是前端 store 里的一份副本。**
 *
 * 服务端把它存在 `app_state` 表里（`active_workspace_id`），因为工作区决定默认模型与
 * 默认 Agent——这份上下文必须全局唯一。如果前端各存一份（zustand / localStorage），
 * 两个标签页就会各自以为自己在不同工作区，而"到底用哪个模型"在两边给出不同答案。
 * 所以：
 *
 * - 读：`GET /workspaces/active`，由 React Query 按 key 去重，侧栏与专家页共用同一次请求；
 * - 写：`POST /workspaces/:id/activate`，成功后让工作区缓存整体失效。
 *
 * 删除当前工作区时服务端会顺手清掉指针（读取端也有自愈逻辑），因此前端**不需要**
 * 在删除后手动"切到另一个工作区"——删完再读一次 `active` 就是真相。
 */

import type {
  CreateWorkspaceInput,
  PickDirectoryResult,
  UpdateWorkspaceInput,
  Workspace,
} from 'harness-shared';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { requestData } from './client';

export const workspaceKeys = {
  all: ['workspaces'] as const,
  list: () => ['workspaces', 'list'] as const,
  /** 当前工作区（全局唯一，单独一个 key 便于其它页面直接订阅）。 */
  active: () => ['workspaces', 'active'] as const,
  detail: (id: string) => ['workspaces', 'detail', id] as const,
};

export const workspacesApi = {
  list: (signal?: AbortSignal) => requestData<Workspace[]>('/workspaces', { signal }),

  /** 一个工作区都没有、或当前指针为空时返回 `null`（不是 404）。 */
  active: (signal?: AbortSignal) => requestData<Workspace | null>('/workspaces/active', { signal }),

  create: (input: CreateWorkspaceInput) =>
    requestData<Workspace>('/workspaces', { method: 'POST', body: input }),

  update: (id: string, patch: UpdateWorkspaceInput) =>
    requestData<Workspace>(`/workspaces/${id}`, { method: 'PATCH', body: patch }),

  activate: (id: string) => requestData<Workspace>(`/workspaces/${id}/activate`, { method: 'POST' }),

  remove: (id: string) => requestData<{ id: string; deleted: true }>(`/workspaces/${id}`, { method: 'DELETE' }),

  /**
   * 让**服务端那台机器**弹出系统目录选择器。
   *
   * 浏览器拿不到绝对路径（`showDirectoryPicker()` 只给句柄），所以这个对话框只能由
   * 服务端拉起。返回值有三种：选中 → 路径；取消 → `null`（**正常结果**）；
   * 这台机器弹不出来 → 抛错，前端提示改手输。
   */
  pickDirectory: (initialPath: string | null) =>
    requestData<PickDirectoryResult>('/workspaces/pick-directory', {
      method: 'POST',
      body: { initialPath },
    }),
};

export function useWorkspaceList() {
  return useQuery({
    queryKey: workspaceKeys.list(),
    queryFn: ({ signal }) => workspacesApi.list(signal),
  });
}

/**
 * 当前工作区。侧栏常驻一个入口，专家页的「使用」也要带上它的 id，两处订阅同一个 key。
 *
 * 不设 `staleTime`：这是**别人也能改**的共享状态（换个标签页切一下工作区就算），
 * 缓存放久了就会让"界面上显示的工作区"和"实际生效的工作区"分叉。一次请求只读一行，
 * 每次挂载/窗口聚焦重新确认一遍是划算的。
 */
export function useActiveWorkspace(options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: workspaceKeys.active(),
    queryFn: ({ signal }) => workspacesApi.active(signal),
    enabled: options.enabled ?? true,
  });
}

/**
 * 三个写操作都让 `workspaceKeys.all` 整体失效。
 *
 * 不逐个精确失效是有意的：改一个工作区的名字会出现在列表、也可能出现在 `/active`
 * 的返回里；精确失效要写三处 key，漏一处就是"改完名字侧栏还是旧的"。
 */
function useWorkspaceMutation<TVariables, TData>(
  mutationFn: (variables: TVariables) => Promise<TData>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => client.invalidateQueries({ queryKey: workspaceKeys.all }),
  });
}

export function useCreateWorkspace() {
  return useWorkspaceMutation((input: CreateWorkspaceInput) => workspacesApi.create(input));
}

export function useUpdateWorkspace() {
  return useWorkspaceMutation((variables: { id: string; patch: UpdateWorkspaceInput }) =>
    workspacesApi.update(variables.id, variables.patch),
  );
}

export function useActivateWorkspace() {
  return useWorkspaceMutation((id: string) => workspacesApi.activate(id));
}

export function useDeleteWorkspace() {
  return useWorkspaceMutation((id: string) => workspacesApi.remove(id));
}

/**
 * 打开系统目录选择器。
 *
 * **不走 `useWorkspaceMutation`**：它一个工作区也没改，让 `workspaceKeys.all` 失效
 * 只会多打几条无谓的请求（表单开着的时候，列表/当前工作区都得重取一遍）。
 * 结果由调用方自己填进输入框。
 */
export function usePickDirectory() {
  return useMutation({
    mutationFn: (initialPath: string | null) => workspacesApi.pickDirectory(initialPath),
  });
}
