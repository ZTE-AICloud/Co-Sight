# 字体资产来源

字体由以下精确锁版的 npm 包提供，经 `src/styles/fonts.css` 引入。构建时由 Vue CLI/webpack 输出至 `dist/fonts/*.woff2`；本目录保留发行时的许可证，运行时不访问字体 CDN。

| 字体 | 包版本 | 来源 | 随站点发布的许可原文 |
| --- | --- | --- | --- |
| Inter Variable | `@fontsource-variable/inter@5.3.0` | https://fontsource.org/fonts/inter | `licenses/Inter-OFL.txt` |
| Noto Sans SC Variable | `@fontsource-variable/noto-sans-sc@5.3.1` | https://fontsource.org/fonts/noto-sans-sc | `licenses/NotoSansSC-OFL.txt` |
| JetBrains Mono Variable | `@fontsource-variable/jetbrains-mono@5.3.0` | https://fontsource.org/fonts/jetbrains-mono | `licenses/JetBrainsMono-OFL.txt` |

三份许可原文均从对应 npm 包的 `LICENSE` 文件复制，使用 SIL Open Font License 1.1。更新字体包时，同时检查许可及字体渲染基准。

加载策略为 `font-display: swap`、Unicode 范围按需加载、Inter Latin 首屏预加载。完整中文分包会随构建发布，浏览器按需请求，支持用户后续输入所覆盖的字符；无需把整个中文字库一次性下载。

Fontsource 接入参考：https://fontsource.org/docs/getting-started/install
