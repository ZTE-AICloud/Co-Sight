import { msg } from '../../i18n/useI18n';
import { modelsApi } from './models';
import { workspacesApi } from './workspaces';

/**
 * 预览 / 评估首次建会话时的默认模型。
 *
 * 服务端只认显式传入的 `modelId`（不猜、不回落），所以这条链由前端走：
 *
 * 1. 智能体所属工作区的 `defaultModelId`（`workspaces/list` 从框架原样转发）；
 * 2. 框架的全局生效模型（`models/list` 的 `activeId`）；
 * 3. 模型列表第一项；
 * 4. 都没有 → 报错（`create.chat.noModel`）。
 *
 * 两处「跳过」是刻意的：
 * - 工作区默认 / 框架生效指向的模型如果已经不在列表里（被删了），继续往下找，
 *   否则会把一个必然 400 的 id 传给服务端；
 * - 不按协议 / 密钥过滤。列表第一项即使引擎不支持，也让它交给服务端报出具体原因
 *   （与模型选择器里能选到的项保持一致）。
 *
 * `workspaceId` 取自智能体详情（`Agent.workspaceId`）；拿不到时退回框架当前工作区。
 * 只在「首次建预览 / 评估会话」时调用一次，之后模型就固定在那场会话上。
 */
export async function resolveDefaultModelId(workspaceId?: string): Promise<string> {
  const [workspaces, models] = await Promise.all([workspacesApi.list(), modelsApi.list()]);

  const workspace =
    (workspaceId === undefined ? undefined : workspaces.items.find((item) => item.id === workspaceId)) ??
    workspaces.items.find((item) => item.id === workspaces.activeId);

  const known = new Set(models.items.map((item) => item.id));

  const fromWorkspace = workspace?.defaultModelId ?? '';
  if (fromWorkspace !== '' && known.has(fromWorkspace)) return fromWorkspace;

  if (models.activeId !== null && known.has(models.activeId)) return models.activeId;

  const first = models.items[0];
  if (first !== undefined) return first.id;

  throw new Error(msg('create.chat.noModel'));
}
