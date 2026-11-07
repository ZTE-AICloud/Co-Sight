// 测的是 `views/kBase/useKbSubPageRouteParams.js`：kb 详情/文件夹/自优化等子页面
// 共用的「拿 route 上的 kbId 换知识库名」钩子。
//
// 背景：非法 kbId 路由下这个钩子是「知识库不存在」toast 与 pageerror 的源头之一 ——
// 它在 setup 里 fire-and-forget 调 getKbName()，失败时拦截器弹一次 toast（正确），
// 但 rejection 没人接 → 浏览器每个调用它的页面都多一条未处理拒绝。
// 本 spec 钉三件事：
//   1) 每次调用 = 一次请求，且用 route 上的 kbId（去重是调用方的事 → Folder.vue 只准调一次）；
//   2) 成功路径：写回 kbName、按「真的变了才 commit」更新 store；
//   3) 失败路径：**不产生未处理拒绝**（console.error 保留线索），kbName 保持空。
// 变异验证：把源码里的 `.catch(...)` 拿掉 → 第 3 组的用例必红（见交付报告）。
import { useKbSubPageRouteParams } from '@/features/knowledge-base/composables/useKbSubPageRouteParams.js'

vi.mock('@/features/knowledge-base/api/knowledgeBase', () => ({
  getKnowledgeBaseInfo: vi.fn()
}))

import { getKnowledgeBaseInfo } from '@/features/knowledge-base/api/knowledgeBase'

/** 造一个组件实例 proxy：只带钩子用到的 $route / $store 两面 */
function makeProxy ({ kbId = 'kb-1', currentName = '' } = {}) {
  const commit = vi.fn()
  return {
    proxy: {
      $route: { params: { id: kbId } },
      $store: {
        state: { kbase: { kBaseName: currentName } },
        commit
      }
    },
    commit
  }
}

/** 让已 resolve/reject 的 promise 链跑完（钩子内部是不 await 的发射后不管） */
async function settle () {
  await Promise.resolve()
  await new Promise(resolve => setTimeout(resolve, 25))
}

describe('useKbSubPageRouteParams', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('given_调用一次_when_初始化_then_按 route 上的 kbId 发一次请求', () => {
    it('kbId 取自路由参数，且一次调用只发一次 getKnowledgeBaseInfo', async () => {
      // Arrange
      getKnowledgeBaseInfo.mockResolvedValue({ name: '知识库A' })
      const { proxy } = makeProxy({ kbId: 'kb-77' })

      // Act
      useKbSubPageRouteParams(proxy)
      await settle()

      // Assert：去重责任在调用方（Folder.vue 曾连调两次 → 两发同名请求两条同名 toast）
      expect(getKnowledgeBaseInfo).toHaveBeenCalledTimes(1)
      expect(getKnowledgeBaseInfo).toHaveBeenCalledWith('kb-77')
    })

    it('success：写回 kbName，并把新名字 commit 给 store', async () => {
      // Arrange
      getKnowledgeBaseInfo.mockResolvedValue({ name: '知识库A' })
      const { proxy, commit } = makeProxy({ currentName: '' })

      // Act
      const { kbName } = useKbSubPageRouteParams(proxy)
      await settle()

      // Assert
      expect(kbName.value).toBe('知识库A')
      expect(commit).toHaveBeenCalledWith('kbase/updatekBaseName', '知识库A')
    })

    it('success：名字没变时不 commit（避免无意义的状态写入）', async () => {
      // Arrange
      getKnowledgeBaseInfo.mockResolvedValue({ name: '同名' })
      const { proxy, commit } = makeProxy({ currentName: '同名' })

      // Act
      useKbSubPageRouteParams(proxy)
      await settle()

      // Assert
      expect(commit).not.toHaveBeenCalled()
    })
  })

  describe('given_请求失败_when_初始化_then_不产生未处理拒绝', () => {
    it('reject 被自己接住：无 unhandledRejection、kbName 保持空、console.error 留痕', async () => {
      // Arrange：模拟 0005「知识库不存在」——拦截器已弹过 toast，这里只关心钩子自身
      getKnowledgeBaseInfo.mockRejectedValue({ code: '0005', msg: '知识库不存在' })
      const { proxy, commit } = makeProxy()
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
      const unhandled = []
      const onUnhandled = reason => unhandled.push(reason)
      process.on('unhandledRejection', onUnhandled)

      try {
        // Act
        const { kbName, kbDetail } = useKbSubPageRouteParams(proxy)
        await settle()

        // Assert：裸奔的 rejection 正是三张非法 id 页面那次战报里的 pageerror（"Object: Object"）
        expect(unhandled).toHaveLength(0)
        expect(kbName.value).toBe('')
        expect(kbDetail.value).toEqual({})
        expect(commit).not.toHaveBeenCalled()
        expect(consoleError).toHaveBeenCalled()
      } finally {
        process.off('unhandledRejection', onUnhandled)
        consoleError.mockRestore()
      }
    })
  })
})
