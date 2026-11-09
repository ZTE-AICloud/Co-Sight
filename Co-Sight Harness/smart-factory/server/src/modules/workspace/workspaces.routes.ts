import { realpathSync } from 'node:fs';
import { join } from 'node:path';
import { Router } from 'express';
import { config } from '../../config/index.js';
import { fetchWorkspaces } from '../../shared/framework/client.js';

/**
 * 工作区只读代理：供前端与 e2e 取 `workspaceId`，以及取该工作区的默认模型。
 *
 * 透出 `id` / `name` / `defaultModelId` 与 `activeId`，**不下发 `directory`**；
 * 工作区的创建、绑定目录与切换都在框架界面完成（4.01-接口总览.md §4.4）。
 * `defaultModelId` 只是原样转发框架的值：Web 端在 `preview` / `evaluation` 首次建会话时
 * 用它解析默认模型，解析完成后仍然显式传给 `sessions/create`（服务端不自己猜）。
 */
export const workspacesRouter = Router();

workspacesRouter.get('/workspaces/list', async (_req, res) => {
  const list = await fetchWorkspaces();
  res.json({
    items: list.items.map(({ id, name, defaultModelId }) => ({ id, name, defaultModelId: defaultModelId ?? null })),
    activeId: list.activeId,
  });
});

/** 可监控目录条目：框架工作区与内置目录条目共用一张形状，`kind` 区分来源。 */
interface DirectoryEntry {
  id: string;
  name: string;
  directory: string | null;
  defaultModelId: string | null;
  kind: 'workspace' | 'default';
}

/**
 * 观测端（cosight-viewer）用的可监控目录清单。
 *
 * 框架工作区列表 + 一条「内置与技能开发目录」，条目形状是 `/workspaces/list` 的超集：
 *
 * - **带 `directory`**：观测端按会话 `cwd` 归属工作区，没有目录就无从过滤；
 * - **补内置目录条目**：不属于任何框架工作区的会话都落在 `{COSIGHT_HOME}/smart-factory/` 下 ——
 *   内置专家的 runtime cwd（`builtin-agents/{id}`）、技能开发的目录会话（`skill-workshop`）、
 *   没有生效工作区时的自由对话（`chat`）。只认框架工作区清单的观测端因此看不到这些会话。
 *   这里补一条 `kind=default`、`directory` 指向该根的条目，观测端按前缀匹配即可覆盖全部。
 *
 * 名字特意不叫「默认工作区」：框架首次启动会建一个**真的**叫「默认工作区」的工作区行
 * （`framework/server/src/seed/seed.ts`），两个同名字段在观测端的筛选下拉里并排出现会让人以为是一回事。
 * 这里只有 `name` 是展示文案；`id` 固定 `default`、`kind` 固定 `default` 是观测端的判别依据（不可改）。
 *
 * 只暴露 `{COSIGHT_HOME}/smart-factory/`：`{COSIGHT_HOME}` 本身还有 `.module-token`、数据库与模块，
 * 不进任何观测清单。`kind` 区分条目来源（`workspace` / `default`）；本条目 `id` 固定 `default`，
 * 永不等于框架工作区 id，所以 `activeId` 不会命中它。`defaultModelId` 原样转发（本条目恒 `null`）。
 *
 * 与 `/workspaces/list` 同口径：框架不可达 / 令牌无效 / 上游非 2xx 时返回 `502`，不做降级。
 */
workspacesRouter.get('/workspaces/directories/list', async (_req, res) => {
  const list = await fetchWorkspaces();
  const items: DirectoryEntry[] = list.items.map(({ id, name, directory, defaultModelId }) => ({
    id,
    name,
    directory: directory ?? null,
    defaultModelId: defaultModelId ?? null,
    kind: 'workspace',
  }));

  const dir = join(config.cosightHome, 'smart-factory');
  let directory = dir;
  try {
    // 引擎记录的是物理 cwd（getcwd 会解掉 symlink）；清单按同一形态给，观测端前缀匹配才能命中。
    directory = realpathSync(dir);
  } catch {
    // 目录尚未落盘（刚安装）：保留逻辑路径，首次会话创建后自然可见。
  }
  // 展示名与框架真实工作区「默认工作区」区分开；id / kind 是观测端的判别依据，不要跟着改。
  items.push({ id: 'default', name: '内置与技能开发目录', directory, defaultModelId: null, kind: 'default' });

  res.json({ items, activeId: list.activeId });
});
