/**
 * 系统目录选择器（`services/directory-picker.ts`）。
 *
 * 这里守的是四类"只会在别人机器上发作"的错误：
 *   1. 没有图形会话时去 spawn，用户拿到一句 GTK 的 `cannot open display`；
 *   2. 工具没装（zenity / pwsh）时没有退路，按钮点了没反应；
 *   3. 把用户给的起点拼进 shell / PowerShell 源码——目录名里一个引号就是注入；
 *   4. 把"取消"与"打不开"混成同一种结果，用户不知道是点错了还是功能坏了。
 */

import os from 'node:os';

import { describe, expect, it, vi } from 'vitest';

import {
  dialogCommands,
  DirectoryPickerService,
  normalizePickedPath,
  runDialogCommand,
  type DialogOutcome,
  type DialogRunner,
} from '../src/services/directory-picker';

const DISPLAY_ENV = { DISPLAY: ':0', HOME: '/home/me' };

function outcome(overrides: Partial<DialogOutcome>): DialogOutcome {
  return { started: true, code: 0, stdout: '', stderr: '', timedOut: false, ...overrides };
}

/** 一个按调用顺序返回预设结果的 runner，并记录收到了哪些命令。 */
function fakeRunner(results: readonly DialogOutcome[]): {
  runner: DialogRunner;
  commands: string[];
} {
  const commands: string[] = [];
  const queue = [...results];
  const runner: DialogRunner = (command) => {
    commands.push(command.file);
    const next = queue.shift();
    if (next === undefined) {
      throw new Error(`runner 被多调用了一次：${command.file}`);
    }
    return Promise.resolve(next);
  };
  return { runner, commands };
}

/**
 * 一个能被测试**从外面**决定何时结束的 runner 返回值。
 *
 * Promise 的 executor 是同步执行的，所以 `pick()` 一返回，`resolve` 就已经可用了；
 * 用它来观察"第二次调用是否复用了同一个 Promise"。
 */
function deferredOutcome(): {
  promise: Promise<DialogOutcome>;
  resolve: (value: DialogOutcome) => void;
} {
  let resolve!: (value: DialogOutcome) => void;
  const promise = new Promise<DialogOutcome>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

describe('按平台选命令', () => {
  it('Linux 没有图形会话时一条候选都不给（不 spawn 一个必然失败的进程）', () => {
    expect(dialogCommands({ platform: 'linux', env: { HOME: '/home/me' } })).toEqual([]);
    expect(dialogCommands({ platform: 'linux', env: { DISPLAY: '' } })).toEqual([]);
  });

  it('Linux 优先 zenity（目录模式 + 起点），退路是 kdialog', () => {
    const commands = dialogCommands({
      platform: 'linux',
      env: DISPLAY_ENV,
      initialPath: '/home/me/projects',
    });

    expect(commands.map((command) => command.file)).toEqual(['zenity', 'kdialog']);
    const zenity = commands[0];
    expect(zenity?.args).toContain('--directory');
    // 结尾斜杠是 zenity 区分"目录"与"要新建的文件"的方式。
    expect(zenity?.args).toContain('--filename=/home/me/projects/');
    expect(commands[1]?.args).toEqual(['--getexistingdirectory', '/home/me/projects', '--title', '选择工作区目录']);
  });

  it('Wayland 会话同样算有图形界面', () => {
    const commands = dialogCommands({ platform: 'linux', env: { WAYLAND_DISPLAY: 'wayland-0' } });
    expect(commands[0]?.file).toBe('zenity');
  });

  it('Windows 先用 pwsh、再用 powershell.exe，且起点只经环境变量传下去', () => {
    const dangerous = "C:\\tmp\\it's; Remove-Item -Recurse C:\\Windows #";
    const commands = dialogCommands({ platform: 'win32', initialPath: dangerous });

    expect(commands.map((command) => command.file)).toEqual(['pwsh', 'powershell.exe']);
    for (const command of commands) {
      expect(command.args).toContain('-STA');
      const script = command.args.at(-1) ?? '';
      // 起点不能出现在脚本源码里：那等于把用户输入当代码执行。
      expect(script).not.toContain('Remove-Item');
      expect(command.env['COSIGHT_DIRECTORY_PICKER_START']).toBe(dangerous);
      // 管道上的中文目录名必须显式切 UTF-8，否则中文系统回的是 GBK。
      expect(script).toContain('[Console]::OutputEncoding');
      expect(script).toContain('UTF8Encoding');
    }
  });

  it('macOS 把起点作为 argv 传给 osascript，取消（-128）在脚本里被接住', () => {
    const commands = dialogCommands({ platform: 'darwin', initialPath: '/Users/me/proj' });
    expect(commands).toHaveLength(1);
    expect(commands[0]?.file).toBe('osascript');
    expect(commands[0]?.args.at(-1)).toBe('/Users/me/proj');
    expect(commands[0]?.args.join(' ')).toContain('on error number -128');
  });
});

describe('选中路径的规范化', () => {
  it('去掉结尾分隔符，根目录本身保留', () => {
    expect(normalizePickedPath('/home/me/proj/\n', 'linux')).toBe('/home/me/proj');
    expect(normalizePickedPath('/', 'linux')).toBe('/');
    expect(normalizePickedPath('C:\\proj\\', 'win32')).toBe('C:\\proj');
    expect(normalizePickedPath('C:\\', 'win32')).toBe('C:\\');
  });

  it('只有空白算"没有选"', () => {
    expect(normalizePickedPath('  \n', 'linux')).toBe('');
  });
});

describe('DirectoryPickerService', () => {
  it('选中后返回去掉尾斜杠的绝对路径', async () => {
    const { runner } = fakeRunner([outcome({ stdout: '/home/me/proj/\n' })]);
    const service = new DirectoryPickerService({ platform: 'linux', env: DISPLAY_ENV, runner });

    await expect(service.pick(null)).resolves.toBe('/home/me/proj');
  });

  it('用户取消（非 0 退出且没有 stderr）返回 null，不当作失败', async () => {
    const { runner } = fakeRunner([outcome({ code: 1 })]);
    const service = new DirectoryPickerService({ platform: 'linux', env: DISPLAY_ENV, runner });

    await expect(service.pick(null)).resolves.toBeNull();
  });

  it('zenity 没装时自动退到 kdialog', async () => {
    const { runner, commands } = fakeRunner([
      outcome({ started: false, code: null, stderr: 'spawn zenity ENOENT' }),
      outcome({ stdout: '/srv/work' }),
    ]);
    const service = new DirectoryPickerService({ platform: 'linux', env: DISPLAY_ENV, runner });

    await expect(service.pick(null)).resolves.toBe('/srv/work');
    expect(commands).toEqual(['zenity', 'kdialog']);
  });

  it('候选全都打不开 → NOT_IMPLEMENTED（前端据此提示手输）', async () => {
    const { runner } = fakeRunner([
      outcome({ started: false, code: null }),
      outcome({ started: false, code: null }),
    ]);
    const service = new DirectoryPickerService({ platform: 'linux', env: DISPLAY_ENV, runner });

    await expect(service.pick(null)).rejects.toMatchObject({
      code: 'NOT_IMPLEMENTED',
      messageKey: 'error.directory_picker.unavailable',
    });
  });

  it('没有图形会话时连 runner 都不调', async () => {
    const { runner, commands } = fakeRunner([]);
    const service = new DirectoryPickerService({ platform: 'linux', env: { HOME: '/home/me' }, runner });

    await expect(service.pick(null)).rejects.toMatchObject({ code: 'NOT_IMPLEMENTED' });
    expect(commands).toEqual([]);
  });

  it('工具带 stderr 退出 → 说"异常退出"，而不是说"已取消"', async () => {
    // 两个候选都带 stderr 失败：这一轮没有"用户取消"，必须报错。
    const { runner } = fakeRunner([
      outcome({ code: 1, stderr: 'Unable to init server: Could not connect: Connection refused' }),
      outcome({ code: 1, stderr: 'cannot connect to X server' }),
    ]);
    const service = new DirectoryPickerService({ platform: 'linux', env: DISPLAY_ENV, runner });

    await expect(service.pick(null)).rejects.toMatchObject({
      code: 'INTERNAL',
      messageKey: 'error.directory_picker.failed',
    });
  });

  it('超时 → 报超时，不谎报成取消', async () => {
    const { runner } = fakeRunner([outcome({ code: null, timedOut: true })]);
    const service = new DirectoryPickerService({
      platform: 'linux',
      env: DISPLAY_ENV,
      runner,
      timeoutMs: 1000,
    });

    await expect(service.pick(null)).rejects.toMatchObject({
      messageKey: 'error.directory_picker.timeout',
    });
  });

  it('起点必须是真实存在的目录，否则退回系统默认位置', async () => {
    const commandsSeen: string[][] = [];
    const runner: DialogRunner = (command) => {
      commandsSeen.push([...command.args]);
      return Promise.resolve(outcome({ code: 1 }));
    };
    const service = new DirectoryPickerService({ platform: 'linux', env: DISPLAY_ENV, runner });

    await service.pick('/definitely/not/a/real/directory/cosight');
    // HOME 成了起点，而不是那个不存在的路径。
    expect(commandsSeen[0]?.join(' ')).toContain('--filename=/home/me/');
  });

  it('连点两次共用同一次对话框（不会弹出第二个模态窗口）', async () => {
    const firstDialog = deferredOutcome();
    const runner = vi.fn(() => firstDialog.promise);
    const service = new DirectoryPickerService({ platform: 'linux', env: DISPLAY_ENV, runner });

    const first = service.pick(null);
    const second = service.pick(null);
    firstDialog.resolve(outcome({ stdout: '/home/me/picked' }));

    await expect(first).resolves.toBe('/home/me/picked');
    await expect(second).resolves.toBe('/home/me/picked');
    expect(runner).toHaveBeenCalledTimes(1);

    // 上一次结束后，下一次是新的对话框。
    const secondDialog = deferredOutcome();
    runner.mockImplementation(() => secondDialog.promise);
    const third = service.pick(null);
    secondDialog.resolve(outcome({ stdout: '/home/me/other' }));
    await expect(third).resolves.toBe('/home/me/other');
  });

  it('默认起点取 HOME（存在的话）', async () => {
    const commandsSeen: string[][] = [];
    const runner: DialogRunner = (command) => {
      commandsSeen.push([...command.args]);
      return Promise.resolve(outcome({ code: 1 }));
    };
    const service = new DirectoryPickerService({
      platform: 'linux',
      env: { DISPLAY: ':0', HOME: os.tmpdir() },
      runner,
    });

    await service.pick(null);
    expect(commandsSeen[0]?.join(' ')).toContain(`--filename=${os.tmpdir()}/`);
  });
});

describe('真实 spawn（不依赖图形界面）', () => {
  it('把子进程的 stdout 原样收回来', async () => {
    const result = await runDialogCommand(
      { file: process.execPath, args: ['-e', "process.stdout.write('/tmp/picked\\n')"], env: {} },
      10_000,
    );

    expect(result.started).toBe(true);
    expect(result.code).toBe(0);
    expect(result.stdout).toBe('/tmp/picked\n');
  });

  it('可执行文件不存在时 started=false（调用方据此换候选）', async () => {
    const result = await runDialogCommand(
      { file: 'cosight-no-such-dialog-tool', args: [], env: {} },
      10_000,
    );

    expect(result.started).toBe(false);
  });

  it('超时会杀掉子进程，并给出 timedOut', async () => {
    const result = await runDialogCommand(
      { file: process.execPath, args: ['-e', 'setTimeout(() => {}, 60_000)'], env: {} },
      150,
    );

    expect(result.started).toBe(true);
    expect(result.timedOut).toBe(true);
  });
});
