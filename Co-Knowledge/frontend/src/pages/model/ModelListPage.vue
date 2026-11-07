<template>
  <AppPage class="management-page models-page">
    <div class="page-inner">
      <PageHeader
        :title="$t('nav.modelManagement')"
        :subtitle="$t('modules.modelManagement.pageSubtitle')"
        :icon="CubeIcon"
      />

      <el-alert
        class="model-notice"
        type="info"
        show-icon
        :title="$t('modules.modelManagement.subtitle')"
      />

      <el-tabs v-model="tabsValue" @tab-click="tabClickHandle">
        <el-tab-pane
          v-for="kind in MODEL_KINDS"
          :key="kind"
          :label="$t(KIND_LABEL_KEY[kind])"
          :name="kind"
          lazy
        >
          <ModelTable :ref="(el: any) => (tableRefs[kind] = el)" :kind="kind" @change-kind="switchKind" />
        </el-tab-pane>
      </el-tabs>
    </div>
  </AppPage>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import ModelTable from '@/features/model/ModelTable.vue'
import AppPage from '@/shared/ui/AppPage.vue'
import PageHeader from '@/shared/ui/reference/PageHeader.vue'
import { CubeIcon } from '@/shared/ui/icons'
import { KIND_LABEL_KEY, MODEL_KINDS, ModelKind } from '@/features/model/type'

/**
 * 三类模型各一个页签，不合成一张带类型列的表格。
 *
 * 理由：三类的**列与表单字段本来就不同**（embedding 有维度、llm 有推理标记与生成参数、
 * rerank 两个都没有），硬合成一张表就得让一半列在两种情况下空着；而且三类各自的消费面
 * 完全独立（建库只认 embedding、画布只认 llm、发布校验只认 rerank），
 * 分开展示才不会让人误以为可以互相替代。
 */
const tabsValue = ref<ModelKind>('llm')
const tableRefs = ref<Record<string, any>>({})

/**
 * 页签是 lazy 的：首次切到某类时才挂载，由 ModelTable 自己的 onMounted 取数；
 * 之后再切回来（EP 会缓存内容，不会重新挂载）才需要手动刷新。
 *
 * 用 visited 区分「首次挂载」与「切回来」：首次如果也调 refresh，会和 onMounted
 * 取数叠成两条相同请求。
 */
const visitedKinds = new Set<ModelKind>(['llm'])

function refreshVisitedKind (kind: string) {
  if (!visitedKinds.has(kind as ModelKind)) {
    visitedKinds.add(kind as ModelKind)
    return
  }
  nextTick(() => {
    tableRefs.value[kind]?.refreshTableData()
  })
}

/**
 * 用事件里的 paneName，不用 tabsValue：`tab-click` 触发时 v-model 可能还没写回，
 * 读 tabsValue 会把「切到新页签」当成「刷新旧页签」，多打一条旧页签的请求。
 */
function tabClickHandle (pane: any) {
  const kind = String(pane?.paneName ?? tabsValue.value)
  refreshVisitedKind(kind)
}

/** 新建/编辑弹窗里改了类型：跟着切到新类型的页签，避免「保存了却看不到」。 */
function switchKind (kind: string) {
  tabsValue.value = kind as ModelKind
  refreshVisitedKind(kind)
}
</script>

<style scoped>
.model-notice :deep(.el-alert__close-btn) { top: 50%; transform: translateY(-50%); }
.models-page .el-alert { margin-bottom: 16px; min-height: 58px; }
</style>
