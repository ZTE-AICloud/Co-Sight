/**
 * `POST /api/workspaces/pick-directory`（系统目录选择）。
 *
 * 这条路由的价值全在"三种结果分得开"：
 *   - 选中 → `200 + { path }`；
 *   - 取消 → `200 + { path: null }`（正常结果，前端保持原值）；
 *   - 打不开 → `501`（前端提示改手输，而不是假装用户取消了）。
 * 另外两条边界：入参必须是绝对路径；非本机来源（Host 不是回环）直接 403——
 * 这个接口会在用户桌面上弹窗口。
 */

import path from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { DirectoryPickerService, type DialogOutcome, type DialogRunner } from '../src/services/directory-picker';
import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

let context: TestContext;

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

interface Seeded {
  /** 收到的每条命令的 argv（用来断言"起点传下去了"）。 */
  commands: string[][];
}

function useRunner(result: DialogOutcome, env: NodeJS.ProcessEnv = { DISPLAY: ':0' }): Seeded {
  const commands: string[][] = [];
  const runner: DialogRunner = (command) => {
    commands.push([...command.args]);
    return Promise.resolve(result);
  };
  context.services.directoryPicker = new DirectoryPickerService({ platform: 'linux', env, runner });
  return { commands };
}

const PICKED: DialogOutcome = {
  started: true,
  code: 0,
  stdout: '/home/me/projects/demo/\n',
  stderr: '',
  timedOut: false,
};

describe('目录选择接口', () => {
  it('选中后回 200 与绝对路径（尾斜杠去掉）', async () => {
    useRunner(PICKED);
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces/pick-directory',
      payload: { initialPath: null },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().data).toEqual({ path: '/home/me/projects/demo' });
  });

  it('用户取消回 200 与 null——这不是错误', async () => {
    useRunner({ started: true, code: 1, stdout: '', stderr: '', timedOut: false });
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces/pick-directory',
      payload: { initialPath: null },
    });

    expect(response.statusCode).toBe(200);
    expect(response.json().data).toEqual({ path: null });
  });

  it('这台机器弹不出对话框时是 501，不是"取消"', async () => {
    // 没有 DISPLAY / WAYLAND_DISPLAY：服务端连 spawn 都不该试。
    useRunner(PICKED, {});
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces/pick-directory',
      payload: { initialPath: null },
    });

    expect(response.statusCode).toBe(501);
    expect(response.json().error.code).toBe('NOT_IMPLEMENTED');
    expect(response.json().error.messageKey).toBe('error.directory_picker.unavailable');
  });

  it('对话框异常退出（带 stderr）是错误，不是取消', async () => {
    useRunner({ started: true, code: 1, stdout: '', stderr: 'cannot open display', timedOut: false });
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces/pick-directory',
      payload: { initialPath: null },
    });

    expect(response.statusCode).toBe(500);
    expect(response.json().error.messageKey).toBe('error.directory_picker.failed');
  });

  it('相对路径在入口就被拒（422），不会交给对话框命令', async () => {
    const seeded = useRunner(PICKED);
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces/pick-directory',
      payload: { initialPath: 'projects/demo' },
    });

    expect(response.statusCode).toBe(422);
    expect(response.json().error.details[0].path).toBe('initialPath');
    expect(seeded.commands).toEqual([]);
  });

  it('已有的目录会作为起点传给对话框', async () => {
    const seeded = useRunner(PICKED);
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces/pick-directory',
      payload: { initialPath: context.home },
    });

    expect(response.statusCode).toBe(200);
    expect(seeded.commands[0]?.join(' ')).toContain(`--filename=${context.home}${path.sep}`);
  });

  it('非本机来源（Host 不是回环）→ 403：它会在桌面上弹窗口', async () => {
    useRunner(PICKED);
    const response = await context.app.inject({
      method: 'POST',
      url: '/api/workspaces/pick-directory',
      headers: { host: 'evil.example.com' },
      payload: { initialPath: null },
    });

    expect(response.statusCode).toBe(403);
    expect(response.json().error.code).toBe('FORBIDDEN');
    expect(response.json().error.messageKey).toBe('error.forbidden.directory_picker');
  });
});
