<template>
  <StudioDialog
    v-if="currentText"
    :model-value="!!releaseNotice"
    :title="$t('modules.release.noticeTitle')"
    :subtitle="`v${currentText.version} · ${currentText.title}`"
    :icon="Bell"
    width="600px"
    @update:model-value="acknowledgeReleaseNotice"
  >
    <div class="release-notice-content">
      <ReleaseChanges :release="currentRelease" />
    </div>
    <template #actions>
      <el-button @click="viewHistory">
        {{ $t('modules.release.viewHistory') }}
      </el-button>
      <el-button type="primary" @click="acknowledgeReleaseNotice">
        {{ $t('modules.release.acknowledge') }}
      </el-button>
    </template>
  </StudioDialog>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { Bell } from '@/shared/lib/icons'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import ReleaseChanges from './ReleaseChanges.vue'
import { acknowledgeReleaseNotice, releaseNotice } from '@/shared/composables/releaseNotice'
import { currentRelease, releaseText } from '@/shared/constants/releases'

/**
 * 登录后弹出的「版本更新」提醒。
 *
 * 关闭弹窗（右上角 / ESC / 「我知道了」）与「查看版本历史」都按**已确认**处理：
 * 同一账号在当前浏览器同一版本只提示一次。
 */
const router = useRouter()
const { locale } = useI18n()

const currentText = computed(() => currentRelease && releaseText(currentRelease, locale.value))

function viewHistory () {
  acknowledgeReleaseNotice()
  router.push({ name: 'release' })
}
</script>

<style scoped>
.release-notice-content { padding-block: 22px; }
</style>
