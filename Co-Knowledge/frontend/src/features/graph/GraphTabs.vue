<template>
  <div class="knowledge-graph-tab-container">
    <div v-if="activeName === 'knowledgeGraphTemplate'" class="kg-template-back">
      <el-button link type="primary" @click="goGraphList">
        <ArrowLeft />
        {{ $t('modules.kb.knowledgeGraph') }}
      </el-button>
    </div>
    <!-- 页签头删除（不再用 `el-tabs` + CSS 隐藏）：图谱列表与模版列表二选一渲染，
         入口在工具条「更多操作 → 知识图谱模版」，模版页顶部有返回链接。 -->
    <KnowledgeGraph v-if="activeName === 'knowledgeGraph'" />
    <KnowledgeGraphTemplate v-else />
  </div>
</template>

<script lang="ts" setup>
import { ref, provide, watch, nextTick, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@/shared/lib/icons'
import KnowledgeGraph from '@/features/graph/GraphList.vue'
import KnowledgeGraphTemplate from '@/features/graph/GraphTemplateList.vue'

const route = useRoute()
const router = useRouter()
// 初值直接看路由：深链/刷新 `?subTab=knowledgeGraphTemplate` 时不能先按默认挂一次
// 图谱列表（那会白发出列表 + 指标 + 环境检查三条请求，再立刻卸载）。
const activeName = ref(
  route.query.subTab === 'knowledgeGraphTemplate' ? 'knowledgeGraphTemplate' : 'knowledgeGraph'
)

function goGraphList () {
  router.push({ path: '/graph', query: { subTab: 'knowledgeGraph' } })
}

// 把当前激活的页签名提供给子组件：knowledgeGraph.vue 用它做自动刷新的可见性闸门
// （停在「知识图谱模版」时不该每 10 秒拉图谱列表）
provide('activeTabName', activeName)

// 从路由参数中获取 subTab，用于控制内部页签（「知识图谱模版」深链，由模版设计器返回时
// 或深链写入；当前路由是 /graph
const updateActiveTabFromRoute = () => {
  const subTab = route.query.subTab as string
  if (subTab === 'knowledgeGraphTemplate') {
    if (activeName.value !== 'knowledgeGraphTemplate') {
      activeName.value = 'knowledgeGraphTemplate'
    }
  } else if (subTab === 'knowledgeGraph') {
    if (activeName.value !== 'knowledgeGraph') {
      activeName.value = 'knowledgeGraph'
    }
  }
}

// ⚠️ 三重延迟（nextTick + 100ms + 300ms）是挂载时序兜底：子页签要等 route.query
// 稳定后才拿得到正确值。`?subTab=knowledgeGraphTemplate` 是回归脚本
// verify-kb-list-regress.js 用例 1b 在钉的路径，没有实测把握前不动这段时序。
onMounted(() => {
  nextTick(() => {
    updateActiveTabFromRoute()

    setTimeout(() => {
      updateActiveTabFromRoute()
    }, 100)

    setTimeout(() => {
      updateActiveTabFromRoute()
    }, 300)
  })
})

// 监听路由参数变化（含首次 immediate）：模版设计器保存/返回时会带上 subTab
watch(
  () => route.query.subTab,
  () => {
    nextTick(() => {
      setTimeout(() => {
        updateActiveTabFromRoute()
      }, 50)
    })
  },
  { immediate: true }
)

// 同时监听整个路由对象的变化，作为备用方案（query 里别的参数变了也重算一次）
watch(
  () => route.query,
  () => {
    nextTick(() => {
      setTimeout(() => {
        updateActiveTabFromRoute()
      }, 50)
    })
  },
  { deep: true }
)
</script>

<style lang="less" scoped>
.knowledge-graph-tab-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: transparent;
}

/* 模版页顶部的返回链接。 */
.kg-template-back {
  flex-shrink: 0;
  padding-bottom: 12px;
}

/* 原 el-tabs 内容区那层 flex:1/overflow:hidden 的职责，现在由这个容器承担。 */
.knowledge-graph-tab-container > :deep(.graph-list-page),
.knowledge-graph-tab-container > :deep(.knowledge-graph-template-page) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>
