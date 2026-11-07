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
| `lxml` | 6.1.3 | BSD-3-Clause；官方 wheel 捆绑 iconv（LGPL-2.1） | 后端运行时 | iconv 以独立动态库形式随 wheel 分发；许可文本见 `lxml-*.dist-info/licenses/LICENSES.txt` |
| `numpy` | 1.26.4 | BSD-3-Clause；wheel 内 libgfortran（GPL-3.0-with-GCC-exception）、libquadmath（LGPL-2.1-or-later） | 后端运行时 | GCC 运行时例外允许随编译产物分发；许可文本见 `numpy-*.dist-info/LICENSE.txt` |
| `uvloop` | 0.23.0 | MIT；捆绑 libuv（MIT） | 后端运行时 | libuv 许可文本随上游发行版保留 |
| `certifi` | 2026.10.23 | MPL-2.0 | 后端运行时 | 文件级 copyleft；未修改，无源码披露义务 |
| `orjson` | 3.13.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | 后端运行时 | MPL 部分保留许可文本与源码链接 |
| `lightningcss` | 1.33.0 | MPL-2.0 | 前端构建期（`vite` 传递依赖） | 文件级 copyleft；未修改、未随 `dist` 分发，无源码披露义务 |
| `webpack-chain` | 6.5.1 | MPL-2.0 | 前端构建期（`@vue/cli-service` 传递依赖） | 同上 |

上游许可文本：

- LGPL-3.0：https://www.gnu.org/licenses/lgpl-3.0.html
- LGPL-2.1：https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- MPL-2.0：https://mozilla.org/MPL/2.0/

前端另有双许可依赖：`dompurify`（MPL-2.0 OR Apache-2.0）、`jszip`（MIT OR
GPL-3.0-or-later）、`node-forge`（BSD-3-Clause OR GPL-2.0）。本项目分别按
Apache-2.0 / MIT / BSD-3-Clause 选项使用，不落入 copyleft 分支。

## 6. 打包进前端产物与后端镜像的其他组件

前端 `dist` 中包含以下运行时组件（许可文本见各 npm 包内 `LICENSE`，以及 bundle 中保留的
版权 banner）：

| 组件 | 许可 | 说明 |
| --- | --- | --- |
| `@fortawesome/free-solid-svg-icons` / `free-regular-svg-icons` 7.3.1 | CC-BY-4.0 AND MIT | 经 `vanilla-jsoneditor` 进入 bundle；banner 保留版权、许可链接与 CC BY 4.0 声明 |
| `mousetrap` 1.6.5 | Apache-2.0 WITH LLVM-exception | — |
| `vis-network` / `vis-data` / `vis-util` / `keycharm` | Apache-2.0 OR MIT | 本项目按 MIT 选项使用 |
| Vue 3.5.26、Element Plus 2.14.7、@antv/x6 2.19.2、axios、lodash、marked、bytemd、sortablejs 等 | MIT / Apache-2.0 / BSD | 完整清单见 `frontend/package-lock.json` |

后端镜像中包含以下附加组件：

| 组件 | 许可 | 说明 |
| --- | --- | --- |
| `minio` 7.2.15 | Apache-2.0 | 带 NOTICE，随 `minio-*.dist-info/NOTICE` 保留 |
| `pypdfium2` 5.14.0 | BSD-3-Clause / Apache-2.0 + 捆绑 PDFium、ICU、FreeType 等 | 许可文本见 `pypdfium2-*.dist-info/licenses/` |
| `Pillow` 13.0.0 | MIT-CMU + 捆绑库 | 许可文本见 `pillow-*.dist-info/licenses/` |
| `requests` / `python-multipart` / `tzdata` / `cryptography` / `packaging` / `regex` | Apache-2.0 或其双许可 | 许可文本随各自 `dist-info` 保留 |
| `openpyxl` / `et_xmlfile` / `dnspython` / `docx2txt` | MIT / ISC | 许可文本随各自 `dist-info` 或 wheel 内 `LICENSE` 保留 |

## 7. 镜像内分发

后端镜像（`backend/Dockerfile` 的 `COPY . .`）会包含本文件的同名副本
`backend/THIRD-PARTY-NOTICES.md`，以覆盖镜像内分发的 tiktoken 词表与
llama-index-core 提示词。OpenSearch 镜像通过 `deploy/opensearch/Dockerfile`
将本文件复制到 `/usr/share/opensearch/THIRD-PARTY-NOTICES.md`。

发布 Docker 镜像时请同时附带项目 `LICENSE`；当前 Dockerfile 未把根 `LICENSE`
复制进运行镜像，二次分发镜像时应自行补齐。
