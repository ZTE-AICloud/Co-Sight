// @vitest-environment jsdom
//
// 测的是 `src/shared/api/client.js` 的共享请求头构造（`buildRequestHeaders`）：
// **Accept-Language 必须随界面语言发**。
//
// 背景：后端（RKB compat 层）的文案语言只认 Accept-Language（`X-Lang-Id` 在那边是
// 死信，见 backend/src/compat/kb_api/identity.py）；前端不能只发
// X-Lang-Id → 否则切到 en 后后端错误 toast 仍是中文。
// 只有 zh-CN（与 *）渲染中文，其余语言回落英文 —— 所以取值按 i18n 的
// 界面语言判定（isGlobalZh）映射成 zh-CN / en-US，而不是透传原始 locale。
//
// 为什么直接挂 base.js：
//   * `@/service/appState` 与 `@/i18n/i18n.js` 都在导入期读 window / localStorage /
//     navigator（见各自文件头），所以必须 mock —— 单测也不该碰真实鉴权状态；
//   * 语言开关用 `vi.hoisted` 变量 + `vi.resetModules()`：mock 工厂在每次重新
//     import 时执行，读到的就是当前值。
import { describe, it, expect, vi, beforeEach } from 'vitest'

const env = vi.hoisted(() => ({ isZh: true }))

vi.mock('@/app/state', () => ({
  default: {
    user: { authValue: 'test-token', userName: 'tester' },
    langId: 'zh-CN'
  }
}))
vi.mock('@/app/i18n/i18n.js', () => ({
  $t: (key) => key,
  // getter：base.js 在 **调用时** 读 isGlobalZh，每个用例直接改 env.isZh 即可，
  // 不依赖 mock 工厂重跑（vi.resetModules 对 mock 工厂结果不保证重建）
  get isGlobalZh () { return env.isZh }
}))
vi.mock('@/shared/lib/message', () => ({
  default: { error: vi.fn(), close: vi.fn() }
}))
vi.mock('@/shared/lib/cookies.ts', () => ({ encodeHeaderValue: (s) => s }))
vi.mock('@/shared/constants/index.js', () => ({ REPEATFILENAMECODE: 'REPEATFILENAME' }))

describe('buildRequestHeaders 的语言头', () => {
  beforeEach(() => {
    env.isZh = true
  })

  it('zh 界面：Accept-Language=zh-CN（后端才给中文文案）', async () => {
    // Arrange & Act
    const { buildRequestHeaders } = await import('@/shared/api/client')
    const headers = buildRequestHeaders()

    // Assert
    expect(headers['Accept-Language']).toBe('zh-CN')
  })

  it('en 界面：Accept-Language=en-US（en 错误 toast 不再回落中文）', async () => {
    // Arrange
    env.isZh = false

    // Act
    const { buildRequestHeaders } = await import('@/shared/api/client')
    const headers = buildRequestHeaders()

    // Assert
    expect(headers['Accept-Language']).toBe('en-US')
  })

  it('保留既有 X-Lang-Id 与鉴权头（不删兼容头）', async () => {
    // Arrange
    env.isZh = false

    // Act
    const { buildRequestHeaders } = await import('@/shared/api/client')
    const headers = buildRequestHeaders()

    // Assert
    expect(headers['X-Lang-Id']).toBe('zh_CN')
    expect(headers['X-Auth-Value']).toBe('test-token')
    expect(headers['X-Emp-No']).toBe('tester')
  })
})
