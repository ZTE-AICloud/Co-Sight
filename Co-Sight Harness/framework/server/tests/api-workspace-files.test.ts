/**
 * 工作区文件浏览（只读）：列目录、读文本、读图片。
 *
 * 这个文件里的用例**大部分是安全用例**，这不是过度紧张：这是框架里第一组
 * 会把用户目录里**文件内容**吐出去的接口，而它的输入是一个用户可控的字符串。
 * 所以每一条"能逃出工作区"的走法都各有一条用例，而不是合并成一条
 * "非法路径被拒"——真出了洞，能一次说清是哪一种走法漏了，比"确实漏了"有用得多。
 *
 * 另一半是用例是**上限**：条目数、文本字节、图片字节、二进制判定。上限最容易
 * 写成一个"看起来能拦住"的近似实现（比如用 `readFileSync` 读完再切），
 * 所以断言里比的是**字节数**与 `truncated` 标志，不是"有没有报错"。
 */

import fs from 'node:fs';
import path from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { WORKSPACE_FILE_LIMITS } from 'harness-shared';
import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

let context: TestContext;
/** 工作区绑定的目录（每套用例共用一棵只读的树；少数用例会改自己那部分）。 */
let tree: string;
/** 工作区**外面**的目录，用来验证"软链指出去"这一类逃逸。 */
let outside: string;
let workspaceId: string;

const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

/** 一个中文（3 字节）文件，长度**故意**不是 3 的倍数关系，好让截断点落在字符中间。 */
const MULTIBYTE_TEXT = '中'.repeat(200_000);

beforeAll(async () => {
  context = await createTestContext();

  tree = path.join(context.home, 'tree');
  outside = path.join(context.home, 'outside');
  fs.mkdirSync(path.join(tree, 'src'), { recursive: true });
  fs.mkdirSync(path.join(tree, 'many'), { recursive: true });
  fs.mkdirSync(outside, { recursive: true });
  fs.writeFileSync(path.join(outside, 'secret.txt'), '工作区外面的东西\n');

  fs.writeFileSync(path.join(tree, 'src', 'main.ts'), 'export const answer = 42;\n');
  fs.writeFileSync(path.join(tree, 'readme.md'), '# 标题\n');
  fs.writeFileSync(path.join(tree, 'empty.txt'), '');
  // 512 KiB 以上：截断那条用它
  fs.writeFileSync(path.join(tree, 'big.txt'), 'a'.repeat(WORKSPACE_FILE_LIMITS.maxTextBytes + 1024));
  fs.writeFileSync(path.join(tree, 'multibyte.txt'), MULTIBYTE_TEXT);
  // 有 NUL：二进制判定第一条
  fs.writeFileSync(path.join(tree, 'bin.dat'), Buffer.from([0x61, 0x00, 0x62]));
  // 没有 NUL、但不是合法 UTF-8：二进制判定第二条（两条都在才行，少一条会漏）
  fs.writeFileSync(path.join(tree, 'bad-utf8.txt'), Buffer.from([0xff, 0xfe, 0x61]));
  fs.writeFileSync(path.join(tree, 'pic.png'), Buffer.from([...PNG_MAGIC, 0x00, 0x01, 0x02]));
  fs.writeFileSync(path.join(tree, 'big.png'), Buffer.concat([
    Buffer.from(PNG_MAGIC),
    Buffer.alloc(WORKSPACE_FILE_LIMITS.maxImageBytes + 1),
  ]));
  fs.writeFileSync(path.join(tree, 'vector.svg'), '<svg xmlns="http://www.w3.org/2000/svg"></svg>');

  for (let index = 1; index <= WORKSPACE_FILE_LIMITS.maxEntries + 1; index += 1) {
    fs.writeFileSync(path.join(tree, 'many', `f${String(index).padStart(5, '0')}.txt`), '');
  }

  // 指向工作区**外面**的软链：这一条是 realpath 那一关存在的全部理由
  fs.symlinkSync(outside, path.join(tree, 'link-out'));
  // 指向工作区**里面**的软链：同样拒（"不跟随软链"是一条规则，没有例外）
  fs.symlinkSync(path.join(tree, 'src', 'main.ts'), path.join(tree, 'link-in'));

  const created = await context.app.inject({
    method: 'POST',
    url: '/api/workspaces',
    payload: { name: '浏览用工作区', directory: tree },
  });
  expect(created.statusCode).toBe(201);
  workspaceId = created.json().data.id as string;
});

afterAll(async () => {
  await destroyTestContext(context);
});

interface FileRequest {
  workspace?: string;
  /** `files` / `files/content` / `files/image`。 */
  endpoint?: string;
  /** 工作区相对路径（就是查询串里的 `path`）；不给 = 根。 */
  path?: string;
  headers?: Record<string, string>;
}

function getFiles({ workspace = workspaceId, endpoint = 'files', path: relative, headers }: FileRequest) {
  return context.app.inject({
    method: 'GET',
    url: `/api/workspaces/${workspace}/${endpoint}`,
    ...(relative === undefined ? {} : { query: { path: relative } }),
    ...(headers === undefined ? {} : { headers }),
  });
}

async function createWorkspace(name: string, directory: string | null): Promise<string> {
  const response = await context.app.inject({
    method: 'POST',
    url: '/api/workspaces',
    payload: { name, directory },
  });
  expect(response.statusCode).toBe(201);
  return response.json().data.id as string;
}

describe('列目录', () => {
  it('根目录解析出真实路径，并给出可直接使用的条目', async () => {
    const response = await getFiles({});
    expect(response.statusCode).toBe(200);

    const data = response.json().data as {
      root: string;
      path: string;
      entries: { name: string; type: string; size?: number }[];
      truncated: boolean;
    };
    // `root` 必须是**服务端解析出来的真实路径**：用户填的树里可能带软链，
    // 客户端拿它去拼别的路径就会拼到另一个地方。
    expect(data.root).toBe(fs.realpathSync(tree));
    expect(data.path).toBe('');
    expect(data.truncated).toBe(false);

    const byName = new Map(data.entries.map((entry) => [entry.name, entry]));
    expect(byName.get('src')?.type).toBe('directory');
    expect(byName.get('readme.md')).toMatchObject({ type: 'file', size: 9 });
    expect(byName.get('empty.txt')).toMatchObject({ type: 'file', size: 0 });
    // 软链是 `other`：界面据此不给"点开看看"这个承诺
    expect(byName.get('link-out')?.type).toBe('other');
    expect(byName.get('link-in')?.type).toBe('other');
  });

  it('子目录按相对路径展开', async () => {
    const response = await getFiles({ path: 'src' });
    expect(response.statusCode).toBe(200);
    expect(response.json().data.path).toBe('src');
    expect(response.json().data.entries.map((entry: { name: string }) => entry.name)).toEqual(['main.ts']);
  });

  it('省略 path 与给空串等价', async () => {
    const omitted = await getFiles({});
    const empty = await getFiles({ path: '' });
    expect(empty.json().data).toEqual(omitted.json().data);
  });

  it('`./src` 与 `src` 等价（`.` 段只是噪声，丢掉不改变指向）', async () => {
    const response = await getFiles({ path: './src' });
    expect(response.statusCode).toBe(200);
    expect(response.json().data.path).toBe('src');
  });

  it('对文件调列目录 → 400', async () => {
    const response = await getFiles({ path: 'readme.md' });
    expect(response.statusCode).toBe(400);
    expect(response.json().error.code).toBe('BAD_REQUEST');
  });

  it('条目数超过上限时截断，并且是稳定序', async () => {
    const response = await getFiles({ path: 'many' });
    const data = response.json().data as { entries: { name: string }[]; truncated: boolean };

    expect(data.truncated).toBe(true);
    expect(data.entries).toHaveLength(WORKSPACE_FILE_LIMITS.maxEntries);
    // 截断必须是可复现的：按名字排序后取前 N 个，不看文件系统的返回顺序。
    expect(data.entries[0]?.name).toBe('f00001.txt');
    expect(data.entries.at(-1)?.name).toBe('f02000.txt');
  });
});

describe('路径逃逸：每一类走法各一条用例', () => {
  it('`..` 段被拒（403）', async () => {
    for (const probe of ['..', '../..', 'src/../..', '../../etc/passwd']) {
      const response = await getFiles({ path: probe });
      expect(response.statusCode, probe).toBe(403);
      expect(response.json().error.code, probe).toBe('FORBIDDEN');
    }
  });

  it('绝对路径被拒（403）', async () => {
    for (const probe of ['/etc/passwd', '/', '/tmp']) {
      const response = await getFiles({ path: probe });
      expect(response.statusCode, probe).toBe(403);
    }
  });

  it('反斜杠与盘符被拒（403）——`path.join` 在 Windows 上会把它当分隔符', async () => {
    for (const probe of ['src\\main.ts', 'a\\..\\..\\x', 'C:', 'C:\\Windows']) {
      const response = await getFiles({ path: probe });
      expect(response.statusCode, probe).toBe(403);
    }
  });

  it('NUL 字节被拒（403）', async () => {
    const response = await getFiles({ path: 'readme.md\u0000.txt' });
    expect(response.statusCode).toBe(403);
  });

  it('中间一段是软链、指向工作区外面 → 403（字符串前缀比对发现不了这种）', async () => {
    const response = await getFiles({ path: 'link-out/secret.txt' });
    expect(response.statusCode).toBe(403);
    expect(response.json().error.code).toBe('FORBIDDEN');

    // 消息里只回显用户自己给的那段相对路径，不回显解析出来的真实路径
    const message = response.json().error.message as string;
    expect(message).toContain('link-out/secret.txt');
    expect(message).not.toContain(outside);
  });

  it('末段是软链一律拒，哪怕它指向工作区里面', async () => {
    // 这一条是"简单规则胜过聪明规则"：不跟随软链，没有例外，
    // 于是"读的是哪个文件"不需要任何推理。
    const escaping = await getFiles({ path: 'link-out' });
    expect(escaping.statusCode).toBe(403);

    const pointingIn = await getFiles({ path: 'link-in', endpoint: 'files/content' });
    expect(pointingIn.statusCode).toBe(403);
  });

  it('不存在的路径 → 404（不是 403，也不是空列表）', async () => {
    const response = await getFiles({ path: 'nope.txt' });
    expect(response.statusCode).toBe(404);
    expect(response.json().error.code).toBe('NOT_FOUND');
  });
});

describe('读文本', () => {
  it('读出内容与完整字节数', async () => {
    const response = await getFiles({ path: 'readme.md', endpoint: 'files/content' });
    expect(response.statusCode).toBe(200);

    const data = response.json().data as { text: string; size: number; truncated: boolean };
    expect(data.text).toBe('# 标题\n');
    expect(data.size).toBe(Buffer.byteLength('# 标题\n'));
    expect(data.truncated).toBe(false);
  });

  it('空文件读成空串，不是错误', async () => {
    const response = await getFiles({ path: 'empty.txt', endpoint: 'files/content' });
    expect(response.statusCode).toBe(200);
    expect(response.json().data.text).toBe('');
  });

  it('超过上限的文件只读前 512 KiB，`size` 报完整长度', async () => {
    const response = await getFiles({ path: 'big.txt', endpoint: 'files/content' });
    const data = response.json().data as { text: string; size: number; truncated: boolean };

    expect(data.truncated).toBe(true);
    expect(Buffer.byteLength(data.text)).toBe(WORKSPACE_FILE_LIMITS.maxTextBytes);
    // `size` 是文件的真实大小，不是返回的文本长度——否则界面上的"仅显示前 N"
    // 会把"文件有多大"这件事说错。
    expect(data.size).toBe(WORKSPACE_FILE_LIMITS.maxTextBytes + 1024);
  });

  it('截断点落在多字节字符中间时不误报"不是文本"', async () => {
    /*
     * 这条守的是一个**很容易写出来的 bug**：截断是按字节切的，切点可能正好在
     * 一个中文字符的中间，此时用致命解码判"是不是文本"会失败，于是一个正常的
     * 中文文件被报成 415。用非致命解码又能通过，但那样二进制内容会带着一堆
     * 替换字符显示出来。两种都不行，所以实现里是"丢掉尾部 1–3 字节再试"。
     */
    const response = await getFiles({ path: 'multibyte.txt', endpoint: 'files/content' });
    expect(response.statusCode).toBe(200);

    const data = response.json().data as { text: string; size: number; truncated: boolean };
    expect(data.truncated).toBe(true);
    expect(data.text).not.toContain('\uFFFD');
    // 确实是原文件的前缀，且真的被切短了（没有把整个文件读回来）
    expect(MULTIBYTE_TEXT.startsWith(data.text)).toBe(true);
    expect(Buffer.byteLength(data.text)).toBeLessThan(WORKSPACE_FILE_LIMITS.maxTextBytes);
    // 切点确实落在字符中间，否则这条用例测不到它想测的东西
    expect(WORKSPACE_FILE_LIMITS.maxTextBytes % 3).not.toBe(0);
  });

  it('含 NUL 的文件 → 415', async () => {
    const response = await getFiles({ path: 'bin.dat', endpoint: 'files/content' });
    expect(response.statusCode).toBe(415);
    expect(response.json().error.code).toBe('UNSUPPORTED_MEDIA_TYPE');
  });

  it('不是合法 UTF-8 又含 NUL → 415（两条判据都要有）', async () => {
    const response = await getFiles({ path: 'bad-utf8.txt', endpoint: 'files/content' });
    expect(response.statusCode).toBe(415);
  });

  it('对目录读内容 → 400', async () => {
    const response = await getFiles({ path: 'src', endpoint: 'files/content' });
    expect(response.statusCode).toBe(400);
  });

  it('文件改过之后重读拿到新内容（没有缓存）', async () => {
    const file = path.join(tree, 'fresh.txt');
    fs.writeFileSync(file, '第一版');

    const first = await getFiles({ path: 'fresh.txt', endpoint: 'files/content' });
    expect(first.json().data.text).toBe('第一版');

    fs.writeFileSync(file, '第二版');
    const second = await getFiles({ path: 'fresh.txt', endpoint: 'files/content' });
    expect(second.json().data.text).toBe('第二版');
  });
});

describe('读图片', () => {
  it('按内容认格式并内联成 data URL', async () => {
    const response = await getFiles({ path: 'pic.png', endpoint: 'files/image' });
    expect(response.statusCode).toBe(200);

    const data = response.json().data as { contentType: string; dataUrl: string; size: number };
    expect(data.contentType).toBe('image/png');
    expect(data.dataUrl.startsWith('data:image/png;base64,')).toBe(true);
    expect(data.size).toBe(PNG_MAGIC.length + 3);
  });

  it('SVG 也认（<img> 里的 SVG 不执行脚本，这是规范行为）', async () => {
    const response = await getFiles({ path: 'vector.svg', endpoint: 'files/image' });
    expect(response.json().data.contentType).toBe('image/svg+xml');
  });

  it('按内容而不是扩展名：文本文件改名叫 .png 也读不出来', async () => {
    const response = await getFiles({ path: 'readme.md', endpoint: 'files/image' });
    expect(response.statusCode).toBe(415);
  });

  it('超过 2 MiB → 413（在解码之前拦，不是读完再判）', async () => {
    const response = await getFiles({ path: 'big.png', endpoint: 'files/image' });
    expect(response.statusCode).toBe(413);
    expect(response.json().error.code).toBe('PAYLOAD_TOO_LARGE');
  });
});

describe('工作区状态', () => {
  it('没绑目录的工作区：列目录是 200 + root null，读文件是 404', async () => {
    const id = await createWorkspace('没目录的', null);
    await context.app.inject({ method: 'PATCH', url: `/api/workspaces/${id}`, payload: { directory: null } });

    /*
     * 没绑目录**不是错误**——它是新建工作区后的正常状态。
     * 与 `GET /workspaces/active` 没有生效项时返回 `data: null` 是同一条口径，
     * 所以这里也必须是 200，前端才不用把一个正常状态画成红色。
     */
    const listing = await getFiles({ workspace: id });
    expect(listing.statusCode).toBe(200);
    expect(listing.json().data).toEqual({ root: null, path: '', entries: [], truncated: false });

    const content = await getFiles({ workspace: id, path: 'a.txt', endpoint: 'files/content' });
    expect(content.statusCode).toBe(404);
    // 说的是"还没绑目录"，而不是"工作区里没有这个文件"——用户的待办完全不同
    expect(content.json().error.messageKey).toBe('error.not_found.workspace_directory');
  });

  it('绑定目录在磁盘上没了 → 404（不装作一个空目录）', async () => {
    const doomed = path.join(context.home, 'doomed');
    fs.mkdirSync(doomed);
    const id = await createWorkspace('目录会消失的', doomed);
    fs.rmdirSync(doomed);

    const response = await getFiles({ workspace: id });
    expect(response.statusCode).toBe(404);
    expect(response.json().error.messageKey).toBe('error.not_found.workspace_directory');
  });

  it('工作区不存在 → 404；id 不是 uuid → 422', async () => {
    const missing = await getFiles({ workspace: '3f1c9a54-0000-4000-8000-000000000000' });
    expect(missing.statusCode).toBe(404);
    expect(missing.json().error.code).toBe('NOT_FOUND');

    const malformed = await context.app.inject({ method: 'GET', url: '/api/workspaces/not-a-uuid/files' });
    expect(malformed.statusCode).toBe(422);
  });
});

describe('回环门禁', () => {
  /*
   * 浏览器面对 DNS rebinding 本来没有防线：恶意站点把自己控制的域名解析到
   * `127.0.0.1`，浏览器就当成同源，CORS 完全不介入。在此之前这条攻击面只够
   * 看工作区的**记录**；这一组接口一旦开口，它够读**文件内容**。
   * 所以这三个端点额外要求 `Host` 与来源地址都是回环。
   */
  it('Host 不是回环名 → 403（三个端点都拒绝）', async () => {
    for (const endpoint of ['files', 'files/content', 'files/image']) {
      const response = await getFiles({ endpoint, path: 'readme.md', headers: { host: 'evil.example' } });
      expect(response.statusCode, endpoint).toBe(403);
      expect(response.json().error.messageKey, endpoint).toBe('error.forbidden.loopback_only');
    }
  });

  it('Host 是回环名时正常放行（门禁没把正常路径也挡掉）', async () => {
    const response = await getFiles({ headers: { host: '127.0.0.1:4300' } });
    expect(response.statusCode).toBe(200);
  });

  it('其他浏览器面接口**没有**这道门禁（这一刀只切在文件浏览上）', async () => {
    const response = await context.app.inject({
      method: 'GET',
      url: '/api/workspaces',
      headers: { host: 'evil.example' },
    });
    expect(response.statusCode).toBe(200);
  });
});
