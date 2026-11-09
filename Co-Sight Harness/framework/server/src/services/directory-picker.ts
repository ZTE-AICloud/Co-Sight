/**
 * 系统目录选择器：在这台机器的桌面上弹一个原生的「选文件夹」对话框。
 *
 * ## 为什么必须由服务端来弹
 *
 * 浏览器拿不到绝对路径。`<input type="file" webkitdirectory>` 只给 `File` 对象，
 * `showDirectoryPicker()` 给的是 `FileSystemDirectoryHandle`——两者都没有路径。
 * 而工作区要存的是**这台机器上**的绝对路径，所以对话框只能在服务端这一侧拉起：
 * 服务端与本机桌面在同一个用户会话里，前端只是在同一台机器上的另一个客户端。
 *
 * ## 只跑固定命令，用户输入不拼进命令行
 *
 * 候选命令是一张常量表（`dialogCommands`），`spawn` **不开 shell**；
 * 用户给过来的"起始目录"只以 **argv 元素**或**环境变量**的形式传下去
 * （Windows 那条尤其要注意：它把脚本作为 `-Command` 的一个参数，若把路径拼进
 * PowerShell 源码，一个带 `'` 或 `;` 的目录名就是一条注入）。
 *
 * ## 取消与失败分得开
 *
 * 用户点「取消」是**正常结果**（返回 `null`），不是错误：前端据此保持原值。
 * 只有"这台机器没有可用的对话框"（`NOT_IMPLEMENTED`）与"工具真的报错了"
 * （带 stderr / 超时）才抛错，前端会提示改用手输。三种情况必须分开——
 * 把"打不开对话框"说成"你取消了"，用户会以为是自己点错了。
 *
 * ## 一次只开一个
 *
 * 对话框是**模态的系统窗口**，同时开两个会把用户逼进"关掉一个才能操作另一个"。
 * 连点两次按钮（或两个标签页同时点）共用同一次选择：`pending` 上的 promise
 * 被复用，结果一起返回。这比回一个 409 更贴用户想做的事。
 */

import { spawn, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import { AppError } from 'harness-shared';

/** 对话框可以停留多久。用户可能在窗口里翻很久，但不能无限占着请求。 */
export const DEFAULT_PICK_TIMEOUT_MS = 300_000;

/**
 * 传"起始目录"用的环境变量名。
 *
 * 用它而不是直接当参数传：PowerShell 的 `-Command` 拿到的是一个**代码字符串**，
 * 往里面拼路径就等于拼代码。环境变量在脚本运行期才被读出来，值不会被解析。
 */
const START_ENV_KEY = 'COSIGHT_DIRECTORY_PICKER_START';

/** 对话框标题。与服务端其它面向用户的文案同口径：中文。 */
const DIALOG_TITLE = '选择工作区目录';

/** 输出上限。选中的路径本身有 1024 的上限，留余量防止异常工具刷屏。 */
const MAX_OUTPUT_BYTES = 8 * 1024;

export interface DialogCommand {
  /** 可执行文件名（不含路径，走 PATH 查找）。 */
  readonly file: string;
  readonly args: readonly string[];
  /** 追加到子进程环境上的变量（合并进 `process.env`，不替换整个环境）。 */
  readonly env: Readonly<Record<string, string>>;
}

export interface DialogOutcome {
  /**
   * 命令是否真的启动起来了。`false` 表示系统里没有这个可执行文件（ENOENT），
   * 这时换下一个候选；启动之后带 stderr 失败**也**会换下一个（见
   * `DirectoryPickerService`），只有全部候选都没成时才报错。
   */
  readonly started: boolean;
  readonly code: number | null;
  readonly stdout: string;
  readonly stderr: string;
  readonly timedOut: boolean;
}

/** 执行一条对话框命令。单独抽成类型是为了测试能注入假 runner，不去真的开窗口。 */
export type DialogRunner = (command: DialogCommand, timeoutMs: number) => Promise<DialogOutcome>;

export interface DialogCommandOptions {
  platform?: NodeJS.Platform;
  env?: NodeJS.ProcessEnv;
  /** **已经确认存在**的起始目录；不存在或为 null 时对话框从默认位置打开。 */
  initialPath?: string | null;
}

/**
 * 当前平台上可用的对话框命令，按优先顺序。
 *
 * 返回空数组 = 这个环境里根本没法弹（例如 Linux 上没有图形会话）——
 * 调用方据此回 `NOT_IMPLEMENTED`，而不是去 spawn 一个必然会失败的东西。
 */
export function dialogCommands(options: DialogCommandOptions = {}): DialogCommand[] {
  const platform = options.platform ?? process.platform;
  const env = options.env ?? process.env;
  const initial = options.initialPath ?? null;

  if (platform === 'win32') {
    return windowsCommands(initial);
  }
  if (platform === 'darwin') {
    return darwinCommands(initial);
  }
  return linuxCommands(env, initial);
}

/**
 * Windows：PowerShell + `FolderBrowserDialog`。
 *
 * 先试 `pwsh`（PowerShell 7）再退到 `powershell.exe`（Windows PowerShell 5.1）：
 * 前者跑在 .NET Core 上，它的 `FolderBrowserDialog` 是 Vista 风格的资源管理器对话框；
 * 后者的 .NET Framework 版本是老的树形对话框。两者都能选目录，新系统上能拿到更好的
 * 就用更好的；`pwsh` 没装是常态（ENOENT → 换下一个），不是错误。
 *
 * `-STA` 不是可选项：`FolderBrowserDialog` 是 COM 组件，必须跑在单线程单元里。
 * 输出编码必须显式设成 UTF-8：`powershell.exe` 在**管道**上默认用系统 OEM 代码页
 * （中文系统是 GBK），中文目录名回来就是乱码——而这一点在开发机上永远看不出来。
 */
function windowsCommands(initialPath: string | null): DialogCommand[] {
  const script = [
    '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)',
    'Add-Type -AssemblyName System.Windows.Forms | Out-Null',
    '$dialog=New-Object System.Windows.Forms.FolderBrowserDialog',
    `$dialog.Description='${DIALOG_TITLE}'`,
    '$dialog.ShowNewFolderButton=$true',
    `$start=$env:${START_ENV_KEY}`,
    'if($start -and (Test-Path -LiteralPath $start -PathType Container)){$dialog.SelectedPath=$start}',
    'if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){[Console]::Out.Write($dialog.SelectedPath)}',
  ].join('; ');

  const env = initialPath === null ? {} : { [START_ENV_KEY]: initialPath };
  return ['pwsh', 'powershell.exe'].map((file) => ({
    file,
    args: ['-NoProfile', '-NonInteractive', '-STA', '-Command', script],
    env,
  }));
}

/**
 * macOS：`choose folder`。取消会抛 `-128`，脚本里接住并返回空串——
 * 于是"取消"落成 exit 0 + 空输出，与 Windows/Linux 同一种判定。
 *
 * 起始目录先转成 alias；目录不存在时转 alias 会失败（-1700），此时退回不带
 * `default location` 的对话框。**不能**把这个 try 和取消混在一起：那样取消会
 * 被当成"起始目录无效"，然后弹第二个窗口。
 */
const APPLE_SCRIPT = `on run argv
  set startDir to item 1 of argv
  set startAlias to missing value
  try
    if startDir is not "" then set startAlias to (POSIX file startDir) as alias
  end try
  try
    if startAlias is missing value then
      set chosen to choose folder with prompt "${DIALOG_TITLE}"
    else
      set chosen to choose folder with prompt "${DIALOG_TITLE}" default location startAlias
    end if
  on error number -128
    return ""
  end try
  return POSIX path of chosen
end run`;

function darwinCommands(initialPath: string | null): DialogCommand[] {
  return [
    {
      file: 'osascript',
      // 起始目录作为 argv 传进去（脚本里的 `on run argv` 接），不拼进脚本源码。
      args: ['-e', APPLE_SCRIPT, initialPath ?? ''],
      env: {},
    },
  ];
}

/**
 * Linux/BSD：先 `zenity`（GTK/GNOME 系），没有再退 `kdialog`（KDE 系）。
 *
 * 没有 `DISPLAY` 也没有 `WAYLAND_DISPLAY` 时直接返回空数组：这是"服务器上跑着、
 * 没有桌面"的常见情形，spawn 出去也只会拿到一句 `cannot open display`，
 * 不如在门口就说清楚"这台机器弹不出来"。
 */
function linuxCommands(env: NodeJS.ProcessEnv, initialPath: string | null): DialogCommand[] {
  const hasDisplay =
    (env['DISPLAY'] !== undefined && env['DISPLAY'] !== '') ||
    (env['WAYLAND_DISPLAY'] !== undefined && env['WAYLAND_DISPLAY'] !== '');
  if (!hasDisplay) {
    return [];
  }

  const start = initialPath ?? env['HOME'] ?? null;
  const commands: DialogCommand[] = [];
  if (start === null) {
    commands.push({ file: 'zenity', args: ['--file-selection', '--directory', `--title=${DIALOG_TITLE}`], env: {} });
    commands.push({ file: 'kdialog', args: ['--getexistingdirectory'], env: {} });
    return commands;
  }

  // zenity 用结尾的斜杠表示"这是一个目录"，否则会把起点当成要新建的文件名。
  commands.push({
    file: 'zenity',
    args: ['--file-selection', '--directory', `--title=${DIALOG_TITLE}`, `--filename=${withTrailingSeparator(start)}`],
    env: {},
  });
  commands.push({ file: 'kdialog', args: ['--getexistingdirectory', start, '--title', DIALOG_TITLE], env: {} });
  return commands;
}

/** 跑一条对话框命令，把退出码/输出/超时收成一个结果对象（**不抛**）。 */
export function runDialogCommand(
  command: DialogCommand,
  timeoutMs: number = DEFAULT_PICK_TIMEOUT_MS,
): Promise<DialogOutcome> {
  return new Promise((resolve) => {
    let settled = false;
    let timedOut = false;
    let stdout = '';
    let stderr = '';

    const finish = (outcome: DialogOutcome): void => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(outcome);
    };

    let child: ChildProcess | null = null;
    try {
      child = spawn(command.file, [...command.args], {
        stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, ...command.env },
        // Windows 上 pwsh/powershell.exe 会不会闪一个控制台窗口，取决于这个开关。
        windowsHide: true,
      });
    } catch (error) {
      // 同步抛出只可能是参数非法（如 NUL 字节），按"启动不了"处理。
      finish({ started: false, code: null, stdout: '', timedOut: false, stderr: String(error) });
      return;
    }
    if (child === null) {
      // 上面的 catch 已经 return 了，这一条只是让类型收窄；不影响行为。
      return;
    }
    // 收进 const：闭包里用 `child` 会丢掉上面的收窄（`let` 可能被重新赋值）。
    const running = child;
    // `stdio` 明确给了 pipe，所以这两个流一定存在；类型上它们是可空的。
    const stdoutStream = running.stdout;
    const stderrStream = running.stderr;

    const timer = setTimeout(() => {
      timedOut = true;
      running.kill();
    }, timeoutMs);

    stdoutStream?.setEncoding('utf8');
    stderrStream?.setEncoding('utf8');
    stdoutStream?.on('data', (chunk: string) => {
      if (stdout.length < MAX_OUTPUT_BYTES) {
        stdout += chunk;
      }
    });
    stderrStream?.on('data', (chunk: string) => {
      if (stderr.length < MAX_OUTPUT_BYTES) {
        stderr += chunk;
      }
    });

    // ENOENT 走这里：说明这个工具没装，调用方会换下一个候选。
    running.on('error', (error: NodeJS.ErrnoException) => {
      clearTimeout(timer);
      finish({
        started: false,
        code: null,
        stdout,
        stderr: stderr === '' ? error.message : stderr,
        timedOut,
      });
    });

    running.on('close', (code) => {
      clearTimeout(timer);
      finish({ started: true, code, stdout, stderr, timedOut });
    });
  });
}

export interface DirectoryPickerOptions {
  platform?: NodeJS.Platform;
  env?: NodeJS.ProcessEnv;
  timeoutMs?: number;
  /** 测试注入；默认真的 spawn。 */
  runner?: DialogRunner;
}

export class DirectoryPickerService {
  private readonly platform: NodeJS.Platform;
  private readonly env: NodeJS.ProcessEnv;
  private readonly timeoutMs: number;
  private readonly runner: DialogRunner;
  /** 正在等待用户选择的那一次；第二次调用直接复用它（见文件头）。 */
  private pending: Promise<string | null> | null = null;

  constructor(options: DirectoryPickerOptions = {}) {
    this.platform = options.platform ?? process.platform;
    this.env = options.env ?? process.env;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_PICK_TIMEOUT_MS;
    this.runner = options.runner ?? runDialogCommand;
  }

  /**
   * 弹出对话框，返回用户选中的绝对路径；用户取消返回 `null`。
   *
   * `initialPath` 只是起点：不存在、不是目录、或为空时，对话框从系统默认位置打开。
   * 它**不校验合法性**——调用方已经按契约验证过绝对路径，这里只做"能不能当起点"。
   */
  pick(initialPath: string | null): Promise<string | null> {
    if (this.pending !== null) {
      return this.pending;
    }
    const task = this.run(initialPath).finally(() => {
      this.pending = null;
    });
    this.pending = task;
    return task;
  }

  private async run(initialPath: string | null): Promise<string | null> {
    const commands = dialogCommands({
      platform: this.platform,
      env: this.env,
      initialPath: existingDirectory(initialPath),
    });
    if (commands.length === 0) {
      throw unavailable();
    }

    let lastFailure: DialogOutcome | null = null;
    for (const command of commands) {
      const outcome = await this.runner(command, this.timeoutMs);
      if (!outcome.started) {
        // 没装这个工具 → 换下一个候选。
        continue;
      }
      if (outcome.timedOut) {
        throw new AppError(
          'INTERNAL',
          'error.directory_picker.timeout',
          `目录选择器等待超时（${String(Math.round(this.timeoutMs / 1000))} 秒），请手动输入路径`,
          { cause: new Error(lastLine(outcome.stderr)) },
        );
      }
      if (outcome.code === 0) {
        const picked = normalizePickedPath(outcome.stdout, this.platform);
        return picked === '' ? null : picked;
      }
      if (outcome.stderr.trim() === '') {
        // 三个平台在用户取消时都是"非 0 退出、什么也不说"（zenity/kdialog 是 1，
        // osascript 已经在脚本里接住 -128 了）。有 stderr 才是真的出错。
        return null;
      }
      // 启动起来了但报了错（典型：zenity 装了但连不上 X）：换下一个候选再试一次。
      // 一个坏掉的 zenity 不该让 KDE 上的用户用不了这个功能。
      lastFailure = outcome;
    }

    if (lastFailure === null) {
      // 所有候选都是"没装"：与一开始就没有候选同一种结论。
      throw unavailable();
    }
    throw new AppError('INTERNAL', 'error.directory_picker.failed', '目录选择器异常退出，请手动输入路径', {
      cause: new Error(lastLine(lastFailure.stderr)),
    });
  }
}

/**
 * 对话框回传的路径。两个平台会带尾分隔符（`POSIX path of` 一定带，
 * 用户也可能选到根目录），统一去掉；根目录本身保留。
 */
export function normalizePickedPath(raw: string, platform: NodeJS.Platform = process.platform): string {
  const trimmed = raw.replace(/[\r\n]+$/u, '').trim();
  if (trimmed === '') {
    return '';
  }
  const pathImpl = platform === 'win32' ? path.win32 : path.posix;
  const root = pathImpl.parse(trimmed).root;
  let result = trimmed;
  while (result.length > root.length && /[\\/]$/u.test(result)) {
    result = result.slice(0, -1);
  }
  return result;
}

function unavailable(): AppError {
  return new AppError(
    'NOT_IMPLEMENTED',
    'error.directory_picker.unavailable',
    '这台机器上打不开系统目录选择器（没有可用的图形界面或对话框工具），请手动输入路径',
  );
}

/** 起点只接受"真实存在的目录"：不存在时交给对话框会报错或落到奇怪的位置。 */
function existingDirectory(candidate: string | null): string | null {
  if (candidate === null) {
    return null;
  }
  const trimmed = candidate.trim();
  if (trimmed === '') {
    return null;
  }
  try {
    return fs.statSync(trimmed).isDirectory() ? trimmed : null;
  } catch {
    return null;
  }
}

function withTrailingSeparator(target: string): string {
  return /[\\/]$/u.test(target) ? target : `${target}${path.sep}`;
}

/** 只取最后一行非空输出给 cause：真机上 PowerShell/GTK 会把整段调用栈打进来。 */
function lastLine(text: string): string {
  const lines = text
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .filter((line) => line !== '');
  return lines.at(-1) ?? '（无输出）';
}
