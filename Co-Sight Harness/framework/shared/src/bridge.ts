/**
 * 宿主 ↔ 嵌入模块的 postMessage 桥协议（C2；D25 = A 的令牌交换）。
 *
 * 三条设计约束：
 * 1. **命名空间 + 版本**：iframe 里可能同时加载别的东西，所有消息带 `namespace`，
 *    接收方先过滤再分支；`version` 让老模块能被显式拒绝而不是静默错解。
 * 2. **令牌不走 URL**：`host:init` 里带一次性 `bridgeToken`，模块拿它调
 *    `POST /api/bridge/exchange` 换 httpOnly cookie。URL query 会进浏览器历史、
 *    进 Referer、进日志，因此不用。
 * 3. **只传数据不传代码**：协议里没有任何"执行这段脚本"的消息类型。
 */

import type { ExpertAction } from './contracts/expert';
import type { Locale } from './locale';

export const BRIDGE_NAMESPACE = 'cosight-harness';

export const BRIDGE_PROTOCOL_VERSION = 1;

export type BridgeTheme = 'light' | 'dark';

/** 宿主传给模块的上下文；模块据此决定初始视图。 */
export interface BridgeContext {
  workspaceId: string | null;
  expertId: string | null;
  action: ExpertAction | null;
  /** 透传的额外查询参数（如 `mode=design`）。 */
  params: Record<string, string>;
}

interface BridgeBase {
  namespace: typeof BRIDGE_NAMESPACE;
  version: typeof BRIDGE_PROTOCOL_VERSION;
}

/** 宿主 → 模块。 */
export type HostToModuleMessage =
  | (BridgeBase & {
      type: 'host:init';
      moduleId: string;
      locale: Locale;
      theme: BridgeTheme;
      context: BridgeContext;
      /** 一次性令牌，用于换取会话 cookie；模块应尽快消费。 */
      bridgeToken: string;
      /** 换取令牌的接口地址（绝对 URL）。 */
      exchangeUrl: string;
    })
  | (BridgeBase & { type: 'host:locale'; locale: Locale })
  | (BridgeBase & { type: 'host:theme'; theme: BridgeTheme })
  | (BridgeBase & { type: 'host:context'; context: BridgeContext })
  | (BridgeBase & { type: 'host:teardown' });

/** 模块 → 宿主。 */
export type ModuleToHostMessage =
  | (BridgeBase & { type: 'module:ready'; moduleVersion: string })
  | (BridgeBase & { type: 'module:resize'; height: number })
  | (BridgeBase & { type: 'module:navigate'; path: string })
  | (BridgeBase & { type: 'module:open-expert'; expertId: string; action: ExpertAction })
  | (BridgeBase & {
      type: 'module:notify';
      level: 'info' | 'success' | 'warning' | 'error';
      messageKey: string;
    })
  | (BridgeBase & {
      type: 'module:error';
      code: string;
      messageKey: string;
      /** 模块侧已渲染的文案，宿主在缺 i18n 键时兜底显示。 */
      message: string;
    });

export type BridgeMessage = HostToModuleMessage | ModuleToHostMessage;

/** 宿主侧消息的类型白名单，用于拒绝未知 type。 */
export const HOST_TO_MODULE_TYPES = [
  'host:init',
  'host:locale',
  'host:theme',
  'host:context',
  'host:teardown',
] as const;

/** 模块侧消息的类型白名单。 */
export const MODULE_TO_HOST_TYPES = [
  'module:ready',
  'module:resize',
  'module:navigate',
  'module:open-expert',
  'module:notify',
  'module:error',
] as const;

export type HostToModuleType = (typeof HOST_TO_MODULE_TYPES)[number];
export type ModuleToHostType = (typeof MODULE_TO_HOST_TYPES)[number];

function isBridgeBase(value: unknown): value is BridgeBase & { type: string } {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    record['namespace'] === BRIDGE_NAMESPACE &&
    record['version'] === BRIDGE_PROTOCOL_VERSION &&
    typeof record['type'] === 'string'
  );
}

export function isHostToModuleMessage(value: unknown): value is HostToModuleMessage {
  if (!isBridgeBase(value)) {
    return false;
  }
  return (HOST_TO_MODULE_TYPES as readonly string[]).includes(value.type);
}

export function isModuleToHostMessage(value: unknown): value is ModuleToHostMessage {
  if (!isBridgeBase(value)) {
    return false;
  }
  return (MODULE_TO_HOST_TYPES as readonly string[]).includes(value.type);
}

/**
 * 构造一条待发送的消息。
 *
 * 注意：调用方**必须**用 `postMessage(msg, targetOrigin)` 的显式 targetOrigin 形式，
 * 不要用 `'*'`——否则上下文与令牌会广播给任意页面。
 */
export function bridgeMessage<T extends BridgeMessage['type']>(
  type: T,
  payload: Omit<Extract<BridgeMessage, { type: T }>, 'namespace' | 'version' | 'type'>,
): Extract<BridgeMessage, { type: T }> {
  return {
    namespace: BRIDGE_NAMESPACE,
    version: BRIDGE_PROTOCOL_VERSION,
    type,
    ...payload,
  } as Extract<BridgeMessage, { type: T }>;
}
