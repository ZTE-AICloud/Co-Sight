/**
 * 侧栏「最近」：领域映射 + 数据源 + 列表交互。
 *
 * 三层分开测，失败时能直接定位到是哪一层坏了：
 * - `toRecentSessions`：过滤、标题优先级、排序（纯函数，不打桩）；
 * - `smartFactoryRecentSource`：地址、分页参数与"字段缺失"的兼容；
 * - `RecentSessions`：5 条截断、展开/收起、选择回传、空态。
 *
 * 不打桩 React Query 或路由：两者都是生产用的真实现，打桩等于在测自己写的假实现。
 */

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { RecentSessions } from '../src/features/recent-sessions';
import { toRecentSessions, type ServiceSession } from '../src/features/recent-sessions/session-view';
import { smartFactoryRecentSource } from '../src/features/recent-sessions/smart-factory-source';
import { zhCN } from '../src/i18n/messages/zh-CN';
import { jsonResponse, renderWithProviders, stubFetch } from './helpers/render';

function messageOf(key: string): string {
  let node: unknown = zhCN;
  for (const segment of key.split('.')) {
    if (typeof node !== 'object' || node === null) break;
    node = (node as Record<string, unknown>)[segment];
  }
  if (typeof node !== 'string') throw new Error(`词表里没有键 ${key}`);
  return node;
}

function raw(overrides: Partial<ServiceSession> & Pick<ServiceSession, 'id'>): ServiceSession {
  return {
    name: '',
    messageCount: 2,
    lastMessage: null,
    updatedAt: '2026-10-26T10:00:00.000Z',
    instance: { agentId: 'agt_1' },
    ...overrides,
  };
}

function stubSessions(items: ServiceSession[]): void {
  stubFetch(() => jsonResponse({ items, total: items.length }));
}

describe('toRecentSessions', () => {
  it('保留自由对话、过滤空会话，按 updatedAt 降序', () => {
    const sessions = toRecentSessions([
      raw({ id: 'sess_old', updatedAt: '2026-10-20T00:00:00.000Z', lastMessage: '旧的' }),
      raw({ id: 'sess_new', updatedAt: '2026-10-26T00:00:00.000Z', lastMessage: '新的' }),
      raw({
        id: 'sess_chat',
        updatedAt: '2026-10-25T00:00:00.000Z',
        instance: { agentId: null },
        lastMessage: '自由对话',
      }),
      raw({ id: 'sess_empty', messageCount: 0, lastMessage: null }),
    ]);

    expect(sessions.map((session) => session.id)).toEqual([
      'sess_new',
      'sess_chat',
      'sess_old',
    ]);
  });

  it('自由对话（agentId=null）也能出现在最近列表', () => {
    const [session] = toRecentSessions([
      raw({ id: 'sess_chat_only', instance: { agentId: null }, lastMessage: '无智能体的对话' }),
    ]);

    expect(session).toMatchObject({
      id: 'sess_chat_only',
      title: '无智能体的对话',
    });
  });

  it('标题优先级：name → firstUserMessage → lastMessage', () => {
    const sessions = toRecentSessions([
      raw({
        id: 'sess_name',
        name: '会话名',
        firstUserMessage: '用户首条',
        lastMessage: '助手回复',
      }),
      raw({ id: 'sess_first_user', name: '', firstUserMessage: '用户首条', lastMessage: '助手回复' }),
      raw({ id: 'sess_last', name: '', firstUserMessage: null, lastMessage: '助手回复' }),
      raw({ id: 'sess_none', name: '', firstUserMessage: null, lastMessage: null }),
    ]);

    const titleOf = (id: string): string | null =>
      sessions.find((session) => session.id === id)?.title ?? null;

    expect(titleOf('sess_name')).toBe('会话名');
    expect(titleOf('sess_first_user')).toBe('用户首条');
    expect(titleOf('sess_last')).toBe('助手回复');
    expect(titleOf('sess_none')).toBeNull();
  });

  it('smart-factory 未上线 firstUserMessage 时按 name / lastMessage 兜底', () => {
    // 老接口没有这个键：字段为 undefined 而不是 null，标题不能因此变成"新会话"。
    const sessions = toRecentSessions([
      raw({ id: 'sess_legacy', name: '手工会话', lastMessage: '兜底文本' }),
      raw({ id: 'sess_legacy_no_name', name: '', lastMessage: '兜底文本' }),
    ]);

    expect(sessions.find((session) => session.id === 'sess_legacy')?.title).toBe('手工会话');
    expect(sessions.find((session) => session.id === 'sess_legacy_no_name')?.title).toBe('兜底文本');
  });

  it('标题只取首个非空行，并去掉 Markdown 的标题/列表前缀', () => {
    const [session] = toRecentSessions([
      raw({ id: 'sess_md', name: '', firstUserMessage: '\n\n## 帮我整理周报\n第二行' }),
    ]);

    expect(session?.title).toBe('帮我整理周报');
  });
});

describe('smartFactoryRecentSource', () => {
  it('按固定上限取列表并映射成列表项', async () => {
    const mock = stubFetch(() =>
      jsonResponse({
        items: [raw({ id: 'sess_1', name: '', firstUserMessage: '你好' })],
        total: 1,
      }),
    );

    const sessions = await smartFactoryRecentSource.list();

    const url = String((mock.mock.calls[0] as [string, ...unknown[]] | undefined)?.[0]);
    expect(url).toContain('http://127.0.0.1:4100/api/smart-factory/v1/sessions/list');
    expect(url).toContain('pageSize=100');
    expect(sessions).toEqual([
      { id: 'sess_1', title: '你好', updatedAt: '2026-10-26T10:00:00.000Z' },
    ]);
  });

  it('非 2xx 抛出错误（界面据此显示加载失败，而不是空列表）', async () => {
    stubFetch(() => jsonResponse({ error: 'boom' }, 500));

    await expect(smartFactoryRecentSource.list()).rejects.toThrow('HTTP 500');
  });
});

/** 不关心选择的用例传它；交互用例各自传具体的回调。 */
function noop(): void {
  /* 故意什么都不做 */
}

describe('RecentSessions', () => {
  it('默认只露出 5 条，点「查看更多」展开全部并可以收起', async () => {
    const items = Array.from({ length: 7 }, (_, index) => {
      const number = index + 1;
      return raw({
        id: `sess_${String(number)}`,
        lastMessage: `会话 ${String(number)}`,
        updatedAt: `2026-10-26T0${String(number)}:00:00.000Z`,
      });
    });
    stubSessions(items);

    const user = userEvent.setup();
    renderWithProviders(<RecentSessions collapsed={false} onOpenSession={noop} />);

    expect(await screen.findByText('会话 7')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(5);

    await user.click(
      screen.getByRole('button', { name: messageOf('recent.showMore').replace('{count}', '7') }),
    );
    expect(screen.getAllByRole('listitem')).toHaveLength(7);

    await user.click(screen.getByRole('button', { name: messageOf('recent.showLess') }));
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
  });

  it('点一条会话把 id 交给壳层（是否跳转、跳到哪由壳层决定）', async () => {
    stubSessions([raw({ id: 'sess_resume', firstUserMessage: '今天星期几' })]);
    const onOpenSession = vi.fn();

    const user = userEvent.setup();
    renderWithProviders(<RecentSessions collapsed={false} onOpenSession={onOpenSession} />);

    await user.click(await screen.findByRole('button', { name: /今天星期几/ }));

    expect(onOpenSession).toHaveBeenCalledWith('sess_resume');
  });

  it('没有标题的会话显示兜底文案', async () => {
    stubSessions([raw({ id: 'sess_untitled' })]);

    renderWithProviders(<RecentSessions collapsed={false} onOpenSession={noop} />);

    expect(await screen.findByText(messageOf('recent.untitled'))).toBeInTheDocument();
  });

  it('为空时显示空态，且不出现「查看更多」', async () => {
    stubSessions([]);

    renderWithProviders(<RecentSessions collapsed={false} onOpenSession={noop} />);

    expect(await screen.findByText(messageOf('recent.empty'))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /查看更多/ })).not.toBeInTheDocument();
  });

  it('折叠态不渲染，也不发请求', () => {
    const mock = stubFetch(() => jsonResponse({ items: [], total: 0 }));

    renderWithProviders(<RecentSessions collapsed onOpenSession={noop} />);

    expect(screen.queryByText(messageOf('recent.heading'))).not.toBeInTheDocument();
    expect(mock).not.toHaveBeenCalled();
  });
});
