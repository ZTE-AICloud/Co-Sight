<template>
  <WorkspaceShell
    back="/knowledge"
    :parent="$t('modules.kb.dockb')"
    :context="isDocuments ? $t('modules.studioDialogs.knowledgeDetail.contextDocuments') : $t('modules.studioDialogs.knowledgeDetail.context')"
    :title="knowledge?.name || $t('modules.studioDialogs.knowledgeDetail.notFound')"
    :icon="Collection"
    :focused="focused"
    :focus-text="$t('modules.studioDialogs.knowledgeDetail.focusMode')"
    :exit-focus-text="$t('modules.studioDialogs.knowledgeDetail.exitFocus')"
    class="knowledge-detail"
    @toggle-focus="focused = !focused"
  >
    <template v-if="knowledge" #subtitle>
      <span :class="['tag-soft', statusMeta.tone === 'success' ? 'green' : statusMeta.tone === 'danger' ? 'kd-error-status' : 'orange']"><span :class="['status-dot', statusMeta.tone]" />{{ statusMeta.text }}</span>
      <span class="workspace-subtitle-text" :title="knowledge.description || ''">{{ knowledge.description || $t('modules.studioDialogs.knowledgeDetail.noDescription') }}</span>
    </template>
    <template v-if="knowledge" #actions>
      <el-button v-if="isDocuments" class="button-compact" @click="goDetail"><LayersIcon />{{ $t('modules.studioDialogs.knowledgeDetail.viewChunks') }}</el-button>
      <el-button v-else class="button-compact" type="primary" @click="goDocuments"><FolderOpened />{{ $t('modules.studioDialogs.knowledgeDetail.documents') }}</el-button>
    </template>

    <template v-if="knowledge">
      <div class="kd-overview">
        <div v-for="metric in metrics" :key="metric.label" class="kd-metric"><span :class="['kd-metric-icon', metric.tone]"><component :is="metric.icon" /></span><div><span class="text-caption muted">{{ metric.label }}</span><div class="kd-metric-value">{{ metric.value }}<span v-if="metric.unit" class="text-caption muted">{{ metric.unit }}</span></div></div></div>
        <div class="kd-model"><span class="kd-model-symbol purple"><LayersIcon /></span><div><span class="text-caption muted">{{ $t('modules.studioDialogs.knowledgeDetail.embeddingModel') }}</span><div class="text-secondary text-label">{{ knowledge.model || '--' }}</div></div><span class="tag-soft purple">{{ $t('modules.studioDialogs.knowledgeDetail.vectorSearch') }}</span></div>
      </div>

      <template v-if="!isDocuments">
        <el-tabs v-model="tab" class="workspace-tabs kd-tabs" :aria-label="$t('modules.studioDialogs.knowledgeDetail.context')"><el-tab-pane name="chunks"><template #label><span class="kd-tab-label"><Grid />{{ $t('modules.studioDialogs.knowledgeDetail.tabChunks') }}<span class="kd-count">{{ overallChunkTotal }}</span></span></template></el-tab-pane><el-tab-pane name="info"><template #label><span class="kd-tab-label"><InfoFilled />{{ $t('modules.studioDialogs.knowledgeDetail.tabInfo') }}</span></template></el-tab-pane></el-tabs>
        <template v-if="tab === 'chunks'">
          <div class="workspace-toolbar"><div class="workspace-toolbar-group kd-search-group"><el-input v-model="search" :prefix-icon="Search" clearable :placeholder="$t('modules.studioDialogs.knowledgeDetail.searchChunksPlaceholder')" :aria-label="$t('modules.studioDialogs.knowledgeDetail.searchChunks')" class="kd-search" /><el-select v-model="sourceId" filterable clearable :placeholder="$t('modules.studioDialogs.knowledgeDetail.allSources')" :aria-label="$t('modules.studioDialogs.knowledgeDetail.allSources')" class="kd-source"><el-option v-for="file in allFiles" :key="file.id" :label="file.title" :value="file.id" /></el-select></div><div class="kd-view-control"><TableRefreshButton :key="kbId" :label="$t('modules.studioDialogs.knowledgeDetail.refreshChunks')" :refresh="refreshChunks" compact /><span class="text-caption muted">{{ $t('modules.studioDialogs.knowledgeDetail.view') }}</span><button :class="{ active: view === 'grid' }" :aria-label="$t('modules.studioDialogs.knowledgeDetail.cardView')" :aria-pressed="view === 'grid'" @click="view = 'grid'"><Grid /></button><button :class="{ active: view === 'list' }" :aria-label="$t('modules.studioDialogs.knowledgeDetail.listView')" :aria-pressed="view === 'list'" @click="view = 'list'"><List /></button></div></div>
          <div class="kd-results text-caption"><span v-if="filteredChunkTotal">{{ $t('modules.studioDialogs.knowledgeDetail.resultsRange', { total: filteredChunkTotal, from: rangeFrom, to: rangeTo }) }}</span><span v-else>{{ $t('modules.studioDialogs.knowledgeDetail.results', { total: 0 }) }}</span><span><span class="kd-legend-dot" />{{ $t('modules.studioDialogs.knowledgeDetail.legend') }}</span></div>
          <div v-loading="chunkLoading" class="kd-chunks-scroll"><div :class="['kd-chunks', { 'is-list': view === 'list' }]">
            <button v-for="chunk in pageChunks" :key="chunk.id" :class="['kd-chunk', { 'is-disabled': !chunk.enabled }]" @click="selectedChunk = chunk">
              <div class="kd-chunk-head"><span class="kd-chunk-number text-code"># {{ String(chunk.number).padStart(3, '0') }}</span><span class="kd-chunk-state text-caption"><i :class="{ off: !chunk.enabled }" />{{ chunk.enabled ? $t('modules.studioDialogs.knowledgeDetail.chunkEnabled') : $t('modules.studioDialogs.knowledgeDetail.chunkDisabled') }}</span></div>
              <h3>{{ chunk.title }}</h3><p v-if="chunk.body">{{ chunk.body }}</p>
              <div class="kd-chunk-meta text-caption"><span>{{ $t('modules.studioDialogs.knowledgeDetail.chars', { count: chunk.content.length }) }}</span><span>{{ $t('modules.studioDialogs.knowledgeDetail.semanticSplit') }}</span><TopRight /></div>
              <div class="kd-chunk-source text-caption"><span class="kd-file-mark"><Document /></span><span :title="chunk.fileName">{{ chunk.fileName || '--' }}</span></div>
            </button>
          </div><el-empty v-if="!chunkLoading && !pageChunks.length" :description="overallChunkTotal ? $t('modules.studioDialogs.knowledgeDetail.noMatchingChunks') : $t('modules.studioDialogs.knowledgeDetail.noChunks')"><el-button v-if="overallChunkTotal" @click="search = ''; sourceId = ''">{{ $t('modules.studioDialogs.knowledgeDetail.clearFilters') }}</el-button><el-button v-else type="primary" @click="goDocuments">{{ $t('modules.studioDialogs.knowledgeDetail.goDocuments') }}</el-button></el-empty></div>
          <div class="kd-pagination"><span class="text-caption muted">{{ $t('modules.studioDialogs.knowledgeDetail.chunkFooter', { chunks: overallChunkTotal, files: knowledge.fileCount }) }}</span><el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="filteredChunkTotal" :page-sizes="[12, 24, 48]" layout="sizes, prev, pager, next" background :pager-count="5" /></div>
        </template>
        <div v-else class="kd-info-scroll"><div class="kd-info-layout">
          <section class="kd-info-card"><div class="kd-section-heading"><span class="kd-section-icon blue"><Collection /></span><div><h2>{{ $t('modules.studioDialogs.knowledgeDetail.overview') }}</h2><p>{{ $t('modules.studioDialogs.knowledgeDetail.overviewDesc') }}</p></div><el-button link type="primary" @click="openEdit"><Edit />{{ $t('modules.studioDialogs.knowledgeDetail.edit') }}</el-button></div><dl class="kd-properties"><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.name') }}</dt><dd>{{ knowledge.name }}</dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.description') }}</dt><dd>{{ knowledge.description || $t('modules.studioDialogs.knowledgeDetail.noDescription') }}</dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.kbId') }}</dt><dd class="kd-copy-value"><code>{{ knowledge.id }}</code><button class="icon-button copy" :aria-label="$t('modules.studioDialogs.knowledgeDetail.copyKbId')" @click="copyText(knowledge.id)"><CopyDocument /></button></dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.status') }}</dt><dd><span :class="['status-dot', statusMeta.tone]" />{{ statusMeta.text }}</dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.creator') }}</dt><dd><span class="kd-owner">{{ ownerInitial }}</span>{{ knowledge.creator }}</dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.updatedAt') }}</dt><dd>{{ knowledge.time }}</dd></div></dl></section>
          <div class="kd-info-side"><section class="kd-info-card"><div class="kd-section-heading"><span class="kd-section-icon purple"><LayersIcon /></span><div><h2>{{ $t('modules.studioDialogs.knowledgeDetail.indexConfig') }}</h2><p>{{ $t('modules.studioDialogs.knowledgeDetail.indexConfigDesc') }}</p></div></div><dl class="kd-properties kd-properties-stack"><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.embeddingModel') }}</dt><dd><span class="tag-soft purple"><LayersIcon />{{ knowledge.model || '--' }}</span></dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.kbIndex') }}</dt><dd class="kd-copy-value"><code>{{ indexName }}</code><button class="icon-button copy" :aria-label="$t('modules.studioDialogs.knowledgeDetail.copyKbIndex')" @click="copyText(indexName)"><CopyDocument /></button></dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.knowledgeType') }}</dt><dd><span class="tag-soft blue"><Document />{{ $t('modules.studioDialogs.knowledgeDetail.docKb') }}</span></dd></div></dl><p class="kd-info-note text-caption"><InfoFilled />{{ $t('modules.studioDialogs.knowledgeDetail.modelNote') }}</p></section><div class="kd-tip"><span class="kd-section-icon blue"><FolderOpened /></span><div><h3 class="text-body">{{ $t('modules.studioDialogs.knowledgeDetail.keepUpdated') }}</h3><p class="text-secondary">{{ $t('modules.studioDialogs.knowledgeDetail.keepUpdatedDesc') }}</p><el-button link type="primary" @click="goDocuments">{{ $t('modules.studioDialogs.knowledgeDetail.manageDocuments') }}<ArrowRight /></el-button></div></div></div>
        </div></div>
      </template>

      <template v-else>
        <div class="kd-document-heading"><span class="kd-tab-label"><Document />{{ $t('modules.studioDialogs.knowledgeDetail.corpusDocuments') }}<span class="kd-count">{{ knowledge.fileCount }}</span></span><span class="text-caption muted">{{ $t('modules.studioDialogs.knowledgeDetail.corpusDocumentsDesc') }}</span></div>
        <div class="kd-document-layout">
          <aside class="kd-folders"><div class="kd-folder-heading"><span class="text-secondary text-label">{{ $t('modules.studioDialogs.knowledgeDetail.documentFolders') }}</span><button class="icon-button" :aria-label="$t('modules.studioDialogs.knowledgeDetail.createFolder')" @click="createFolder"><Plus /></button></div><el-input v-model="folderSearch" :prefix-icon="Search" :placeholder="$t('modules.studioDialogs.knowledgeDetail.searchFolders')" clearable :aria-label="$t('modules.studioDialogs.knowledgeDetail.searchFolders')" /><div class="kd-folder-list"><button :class="['kd-folder', { active: folderId === 'all' }]" @click="folderId = 'all'"><Collection /><span>{{ $t('modules.studioDialogs.knowledgeDetail.allDocuments') }}</span><span class="kd-folder-count">{{ knowledge.fileCount }}</span></button><div v-for="folder in visibleFolders" :key="folder.id" class="kd-folder-row"><button :class="['kd-folder', { active: folderId === folder.id }]" :title="folder.name" @click="folderId = folder.id"><FolderOpened /><span>{{ folder.name }}</span><span class="kd-folder-count">{{ folderCount(folder.id) }}</span></button><el-dropdown trigger="click" @command="command => folderAction(command, folder)"><button class="icon-button" :aria-label="$t('modules.studioDialogs.knowledgeDetail.folderMore', { name: folder.name })"><MoreFilled class="more-icon" /></button><template #dropdown><el-dropdown-menu><el-dropdown-item command="rename" :disabled="!folder.parentId"><Edit />{{ $t('modules.studioDialogs.knowledgeDetail.renameFolder') }}</el-dropdown-item><el-dropdown-item command="delete" :disabled="!folder.parentId" class="danger-menu-item" divided><Delete />{{ $t('modules.studioDialogs.knowledgeDetail.deleteFolder') }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div></div><div class="kd-folder-foot text-caption"><InfoFilled />{{ $t('modules.studioDialogs.knowledgeDetail.folderFoot') }}</div></aside>
          <section class="kd-document-main"><div class="kd-doc-toolbar"><div><h2 class="text-section-title">{{ currentFolderName }}<span class="text-caption muted">{{ $t('modules.studioDialogs.knowledgeDetail.fileCount', { count: filteredFiles.length }) }}</span></h2><p class="text-caption muted">{{ $t('modules.studioDialogs.knowledgeDetail.filesIntro') }}</p></div><el-button type="primary" class="button-compact" @click="openUpload"><Upload />{{ $t('modules.studioDialogs.knowledgeDetail.importFile') }}</el-button></div><div class="workspace-toolbar kd-doc-filters"><TableRefreshButton :key="kbId" :label="$t('modules.studioDialogs.knowledgeDetail.refreshDocuments')" :refresh="refreshDocuments" compact /><el-input v-model="fileSearch" :prefix-icon="Search" clearable :placeholder="$t('modules.studioDialogs.knowledgeDetail.searchFiles')" :aria-label="$t('modules.studioDialogs.knowledgeDetail.searchFiles')" class="kd-search" /><el-select v-model="fileStatus" clearable :placeholder="$t('modules.studioDialogs.knowledgeDetail.allStatus')" :aria-label="$t('modules.studioDialogs.knowledgeDetail.allStatus')" style="width:140px"><el-option :label="$t('modules.studioDialogs.knowledgeDetail.allStatus')" value="" /><el-option v-for="value in FILE_STATUS_VALUES" :key="value" :label="fileStatusLabel(value)" :value="value" /></el-select></div>
            <div v-if="selectedFiles.length" class="kd-selection text-secondary"><span>{{ $t('modules.studioDialogs.knowledgeDetail.selectedFiles', { count: selectedFiles.length }) }}</span><el-button link type="primary" @click="openMove(selectedFiles)"><FolderOpened />{{ $t('modules.studioDialogs.knowledgeDetail.moveToFolder') }}</el-button><el-button class="danger-action" link type="danger" @click="removeFiles(selectedFiles)"><Delete />{{ $t('modules.studioDialogs.knowledgeDetail.batchDelete') }}</el-button><el-button link @click="selectedIds = []">{{ $t('modules.studioDialogs.knowledgeDetail.clearSelection') }}</el-button></div>
            <div class="table-card kd-files-table"><table class="list-table"><thead><tr><th class="check-cell"><input type="checkbox" :aria-label="$t('modules.studioDialogs.knowledgeDetail.selectAllPage')" :checked="pageFiles.length > 0 && pageFiles.every(file => selectedIds.includes(file.id))" @change="togglePage($event.target.checked)" /></th><th>{{ $t('modules.studioDialogs.knowledgeDetail.fileName') }}</th><th>{{ $t('modules.studioDialogs.knowledgeDetail.status') }}</th><th>{{ $t('modules.studioDialogs.knowledgeDetail.sizeChunks') }}</th><th>{{ $t('modules.studioDialogs.knowledgeDetail.creatorCreated') }}</th><th>{{ $t('modules.studioDialogs.knowledgeDetail.operate') }}</th></tr></thead><tbody><tr v-for="file in pageFiles" :key="file.id"><td class="check-cell"><input v-model="selectedIds" type="checkbox" :value="file.id" :aria-label="$t('modules.studioDialogs.knowledgeDetail.selectFile', { name: file.title })" /></td><td><button class="kd-file-name" @click="previewFile(file)"><span class="kd-doc-icon blue"><Document /></span><span><b>{{ file.title }}</b><span class="entity-sub">{{ extension(file.title) }} {{ kTypeLabel(file.kType) }}<span class="kd-separator">·</span>{{ folderName(file.parentId) }}</span></span></button></td><td class="nowrap"><span :class="['tag-soft', fileMeta(file).tone === 'success' ? 'green' : fileMeta(file).tone === 'danger' ? 'kd-error-status' : 'orange']" :title="file.errorMsg || ''"><span :class="['status-dot', fileMeta(file).tone]" />{{ fileMeta(file).text }}</span></td><td class="nowrap">{{ formatFileSize(Number(file.fileSize) || 0) }}<div class="entity-sub">{{ $t('modules.studioDialogs.knowledgeDetail.chunkCount', { count: chunkCountOf(file) }) }}</div></td><td class="nowrap">{{ creatorOf(file) }}<div class="entity-sub">{{ file.createdDate || '--' }}</div></td><td><div class="kd-file-actions"><button class="icon-button" :aria-label="$t('modules.studioDialogs.knowledgeDetail.download')" :title="$t('modules.studioDialogs.knowledgeDetail.download')" @click="downloadFile(file)"><Download /></button><el-dropdown trigger="click" @command="command => fileAction(command, file)"><button class="icon-button" :aria-label="$t('modules.studioDialogs.knowledgeDetail.moreActions', { name: file.title })"><MoreFilled class="more-icon" /></button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="fileStatusOf(file) === 'failed'" command="retry">{{ $t('modules.studioDialogs.knowledgeDetail.retryParse') }}</el-dropdown-item><el-dropdown-item command="preview">{{ $t('modules.studioDialogs.knowledgeDetail.previewDoc') }}</el-dropdown-item><el-dropdown-item command="chunks">{{ $t('modules.studioDialogs.knowledgeDetail.viewFileChunks') }}</el-dropdown-item><el-dropdown-item command="rename" disabled :title="$t('modules.studioDialogs.knowledgeDetail.renameUnavailable')">{{ $t('modules.studioDialogs.knowledgeDetail.rename') }}</el-dropdown-item><el-dropdown-item command="move"><FolderOpened />{{ $t('modules.studioDialogs.knowledgeDetail.moveToFolder') }}</el-dropdown-item><el-dropdown-item class="danger-menu-item" divided command="delete"><Delete />{{ $t('modules.studioDialogs.knowledgeDetail.delete') }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div></td></tr></tbody></table><el-empty v-if="!filteredFiles.length" :description="$t('modules.studioDialogs.knowledgeDetail.noMatchingFiles')" /></div>
            <div class="kd-pagination"><span class="text-caption muted">{{ $t('modules.studioDialogs.knowledgeDetail.fileFooter', { total: filteredFiles.length }) }}</span><el-pagination v-model:current-page="filePage" v-model:page-size="filePageSize" :total="filteredFiles.length" :page-sizes="[10,20,50]" layout="sizes, prev, pager, next" background :pager-count="5" /></div>
          </section>
        </div>
      </template>
    </template>
    <div v-else class="workspace-empty"><el-empty :description="$t('modules.studioDialogs.knowledgeDetail.notFoundEmpty')" /><RouterLink to="/knowledge">{{ $t('modules.studioDialogs.knowledgeDetail.backToKb') }}</RouterLink></div>

    <el-drawer :model-value="!!selectedChunk" @update:model-value="value => { if (!value) selectedChunk = null }" size="min(540px, 100vw)" append-to-body><template #header><h2 class="workspace-panel-title text-section-title">{{ $t('modules.studioDialogs.knowledgeDetail.chunkDetail') }} <span class="text-caption muted"># {{ selectedChunk?.number }}</span></h2></template><template v-if="selectedChunk"><div class="kd-drawer-status"><span class="text-secondary">{{ $t('modules.studioDialogs.knowledgeDetail.participate') }}</span><el-switch :model-value="selectedChunk.enabled" disabled :aria-label="$t('modules.studioDialogs.knowledgeDetail.enableChunk')" :title="$t('modules.studioDialogs.knowledgeDetail.chunkToggleUnavailable')" /></div><h3 class="text-section-title">{{ selectedChunk.title }}</h3><p class="kd-full-content text-body">{{ selectedChunk.content }}</p><dl class="workspace-properties text-secondary"><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.sourceDoc') }}</dt><dd>{{ selectedChunk.fileName || '--' }}</dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.chunkId') }}</dt><dd class="text-code">{{ selectedChunk.id }}</dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.charCount') }}</dt><dd>{{ selectedChunk.content.length }}</dd></div><div><dt>{{ $t('modules.studioDialogs.knowledgeDetail.splitMethod') }}</dt><dd>{{ $t('modules.studioDialogs.knowledgeDetail.semanticSplit') }}</dd></div></dl></template><template #footer><el-button @click="copyText(selectedChunk.content)"><CopyDocument />{{ $t('modules.studioDialogs.knowledgeDetail.copyContent') }}</el-button></template></el-drawer>
    <el-drawer :model-value="!!preview" @update:model-value="value => { if (!value) preview = null }" size="min(620px, 100vw)" append-to-body><template #header><h2 class="workspace-panel-title text-section-title">{{ $t('modules.studioDialogs.knowledgeDetail.docPreview') }}</h2></template><template v-if="preview"><h3 class="text-section-title kd-preview-title">{{ preview.file.title }}</h3><span class="tag-soft blue">{{ formatFileSize(Number(preview.file.fileSize) || 0) }} · {{ $t('modules.studioDialogs.knowledgeDetail.chunkCount', { count: preview.chunks }) }}</span><pre class="kd-preview-content text-secondary">{{ preview.content }}</pre></template><template #footer><el-button type="primary" @click="downloadFile(preview.file)"><Download />{{ $t('modules.studioDialogs.knowledgeDetail.downloadFile') }}</el-button></template></el-drawer>

    <StudioDialog v-model="uploadOpen" :busy="uploading" :title="$t('modules.studioDialogs.knowledgeDetail.importTitle')" :subtitle="$t('modules.studioDialogs.knowledgeDetail.importSubtitle')" :icon="Upload" :hint="$t('modules.studioDialogs.knowledgeDetail.importHint', { count: uploadFiles.length, folder: uploadFolderName })" width="640px">
      <el-form class="studio-form kd-upload-form" label-position="top" @submit.prevent="submitUpload">
        <div class="studio-form-section">
          <el-form-item :label="$t('modules.studioDialogs.knowledgeDetail.importFolder')" class="kd-upload-folder">
            <el-select v-model="uploadFolder" :aria-label="$t('modules.studioDialogs.knowledgeDetail.importFolder')"><el-option v-for="folder in folders" :key="folder.id" :label="folder.name" :value="folder.id" /></el-select>
            <p class="studio-field-help text-caption">{{ $t('modules.studioDialogs.knowledgeDetail.importFolderHelp') }}</p>
          </el-form-item>
          <KnowledgeFilePicker v-model="uploadFiles" :active-file-limits="uploadLimits.groups" :max-files="uploadLimits.maxFiles" :max-total-bytes="uploadLimits.maxTotalBytes" />
        </div>
      </el-form>
      <template #actions><el-button :disabled="uploading" @click="uploadOpen = false">{{ $t('public.cancel') }}</el-button><el-button type="primary" :loading="uploading" :disabled="!uploadFiles.length" @click="submitUpload">{{ $t('modules.studioDialogs.knowledgeDetail.importCount', { count: uploadFiles.length }) }}</el-button></template>
    </StudioDialog>

    <StudioDialog v-model="editOpen" :title="$t('modules.studioDialogs.knowledgeDetail.editTitle')" :subtitle="$t('modules.studioDialogs.knowledgeDetail.editSubtitle')" :icon="Edit" :hint="$t('modules.studioDialogs.knowledgeDetail.editHint')" width="560px">
      <el-form label-position="top" @submit.prevent="saveInfo"><el-form-item :label="$t('modules.studioDialogs.knowledgeDetail.name')"><el-input v-model="edit.name" maxlength="64" show-word-limit /></el-form-item><el-form-item :label="$t('modules.studioDialogs.knowledgeDetail.description')"><el-input v-model="edit.description" type="textarea" :rows="4" maxlength="1000" show-word-limit /></el-form-item></el-form>
      <template #actions><el-button @click="editOpen = false">{{ $t('public.cancel') }}</el-button><el-button type="primary" :disabled="!edit.name.trim()" @click="saveInfo">{{ $t('modules.studioDialogs.knowledgeDetail.saveChanges') }}</el-button></template>
    </StudioDialog>

    <StudioDialog
      v-model="moveOpen"
      :title="$t('modules.studioDialogs.knowledgeDetail.moveTitle')"
      :subtitle="$t('modules.studioDialogs.knowledgeDetail.moveSubtitle')"
      :icon="FolderOpened"
      :hint="$t('modules.studioDialogs.knowledgeDetail.moveHint', { count: filesToMove.length })"
      width="520px"
    >
      <el-form class="studio-form kd-move-form" label-position="top" @submit.prevent="moveFiles">
        <el-form-item :label="$t('modules.studioDialogs.knowledgeDetail.moveTarget')">
          <el-select v-model="moveFolder" :aria-label="$t('modules.studioDialogs.knowledgeDetail.moveTarget')">
            <el-option v-for="folder in folders" :key="folder.id" :value="folder.id" :label="folder.name" />
          </el-select>
        </el-form-item>
        <p class="text-secondary muted">
          {{ filesToMove.map(file => file.title).join($t('public.comma')) }}
        </p>
      </el-form>
      <template #actions>
        <el-button @click="moveOpen = false">{{ $t('public.cancel') }}</el-button>
        <el-button type="primary" @click="moveFiles">{{ $t('modules.studioDialogs.knowledgeDetail.moveConfirm') }}</el-button>
      </template>
    </StudioDialog>

    <DeleteFolderDialog
      v-model="deleteFolderOpen"
      :folder-name="deleteFolderTarget?.name || ''"
      :document-count="deleteFolderFiles.length"
      :busy="deleteFolderBusy"
      @delete-only="confirmDeleteFolder(false)"
      @delete-with-docs="confirmDeleteFolder(true)"
    />
  </WorkspaceShell>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { debounce } from 'lodash'
import {
  Collection, Coin, Document, FolderOpened, Grid, List, Search, InfoFilled, Edit,
  CopyDocument, ArrowRight, TopRight, Plus, Upload, Download,
  MoreFilled, Delete
} from '@element-plus/icons-vue'
import { LayersIcon } from '@/shared/ui/icons'
import WorkspaceShell from '@/app/layout/WorkspaceShell.vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import { requestDeletion } from '@/shared/composables/deletion'
import message from '@/shared/lib/message'
import { copyTextWithToast } from '@/shared/lib/copy-with-toast'
import { download } from '@/shared/lib/utils'
import { $t } from '@/app/i18n/i18n.js'
import { KB_STATUS, toNum } from '@/features/knowledge-base/lib/list-status'
import { getKnowledgeBaseInfo, updatedKnowledgeBaseInfo, getDatasetList, getFileDatasetApi } from '@/features/knowledge-base/api/knowledgeBase'
import { getDescendantsDirectoryList, createDirectory, deleteDirectory, deleteFile, downloadFileOut, getAllFilesPageApi, moveDocuments, retryFile, updateDirectory } from '@/features/knowledge-base/api/directory'
import { uploadFileAndSplitConfigApi } from '@/features/knowledge-base/api/kbaseApi.js'
import { useCrypto } from '@/shared/composables/useCrypto'
import { FILE_NAME_CONFLICT_CODE } from '@/shared/constants/index.js'
import { formatFileSize } from '@/features/knowledge-base/lib/knowledge-files'
import KnowledgeFilePicker from '@/features/knowledge-base/components/KnowledgeFilePicker.vue'
import DeleteFolderDialog from '@/features/knowledge-base/components/DeleteFolderDialog.vue'
import { buildDefaultSplitOperator, fallbackUploadLimits, loadUploadLimits } from '@/features/knowledge-base/lib/quick-create'
import { chunkParts } from '@/features/knowledge-base/lib/chunk-display'

const route = useRoute()
const router = useRouter()

const kbId = computed(() => String(route.params.id || ''))
const isDocuments = computed(() => route.name === 'knowledge-documents')
const focused = ref(false)

const kbDetail = ref(null)
const allFiles = ref([])
const folders = ref([])

// 删除目录：**一层弹窗**内直接三选一（一并删除 / 仅删除目录 / 中止）。
// 不要拆成「通用删除确认 → 再弹一个文档处理选择」两层：弹窗本身就是决策点。
const deleteFolderOpen = ref(false)
const deleteFolderTarget = ref(null)
const deleteFolderFiles = ref([])
const deleteFolderBusy = ref(false)
const overallChunkTotal = ref(0)

const knowledge = computed(() => {
  if (!kbDetail.value) {
    return null
  }
  const row = kbDetail.value
  const files = allFiles.value
  return {
    id: row.id || kbId.value,
    name: row.name || '',
    description: row.description || '',
    model: row.props?.embeddingModel || row.embeddingModel || '',
    status: row.status,
    fileCount: Number(row.currentFileCount) || files.length,
    creator: row.createdBy || '--',
    time: formatDateTime(row.lastUpdatedDate || row.createdDate)
  }
})

/** 知识库状态：0/5/7/8 就绪；1–4/6 处理中；101–106 失败；空库显示「等待导入」。 */
const statusMeta = computed(() => {
  const row = kbDetail.value || {}
  const status = toNum(row.status)
  if (!knowledge.value?.fileCount) {
    return { tone: 'warning', text: $t('modules.studioDialogs.knowledgeDetail.statusWaitingImport') }
  }
  if ([KB_STATUS.CREATED, KB_STATUS.PENDING_PUBLISH, KB_STATUS.PUBLISHED, KB_STATUS.PUBLISHED_MODIFIED].includes(status)) {
    return { tone: 'success', text: $t('modules.kb.statusReady') }
  }
  if ([KB_STATUS.PARSE_FAILED, KB_STATUS.SPLIT_FAILED, KB_STATUS.GENERATE_FAILED, KB_STATUS.INDEX_FAILED, KB_STATUS.PUBLISH_FAILED].includes(status)) {
    return { tone: 'danger', text: failureText(status) }
  }
  return { tone: 'warning', text: processingText(status) }
})

function failureText (status) {
  return {
    [KB_STATUS.PARSE_FAILED]: $t('modules.kb.statusParseFailed'),
    [KB_STATUS.SPLIT_FAILED]: $t('modules.kb.statusSplitFailed'),
    [KB_STATUS.GENERATE_FAILED]: $t('modules.kb.statusGenerateFailed'),
    [KB_STATUS.INDEX_FAILED]: $t('modules.kb.statusIndexFailed'),
    [KB_STATUS.PUBLISH_FAILED]: $t('modules.kb.statusPublishFailed')
  }[status] || $t('modules.kb.statusUnknown')
}

function processingText (status) {
  return {
    [KB_STATUS.PARSING]: $t('modules.kb.statusParsing'),
    [KB_STATUS.SPLITTING]: $t('modules.kb.statusSplitting'),
    [KB_STATUS.GENERATING]: $t('modules.kb.statusGenerating'),
    [KB_STATUS.INDEXING]: $t('modules.kb.statusIndexing'),
    [KB_STATUS.PUBLISHING]: $t('modules.kb.statusPublishing')
  }[status] || $t('modules.kb.statusUnknown')
}

const indexName = computed(() => `doc_${String(knowledge.value?.id || '').replaceAll('-', '_')}`)
const ownerInitial = computed(() => String(knowledge.value?.creator || '?').charAt(0).toUpperCase())
const metrics = computed(() => ([
  { label: $t('modules.studioDialogs.knowledgeDetail.sourceFiles'), value: String(knowledge.value?.fileCount || 0), unit: $t('modules.studioDialogs.knowledgeDetail.unitDoc'), icon: Document, tone: 'blue' },
  { label: $t('modules.studioDialogs.knowledgeDetail.chunks'), value: String(overallChunkTotal.value), unit: $t('modules.studioDialogs.knowledgeDetail.unitChunk'), icon: LayersIcon, tone: 'purple' },
  { label: $t('modules.studioDialogs.knowledgeDetail.storage'), value: formatFileSize(allFiles.value.reduce((sum, file) => sum + (Number(file.fileSize) || 0), 0)), icon: Coin, tone: 'orange' }
]))

/* ── 路由 / 页签 ─────────────────────────────────────────────── */
const tab = computed({
  get: () => (route.query.tab === 'info' ? 'info' : 'chunks'),
  set: value => router.replace({ query: value === 'info' ? { ...route.query, tab: 'info' } : stripTabQuery(route.query) })
})

function stripTabQuery (query) {
  const { tab: _tab, ...rest } = query // eslint-disable-line no-unused-vars
  return rest
}

function goDetail () {
  router.push({ name: 'knowledge-detail', params: { id: kbId.value } })
}

function goDocuments () {
  router.push({ name: 'knowledge-documents', params: { id: kbId.value } })
}

/** 复制并提示结果（成功/失败都要有反馈，见 copy-with-toast.js）。 */
function copyText (text) {
  return copyTextWithToast(text)
}

function formatDateTime (value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '--'
}

/* ── 数据加载 ─────────────────────────────────────────────────── */
const chunkLoading = ref(false)

async function loadKnowledge (rethrow = false) {
  if (!kbId.value) {
    return
  }
  try {
    kbDetail.value = await getKnowledgeBaseInfo(kbId.value)
    // 切片总数随详情一起返回（后端一次 count，不再单独发 chunks?size=1 探针）。
    // 与列表信封的 total 同口径，搜索结果只影响列表，不影响这个角标。
    overallChunkTotal.value = Number(kbDetail.value?.chunkCount) || 0
  } catch (error) {
    // 轮询/自动刷新时的瞬时失败保留已渲染的数据，不要把整页翻成「知识库不存在」
    if (!kbDetail.value) {
      kbDetail.value = null
    }
    if (rethrow) {
      throw error
    }
  }
}

async function loadAllFiles (rethrow = false) {
  if (!kbId.value) {
    return
  }
  // 后端 `/directory/search/pageFile/all` 的 pageSize 上限是 100（超了回 0004），
  // 这里按 100 翻页；最多翻 20 页（2000 个文件）—— 超过时指标按已取到的部分统计。
  const pageSize = 100
  const collected = []
  try {
    for (let page = 1; page <= 20; page += 1) {
      const response = await getAllFilesPageApi(kbId.value, { currentPage: page, pageSize })
      const rows = Array.isArray(response?.items) ? response.items : []
      collected.push(...rows)
      if (rows.length < pageSize || collected.length >= Number(response?.total || 0)) {
        break
      }
    }
    allFiles.value = collected
  } catch (error) {
    // 同理：失败保留上一屏；首次加载失败时保持空表（行内会显示 0 篇）
    if (rethrow) {
      throw error
    }
  }
}

async function loadFolders (rethrow = false) {
  try {
    const response = await getDescendantsDirectoryList({ kbaseId: kbId.value, type: 'folder', category: 0 })
    const rows = Array.isArray(response) ? response : []
    folders.value = rows
      .filter(row => row && (row.type === 'folder' || !row.type))
      .map(row => ({ id: row.id, name: row.title || row.name || row.id, parentId: row.parentId }))
  } catch (error) {
    if (rethrow) {
      throw error
    }
    folders.value = []
  }
}

/* ── 分块 ─────────────────────────────────────────────────────── */
const search = ref('')
const sourceId = ref('')
const view = ref('grid')
const page = ref(1)
const pageSize = ref(12)
const selectedChunk = ref(null)
const chunks = ref([])
const filteredChunkTotal = ref(0)

const pageChunks = computed(() => chunks.value)
const rangeFrom = computed(() => (filteredChunkTotal.value ? (page.value - 1) * pageSize.value + 1 : 0))
const rangeTo = computed(() => Math.min(page.value * pageSize.value, filteredChunkTotal.value))

function chunkTitle (content) {
  return chunkParts(content).title
}

function toChunk (item, index) {
  const { title, body } = chunkParts(item.content)
  return {
    id: item.chunkId,
    number: (page.value - 1) * pageSize.value + index + 1,
    title,
    content: String(item.content || ''),
    body,
    fileName: item.source || '',
    fileId: item.fileId || '',
    enabled: item.effectFlag === undefined ? true : Number(item.effectFlag) === 1
  }
}

async function loadChunks (rethrow = false) {
  if (!kbId.value) {
    return
  }
  chunkLoading.value = true
  try {
    const params = {
      kbaseId: kbId.value,
      keyword: search.value.trim(),
      richTextSwitch: true,
      currentPage: page.value,
      pageSize: pageSize.value
    }
    if (sourceId.value) {
      const response = await getFileDatasetApi(sourceId.value, params)
      const rows = response?.items || []
      chunks.value = rows.map(toChunk)
      filteredChunkTotal.value = Number(response?.total) || rows.length
    } else {
      const response = await getDatasetList(params)
      const rows = Array.isArray(response?.items) ? response.items : []
      chunks.value = rows.map(toChunk)
      filteredChunkTotal.value = Number(response?.total) || rows.length
    }
  } catch (error) {
    if (rethrow) {
      throw error
    }
    chunks.value = []
    filteredChunkTotal.value = 0
  } finally {
    chunkLoading.value = false
  }
}

watch([sourceId, pageSize], () => {
  page.value = 1
})
watch([sourceId, page, pageSize], () => {
  if (!isDocuments.value) {
    loadChunks()
  }
})

/* ── 文档 ─────────────────────────────────────────────────────── */
const folderId = ref('all')
const folderSearch = ref('')
const fileSearch = ref('')
const fileStatus = ref('')
const filePage = ref(1)
const filePageSize = ref(10)
const selectedIds = ref([])
const FILE_STATUS_VALUES = ['available', 'pending', 'failed']

const visibleFolders = computed(() => folders.value.filter(folder => folder.name.toLowerCase().includes(folderSearch.value.trim().toLowerCase())))
const currentFolderName = computed(() => (folderId.value === 'all' ? $t('modules.studioDialogs.knowledgeDetail.allDocuments') : folderName(folderId.value)))

const filteredFiles = computed(() => allFiles.value.filter(file => (
  (folderId.value === 'all' || file.parentId === folderId.value) &&
  (!fileStatus.value || fileStatusOf(file) === fileStatus.value) &&
  String(file.title || '').toLowerCase().includes(fileSearch.value.trim().toLowerCase())
)))
const pageFiles = computed(() => filteredFiles.value.slice((filePage.value - 1) * filePageSize.value, filePage.value * filePageSize.value))
const selectedFiles = computed(() => allFiles.value.filter(file => selectedIds.value.includes(file.id)))

watch([folderId, fileSearch, fileStatus, filePageSize], () => {
  filePage.value = 1
  selectedIds.value = []
})

function folderName (id) {
  return folders.value.find(folder => folder.id === id)?.name || '--'
}

function folderCount (id) {
  return allFiles.value.filter(file => file.parentId === id).length
}

function fileStatusOf (file) {
  const status = toNum(file.status)
  if (status === 1) {
    return 'available'
  }
  if (status === 2) {
    return 'failed'
  }
  return 'pending'
}

function fileStatusLabel (value) {
  return {
    available: $t('modules.studioDialogs.knowledgeDetail.statusAvailable'),
    pending: $t('modules.studioDialogs.knowledgeDetail.statusPending'),
    failed: $t('modules.studioDialogs.knowledgeDetail.statusFailed')
  }[value] || value
}

function fileMeta (file) {
  const key = fileStatusOf(file)
  return {
    tone: key === 'available' ? 'success' : key === 'failed' ? 'danger' : 'warning',
    text: fileStatusLabel(key)
  }
}

function kTypeLabel (kType) {
  return kType === 'QA' ? 'QA' : $t('modules.studioDialogs.knowledgeDetail.fileTypeDocument')
}

function extension (name) {
  return String(name || '').split('.').pop().toUpperCase()
}

function creatorOf (file) {
  const name = file.fullName || file.fullNameEn || file.createdBy || ''
  return name || '--'
}

/**
 * 「N 个切片」列：文件列表接口直接带 `chunkCount`（后端一次 GROUP BY 算好）。
 * 只有「已可用」的文件才有该字段；处理中/失败显示「—」（处理中查出来恒为 0，
 * 直接显示 0 会一直错到下次刷新 —— 这是既定语义）。
 */
function chunkCountOf (file) {
  return fileStatusOf(file) === 'available' && file.chunkCount !== undefined
    ? file.chunkCount
    : '—'
}

function togglePage (checked) {
  const ids = pageFiles.value.map(file => file.id)
  selectedIds.value = checked
    ? [...new Set([...selectedIds.value, ...ids])]
    : selectedIds.value.filter(id => !ids.includes(id))
}

/* ── 目录 / 文档操作 ─────────────────────────────────────────── */
/**
 * 目录名规则与后端校验一致（`^[\p{IsHan}a-zA-Z0-9_.\- ]{2,30}$`）。
 * 前端先拦一次，避免用户敲完才被 0005 打回。
 */
const FOLDER_NAME_MIN = 2
const FOLDER_NAME_MAX = 30
const FOLDER_NAME_PATTERN = /^[\p{Script=Han}A-Za-z0-9_.\- ]+$/u

function validateFolderName (value) {
  const name = String(value || '').trim()
  if (!name) {
    return $t('modules.studioDialogs.knowledgeDetail.folderNameRequired')
  }
  if (name.length < FOLDER_NAME_MIN || name.length > FOLDER_NAME_MAX ||
      !FOLDER_NAME_PATTERN.test(name)) {
    return $t('modules.studioDialogs.knowledgeDetail.folderNameInvalid', {
      min: FOLDER_NAME_MIN,
      max: FOLDER_NAME_MAX
    })
  }
  return true
}

async function createFolder () {
  try {
    const { value } = await ElMessageBox.prompt($t('modules.studioDialogs.knowledgeDetail.createFolder'), $t('modules.studioDialogs.knowledgeDetail.documentFolders'), {
      confirmButtonText: $t('public.confirm'),
      cancelButtonText: $t('public.cancel'),
      inputValidator: validateFolderName
    })
    const name = String(value || '').trim()
    if (!name) {
      return
    }
    if (folders.value.some(folder => folder.name.toLowerCase() === name.toLowerCase())) {
      message.warning($t('modules.studioDialogs.knowledgeDetail.folderExists'))
      return
    }
    const root = folders.value.find(folder => !folder.parentId) || folders.value[0]
    await createDirectory({ kbaseId: kbId.value, parentId: root?.id }, { title: name, category: 0 })
    await loadFolders()
    const created = folders.value.find(folder => folder.name === name)
    if (created) {
      folderId.value = created.id
    }
  } catch {
    // 用户取消
  }
}

function chunkCountLabel (file) {
  const count = chunkCountOf(file)
  return count === '—' ? '—' : $t('modules.studioDialogs.knowledgeDetail.chunkCount', { count })
}

/** 文档删除走统一确认弹窗（影响说明 + 对象信息 + 验证码）。 */
async function removeFiles (files) {
  const targets = [...files]
  if (!targets.length) {
    return
  }
  const knownChunks = targets.reduce((sum, file) => sum + (Number(file.chunkCount) || 0), 0)
  const hasUnknownChunks = targets.some(file => file.chunkCount === undefined)
  const confirmed = await requestDeletion({
    resourceType: $t('modules.studioDialogs.knowledgeDetail.documentResource'),
    title: targets.length > 1
      ? $t('modules.studioDialogs.knowledgeDetail.batchDelete')
      : $t('modules.studioDialogs.knowledgeDetail.deleteFilesTitle'),
    warning: $t('modules.studioDialogs.knowledgeDetail.deleteDocWarning'),
    description: $t('modules.studioDialogs.knowledgeDetail.deleteDocDescription'),
    items: targets.map(file => ({
      id: file.id,
      name: file.title,
      meta: `${formatFileSize(Number(file.fileSize) || 0)} · ${chunkCountLabel(file)}`,
      tag: extension(file.title)
    })),
    detail: $t('modules.studioDialogs.knowledgeDetail.deleteDocDetail', {
      count: targets.length,
      chunks: hasUnknownChunks ? '—' : knownChunks,
      kb: knowledge.value?.name || ''
    }),
    hint: $t('modules.studioDialogs.knowledgeDetail.deleteDocHint')
  })
  if (!confirmed) {
    return
  }
  const results = await Promise.allSettled(targets.map(file => deleteFile(kbId.value, file.id)))
  const deletedIds = new Set()
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      deletedIds.add(targets[index].id)
    }
  })
  selectedIds.value = selectedIds.value.filter(id => !deletedIds.has(id))
  if (deletedIds.size) {
    message.success($t('modules.studioDialogs.knowledgeDetail.deleteFilesSuccess'))
  }
  if (deletedIds.size < targets.length) {
    message.error($t('modules.studioDialogs.knowledgeDetail.deleteDocPartial'))
  }
  // 已删的行必须从界面消失；失败的保留在列表里
  await refreshAfterMutation()
}

/* ── 目录重命名 / 删除 / 移动文档 ─────────────────────────────── */
async function renameFolder (folder) {
  if (!folder?.parentId) {
    return
  }
  try {
    const { value } = await ElMessageBox.prompt(
      $t('modules.studioDialogs.knowledgeDetail.folderNameLabel'),
      $t('modules.studioDialogs.knowledgeDetail.renameFolder'),
      {
        inputValue: folder.name,
        inputValidator: validateFolderName,
        confirmButtonText: $t('public.save'),
        cancelButtonText: $t('public.cancel')
      }
    )
    const name = String(value || '').trim()
    if (!name || name === folder.name) {
      return
    }
    if (folders.value.some(item => item.id !== folder.id && item.name.toLowerCase() === name.toLowerCase())) {
      message.warning($t('modules.studioDialogs.knowledgeDetail.folderExists'))
      return
    }
    await updateDirectory(kbId.value, folder.id, { title: name })
    message.success($t('modules.studioDialogs.knowledgeDetail.folderRenamed'))
    await loadFolders()
  } catch {
    // 用户取消；接口错误由拦截器提示
  }
}

/** 目录自身 + 全部子孙目录的 id（目录列表是扁平的，parentId 串成树）。 */
function descendantFolderIds (rootId) {
  const ids = new Set([rootId])
  let grew = true
  while (grew) {
    grew = false
    for (const folder of folders.value) {
      if (folder.parentId && ids.has(folder.parentId) && !ids.has(folder.id)) {
        ids.add(folder.id)
        grew = true
      }
    }
  }
  return ids
}

/** 打开「删除目录」三选一弹窗（含子目录里的文档一起计数）。 */
function openDeleteFolder (folder, files) {
  deleteFolderTarget.value = folder
  deleteFolderFiles.value = files
  deleteFolderOpen.value = true
}

/**
 * 执行目录删除。`withDocs=true` 时先删光目录树里的文档再删目录；
 * 任一篇没删掉就整体中止，避免剩下的文档被静默移到 Default。
 */
async function confirmDeleteFolder (withDocs) {
  const folder = deleteFolderTarget.value
  if (!folder) {
    return
  }
  deleteFolderBusy.value = true
  try {
    if (withDocs) {
      const results = await Promise.allSettled(
        deleteFolderFiles.value.map(file => deleteFile(kbId.value, file.id)))
      const failed = results.filter(result => result.status === 'rejected').length
      if (failed) {
        message.error($t('modules.studioDialogs.knowledgeDetail.deleteDocPartial'))
        deleteFolderOpen.value = false
        await refreshAfterMutation()
        return
      }
    }
    await deleteDirectory(kbId.value, folder.id)
    message.success($t(withDocs
      ? 'modules.studioDialogs.knowledgeDetail.deleteFolderWithDocsSuccess'
      : 'modules.studioDialogs.knowledgeDetail.deleteFolderSuccess'))
    if (folderId.value === folder.id) {
      folderId.value = 'all'
    }
    deleteFolderOpen.value = false
    await refreshAfterMutation()
  } catch {
    // 409（Default 同名冲突等）由拦截器提示；关闭弹窗，保留当前目录
    deleteFolderOpen.value = false
  } finally {
    deleteFolderBusy.value = false
  }
}

async function folderAction (command, folder) {
  if (!folder?.parentId) {
    return
  }
  if (command === 'rename') {
    await renameFolder(folder)
    return
  }
  if (command !== 'delete') {
    return
  }
  const scope = descendantFolderIds(folder.id)
  const files = allFiles.value.filter(file => scope.has(file.parentId))
  openDeleteFolder(folder, files)
}

const moveOpen = ref(false)
const moveFolder = ref('')
const filesToMove = ref([])

function openMove (files) {
  const targets = [...files]
  if (!targets.length) {
    return
  }
  const preferred = folders.value.find(folder => targets.some(file => file.parentId !== folder.id))
    || folders.value[0]
  if (!preferred) {
    message.warning($t('modules.studioDialogs.knowledgeDetail.moveNoTarget'))
    return
  }
  filesToMove.value = targets
  moveFolder.value = preferred.id
  moveOpen.value = true
}

async function moveFiles () {
  if (!moveFolder.value || !filesToMove.value.length) {
    return
  }
  // 目标目录的同名冲突先在前端拦一次，后端仍会兜底（409）。
  const movingIds = new Set(filesToMove.value.map(file => file.id))
  const occupied = new Set(
    allFiles.value
      .filter(file => file.parentId === moveFolder.value && !movingIds.has(file.id))
      .map(file => file.title)
  )
  const movingTitles = new Set()
  for (const file of filesToMove.value) {
    if (occupied.has(file.title) || movingTitles.has(file.title)) {
      message.warning($t('modules.studioDialogs.knowledgeDetail.moveConflict'))
      return
    }
    movingTitles.add(file.title)
  }
  try {
    await moveDocuments(kbId.value, Array.from(movingIds), moveFolder.value)
    message.success($t('modules.studioDialogs.knowledgeDetail.moveSuccess'))
    folderId.value = moveFolder.value
    fileSearch.value = ''
    fileStatus.value = ''
    filePage.value = 1
    selectedIds.value = []
    moveOpen.value = false
    await refreshAfterMutation()
  } catch {
    // 接口错误由拦截器提示，弹窗保持打开
  }
}

async function fileAction (command, file) {
  if (command === 'chunks') {
    sourceId.value = file.id
    router.push({ name: 'knowledge-detail', params: { id: kbId.value }, query: { source: file.id } })
  } else if (command === 'preview') {
    previewFile(file)
  } else if (command === 'move') {
    openMove([file])
  } else if (command === 'retry') {
    await retryDocument(file)
  } else if (command === 'delete') {
    await removeFiles([file])
  }
}

/** 重新解析一篇失败文档：后端置回待处理并重新入队，列表 5 秒轮询会接上进度。 */
async function retryDocument (file) {
  if (!file || fileStatusOf(file) !== 'failed') {
    return
  }
  try {
    await retryFile(kbId.value, file.id)
  } catch {
    // 接口错误由拦截器提示（例如状态已不是失败、文件不存在）
    return
  }
  message.success($t('modules.studioDialogs.knowledgeDetail.retryStarted'))
  await refreshAfterMutation()
}

const preview = ref(null)
async function previewFile (file) {
  try {
    // order=asc：切片接口默认按 REL.id 倒序（切片管理页要「后加的在前」），
    // 文档预览必须按原文顺序拼，否则整篇内容是反的。
    const response = await getFileDatasetApi(file.id, {
      kbaseId: kbId.value,
      currentPage: 1,
      pageSize: 50,
      order: 'asc'
    })
    const rows = response?.items || []
    const content = rows.map(row => `## ${chunkTitle(row.content)}\n\n${row.content}`).join('\n\n')
    preview.value = {
      file,
      chunks: Number(response?.total) || rows.length,
      content: content || $t('modules.studioDialogs.knowledgeDetail.previewUnavailable')
    }
  } catch {
    preview.value = { file, chunks: 0, content: $t('modules.studioDialogs.knowledgeDetail.previewUnavailable') }
  }
}

async function downloadFile (file) {
  if (!file) {
    return
  }
  try {
    const blob = await downloadFileOut({ kbaseId: kbId.value, fileId: file.id })
    download(blob, file.title, '')
  } catch {
    // 拦截器已提示
  }
}

/* ── 上传 ─────────────────────────────────────────────────────── */
const uploadOpen = ref(false)
const uploadFiles = ref([])
const uploadFolder = ref('')
const uploading = ref(false)
const uploadLimits = ref(fallbackUploadLimits())
const uploadFolderName = computed(() => folderName(uploadFolder.value))

async function openUpload () {
  uploadFiles.value = []
  const defaultFolder = folderId.value === 'all' ? (folders.value.find(folder => !folder.parentId) || folders.value[0]) : folders.value.find(folder => folder.id === folderId.value)
  uploadFolder.value = defaultFolder?.id || ''
  uploadOpen.value = true
  uploadLimits.value = await loadUploadLimits()
}

function normalizeFileName (file) {
  const index = file.name.lastIndexOf('.')
  if (index === -1) {
    return file
  }
  const name = `${file.name.slice(0, index)}.${file.name.slice(index + 1).toLowerCase()}`
  return name === file.name ? file : new File([file], name, { type: file.type })
}

async function performUpload (files, coverFlag = false) {
  const splitOperator = await buildDefaultSplitOperator(files)
  const data = new FormData()
  files.forEach(file => data.append('files', file))
  data.append('metadata', JSON.stringify({
    kType: 'outer-document',
    directoryId: uploadFolder.value,
    kbaseId: kbId.value,
    splitType: 'system',
    splitOperator,
    coverFlag
  }))
  const { getConfig } = useCrypto(kbId.value)
  const config = await getConfig()
  await uploadFileAndSplitConfigApi(kbId.value, data, config)
}

async function submitUpload () {
  if (!uploadFiles.value.length || uploading.value) {
    return
  }
  if (!uploadFolder.value) {
    message.warning($t('modules.studioDialogs.knowledgeDetail.importFolderMissing'))
    return
  }
  uploading.value = true
  try {
    await performUpload(uploadFiles.value.map(normalizeFileName))
    message.success($t('modules.studioDialogs.knowledgeDetail.filesAdded'))
    uploadOpen.value = false
    await refreshAfterMutation()
  } catch (error) {
    if (error?.code === FILE_NAME_CONFLICT_CODE) {
      try {
        await ElMessageBox.confirm(
          $t('modules.studioDialogs.knowledgeDetail.duplicateFileConfirm'),
          $t('messageBox.tip'),
          { confirmButtonText: $t('knowledge.import.recover'), cancelButtonText: $t('public.cancel'), type: 'warning' }
        )
        await performUpload(uploadFiles.value.map(normalizeFileName), true)
        message.success($t('modules.studioDialogs.knowledgeDetail.filesAdded'))
        uploadOpen.value = false
        await refreshAfterMutation()
      } catch {
        // 取消覆盖，保持弹窗
      }
    }
  } finally {
    uploading.value = false
  }
}

/* ── 编辑基本信息 ─────────────────────────────────────────────── */
const editOpen = ref(false)
const edit = reactive({ name: '', description: '' })

function openEdit () {
  Object.assign(edit, { name: knowledge.value?.name || '', description: knowledge.value?.description || '' })
  editOpen.value = true
}

async function saveInfo () {
  const name = edit.name.trim()
  if (!name) {
    return
  }
  try {
    await updatedKnowledgeBaseInfo(knowledge.value.id, { name, description: edit.description.trim() })
    message.success($t('modules.studioDialogs.knowledgeDetail.infoUpdated'))
    editOpen.value = false
    await loadKnowledge()
  } catch {
    // 拦截器已提示
  }
}

/* ── 刷新 ─────────────────────────────────────────────────────── */
/** 分块页刷新按钮。失败时保留旧内容（load* 的 rethrow 分支不清数据）。 */
async function refreshChunks () {
  await Promise.all([
    loadKnowledge(true),
    loadAllFiles(true),
    loadFolders(true)
  ])
  const ids = new Set(allFiles.value.map(file => file.id))
  selectedIds.value = selectedIds.value.filter(id => ids.has(id))
  page.value = Math.max(1, Math.min(page.value, Math.ceil(filteredChunkTotal.value / pageSize.value) || 1))
  await loadChunks(true)
  const maxPage = Math.max(1, Math.ceil(filteredChunkTotal.value / pageSize.value))
  page.value = Math.min(page.value, maxPage)
}

/** 文档管理刷新按钮。保留搜索 / 状态 / 页码与仍存在的勾选。 */
async function refreshDocuments () {
  await Promise.all([
    loadKnowledge(true),
    loadAllFiles(true),
    loadFolders(true)
  ])
  const ids = new Set(allFiles.value.map(file => file.id))
  selectedIds.value = selectedIds.value.filter(id => ids.has(id))
  const maxPage = Math.max(1, Math.ceil(filteredFiles.value.length / filePageSize.value))
  filePage.value = Math.min(filePage.value, maxPage)
}

async function refreshAfterMutation () {
  await Promise.all([loadKnowledge(), loadAllFiles(), loadFolders()])
  // 删除最后一行的场景：当前页可能已越界，回落到最后一个有效页
  const maxFilePage = Math.max(1, Math.ceil(filteredFiles.value.length / filePageSize.value))
  filePage.value = Math.min(filePage.value, maxFilePage)
  if (!isDocuments.value) {
    await loadChunks()
    const maxChunkPage = Math.max(1, Math.ceil(filteredChunkTotal.value / pageSize.value))
    page.value = Math.min(page.value, maxChunkPage)
  }
}

let refreshTimer = null
function ensureAutoRefresh () {
  const hasProcessing = () => allFiles.value.some(file => fileStatusOf(file) === 'pending')
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  refreshTimer = setInterval(() => {
    if (!hasProcessing()) {
      return
    }
    Promise.all([loadAllFiles(), loadKnowledge()]).then(() => {
      if (!isDocuments.value && !hasProcessing()) {
        loadChunks()
      }
    })
  }, 5000)
}

async function loadPage () {
  if (!kbId.value) {
    return
  }
  await Promise.all([loadKnowledge(), loadAllFiles(), loadFolders()])
  if (!isDocuments.value) {
    await loadChunks()
  }
}

watch(kbId, () => {
  kbDetail.value = null
  overallChunkTotal.value = 0
  allFiles.value = []
  selectedIds.value = []
  preview.value = null
  selectedChunk.value = null
  search.value = ''
  sourceId.value = route.query.source ? String(route.query.source) : ''
  folderId.value = 'all'
  folderSearch.value = ''
  fileSearch.value = ''
  fileStatus.value = ''
  uploadOpen.value = false
  editOpen.value = false
  moveOpen.value = false
  page.value = 1
  filePage.value = 1
  loadPage()
})

watch(() => route.query.source, value => {
  if (!isDocuments.value) {
    sourceId.value = value ? String(value) : ''
  }
})

watch(isDocuments, () => {
  if (isDocuments.value) {
    loadAllFiles()
  } else {
    loadChunks()
  }
})

watch(() => route.query.import, value => {
  if (value === '1' && isDocuments.value && knowledge.value) {
    openUpload()
    const { import: _import, ...rest } = route.query // eslint-disable-line no-unused-vars
    router.replace({ query: rest })
  }
})

onMounted(async () => {
  sourceId.value = route.query.source ? String(route.query.source) : ''
  await loadPage()
  // `/knowledge/detail/:id/documents?import=1`：列表页「导入文档」直达上传弹窗
  if (route.query.import === '1' && isDocuments.value && knowledge.value) {
    openUpload()
    const { import: _import, ...rest } = route.query // eslint-disable-line no-unused-vars
    router.replace({ query: rest })
  }
  ensureAutoRefresh()
})

onBeforeUnmount(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})

// 搜索防抖：换关键字回到第 1 页，再取数（输入即筛，这里不打断输入）
const debouncedSearch = debounce(() => {
  page.value = 1
  loadChunks()
}, 300)
watch(search, () => {
  debouncedSearch()
})
</script>

<style scoped>
.knowledge-detail { gap: 20px; }
.kd-overview { display: grid; grid-template-columns: 1fr 1fr 1fr minmax(280px,1.65fr); border: 1px solid var(--rs-border); border-radius: 10px; padding: 19px 0; background: var(--rs-bg-card); flex-shrink: 0; }
.kd-metric { display: flex; align-items: center; gap: 12px; padding: 0 24px; border-right: 1px solid var(--rs-border-soft); }
.kd-metric-icon,.kd-model-symbol { display: flex; align-items: center; justify-content: center; width: 40px; height: 40px; background: var(--tint); color: var(--tone); border-radius: 10px; flex-shrink: 0; }
.kd-metric-icon svg { width: 21px; height: 21px; }.kd-metric-value { font-size: 23px; font-weight: 650; line-height: 1.5; font-variant-numeric: tabular-nums; white-space: nowrap; }.kd-metric-value > span { margin-left: 6px; font-weight: 400; }
.kd-model { display: flex; align-items: center; gap: 12px; padding: 0 22px; }.kd-model .tag-soft { margin-left: auto; }.kd-model .text-label { margin-top: 5px; }.kd-model-symbol { width: 34px; height: 34px; background: none; }
.kd-tab-label { display: flex; align-items: center; gap: 8px; }.kd-tab-label > svg { width: 16px; height: 16px; }.kd-count { background: var(--rs-bg-soft); color: var(--rs-text-3); border-radius: 5px; padding: 1px 6px; font-size: 11px; font-weight: 500; line-height: 18px; }.kd-tabs :deep(.is-active .kd-count) { background: var(--rs-bg-selected); color: var(--rs-primary); }
.kd-search { width: 320px; }.kd-source { width: 210px; }.kd-source :deep(.el-select__wrapper),.kd-doc-filters :deep(.el-select__wrapper) { min-height: 40px; }.kd-view-control { display: flex; align-items: center; gap: 3px; }.kd-view-control > span { margin-right: 10px; }.kd-view-control button { width: 32px; height: 32px; border: 1px solid transparent; border-radius: 6px; color: var(--rs-text-3); background: transparent; }.kd-view-control button.active { background: var(--rs-bg-selected); color: var(--rs-primary); border-color: var(--rs-primary-border); }.kd-view-control svg { width: 16px; }
.kd-results { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--rs-text-3); }.kd-results b { color: var(--rs-text-2); font-weight: 600; }.kd-legend-dot { display: inline-block; width: 6px; height: 6px; background: var(--rs-success); border-radius: 50%; margin-right: 6px; }
.kd-chunks-scroll { flex: 1; min-height: 0; overflow: auto; padding: 1px 3px 4px 1px; }.kd-chunks { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 16px; }.kd-chunk { text-align: left; border: 1px solid var(--rs-border); border-radius: 9px; background: var(--rs-bg-card); padding: 17px 18px 0; min-width: 0; color: var(--rs-text); transition: border-color .15s, box-shadow .15s; overflow: hidden; }.kd-chunk:hover { border-color: var(--rs-primary-border); box-shadow: 0 3px 14px #1677ff0c; }.kd-chunk:focus-visible { outline-offset: -3px; }.kd-chunk.is-disabled { opacity: .65; }.kd-chunk-head { display: flex; justify-content: space-between; align-items: center; }.kd-chunk-number { color: var(--rs-primary); font-size: 11px; background: var(--rs-bg-selected); padding: 3px 7px; border-radius: 4px; }.kd-chunk-state { display: flex; align-items: center; gap: 5px; color: var(--rs-text-3); }.kd-chunk-state i { width: 5px; height: 5px; border-radius: 50%; background: var(--rs-success); }.kd-chunk-state i.off { background: var(--rs-text-3); }.kd-chunk h3 { font-size: var(--rs-font-size-body); margin: 14px 0 8px; font-weight: 600; }.kd-chunk p { font-size: var(--rs-font-size-secondary); color: var(--rs-text-2); line-height: 1.85; margin: 0; height: 72px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }.kd-chunk-meta { display: flex; align-items: center; gap: 12px; margin: 14px 0; color: var(--rs-text-3); }.kd-chunk-meta > span + span::before { content: '·'; margin-right: 12px; }.kd-chunk-meta svg { margin-left: auto; width: 13px; height: 13px; opacity: 0; color: var(--rs-primary); }.kd-chunk:hover .kd-chunk-meta svg { opacity: 1; }.kd-chunk-source { display: flex; align-items: center; gap: 8px; border-top: 1px solid var(--rs-border-soft); padding: 11px 0; color: var(--rs-text-2); }.kd-chunk-source > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.kd-file-mark { display: flex; color: var(--rs-primary); }.kd-file-mark svg { width: 14px; height: 14px; }.kd-chunks.is-list { grid-template-columns: 1fr; }.is-list .kd-chunk p { height: auto; -webkit-line-clamp: 2; }.is-list .kd-chunk h3 { margin-top: 8px; }
.kd-pagination { display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; gap: 12px; padding-top: 14px; border-top: 1px solid var(--rs-border-soft); }.kd-pagination :deep(.el-pagination) { --el-pagination-button-bg-color: var(--rs-bg-soft); font-size: var(--rs-font-size-caption); }.kd-pagination :deep(.el-select) { width: 106px; }.kd-pagination :deep(.el-select__wrapper) { min-height: 32px; font-size: var(--rs-font-size-caption); }.kd-pagination :deep(.el-pagination.is-background .el-pager li.is-active) { background: var(--rs-bg-selected); color: var(--rs-primary); }
.kd-info-scroll { overflow: auto; flex: 1; padding-bottom: 10px; }.kd-info-layout { display: grid; grid-template-columns: minmax(0,1.35fr) minmax(0,1fr); gap: 24px; align-items: stretch; }.kd-info-layout > .kd-info-card { display: flex; flex-direction: column; }.kd-info-layout > .kd-info-card > .kd-properties { flex: 1; display: grid; grid-template-rows: repeat(6, minmax(min-content, 1fr)); }.kd-info-card { border: 1px solid var(--rs-border); border-radius: 10px; background: var(--rs-bg-card); padding: 24px; }.kd-section-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }.kd-section-heading h2 { font-size: var(--rs-font-size-section-title); margin: 0 0 5px; font-weight: 600; }.kd-section-heading p { color: var(--rs-text-3); font-size: var(--rs-font-size-caption); margin: 0; }.kd-section-heading > .el-button { margin-left: auto; }.kd-section-icon { display: flex; align-items: center; justify-content: center; width: 38px; height: 38px; background: var(--tint); color: var(--tone); border-radius: 9px; flex-shrink: 0; }.kd-properties { margin: 0; font-size: var(--rs-font-size-secondary); }.kd-properties > div { display: grid; grid-template-columns: 110px minmax(0,1fr); gap: 16px; padding: 19px 0; border-bottom: 1px solid var(--rs-border-soft); align-items: center; line-height: 1.7; }.kd-properties > div:last-child { border: none; padding-bottom: 4px; }.kd-properties dt { color: var(--rs-text-3); }.kd-properties dd { margin: 0; overflow-wrap: anywhere; }.kd-copy-value { display: flex; align-items: center; gap: 10px; min-width: 0; }.kd-copy-value code { font-size: var(--rs-font-size-caption); overflow-wrap: anywhere; }.kd-copy-value .icon-button { flex-shrink: 0; }.kd-owner { display: inline-flex; align-items: center; justify-content: center; background: var(--rs-bg-selected); color: var(--rs-primary); width: 24px; height: 24px; border-radius: 50%; margin-right: 8px; font-size: 11px; }.kd-properties-stack > div { grid-template-columns: 1fr; gap: 8px; padding: 14px 0; }.kd-properties-stack .kd-copy-value { justify-content: space-between; }.kd-info-note { display: flex; align-items: center; gap: 7px; color: var(--rs-text-3); background: var(--rs-bg-soft); padding: 12px; border-radius: 6px; margin: 20px 0 0; }.kd-info-note svg { width: 14px; height: 14px; }.kd-info-side { display: grid; grid-template-rows: minmax(min-content, 1fr) auto; gap: 24px; }.kd-info-side > .kd-info-card { display: flex; flex-direction: column; }.kd-info-side .kd-properties { flex: 1; }.kd-tip { display: flex; align-items: flex-start; gap: 14px; background: var(--rs-bg-hover); border: 1px solid var(--rs-border); border-radius: 10px; padding: 24px; }.kd-tip h3 { margin: 0 0 7px; }.kd-tip p { color: var(--rs-text-2); margin: 0 0 12px; }
.kd-folder-row { position:relative; }.kd-folder-row .kd-folder { padding-right:40px; }.kd-folder-row > .el-dropdown { position:absolute;right:4px;top:50%;transform:translateY(-50%); }.kd-move-form { padding:24px 0; }.kd-move-form > p { overflow-wrap:anywhere;max-height:120px;overflow:auto; }
.kd-document-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 8px 0 17px; border-bottom: 1px solid var(--rs-border); }.kd-document-heading > .kd-tab-label { font-size: var(--rs-font-size-tab); font-weight: 600; color: var(--rs-primary); }.kd-document-layout { flex: 1; min-height: 0; display: grid; grid-template-columns: 202px minmax(0,1fr); gap: 24px; }.kd-folders { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--rs-border); padding-right: 20px; }.kd-folder-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }.kd-folders :deep(.el-input__wrapper) { min-height: 34px; padding-left: 10px; }.kd-folder-list { display: flex; flex-direction: column; gap: 5px; margin-top: 16px; overflow: auto; }.kd-folder { border: 0; background: none; color: var(--rs-text-2); display: flex; align-items: center; gap: 9px; width: 100%; padding: 11px 10px; border-radius: 6px; text-align: left; font-size: var(--rs-font-size-secondary); }.kd-folder > svg { width: 16px; height: 16px; }.kd-folder > span:nth-child(2) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }.kd-folder.active { background: var(--rs-bg-selected); color: var(--rs-primary); font-weight: 500; }.kd-folder:hover { background: var(--rs-bg-hover); }.kd-folder-count { margin-left: auto; font-size: 11px; color: var(--rs-text-3); }.kd-folder-foot { margin-top: auto; padding-top: 24px; color: var(--rs-text-3); display: flex; align-items: flex-start; gap: 7px; line-height: 1.8; }.kd-folder-foot svg { width: 13px; height: 13px; margin-top: 3px; }.kd-document-main { min-height: 0; min-width: 0; display: flex; flex-direction: column; gap: 16px; }.kd-doc-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; }.kd-doc-toolbar h2 { margin: 0 0 5px; display: flex; align-items: center; gap: 12px; }.kd-doc-toolbar p { margin: 0; }.kd-doc-filters { justify-content: flex-start; flex-wrap: nowrap; }.kd-doc-filters .kd-search { flex: 1; max-width: 400px; }.kd-selection { display: flex; align-items: center; gap: 16px; padding: 9px 12px; background: var(--rs-bg-selected); border-radius: 6px; }.kd-files-table { flex: 1; min-height: 100px; overflow: auto; }.kd-files-table .list-table { min-width: 760px; }.kd-files-table thead { position: sticky; top: 0; z-index: 1; }.kd-file-name { display: flex; gap: 10px; align-items: center; text-align: left; border: none; background: none; padding: 0; color: var(--rs-text); font-size: var(--rs-font-size-secondary); }.kd-file-name b { font-weight: 650; }.kd-file-name:hover b { color: var(--rs-primary); }.kd-doc-icon { width: var(--rs-table-icon-size); height: var(--rs-table-icon-size); display: flex; align-items: center; justify-content: center; background: var(--tint); color: var(--tone); border-radius: 6px; }.kd-doc-icon svg { width: 18px; }.kd-file-name .entity-sub { display: block; }.kd-separator { margin: 0 6px; }.kd-file-actions { display: flex; align-items: center; gap: 6px; }.kd-file-actions svg { width: 15px; height: 15px; }.tag-soft .status-dot { width: 5px; height: 5px; margin-right: 2px; }.kd-error-status { color: var(--rs-danger); background: color-mix(in srgb, var(--rs-danger) 10%, var(--rs-bg-card)); }
.kd-drawer-status { display: flex; justify-content: space-between; align-items: center; background: var(--rs-bg-soft); border-radius: 8px; padding: 10px 16px; margin-bottom: 28px; }.kd-full-content { line-height: 2; color: var(--rs-text-2); padding: 18px; background: var(--rs-bg-soft); border-radius: 8px; margin: 20px 0; }.kd-preview-title { overflow-wrap: anywhere; }.kd-preview-content { font-family: inherit; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.9; margin-top: 24px; color: var(--rs-text-2); }.kd-upload-folder { width: 100%; }
@media (min-width: 1700px) { .kd-chunks { grid-template-columns: repeat(4,minmax(0,1fr)); } }
@media (max-width: 1250px) { .kd-overview { grid-template-columns: repeat(3,1fr); row-gap: 16px; }.kd-model { grid-column: 1 / -1; border-top: 1px solid var(--rs-border-soft); padding-top: 14px; }.kd-metric:nth-child(3) { border-right: 0; }.kd-model .tag-soft { margin-left: 4px; }.kd-document-layout { grid-template-columns: 170px minmax(0,1fr); gap: 18px; }.kd-folders { padding-right: 14px; }.kd-chunks { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 950px) { .kd-info-layout { grid-template-columns: 1fr; }.kd-info-layout > .kd-info-card,.kd-info-layout > .kd-info-card > .kd-properties { display: block; }.kd-info-card { padding: 20px; }.kd-search { width: 260px; }.kd-source { width: 180px; }.kd-metric { padding: 0 16px; }.kd-metric-icon { width: 32px; height: 32px; }.kd-metric-value { font-size: 20px; }.kd-pagination { flex-wrap: wrap; }.kd-pagination > span { display: none; }.kd-pagination :deep(.el-pagination) { margin-left: auto; } }
@media (max-width: 700px) { .knowledge-detail :deep(.workspace-body) { min-height: auto; }.kd-chunks-scroll { flex: none; overflow: visible; }.kd-chunks { grid-template-columns: 1fr; }.kd-overview { grid-template-columns: repeat(3,minmax(0,1fr)); }.kd-metric { padding: 0 8px; gap: 6px; }.kd-metric-icon { display: none; }.kd-metric-value { font-size: 18px; }.kd-model { padding: 12px 8px 0; gap: 6px; }.kd-model .tag-soft { display: none; }.kd-model .text-label { font-size: 12px; }.kd-results > span:last-child { display: none; }.kd-search-group { width: 100%; }.kd-search,.kd-source { width: 100%; }.kd-document-layout { grid-template-columns: 1fr; flex: none; }.kd-folders { border-right: 0; border-bottom: 1px solid var(--rs-border); padding: 0 0 12px; }.kd-folders > .el-input,.kd-folder-foot { display: none; }.kd-folder-list { flex-direction: row; margin-top: 0; }.kd-folder { width: auto; flex-shrink: 0; }.kd-folder-heading { margin-bottom: 5px; }.kd-files-table { max-height: 620px; flex: none; }.kd-document-heading > .muted { display: none; }.kd-properties > div { grid-template-columns: 86px minmax(0,1fr); gap: 8px; }.kd-properties-stack > div { grid-template-columns: 1fr; }.kd-pagination :deep(.el-pagination) { flex-wrap: wrap; gap: 3px; }.kd-doc-toolbar h2 { flex-wrap: wrap; }.kd-doc-toolbar { align-items: flex-start; }.kd-doc-filters { flex-wrap: wrap; } }
</style>
