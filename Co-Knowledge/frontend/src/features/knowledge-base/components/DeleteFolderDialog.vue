<template>
  <StudioDialog
    v-model="open"
    dialog-class="delete-folder-dialog"
    width="560px"
    :title="$t('modules.studioDialogs.knowledgeDetail.deleteFolder')"
    :subtitle="subtitle"
    :icon="Delete"
    :hint="$t('modules.studioDialogs.knowledgeDetail.deleteFolderHint')"
    :busy="busy"
  >
    <div class="delete-confirm-content">
      <div class="delete-confirm-warning" role="note">
        <WarningFilled />
        <div>
          <strong class="text-body">{{ summary }}</strong>
        </div>
      </div>
      <ul v-if="documentCount > 0" class="delete-folder-options">
        <li>
          <strong>{{ $t('modules.studioDialogs.knowledgeDetail.deleteFolderAndDocs') }}</strong>
          <span class="text-caption text-secondary">{{ $t('modules.studioDialogs.knowledgeDetail.deleteFolderAndDocsDesc') }}</span>
        </li>
        <li>
          <strong>{{ $t('modules.studioDialogs.knowledgeDetail.deleteFolderOnly') }}</strong>
          <span class="text-caption text-secondary">{{ $t('modules.studioDialogs.knowledgeDetail.deleteFolderOnlyDesc') }}</span>
        </li>
      </ul>
      <DeleteVerification ref="verificationRef" @update:verified="verified = $event" />
    </div>
    <template #actions>
      <el-button :disabled="busy" @click="open = false">{{ $t('modules.studioDialogs.knowledgeDetail.deleteFolderCancel') }}</el-button>
      <el-button :disabled="busy || !verified" @click="$emit('delete-only')">{{ $t('modules.studioDialogs.knowledgeDetail.deleteFolderOnly') }}</el-button>
      <el-button v-if="documentCount > 0" type="danger" :disabled="busy || !verified" @click="$emit('delete-with-docs')">
        {{ $t('modules.studioDialogs.knowledgeDetail.deleteFolderAndDocs') }}
      </el-button>
    </template>
  </StudioDialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { Delete, WarningFilled } from '@element-plus/icons-vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import DeleteVerification from '@/shared/ui/DeleteVerification.vue'
import { $t } from '@/app/i18n/i18n.js'

const props = defineProps({
  folderName: { type: String, default: '' },
  documentCount: { type: Number, default: 0 },
  busy: Boolean
})
defineEmits(['delete-only', 'delete-with-docs'])
const open = defineModel({ type: Boolean, default: false })
const verificationRef = ref()
const verified = ref(false)

// 每次打开都重新生成确认码（StudioDialog destroy-on-close 会重建子组件，这里兜底）。
watch(open, value => {
  verified.value = false
  if (value) {
    nextTick(() => verificationRef.value?.reset())
  }
})

const summary = computed(() => props.documentCount > 0
  ? $t('modules.studioDialogs.knowledgeDetail.deleteFolderWithDocs', {
    name: props.folderName,
    count: props.documentCount
  })
  : $t('modules.studioDialogs.knowledgeDetail.deleteFolderEmpty', { name: props.folderName }))

const subtitle = computed(() => props.documentCount > 0
  ? $t('modules.studioDialogs.knowledgeDetail.deleteFolderDialogSubtitle')
  : $t('modules.studioDialogs.knowledgeDetail.deleteFolderEmptySubtitle'))
</script>

<style scoped>
.delete-folder-options {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.delete-folder-options li {
  display: grid;
  gap: 3px;
  padding: 12px 14px;
  border: 1px solid var(--rs-border);
  border-radius: var(--rs-radius);
  background: var(--rs-bg-card);
}

.delete-folder-options strong {
  color: var(--rs-text);
  font-weight: 600;
}
</style>
