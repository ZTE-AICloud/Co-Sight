# 第三方组件与许可声明

本项目以 Apache License 2.0 发布，完整许可文本见 [`LICENSE`](LICENSE)。

本文件保留随仓库分发的第三方内容的版权与许可声明。运行时依赖（npm / PyPI 包）不随本仓库
分发，其许可与版权声明以各依赖包内的 `LICENSE` 文件为准；依赖清单见 `pnpm-lock.yaml`
及各组件目录下的 `package.json` / `package-lock.json`。

## 1. Claude-Code-Agent-Monitor

使用位置：`cosight-viewer/` 组件的设计与实现参考并复用了该项目的部分代码。

上游：<https://github.com/hoangsonww/Claude-Code-Agent-Monitor>

许可：MIT

```text
MIT License

Copyright (c) 2026 - Now, Son Nguyen

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

该声明同时保留在 [`cosight-viewer/NOTICE`](cosight-viewer/NOTICE)。

## 2. 未随仓库分发的外部组件

- **Claude Code CLI / Claude Agent SDK**：本发行物不包含、不分发 Anthropic 的 Claude Code CLI
  或 Claude Agent SDK。需要真实执行能力时，由用户在自己的运行机上安装并接受 Anthropic 的条款；
  未安装时，各模块的创建、管理与浏览功能照常可用。
- **字体**：`framework/web/public/fonts/` 仅包含说明文档，不含字体文件。若使用方自行放入字体，
  应自行确认该字体的授权范围。

如发现遗漏的第三方声明，欢迎提交 Issue 或 Pull Request 补充。
