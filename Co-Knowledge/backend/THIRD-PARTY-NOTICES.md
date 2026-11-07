# 第三方组件与许可声明

本仓库以 Apache License 2.0 发布，完整许可文本见 `LICENSE`。本文件保留随仓库分发、
随镜像分发或被逐字引用的第三方内容的版权与许可声明。

运行时依赖的完整清单见 `backend/requirements.txt`、`backend/requirements.lock`、
`frontend/package.json` 与 `frontend/package-lock.json`；各依赖的许可以其包内
`LICENSE` 为准。本仓库不复制这些依赖的源码。

## 1. llama-index-core 0.10.31

使用位置：

- `backend/src/engine/primitives/prompts.py`：6 段默认 prompt 逐字复制；
- `backend/src/engine/primitives/` 其余模块：行为、默认模板与若干格式复刻自
  llama-index-core，均为本仓独立重写实现。

上游：https://github.com/run-llama/llama_index （v0.10.31）

许可：MIT

```text
The MIT License

Copyright (c) Jerry Liu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## 2. tiktoken（cl100k_base 词表）

使用位置：`backend/src/engine/primitives/_static/tiktoken_cache/9b5ad71b2ce5302211f9c61530b329a4922fc6a4`
（1,688,126 字节，内容为 cl100k_base BPE 词表；经 `llama-index-core 0.10.31`
wheel 拷贝，文件逐字节未修改）。

上游：https://github.com/openai/tiktoken

许可：MIT

```text
MIT License

Copyright (c) 2022 OpenAI, Shantanu Jain

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 3. 字体

| 字体 | 来源包 | 许可 | 许可原文 |
| --- | --- | --- | --- |
| Inter Variable | `@fontsource-variable/inter@5.3.0` | SIL OFL 1.1 | `frontend/public/fonts/licenses/Inter-OFL.txt` |
| Noto Sans SC Variable | `@fontsource-variable/noto-sans-sc@5.3.1` | SIL OFL 1.1 | `frontend/public/fonts/licenses/NotoSansSC-OFL.txt` |
| JetBrains Mono Variable | `@fontsource-variable/jetbrains-mono@5.3.0` | SIL OFL 1.1 | `frontend/public/fonts/licenses/JetBrainsMono-OFL.txt` |

字体文件来自对应 npm 包，未做修改；SIL OFL 1.1 允许随软件再分发。许可原文随仓库与
前端镜像（`/usr/share/nginx/html/fonts/licenses/`）保留。

## 4. 容器镜像与插件

| 组件 | 版本 | 许可 | 说明 |
| --- | --- | --- | --- |
| OpenSearch | 2.19.6 | Apache-2.0 | 基础镜像 `opensearchproject/opensearch:2.19.6`；其 NOTICE/LICENSE 随镜像保留 |
| analysis-ik | 2.19.6 | Apache-2.0 | 上游 https://github.com/medcl/elasticsearch-analysis-ik ；插件包随构建上下文分发（`deploy/opensearch/analysis-ik.zip`），构建时校验 SHA-256（见 `deploy/opensearch/Dockerfile`） |

analysis-ik 插件包内还包含以下第三方 Java 依赖（随插件包原样分发）：
`httpclient-4.5.13`、`httpcore-4.4.13`、`commons-logging-1.2`、`commons-codec-1.11`。
这些 jar 的许可以其包内声明为准。

## 5. 弱 copyleft 依赖

下表列出以 LGPL / MPL 许可使用的依赖。它们均未修改源码：LGPL 依赖以独立模块动态导入，
不改变本项目 Apache-2.0 许可；MPL 依赖仅用于前端构建，不进入 `dist`。完整许可文本见各包
`dist-info/LICENSE` / 包内 `LICENSE`，或下列上游链接。

| 包 | 版本 | 许可 | 使用方式 | 说明 |
| --- | --- | --- | --- | --- |
| `psycopg2-binary` | 2.9.9 | LGPL-3.0-or-later，附 OpenSSL 链接例外 | 后端运行时，`import psycopg2` 动态导入 | 保留许可与版权声明；修改该库时修改部分需按 LGPL 发布；未修改则不要求本项目开源 |
| `chardet` | 5.2.0 | LGPL-2.1（或更高） | 后端运行时，独立模块导入 | 同上 |
| `lightningcss` | 1.33.0 | MPL-2.0 | 前端构建期（`vite` 传递依赖） | 文件级 copyleft；未修改、未随 `dist` 分发，无源码披露义务 |
| `webpack-chain` | 6.5.1 | MPL-2.0 | 前端构建期（`@vue/cli-service` 传递依赖） | 同上 |

上游许可文本：

- LGPL-3.0：https://www.gnu.org/licenses/lgpl-3.0.html
- LGPL-2.1：https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- MPL-2.0：https://mozilla.org/MPL/2.0/

前端另有双许可依赖：`dompurify`（MPL-2.0 OR Apache-2.0）、`jszip`（MIT OR
GPL-3.0-or-later）、`node-forge`（BSD-3-Clause OR GPL-2.0）。本项目分别按
Apache-2.0 / MIT / BSD-3-Clause 选项使用，不落入 copyleft 分支。

## 6. 镜像内分发

后端镜像（`backend/Dockerfile` 的 `COPY . .`）会包含本文件的同名副本
`backend/THIRD-PARTY-NOTICES.md`，以覆盖镜像内分发的 tiktoken 词表与
llama-index-core 提示词。
