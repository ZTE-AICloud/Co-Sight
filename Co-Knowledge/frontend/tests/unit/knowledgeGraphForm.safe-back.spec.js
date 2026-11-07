// @vitest-environment jsdom
// ↑ 组件测试：要真 i18n（`proxy.$t`）+ DOM（`window.history.state`）
//
// 测的是 `views/knowledgeGraphTab/composables/useKnowledgeGraphForm.js` 里
// `fetchKnowledgeGraphInfo` 的三条错误分支（缺 id / 接口返回空 / 接口抛异常）在
// 「新标签页直开深链、没有可退历史」时的落点。
//
// 无历史时不能 `router.back()` —— 那会退到 about:blank，整页白屏且页内无自愈入口。
// 约定：无历史时 `router.replace({ path: '/graph' })`，有历史时保持 back()。
// 本条用例是这条约定的唯一钉子 —— 谁把 fallback 改回 back()、
// 或把「有历史也 replace」写进来，下面就会红。

import { vi } from 'vitest'
import { defineComponent } from 'vue'
import { mountWithPlugins } from './helpers/mount'

vi.mock('@/features/model/api/models', () => ({ getModelList: vi.fn() }))
vi.mock('@/features/graph/api/knowledgeGraph', () => ({
  getKnowledgeGraphBasicInfoApi: vi.fn(),
  updateKnowledgeGraphExtractApi: vi.fn()
}))

import { useKnowledgeGraphForm } from '@/features/graph/composables/useKnowledgeGraphForm'
import { getKnowledgeGraphBasicInfoApi } from '@/features/graph/api/knowledgeGraph'

const basicInfoApi = vi.mocked(getKnowledgeGraphBasicInfoApi)

const GRAPH_LIST_PATH = '/graph'

/** 假 router：只关心 back() 与 replace() 的调用，不真导航。 */
function makeFakeRouter () {
  return { back: vi.fn(), replace: vi.fn() }
}

/**
 * 把 composable 挂进一个探针组件（`getCurrentInstance()` 要求 setup 上下文），
 * 并把 `$message` 桩从参数传进去以便断言 toast。
 */
async function setupForm (messageMock) {
  let form = null
  const Probe = defineComponent({
    setup () {
      form = useKnowledgeGraphForm()
      return () => null
    }
  })
  await mountWithPlugins(Probe, {
    route: '/graph/edit/bad-id',
    global: { mocks: { $message: messageMock } }
  })
  return form
}

function makeMessageMock () {
  return { error: vi.fn(), success: vi.fn(), warning: vi.fn() }
}

/** 模拟 vue-router 4 写进 history.state 的形状（首个条目 back 为 null）。 */
function setHistoryBack (back) {
  window.history.replaceState({ back, current: 'cur-key', forward: null, position: 0 }, '')
}

describe('fetchKnowledgeGraphInfo：无历史时的安全返回', () => {
  beforeEach(() => {
    basicInfoApi.mockReset()
    // jsdom 默认 history.state 为 null；这里显式复位，避免用例间串状态
    window.history.replaceState(null, '')
  })

  it('接口抛异常 + 无可退历史（state 为 null）→ 弹错误提示后 replace 到图谱列表，不再 back()', async () => {
    // Arrange：新标签页直开非法 id 的深链
    basicInfoApi.mockRejectedValue(new Error('boom'))
    const messageMock = makeMessageMock()
    const form = await setupForm(messageMock)
    const router = makeFakeRouter()

    // Act
    await form.fetchKnowledgeGraphInfo({ params: { id: 'no-such-id' } }, router)

    // Assert：提示仍保留（replace 后挂在列表页上），跳转目标是图谱列表
    expect(messageMock.error).toHaveBeenCalledTimes(1)
    expect(router.replace).toHaveBeenCalledWith({ path: GRAPH_LIST_PATH })
    expect(router.back).not.toHaveBeenCalled()
    // 先提示、后跳转（反过来提示会被导航竞态吞掉）
    expect(messageMock.error.mock.invocationCallOrder[0])
      .toBeLessThan(router.replace.mock.invocationCallOrder[0])
  })

  it('接口抛异常 + 首个历史条目（state.back === null，vue-router 真实形状）→ 同样 replace 兜底', async () => {
    // Arrange
    basicInfoApi.mockRejectedValue(new Error('boom'))
    setHistoryBack(null)
    const form = await setupForm(makeMessageMock())
    const router = makeFakeRouter()

    // Act
    await form.fetchKnowledgeGraphInfo({ params: { id: 'no-such-id' } }, router)

    // Assert
    expect(router.replace).toHaveBeenCalledWith({ path: GRAPH_LIST_PATH })
    expect(router.back).not.toHaveBeenCalled()
  })

  it('接口抛异常 + 有可退历史（state.back 为字符串）→ back()，不 replace', async () => {
    // Arrange：从列表页点进来的正常路径，必须保持 back() 体验
    basicInfoApi.mockRejectedValue(new Error('boom'))
    setHistoryBack('prev-key')
    const form = await setupForm(makeMessageMock())
    const router = makeFakeRouter()

    // Act
    await form.fetchKnowledgeGraphInfo({ params: { id: 'no-such-id' } }, router)

    // Assert
    expect(router.back).toHaveBeenCalledTimes(1)
    expect(router.replace).not.toHaveBeenCalled()
  })

  it('接口返回空（res 为 falsy）+ 无历史 → 同样 replace 兜底', async () => {
    // Arrange
    basicInfoApi.mockResolvedValue(null)
    const messageMock = makeMessageMock()
    const form = await setupForm(messageMock)
    const router = makeFakeRouter()

    // Act
    await form.fetchKnowledgeGraphInfo({ params: { id: 'gone-id' } }, router)

    // Assert
    expect(messageMock.error).toHaveBeenCalledTimes(1)
    expect(router.replace).toHaveBeenCalledWith({ path: GRAPH_LIST_PATH })
    expect(router.back).not.toHaveBeenCalled()
  })

  it('缺 id + 无历史 → 提示「缺少知识图谱ID」后 replace 兜底（同一安全返回）', async () => {
    // Arrange
    const messageMock = makeMessageMock()
    const form = await setupForm(messageMock)
    const router = makeFakeRouter()

    // Act
    await form.fetchKnowledgeGraphInfo({ params: {} }, router)

    // Assert：不碰接口，直接提示 + 兜底
    expect(basicInfoApi).not.toHaveBeenCalled()
    expect(messageMock.error).toHaveBeenCalledTimes(1)
    expect(router.replace).toHaveBeenCalledWith({ path: GRAPH_LIST_PATH })
    expect(router.back).not.toHaveBeenCalled()
  })
})
