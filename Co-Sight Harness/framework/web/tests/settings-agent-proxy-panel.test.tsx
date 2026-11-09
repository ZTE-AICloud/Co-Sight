/**
 * Agent 代理配置面板（设置 → Agent 代理配置）。
 *
 * 本期只展示**一个**代理：smart-factory 的 `GET /engine/detail`。
 * 用例钉三件事：数据来源只有一个 URL、只渲染引擎与版本、没有多代理的增删改入口。
 */

import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

import { AgentProxySettingsPanel } from '../src/features/agent-proxies/AgentProxySettingsPanel';
import { zhCN } from '../src/i18n/messages/zh-CN';
import {
  callUrl,
  jsonResponse,
  renderWithProviders,
  resetUiStore,
  stubFetch,
  stubFetchSequence,
} from './helpers/render';

const P = zhCN.settings.agentProxy;

const DETAIL = {
  engine: 'claude-cli',
  cwd: '/home/me/work',
  version: '2.1.311',
  commandCount: 24,
};

const DETAIL_OK = jsonResponse(DETAIL);
const DETAIL_URL = 'http://127.0.0.1:4100/api/smart-factory/v1/engine/detail';

function renderPanel(): void {
  renderWithProviders(<AgentProxySettingsPanel />);
}

describe('Agent 代理配置面板', () => {
  beforeEach(() => {
    resetUiStore();
  });

  it('只展示引擎与版本，不再展示命令数与工作目录', async () => {
    const mock = stubFetch(DETAIL_OK);
    renderPanel();

    expect(await screen.findByText(P.engine.claudeAgentSdk)).toBeInTheDocument();
    expect(screen.getByText(DETAIL.version)).toBeInTheDocument();
    // 接口仍返回 cwd / commandCount，但面板按产品要求不展示。
    expect(screen.queryByText(DETAIL.cwd)).toBeNull();
    expect(screen.queryByText(String(DETAIL.commandCount))).toBeNull();

    // 只打这一个接口，且没有走框架 `/api` 的信封通道。
    expect(mock).toHaveBeenCalledTimes(1);
    expect(callUrl(mock)).toBe(DETAIL_URL);
  });

  it('未知引擎原样显示标识，不编展示名', async () => {
    stubFetch(jsonResponse({ ...DETAIL, engine: 'some-new-engine' }));
    renderPanel();

    expect(await screen.findByText('some-new-engine')).toBeInTheDocument();
  });

  it('引擎标识撞上 Object.prototype 键名时原样显示，不炸面板', async () => {
    // 响应是未校验的裸 JSON：普通对象查表会把 `constructor` / `toString` 查成函数，
    // 交给 t() 会在 split 上抛异常、整块设置界面掉进错误边界。
    stubFetch(jsonResponse({ ...DETAIL, engine: 'constructor' }));
    renderPanel();

    expect(await screen.findByText('constructor')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('版本号缺失时显示占位符，不渲染空格子', async () => {
    stubFetch(jsonResponse({ engine: 'claude-cli', cwd: DETAIL.cwd, commandCount: 0 }));
    renderPanel();

    expect(await screen.findByText(P.engine.claudeAgentSdk)).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('页签未选中（active=false）时不请求引擎详情', async () => {
    // 每次取详情都会让 smart-factory 起一个 Claude Code 探测进程：设置弹窗把面板
    // 常驻挂载着，只有切到 Agent 代理页签时才该取数。
    const mock = stubFetch(DETAIL_OK);
    renderWithProviders(<AgentProxySettingsPanel active={false} />);

    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
    expect(mock).not.toHaveBeenCalled();
  });

  it('加载失败显示错误与 HTTP 状态，点「重试」再取一次', async () => {
    const user = userEvent.setup();
    const mock = stubFetchSequence([jsonResponse({}, 503), DETAIL_OK]);
    renderPanel();

    const alert = await screen.findByRole('alert');
    expect(within(alert).getByText(P.error.title)).toBeInTheDocument();
    expect(within(alert).getByText(/HTTP 503/)).toBeInTheDocument();

    await user.click(within(alert).getByRole('button', { name: zhCN.error.retry }));

    expect(await screen.findByText(P.engine.claudeAgentSdk)).toBeInTheDocument();
    expect(mock.mock.calls).toHaveLength(2);
  });

  it('没有新增 / 编辑 / 删除 / 设为默认入口：多 Agent 代理暂不开放', async () => {
    stubFetch(DETAIL_OK);
    renderPanel();

    await screen.findByText(P.engine.claudeAgentSdk);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });
});
