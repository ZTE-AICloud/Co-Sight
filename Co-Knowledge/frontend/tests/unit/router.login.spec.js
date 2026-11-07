// @vitest-environment jsdom
// 登录路由必须是与 `/` 平级的顶层记录：落进 Home 的 children 会把侧栏/主面板
// 外壳一起渲染出来，登录页就不再是整页布局。
import { createMemoryHistory, createRouter } from 'vue-router'
import routes from '@/app/router'

describe('router 登录页', () => {
  const router = createRouter({ history: createMemoryHistory(), routes })

  it('注册 /login（name=login，meta.layout=auth）', () => {
    // Act
    const route = router.getRoutes().find(record => record.name === 'login')

    // Assert
    expect(route).toBeTruthy()
    expect(route.path).toBe('/login')
    expect(route.meta.layout).toBe('auth')
  })

  it('/login 只匹配一条顶层记录（不是 Home 的子路由）', () => {
    // Act
    const resolved = router.resolve('/login')

    // Assert：若是 Home 的 children，matched 会是 [Home, login] 两条
    expect(resolved.name).toBe('login')
    expect(resolved.matched).toHaveLength(1)
    expect(resolved.matched[0].name).toBe('login')
  })
})
