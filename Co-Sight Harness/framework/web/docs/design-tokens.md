# Co-Sight Harness — Design Tokens (extracted from Sketch MeaXure spec)

**Source:** UX design spec export (Sketch MeaXure); not bundled in this repository
**Export type:** Sketch MeaXure *spec export* (not a clickable prototype)
**Document settings:** `resolution: 1`, `unit: px`, `colorFormat: color-hex`
**Page:** `页面 1`

The spec is a single minified HTML file. All measurements live in an embedded
`let data = {…}` JSON blob (402 KB) containing `artboards`, `slices`, `colors`
and `languages`. Every layer carries a `rect`, optional `radius`, `fills`,
`borders`, `shadows`, `styleName` and — for text — `content`, `color`,
`fontSize`, `fontFace`, `lineHeight`, `letterSpacing`, `textAlign`. Most layers
also carry a pre-rendered `css: []` array. **Everything below is read directly
from that JSON** unless explicitly marked *(inferred)*.

---

## 1. Artboards (3 total, all 1920 × 1080)

| # | Spec name | Slug | Preview PNG | What it depicts |
|---|-----------|------|-------------|-----------------|
| 0 | `全屏-01备份 49` | `页面-1-1-全屏-01备份-49` | `preview/页面-1-1-全屏-01备份-49.png` | **Home / new-conversation start screen.** Sidebar + big centred wordmark + mode tabs + recommendation tags + large input box + send button + AI disclaimer. |
| 1 | `全屏-01备份 51` | `页面-1-2-全屏-01备份-51` | `preview/页面-1-2-全屏-01备份-51.png` | **Expert grid page (`专家`).** Sidebar + page title + segmented filter tabs + search box + 6 × 5 grid of expert cards (28 drawn). Card #8 is shown in the *selected* state. |
| 2 | `全屏-01备份 50` | `页面-1-3-全屏-01备份-50` | `preview/页面-1-3-全屏-01备份-50.png` | **Conversation detail page.** Sidebar (with a highlighted history item) + chat topbar + dismissible banner + message stream (user bubbles right, AI messages left) + action icon row + follow-up suggestion pills + input box. |

Layer counts: ab0 = 101, ab1 = 476, ab2 = 169 (top-level `artboards[].layers`).
Note: MeaXure **flattens groups** — a `group` layer frequently has `layers: []`
while its children appear as *siblings* at the same level. Geometry is still
absolute and correct, so this does not affect the token extraction.

---

## 2. Colour tokens

### 2.1 Document palette (the `colors` array — 5 named swatches)

| Swatch name | Actual value | Notes |
|---|---|---|
| `D9D9D9` | `#D9D9D9` | neutral grey |
| `1993FF` | `#1993FF` | brand blue |
| `4D4D4D` | `#4D4D4D` | dark grey |
| `737373` | `#737373` | mid grey |
| `F5F5F5` | `#FFF5EE` | ⚠️ **name/value mismatch** — swatch is named `F5F5F5` but its value is `#FFF5EE` |

### 2.2 Fill colours by frequency (`fills[]` across all 3 artboards)

| Hex | Alpha | ×n | Role (from `styleName` / context) |
|---|---|---|---|
| `#EEEEEE` | 100% | 84 | **Tag / chip background** — `辅助色/灰色/Gray-3(#eeeeee)` |
| `#FFFFFF` | 100% | 41 | Card background, search box, tab pill, input box, avatar ring |
| `#737373` | 100% | 22 | Icon glyph fills, divider strokes |
| `#333333` | 100% | 14 | Icon glyph fills; **send button** background |
| `#000000` | 100% | 12 | Icon glyph geometry (symbol internals) |
| `#1A1A1A` | 100% | 6 | Calendar nav-icon glyph |
| `#FFFFFF` | 85% | 3 | **Main content panel background** (`rgba(255,255,255,0.85)`) |
| `#374151` | 100% | 3 | Agent nav-icon glyph |
| `#E6ECF6` | 100% | 2 | **Segmented tab track** background |
| `#31517A` | 100% | 2 | `+` (new) icon glyph |
| `#53AEFF` | 100% | 2 | **User chat bubble** background (`基准色/蓝色/Blue-2`) |
| `#737373` | 0% | 2 | Transparent icon backer plate |
| `#1993FF` | 100% | 1 | Selected history-item highlight (drawn at `opacity: 0.1`) |
| `#FFFFFF` | 30% | 1 | Chat topbar background |
| `#DFE9EF` | 40% | 1 | Chat banner background |
| `#BDE5FF` | 100% | 1 | Chat title chip (drawn at `opacity: 0`) |

### 2.3 Border colours — **exactly 4 neutral borders** (+2 accents)

| Hex | Position | Thickness | ×n | Applied to |
|---|---|---|---|---|
| `#DCE8EA` | Inside | 1px | 27 | **Expert card border** (default state) |
| `#CDDDE5` | Inside | 1px | 9 | Recommendation tag border (ab0, `06-线面/11-场景推荐按钮`) |
| `#CDDDE5` | Center | 1px | 3 | Follow-up suggestion pill border (ab2, `辅助色/海军蓝/Navy-1`) |
| `#D9D9D9` | Inside | 1px | 6 | Main panel outer border; **input-box** border; search-box border |
| `#D9D9D9` | Center | 1px | 2 | In-message divider (`直线 3`) |
| `#D7E0E5` | Center | 1px | 3 | **Sidebar bottom divider** |
| `#1993FF` | Inside | 1px | 1 | **Selected expert card border** (accent) |
| `#737373` | Inside | 1px | 1 | Icon stroke (accent) |

> The 4 neutral border colours are `#DCE8EA`, `#CDDDE5`, `#D9D9D9`, `#D7E0E5`.
> All borders are **1px**.

### 2.4 Text colours

| Hex | ×n | Role |
|---|---|---|
| `#4D4D4D` | 142 | **Body / primary text** — card description, tag label, author line |
| `#333333` | 73 | **Heading / nav / chat body** — page title, sidebar nav labels, history items, AI message body |
| `#737373` | 31 | **Secondary / label** — app subtitle, `历史会话` section label, chat meta (`我`, timestamps), topbar controls, suggestion-pill text |
| `#999999` | 5 | **Placeholder / hint** — input placeholder, search placeholder, AI disclaimer |
| `#000000` | 4 | Wordmark (`Co-Sight Harness` ×3, once at 18px and once at 40px) |
| `#FFFFFF` | 2 | Text on accent (user chat bubble) |
| `#1993FF` | 1 | Inline link text inside an AI message (`已选网元(12)`) |

### 2.5 Elevation (4 distinct shadows, all present)

| CSS | ×n | Applied to |
|---|---|---|
| `box-shadow: 0 1px 3px 0 rgba(0,0,0,0.15)` | 2 | Sidebar active/selected item background; sidebar "new chat" background |
| `box-shadow: 0 1px 8px 0 rgba(13,139,211,0.15)` | 1 | Home input box (ab0) |
| `box-shadow: 0 1px 1px 0 rgba(13,139,211,0.15)` | 1 | Chat input box (ab2) |
| `box-shadow: 0 1px 16px 0 rgba(0,0,0,0.15)` | 1 | **Selected expert card** |

### 2.6 Gradients (1 only)

```css
/* Selected expert card background */
background-image: linear-gradient(151deg, rgba(216,240,255,0.20) 35%, rgba(239,191,255,0.20) 100%);
```

---

## 3. Typography

### 3.1 Font families — verbatim strings

Two different spellings exist: `fontFace` (Sketch face name, with spaces) and the
`font-family` string MeaXure writes into `css[]`. **Use the `css[]` form in code.**

| `fontFace` | `font-family` (verbatim) | Weight emitted | ×n |
|---|---|---|---|
| `Alibaba PuHuiTi` | `Alibaba-PuHuiTi-R` | `400` | 201 |
| `Alibaba PuHuiTi` | `Alibaba-PuHuiTi-M` | `500` | 50 |
| `Helvetica` | `Helvetica-Bold` | `700` | 4 |
| `PingFang TC` | `PingFangTC-Regular` | `400` | 3 |

> `Alibaba-PuHuiTi-R` / `Alibaba-PuHuiTi-M` are **weight-suffixed family names**,
> i.e. Regular and Medium are separate families in this export, each also carrying
> an explicit `font-weight`. If you self-host, map both to one family with two weights.

### 3.2 Font sizes in use
`10px`, `12px`, `14px`, `16px`, `18px`, `40px` — no others.

### 3.3 Line heights in use
`16px`, `18px`, `22px`, `24px`, plus *unset* (auto) on a number of layers.

### 3.4 Letter spacing
`letterSpacing: 0` on **every** text layer in the document. No tracking anywhere.

### 3.5 Complete type-style table (every distinct combination present)

| Family | Size | Weight | Line-height | Align | Colour | ×n | Applied to |
|---|---|---|---|---|---|---|---|
| `Alibaba-PuHuiTi-R` | 10 | 400 | 18 | center | `#4D4D4D` | 84 | **Card tag label** (`02-Body正文/Center/Body正文-s`) |
| `Alibaba-PuHuiTi-R` | 10 | 400 | 16 | left | `#4D4D4D` | 28 | **Card description** (2-line clamp) |
| `Alibaba-PuHuiTi-R` | 10 | 400 | auto | left | `#4D4D4D` | 28 | **Card author / uploader line** |
| `Alibaba-PuHuiTi-M` | 12 | 500 | 22 | left | `#333333` | 28 | **Card title** (`02-s12/01-标题/二级标题14Bold-Left`) |
| `Alibaba-PuHuiTi-R` | 14 | 400 | 18 | left | `#333333` | 15 | **Sidebar history-item label** |
| `Alibaba-PuHuiTi-M` | 14 | 500 | auto | left | `#333333` | 12 | **Sidebar nav item label** |
| `Alibaba-PuHuiTi-R` | 12 | 400 | 18 | left | `#737373` | 12 | Chat meta / topbar control (`05-Label标签&未选中-s`) |
| `Alibaba-PuHuiTi-R` | 12 | 400 | 22 | center | `#737373` | 9 | **Recommendation tag label** (ab0, `02-s12/05-标签&未选中/h22-center（AI）`) |
| `Alibaba-PuHuiTi-R` | 12 | 400 | auto | left | `#737373` | 4 | Chat banner text; follow-up suggestion pill text |
| `Alibaba-PuHuiTi-R` | 12 | 400 | auto | center | `#333333` | 3 | Mode tab inactive label (`代码开发`, `最热`, `最新`) |
| `Helvetica-Bold` | 18 | 700 | auto | left | `#000000` | 3 | **Sidebar wordmark** |
| `Alibaba-PuHuiTi-R` | 10 | 400 | 18 | left | `#737373` | 3 | Sidebar app subtitle (`您的全天候个人秘书`) |
| `Alibaba-PuHuiTi-M` | 14 | 500 | 18 | left | `#333333` | 3 | Sidebar "new chat" label (`新建对话`) |
| `Alibaba-PuHuiTi-M` | 12 | 500 | 18 | left | `#333333` | 3 | Sidebar user name (`User name`) |
| `PingFangTC-Regular` | 12 | 400 | auto | center | `#737373` | 3 | Sidebar section label (`历史会话`) |
| `Alibaba-PuHuiTi-R` | 12 | 400 | 22 | left | `#333333` | 3 | AI message body |
| `Alibaba-PuHuiTi-R` | 14 | 400 | 22 | left | `#999999` | 2 | **Input placeholder** (`今天帮你做些什么？…`) |
| `Alibaba-PuHuiTi-M` | 12 | 500 | auto | left | `#333333` | 2 | Mode tab **active** label (`日常办公`, `全部`) |
| `Alibaba-PuHuiTi-R` | 12 | 400 | 18 | center | `#999999` | 2 | AI disclaimer (`内容由AI生成，仅供参考`) |
| `Alibaba-PuHuiTi-R` | 12 | 400 | 18 | left | `#FFFFFF` | 2 | User chat bubble text |
| `Alibaba-PuHuiTi-R` | 12 | 400 | 24 | left | `#333333` | 2 | AI message body (looser variant) |
| `Helvetica-Bold` | 40 | 700 | auto | left | `#000000` | 1 | **Home hero wordmark** |
| `Alibaba-PuHuiTi-M` | 16 | 500 | auto | center | `#333333` | 1 | **Page title** (`专家`) |
| `Alibaba-PuHuiTi-R` | 12 | 400 | 18 | left | `#999999` | 1 | **Search placeholder** (`搜索`) |
| `Alibaba-PuHuiTi-M` | 12 | 500 | 18 | left | `#4D4D4D` | 1 | Chat conversation title (`张江地区执行小区克隆查询`) |
| `Alibaba-PuHuiTi-R` | 12 | 400 | 22 | left | `#1993FF` | 1 | Inline link in AI message (`已选网元(12)`) |
| `Alibaba-PuHuiTi-R` | 12 | 400 | 22 | left | `#4D4D4D` | 1 | Inline continuation text (`，目标网元：`) |
| `Alibaba-PuHuiTi-R` | 12 | 400 | auto | left | `#333333` | 1 | `您还可以这样问：` |

> ⚠️ Note the naming inconsistency in the spec itself: the card **title** style is
> named `二级标题14Bold` but is actually **12px / weight 500**, not 14px / bold.

---

## 4. Radii — 9 distinct values + 1 asymmetric

| Radius | ×n | Applied to |
|---|---|---|
| `1px` | 2 | Tiny text-rendering glyph bars inside an icon |
| `3px` | 85 | **Tag chip background**; **search box** (`线面/normal(白底)`) |
| `8px` | 3 | Chat user bubble; selected history-item highlight |
| `10px` | 2 | **Sidebar item pill** (new-chat / active nav item) |
| `12px` | 28 | **Expert card** (all 28) |
| `15px` | 2 | **Segmented-control active pill** (inside a 16px-radius track) |
| `16px` | 14 | **Segmented tab track**; **recommendation tag** (80×28); **follow-up suggestion pill** |
| `20px` | 4 | **Input box** (960×148 and 960×130); **send button** (32×32) |
| `56px` | 5 | **Avatar** (24×24 and 40×40 — effectively a circle) |
| `12px 0 0 12px` | 3 | **Main content panel** (rounded on the left edge only) |

A bare `radius: [0]` appears 14× — this is an explicit zero, used on icon-internal
rectangles and on full-bleed bars (chat topbar / banner), not a distinct token.

---

## 5. Layout & geometry

### 5.1 Shell (identical across all 3 artboards)

| Element | x | y | w × h | Notes |
|---|---|---|---|---|
| Artboard | 0 | 0 | **1920 × 1080** | |
| **Sidebar** | 0 | 0 | 280 × 1080 | No explicit background rect — *(inferred)* 280px wide, transparent/white canvas |
| **Main panel** | 280 | 0 | **1640 × 1080** | `background: rgba(255,255,255,0.85)`; `border: 1px solid #D9D9D9`; `border-radius: 12px 0 0 12px` |
| Sidebar bottom divider | 0 | 1027.5 | 280 × 1 | `1px solid #D7E0E5` |
| AI disclaimer | 590 | 1054 | 1020 × 18 | 12px/18 centered `#999999` |

**So: sidebar width = 280px, main panel = 1640px, total 1920px.**

### 5.2 Sidebar internals

| Element | x | y | w × h | Style |
|---|---|---|---|---|
| Wordmark `Co-Sight Harness` | 54 | 14 | 150 × 22 | Helvetica-Bold 18px `#000000` |
| Collapse icon (`折叠`) | 24 | 27 | 11 × 10 | fill `#737373` |
| Subtitle `您的全天候个人秘书` | 55 | 36 | 89 × 18 | 10px/18 `Alibaba-PuHuiTi-R` `#737373` |
| **Item pill background** | 16 | *varies* | **248 × 40** | `border-radius: 10px`; `#FFFFFF`; `box-shadow: 0 1px 3px 0 rgba(0,0,0,0.15)` |
| Item icon | 28 | *varies* | 16 × 16 | fill `#333333` (varies per icon) |
| Item label | 52 | *varies* | — | 14px `Alibaba-PuHuiTi-M` w500 `#333333` |

**Nav item vertical positions (measured, ab1):**

| Item | Pill top (y) | Label y | Icon y |
|---|---|---|---|
| `新建对话` (new chat) | 71 | 81 | 82 (group `新建对话 (1)`, 16×16 at x=28) |
| `专家` | 119 | 129 | 131 (`闪电 (1)` 15.05×16 at x=27) |
| `Agent开发. 评估` | 167 | 177 | 179 (`智能体` 15.82×16 at x=28) |
| `知识库` | 213 | 223 | 225.25 (`日程` 16×15.16 at x=26.875) |
| `观测` | 261 | 271 | 274 (`Dashboard 3` 16×16 at x=28) |

Item box is **248 × 40** at **x = 16**. Stride between item tops: 71 → 119 = 48,
119 → 167 = 48, 167 → 213 = 46, 213 → 261 = 48. *(inferred)* the intended gap is
**8px** between 40px-tall items (the 46px step is a 2px measurement artifact in the
`知识库` group). **Note:** the group containing `Agent开发. 评估` is `248 × 123`
because it is drawn as an expanded parent group — the nav item itself is 40 tall.

| Section label `历史会话` | 18 | 309 | 48 × 28 | `PingFangTC-Regular` 12px `#737373` centered |
|---|---|---|---|---|
| History item label | 24 | 343 / 383 / 423 / 463 / 503 | ~140 × 40 | 14px/18 `Alibaba-PuHuiTi-R` `#333333`; **40px stride** |
| **Selected history highlight** (ab2) | 16 | 345 | **248 × 36** | `background: #1993FF; opacity: 0.1; border-radius: 8px` |
| User avatar | 16 | 1040 | 24 × 24 | `border-radius: 56px` |
| User name `User name` | 50 | 1044 | 63 × 18 | 12px/18 `Alibaba-PuHuiTi-M` `#333333` |
| User chevron | 248 | 1044 | 16 × 16 | `16px/03方向指示类/down` |

**Active-nav treatment:** the white pill + `0 1px 3px rgba(0,0,0,0.15)` shadow is the
"selected" state. In **ab0** it sits on `新建对话` (y=71); in **ab1** it sits on `专家`
(y=119); **ab2** has no white nav pill at all.

### 5.3 Expert grid page (ab1)

| Element | x | y | w × h | Style |
|---|---|---|---|---|
| Page title `专家` | 304 | 16 | 32 × 40 | 16px `Alibaba-PuHuiTi-M` w500 `#333333` |
| **Filter tab track** | 304 | 60 | **184 × 32** | `#E6ECF6`, `border-radius: 16px` |
| Active tab pill | 306 | 62 | **60 × 28** | `#FFFFFF`, `border-radius: 15px` |
| `全部` (active) | 322 | 67 | 24 × 17 | 12px `Alibaba-PuHuiTi-M` w500 `#333333` |
| `最热` | 372 | 67 | 48 × 17 | 12px `Alibaba-PuHuiTi-R` `#333333`, **`opacity: 0.7`** |
| `最新` | 432 | 67 | 48 × 17 | 12px `Alibaba-PuHuiTi-R` `#333333`, **`opacity: 0.7`** |
| **Search box** | 1696 | 60 | **200 × 32** | `#FFFFFF`, `border: 1px solid #D9D9D9`, `border-radius: 3px` |
| Search icon | 1704 | 68 | 16 × 16 | fill `#737373` |
| Search placeholder `搜索` | 1724 | 67 | 164 × 18 | 12px/18 `Alibaba-PuHuiTi-R` `#999999` |

**Grid geometry (measured from all 28 card rects):**

- **6 columns × 5 rows** laid out, **28 cards drawn** (the last row has only 4).
- Column x positions: `304, 572, 840, 1108, 1376, 1644` → **column pitch 268px**
- Row y positions: `108, 258, 408, 558, 708` → **row pitch 150px**
- Card size **252 × 134**
- **Gap = 16px horizontal, 16px vertical** (268 − 252 = 16; 150 − 134 = 16)
- Grid left = 304, right edge = 1644 + 252 = **1896**
- Content padding = **24px** on both sides (304 − 280 = 24; 1920 − 1896 = 24)
- Vertical gap between the tab track (bottom 92) and the first row (108) = **16px**
- Row 5 contains cards at x = 304, 572, 840, 1108 only.

### 5.4 Home screen (ab0)

| Element | x | y | w × h | Style |
|---|---|---|---|---|
| Hero wordmark `Co-Sight Harness` | 934 | 281 | 332 × 48 | **`Helvetica-Bold` 40px `#000000`** |
| Mode tab track | 1001 | 345 | 198 × 32 | `#E6ECF6`, r16 |
| Mode tab active pill | 1003 | 347 | 96 × 28 | `#FFFFFF`, r15 |
| `日常办公` (active) | 1036 | 352 | 48 × 17 | 12px `Alibaba-PuHuiTi-M` w500 `#333333` |
| `代码开发` | 1135 | 352 | 48 × 17 | 12px `Alibaba-PuHuiTi-R` `#333333`, `opacity: 0.7` |
| Tab icons | 1016 / 1115 | 353 | 16 × 16 | calendar glyphs |
| **Recommendation tag row** | 620 | 417 | 9 pills, each **80 × 28** | `border: 1px solid #CDDDE5` (no fill), `border-radius: 16px` |
| Tag label | +16 | 420 | 48 × 22 | 12px/22 `Alibaba-PuHuiTi-R` `#737373`, centered |
| **Input box** | 620 | 453 | **960 × 148** | `#FFFFFF`, `border: 1px solid #D9D9D9`, `border-radius: 20px`, `box-shadow: 0 1px 8px 0 rgba(13,139,211,0.15)` |
| Input placeholder | 636 | 473 | 326 × 22 | 14px/22 `Alibaba-PuHuiTi-R` `#999999` |
| Attach `+` icon | 641 | 562 | 20 × 20 | glyph fill `#31517A` |
| **Send button** | 1532 | 553 | **32 × 32** | `#333333`, `border-radius: 20px` |
| Send arrow glyph | 1541 | 561 | 13.14 × 16 | `#FFFFFF` |

Tag row x positions: `620, 704, 788, 872, 956, 1040, 1124, 1208, 1292`
→ **stride 84, gap 4px** for an 80px-wide pill.
Verbatim tag labels: `预定会议`, `会议记录`, `生成周报`, `文档处理`, `会议记录`,
`生成周报`, `文档处理`, `会议记录`, `生成周报` (spec repeats placeholders).
There is also a decorative robot image at (1389, 373) 216 × 216.

### 5.5 Chat page (ab2)

| Element | x | y | w × h | Style |
|---|---|---|---|---|
| Topbar bar | 281 | 8 | 1639 × 40 | `rgba(255,255,255,0.30)` |
| Conversation title | 305 | 19 | 142 × 18 | 12px/18 `Alibaba-PuHuiTi-M` w500 `#4D4D4D` |
| Title chip | 310 | 12 | 142 × 32 | `#BDE5FF` at `opacity: 0` |
| `全部文件` control | 1764 | 19 | 48 × 18 | 12px/18 `Alibaba-PuHuiTi-R` `#737373`; icon 16×16 at (1744, 20) |
| `对话设置` control | 1848 | 19 | 48 × 18 | same; icon group at (1828, 14) |
| Banner bar | 281 | 48 | 1639 × 40 | `rgba(223,233,239,0.40)` |
| Banner text | 305 | 60 | 730 × 17 | 12px `Alibaba-PuHuiTi-R` `#737373` |
| Banner chevron / close | 1847 / 1879 | 60 | 16 × 16 | `#737373` |
| **AI avatar** | 589 | 198 / 301 / 477 | **40 × 40** | `#FFFFFF`, `border-radius: 56px` |
| Agent name `场景辅助专家` | 644–645 | 198 / 301 / 477 | 71 × 18 | 12px/18 `Alibaba-PuHuiTi-R` `#737373` |
| Timestamp `11:24` | 722–724 | same | 31 × 18 | 12px/18 `Alibaba-PuHuiTi-R` `#737373` |
| **AI message body** | 644 | 225 / 503 | 961–964 wide | 12px/22 or 12px/24 `Alibaba-PuHuiTi-R` `#333333` |
| Inline link | 1396 | 247 | 70 × 22 | 12px/22 `#1993FF` |
| Action icon row | 648 | 539 | 135 × 24 | icons 16×16 at x = 648, 690, 722, 767; dividers `1 × 15` at x = 674, 754, `#D9D9D9` |
| `您还可以这样问：` | 645 | 579 | 95 × 17 | 12px `Alibaba-PuHuiTi-R` `#333333` |
| **Follow-up pill 1** | 645 | 604 | 215 × 32 | `border: 1px solid #CDDDE5`, `border-radius: 16px`, no fill |
| Follow-up pill 2 | 645 | 644 | 260 × 32 | same; **40px stride** |
| Follow-up pill 3 | 645 | 684 | 322 × 32 | same |
| Pill label | +12 | +7 | — | 12px `Alibaba-PuHuiTi-R` `#737373`; arrow icon 16×16 at the right edge |
| **User bubble 1** | 1529 | 126 | **80 × 40** | `#53AEFF`, `border-radius: 8px`; label `小区克隆` 12px/18 `#FFFFFF` |
| User meta `我` / `11:24` | 1558 / 1578 | 104 | 12 / 31 × 18 | 12px/18 `#737373`, right-aligned above the bubble |
| **User bubble 2** | 674 | 405 | **935 × 40** | `#53AEFF`, `border-radius: 8px` (styleName notes 按钮禁用色) |
| **Chat input box** | 619 | 916 | **960 × 130** | `#FFFFFF`, `border: 1px solid #D9D9D9`, `border-radius: 20px`, `box-shadow: 0 1px 1px 0 rgba(13,139,211,0.15)` |
| Input placeholder | 635 | 931 | 326 × 22 | 14px/22 `#999999` |
| Send button | 1531 | 998 | 32 × 32 | r20 `#333333` |

Message column spans **x = 589 → 1608**; user bubbles right-align at x = 1608.

---

## 6. The expert card — full internal geometry

Card box: **252 × 134**, `background: #FFFFFF`, `border: 1px solid #DCE8EA`,
`border-radius: 12px`.

All offsets below are **relative to the card's top-left corner** (absolute origin
taken from the first card at `1644, 108`).

| Part | Δx | Δy | w × h | Spec | Style |
|---|---|---|---|---|---|
| Avatar (image slice) | **16** | **12** | 32.8 × 32 | `01-…/01-Agent头像/40px-全屏聊天区/…` | bitmap, no radius applied in spec — *(inferred)* circular |
| **Name** | **60** | **9** | e.g. 71 × 22 | 12px / lh 22 / `Alibaba-PuHuiTi-M` w500 / `#333333` | `02-s12/01-标题/二级标题14Bold-Left（卡片&表头）` |
| **Author / uploader** | **60** | **31** | e.g. 40 × 14 | 10px / lh auto / `Alibaba-PuHuiTi-R` w400 / `#4D4D4D` | — |
| **Description** | **16** | **59** | **227 × 32** | 10px / lh 16 / `Alibaba-PuHuiTi-R` / `#4D4D4D` / left | 2 lines of text |
| **Tag row** | **16** | **99** (box) / **100** (rect) | 3 tags, each **50 × 18** | gap **4px** (stride 54) | `Plx:04-Tag标签组件/h16/gray灰色标签` |
| └ Tag background | 0 | +1 | 50 × 18 | `#EEEEEE`, `border-radius: 3px` | `辅助色/灰色/Gray-3(#eeeeee)` |
| └ Tag label | +5 | 0 | 40 × 18 | 10px / lh 18 / `Alibaba-PuHuiTi-R` / `#4D4D4D` / center | `02-Body正文/Center/Body正文-s` |

**Derived padding:** left **16px**, top **12px**. The description block is 227 wide
(≈ 243 from the left edge to the card's right inner edge minus 9px) — treat the
description max-width as **227px, clamped to 2 lines** (32px at 16px line-height).
Right padding is not consistent across children, so **use 16px left/right and let the
description clamp at 2 lines** *(inferred)*.

**Vertical rhythm inside the card:**

```
y = 0    card top
y = 9    name line box top (height 22)  ┐
y = 31   author line top (height 14)    ┘ stack is centred against the 32px avatar (avatar 12→44)
y = 59   description top (2 × 16 = 32 tall) → ends at 91
y = 100  tag row rect top (18 tall) → ends at 118
y = 134  card bottom
```

**Space below the tag row = 134 − 118 = 16px.** Gap between the description bottom
(91) and the tag row top (100) = **9px**.

### 6.1 Card states found in the spec

**Default** (27 of 28 cards):
```css
background: #FFFFFF;
border: 1px solid #DCE8EA;
border-radius: 12px;
```

**Selected** (1 card, ab1, at x=1108 y=258):
```css
background-image: linear-gradient(151deg, rgba(216,240,255,0.20) 35%, rgba(239,191,255,0.20) 100%);
border: 1px solid #1993FF;
box-shadow: 0 1px 16px 0 rgba(0,0,0,0.15);
border-radius: 12px;
```

### 6.2 Verbatim card content (as drawn in the spec)

Card titles: `高级开发工程师`, `全栈开发专家`, `战略咨询合伙人`, `嵌入式固件工程师`,
`工作台搭建师`, `资讯速递专家`
Author sub-lines: `吴量`, `信息AI专家`, `战略咨询顾问`, `固件通`, `小台`, `数字生命`
Description (identical on all 28 cards):
`10年以上全栈经验，精通多种语言和框架，以严谨的工程纪律交付可运行的高质量代码`
Tags (identical on all 28 cards): `全栈开发`, `架构设计`, `代码质量`

---

## 7. Exact UI strings (verbatim, character-for-character)

### 7.1 Sidebar nav labels — **the important one**

The label is:

```
Agent开发. 评估
```

**Byte-exact verification** (`xxd` of the raw file, and `ord()` of the parsed JSON
`content` field — both agree):

```
41 67 65 6e 74 e5 bc 80 e5 8f 91 2e 20 e8 af 84 e4 bc b0
A  g  e  n  t  开       发        .  ␠  评       估
```

- `2E` = **U+002E LATIN SMALL LETTER FULL STOP** — it is a **plain ASCII period**, NOT
  `。` (U+3002, UTF-8 `E3 80 82`) and NOT `．` (U+FF0E, UTF-8 `EF BC 8E`).
- `20` = **U+0020 SPACE** — a **single regular ASCII space** follows it.
- The `content` string is exactly `'Agent开发. 评估'` (11 code points).

There is **no slash** anywhere in this label.

### 7.2 All sidebar strings

| Role | Verbatim |
|---|---|
| Wordmark | `Co-Sight Harness` |
| Subtitle | `您的全天候个人秘书` |
| New chat | `新建对话` |
| Nav 1 | `专家` |
| Nav 2 | `Agent开发. 评估` |
| Nav 3 | `知识库` |
| Nav 4 | `观测` |
| Section label | `历史会话` |
| History items | `生成可追溯性机制`, `SDR和ITBBU的区别`, `故障处理的方法有哪些`, `全网弱覆盖情况`, `全网重叠覆盖情况` |
| User row | `User name` |

### 7.3 Expert page (ab1)

| Role | Verbatim |
|---|---|
| Page title | `专家` |
| Filter tabs | `全部`, `最热`, `最新` |
| Search placeholder | `搜索` |
| Card titles | see §6.2 |
| Tags | `全栈开发`, `架构设计`, `代码质量` |

### 7.4 Home page (ab0)

| Role | Verbatim |
|---|---|
| Hero | `Co-Sight Harness` |
| Mode tabs | `日常办公`, `代码开发` |
| Recommendation tags | `预定会议`, `会议记录`, `生成周报`, `文档处理`, `会议记录`, `生成周报`, `文档处理`, `会议记录`, `生成周报` |
| Input placeholder | `今天帮你做些什么？ @引用对话文件/调用技能与指令` |
| AI disclaimer | `内容由AI生成，仅供参考` |

### 7.5 Chat page (ab2)

| Role | Verbatim |
|---|---|
| Conversation title | `张江地区执行小区克隆查询` |
| Topbar controls | `全部文件`, `对话设置` |
| Banner | `以下是您即将执行的小区克隆相关信息：源小区：网元名称(10001)-小区名称(171）克隆小区：网元名称(10001)-小区名称(172）制式：NR` |
| Agent name | `场景辅助专家` |
| User label | `我` |
| Timestamp | `11:24` |
| User bubble | `小区克隆` |
| AI message (long) | `非常抱歉，由于未能识别到源小区和克隆小区的网元及小区信息，无法确定相关对象。请重新描述您的需求，例如：1）同网元克隆：基于网元115416的171小区，克隆172、173小区。2）跨网元克隆：基于网元115416的171小区，克隆网元124738的172、173小区和网元123567的173、174、175小区。或请明确指定源网元：已选网元(12)，目标网元：` |
| Inline link | `已选网元(12)` |
| Follow-up prompt | `您还可以这样问：` |
| Follow-up pills | `可以帮我生成以下方案创建流程`, `给我生成更详细更具体的内容的解决方案？`, `能否给我生成一个区别于现有方案的其他类型的方案？` |

> Note the banner and message strings contain **mixed full-width and half-width
> parentheses**: `小区名称(171）` — the opening bracket is ASCII `(` (U+0028) but the
> closing is full-width `）` (U+FF09). Reproduce as-is or normalise deliberately.

---

## 8. What the spec does NOT contain (MISSING — do not invent values)

These are things a production token file normally needs that **this spec simply does
not specify**. Each was verified by exhaustive search of the JSON (all `fill`, `border`,
`css`, `styleName`, `name`, and text content), not by spot-checking.

### 8.1 ❗ No interaction states whatsoever

A case-insensitive search for `hover`, `active`, `disabled`, `focus` and `pressed`
anywhere in the entire document returns **zero hits** in design content. The only
matches for `switch` / `toggle` are **MeaXure's own plugin UI localisation strings**
(`"Unit switch": "切换单位"`, `"Toggle Hidden": "切换可见"`) bundled inside the export —
they are not part of the design.

**Concretely, the spec provides NONE of:**

- ❌ hover states (for nav items, cards, tags, tabs, buttons, links, history items)
- ❌ active / pressed states
- ❌ focus rings or focus-visible styles
- ❌ a disabled state for any real control
- ❌ **button variants** — there are no `btn/primary`, `btn/secondary` or `btn/ghost`
  styles. The only button-ish style names are `06-线面/11-场景推荐按钮`
  (border `#CDDDE5`, radius 16px) and `生成对话操作图标按钮` (chat action icons).
  There is **no primary/secondary/ghost button system in this spec.**
- ❌ any toggle / switch / checkbox / radio control
- ❌ transitions or animation/easing tokens (no `transition`, no `cubic-bezier`, no durations)
- ❌ loading, empty, or error states
- ❌ scrollbar styling

> The one near-miss: a style named `基准色/蓝色/Blue-2(按钮禁用色)` exists, but it is
> applied to a **935 × 40 user chat bubble**, not to a button. It is not a disabled-button token.

### 8.2 Other gaps

| Missing | Detail |
|---|---|
| **Font files / URLs** | Only family names are given (`Alibaba-PuHuiTi-R/M`, `Helvetica-Bold`, `PingFangTC-Regular`). No `@font-face`, no weights-to-files mapping, no licence info. |
| **Sidebar background** | There is no background rect covering x = 0…280. The sidebar colour comes from the artboard canvas. No token for it. |
| **Page / app background** | No canvas background layer exists for the area outside the main panel. |
| **Colour semantic names** | Colours have Sketch-style names (`Gray-3`, `Blue-2`, `Navy-1`, `Gray-6`, `Gray-8`) but only for the layers that use them. There is no authoritative role mapping (e.g. nothing named `text/primary` or `border/default`). The 5-entry document palette is incomplete relative to the ~16 fills actually used. |
| **Spacing scale** | No named spacing tokens. Only the literal geometry in §5. |
| **Typography scale names** | Style names exist (`02-Body正文/…`, `04-Tip提示&XY轴/…`) but they are Sketch library paths, not a documented scale, and at least one is mislabelled (`二级标题14Bold` is 12px/500). |
| **Icon inventory** | 16 × 16 is the dominant icon size, but icons are Sketch symbols with no exported SVG/icon-font assets here. Sizes observed: 16×16 (dominant), 20×20 (`16px/01通用/new` renders 20×20), 24×24 (avatar), 40×40 (avatar). |
| **Breakpoints / responsive rules** | All 3 artboards are fixed at exactly **1920 × 1080**. There are no mobile/tablet artboards and no responsive constraints. |
| **Dark theme** | None. Light only. |
| **Z-index / layering scale** | Not encoded. |
| **Long-text behaviour** | The card description is drawn as 2 lines in a 227 × 32 box, but the spec states no explicit `-webkit-line-clamp` or overflow rule. *(inferred: clamp to 2 lines, ellipsis)* |
| **Avatar radius on the card** | The card avatar is an image **slice** with no `radius` field, while chat avatars carry `border-radius: 56px`. *(inferred: card avatars are also circular)* |
| **Grid column behaviour** | 6 × 252px cards at 1920px wide with 16px gaps. The spec shows no rule for fewer/more columns at other widths, and card 29/30 are absent from the last row. |
| **Numeric token for the `opacity: 0.7` / `0.1` values** | Inactive tab labels use `opacity: 0.7`; the selected history highlight uses `opacity: 0.1`. These are not named tokens. |

---

## 9. Quick reference — CSS custom properties

```css
:root {
  /* ---- colour: surfaces ---- */
  --color-panel:            rgba(255, 255, 255, 0.85); /* main content panel */
  --color-surface:          #FFFFFF;                    /* cards, input, pill, search */
  --color-surface-tint:     #E6ECF6;                    /* segmented tab track */
  --color-tag-bg:           #EEEEEE;                    /* Gray-3 */
  --color-topbar:           rgba(255, 255, 255, 0.30);  /* chat topbar */
  --color-banner:           rgba(223, 233, 239, 0.40);  /* chat banner */

  /* ---- colour: brand / accent ---- */
  --color-primary:          #1993FF;                    /* selected border, link, highlight */
  --color-primary-bubble:   #53AEFF;                    /* Blue-2 — user chat bubble */
  --color-primary-soft:     #BDE5FF;                    /* Blue-2 chip */
  --color-send-bg:          #333333;

  /* ---- colour: borders (4 neutral + accents) ---- */
  --border-card:            #DCE8EA;
  --border-reco:            #CDDDE5;
  --border-panel:           #D9D9D9;
  --border-sidebar:         #D7E0E5;
  --border-selected:        #1993FF;

  /* ---- colour: text ---- */
  --text-body:              #4D4D4D;
  --text-heading:           #333333;
  --text-secondary:         #737373;
  --text-placeholder:       #999999;
  --text-on-brand:          #FFFFFF;
  --text-wordmark:          #000000;

  /* ---- typography ---- */
  --font-sans:   Alibaba-PuHuiTi-R, "Alibaba PuHuiTi", sans-serif;
  --font-medium: Alibaba-PuHuiTi-M, "Alibaba PuHuiTi", sans-serif;
  --font-brand:  Helvetica-Bold, Helvetica, sans-serif;
  --font-tc:     PingFangTC-Regular, "PingFang TC", sans-serif;

  --fs-10: 10px;   --lh-10: 18px;   /* tag, card author */
  --fs-10-desc: 10px; --lh-10-desc: 16px; /* card description */
  --fs-12: 12px;   --lh-12: 18px;   /* labels, chat, buttons */
  --fs-12-body: 12px; --lh-12-body: 22px; /* card title, AI body */
  --fs-14: 14px;   --lh-14: 18px;   /* nav, history */
  --fs-14-input: 14px; --lh-14-input: 22px; /* placeholder */
  --fs-16: 16px;   /* page title */
  --fs-18: 18px;   /* sidebar wordmark */
  --fs-40: 40px;   /* hero wordmark */

  --ls-none: 0;

  /* ---- radii ---- */
  --r-xs:  3px;    /* tag chip, search box */
  --r-sm:  8px;    /* chat bubble, history highlight */
  --r-md:  10px;   /* sidebar item pill */
  --r-card: 12px;  /* expert card */
  --r-pill: 15px;  /* segmented active pill */
  --r-lg:  16px;   /* tab track, recommendation tag */
  --r-xl:  20px;   /* input box, send button */
  --r-full: 56px;  /* avatar */
  --r-panel: 12px 0 0 12px;

  /* ---- elevation ---- */
  --shadow-item:    0 1px 3px 0 rgba(0, 0, 0, 0.15);
  --shadow-input:   0 1px 8px 0 rgba(13, 139, 211, 0.15);
  --shadow-input-chat: 0 1px 1px 0 rgba(13, 139, 211, 0.15);
  --shadow-card-selected: 0 1px 16px 0 rgba(0, 0, 0, 0.15);

  /* ---- layout ---- */
  --sidebar-w:            280px;
  --panel-w:              1640px;
  --content-padding-x:    24px;
  --nav-item-w:           248px;
  --nav-item-h:           40px;
  --nav-icon:             16px;
  --card-w:               252px;
  --card-h:               134px;
  --grid-gap:             16px;   /* both axes */
  --grid-cols:            6;
  --input-h-home:         148px;
  --input-h-chat:         130px;
  --send-btn:             32px;
}
```

---

## 10. Method notes

- The spec file is minified into 19 lines; the mock data lives entirely in line 15 as
  `let data = {…}`. It was extracted by brace-matching (string-aware) and parsed with
  `json.loads`, giving a 402 KB structured object.
- Frequencies were computed by walking every layer of all 3 artboards recursively
  (746 layers total) and tallying `fills[].color.color-hex`, `borders[]`, `radius`,
  `shadows[]`, and the text properties.
- The `css: []` array MeaXure emits is convenient but **not always present** (some
  layers have only `fills`/`borders`), so token extraction reads the structured fields
  first and uses `css[]` only for verbatim string checks (font-family, box-shadow).
- The nav-label codepoint check was done twice, independently: `ord()` over the parsed
  JSON `content`, and `xxd` over the raw bytes in the source HTML. Both give `2E 20`.

---

## 11. Implementation deltas — where the code differs from this spec

**Sections 1–10 above are the spec, extracted verbatim.** This section is the only place
in this file that records where the implementation deliberately departs from it, so §9's
"quick reference" is not mistaken for what `tokens.css` actually contains.

The implementation's source of truth is `framework/web/src/styles/tokens.css`; each block
there is tagged `[稿]` (copied from this spec) / `[推]` (derived in the spec's style) /
`[增]` (a capability the spec does not have). Anything not listed below is `[稿]`.

| Token / item | Spec (§9) | Implementation | Why |
|---|---|---|---|
| `--card-h` | 134px | **166px** | §6's budget leaves only 16px below the tag row, and the permanent action bar (D17=A) needs 8px padding + 24px buttons. |
| `--grid-cols` | 6 | **4** | 需求 UX-3.1「每行建议放置四个卡片」. The spec's 6 is a 1920-wide artboard; the frame is used from about 1280 up. |
| `--sidebar-w` | 280px | **removed** | The sidebar is draggable (需求 UX-2), so a fixed token would be a second source of truth. Range lives in `src/lib/sidebarWidth.ts` (min 264 / default 280 / max 420; 264–420 taken from deepseek-harness `SIDEBAR_MIN`/`SIDEBAR_MAX`). |
| `--nav-item-w` | 248px | **removed** | Nav / history / user rows are fluid (`width: 100%`). 248 = 280 − 2×16 is only correct at the default sidebar width and broke at every other one. |
| `--shadow-card-hover` | — | **added** | 需求 UX-3.4. A *new* token rather than a reuse of `--shadow-card-selected`: the 6px downward offset reads as "raised", while the selected shadow is a 16px all-round halo — reusing it would make hover and selected indistinguishable. |
| `--color-tag-blue/teal/green/purple/amber/rose` | — | **added** | 需求 UX-3.6 (tags need not all be grey). Assigned **by tag text**, so a tag keeps its colour across filters, sorts and pages. Backgrounds only; the label stays `--text-body`, which is what §2.4's contrast was measured against. The original assignment lived in `src/features/experts/tagTone.ts`, deleted together with the native experts page (D44); the six tokens stay — `Tag` still uses them. |
| Card action bar styling | — | **added** | Bordered buttons with a blue label, separated from the content above by `1px --border-card` (需求 UX-3.3). The spec has the buttons inside the card with no border and no separator. |
| `--color-primary-text` | — | **added** (`#0a66c2`) | The action-bar label needs "blue = clickable" (需求 UX-3.3), but §4's `--color-primary` `#1993ff` measures **3.15:1** on white (2.89 hovered, 2.71 pressed) — below the 4.5:1 that 12px body text requires. It is a *non-text* colour in the spec (borders, icons, selected-history fill — 3:1 is enough there), so the spec is not wrong; we were. Same hue, darker: 5.69 / 5.21 / 4.89. The darkest-but-lightest passing step — `#0b6fd1` drops to 4.29 on the pressed fill. Guarded by `tests/token-contrast.test.ts`. |
| `--color-hover` / `--color-active` | — | **added** | §8.1 — the spec contains **no** interaction states. |
| Sidebar toggle icon | — | `panelLeft` | 需求 UX-1「和 deepseek-harness 的收起侧边栏图标保持一致」. dsh draws the same artwork in all three states (`ui-primitives/src/icons/index.tsx:81`), so the icon deliberately does **not** change between expanded and collapsed. |

Card 3.2 (§6) is also affected: the spec puts the author line hard against the card's left
edge, while the implementation puts name and author in one column to the right of the
avatar (需求 UX-3.2) so that the author reads as belonging to the name above it.
