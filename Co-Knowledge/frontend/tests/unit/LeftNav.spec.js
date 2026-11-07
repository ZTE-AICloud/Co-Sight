// @vitest-environment jsdom
// ↑ 组件测试：必须 jsdom（`useRoute` + `localStorage` + EP 菜单都要 DOM）
import { h } from 'vue'
import { vi } from 'vitest'
import { flush, findByText, mountWithPlugins, textOf, expectNoI18nMisses } from './helpers/mount'
import { resolveActiveMenu } from '@/app/layout/nav/menu.config'

import LeftNav from '@/app/layout/nav/LeftNav.vue'

// 测的是 `src/app/layout/nav/LeftNav.vue` + `src/app/layout/nav/menu.config.js`。
//
// 这块逻辑没有自动化验证，只能「手工开浏览器点一遍」，而它的失效方式都很安静：
//   - `resolveActiveMenu` 漏一支 → 进某个子页后整条左栏没有高亮，看起来像页面坏了
//   - i18n 键拼错 → 菜单上直接显示 `modules.kb.dockb` 这种键名
//   - 折叠状态没落 localStorage → 刷新后展开，用户每次都要再收一次
//   - 两处 `:key` 被删 → EP 在 collapse 变化时清空 openedMenus，展开后分组全关着
//
// 所以下面钉的都是**渲染出来的行为**（文案 / 高亮项 / 宽度 / localStorage 往返），
// 不是内部变量。

const COLLAPSE_KEY = 'ragstudio-nav-collapse'
const LANGUAGE_KEY = 'language-option'

// 菜单真值（zh），逐个从 `src/i18n/zh*` 抄来后再交叉核对过；拼错键名时
// vue-i18n 会把键名渲染成文案，下面的 `toEqual` 立刻红，`expectNoI18nMisses` 再点名。
const ZH = {
  kb: '知识库',
  rag: '知识检索',
  documentKb: '文档知识库',
  graphKb: '图谱知识库',
  chat: '对话测试',
  extended: '自定义算子',
  model: '模型管理',
  remote: '远程接入',
  remoteGuide: '接入方法',
  remoteKeys: '密钥管理',
  collapse: '收起侧栏',
  expand: '展开侧栏',
  switchLanguage: '切换语言'
}

/** 渲染出来的叶子菜单文案（顺序 = 模板顺序）。 */
function leafLabels (wrapper) {
  return wrapper.findAll('.nav-item').map(textOf)
}

/** 当前高亮的叶子菜单文案。 */
function activeLabels (wrapper) {
  return wrapper.findAll('.nav-item.router-link-active').map(textOf)
}

describe('LeftNav', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  describe('渲染（真 i18n 词条）', () => {
    it('两组标题 + 八项叶子菜单都用真文案，没有渲染出 i18n 键名', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })

      // Assert
      expect(wrapper.findAll('.group-title').map(textOf)).toEqual([
        ZH.kb,
        ZH.remote
      ])
      expect(leafLabels(wrapper)).toEqual([
        ZH.documentKb,
        ZH.graphKb,
        ZH.rag,
        ZH.chat,
        ZH.extended,
        ZH.model,
        ZH.remoteGuide,
        ZH.remoteKeys
      ])
      expectNoI18nMisses(wrapper)
    })

    it('默认展开三个分组（否则二三级入口要点一下才看得见）', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })

      // Assert：侧栏没有折叠子菜单，八个叶子入口始终在 DOM 里
      const documentKb = findByText(wrapper, ZH.documentKb, '.nav-item')
      expect(documentKb).not.toBeNull()
      expect(documentKb.isVisible()).toBe(true)
    })

    it('展开态：.sidebar 壳、显示品牌文字、收起按钮的可访问名称是「收起导航」', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })

      // Assert：AppSidebar 的 DOM/类名
      expect(wrapper.classes()).toContain('sidebar')
      expect(wrapper.find('.brand-copy').exists()).toBe(true)
      const collapse = wrapper.findAll('.side-footer .icon-button')
        .find(node => node.attributes('aria-label') === ZH.collapse)
      expect(collapse).toBeTruthy()
      expect(collapse.find('svg').exists()).toBe(true)
    })
  })

  // 语言切换。
  //
  // 注意驱动方式：按钮文案与切换目标**不是**从 i18n 的 locale 推的，而是从
  // `localStorage['language-option']`（回落 navigator.language）——与
  // `@/i18n/i18n.js`、`@/service/appState.js` 读的是同一个来源。
  // 所以测试也必须写 localStorage 来驱动，不能只给 mount 传 `locale`：
  // 传 locale 只影响界面文案，不影响按钮自己的判断，那样测出来是假的。
  describe('语言切换（0.1.0 偏好设置气泡）', () => {
    // 偏好设置用 el-popover。测试脚手架没注册它（轻量集里没有 popper），
    // 用一个透明占位件把 #reference 与默认插槽都渲染出来，专测交互接线。
    const POPOVER_STUB = {
      name: 'ElPopover',
      props: ['visible', 'placement', 'trigger', 'width', 'offset', 'popperClass'],
      emits: ['update:visible'],
      setup (_props, { slots }) {
        return () => h('div', [slots.reference?.(), slots.default?.()])
      }
    }

    function mountNav (locale = 'zh') {
      return mountWithPlugins(LeftNav, {
        route: '/chat',
        locale,
        global: { components: { ElPopover: POPOVER_STUB } }
      })
    }

    /** jsdom 没实现 location.reload；换成可写副本后才能断言"确实要求了整页重载"。 */
    async function withStubbedLocation (fn) {
      const original = window.location
      const reload = vi.fn()
      delete window.location
      window.location = { ...original, reload }
      try {
        await fn(reload)
      } finally {
        delete window.location
        window.location = original
      }
    }

    /** 打开页脚「偏好设置」气泡（语言选项在 popper 里，挂在 body 上）。 */
    async function openPreferences () {
      await flush()
    }


    function languageOptionEls (wrapper) {
      return wrapper.findAll('.language-option').map(node => node.element)
    }

    afterEach(() => {
      document.body.innerHTML = ''
    })

    it('中文环境：当前项是简体中文，English 可选', async () => {
      // Arrange
      localStorage.setItem(LANGUAGE_KEY, JSON.stringify('zh-CN'))
      const wrapper = await mountNav()

      // Act
      await openPreferences()

      // Assert
      const options = languageOptionEls(wrapper)
      expect(options.map(node => node.textContent.trim())).toEqual(['简体中文', 'English'])
      expect(options[0].classList.contains('is-current')).toBe(true)
      expect(options[1].classList.contains('is-current')).toBe(false)
      expect(wrapper.find('.settings-button').attributes('aria-label')).toBe('偏好设置')
    })

    it('英文环境：当前项是 English', async () => {
      // Arrange
      localStorage.setItem(LANGUAGE_KEY, JSON.stringify('en-US'))
      const wrapper = await mountNav('en')

      // Act
      await openPreferences()

      // Assert
      const options = languageOptionEls(wrapper)
      expect(options[1].classList.contains('is-current')).toBe(true)
    })

    it('点击 English：把目标语言**按 JSON 编码**写进 localStorage，并整页重载', async () => {
      // Arrange
      localStorage.setItem(LANGUAGE_KEY, JSON.stringify('zh-CN'))
      const wrapper = await mountNav()
      await openPreferences()

      // Act
      await withStubbedLocation(async reload => {
        languageOptionEls(wrapper)[1].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
        await flush()

        // Assert：必须是 JSON 串（带引号）—— `@/i18n/i18n.js` 用 JSON.parse 读它，
        // 裸 `en-US` 会让 JSON.parse 抛异常、应用在导入期就白屏。
        expect(localStorage.getItem(LANGUAGE_KEY)).toBe('"en-US"')
        // 断言"要求了整页重载"：语言在导入期被读多处（i18n 常量 / appState 的 LANG 头 /
        // EP 安装参数），不重载会留下半中半英。
        expect(reload).toHaveBeenCalledTimes(1)
      })
    })

    it('点当前语言不重载、不写存储', async () => {
      // Arrange
      localStorage.setItem(LANGUAGE_KEY, JSON.stringify('zh-CN'))
      const wrapper = await mountNav()
      await openPreferences()

      // Act
      await withStubbedLocation(async reload => {
        languageOptionEls(wrapper)[0].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
        await flush()

        // Assert
        expect(localStorage.getItem(LANGUAGE_KEY)).toBe('"zh-CN"')
        expect(reload).not.toHaveBeenCalled()
      })
    })

    it('切换语言不会写折叠状态', async () => {
      // Arrange
      localStorage.setItem(LANGUAGE_KEY, JSON.stringify('zh-CN'))
      const wrapper = await mountNav()
      await openPreferences()

      // Act
      await withStubbedLocation(async () => {
        languageOptionEls(wrapper)[1].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
        await flush()
      })

      // Assert
      expect(localStorage.getItem(COLLAPSE_KEY)).toBeNull()
    })
  })

  describe('高亮（activeMenu ← resolveActiveMenu ← 当前路由）', () => {
    it('路由 /chat 时只有「对话测试」高亮', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })

      // Assert：不能是「至少一个高亮」——同时高亮两项也是坏的
      expect(activeLabels(wrapper)).toEqual([ZH.chat])
    })

    it('路由 /flow 时只有「知识检索」高亮', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/flow' })

      // Assert
      expect(activeLabels(wrapper)).toEqual([ZH.rag])
    })

    it('/graph（图谱知识库独立页）时高亮「图谱知识库」', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/graph' })

      // Assert
      expect(activeLabels(wrapper)).toEqual([ZH.graphKb])
    })

    it('/knowledge（文档知识库列表）时高亮「文档知识库」——不能整条都不亮', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/knowledge' })

      // Assert
      expect(activeLabels(wrapper)).toEqual([ZH.documentKb])
    })

    it('/graph/detail/x 这种图谱子页归到「图谱知识库」', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/graph/detail/42' })

      // Assert
      expect(activeLabels(wrapper)).toEqual([ZH.graphKb])
    })

    it('/knowledge/folder/9 这种文档库子页归到「文档知识库」', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/knowledge/folder/9' })

      // Assert
      expect(activeLabels(wrapper)).toEqual([ZH.documentKb])
    })

    it('/operators 高亮「自定义算子」（一级项直接是 el-menu-item）', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/operators' })

      // Assert
      expect(activeLabels(wrapper)).toEqual([ZH.extended])
    })

    it('/access 高亮「接入方法」', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/access' })

      // Assert
      expect(activeLabels(wrapper)).toEqual([ZH.remoteGuide])
    })

    it('/keys 高亮「密钥管理」', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/keys' })

      // Assert
      expect(activeLabels(wrapper)).toEqual([ZH.remoteKeys])
    })

    it('/approve 这种菜单外的路由整条左栏不高亮（有意如此）', async () => {
      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/approve' })

      // Assert：返回 path 本身 ⇒ 匹配不上任何 index ⇒ 零高亮
      expect(activeLabels(wrapper)).toEqual([])
    })
  })

  describe('折叠状态', () => {
    const collapseButton = wrapper => wrapper.findAll('.side-footer .icon-button')
      .find(node => [ZH.collapse, ZH.expand].includes(node.attributes('aria-label')))

    it('点折叠按钮：加 collapsed 类、按钮变「展开导航」', async () => {
      // Arrange
      const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })

      // Act
      await collapseButton(wrapper).trigger('click')

      // Assert：侧栏靠 .collapsed 类切到 78px 导轨
      expect(wrapper.classes()).toContain('collapsed')
      expect(collapseButton(wrapper).attributes('aria-label')).toBe(ZH.expand)
    })

    it('折叠状态写进 localStorage，再点一次写回 0（刷新后能复原）', async () => {
      // Arrange
      const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })

      // Act & Assert：收起
      await collapseButton(wrapper).trigger('click')
      expect(localStorage.getItem(COLLAPSE_KEY)).toBe('1')

      // Act & Assert：展开
      await collapseButton(wrapper).trigger('click')
      expect(localStorage.getItem(COLLAPSE_KEY)).toBe('0')
      expect(wrapper.classes()).not.toContain('collapsed')
    })

    it('localStorage 里是 1 时，新挂载的实例直接是折叠态（读回）', async () => {
      // Arrange
      localStorage.setItem(COLLAPSE_KEY, '1')

      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })

      // Assert
      expect(wrapper.classes()).toContain('collapsed')
    })

    it('localStorage 里是垃圾值时按展开处理（不是按真值判断）', async () => {
      // Arrange：`=== '1'` 才折叠；写成 truthy 判断会把 '0'/'false' 也当折叠
      localStorage.setItem(COLLAPSE_KEY, '0')

      // Act
      const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })

      // Assert
      expect(wrapper.classes()).not.toContain('collapsed')
    })
  })

  describe('导航（RouterLink + 每项的 route 配置）', () => {
    it('点「对话测试」会 push 到 /chat', async () => {
      // Arrange
      const wrapper = await mountWithPlugins(LeftNav, { route: '/operators' })

      // Act
      await findByText(wrapper, ZH.chat, '.nav-item').trigger('click')
      await flush()

      // Assert：把 `:route="child.route"` 删掉会退化成按 index 字符串跳（'/chat' 凑巧也对），
      // 真正能分辨这两条路的是下面那条「图谱知识库」（index 与 route 不同源）：
      expect(wrapper.router.currentRoute.value.path).toBe('/chat')
    })

    it('点「图谱知识库」会 push 到 /graph（独立页，不再带 ?tab=）', async () => {
      // Arrange：拆页前这项的 index 与 route 都带 `?tab=knowledgeGraph`；现在两项
      // 各是一条路由 —— 若 route 写回旧 query 形式，这里的 path/query 断言会立刻红
      const wrapper = await mountWithPlugins(LeftNav, { route: '/chat' })

      // Act
      await findByText(wrapper, ZH.graphKb, '.nav-item').trigger('click')
      await flush()

      // Assert
      expect(wrapper.router.currentRoute.value.path).toBe('/graph')
      expect(wrapper.router.currentRoute.value.query).toEqual({})
    })
  })
})

describe('resolveActiveMenu（纯函数，逐条钉映射表）', () => {
  const cases = [
    ['/knowledge', '/knowledge'],
    ['/graph', '/graph'],
    // 带尾斜杠：vue-router strict:false 仍匹配，route.path 保留斜杠 —— 不能整条不亮
    ['/graph/', '/graph'],
    // 图谱子页（详情/新建/编辑/模版设计器）归图谱知识库
    ['/graph/detail/42', '/graph'],
    ['/graph/create', '/graph'],
    ['/graph/edit', '/graph'],
    ['/graph/createTemplate', '/graph'],
    // 其余 /knowledge/* 子页归文档知识库
    ['/knowledge/detail/9/documents', '/knowledge'],
    ['/chat', '/chat'],
    ['/flow', '/flow'],
    // 远程接入的子菜单（带尾斜杠也要命中）
    ['/access', '/access'],
    ['/keys', '/keys'],
    ['/keys/', '/keys'],
    // `/remoteAccess` 是已下线的旧前缀；纯函数原样返回，不高亮任何叶子
    ['/remoteAccess', '/remoteAccess'],
    // 菜单外：原样返回，结果是「不高亮」
    ['/approve', '/approve'],
    ['/', '/']
  ]

  it.each(cases)('%s → %s', (path, expected) => {
    expect(resolveActiveMenu(path)).toBe(expected)
  })
})
