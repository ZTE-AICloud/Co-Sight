<template>
  <StudioDialog
    v-model="open"
    :title="$t('modules.kb.importHintTitle')"
    :subtitle="$t('modules.kb.importSubtitle')"
    :icon="Upload"
    :hint="$t('modules.kb.importHint', { count: files.length, size: formatFileSize(totalBytes) })"
    width="640px"
    :busy="submitting"
  >
    <el-form class="studio-form knowledge-import-form" label-position="top" @submit.prevent="submit">
      <div class="studio-form-section">
        <el-form-item :label="$t('modules.kb.importTarget')">
          <el-select
            v-model="targetId"
            :aria-label="$t('modules.kb.importTarget')"
            :placeholder="$t('modules.kb.importSelectTarget')"
            filterable
            @change="error = ''"
          >
            <el-option v-for="entry in entries" :key="entry.id" :value="entry.id" :label="entry.name" />
          </el-select>
        </el-form-item>
        <KnowledgeFilePicker
          v-model="files"
          :active-file-limits="limits.groups"
          :max-files="limits.maxFiles"
          :max-total-bytes="limits.maxTotalBytes"
        />
        <p class="knowledge-import-note text-caption">
          {{ $t('modules.kb.importNote') }}
        </p>
        <!-- 接口错误单独占一行：挂到 el-form-item 的 `error` 是绝对定位的，
             会和下面的拖拽区叠在一起。 -->
        <p v-if="error" class="knowledge-import-error text-caption" role="alert">
          <WarningFilled />{{ error }}
        </p>
      </div>
    </el-form>
    <template #actions>
      <el-button :disabled="submitting" @click="open = false">{{ $t('public.cancel') }}</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!files.length || !entries.length" @click="submit">
        <Upload />{{ $t('modules.kb.importHintTitle') }}
      </el-button>
    </template>
  </StudioDialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Upload, WarningFilled } from '@element-plus/icons-vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import KnowledgeFilePicker from './KnowledgeFilePicker.vue'
import { $t } from '@/app/i18n/i18n.js'
import { FILE_NAME_CONFLICT_CODE } from '@/shared/constants/index.js'
import { formatFileSize } from '../lib/knowledge-files'
import { fallbackUploadLimits, loadUploadLimits } from '../lib/quick-create'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({
  entries: { type: Array, default: () => [] },
  initialId: { type: String, default: '' },
  /** 由父级注入的真实上传动作；返回 Promise 时关闭弹窗，抛错时保持打开并显示错误 */
  submitHandler: { type: Function, default: null }
})
const emit = defineEmits(['import'])

const targetId = ref('')
const files = ref([])
const error = ref('')
const submitting = ref(false)
const limits = ref(fallbackUploadLimits())
const totalBytes = computed(() => files.value.reduce((sum, file) => sum + file.size, 0))

watch(open, async value => {
  if (!value) {
    return
  }
  targetId.value = props.initialId || ''
  files.value = []
  error.value = ''
  submitting.value = false
  limits.value = await loadUploadLimits()
})

watch(() => props.entries, entries => {
  if (!open.value) {
    return
  }
  if (!entries.some(entry => entry.id === targetId.value)) {
    const initial = entries.find(entry => entry.id === props.initialId)
    targetId.value = initial?.id || ''
  }
}, { deep: false })

/** 真正的上传动作：`options.coverFlag` 由覆盖确认分支传入。 */
function runSubmit (payload, options = {}) {
  if (!props.submitHandler) {
    emit('import', { ...payload, ...options })
    return Promise.resolve()
  }
  return Promise.resolve(props.submitHandler(payload, options))
}

/** 同名冲突：让用户明确选择「覆盖更新」，而不是把 409 文案当成一句死提示。 */
async function confirmOverwrite () {
  try {
    await ElMessageBox.confirm(
      $t('modules.studioDialogs.knowledgeDetail.duplicateFileConfirm'),
      $t('messageBox.tip'),
      {
        confirmButtonText: $t('knowledge.import.recover'),
        cancelButtonText: $t('public.cancel'),
        type: 'warning'
      }
    )
    return true
  } catch {
    // 取消覆盖：保持弹窗与已选文件，用户可以换目标库或删掉重名文件。
    return false
  }
}

async function submit () {
  const target = props.entries.find(entry => entry.id === targetId.value)
  if (!target) {
    error.value = $t('modules.kb.importTargetRequired')
    return
  }
  if (!files.value.length || submitting.value) {
    return
  }
  error.value = ''
  const payload = { target, files: [...files.value], totalBytes: totalBytes.value }
  if (!props.submitHandler) {
    runSubmit(payload)
    open.value = false
    return
  }
  submitting.value = true
  try {
    await runSubmit(payload)
    open.value = false
  } catch (err) {
    if (err?.code === FILE_NAME_CONFLICT_CODE) {
      if (!(await confirmOverwrite())) {
        return
      }
      try {
        await runSubmit(payload, { coverFlag: true })
        open.value = false
        return
      } catch (retryError) {
        error.value = retryError?.detail || retryError?.message || $t('modules.studioDialogs.knowledgeDetail.uploadFailed')
        return
      }
    }
    error.value = err?.detail || err?.message || $t('modules.studioDialogs.knowledgeDetail.uploadFailed')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.knowledge-import-note { color:var(--rs-text-3);margin:18px 0 0; }
.knowledge-import-error { display:flex; align-items:flex-start; gap:6px; margin:12px 0 0; padding:9px 12px; border:1px solid color-mix(in srgb, var(--rs-danger) 30%, var(--rs-border)); background:color-mix(in srgb, var(--rs-danger) 5%, var(--rs-bg-card)); border-radius:6px; color:var(--rs-danger); overflow-wrap:anywhere; }
.knowledge-import-error svg { width:14px; height:14px; flex-shrink:0; margin-top:2px; }
</style>
