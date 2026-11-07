/**
 * 「当前选中的已发布工作流，绑定的知识库还在不在？」
 *
 * 判据在 `lib/kb-bindings.ts`（纯函数）；这里只负责取数、防止过期响应覆盖、
 * 以及失败时**放行**（fail-open —— 校验本身不该把对话页拦死）。
 */
import { onMounted, ref, watch, type Ref } from 'vue'
import { getAllStatusKbase, getPublishedFlowConfig } from '@/features/workflow/api/workflow'
import { collectBoundKbNames, findMissingKbNames, type KbBindingOption } from '@/features/chat/lib/kb-bindings'

export interface WorkflowBindingCheckApi {
  /** 已发布快照里绑定了、但当前库列表里找不到的库名（去重） */
  missingKbNames: Ref<string[]>
  /** 正在核对（供 UI 决定是否占位；当前页面不需要闪烁提示，保留给测试） */
  checking: Ref<boolean>
  /** 手动重跑一次（刷新工作流列表后调用） */
  recheck: () => Promise<void>
}

/** `/workflow/allStatusKbase` 的返回：bo 被 axios 拦截器解包后就是这个形状。 */
interface KbaseGroups {
  running?: KbBindingOption[]
  dev?: KbBindingOption[]
}

/** `/flow/published` 的返回（只声明本文件用到的字段）。 */
interface PublishedFlowConfig {
  nodeConfigDTOList?: unknown
}

function flattenOptions (groups: KbaseGroups | null | undefined): KbBindingOption[] {
  return [...(groups?.running || []), ...(groups?.dev || [])]
}

export function useWorkflowBindingCheck (selectedWorkflowId: Ref<string>): WorkflowBindingCheckApi {
  const missingKbNames = ref<string[]>([])
  const checking = ref(false)
  // 选中项变化很快时，只认最后一次请求的结果
  let requestSeq = 0

  async function recheck (): Promise<void> {
    const workflowId = selectedWorkflowId.value
    const seq = ++requestSeq
    if (!workflowId) {
      missingKbNames.value = []
      checking.value = false
      return
    }
    checking.value = true
    try {
      const [config, groups] = await Promise.all([
        getPublishedFlowConfig(workflowId),
        getAllStatusKbase()
      ])
      if (seq !== requestSeq) {
        return
      }
      missingKbNames.value = findMissingKbNames(
        collectBoundKbNames(config as PublishedFlowConfig | null | undefined),
        flattenOptions(groups as KbaseGroups | null | undefined)
      )
    } catch {
      // fail-open：取不到配置/列表时不报警，避免把网络问题说成「库被删了」
      if (seq === requestSeq) {
        missingKbNames.value = []
      }
    } finally {
      if (seq === requestSeq) {
        checking.value = false
      }
    }
  }

  onMounted(recheck)
  watch(selectedWorkflowId, () => {
    void recheck()
  })

  return { missingKbNames, checking, recheck }
}
