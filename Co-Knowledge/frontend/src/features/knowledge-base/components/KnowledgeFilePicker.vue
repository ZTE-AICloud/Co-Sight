<template>
  <div class="knowledge-file-picker">
    <!-- 文件选择框用「覆盖整块区域的透明 input」而不是 script 里 input.click()：
         原生 label/input 激活不依赖模板 ref 是否有效，也没有隐藏 input 不弹框的浏览器差异。 -->
    <label :class="['kb-dropzone', { 'is-dragging': dragDepth > 0 }]" @dragenter.prevent="dragDepth++" @dragover.prevent @dragleave.prevent="dragDepth = Math.max(0, dragDepth - 1)" @drop.prevent="onDrop">
      <input class="kb-upload-input" type="file" :accept="acceptAttr" multiple @change="onFileChange"/>
      <span class="kb-upload-icon"><UploadFilled/></span>
      <span class="kb-upload-title text-body">{{ $t('modules.studioDialogs.createKnowledge.dropzone') }}<span>{{ $t('modules.studioDialogs.createKnowledge.dropzoneAction') }}</span></span>
      <span class="kb-upload-caption text-caption">{{ $t('modules.studioDialogs.createKnowledge.dropzoneCaption') }}</span>
    </label>
    <div class="kb-upload-meta text-caption">
      <span>{{ limitSummary }}</span>
      <details class="kb-file-limits">
        <summary>{{ $t('modules.studioDialogs.createKnowledge.fileLimits') }}<ArrowDown/></summary>
        <div class="kb-limits-popover">
          <div v-for="group in activeLimits" :key="group.maxMB"><span>{{ group.extensions.join(' / ').toUpperCase() }}</span><b>≤ {{ group.maxMB }} MB</b></div>
          <p>{{ $t('modules.studioDialogs.createKnowledge.fileLimitsNote') }}</p>
        </div>
      </details>
    </div>
    <div v-if="uploadErrors.length" class="kb-upload-errors text-caption" role="alert">
      <div class="kb-errors-heading"><WarningFilled/><span>{{ $t('modules.studioDialogs.createKnowledge.partialErrors') }}</span><button type="button" class="icon-button" :aria-label="$t('modules.studioDialogs.createKnowledge.closeErrors')" @click="uploadErrors = []"><Close/></button></div>
      <ul><li v-for="error in uploadErrors" :key="error">{{ error }}</li></ul>
    </div>

    <div class="kb-files-heading text-secondary">
      <span>{{ title || $t('modules.studioDialogs.createKnowledge.filesHeading') }} <b class="kb-file-count text-caption">{{ files.length }}</b></span>
      <el-button v-if="files.length" link type="primary" @click="clear">{{ $t('modules.studioDialogs.createKnowledge.clearFiles') }}</el-button>
      <span v-else class="text-caption">{{ $t('modules.studioDialogs.createKnowledge.filesPlaceholder') }}</span>
    </div>
    <div v-if="!files.length" class="kb-files-empty text-secondary"><Document/><span>{{ $t('modules.studioDialogs.createKnowledge.filesEmpty') }}</span></div>
    <ul v-else class="kb-file-list" :aria-label="title || $t('modules.studioDialogs.createKnowledge.filesHeading')">
      <li v-for="file in files" :key="fileKey(file)">
        <span :class="['kb-file-icon', fileTone(file)]"><Document/></span>
        <div class="kb-file-info"><span class="text-secondary" :title="file.name">{{ file.name }}</span><span class="text-caption">{{ $t('modules.studioDialogs.createKnowledge.localFile') }} · {{ formatFileSize(file.size) }}</span></div>
        <span class="kb-file-status text-caption"><span/>{{ $t('modules.studioDialogs.createKnowledge.pendingImport') }}</span>
        <button type="button" class="icon-button" :aria-label="$t('modules.studioDialogs.createKnowledge.removeFile', { name: file.name })" @click="removeFile(file)"><Close/></button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Document, UploadFilled, ArrowDown, WarningFilled, Close } from '@element-plus/icons-vue'
import { fileLimits, fileKey, formatFileSize, collectKnowledgeFiles } from '../lib/knowledge-files'

const files = defineModel({ type: Array, default: () => [] })
const props = defineProps({
  /** 文件列表标题（待导入文件 / 新增文件） */
  title: { type: String, default: '' },
  /** 编辑页已有的来源文件：只参与查重与总数，不在这里展示 */
  existingFiles: { type: Array, default: () => [] },
  activeFileLimits: { type: Array, default: () => fileLimits },
  maxFiles: { type: Number, default: 50 },
  maxTotalBytes: { type: Number, default: 650 * 1024 ** 2 }
})

const { t } = useI18n()
const uploadErrors = ref([])
const dragDepth = ref(0)

const activeLimits = computed(() => (
  Array.isArray(props.activeFileLimits) && props.activeFileLimits.length
    ? props.activeFileLimits
    : fileLimits
))
const acceptAttr = computed(() => activeLimits.value
  .flatMap(group => (group.extensions || []).map(extension => `.${extension}`))
  .join(','))
const limitSummary = computed(() => {
  const mb = props.maxTotalBytes / 1024 ** 2
  const size = Number.isInteger(mb) ? `${mb} MB` : formatFileSize(props.maxTotalBytes)
  return t('modules.studioDialogs.createKnowledge.limitSummary', { files: props.maxFiles, size })
})

function addFiles (incoming) {
  const existing = props.existingFiles
  // 已有来源没有 lastModified，fileKey 比不全：先按「名称 + 大小」挡掉重复添加
  const existingKey = new Set(existing.map(file => `${file.name}:${file.size}`))
  const errors = []
  const incomingFiles = Array.from(incoming || []).filter((file) => {
    if (existingKey.has(`${file.name}:${file.size}`)) {
      errors.push(`${file.name}：${t('modules.studioDialogs.createKnowledge.errorDuplicate')}`)
      return false
    }
    return true
  })
  const result = collectKnowledgeFiles([...existing, ...files.value], incomingFiles, {
    limits: activeLimits.value,
    maxFiles: props.maxFiles,
    maxTotalBytes: props.maxTotalBytes,
    messages: {
      format: t('modules.studioDialogs.createKnowledge.errorFormat'),
      empty: t('modules.studioDialogs.createKnowledge.errorEmpty'),
      tooLarge: max => t('modules.studioDialogs.createKnowledge.errorTooLarge', { max }),
      duplicate: t('modules.studioDialogs.createKnowledge.errorDuplicate'),
      tooMany: max => t('modules.studioDialogs.createKnowledge.errorTooMany', { max }),
      totalTooLarge: max => t('modules.studioDialogs.createKnowledge.errorTotalTooLarge', { max }),
      batchRejected: (reason, count) => t('modules.studioDialogs.createKnowledge.errorBatchRejected', { reason, count })
    }
  })
  files.value = result.files.filter(file => !existing.includes(file))
  uploadErrors.value = [...errors, ...result.errors]
}
function onFileChange (event) {
  addFiles(event.target.files)
  event.target.value = ''
}
function onDrop (event) {
  dragDepth.value = 0
  addFiles(event.dataTransfer.files)
}
function removeFile (file) {
  files.value = files.value.filter(item => fileKey(item) !== fileKey(file))
}
function clear () {
  files.value = []
  uploadErrors.value = []
}
function fileTone (file) {
  if (/\.(pdf|pptx)$/i.test(file.name)) {
    return 'orange'
  }
  return /\.(xlsx|csv|json)$/i.test(file.name) ? 'green' : 'blue'
}

defineExpose({ clear })
</script>

<style>
.kb-dropzone { position: relative; width: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 22px 16px; border: 1px dashed var(--rs-primary-border); border-radius: 8px; background: var(--rs-bg-hover); color: var(--rs-text); cursor: pointer; transition: background .15s, border-color .15s; }
.kb-dropzone:hover, .kb-dropzone.is-dragging { border-color: var(--rs-primary); background: var(--rs-bg-selected); }
.kb-dropzone:has(.kb-upload-input:focus-visible) { outline: 2px solid var(--rs-primary); outline-offset: 2px; }
/* 透明 input 铺满整块拖拽区：鼠标点击直接落在原生 input 上，不再走脚本 input.click()。 */
.kb-upload-input { position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; font-size: 0; }
.kb-dropzone > :not(.kb-upload-input) { pointer-events: none; }
.kb-upload-icon { width: 42px; height: 42px; display: flex; align-items: center; justify-content: center; border-radius: 10px; background: var(--rs-bg-selected); color: var(--rs-primary); margin-bottom: 12px; }
.kb-upload-icon svg { width: 26px; height: 26px; }
.kb-upload-title > span { color: var(--rs-primary); margin-left: 4px; font-weight: 500; }
.kb-upload-caption { color: var(--rs-text-3); margin-top: 6px; }
.kb-upload-meta { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 12px; margin-top: 10px; color: var(--rs-text-3); }
.kb-file-limits { position: relative; flex-shrink: 0; }
.kb-file-limits[open] { flex-basis: 100%; }
.kb-file-limits[open] summary { justify-content: flex-end; }
.kb-file-limits summary { list-style: none; display: flex; align-items: center; gap: 4px; color: var(--rs-text-2); cursor: pointer; }
.kb-file-limits summary::-webkit-details-marker { display: none; }
.kb-file-limits summary svg { width: 12px; height: 12px; transition: transform .15s; }
.kb-file-limits[open] summary svg { transform: rotate(180deg); }
.kb-file-limits summary:focus-visible { outline: 2px solid var(--rs-primary); outline-offset: 3px; }
.kb-limits-popover { margin-top: 8px; width: 100%; padding: 12px 16px; border-radius: 8px; border: 1px solid var(--rs-border); background: var(--rs-bg-soft); }
.kb-limits-popover > div { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; }
.kb-limits-popover b { font-weight: 500; white-space: nowrap; color: var(--rs-text-2); }
.kb-limits-popover p { margin: 8px 0 0; padding-top: 8px; border-top: 1px solid var(--rs-border-soft); }
.kb-files-heading { display: flex; justify-content: space-between; align-items: center; margin: 22px 0 10px; color: var(--rs-text-2); }
.kb-files-heading > span { display: flex; align-items: center; gap: 8px; }
.kb-files-heading > span:last-child { color: var(--rs-text-3); }
.kb-files-heading .el-button { font-size: var(--rs-font-size-caption); }
.kb-file-count { background: var(--rs-bg-soft); color: var(--rs-text-2); padding: 0 7px; border-radius: 4px; font-weight: 500; }
.kb-files-empty { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 56px; border: 1px solid var(--rs-border-soft); border-radius: 6px; color: var(--rs-text-3); }
.kb-files-empty svg { width: 17px; height: 17px; }
.kb-file-list { margin: 0; padding: 0; list-style: none; max-height: 210px; overflow-y: auto; border: 1px solid var(--rs-border); border-radius: 8px; }
.kb-file-list li { display: flex; align-items: center; gap: 12px; padding: 12px 14px; }
.kb-file-list li + li { border-top: 1px solid var(--rs-border-soft); }
.kb-file-icon { display: flex; align-items: center; justify-content: center; width: 34px; height: 38px; border-radius: 6px; background: var(--tint); color: var(--tone); }
.kb-file-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.kb-file-info > span:first-child { color: var(--rs-text); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.kb-file-info > span:last-child { color: var(--rs-text-3); }
.kb-file-status { color: var(--rs-text-2); display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.kb-file-status > span { width: 6px; height: 6px; border-radius: 50%; background: var(--rs-text-3); }
.kb-file-list .icon-button svg { width: 15px; height: 15px; }
.kb-upload-errors { margin-top: 12px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--rs-danger) 30%, var(--rs-border)); background: color-mix(in srgb, var(--rs-danger) 5%, var(--rs-bg-card)); border-radius: 6px; color: var(--rs-danger); overflow-wrap: anywhere; }
.kb-errors-heading { display: flex; align-items: center; gap: 6px; }
.kb-errors-heading > svg { width: 14px; height: 14px; }
.kb-errors-heading .icon-button { margin-left: auto; height: 20px; }
.kb-upload-errors ul { max-height: 100px; overflow-y: auto; margin: 4px 0 0; padding-left: 20px; }
@media (max-width: 600px) {
  .kb-upload-meta { flex-direction: column; gap: 6px; }
  .kb-file-status { display: none; }
}
</style>
