/**
 * 种子写入。
 *
 * `seedPresetExperts` **只在 experts 表为空时写入**：预置内容是随框架分发的，
 * 用户删掉一条就代表他真的不想要它，服务重启不该把它塞回来。
 * 想恢复出厂状态，用 `pnpm db:seed -- --force`（见 seed/run.ts）。
 *
 * `seedDefaultWorkspace` 语义相同，但目的不同：产品出厂就该有一个能直接用的
 * 工作区。没有 active 工作区时，下游（smart-factory）的预置智能体虽然仍登记在
 * 库里，前端却连列表都不请求——用户看到的是一屏"未选择工作区"。
 *
 * `seedDefaultRagKnowledge` 同理：出一条「当前可用」的知识库路由，左侧「知识库」
 * 菜单开箱就能点开。判定依旧是"表为空"，用户删光后不会再被塞回来。
 */

import type { RagKnowledgeBase, Workspace } from 'harness-shared';

import type { Services } from '../services/container';
import { PRESET_EXPERTS } from './data';

export interface SeedResult {
  inserted: number;
  /** 因表非空而跳过。 */
  skipped: boolean;
}

/** 预置项之间间隔 1 分钟的创建时间，避免同一毫秒导致 `最新` 排序退化成 id 序。 */
const CREATED_AT_STEP_MS = 60_000;

/**
 * 首次启动时自动建的工作区名。
 *
 * 名字是给人看的，目录名由 `services/workspaces.ts` 走 slug 派生（中文会被保留），
 * 不要在这里拼路径。
 */
export const DEFAULT_WORKSPACE_NAME = '默认工作区';

export interface DefaultWorkspaceSeedResult {
  created: boolean;
  /** 新建出来的工作区；跳过时为 null。 */
  workspace: Workspace | null;
  /** 工作区表非空，因而跳过。 */
  skipped: boolean;
}

/**
 * 一个工作区都没有时建一个并设为当前。
 *
 * 判定用「表是否为空」而不是「是不是首次启动」：删光所有工作区与全新安装是
 * 同一个状态——界面没有任何可用的工作区，下游模块的预置内容也看不到。
 * 与预置专家同一套语义。用户只要留下任意一个工作区，这里就永远不再插手。
 */
export async function seedDefaultWorkspace(services: Services): Promise<DefaultWorkspaceSeedResult> {
  const existing = await services.workspaces.list();
  if (existing.length > 0) {
    return { created: false, workspace: null, skipped: true };
  }

  // directory 传 null：由工作区服务在 `<工作区根>/<slug>` 下建目录并绑定，
  // 与用户在界面上直接填名字新建完全同一条代码路径。
  const workspace = await services.workspaces.create({
    name: DEFAULT_WORKSPACE_NAME,
    directory: null,
    defaultModelId: null,
    defaultAgentId: null,
  });
  // 必须激活：只建不激活的话，前端拿到的 activeId 仍是 null，预置智能体照样不显示。
  await services.workspaces.activate(workspace.id);
  return { created: true, workspace, skipped: false };
}

/**
 * 出厂默认的知识库路由。
 *
 * 这里的 `admin/admin` 是**演示环境内置账号**，不是任何真实凭据：目标站点是产品
 * 自带的默认知识库，用户可以在「设置 → 知识库路由设置」里随时改成自己的账号。
 * 写成常量而不是环境变量，是因为它必须与"出厂即可用"这个目标绑定——缺了它，
 * 全新安装打开知识库菜单只会看到空态。
 */
export const DEFAULT_RAG_KNOWLEDGE = {
  name: '知识库默认路由',
  routeUrl: 'http://localhost:8080/#/login?redirect=/kb',
  username: 'admin',
  password: 'admin',
} as const;

export interface DefaultRagKnowledgeSeedResult {
  created: boolean;
  /** 新建出来的路由；跳过时为 null。 */
  base: RagKnowledgeBase | null;
  /** 路由表非空，因而跳过。 */
  skipped: boolean;
}

/**
 * 一条路由都没有时建一条并设为当前可用。
 *
 * 判定用「表是否为空」而不是「是不是首次启动」，与预置专家 / 默认工作区同一套语义：
 * 用户删光所有路由与全新安装是同一个状态——菜单点开没有落点。只要留下任意一条，
 * 这里就永远不再插手。
 */
export async function seedDefaultRagKnowledge(
  services: Services,
): Promise<DefaultRagKnowledgeSeedResult> {
  const existing = await services.ragKnowledge.list();
  if (existing.length > 0) {
    return { created: false, base: null, skipped: true };
  }

  const base = await services.ragKnowledge.create({
    ...DEFAULT_RAG_KNOWLEDGE,
    description: null,
    isActive: true,
  });
  return { created: true, base, skipped: false };
}

export async function seedPresetExperts(
  services: Services,
  options: { force?: boolean } = {},
): Promise<SeedResult> {
  const existing = await services.experts.count();
  if (existing > 0 && options.force !== true) {
    return { inserted: 0, skipped: true };
  }

  const base = Date.now();
  let inserted = 0;

  for (const [index, input] of PRESET_EXPERTS.entries()) {
    const createdAt = new Date(base - index * CREATED_AT_STEP_MS);
    const created = await services.experts.create(input, createdAt);
    // 使用次数递减，让 `最热` 页签排出的顺序与数组顺序一致。这个初始值
    // 明显低于任何真实使用累积出的量级，不会长期占据榜首（D15 = B：纯计数）。
    const initialUseCount = Math.max(1, PRESET_EXPERTS.length - index);
    await services.experts.setUseCount(created.id, initialUseCount, createdAt);
    inserted += 1;
  }

  return { inserted, skipped: false };
}
