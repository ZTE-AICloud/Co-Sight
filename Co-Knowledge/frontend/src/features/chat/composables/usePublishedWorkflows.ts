/**
 * 「已发布工作流」下拉的数据源：拉列表 → 过滤 → 维持选中项 → 空态/错误态。
 *
 * 只在这里依赖 vue / vue-i18n；真正的判据（publishType 过滤）没有可测的纯逻辑，
 * 单独抽出去反而绕远，就放在这一层。
 */
import { onMounted, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getFlowList } from '@/features/workflow/api/workflow'
import { errText } from '@/features/chat/lib/errors'
import { readLastWorkflow, writeLastWorkflow } from '@/features/chat/lib/session-storage'

/** 一次性拉完再用 —— 当前栈里工作流条数是个位数，做分页下拉是过度设计。 */
const WORKFLOW_PAGE_SIZE = 100

/** 工作流创建时绑定的知识库项（列表接口回显用） */
export interface WorkflowBoundKb {
  name?: string
  assetId?: string
  tableName?: string
  [key: string]: unknown
}

/** 工作流列表项。只声明这个页面真正用到的字段，其余原样透传。 */
export interface WorkflowOption {
  workFlowId: string
  name: string
  /** 0=未发布，1=已发布，2=已发布但草稿有改动 */
  publishType?: number
  /** 创建时绑定的文档库（用于把已删除库的基名映射回可读名称） */
  kbPkIds?: WorkflowBoundKb[]
  graphKbPkIds?: WorkflowBoundKb[]
  [key: string]: unknown
}

export interface PublishedWorkflowsApi {
  loadingWorkflows: Ref<boolean>
  loadError: Ref<string>
  publishedWorkflows: Ref<WorkflowOption[]>
  selectedWorkflowId: Ref<string>
  loadWorkflows: () => Promise<void>
}

/**
 * 拉取并维护「已发布工作流」下拉。
 *
 * 组件挂载即加载（`onMounted` 由本层注册，视图不必再自己接一根线）。
 * 加载失败与「一条都没发布」在视图上是**两块不同的 UI**，所以这里把
 * `loadingWorkflows` / `loadError` / 空列表三种状态分开暴露。
 */
export function usePublishedWorkflows (): PublishedWorkflowsApi {
  const { t } = useI18n()

  const loadingWorkflows = ref(true)
  const loadError = ref('')
  const publishedWorkflows = ref<WorkflowOption[]>([])
  const selectedWorkflowId = ref('')

  async function loadWorkflows (): Promise<void> {
    loadingWorkflows.value = true
    loadError.value = ''
    try {
      const res: unknown = await getFlowList(1, WORKFLOW_PAGE_SIZE)
      const data = (res as { items?: unknown } | null | undefined)?.items
      const all = Array.isArray(data) ? (data as WorkflowOption[]) : []
      // publishType: 0=未发布，1=已发布，2=已发布但草稿有改动。
      // 1 和 2 都有可用的发布快照（编排运行时读的就是快照，草稿改了不影响线上），
      // 只有 0 跑不起来。列表页的发布状态列用的是同一套判据。
      publishedWorkflows.value = all.filter(wf => wf.publishType !== 0)
      // 选择顺序：当前仍有效 → 上次选择（刷新后恢复到原工作流/原历史）→ 第一条
      const stillValid = publishedWorkflows.value.some(wf => wf.workFlowId === selectedWorkflowId.value)
      if (!stillValid) {
        const remembered = readLastWorkflow()
        const rememberedValid = remembered
          && publishedWorkflows.value.some(wf => wf.workFlowId === remembered)
        selectedWorkflowId.value = rememberedValid
          ? remembered
          : (publishedWorkflows.value.length ? publishedWorkflows.value[0].workFlowId : '')
      }
    } catch (e: unknown) {
      // 这里不额外弹 toast：默认拦截器已经弹过一次了，再弹一个是重复提示
      publishedWorkflows.value = []
      selectedWorkflowId.value = ''
      loadError.value = errText(e, t('modules.chatTest.loadWorkflowsFailed'))
    } finally {
      loadingWorkflows.value = false
    }
  }

  onMounted(loadWorkflows)

  // 记住选择：刷新后能回到同一个工作流（历史会话挂在它的键下）
  watch(selectedWorkflowId, (workflowId) => writeLastWorkflow(workflowId))

  return { loadingWorkflows, loadError, publishedWorkflows, selectedWorkflowId, loadWorkflows }
}
