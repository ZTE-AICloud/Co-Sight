# 通用文件（files）

> 状态：**草案**。本文是 files 模块的设计依据：上传与读取的机制、安全边界、与 artifacts 的分工、刻意不做的事。
> 接口形状见 [`../05-openapi/5.02-file-openapi.yaml`](../05-openapi/5.02-file-openapi.yaml)；代码落点：`server/src/modules/files/*`（挂载见 `server/src/app.ts`）。
> 验收测试：`server/tests/files-api.test.ts`。

## 1. 定位与分工

上传的是**用户自选的静态资源**（封面图、附件），读取按存储名原样回字节。与 artifacts 的分界：artifacts 读的是智能体工作区（`development/`、`preview/`、`evaluation/` 三个 stage 根，runtime 根嵌在 development 树内）里的产物文件，只读、面向文件浏览；files 管的是用户上传进来的新文件，只增不改（覆盖=换名新文件）、无目录层级。

首个使用方：智能体封面图。`Agent.icon` 存上传响应的 `url`，展示逻辑零改动（icon 本就是 URL 字符串，4.02 的兜底头像口径不变：空串 = 没有封面）。

## 2. 存储布局与命名

- 落盘位置：`{SMART_FACTORY_HOME}/files/`，与 `agents/` 等三根目录并列的独立顶层目录，首次上传时创建。
- 存储名 = 对外 id = `fil_<uuid>` + 可选扩展名，服务端生成；**原文件名不保留**（只消毒其扩展名：去点、小写、只留字母数字、最长 10 段，洗不出合法形态就不带扩展名）。
- 不进数据库：存储名本身编码了全部元数据（身份在 uuid、Content-Type 线索在扩展名、大小在文件系统）。查询、引用计数、回收站都不存在，`Agent.icon` 里的 URL 就是唯一的引用关系。

## 3. 写路径（上传）

multer（diskStorage）收 multipart → 落临时名到 `files/` → 服务层 rename 成存储名。同目录内 rename，无跨设备问题。单文件上限 `FILES_MAX_FILE_BYTES`（缺省 10MB），超限 multer 抛 `LIMIT_FILE_SIZE`，翻译成 `413 PAYLOAD_TOO_LARGE`；缺 `file` 字段或字段名不对翻译成 `400`（见 `files.controller.ts` 的 `uploadSingleFile`）。

## 4. 读路径与安全边界

读取的唯一安全边界是存储名形态校验（`FILE_ID_PATTERN`）：它只放行 `fil_` + uuid + 可选小写字母数字扩展名，**拼不出分隔符、`..` 与绝对路径**。校验后另做一次 resolve 前缀检查（双保险，与 artifact 的 `assertRelativePath` 同思路）。形态非法 400，合法但不存在 404（4.02 §11 的分界口径）。

Content-Type 按扩展名查固定映射表，不在表内一律 `application/octet-stream`；响应恒带 `X-Content-Type-Options: nosniff`。已知残余风险：SVG 可携带脚本，同源直开可执行，端侧本地单用户假设下接受（4.02 §12 的鉴权口径同源），要收窄时在映射表把 `.svg` 降级为 `text/plain` 即可。

## 5. 配置

| 环境变量 | 缺省 | 含义 |
|---|---|---|
| `FILES_MAX_FILE_BYTES` | `10485760`（10MB） | 单个上传文件的大小上限，非法值启动即拒（同 `ARTIFACT_MAX_FILE_BYTES` 的口径） |

## 6. 刻意不做

- **无删除端点、无列表端点**：删除需求只有一个场景（换封面），旧文件留在盘上当孤儿即可，量小（单文件 ≤10MB）；真要清理时按 `fil_` 前缀盘库是运维脚本的事，不值得进 API 面。
- **无覆盖语义**：每次上传都是新 id，客户端自己决定把哪个 URL 存进引用方（如 `Agent.icon`）。
- **不做类型白名单**：模块是通用的，场景各自收口（前端图片选择器限定 accept 即可）。
