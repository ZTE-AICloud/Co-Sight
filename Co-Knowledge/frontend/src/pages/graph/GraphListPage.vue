<template>
  <AppPage class="management-page knowledge-page">
    <div class="page-inner">
      <PageHeader
        :title="$t('modules.kb.graphKnowledgeBase')"
        :subtitle="$t('modules.kb.graphPageSubtitle')"
        :icon="Share"
      />

      <!-- 容器按 subTab 二选一渲染图谱列表或模版列表。 -->
      <KnowledgeGraphtab />
    </div>
  </AppPage>
</template>

<script lang="ts" setup>
import { ref, onMounted, provide } from 'vue'
import { Share } from '@/shared/lib/icons'
import { useRouter } from 'vue-router'
import KnowledgeGraphtab from '@/features/graph/GraphTabs.vue'
import AppPage from '@/shared/ui/AppPage.vue'
import PageHeader from '@/shared/ui/reference/PageHeader.vue'
import { checkAISEnvironmentApi } from '@/features/knowledge-base/api/kbaseApi.js'

// 图谱知识库页：页面结构 = 管理页壳 + PageHeader + knowledgeGraphtab
// （它自带「知识图谱 / 知识图谱模版」两个子页签）。

const router = useRouter()

// 给下面的图谱列表/模版列表喂「外层页签」状态：knowledgeGraph.vue / knowledgeGraphTemplate.vue
// 通过 inject('kbaseActiveTab') 判断自己所在的图谱面是否可见（决定自动刷新要不要跑）。
// 本页就是图谱页，没有第二个外层页签，所以给一个常量 ref。
provide('kbaseActiveTab', ref('knowledgeGraph'))

// AIS/V7 环境闸门：「AIS 或 V7」环境隐藏图谱知识库（/kbase/ais 返回 ais=true）；检查失败也不放行。
//   未设 DEPLOY_PLAT_TYPE（compat 侧由它决定 ais）时恒为非 AIS，闸门不触发。
onMounted(() => {
  checkAISEnvironmentApi()
    .then((res: any) => {
      if (res && typeof res === 'object' && res.ais === true) {
        router.replace({ path: '/knowledge' })
      }
    })
    .catch(() => {
      router.replace({ path: '/knowledge' })
    })
})
</script>
