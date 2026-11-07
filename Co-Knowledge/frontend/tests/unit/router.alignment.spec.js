// @vitest-environment jsdom
// 路由契约：路径、路由名、参数名在这里逐条登记。
//
// 这是「URL 契约」的钉子：登记的路径、路由名、参数名，这里逐条比对。
// 之所以单独一份 spec：路由表被改错时页面往往还能渲染（只是地址变了/旧链接失效），
// 没有断言的话只会在书签、外部文档和 E2E 深链里静默回归。

// router.js 的依赖链会在导入期读 localStorage（constants → i18n），
// jsdom 环境有 localStorage，但 i18n 模块仍会读语言；按路由相关 spec 的既有做法
// 用真实词条替身，避免把整套 zh/en 消息灌进每个断言。
vi.mock('@/app/i18n/i18n.js', async () => {
  const { createI18n } = await import('vue-i18n')
  const zh = (await import('@/app/i18n/zh.js')).default
  const en = (await import('@/app/i18n/en.js')).default
  const i18n = createI18n({ legacy: false, locale: 'zh', messages: { zh, en } })
  const translate = (key, values) => i18n.global.t(key, values)
  return { default: i18n, translate, $t: translate, isGlobalZh: true }
})

import routes_out from '@/app/router'

const flatten = routes =>
  routes.flatMap(route => [route, ...flatten(route.children || [])])

const ALL = flatten(routes_out)

function byName (name) {
  const record = ALL.find(route => route.name === name)
  expect(record, `缺路由名：${name}`).toBeTruthy()
  return record
}

describe('路由与 UX 原型对齐（路径 + 路由名 + 参数名）', () => {
  it.each([
    // [路由名, 期望路径]
    ['login', '/login'],
    ['knowledge', '/knowledge'],
    ['knowledge-detail', '/knowledge/detail/:id'],
    ['knowledge-documents', '/knowledge/detail/:id/documents'],
    ['graph', '/graph'],
    ['graph-detail', '/graph/detail/:id'],
    ['graph-edit', '/graph/edit/:id'],
    ['flow', '/flow'],
    ['flow-detail', '/flow/detail/:id'],
    ['chat', '/chat'],
    ['operators', '/operators'],
    ['models', '/models'],
    ['access', '/access'],
    ['keys', '/keys']
  ])('%s → %s', (name, path) => {
    expect(byName(name).path).toBe(path)
  })

  it('不再注册任何旧地址兼容记录（含旧前缀与原型旧别名）', () => {
    // 旧地址全部移除，不做兼容。旧地址只走全局兜底。
    const legacyPaths = [
      '/kb',
      '/kb/knowledgeDetail/:id',
      '/kb/knowledgeDetail/:id/documents',
      '/kb/knowledgeGraph',
      '/kb/knowledgeGraphDetail/:id',
      '/kb/editKnowledgeGraph/:id',
      '/kb/createKnowledgeGraph',
      '/kb/createGraphTemplate/:templateId',
      '/extendedManagement',
      '/model',
      '/remoteAccess',
      '/remoteAccess/guide',
      '/remoteAccess/keys',
      '/docKnowledgeLibrary',
      '/docLibrary',
      '/docKnowledgeLibrary/create'
    ]
    const registered = new Set(ALL.map(route => route.path))
    expect(legacyPaths.filter(path => registered.has(path))).toEqual([])
    expect(byName('graph-detail').alias).toBeUndefined()
    expect(ALL.some(route => route.path === '/remoteAccess')).toBe(false)
  })

  it('远程接入两条路由共用 AgentLayout（不再挂 /remoteAccess 父路径）', () => {
    // /access 与 /keys 是两条独立页面，但共用 AgentLayout
    // （面包屑/标题/状态只取一次），由布局按 route.name 渲染对应子页。
    expect(byName('access').component).toBe(byName('keys').component)
  })

  it('首页与未知地址的落点与原型一致', () => {
    // / → /login；此外保留全局兜底（没有 pathMatch 记录），
    // 兜底落在文档知识库列表。
    expect(routes_out[0].redirect).toEqual({ name: 'login' })
    const fallback = routes_out[0].children.find(route => route.path === '/:pathMatch(.*)*')
    // 函数形式：旧地址上的 query（如 ?tab=knowledgeGraph）不得被带进兜底页
    expect(fallback.redirect({ query: { tab: 'knowledgeGraph' } })).toEqual({
      name: 'knowledge',
      query: {}
    })
  })

  it('没有遗留的参数名 :kbId/:appId（原型统一用 :id）', () => {
    const offenders = ALL
      .filter(route => typeof route.path === 'string' && /:kbId|:appId/.test(route.path))
      .map(route => route.path)

    expect(offenders).toEqual([])
  })
})
