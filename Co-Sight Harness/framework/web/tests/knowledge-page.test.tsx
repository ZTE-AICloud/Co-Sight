/**
 * 知识库页（`/knowledge`，`KnowledgePage`）。
 *
 * 这一页把用户配置的地址嵌进主面板，是「侧栏菜单 → 当前可用路由 → iframe」这条
 * 链路的终点。三个状态各钉一条：
 * - 有可用路由：iframe 的地址就是配置值，标题带上知识库名称；
 * - 没有可用路由：空态里直接给「去设置新增」，点下去落到设置的知识库页签并展开表单；
 * - 读取失败：错误 + 重试，重试真的再打一次接口。
 *
 * 全局断言尽量避开侧栏（`renderApp` 会连带渲染它）：侧栏自己也有链接和按钮。
 */

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { RagKnowledgeBase } from 'harness-shared';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { zhCN } from '../src/i18n/messages/zh-CN';
import { useUiStore } from '../src/stores/ui';
import {
  envelope,
  errorEnvelope,
  jsonResponse,
  renderApp,
  resetUiStore,
  type FakeResponse,
} from './helpers/render';

const K = zhCN.knowledgeRoute;

const ACTIVE_KB: RagKnowledgeBase = {
  id: '77777777-7777-4777-8777-777777777777',
  name: '产品知识库',
  routeUrl: 'https://kb.example.com/kb/42',
  username: null,
  passwordMasked: null,
  hasPassword: false,
  apiKeyMasked: null,
  hasApiKey: false,
  description: null,
  isActive: true,
  createdAt: '2026-01-01T00:00:00.000Z',
  updatedAt: '2026-01-01T00:00:00.000Z',
};

/** 设置弹窗打开后会连带渲染其它配置面板；给它们喂"没有数据"的正常形状。 */
const LIST_PATHS = new Set([
  '/api/models',
  '/api/workspaces',
  '/api/agent-proxies',
  '/api/rag-knowledge',
]);

const NULLABLE_PATHS = new Set([
  '/api/models/active',
  '/api/workspaces/active',
  '/api/agent-proxies/default',
]);

/** 只给 `/rag-knowledge/active` 指定响应；其余接口给外壳与设置面板能读的最小值。 */
function stubActive(response: () => Promise<FakeResponse>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string) => {
      const pathname = new URL(input, 'http://localhost').pathname;
      if (pathname === '/api/rag-knowledge/active') {
        return response();
      }
      if (LIST_PATHS.has(pathname)) {
        return Promise.resolve(jsonResponse(envelope([])));
      }
      if (NULLABLE_PATHS.has(pathname)) {
        return Promise.resolve(jsonResponse(envelope(null)));
      }
      if (pathname === '/api/modules') {
        return Promise.resolve(jsonResponse(envelope({ modules: [], invalid: [] })));
      }
      if (pathname === '/health') {
        return Promise.resolve(
          jsonResponse(
            envelope({
              status: 'ok',
              version: '0.1.0',
              uptimeSeconds: 1,
              cosightHome: '/tmp/cosight-test',
              database: 'sqlite',
            }),
          ),
        );
      }
      // 侧栏「最近」的会话列表等外壳级请求。
      return Promise.resolve(jsonResponse({ items: [], total: 0 }));
    }),
  );
}

beforeEach(() => {
  resetUiStore();
});

describe('KnowledgePage（/knowledge）', () => {
  it('有可用路由时把配置的地址嵌进主面板', async () => {
    stubActive(() => Promise.resolve(jsonResponse(envelope(ACTIVE_KB))));
    renderApp('/knowledge');

    const frame = await screen.findByTitle(K.frameTitle.replace('{name}', ACTIVE_KB.name));
    expect(frame).toHaveAttribute('src', ACTIVE_KB.routeUrl);
    // 地址是用户填的任意站点：iframe 仍然走最小权限沙箱（与 ModuleHost 同一套）。
    expect(frame.getAttribute('sandbox')).toContain('allow-scripts');
    expect(frame.getAttribute('sandbox')).not.toMatch(/(^|\s)allow-top-navigation(\s|$)/);
  });

  it('没有可用路由时给出空态，按钮直接打开设置的新增表单', async () => {
    const user = userEvent.setup();
    stubActive(() => Promise.resolve(jsonResponse(envelope(null))));
    renderApp('/knowledge');

    expect(await screen.findByText(K.missingTitle)).toBeInTheDocument();
    expect(document.querySelector('iframe')).toBeNull();

    await user.click(screen.getByRole('button', { name: K.openSettings }));

    expect(useUiStore.getState().settingsOpen).toBe(true);
    expect(useUiStore.getState().settingsTab).toBe('ragKnowledge');
    // 面板消费请求后直接展开「新增」——不是把用户丢在列表上再找一次按钮。
    expect(await screen.findByText(zhCN.settings.ragKnowledge.createTitle)).toBeInTheDocument();
  });

  it('读取失败时显示错误与重试，重试成功后才嵌入页面', async () => {
    const user = userEvent.setup();
    let attempts = 0;
    stubActive(() => {
      attempts += 1;
      return attempts === 1
        ? Promise.resolve(jsonResponse(errorEnvelope('internal', 'error.internal'), 500))
        : Promise.resolve(jsonResponse(envelope(ACTIVE_KB)));
    });

    renderApp('/knowledge');

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(K.loadFailedTitle);
    expect(document.querySelector('iframe')).toBeNull();

    await user.click(screen.getByRole('button', { name: zhCN.error.retry }));

    expect(
      await screen.findByTitle(K.frameTitle.replace('{name}', ACTIVE_KB.name)),
    ).toBeInTheDocument();
    // 重试是真的又打了一次接口，而不是复用失败结果。
    expect(attempts).toBe(2);
  });
});
