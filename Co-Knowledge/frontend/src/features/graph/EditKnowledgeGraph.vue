<template>
  <WorkspaceShell
    class="graph-edit-page"
    back="/graph"
    :parent="$t('modules.kb.graphKnowledgeBase')"
    :context="$t('modules.kb.editKnowledgeGraph')"
    :title="$t('modules.kb.editKnowledgeGraph')"
    :icon="Edit"
  >
    <template v-if="graphReady" #subtitle>
      <span class="tag-soft purple">{{ $t('modules.kb.knowledgeGraph') }}</span>
      <span>{{ formData.name }}</span>
    </template>
    <template v-if="graphReady" #actions>
      <RouterLink :to="detailLocation" class="gx-view-link text-secondary">
        <Share />{{ $t('modules.kb.graphEditViewGraph') }}
      </RouterLink>
    </template>

    <template v-if="graphReady">
      <div ref="scrollArea" class="gx-scroll">
        <el-form class="studio-form gx-layout" label-position="top" @submit.prevent="save" @keydown.ctrl.enter.prevent="save">
          <div class="gx-main-column">
            <FormSection number="01" :title="$t('modules.kb.basicInfo')" :note="$t('modules.kb.graphEditBasicNote')" class="gx-card">
              <el-form-item :label="$t('modules.kb.knowledgeGraphName')" required :error="errorText(errors.name)">
                <el-input
                  v-model="formData.name"
                  :aria-label="$t('modules.kb.knowledgeGraphName')"
                  :placeholder="$t('modules.kb.pleaseInputKnowledgeGraphName')"
                  maxlength="30"
                  show-word-limit
                  @input="errors.name = ''"
                />
              </el-form-item>
              <el-form-item :error="errorText(errors.description)">
                <template #label>
                  {{ $t('modules.kb.knowledgeGraphDescription') }}<span class="studio-optional">{{ $t('modules.studioDialogs.common.optional') }}</span>
                </template>
                <el-input
                  v-model="formData.description"
                  :aria-label="$t('modules.kb.knowledgeGraphDescription')"
                  type="textarea"
                  :autosize="{ minRows: 2, maxRows: 6 }"
                  maxlength="1000"
                  show-word-limit
                  :placeholder="$t('modules.kb.pleaseInputKnowledgeGraphDescription')"
                  @input="errors.description = ''"
                />
              </el-form-item>
            </FormSection>

            <FormSection number="02" :title="$t('modules.kb.graphEditSectionDocuments')" :note="$t('modules.kb.localFile')" class="gx-card gx-documents">
              <p class="gx-section-intro text-secondary">{{ $t('modules.kb.graphEditDocumentsIntro') }}</p>
              <div v-if="originalFiles.length" class="gx-existing">
                <div class="gx-files-heading text-secondary">
                  <span>{{ $t('modules.kb.graphEditExistingHeading') }} <b class="text-caption">{{ existingFiles.length }}</b></span>
                  <el-button v-if="removedCount" type="primary" link @click="restoreRemoved">
                    {{ $t('modules.kb.graphEditRestore', { count: removedCount }) }}
                  </el-button>
                </div>
                <ul v-if="existingFiles.length" class="gx-existing-files" :aria-label="$t('modules.kb.graphEditExistingHeading')">
                  <li v-for="file in existingFiles" :key="file.id">
                    <span class="gx-file-symbol"><Document /></span>
                    <div>
                      <span :title="file.title" class="text-secondary">{{ file.title }}</span>
                      <span class="text-caption">{{ formatFileSize(file.fileSize) }} · {{ $t('modules.kb.localFileSource') }}</span>
                    </div>
                    <span class="gx-retained text-caption">{{ $t('modules.kb.graphEditRetained') }}</span>
                    <button type="button" class="icon-button" :aria-label="$t('modules.kb.graphEditRemoveExisting', { name: file.title })" @click="removeExisting(file.id)">
                      <Close />
                    </button>
                  </li>
                </ul>
                <p v-else class="gx-no-retained text-caption">{{ $t('modules.kb.graphEditAllRemoved') }}</p>
              </div>
              <KnowledgeFilePicker
                v-model="newFiles"
                :title="$t('modules.kb.graphEditNewFiles')"
                :existing-files="existingFileInputs"
                :active-file-limits="fileLimitGroups"
                :max-files="fileLimitCount"
              />
            </FormSection>
          </div>

          <FormSection number="03" :title="$t('modules.kb.knowledgeGraphBuildConfig')" class="gx-card gx-build">
            <div class="gx-locked-heading text-caption"><Lock />{{ $t('modules.kb.graphEditLockedHeading') }}</div>
            <dl class="gx-locked-config">
              <div>
                <dt class="text-caption">{{ $t('modules.kb.graphInfoEmbeddingModel') }}</dt>
                <dd class="text-secondary"><LayersIcon /><span>{{ formData.embeddingModel || $t('modules.kb.graphInfoNotConfigured') }}</span><Lock /></dd>
              </div>
              <div>
                <dt class="text-caption">{{ $t('modules.kb.graphInfoOperator') }}</dt>
                <!-- 算子缺失（导入生成的图谱 operatorId 为空 / 原算子被删除）时不再死锁：
                     允许现场选一个可用的抽取算子，否则「修改知识图谱」永远是死路。 -->
                <dd v-if="!operatorNotFound" class="text-secondary"><Setting /><span>{{ operatorName || $t('modules.kb.graphInfoNotConfigured') }}</span><Lock /></dd>
                <dd v-else class="text-secondary gx-operator-repair">
                  <Setting />
                  <el-select
                    v-model="repairOperatorId"
                    class="gx-operator-select"
                    :placeholder="$t('modules.kb.selectOperator')"
                    filterable
                    @change="handleRepairOperator"
                  >
                    <el-option
                      v-for="op in operatorList"
                      :key="op.id"
                      :label="operatorLabel(op)"
                      :value="String(op.id)"
                    />
                  </el-select>
                </dd>
              </div>
              <div>
                <dt class="text-caption">{{ $t('modules.kb.graphInfoTemplateName') }}</dt>
                <dd class="text-secondary"><Collection /><span>{{ schemaInfo?.schema_name || $t('modules.kb.graphInfoNoTemplate') }}</span><Lock /></dd>
              </div>
            </dl>
            <div class="gx-config-divider" />
            <el-alert v-if="operatorNotFound" type="warning" show-icon :closable="false" class="gx-alert">
              <p>{{ operatorWasUnset ? $t('modules.kb.operatorMissingForImported') : $t('modules.kb.operatorNotFoundWarning') }}</p>
            </el-alert>
            <el-alert v-if="templateNotFound" type="warning" show-icon :closable="false" class="gx-alert">
              <p>{{ $t('modules.kb.templateNotFoundWarning') }}</p>
            </el-alert>
            <el-form label-position="top" class="gx-arg-form" @submit.prevent>
              <OperatorArgsForm
                :operator-args="operatorArgs"
                :dynamic-params="dynamicParams"
                :schema-info="schemaInfo"
                :template-not-found="templateNotFound"
                :current-operator="currentOperator"
                :template-list="templateList"
                :llm-model-list="llmModelList"
                @update:dynamic-params="updateDynamicParams"
              />
            </el-form>
            <p v-if="firstParamError" class="gx-param-error text-caption" role="alert">{{ firstParamError }}</p>
            <div class="gx-build-note text-caption"><InfoFilled /><span>{{ $t('modules.kb.graphEditLockedNote') }}</span></div>
          </FormSection>
        </el-form>
      </div>

      <footer class="gx-footer">
        <div class="gx-save-status">
          <span :class="['gx-dirty-dot', { dirty }]" />
          <div>
            <span class="text-secondary" role="status">{{ dirty ? $t('modules.kb.graphEditDirty') : $t('modules.kb.graphEditSynced') }}</span>
            <p class="text-caption">{{ totalFiles ? $t('modules.kb.graphEditFileSummary', { count: totalFiles, size: formatFileSize(totalBytes) }) : $t('modules.kb.graphEditNoFilesHint') }}</p>
          </div>
        </div>
        <div class="gx-footer-actions">
          <el-button class="button-compact" @click="goBack">{{ $t('public.cancel') }}</el-button>
          <el-button class="button-compact" type="primary" :loading="buildLoading" :disabled="!canBuild" @click="save">
            <Connection />{{ $t('modules.kb.graphEditSaveBuild') }}
          </el-button>
        </div>
      </footer>
    </template>

    <div v-else class="workspace-empty">
      <p class="text-body">{{ $t('modules.kb.graphEditNotFound') }}</p>
      <RouterLink to="/graph">{{ $t('modules.kb.graphEditBackToList') }}</RouterLink>
    </div>
  </WorkspaceShell>
</template>

<script lang="ts" setup>
import { computed, getCurrentInstance, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Edit, Share, Document, Close, Lock, Setting, Collection, InfoFilled, Connection } from '@element-plus/icons-vue'
import { LayersIcon } from '@/shared/ui/icons'
import WorkspaceShell from '@/app/layout/WorkspaceShell.vue'
import FormSection from '@/shared/ui/FormSection.vue'
import KnowledgeFilePicker from '@/features/knowledge-base/components/KnowledgeFilePicker.vue'
import OperatorArgsForm from './components/OperatorArgsForm.vue'
import { useOperatorValidation } from './composables/useOperatorValidation'
import { useFileUpload } from './composables/useFileUpload'
import { useKnowledgeGraphForm } from './composables/useKnowledgeGraphForm'
import { useKnowledgeGraphBuild } from './composables/useKnowledgeGraphBuild'
import { validateGraphEditDraft, graphEditSnapshot, type GraphEditErrors } from './lib/graph-edit'
import { fileKey, formatFileSize } from '@/features/knowledge-base/lib/knowledge-files'

const { proxy } = getCurrentInstance() as any
const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const {
  formData,
  step2Form,
  buildLoading,
  knowledgeGraphId,
  schemaInfo,
  fetchKnowledgeGraphInfo,
  handleBuild: handleBuildBase
} = useKnowledgeGraphForm()

const {
  operatorList,
  llmModelList,
  templateList,
  operatorNotFound,
  currentOperator,
  templateNotFound,
  dynamicParams,
  operatorArgs,
  validateOperator
} = useOperatorValidation()

const {
  uploadedFiles,
  existingFiles,
  fileLimit,
  deletedFiles,
  remainingFiles,
  allFiles,
  loadFileLimit,
  loadExistingFiles,
  removeFile,
  restoreFile
} = useFileUpload()

const { canBuild } = useKnowledgeGraphBuild(
  formData,
  step2Form,
  operatorNotFound,
  templateNotFound,
  allFiles,
  operatorArgs,
  dynamicParams
)

const graphReady = ref(false)
const scrollArea = ref<HTMLElement | null>(null)
const newFiles = ref<File[]>([])
const originalFiles = ref<any[]>([])
const originalSnapshot = ref('')
const errors = ref<GraphEditErrors>({ name: '', description: '', params: {} })
// 算子修复：原 operatorId 为空（导入生成的图谱）或指向已删除的算子时，
// 允许在页内重新选一个，否则该图谱永远无法保存构建。
const repairOperatorId = ref('')
const operatorWasUnset = ref(false)

const detailLocation = computed(() => ({ name: 'graph-detail', params: { id: route.params.id } }))
const operatorName = computed(() => {
  const operator = operatorList.value.find((item: any) => String(item?.id) === String(dynamicParams.operatorId))
  if (!operator) {
    return ''
  }
  return proxy?.$i18n?.locale === 'zh'
    ? operator.name || operator.nameEn || ''
    : operator.nameEn || operator.name || ''
})
const removedCount = computed(() => originalFiles.value.length - existingFiles.value.length)
const totalFiles = computed(() => existingFiles.value.length + newFiles.value.length)
const totalBytes = computed(() => (
  existingFiles.value.reduce((sum: number, file: any) => sum + (Number(file.fileSize) || 0), 0) +
  newFiles.value.reduce((sum: number, file: File) => sum + file.size, 0)
))
const existingFileInputs = computed(() => existingFiles.value.map((file: any) => ({
  name: file.title,
  size: Number(file.fileSize) || 0
})))
const fileLimitGroups = computed(() => (
  fileLimit.value?.maxSizeMap
    ? Object.entries(fileLimit.value.maxSizeMap).map(([extension, maxMB]) => ({
      extensions: [extension],
      maxMB: Number(maxMB)
    }))
    : []
))
const fileLimitCount = computed(() => Number(fileLimit.value?.number) || 50)

const snapshot = () => graphEditSnapshot({
  draft: {
    name: formData.name,
    description: formData.description,
    params: { ...dynamicParams }
  },
  retainedFileIds: existingFiles.value.map((file: any) => String(file.id)),
  newFileKeys: newFiles.value.map(file => fileKey(file))
})
const dirty = computed(() => originalSnapshot.value !== '' && snapshot() !== originalSnapshot.value)

function errorText (code: string) {
  switch (code) {
    case 'nameRequired': return t('modules.kb.graphEditNameRequired')
    case 'nameFormat': return t('modules.kb.graphEditNameFormat')
    case 'descriptionTooLong': return t('modules.kb.graphEditDescriptionTooLong')
    default: return ''
  }
}

function paramErrorText (code: string) {
  switch (code) {
    case 'required': return t('modules.studioDialogs.createKnowledge.argRequired')
    case 'integer': return t('modules.studioDialogs.createKnowledge.argInteger')
    case 'chunkSizeRange': return t('modules.studioDialogs.createKnowledge.argChunkSizeRange')
    case 'overlapRange': return t('modules.studioDialogs.createKnowledge.argOverlapRange')
    case 'overlapLessThanChunkSize': return t('modules.studioDialogs.createKnowledge.argOverlapLessThanChunkSize')
    default: return ''
  }
}

const firstParamError = computed(() => {
  const entries = Object.entries(errors.value.params || {})
  const first = entries.find(([, code]) => Boolean(code))
  return first ? t('modules.kb.graphEditParamError', { error: paramErrorText(first[1]) }) : ''
})

function updateDynamicParams (nextParams: any) {
  Object.keys(dynamicParams).forEach((key) => delete dynamicParams[key])
  Object.assign(dynamicParams, nextParams)
  errors.value = { ...errors.value, params: {} }
}

function operatorLabel (operator: any) {
  return proxy?.$i18n?.locale === 'zh'
    ? operator.name || operator.nameEn || ''
    : operator.nameEn || operator.name || ''
}

/** 算子缺失时现场补选：清掉旧参数后按新算子的 args 重新初始化。 */
async function handleRepairOperator (operatorId: string) {
  if (!operatorId) {
    return
  }
  Object.keys(dynamicParams).forEach((key) => delete dynamicParams[key])
  step2Form.config.operator = String(operatorId)
  await validateOperator(operatorId, schemaInfo.value)
  if (!operatorNotFound.value) {
    repairOperatorId.value = String(operatorId)
  }
}

function removeExisting (id: string) {
  const index = allFiles.value.findIndex((file: any) => !file.isUploaded && file.id === id)
  if (index > -1) {
    removeFile(index)
  }
}

function restoreRemoved () {
  const missing = originalFiles.value.filter((file: any) => !existingFiles.value.some((item: any) => item.id === file.id))
  missing.forEach(file => restoreFile({ ...file }))
}

function goBack () {
  router.push(detailLocation.value)
}

async function save () {
  errors.value = validateGraphEditDraft({
    name: formData.name,
    description: formData.description,
    params: dynamicParams
  }, operatorArgs.value)
  if (errors.value.name || errors.value.description || Object.keys(errors.value.params).length) {
    await nextTick()
    scrollArea.value?.querySelector('.is-error')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    return
  }
  await handleBuildBase(canBuild, uploadedFiles, deletedFiles, remainingFiles, dynamicParams, router)
}

// 新增文件 → 走既有上传链路（handleBuildBase 只认 uploadedFiles）
watch(newFiles, (files) => {
  uploadedFiles.value = files.map(file => ({
    title: file.name,
    fileSize: file.size,
    raw: file,
    isUploaded: true
  }))
})

// 已有来源首次加载完成后记下基线（之后的变化都算脏）
watch(existingFiles, (files) => {
  if (originalSnapshot.value || !files.length) {
    return
  }
  originalFiles.value = files.map((file: any) => ({ ...file }))
  originalSnapshot.value = snapshot()
}, { deep: true })

async function loadPage () {
  const requestId = route.params.id
  graphReady.value = false
  // 切到另一个图谱（或无效 ID）时先清空上一个图谱的状态：组件实例会被复用，
  // 不清空的话请求失败时页面仍显示上一个图谱的名称与来源文件。
  existingFiles.value = []
  remainingFiles.value = []
  uploadedFiles.value = []
  deletedFiles.value = []
  newFiles.value = []
  originalFiles.value = []
  originalSnapshot.value = ''
  operatorWasUnset.value = false
  step2Form.config.operator = ''
  step2Form.config.template = ''
  step2Form.config.llmModel = ''
  step2Form.config.prompt = ''

  const res = await fetchKnowledgeGraphInfo(route, router)
  // 连续切换 ID 时旧请求可能后返回：只认当前 URL 对应的结果。
  if (!res || route.params.id !== requestId) {
    return
  }
  await loadFileLimit()
  await loadExistingFiles(knowledgeGraphId.value, () => route.params.id === requestId)
  if (route.params.id !== requestId) {
    return
  }
  operatorWasUnset.value = res.data?.operatorId === null || res.data?.operatorId === undefined
  await validateOperator(
    res.data?.operatorId,
    schemaInfo.value,
    () => route.params.id === requestId
  )
  if (route.params.id !== requestId) {
    return
  }
  if (!operatorWasUnset.value) {
    step2Form.config.operator = String(res.data.operatorId)
  }
  originalFiles.value = existingFiles.value.map((file: any) => ({ ...file }))
  originalSnapshot.value = snapshot()
  graphReady.value = true
}

onMounted(loadPage)

// 同一路由只变参数时组件会被复用：重新加载，避免继续编辑上一个图谱。
watch(() => route.params.id, (id, previous) => {
  if (!id || id === previous) {
    return
  }
  loadPage()
})
</script>

<style lang="less" scoped>
.graph-edit-page {
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.gx-view-link { display: inline-flex; align-items: center; gap: 7px; color: var(--rs-text-2); }
.gx-view-link:hover { color: var(--rs-primary); }
.gx-view-link svg { width: 15px; height: 15px; }
.gx-scroll { flex: 1; min-height: 0; overflow: auto; container-type: inline-size; }
.gx-layout { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 20px; align-items: start; width: 100%; margin: 0; }
.gx-main-column { display: flex; flex-direction: column; gap: 20px; min-width: 0; }
.gx-card.studio-form-section { min-width: 0; padding: 22px 24px; background: var(--rs-bg-card); border: 1px solid var(--rs-border); border-radius: var(--rs-radius); }
.gx-section-intro { margin: -3px 0 18px; color: var(--rs-text-3); line-height: 1.7; }
.gx-files-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 0 0 12px; color: var(--rs-text-2); flex-wrap: wrap; }
.gx-files-heading b { display: inline-block; margin-left: 5px; padding: 0 6px; background: var(--rs-bg-soft); border-radius: 4px; color: var(--rs-text-3); font-weight: 500; }
.gx-files-heading .el-button { font-size: var(--rs-font-size-caption); }
.gx-existing { margin-bottom: 20px; }
.gx-existing-files { list-style: none; padding: 0; margin: 0; max-height: 220px; overflow-y: auto; border: 1px solid var(--rs-border); border-radius: 8px; }
.gx-existing-files li { display: flex; align-items: center; gap: 10px; padding: 12px; }
.gx-existing-files li + li { border-top: 1px solid var(--rs-border-soft); }
.gx-file-symbol { display: grid; place-items: center; width: 32px; height: 36px; background: var(--rs-bg-selected); color: var(--rs-primary); border-radius: 6px; flex-shrink: 0; }
.gx-existing-files li > div { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.gx-existing-files li > div > span:first-child { color: var(--rs-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gx-existing-files li > div > span:last-child { color: var(--rs-text-3); }
.gx-retained { color: var(--rs-text-3); flex-shrink: 0; }
.gx-no-retained { padding: 12px; background: var(--rs-bg-soft); color: var(--rs-text-3); border-radius: 6px; margin: 0; }
.gx-locked-heading { display: flex; align-items: center; gap: 6px; color: var(--rs-text-3); margin-bottom: 14px; }
.gx-locked-heading svg { width: 13px; height: 13px; }
.gx-locked-config { margin: 0; padding: 14px; background: var(--rs-bg-soft); border: 1px solid var(--rs-border-soft); border-radius: 8px; }
.gx-locked-config > div + div { margin-top: 13px; }
.gx-locked-config dt { color: var(--rs-text-3); margin-bottom: 6px; }
.gx-locked-config dd { display: flex; align-items: flex-start; gap: 8px; margin: 0; color: var(--rs-text-2); line-height: 1.6; }
.gx-locked-config dd span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.gx-locked-config dd svg { width: 15px; height: 15px; margin-top: 3px; color: var(--rs-text-3); }
.gx-locked-config dd svg:first-child { color: var(--rs-primary); }
.gx-locked-config dd svg:last-child { width: 12px; height: 12px; }
.gx-locked-config dd.gx-operator-repair { align-items: center; }
.gx-locked-config dd.gx-operator-repair svg { width: 15px; height: 15px; margin-top: 0; flex-shrink: 0; }
.gx-operator-select { flex: 1; min-width: 0; }
.gx-config-divider { border-top: 1px solid var(--rs-border-soft); margin: 20px 0; }
.gx-alert { margin-bottom: 16px; }
.gx-arg-form :deep(.el-form-item) { margin-bottom: 20px; }
.gx-arg-form :deep(.el-form-item:last-child) { margin-bottom: 0; }
.gx-param-error { margin: 8px 0 0; color: var(--rs-danger); }
.gx-build-note { display: flex; align-items: flex-start; gap: 6px; margin-top: 14px; color: var(--rs-text-3); line-height: 1.7; }
.gx-build-note svg { width: 13px; height: 13px; margin-top: 3px; }
.gx-footer { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 16px 0 0; margin-top: 6px; border-top: 1px solid var(--rs-border); flex-shrink: 0; background: var(--rs-bg-page); }
.gx-save-status { display: flex; align-items: flex-start; gap: 8px; color: var(--rs-text-2); }
.gx-save-status p { margin: 4px 0 0; color: var(--rs-text-3); }
.gx-dirty-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--rs-success); margin-top: 8px; flex-shrink: 0; }
.gx-dirty-dot.dirty { background: var(--rs-warning); }
.gx-footer-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.gx-footer-actions .el-button + .el-button { margin-left: 0; }
@container (max-width: 850px) { .gx-layout { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 700px) {
  .gx-footer { flex-direction: column; align-items: stretch; gap: 12px; }
  .gx-footer-actions { justify-content: flex-end; flex-wrap: wrap; }
  .gx-card.studio-form-section { padding: 20px 16px; }
  .gx-layout, .gx-main-column { gap: 16px; }
  .gx-retained { display: none; }
}
</style>
