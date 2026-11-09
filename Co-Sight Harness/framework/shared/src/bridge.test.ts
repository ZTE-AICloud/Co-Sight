import { describe, expect, test } from 'vitest';

import {
  BRIDGE_NAMESPACE,
  BRIDGE_PROTOCOL_VERSION,
  bridgeMessage,
  isHostToModuleMessage,
  isModuleToHostMessage,
} from './bridge';

const init = {
  namespace: BRIDGE_NAMESPACE,
  version: BRIDGE_PROTOCOL_VERSION,
  type: 'host:init',
} as const;

describe('消息来源鉴别', () => {
  test('同命名空间同版本的宿主消息被接受', () => {
    expect(isHostToModuleMessage({ ...init, moduleId: 'm', locale: 'zh-CN' })).toBe(true);
  });

  test('别的应用的 postMessage 会被拒（iframe 里可能共存其他代码）', () => {
    expect(isHostToModuleMessage({ ...init, namespace: 'some-other-app' })).toBe(false);
  });

  test('协议版本不匹配会被拒，而不是被静默错解', () => {
    expect(isHostToModuleMessage({ ...init, version: BRIDGE_PROTOCOL_VERSION + 1 })).toBe(false);
  });

  test('未知 type 会被拒', () => {
    expect(isHostToModuleMessage({ ...init, type: 'host:run-arbitrary-code' })).toBe(false);
  });

  test('非对象输入不会抛异常', () => {
    expect(isHostToModuleMessage(null)).toBe(false);
    expect(isHostToModuleMessage('host:init')).toBe(false);
    expect(isModuleToHostMessage(undefined)).toBe(false);
  });

  test('宿主与模块的方向互不串台', () => {
    expect(isModuleToHostMessage({ ...init, type: 'host:teardown' })).toBe(false);
    expect(isHostToModuleMessage({ ...init, type: 'module:ready' })).toBe(false);
    expect(isModuleToHostMessage({ ...init, type: 'module:ready' })).toBe(true);
  });
});

describe('bridgeMessage', () => {
  test('自动补齐命名空间与版本', () => {
    const message = bridgeMessage('module:resize', { height: 720 });
    expect(message.namespace).toBe(BRIDGE_NAMESPACE);
    expect(message.version).toBe(BRIDGE_PROTOCOL_VERSION);
    expect(message.height).toBe(720);
  });

  test('host:init 携带一次性令牌与交换地址，令牌不进 URL（D25 = A）', () => {
    const message = bridgeMessage('host:init', {
      moduleId: 'conversation-module',
      locale: 'zh-CN',
      theme: 'light',
      context: { workspaceId: null, expertId: 'e-1', action: 'use', params: {} },
      bridgeToken: 'one-shot',
      exchangeUrl: 'http://localhost:4300/api/bridge/exchange',
    });
    expect(message.bridgeToken).toBe('one-shot');
    expect(message.context.action).toBe('use');
  });
});
