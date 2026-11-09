# 自托管字体（D23 = A）

把 Alibaba PuHuiTi 的两个字面按下面的**确切文件名**放进本目录即可生效，不需要改代码：

| 文件名 | 字重 | 用途 |
|---|---|---|
| `AlibabaPuHuiTi-Regular.woff2` | 400 | 卡片描述、上传者、历史项、会话正文 |
| `AlibabaPuHuiTi-Medium.woff2` | 500 | 卡片标题、导航项、页标题、发送按钮文字 |

声明见 `src/styles/fonts.css`，族名与字重的对应关系见 `src/styles/tokens.css` 的字体区块。

## 为什么是这两个文件

UX 稿只给了族名（`Alibaba-PuHuiTi-R` / `Alibaba-PuHuiTi-M`），**没有给字体文件**，
设计稿的 JSON 里也没有 `@font-face`、权重到文件的映射或授权信息
（`docs/design-tokens.md` §8.2 逐项列了缺失清单）。所以本目录现在是空的，
字体由 `tokens.css` 里同字重的回退链负责。

## 在此之前会发生什么

- 从 `local()` 开始找：装了普惠体的机器直接命中本地字体，**没有网络请求**。
- 没装的机器会各请求一次 `/fonts/*.woff2`，拿不到字体文件，然后回退到
  `思源黑体 CN Regular` / `思源黑体 CN Medium`。
  这里**两种运行态的失败长得不一样**，别被状态码骗了：生产态（`vite build` 的产物
  由 server 静态托管）是真 404，而且构建时就会打印 `didn't resolve at build time`；
  开发态（`vite dev`）的 SPA 回退会给这个路径返回 **200 + 一段 `index.html`**，
  浏览器再把 HTML 当 woff2 解析、解析失败。看到 200 不代表字体在，看 `content-type`
  是不是 `text/html` 就知道。
- `font-display: swap` 意味着**内容不会因此晚出现**，只会有一瞬字形切换。
- DevTools 的 Network 里看到两条失败的字体请求是预期现象，不是配置错误。

## 注意

- **必须是 woff2**。`fonts.css` 刻意没写 ttf/otf 回退（原因见该文件末尾的注释）。
- **Medium 不要用合成粗体代替**。若只有 Regular 一个字面，`font-weight: 500`
  会被解析成 400，标题与正文的粗细差异会整体消失——这不是"小一号字重"，
  是设计稿的层次感没了。回退链里点名 `思源黑体 CN Medium` 就是为了避开这一点。
- 放入字体前请先确认授权范围（普惠体可免费商用，但分发形式与再授权条款需按
  项目合规要求复核），这属于本项目无法代为判断的事项。
