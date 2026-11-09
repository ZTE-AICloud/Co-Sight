# 知识库路由设置 · 实施方案

> 状态：**已实施（2026-10-27）**。本文保留为设计依据与实施顺序；
> 落地后的接口口径以 [`rag-knowledge-api.md`](rag-knowledge-api.md) 为准，
> 取舍见 [`framework-decisions.md`](framework-decisions.md) 的 D51。
>
> **与方案的两处偏差**（实施时收敛的）：
> 1. §3.1 的自写 `isJumpRoute` 没有采用——基础协议约束复用契约层已有的
>    `httpUrlSchema`（`primitives.ts`），只在其上补一条"不得内嵌账号密码"的 refine。
>    少一份手写解析，就少一处与 `module.ts` 的 `entryPath` 校验漂移的机会。
> 2. 示例里的 id 早期写成 `kb_3f2a`，实际主键是 **uuid**；本文示例已改正。
> 3. 侧栏「知识库」在方案里仍指向模块宿主 `/knowledge`。实施后按用户要求改成
>    **打开当前生效项的入口**；设置列表行上的「打开」按钮随之删除（同一个动作只留一个入口）。
>    2026-10-27 再修订：不再新开标签页，而是由 `/knowledge` 页把地址**嵌进主面板**；
>    未配置时点菜单直接打开本页签的新增表单（不再先弹提示）。见 D51 第 8、9 条。
>    2026-10-28 再修订（当前口径）：侧栏改回**新浏览器标签页**打开生效项的 `routeUrl`；
>    `/knowledge` 页保留给直接访问 / 旧书签，不再是从菜单进入的落点。见 D51 第 8、9 条。
>
> 需求原文：「配置中支持 用户配置 RAG知识库的 跳转路由，框架需要再模型设置的平级
> (通用设置，模型设置，Agent代理配置，观测设置)设置菜单。允许配置新增，对各个模块允许查询，
> 允许用户修改，删除，设置为可用；帮我输出可行的方案」

## 0. 一句话

在设置弹窗里加第五个页签 **「知识库路由设置」**：用户维护若干条「名称 + 跳转路由 + 说明」，
其中**至多一条处于「可用」（生效）状态**；框架前端走 `/api/rag-knowledge/*` 增删改查与切换，
各模块进程走模块面 `/api/framework/v1/rag-knowledge/*` **只读**查询当前生效的那条。

改动只落在框架（`shared/` + `server/` + `web/` + 文档），不动任何模块源码，也不改打包与安装链路。

---

## 1. 需求拆解

| 需求原话 | 落地成什么 |
| --- | --- |
| 「在模型设置的平级设置菜单」 | 设置弹窗的第五个页签（与通用/模型/Agent 代理/观测同一个 `tablist`），**不是**新路由、不是新页面 |
| 「配置 RAG 知识库的跳转路由」 | 每条记录的核心字段 `routeUrl`：用户填的 http/https 绝对地址 |
| 「允许配置新增」 | `POST /api/rag-knowledge` + 面板里的「新增」表单 |
| 「对各个模块允许查询」 | 模块面只读接口：`GET /api/framework/v1/rag-knowledge`、`/active` |
| 「允许用户修改、删除」 | `PATCH /api/rag-knowledge/:id`、`DELETE /api/rag-knowledge/:id` |
| 「设置为可用」 | `POST /api/rag-knowledge/:id/activate`，**单条生效**语义 |

### 1.1 三个语义先定死

1. **「可用」= 当前生效，全局至多一条。**
   不做 `enabled` + `isDefault` 两个开关（Agent 代理那套）。需求只要「设置为可用」一个动作，
   两个开关会让「可用但没选」变成第三种状态，而模块拿到它也没法决定该用哪条。
2. **全局，不按工作区分。**
   与模型配置、Agent 代理一致。以后真要按工作区隔离，加一列 `workspace_id` 即可，
   现在不提前设计（YAGNI）。
3. **模块侧只读。**
   模块面新增的这个子树**只有 GET**。模型与工作区在模块面可写，是因为模块确实要写；
   知识库的写入者是「设置里的用户」，模块没有写理由。少一个写入口，
   泄漏的令牌就少一分杀伤面。

### 1.2 与左侧栏「知识库」导航的关系（需要单独确认）

左侧栏 `nav.knowledge` 现在指向 `<ModuleHost capability="knowledge" />`，而当前没有任何模块
声明 `knowledge` 能力，所以点进去是「该模块尚未接入」。这与本次需求**不是同一件事**，
但用户说「跳转路由」时也可能指它。本方案的处理：

- **一期（本方案主体）**：知识库路由是被模块消费的配置。
- **二期（已实施；2026-10-28 修订为当前口径）**：「知识库」导航在**新浏览器标签页**打开
  生效项的地址（`target="_blank" rel="noopener noreferrer"`）。宿主仍保留 `/knowledge`
  路由给直接访问 / 旧书签，由 `KnowledgePage` 把地址嵌进主面板。
  - 未配置时点菜单直接落到「设置 → 知识库路由设置」并展开新增表单；从这条路径进入时
    表单默认勾「设为可用」，避免"新建了但侧栏仍打不开"；面板自己的「新增」按钮不变。
  - 嵌入用与模块宿主同一份最小权限沙箱（`allow-scripts allow-same-origin allow-forms
    allow-popups allow-downloads allow-top-navigation-by-user-activation` + 剪贴板）。
    这**不**等于给框架开任意嵌入入口：被嵌地址由本机用户当场选定，且只有一条；
    模块侧仍然不能用它自行 iframe 内嵌（见 `rag-knowledge-api.md` §6）。
  - 也**没有**在页面加载时自动 `location.assign`，那会把用户无声地带离宿主。

---

## 2. 数据模型

新表，与 `model_configs` 同风格（snake_case 列名、`*_at` 用 `timestamp_ms`、无密钥）。

```sql
CREATE TABLE rag_knowledge_bases (
  id          TEXT PRIMARY KEY NOT NULL,
  name        TEXT NOT NULL,
  route_url   TEXT NOT NULL,
  description TEXT,
  is_active   INTEGER NOT NULL DEFAULT 0,
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

-- 单条生效的兜底：即使并发/手改库，也不可能出现两条 1。
CREATE UNIQUE INDEX rag_knowledge_bases_active_uidx
  ON rag_knowledge_bases (is_active) WHERE is_active = 1;
```

Drizzle 定义（`server/src/db/schema.ts`，第三个参数用数组形式，与 `experts` 一致）：

```ts
export const ragKnowledgeBases = sqliteTable(
  'rag_knowledge_bases',
  {
    id: text('id').primaryKey(),
    name: text('name').notNull(),
    routeUrl: text('route_url').notNull(),
    description: text('description'),
    isActive: integer('is_active', { mode: 'boolean' }).notNull().default(false),
    createdAt: integer('created_at', { mode: 'timestamp_ms' }).notNull(),
    updatedAt: integer('updated_at', { mode: 'timestamp_ms' }).notNull(),
  },
  (table) => [
    // 部分唯一索引：只约束 is_active = 1 的行，0 可以有任意多条。
    uniqueIndex('rag_knowledge_bases_active_uidx')
      .on(table.isActive)
      .where(sql`${table.isActive} = 1`),
  ],
);
```

`drizzle-orm@0.45.4` 的 `IndexBuilder.where()` 支持部分索引（已核对类型定义），
`drizzle-kit@0.31.11` 能把它生成到 SQL 里。

**迁移**：`cd framework/server && pnpm db:generate` 生成 `drizzle/0001_*.sql`，
启动时由 `runMigrations` 自动应用。纯新增表，旧库升级无需删库；旧版本代码不认这张表也无害。

**不做唯一约束的**：`name` 与 `route_url` 都允许重复。两条同名不同地址是用户自己的选择；
强制唯一只会在保存时制造「为什么不让存」的困惑。

---

## 3. 契约层

新文件 `shared/src/contracts/rag-knowledge.ts`，并在 `contracts/index.ts` 加一行导出。

### 3.1 跳转路由的校验（这是整个功能唯一有攻击面的字段）

```ts
export const RAG_KB_ROUTE_MAX_LENGTH = 2048;
export const RAG_KB_NAME_MAX_LENGTH = 64;
export const RAG_KB_DESCRIPTION_MAX_LENGTH = 256;

/**
 * 跳转路由：只接受 http/https 绝对地址，且不能内嵌账号密码。
 *
 * 协议与绝对地址的形状约束复用 `httpUrlSchema`（`contracts/primitives.ts`），
 * 这里只补一条它不管的：`https://user:pass@host/` 合法但会把凭据带进浏览器历史、
 * Referer 与截图。
 */
export const ragKnowledgeRouteUrlSchema = httpUrlSchema
  .max(RAG_KB_ROUTE_MAX_LENGTH)
  .refine((value) => {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      return false;
    }
    return url.username === '' && url.password === '';
  }, '跳转路由不能内嵌账号密码');
```

拒绝清单及理由：

| 输入 | 结果 | 为什么 |
| --- | --- | --- |
| `javascript:alert(1)` | 拒绝 | 会被当成可点击链接，直接是 XSS 面 |
| `data:text/html,...` | 拒绝 | 同上 |
| `file:///etc/passwd` | 拒绝 | 把用户引向本机文件，且暴露路径语义 |
| `//evil.example/x` | 拒绝 | 协议相对地址，解析后仍是外站，但用户以为「没写域名」 |
| `/\evil.example/x` | 拒绝 | 部分解析器会折成 `//evil.example`（同 `module.ts` 的 entryPath 教训） |
| `https://u:p@host/` | 拒绝 | 凭据会随链接进入浏览器历史与日志 |
| 3000 字符 | 拒绝 | 长度上限，避免把整页撑坏 |
| `http://127.0.0.1:4830/kb/1` | 接受 | 本机模块地址是合法用法（只要它是 http/https） |

> **不做服务端连通性探测。** 与模型配置的 `probe`（D21）理由相同：用户填什么地址，
> 服务端就去请求什么地址 = 一条 SSRF 路径（可打内网、可打云元数据端点）。
> 想验证路由是否可达，点侧栏「知识库」让浏览器在新标签页里加载它（打不开就是不可达）——
> 服务端始终不碰这个地址。

### 3.2 schema

```ts
export const ragKnowledgeBaseSchema = z.object({
  id: z.uuid(),
  name: z.string().min(1).max(RAG_KB_NAME_MAX_LENGTH),
  routeUrl: ragKnowledgeRouteUrlSchema,
  description: z.string().max(RAG_KB_DESCRIPTION_MAX_LENGTH).nullable(),
  isActive: z.boolean(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
});

export const createRagKnowledgeBaseInputSchema = z.object({
  name: z.string().trim().min(1).max(RAG_KB_NAME_MAX_LENGTH),
  routeUrl: ragKnowledgeRouteUrlSchema,
  description: z.string().trim().max(RAG_KB_DESCRIPTION_MAX_LENGTH).nullable().default(null),
  /** 新增时即可设为可用（面板里是个勾选框，默认不勾）。 */
  isActive: z.boolean().default(false),
});

/** PATCH：undefined = 不改，null = 清空（与 updateModelConfigInputSchema 同一套语义）。 */
export const updateRagKnowledgeBaseInputSchema = z
  .object({
    name: z.string().trim().min(1).max(RAG_KB_NAME_MAX_LENGTH).optional(),
    routeUrl: ragKnowledgeRouteUrlSchema.optional(),
    description: z.string().trim().max(RAG_KB_DESCRIPTION_MAX_LENGTH).nullable().optional(),
    isActive: z.boolean().optional(),
  })
  .refine((patch) => Object.values(patch).some((value) => value !== undefined), {
    message: '至少需要一个待更新字段',
  });
```

复用现有的 `idParamsSchema`。

---

## 4. 服务端

### 4.1 仓储

`server/src/repositories/rag-knowledge.repository.ts`，接口与 `ModelConfigRepository` 对齐：

```ts
list(): Promise<RagKnowledgeBase[]>            // createdAt asc
findById(id): Promise<RagKnowledgeBase | null>
findActive(): Promise<RagKnowledgeBase | null>
create(input): Promise<RagKnowledgeBase>
update(id, patch): Promise<RagKnowledgeBase | null>
deleteById(id): Promise<boolean>
```

关键实现点：

1. **激活放在事务里**，且**先清后设**：

   ```ts
   await this.#db.transaction(async (tx) => {
     await tx.update(ragKnowledgeBases).set({ isActive: false });
     await tx.update(ragKnowledgeBases).set({ isActive: true, updatedAt: now })
       .where(eq(ragKnowledgeBases.id, id));
   });
   ```

   顺序反了会撞上那条第 2 节的部分唯一索引（两条同时为 1 的瞬间被拒）。
   事务保证模块侧读不到「一条都没有」的中间态。

2. **`create({ isActive: true })` 同样要清旧**，否则直接违反唯一索引。
3. `isActive: false` 走普通 update（只是关掉，不影响别人）。
4. **删除生效项不自动补位**：删完就是「当前没有生效的知识库」，模块侧 `GET /active` 返回
   `data: null`。自动把另一条提上来等于替用户改配置——他可能只是删错了想重加。
5. 不需要 `newId()` 之外的任何加密/密钥逻辑：这张表没有秘密。

在 `server/src/services/container.ts` 里挂成 `app.services.ragKnowledge`。

### 4.2 浏览器面（设置面板用）

新文件 `server/src/routes/rag-knowledge.ts`，在 `app.ts` 里
`await app.register(ragKnowledgeRoutes, { prefix: '/api/rag-knowledge' });`，
并给 swagger 的 `tags` 加一条 `{ name: 'rag-knowledge', description: 'RAG 知识库跳转路由' }`。

| 方法 | 路径 | 返回/错误 |
| --- | --- | --- |
| GET | `/api/rag-knowledge` | 全量列表（`createdAt` 升序） |
| GET | `/api/rag-knowledge/active` | 当前生效的一条；没有则 `data: null`（**不是 404**） |
| POST | `/api/rag-knowledge` | 201 + 新记录 |
| GET | `/api/rag-knowledge/:id` | 单条；不存在 → `AppError.notFound('知识库', id)` |
| PATCH | `/api/rag-knowledge/:id` | 部分更新；`isActive:true` 会清掉别人的 |
| POST | `/api/rag-knowledge/:id/activate` | 设为可用（等价 `PATCH {isActive:true}`，与模型接口对齐） |
| DELETE | `/api/rag-knowledge/:id` | `{ id, deleted: true }`；不存在 → 404 |

响应一律走 `sendOk`，错误一律 `AppError`——与现有路由同一套信封，前端不需要分支。
限流、CORS、错误处理都由 `app.ts` 的全局插件继承，路由内不额外配置。

### 4.3 模块面（模块查询用）

新文件 `server/src/routes/module-rag-knowledge.ts`，**只在 `module-face.ts` 里注册一次**：

```ts
await app.register(moduleRagKnowledgeRoutes, { prefix: '/rag-knowledge' });
```

门禁（回环 + 拒绝 `Origin` + 令牌）由父上下文的 `onRequest` 自动继承——这正是
`module-face.ts` 文件头说的「新加子树不会忘记挂门禁」。**不要**去 `app.ts` 单独注册，
否则绕开门禁（那里也有一句同样的提醒）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/framework/v1/rag-knowledge` | 全量列表，供模块让用户「选一条」 |
| GET | `/api/framework/v1/rag-knowledge/active` | 当前生效的一条或 `null` |

**这两个端点只读**，`POST/PATCH/DELETE` 一律不注册（返回 Fastify 默认 404）。

同步要改的三处「会变成谎话的注释/描述」：

1. `module-face.ts` 文件头「面下有两个子树」→ 三个；
2. `app.ts` 里 `framework-module` tag 的 description 补上 RAG 知识库；
3. `docs/module-facing-api.md` 的「两个子树」表述与 §1 对照表。

### 4.4 模块侧怎么用（给模块作者的口径）

```bash
FRAMEWORK=http://127.0.0.1:4300          # 产物里由 artifact.json 的 {{frameworkUrl}} 注入
TOKEN=$(cat "$COSIGHT_HOME/.module-token")   # 令牌自己读文件，不要注入环境变量
curl -s -H "Authorization: Bearer $TOKEN" \
  "$FRAMEWORK/api/framework/v1/rag-knowledge/active"
```

```json
{
  "success": true,
  "data": {
    "id": "3f2a8c1e-6b8d-4a2f-9c31-0d5e7b2f4a10",
    "name": "产品知识库",
    "routeUrl": "https://kb.example.com/kb/42",
    "description": "对外版",
    "isActive": true,
    "createdAt": "2026-10-27T09:12:31.000Z",
    "updatedAt": "2026-10-27T09:12:31.000Z"
  },
  "error": null,
  "meta": null
}
```

未配置时 `data` 为 `null`、HTTP 仍是 200——模块必须把「没有生效知识库」当正常态，
不要按失败重试。

**模块的前端**（iframe 里的页面）不能直接调这个面：浏览器请求带 `Origin`，会被第二道门禁拒掉。
正确姿势是模块自己的后端代取、前端调自己的后端；这也是模块面存在的本意。
（模块基址在产物里由 `artifact.json` 的 `{{frameworkUrl}}` 注入，开发态由 `launch.json` 注入，
令牌仍必须由模块进程自己读 `$COSIGHT_HOME/.module-token`——原因见
`docs/module-facing-api.md` §2 的「三条要求」。）

---

## 5. 前端

### 5.1 设置菜单

- `web/src/stores/ui.ts`：`SETTINGS_TABS` 改为
  `['general', 'model', 'ragKnowledge', 'agentProxy', 'observation']`
  （知识库紧挨模型：两者都是「能力提供方的配置」）。
  `settingsTab` **不持久化**（见该文件头），因此没有旧值迁移问题。
- `web/src/i18n/messages/zh-CN.ts`：`settings.nav.ragKnowledge = '知识库路由设置'`；
  `en-US.ts` 对应 `'Knowledge Base Route'`。`en-US` 类型标注是 `Messages`，
  漏翻会直接编译失败。
- `SettingsDialog.tsx`：在 `.content` 里加一个与现有一模一样的
  `<section role="tabpanel" id="settings-panel-ragKnowledge" hidden={tab !== 'ragKnowledge'}>`。
  页签按钮、键盘漫游（`useRovingFocus`）都从数组派生，不需要额外代码。
  面板必须**常驻挂载**（与其它三个一致），否则切页签会丢掉填了一半的表单。

建议文案：

| key | zh-CN | en-US |
| --- | --- | --- |
| `settings.nav.ragKnowledge` | 知识库路由设置 | Knowledge Base Route |
| `settings.ragKnowledge.title` | 知识库路由设置 | Knowledge Base Route |
| ~~`settings.ragKnowledge.intro`~~ | **已移除**：面板顶部不再放解释段，字段标签与空态已经说清了用途。 | **Removed**; the field labels and empty state carry the explanation. |
| `...listSection` | 知识库跳转路由 | Knowledge-base redirects |
| `...create` | 新增 | Add |
| `...active` / `...setActive` | 当前生效 / 设为可用 | Active / Set active |
| `...empty.title` / `.hint` | 还没有知识库 / 新增一条后，模块就能读到这个跳转路由。 | No knowledge bases yet / Add one so modules can read its jump route. |
| `knowledgeRoute.loading` / `.missingTitle` / `.missingHint` / `.openSettings` | `/knowledge` 页的加载态、未配置空态与「去设置新增」按钮 |
| `knowledgeRoute.loadFailedTitle` / `.loadFailedHint` | `/knowledge` 读取失败（与"没配置"分开说，避免把后端故障误报成未配置） |
| `knowledgeRoute.frameTitle` | 知识库：{name}——iframe 的可访问名，读屏靠它区分被嵌页面 |

### 5.2 数据层

`web/src/api/ragKnowledge.ts`，照 `agentProxies.ts` 的形状：

```ts
export const ragKnowledgeKeys = {
  all: ['rag-knowledge'] as const,
  list: () => [...ragKnowledgeKeys.all, 'list'] as const,
  active: () => [...ragKnowledgeKeys.all, 'active'] as const,
  detail: (id: string) => [...ragKnowledgeKeys.all, 'detail', id] as const,
};
```

hook：`useRagKnowledgeList`、`useActiveRagKnowledge`、`useCreateRagKnowledge`、
`useUpdateRagKnowledge`、`useDeleteRagKnowledge`、`useActivateRagKnowledge`。
所有写操作成功后 `invalidateQueries({ queryKey: ragKnowledgeKeys.all })`——
一次失效同时覆盖列表与 `/active`，不会出现「列表显示已生效、别处仍读旧值」。

### 5.3 面板

`web/src/features/rag-knowledge/`：

| 文件 | 职责 |
| --- | --- |
| `RagKnowledgeSettingsPanel.tsx` | 列表 / 表单二选一；加载骨架、空态、`role="alert"` 错误态 |
| `RagKnowledgeForm.tsx` | 名称、跳转路由、说明；新增时多一个「新增后立即设为可用」勾选框 |
| `ragKnowledgeForm.ts` | 表单状态与校验（与契约同规则，纯函数，单测友好） |

交互细节：

- 每行：名称、「当前生效」徽标、路由（`truncate` + `title` 显示全文）、说明、
  「设为可用 / 编辑 / 删除」。生效那行不显示「设为可用」。
- 行上**不给**「打开」：打开入口只有侧栏「知识库」一处（实施时按用户要求调整，
  见文件头偏差说明与 D51 第 8 条）。
- 删除走 `features/config/ConfirmDelete`，确认文案里带名称。
- 样式复用 `features/config/config.module.css`，不新增视觉体系。
- 可访问性：生效态用文字徽标而非只靠颜色；错误文本通过 `aria-describedby` 关联到字段。

---

## 6. 安全清单

- [x] 路由字段只接受 http/https 绝对地址，拒绝 `javascript:`/`data:`/`file:`/协议相对/内嵌凭据；
- [x] 前后端同一套校验（shared 契约），前端校验只为即时反馈，服务端才是边界；
- [x] React 以文本渲染 `routeUrl`，不拼 HTML、不用 `dangerouslySetInnerHTML`；
- [x] 嵌入走 iframe 沙箱白名单（与模块宿主同一份），不给无用户激活的顶层跳转；
      模块侧若用真链接，带 `rel="noopener noreferrer"`；
- [x] 服务端不请求用户填的地址（无 SSRF），因此不实现「探测」；
- [x] 模块面新子树只读，且门禁由父上下文继承（回环 + 无 `Origin` + 令牌）；
- [x] 不存任何密钥，不引入新的凭据文件；
- [x] 长度上限（名称 64 / 路由 2048 / 说明 256），避免把 UI 或响应撑坏；
- [x] 浏览器面无鉴权依赖既有前提（D25：本机单用户、只监听回环），与模型设置一致；
- [x] 错误消息不回显内部路径或 SQL。

---

## 7. 测试

覆盖率门槛沿用仓库要求（80%）。

| 层 | 文件 | 要点 |
| --- | --- | --- |
| 契约 | `shared/src/contracts/rag-knowledge.test.ts` | 第 3.1 节的拒绝清单逐条；名称/说明长度；PATCH 的 `undefined` vs `null` |
| 仓储 | `server/tests/rag-knowledge.repository.test.ts` | 单条生效（连续激活两条后只有一条为真）；删除生效项后无生效；部分唯一索引在并发写下的兜底；删除不存在返回 false |
| 浏览器面 | `server/tests/api-rag-knowledge.test.ts` | 七个端点；404 形状；激活后列表里旧的变 false；创建时 `isActive:true` 不会留下两条 |
| 模块面 | `server/tests/module-rag-knowledge.test.ts` | 无令牌 403、带 `Origin` 403、非回环 Host 403；GET 列表/active 正常；`POST` 不可用；无生效时 `data:null` |
| 数据层 | `web/tests/api-hooks.test.tsx`（扩） | 写操作后列表与 active 同时失效 |
| 面板 | `web/tests/settings-rag-knowledge-panel.test.tsx` | 空态、新增、编辑、设为可用、删除确认、错误态、加载态；从 `/knowledge` 带一次性请求进入时直接展开表单并预勾「设为可用」，且请求只生效一次 |
| 知识库页 | `web/tests/knowledge-page.test.tsx` | `/knowledge` 嵌入生效地址与沙箱白名单；未配置时按钮打开新增表单；读取失败可重试且真的重取 |
| 侧栏 | `web/tests/shell.test.tsx` | 「知识库」有生效项时是指向 `/knowledge` 的宿主内链接（无 `target`/`rel`）；未配置时打开设置新增；读取失败用「重试」；保存后立即变链接 |
| 设置弹窗 | `web/tests/settings-dialog.test.tsx`（改） | 新页签出现在 `SETTINGS_TABS` 循环里；panel 的 `aria-labelledby`；第 ~343 行的面板断言表补一行 `['ragKnowledge', …listSection, …create]` |
| i18n | `web/tests/i18n.test.ts` | 两语言键一致（现有测试应能自动覆盖） |

回归门禁：`pnpm verify`（typecheck + oxlint + 全部测试 + 覆盖率）。脚本与打包测试不受影响。

---

## 8. 文档

| 文档 | 改动 |
| --- | --- |
| `docs/rag-knowledge-api.md`（新建） | **可直接转发给模块作者**：基址、令牌、两个只读端点、真实响应、接入写法、无生效时的处理 |
| `docs/module-facing-api.md` | 「两个子树」→ 三个；§1 对照表加一行；权限面一节说明「知识库只读」 |
| `docs/framework-decisions.md` | 新增三条：单条生效且删除不自动补位；模块面只读；不做服务端探测 |
| `docs/task-list.md` | 记录本功能的状态 |
| `framework/README.md` | 文档表加 `rag-knowledge-api.md` 一行 |

---

## 9. 实施顺序与改动面

按可独立验证的顺序推进，每步都能单独过门禁。

| 阶段 | 内容 | 文件 |
| --- | --- | --- |
| 1 | 契约 | `shared/src/contracts/rag-knowledge.ts`（新）、`contracts/index.ts`、契约测试 |
| 2 | 表与迁移 | `server/src/db/schema.ts`、`drizzle/0001_*.sql`（生成）、`server/drizzle/meta/*` |
| 3 | 仓储 + 装配 | `repositories/rag-knowledge.repository.ts`（新）、`services/container.ts`、仓储测试 |
| 4 | 浏览器面 | `routes/rag-knowledge.ts`（新）、`app.ts`（注册 + tag）、路由测试 |
| 5 | 模块面 | `routes/module-rag-knowledge.ts`（新）、`routes/module-face.ts`（注册 + 头注释）、测试 |
| 6 | 前端 | `stores/ui.ts`、`SettingsDialog.tsx`、`api/ragKnowledge.ts`（新）、`features/rag-knowledge/*`（新）、两份 i18n、前端测试 |
| 7 | 文档 | 第 8 节 |

工作量估计：服务端 1 天，前端 1 天，测试与文档各半天（含评审修改）。
**不涉及**：打包脚本、产物清单、模块源码、安装/卸载流程、数据库模板。

---

## 10. 验收标准

用户视角：

1. 打开设置 →「知识库路由设置」与其它四个页签并列；键盘左右/上下切换、`aria` 关系正确；
2. 新增一条 `https://kb.example.com/kb/1`，列表出现，未标「当前生效」；
3. 点「设为可用」，该行出现「当前生效」，另一条（若原本生效）自动变回普通行；
4. 编辑名称与路由后保存，列表与生效状态都保留；
5. 填 `javascript:alert(1)` 保存 → 字段报错，请求不发出（前端拦截）、
   绕过前端直接 `curl` 也返回 400（服务端拦截）；
6. 删除当前生效项 → 列表里无「当前生效」，模块面 `GET /active` 返回 `data: null`；
7. 重启框架后配置仍在（迁移已落库）。

模块作者视角：

```bash
TOKEN=$(cat ~/.cosight-harness/.module-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:4300/api/framework/v1/rag-knowledge/active
```

无令牌 / 带 `Origin` / 非回环来源三种情况都是 403；`POST` 该路径是 404。

---

## 11. 明确不做 / 待确认

| 项 | 决定 | 理由 |
| --- | --- | --- |
| 在 iframe 里嵌入 RAG 页面 | **不做** | 用户填的任意 URL 绕过 `allowedOrigins`（D24），等于开一个任意嵌入入口 |
| 自动打开 / 自动跳转 | **不做** | 用户填错地址时会把页面带离宿主，且没有任何提示 |
| 服务端连通性探测 | **不做** | SSRF（同 D21 的模型 probe） |
| 路由里的占位符（`{workspaceId}` 等） | **一期不做** | 需要白名单与转义规则；先看真实需求再定，避免提前发明模板语法 |
| 多条同时「可用」 | **不做** | 模块无法决定用哪条；需求也只要求「设置为可用」 |
| 按工作区隔离 | **不做** | 与模型/代理配置保持一致；以后加 `workspace_id` 即可 |
| 模块侧写接口 | **不做** | 最小权限；知识库的写入者是设置里的用户 |
| 左侧栏「知识库」跳转到该路由 | **已实施（二期）** | 与「模块消费配置」是两件事；按 §1.2 的安全形状实现，见 D51 第 8、9 条 |
