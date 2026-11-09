/**
 * 模块面文档与真实路由的一致性回归。
 *
 * 模块面（`/api/framework/v1/*`）是**唯一**能把明文密钥交给本机其他进程的口子，
 * 而它的读者是**别的团队的模块作者**——他们不会去读 `src/routes/`，只会照文档写代码。
 * 于是文档里一个过期的路径、一个写错的令牌文件名，代价是对方拿到 401/404 之后
 * 从头猜"是我们文档写错了还是我代码写错了"。
 *
 * 这类错误**没有任何运行期信号**：文档不是代码，没有类型、没有编译、没有 lint 会碰它。
 * 所以只能在这里钉住四件事：
 *
 * 1. **路径集合**：给模块作者看的 `module-facing-api.md` 里的路径，与 `/api/docs/json`
 *    里登记的模块面路径**双向相等**（少一条是"功能没写"，多一条是"文档在讲一个不存在的接口"）；
 * 2. **方法集合**：一张手写的"路径 → 方法"期望表，与 spec 完全相等。
 *    只比路径的话，把某个 `/:id` 从 `GET` 改成 `PATCH`（路径不变）不会红；
 * 3. **文档里的每个 `(方法, 路径)` 都真的存在**（方向反过来：防文档讲出一套不存在的接口）；
 * 4. 令牌文件路径、两条取令牌的硬要求、`protocol` 字段这些**照抄级**的细节写全了。
 *
 * 文件名仍叫 `module-model-api-doc`：它守护的是整个模块面，改名只是噪音。
 */

import fs from 'node:fs';
import path from 'node:path';

import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { createTestContext, destroyTestContext, type TestContext } from './helpers/context';

let context: TestContext;

beforeAll(async () => {
  context = await createTestContext();
});

afterAll(async () => {
  await destroyTestContext(context);
});

/** 用 `import.meta.dirname` 而不是 `process.cwd()`：与测试运行时的目录无关。 */
const docsDir = path.resolve(import.meta.dirname, '..', '..', 'docs');

/** 给"任何模块作者"看的模块面接口总览。**它是唯一要求"写全"的一份**。 */
const FACE_DOC = 'module-facing-api.md';

/** 与 smart-factory 的对接说明，第 8 节讲的是同一套模型接口。 */
const INTEGRATION_DOC = 'module-integration-smart-factory.md';

/**
 * 直接转发给消费方同事的自足接口说明。
 *
 * 它和上面两份**内容有重叠是刻意的**：上面两份是给框架维护者读的（含内部取舍、残余风险、
 * 代码位置），这份是给另一个团队照着写客户端的。受众不同，所以分文件；代价是同一份契约
 * 有三处抄写，因此它必须和另外两份一样进下面的断言——重叠靠测试钉住，不靠人记得改。
 */
const HANDOVER_DOC = 'model-config-api.md';

/**
 * 工作区接口的自足说明，与 `HANDOVER_DOC` 同构（基址 / 鉴权 / 端点 / 错误 / 接入写法）。
 *
 * 它是**第二份**面向消费方的可转发文档：另一边团队照着它调工作区接口。两份的读者相同，
 * 于是两份受**同一套**约束——路径不许凭空出现，写了方法的每一处都要真有那条接口。
 */
const WORKSPACE_HANDOVER_DOC = 'workspace-api.md';

/** 工作区方案。它讲的是磁盘那一半，但会顺带引用几条模块面路径。 */
const WORKSPACE_DOC = 'workspace-design.md';

/** 知识库路由的可转发说明：模块面两条只读端点 + 设置面附录（附录路径不在模块面前缀内）。 */
const RAG_KNOWLEDGE_HANDOVER_DOC = 'rag-knowledge-api.md';

/**
 * 讲这套模块面接口的文档。加新文档时只需改这一处，下面的断言自动跟着覆盖。
 *
 * 注意两类断言的适用范围不同（见下面各用例的注释）：
 * **路径写全**只要求 `FACE_DOC`；其余每一份都只要求"不许出现不存在的路径"。
 * 这正好对应它们的受众——只有 FACE_DOC 自称是"总览"。
 */
const DOCS_ON_MODULE_FACE = [
  FACE_DOC,
  INTEGRATION_DOC,
  HANDOVER_DOC,
  WORKSPACE_HANDOVER_DOC,
  WORKSPACE_DOC,
  RAG_KNOWLEDGE_HANDOVER_DOC,
];

/**
 * 自称"接口清单"的几份：它们**必须**真的列出带方法的接口。
 *
 * `workspace-design.md` 不在其中——它是设计文档，讲的是磁盘行为与命名规则，
 * 接口只在正文里顺带提及。要求它也列一张方法表，只会让它变成 `FACE_DOC` 的副本。
 * 它仍然受"不许引用不存在的路径/接口"那条约束（安全方向），只是不受"必须写全"这条。
 */
const DOCS_WITH_ENUMERATED_OPERATIONS = [
  FACE_DOC,
  HANDOVER_DOC,
  WORKSPACE_HANDOVER_DOC,
  INTEGRATION_DOC,
  RAG_KNOWLEDGE_HANDOVER_DOC,
];

/**
 * 模块面的**完整形状**：路径 → 该路径上注册的 HTTP 方法。
 *
 * 这是**手写的期望值**，不是从 spec 里读出来的——从 spec 读出来再跟它自己比，等于什么都没测。
 * 改模块面时先改这张表，再改代码；表红了说明改动没有被意识到，而不是测试太严。
 */
const MODULE_FACE_OPERATIONS: Record<string, readonly string[]> = {
  '/api/framework/v1/models': ['get', 'post'],
  '/api/framework/v1/models/active': ['get'],
  '/api/framework/v1/models/{id}': ['delete', 'get', 'patch'],
  // RAG 知识库在模块面**只读**：只有列表与生效项两个 GET，没有写接口。
  '/api/framework/v1/rag-knowledge': ['get'],
  '/api/framework/v1/rag-knowledge/active': ['get'],
  '/api/framework/v1/workspaces': ['get', 'post'],
  '/api/framework/v1/workspaces/active': ['get'],
  '/api/framework/v1/workspaces/{id}': ['delete', 'get', 'patch'],
  '/api/framework/v1/workspaces/{id}/activate': ['post'],
};

const MODULE_FACE_PREFIX = '/api/framework/v1';

function readDoc(fileName: string): string {
  const file = path.join(docsDir, fileName);
  if (!fs.existsSync(file)) {
    // 显式抛而不是让 readFileSync 的 ENOENT 冒出去：这条失败最常见的原因是
    // 文档被改名或挪走，把"找不到哪份文件"直接写进消息里省一轮排查。
    throw new Error(`模块面文档不存在：${file}`);
  }
  return fs.readFileSync(file, 'utf8');
}

/**
 * 从 markdown 正文里抽出模块面路径。
 *
 * 刻意**只抽模块面前缀**，不抽所有 `/api/...`：文档里顺带提到的 `/api/docs`、`/api/health`、
 * 桥接的 `/api/bridge/*` 各自有别的归属（`/api/docs` 根本不在 swagger 的 `paths` 里），
 * 一并断言只会让这条用例变成"谁改了无关段落就会红"的脆弱测试。
 *
 * 用**白名单**（路径里可能出现的字符）而不是黑名单，是有原因的：黑名单写起来要
 * 把 markdown 的全部标点、引号、全角标点都列进去，漏一个就会把标点吃进路径里，
 * 于是断言红在一个与被测行为无关的原因上。白名单只描述"路径长什么样"。
 * 副作用正好是想要的——`/api/framework/v1/models/*` 里那个 `*` 不是路径字符，
 * 匹配在 `/` 处停下，归一化后等于集合路由 `/api/framework/v1/models`。
 */
const MODULE_FACE_PATH = /\/api\/framework\/v1\/[\w.:{}/-]*/g;

/**
 * 文档里"带方法"的写法。**刻意写紧**：只认两种真实出现过的形态——
 * `` `GET /path` ``（正文与标题）与 `` `GET` | `/path` ``（表格）。
 *
 * 不写成"方法后面 8 个字符内有路径就算"那种松窗口：`module-integration-smart-factory.md`
 * 里有一句"模块面现在还开了模型的 `POST`/`PATCH`/`DELETE` 与一整套工作区接口
 * （`/api/framework/v1/workspaces/*`）"，松窗口会把 `DELETE` 和那个路径配成一对，
 * 于是断言红在一个**文档没写错**的地方。
 */
const DOCUMENTED_OPERATION = /(GET|POST|PUT|PATCH|DELETE)(?:`\s*\|\s*|\s)`?(\/api\/framework\/v1\/[\w.:{}/-]*)/g;

/** 把文档里的三种占位写法统一成 swagger 的 `{id}`，并去掉尾斜杠。 */
function normalize(pathname: string): string {
  return pathname.replace(/:([a-zA-Z]+)/g, '{$1}').replace(/\/+$/, '');
}

function pathsInDoc(text: string): string[] {
  // 先归一化再去重：`/api/framework/v1/models` 与 `/api/framework/v1/models/` 是同一路径的
  // 两种写法（后者来自 `.../models/*` 那一族的说法），去重必须在归一化之后做。
  return [
    ...new Set(
      (text.match(MODULE_FACE_PATH) ?? [])
        .map(normalize)
        // `/api/framework/v1` 本身是**挂载点**（`MODULE_FACE_BASE_PATH`），
        // 不是一条端点——文档里说"模块面 `/api/framework/v1/*`"是对的，
        // 而 swagger 的 `paths` 里只有具体路径。不过滤的话这条断言永远红在它上面。
        .filter((pathname) => pathname !== MODULE_FACE_PREFIX),
    ),
  ].toSorted();
}

/** 文档里明确写了方法的 `(方法, 路径)` 对，归一化后去重。 */
function operationsInDoc(text: string): string[] {
  return [
    ...new Set(
      [...text.matchAll(DOCUMENTED_OPERATION)].map((match) => {
        /*
         * 正则里恰好两个捕获组，命中时必然有值——但 `noUncheckedIndexedAccess`
         * 只能看到 `string | undefined`。用 `?? ''` 收窄类型而不是 `!`：
         * 万一正则被改成可选组，拼出来的会是一个明显不成立的串（`" "`），
         * 在下面那条 `known.has(operation)` 断言上立刻红掉，而不是静默通过。
         */
        const [, method, pathname] = match;
        return `${(method ?? '').toUpperCase()} ${normalize(pathname ?? '')}`;
      }),
    ),
  ].toSorted();
}

interface SpecFace {
  /** 路径（归一化后） → 该路径上注册的方法（小写、已排序）。 */
  byPath: Record<string, string[]>;
}

/** `/api/docs/json` 里登记的模块面路径与方法。 */
async function specFace(): Promise<SpecFace> {
  const response = await context.app.inject({ method: 'GET', url: '/api/docs/json' });
  expect(response.statusCode).toBe(200);

  const entries = Object.entries(response.json().paths as Record<string, Record<string, unknown>>)
    .filter(([pathname]) => pathname.startsWith(MODULE_FACE_PREFIX))
    .map(([pathname, operations]) => [normalize(pathname), Object.keys(operations).toSorted()]);

  return { byPath: Object.fromEntries(entries) };
}

describe('模块面文档与真实路由一致', () => {
  it('模块面总览里的路径与 OpenAPI 里登记的双向一致', async () => {
    /*
     * **双向**相等断言，而不是"文档里的都在 spec 里"：单向只能发现"文档多写了"，
     * 发现不了"新加了端点却没写文档"——而后者才是真正会让模块作者漏掉功能的那个方向。
     *
     * 只对 FACE_DOC 要求"写全"：另外两份的受众更窄（一份只讲模型、一份只讲工作区），
     * 要求它们列出全部七条路径，只会让它们变成 FACE_DOC 的副本。
     */
    const { byPath } = await specFace();
    const specPaths = Object.keys(byPath).toSorted();
    expect(specPaths.length).toBeGreaterThan(0);

    expect(pathsInDoc(readDoc(FACE_DOC)), `${FACE_DOC} 与 /api/docs/json 的模块面路径不一致`).toEqual(
      specPaths,
    );
  });

  it('其余各份文档引用的模块面路径都真实存在', () => {
    // 反向：文档不能引用一个不存在的接口。受众窄的文档只受这一条约束。
    const specPaths = new Set(Object.keys(MODULE_FACE_OPERATIONS));

    for (const fileName of DOCS_ON_MODULE_FACE) {
      for (const pathname of pathsInDoc(readDoc(fileName))) {
        expect(specPaths.has(pathname), `${fileName} 引用了不存在的模块面路径 ${pathname}`).toBe(true);
      }
    }
  });

  it('模块面每个路径上的方法集合与手写期望表完全相等', async () => {
    /*
     * 只比路径的话，把 `/:id` 的 `GET` 换成 `PATCH`（路径不变）不会红。
     * 所以这里比的是完整的 "路径 → 方法集合"。
     */
    const { byPath } = await specFace();

    expect(byPath, '模块面的路径与方法集合变了；先确认是有意改动，再同步这张表').toEqual(
      Object.fromEntries(
        Object.entries(MODULE_FACE_OPERATIONS).map(([pathname, methods]) => [
          pathname,
          [...methods].toSorted(),
        ]),
      ),
    );
  });

  it('文档里写了方法的每一处，都对应一条真实存在的接口', () => {
    /*
     * 这是老那条"模块面不许出现写接口"断言的反面。
     *
     * 那条断言的动机是对的——防的是"有人照着'对外提供模型设置'这句话在文档里补一段
     * `POST /api/framework/v1/models`，但服务端从来没有这条路由"。D33 之后写接口有了，
     * 于是"禁写"这个判据本身失效；但**同一个动机**还在，把方向倒过来就仍然成立：
     * 文档里每一个 `(方法, 路径)` 都必须能在期望表里找到。
     *
     * 它同时兜住了"文档写了 `DELETE /api/framework/v1/workspaces`（集合路径）"这种
     * 看着合理、实际没有的接口——只比路径集合是发现不了的。
     */
    const known = new Set(
      Object.entries(MODULE_FACE_OPERATIONS).flatMap(([pathname, methods]) =>
        methods.map((method) => `${method.toUpperCase()} ${pathname}`),
      ),
    );

    for (const fileName of DOCS_WITH_ENUMERATED_OPERATIONS) {
      // 至少抽到一条，否则下面那个循环会在"提取正则被写坏"时空转通过。
      const documented = operationsInDoc(readDoc(fileName));
      expect(documented.length, `${fileName} 里一条带方法的接口都没抽到，提取正则可能坏了`)
        .toBeGreaterThan(0);
    }

    for (const fileName of DOCS_ON_MODULE_FACE) {
      for (const operation of operationsInDoc(readDoc(fileName))) {
        expect(known.has(operation), `${fileName} 写了不存在的接口：${operation}`).toBe(true);
      }
    }
  });

  it('模块面总览写全了令牌文件路径，两种写法都在', () => {
    /*
     * 这是模块作者唯一必须逐字照抄的东西。写"在某个配置里"或只给相对路径，
     * 结果是对方把令牌塞进 `.env`——而 `claude-adapter.ts` 那类适配器会把
     * `process.env` 整体透传给模型子进程，等于把令牌交给 LLM 工具链。
     * 所以两种写法（环境变量形态与家目录形态）都必须出现。
     */
    const text = readDoc(FACE_DOC);
    expect(text).toContain('$COSIGHT_HOME/.module-token');
    expect(text).toContain('~/.cosight-harness/.module-token');
  });

  it('模块面总览讲清了取令牌的两条硬要求', () => {
    const text = readDoc(FACE_DOC);
    // 认哪种头：写错就永远 401，且 401 的四种原因返回同一句话，从响应里看不出是哪一步错。
    expect(text).toContain('Authorization: Bearer');
    // 令牌不是访问控制边界——不写清这一条，读者会把它当成权限系统，从而给出错误的安全感，
    // 也会有人据此决定"那我把模块面暴露到 0.0.0.0 上"。
    expect(text).toContain('不是访问控制边界');
  });

  it('模块面总览给出了 protocol 字段（防"拿错协议"那类静默失败）', () => {
    /*
     * 框架的 `provider` 是"供应商"，`protocol` 才是"线协议"。消费方若自己从 provider
     * 推断协议，用户把 OpenAI 兼容模型设为激活时会静默拿 Anthropic SDK 去打它，
     * 表现为一句语焉不详的上游报错。这个字段的存在必须写在文档里，否则没人会用它。
     */
    expect(readDoc(FACE_DOC)).toContain('protocol');
  });

  it('写接口的权限面写进了文档（只读消费方要被明确劝住）', () => {
    /*
     * D33 之后令牌的爆炸半径变大了。文档必须**明确说出这件事**，而不是把写接口
     * 混在接口清单里让读者自己判断——`smart-factory` 那种只读消费方看到一份
     * 不带警告的清单，很容易"顺手也调一下 POST"。
     */
    const text = readDoc(FACE_DOC);
    // 对只读消费方的那句劝告必须逐字在。（措辞可以改，但改了就要同步这条断言——那正是它存在的意义。）
    expect(text).toContain('不该要写权限的模块就别要');
    // 写操作会被记一条 warn 日志：这是出事之后唯一能回答"哪台机器、什么时候"的东西。
    expect(text).toContain('审计日志');
  });

  it('对接说明里那三个变量名与 smart-factory 的现状对得上', () => {
    /*
     * 第 8.2 节要给对方的是"把 `process.env.MODEL_*` 换成从模块面取"。变量名写错一个字母，
     * 对方看到的就是"这段文档跟我代码里的东西对不上"，然后整节的可信度就没了。
     * 这三个名字来自 `smart-factory/server/src/config/index.ts`（我们只读取、不修改），
     * 它们一旦在那边改名，这条断言会红——那是**正确的**提醒：该同步文档了。
     */
    const text = readDoc(INTEGRATION_DOC);
    expect(text).toContain('MODEL_NAME');
    expect(text).toContain('MODEL_BASE_URL');
    expect(text).toContain('MODEL_API_KEY');
    // "自己读文件、不要注入环境变量"这条要求的理由是他们的适配器透传 process.env，
    // 点出文件名才让人能自己去核实，而不是当成一句风格建议。
    expect(text).toContain('claude-adapter.ts');
  });

  it('对接说明明确写了不代他们改代码', () => {
    // 模块边界（同事模块只做宿主侧）。写进文档是为了让"我们没动 smart-factory"这件事
    // 有据可查——否则下一个人看到第 8.2 节会以为那是待办，直接去改别人的仓。
    expect(readDoc(INTEGRATION_DOC)).toContain('不改 `smart-factory/`');
  });
});
