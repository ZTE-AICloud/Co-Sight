<template>
  <AppPage v-if="isKeys" class="management-page keys-page">
    <div class="page-inner">
      <ReferencePageHeader
        :title="$t(subpageLabelKey)"
        :subtitle="$t(pageDescriptionKey)"
        :icon="Lock"
      />

      <el-alert
        v-if="statusError"
        class="remote-access__alert"
        type="warning"
        :closable="false"
        show-icon
      >
        {{ $t('modules.remoteAccess.statusLoadFailed') }}
      </el-alert>

      <KeyManagementPage :status="status" @go-keys="goKeys" />
    </div>
  </AppPage>

  <AppPage v-else class="access-page">
    <div class="page-inner access-layout">
      <ReferencePageHeader
        :title="$t(subpageLabelKey)"
        :subtitle="$t(pageDescriptionKey)"
        :icon="Link"
      >
        <template #actions>
          <el-button class="button-compact" @click="showUsageGuide">
            <Reading />
            {{ $t('modules.remoteAccess.usageGuide') }}
          </el-button>
        </template>
      </ReferencePageHeader>

      <el-alert
        v-if="statusError"
        class="remote-access__alert"
        type="warning"
        :closable="false"
        show-icon
      >
        {{ $t('modules.remoteAccess.statusLoadFailed') }}
      </el-alert>

      <AccessGuidePage :status="status" @go-keys="goKeys" />
    </div>
  </AppPage>
</template>

<script setup>
import { computed, getCurrentInstance, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import AppPage from '@/shared/ui/AppPage.vue'
import ReferencePageHeader from '@/shared/ui/reference/PageHeader.vue'
import { getAgentKeyStatusApi } from '@/features/agent/api/remoteAccess'
import { Link, Lock, Reading } from '@/shared/lib/icons'
import AccessGuidePage from './AccessGuidePage.vue'
import KeyManagementPage from './KeyManagementPage.vue'

const { proxy } = getCurrentInstance()

function showUsageGuide () {
  ElMessageBox.alert(
    proxy.$t('modules.kb.docsBody'),
    proxy.$t('modules.kb.docsTitle'),
    {
      confirmButtonText: proxy.$t('modules.kb.docsConfirm'),
      customStyle: { whiteSpace: 'pre-line' }
    }
  )
}

const route = useRoute()
const router = useRouter()
const status = ref(null)
const statusError = ref(false)

/** 面包屑第二级来自路由 meta；直接访问子路由时也正确。 */
const subpageLabelKey = computed(() => route.meta.subpageLabelKey || 'nav.remoteAccessGuide')

/** 两个子页共用一层布局，标题下的说明按子页切换。 */
const isKeys = computed(() => route.name === 'keys')
const pageDescriptionKey = computed(() => (
  isKeys.value ? 'modules.remoteAccess.keysSubtitle' : 'modules.remoteAccess.subtitle'
))

function goKeys () {
  router.push({ name: 'keys' })
}

onMounted(async () => {
  try {
    status.value = await getAgentKeyStatusApi({ skipErrorHandler: true })
  } catch {
    // 状态接口失败不挡页面：接入说明仍可看，密钥表会自行报错。
    statusError.value = true
  }
})
</script>

<style scoped>
.access-layout { max-width: 1120px; }
.access-page :deep(.page-title) { margin-bottom: 36px; }
.remote-access__alert { margin-bottom: 16px; }

@media (max-width: 800px) {
  .access-page :deep(.page-title) { margin-bottom: 28px; }
}
</style>
