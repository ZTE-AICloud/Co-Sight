// @vitest-environment jsdom
// ↑ 只有这个 spec 需要 DOM：DOMPurify 在没有 window 的环境里是**空壳**（`sanitize`
//   为 undefined），XSS 用例就测不成了。全局配置仍是 `environment: 'node'`，
//   这里按文件覆盖。
import { FORBIDDEN_HTML_TAGS, renderMarkdown } from '@/features/chat/lib/markdown'

// 测的是 `chat/lib/markdown.ts`。分两组：
//  ① 消毒（安全）—— 断言**危险构造不存在**，而不是断言整段 HTML 相等
//     （整段相等会随 marked/DOMPurify 版本漂移，噪音太大）；
//  ② 渲染（功能）—— 正常 markdown 必须能渲染出来，防止「消毒把正文也干掉了」。
describe('renderMarkdown', () => {
  describe('given_恶意输入_when_渲染_then_消毒后不含可执行内容', () => {
    it('<img onerror> 被整段拦掉（FORBID_TAGS 禁 img，见模块头注释）', () => {
      // Act
      const html = renderMarkdown('<img src=x onerror="alert(1)">')

      // Assert
      expect(html).not.toContain('<img')
      expect(html).not.toContain('onerror')
      expect(html).not.toContain('alert(1)')
    })

    it('markdown 图片语法同样产不出 <img>', () => {
      // Act
      const html = renderMarkdown('![x](https://evil.example/beacon.png)')

      // Assert：img 在禁用表里，从「检索到的文档正文」带进来的外部信标加载即上报
      expect(html).not.toContain('<img')
    })

    it('<script> 被剥掉', () => {
      // Act
      const html = renderMarkdown('正常正文<script>alert(1)</script>再看这里')

      // Assert
      expect(html).not.toContain('<script')
      expect(html).not.toContain('alert(1)')
      expect(html).toContain('正常正文')
    })

    it('<svg> 元素被 FORBID_TAGS 剥掉（含 onload 属性那种）', () => {
      // Arrange：markdown 本身不产出 svg，但「检索到的文档正文」可以带进来
      const html = renderMarkdown('<svg width="10" onload="alert(1)"></svg>正文甲')

      // Assert
      expect(html).not.toContain('<svg')
      expect(html).not.toContain('onload')
      // 元素被摘掉，但**元素外面的正文不能跟着消失**
      expect(html).toContain('正文甲')
    })

    it('未闭合的原始 <svg> 不会把后面的正文吞进 svg 元素里', () => {
      // Arrange：实测过一条 `<svg/onload=…>` 能让答案后半截消失，所以 svg 进禁用清单。
      // marked 对这条（属性不带引号）会转义成文本，转义后是惰性文本，这里只钉**安全性**
      // —— 不管走 marked 转义还是 DOMPurify 剥离，结果都不能是可执行元素。
      const html = renderMarkdown('<svg/onload=alert(1)>后面的正文')

      // Assert
      expect(html).not.toContain('<svg')
      expect(html).toContain('后面的正文')
    })

    it('javascript: 链接被剥掉 href', () => {
      // Act
      const html = renderMarkdown('[点我](javascript:alert(1))')

      // Assert
      expect(html).not.toContain('javascript:')
      expect(html).not.toContain('href="javascript')
      // 链接文字还在（只是不可点），正文不该整段消失
      expect(html).toContain('点我')
    })

    it('允许标签上的 on* 事件属性被剥掉', () => {
      // Act
      const html = renderMarkdown('<p onclick="alert(1)">hi</p>')

      // Assert
      expect(html).not.toContain('onclick')
      expect(html).toContain('hi')
    })

    it('FORBIDDEN_HTML_TAGS 覆盖住被禁的那批标签', () => {
      // Assert：清单本身就是契约，缩水了上面几条就会漏
      expect(FORBIDDEN_HTML_TAGS).toEqual(
        expect.arrayContaining(['img', 'svg', 'math', 'style', 'form', 'input', 'button', 'video', 'audio'])
      )
    })

    it('禁用标签逐个验证：渲染出来一个都不留', () => {
      // Arrange：每个标签单独喂，断言它没出现在结果里
      FORBIDDEN_HTML_TAGS.forEach(tag => {
        // Act
        const html = renderMarkdown(`<${tag}></${tag}>`)
        // Assert
        expect(html.toLowerCase()).not.toContain(`<${tag}`)
      })
    })
  })

  describe('given_正常 markdown_when_渲染_then_该有的结构都在', () => {
    it('粗体渲染成 <strong>（并确认正文里没有裸星号）', () => {
      // Act
      const html = renderMarkdown('这是**加粗**文字')

      // Assert
      expect(html).toContain('<strong>加粗</strong>')
      expect(html).not.toContain('**')
    })

    it('无序列表渲染成 <ul><li>', () => {
      // Act
      const html = renderMarkdown('- 第一项\n- 第二项')

      // Assert
      expect(html).toContain('<ul>')
      expect(html).toContain('<li>第一项</li>')
      expect(html).toContain('<li>第二项</li>')
    })

    it('围栏代码块渲染成 <pre><code>', () => {
      // Act
      const html = renderMarkdown('```js\nconst a = 1\n```')

      // Assert
      expect(html).toContain('<pre>')
      expect(html).toContain('<code')
      expect(html).toContain('const a = 1')
    })

    it('表格（gfm）渲染成 <table>', () => {
      // Act
      const html = renderMarkdown('| 列A | 列B |\n| --- | --- |\n| 1 | 2 |')

      // Assert
      expect(html).toContain('<table>')
      expect(html).toContain('<th>列A</th>')
      expect(html).toContain('<td>1</td>')
    })

    it('单个换行即换行（breaks）渲染成 <br>', () => {
      // Act
      const html = renderMarkdown('第一行\n第二行')

      // Assert：用户 Shift+Enter 的换行与模型逐行排的要点都不带空行
      expect(html).toContain('<br>')
    })

    it('普通 http(s) 链接与正文 HTML 保留', () => {
      // Act
      const html = renderMarkdown('[文档](https://example.com/doc)')

      // Assert
      expect(html).toContain('href="https://example.com/doc"')
      expect(html).toContain('文档')
    })

    it('空值返回空串（模板里靠它决定走 v-html 还是纯文本兜底）', () => {
      // Act & Assert
      expect(renderMarkdown('')).toBe('')
      expect(renderMarkdown(null)).toBe('')
      expect(renderMarkdown(undefined)).toBe('')
    })
  })
})
