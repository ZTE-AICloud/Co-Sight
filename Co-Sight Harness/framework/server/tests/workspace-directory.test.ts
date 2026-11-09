/**
 * 工作区目录派生（`lib/slug.ts` + `services/workspaces.ts` 的分配循环）。
 *
 * 与 `api-module-workspace.test.ts` 的分工：那边测"经 HTTP 走一遍之后的形状"，
 * 这边测**纯函数本身**与**分配算法在磁盘上留下的痕迹**。分开的理由是纯函数那一半
 * 一次能覆盖几十个输入（表格驱动），而每一条都走一遍 HTTP 要慢两个数量级；
 * 反过来，分配算法的碰撞/大小写/符号链接那几条只能真的碰磁盘才测得出来。
 *
 * 这个文件里最要紧的一条仍然是**安全**：工作区名是用户输入，而它是一个路径段。
 * 表格里的 `../../etc`、`..`、`/etc/passwd` 不是"边缘输入"，是每个应用都会收到的输入。
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { buildApp } from '../src/app';
import { loadConfig } from '../src/config/env';
import { PUBLIC_WORKSPACE_DIR_NAME } from '../src/config/paths';
import {
  directorySlugAttempt,
  FALLBACK_DIRECTORY_SLUG,
  isDirectorySlug,
  MAX_DIRECTORY_SLUG_LENGTH,
  toDirectorySlug,
} from '../src/lib/slug';
import { closeServices, createServices, type Services } from '../src/services/container';
import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

describe('toDirectorySlug：用户输入永远变不成一个能穿出去的路径段', () => {
  /*
   * 表格的每一行是一类真实输入。**期望值是手写的**——从实现里反推期望值，
   * 等于把"实现做了什么"当成"实现该做什么"。
   */
  const cases: [string, string, string][] = [
    // 中文原样保留：主路径是中文名，折成一串 `-` 会让用户打开根目录看到一屏 `-----`
    ['周报助手开发', '周报助手开发', '中文不该被折掉'],
    // 路径穿越：这是本表存在的全部理由
    ['../../etc', 'etc', '`..` 与 `/` 被一起吃成连字符后再剥掉'],
    ['..', FALLBACK_DIRECTORY_SLUG, '纯 `..` 连一个可保留字符都没有'],
    ['/etc/passwd', 'etc-passwd', '绝对路径降级成相对的一段'],
    ['C:\\Windows', 'C-Windows', 'Windows 盘符与反斜杠'],
    ['~/Documents', 'Documents', '`~` 与 `/` 都不在保留集里'],
    ['a\u0000b', 'a-b', 'NUL 与其它控制字符'],
    // 折叠与去边界
    ['  前后空格  ', '前后空格', '首尾空白'],
    ['a---b', 'a-b', '连续分隔折叠成一个'],
    ['-a-', 'a', '首尾的 `-` 被剥掉'],
    ['a.', 'a', '尾部的 `.` 在 Windows 上会被静默吃掉，不能留'],
    ['a b', 'a-b', '空格折成连字符'],
    // 框架保留命名空间：用户无论如何落不到 `_` 开头的名字里
    ['_public', 'public', '前导 `_` 被剥掉，用户拿不到框架的命名空间'],
    ['__x', 'x', '连续前导下划线一起剥'],
    // NFKC
    ['ＡＢ１２', 'AB12', '全角字母数字折成半角，否则会生成两个看着一样的目录名'],
    ['①号', '1号', '兼容字符折成基字符'],
    // 没有可保留字符时的兜底
    ['。。。', FALLBACK_DIRECTORY_SLUG, '`。` 是标点类，不在保留集里'],
    ['///', FALLBACK_DIRECTORY_SLUG, '纯分隔符'],
    ['---', FALLBACK_DIRECTORY_SLUG, '纯连字符'],
    ['', FALLBACK_DIRECTORY_SLUG, '空串'],
    ['   ', FALLBACK_DIRECTORY_SLUG, '纯空白'],
    // 保留集的边界：下划线与数字可以出现在中间
    ['a_b', 'a_b', '下划线是保留字符，只有前导/尾随的那几个才剥'],
    ['2026-Q1', '2026-Q1', '数字与连字符'],
    ['🚀项目', '项目', 'emoji 不是字母类，被吃掉'],
    // Windows 保留设备名：这几种名字在 Windows 上建不出目录，接个后缀绕开。
    // 本机（Linux）建得出来，所以只有这张表能守住——见 lib/slug.ts 的说明。
    ['CON', 'CON-ws', '控制台设备名，大小写不敏感'],
    ['nul', 'nul-ws', '小写同样撞'],
    ['COM1', 'COM1-ws', '串口'],
    ['LPT9', 'LPT9-ws', '并口，清单到 9 为止'],
    ['COM0', 'COM0', 'COM0 不在微软的清单里，不该被改'],
    ['console', 'console', '只是前缀相同的普通名字，照原样留着'],
  ];

  for (const [input, expected, why] of cases) {
    it(`${JSON.stringify(input)} → ${JSON.stringify(expected)}（${why}）`, () => {
      expect(toDirectorySlug(input)).toBe(expected);
    });
  }

  it('输出的每一条都通过 isDirectorySlug 自检', () => {
    // 把上面那些输入整体喂一遍，断言"生成的东西一定是合法的目录名"。
    // 这比逐条断言目录名更根本：将来调整规则时，这条会挡住"忘了收边界"的改动。
    for (const [input] of cases) {
      const slug = toDirectorySlug(input);
      expect(isDirectorySlug(slug), `${JSON.stringify(input)} → ${slug} 不是合法目录名`).toBe(true);
    }
  });

  it('超长中文名截到 48 个码点', () => {
    const slug = toDirectorySlug('汉'.repeat(60));
    expect([...slug].length).toBe(MAX_DIRECTORY_SLUG_LENGTH);
    // 按字节算：48 个汉字 = 144 字节，离 ext4 单组件 255 字节上限还有余量
    expect(Buffer.byteLength(slug, 'utf8')).toBe(144);
  });

  it('截断不会把星际平面字符切成孤立代理项', () => {
    /*
     * 这是"按码点切"而不是"按 UTF-16 单位切"的全部理由。用 `slice(0, 48)` 切
     * 一串 2 个 UTF-16 单位的字符，第 48 位会落在**代理对的中间**，得到一个
     * 孤立代理项——那是一个无法编码进文件名的串，`mkdir` 会抛 ERR_INVALID_ARG_VALUE，
     * 而错误信息（"path must be a string without null bytes"）完全指不到这里。
     */
    const astral = String.fromCodePoint(0x10400); // 迪塞雷特大写字母，\p{L}，UTF-8 4 字节
    const slug = toDirectorySlug(astral.repeat(60));

    expect([...slug].length).toBe(MAX_DIRECTORY_SLUG_LENGTH);
    expect(Buffer.byteLength(slug, 'utf8')).toBe(MAX_DIRECTORY_SLUG_LENGTH * 4);
    // 往返回 utf8：孤立代理项在这里会变成 U+FFFD，于是这条会红。
    expect(Buffer.from(slug, 'utf8').toString('utf8')).toBe(slug);
    expect(isDirectorySlug(slug)).toBe(true);
  });

  it('截断之后如果尾巴正好落在连字符上，也要再剥一次', () => {
    // 48 个 `a` 后面接连字符：截断点上恰好是 `-`，不修的话目录名以 `-` 结尾。
    const slug = toDirectorySlug(`${'a'.repeat(48)}-尾`);
    expect(slug.endsWith('-')).toBe(false);
    expect(isDirectorySlug(slug)).toBe(true);
  });

  it('是纯函数：同样的输入永远同样的输出，且不碰磁盘', () => {
    expect(toDirectorySlug('周报 / 2026')).toBe(toDirectorySlug('周报 / 2026'));
  });
});

describe('directorySlugAttempt：冲突时怎么改名', () => {
  it('1 → 原名，2 → -2，99 → -99', () => {
    expect(directorySlugAttempt('周报', 1)).toBe('周报');
    expect(directorySlugAttempt('周报', 2)).toBe('周报-2');
    expect(directorySlugAttempt('周报', 99)).toBe('周报-99');
  });

  it('加后缀之后仍是合法目录名', () => {
    for (const index of [1, 2, 9, 99]) {
      expect(isDirectorySlug(directorySlugAttempt('周报', index))).toBe(true);
    }
  });
});

describe('分配循环：磁盘上真的发生了什么', () => {
  let context: TestContext;

  beforeAll(async () => {
    context = await createTestContext();
  });

  afterAll(async () => {
    await destroyTestContext(context);
  });

  const root = () => context.services.paths.workspaces;

  /** 根下不属于框架自用命名空间的条目。 */
  const entries = () =>
    fs.readdirSync(root()).filter((entry) => entry !== PUBLIC_WORKSPACE_DIR_NAME).toSorted();

  /**
   * 建一个工作区，走"框架自己建目录"那条路。
   *
   * 四个字段一个不落地写出来，而不是省掉几个：服务层收的是**已经解析过的契约值**，
   * `createWorkspaceInputSchema` 里那几个 `default(null)` 是路由上的 zod 干的活，
   * 类型上 `CreateWorkspaceInput` 的四个字段都是必填。省掉 `directory` 会给到
   * `undefined`，而 `#bindDirectory` 判的是 `!== null`，于是它会把 `undefined`
   * 当成"用户填了路径"原样返回——落库变成 NULL，等于"这条工作区没有目录"，
   * 与"不传就帮我建一个"正好相反。类型挡住了这个写法，这个注释只是说明**为什么**。
   */
  const create = (name: string) =>
    context.services.workspaces.create({
      name,
      directory: null,
      defaultModelId: null,
      defaultAgentId: null,
    });

  it('目录被手工占着（库里没有记录）→ 换下一个候选 `-2`', async () => {
    fs.mkdirSync(path.join(root(), '手工占位'));

    const created = await create('手工占位');
    expect(path.basename(String(created.directory))).toBe('手工占位-2');
  });

  it('大小写不同的占用同样算冲突（`Report` 占着则 `report` 拿 `report-2`）', async () => {
    /*
     * macOS APFS / Windows NTFS / 部分网络挂载上 `Report` 与 `report` 是同一个目录，
     * 而 SQLite 的文本比较是大小写**敏感**的——库里的重名检查挡不住这一层。
     * 这条在 Linux 上也必须过：判重的正确性不该取决于跑在哪台机器上。
     */
    fs.mkdirSync(path.join(root(), 'Report'));

    const created = await create('report');
    expect(path.basename(String(created.directory))).toBe('report-2');
  });

  it('目录被手工删掉但记录还在 → 仍然算冲突（库里那一份也要看）', async () => {
    /*
     * 两个来源必须都看，少一个就是一个真实的重复目录：
     * - 只看磁盘：用户手工删掉目录后，下一次创建会**抢到同一个目录名**，
     *   于是两条记录的 `directory` 指向同一处；
     * - 只看库：同事手工 `mkdir` 一个目录进去就被覆盖掉。
     *
     * 这里用两个不同的名字去撞**同一个 slug**（`a/b` 与 `a b` 都折成 `a-b`），
     * 因为同名会被 409 挡在更前面，根本走不到目录分配那一步。
     */
    const first = await create('a/b');
    expect(path.basename(String(first.directory))).toBe('a-b');
    fs.rmSync(String(first.directory), { recursive: true, force: true });

    const second = await create('a b');
    expect(path.basename(String(second.directory))).toBe('a-b-2');
    expect(second.directory).not.toBe(first.directory);
  });

  it('存的是 realpath，不是拼出来的字符串', async () => {
    const created = await create('realpath 用例');
    const directory = String(created.directory);
    expect(directory).toBe(fs.realpathSync(directory));
  });

  it('改名不重命名目录', async () => {
    const created = await create('稳定性用例');
    const directory = String(created.directory);

    const updated = await context.services.workspaces.update(created.id, { name: '改过名的' });
    expect(updated?.name).toBe('改过名的');
    expect(updated?.directory).toBe(directory);
    expect(fs.existsSync(directory)).toBe(true);
  });

  it('删除会连同框架创建的工作区目录一起删掉', async () => {
    const created = await create('删除目录用例');
    const directory = String(created.directory);
    fs.writeFileSync(path.join(directory, '用户文件.txt'), '内容');

    const result = await context.services.workspaces.deleteById(created.id);

    expect(result?.directoryDisposition).toBe('deleted');
    expect(result?.directory).toBe(directory);
    expect(fs.existsSync(directory)).toBe(false);
    expect(entries()).not.toContain(path.basename(directory));
  });

  it('删除外部绑定目录时只删记录，用户目录原样保留', async () => {
    const external = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-external-'));
    fs.writeFileSync(path.join(external, '用户文件.txt'), '内容');
    try {
      const created = await context.services.workspaces.create({
        name: '外部目录用例',
        directory: external,
        defaultModelId: null,
        defaultAgentId: null,
      });

      const result = await context.services.workspaces.deleteById(created.id);

      // 外部路径是用户自己准备的，框架没有资格做 `rm -rf`。
      expect(result?.directoryDisposition).toBe('external');
      expect(fs.existsSync(path.join(external, '用户文件.txt'))).toBe(true);
    } finally {
      fs.rmSync(external, { recursive: true, force: true });
    }
  });

  it('框架保留的 _public 即使被绑定也不会被删', async () => {
    const publicWorkspace = context.services.paths.publicWorkspace;
    const created = await context.services.workspaces.create({
      name: '公共目录用例',
      directory: publicWorkspace,
      defaultModelId: null,
      defaultAgentId: null,
    });

    const result = await context.services.workspaces.deleteById(created.id);

    expect(result?.directoryDisposition).toBe('external');
    expect(fs.existsSync(publicWorkspace)).toBe(true);
  });

  it('目录被替换成符号链接时只删链接，不跟随到外部目标', async () => {
    const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-outside-'));
    fs.writeFileSync(path.join(outside, '保留.txt'), '内容');
    const link = path.join(root(), '链接目录');
    try {
      fs.symlinkSync(outside, link);
      const created = await context.services.workspaces.create({
        name: '链接目录用例',
        directory: link,
        defaultModelId: null,
        defaultAgentId: null,
      });

      const result = await context.services.workspaces.deleteById(created.id);

      expect(result?.directoryDisposition).toBe('deleted');
      expect(fs.existsSync(link)).toBe(false);
      // 链接目标在根外，必须原样保留。
      expect(fs.existsSync(path.join(outside, '保留.txt'))).toBe(true);
    } finally {
      fs.rmSync(outside, { recursive: true, force: true });
    }
  });

  it('根目录被整体删掉后，下一次创建会把它建回来（幂等兜底）', async () => {
    // 覆盖两种情况：测试里关掉了 preparePaths、以及用户手工删了根目录。
    fs.rmSync(root(), { recursive: true, force: true });

    const created = await create('根被删了');
    expect(fs.existsSync(String(created.directory))).toBe(true);
  });
});

describe('根目录是个符号链接时，存下来的是链接指向的真实路径', () => {
  /*
   * 场景不罕见：`COSIGHT_WORKSPACES_ROOT` 指到 `/data/workspaces`，而 `/data` 是
   * 挂载盘或另一块盘的链接；或者用户自己把 home 放在链接后面的目录上。
   *
   * 存链接路径的后果不是"报错"，是**两个字符串指向同一个目录而 `!==`**：
   * 上层拿 `directory` 做集合判重、做缓存键、做"是不是同一个工作区"的比较时，
   * 会得出错误的结论。所以这里必须收敛成 realpath。
   */
  let home: string;
  let realRoot: string;
  let services: Services;

  beforeAll(async () => {
    home = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-link-'));
    realRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'cosight-realroot-'));
    const linkRoot = path.join(home, 'link-to-root');
    fs.symlinkSync(realRoot, linkRoot);

    services = await createServices({
      config: loadConfig({
        COSIGHT_HOME: home,
        COSIGHT_DATABASE_URL: `file:${path.join(home, 'test.sqlite')}`,
        COSIGHT_HOST_ORIGIN: 'http://127.0.0.1:4310',
        COSIGHT_WORKSPACES_ROOT: linkRoot,
        NODE_ENV: 'test',
      }),
    });
    // 建一次 app，让迁移与 `ensureDataPaths` 都跑过——与真实启动路径一致。
    const app = await buildApp({ services, logger: false });
    await app.ready();
    await app.close();
  });

  afterAll(async () => {
    await closeServices(services);
    fs.rmSync(home, { recursive: true, force: true });
    fs.rmSync(realRoot, { recursive: true, force: true });
  });

  it('directory 落在链接指向的真实目录下，不是链接路径下', async () => {
    const created = await services.workspaces.create({
      name: '链接用例',
      directory: null,
      defaultModelId: null,
      defaultAgentId: null,
    });
    const directory = String(created.directory);

    expect(directory).toBe(path.join(fs.realpathSync(realRoot), '链接用例'));
    expect(fs.statSync(directory).isDirectory()).toBe(true);
  });
});
