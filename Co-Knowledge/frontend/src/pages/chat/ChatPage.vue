<template>
  <!-- 不传 scrollable：用 AppPage 默认 fill 拿到父级 .content-router-box 的 100% 高度，
       高度再经 .page-inner → .chat-workspace(flex:1) 传下去；否则 app-page 退化为
       内容高度，工作区只剩 min-height:650px，输入区贴不住页面底部。 -->
  <AppPage class="management-page chat-page">
    <div class="page-inner">
      <PageHeader
        :title="$t('nav.chat')"
        :subtitle="$t('modules.chatTest.pageSubtitle')"
        :icon="Document"
      />

      <div class="chat-workspace">
        <!-- 工具栏升为整页通栏（工作流/刷新/发布规则 + 右侧新会话），
           下方历史、对话、检索面板顶部对齐。完整发布规则收进提示气泡。 -->
        <div class="chat-toolbar" role="group" :aria-label="$t('modules.chatTest.toolbarAria')">
          <div class="chat-toolbar-context">
            <span class="chat-toolbar__label">{{ $t('modules.chatTest.workflowLabel') }}</span>
            <el-select
              v-model="selectedWorkflowId"
              class="chat-workflow-select"
              filterable
              :placeholder="$t('modules.chatTest.workflowPlaceholder')"
              :loading="loadingWorkflows"
              :disabled="sending || !publishedWorkflows.length"
              :aria-label="$t('modules.chatTest.workflowLabel')"
            >
              <el-option
                v-for="wf in publishedWorkflows"
                :key="wf.workFlowId"
                :label="wf.name"
                :value="wf.workFlowId"
              />
            </el-select>
            <TableRefreshButton
              :label="$t('modules.chatTest.refreshPublished')"
              :refresh="refreshWorkflows"
            />
            <el-tooltip
              :content="$t('modules.chatTest.publishedHint')"
              placement="bottom"
              :trigger="['hover', 'focus', 'click']"
            >
              <button
                type="button"
                class="chat-publish-note"
                :aria-label="$t('modules.chatTest.onlyPublished')"
              >
                <InfoFilled />
                <span>{{ $t('modules.chatTest.onlyPublished') }}</span>
              </button>
            </el-tooltip>
          </div>
          <el-button type="primary" @click="newConversation">
            <ChatLineSquare />
            {{ $t('modules.chatTest.newSession') }}
          </el-button>
        </div>

        <div class="chat-left">
          <!-- 工作流引用了已删除的知识库：运行时按名称查不到库，会静默召回 0 条。
             这里把「静默」变成可见告警。 -->
          <el-alert
            v-if="missingKbNames.length"
            class="chat-hint"
            type="warning"
            show-icon
            :closable="false"
            :title="$t('modules.chatTest.missingKbTitle')"
            :description="$t('modules.chatTest.missingKbDesc', { names: missingKbLabels.join(', ') })"
          />

          <div v-if="loadingWorkflows" class="chat-filling">
            <AppEmpty state="loading" :title="$t('public.loading')" />
          </div>

          <!-- 加载失败与「一条都没发布」必须分开：把网络错误说成「还没有已发布的工作流」
             会把人指到错误的方向上去排查。 -->
          <div v-else-if="loadError" class="chat-filling">
            <AppEmpty state="error" :description="loadError" @retry="refreshWorkflows" />
          </div>

          <template v-else>
            <el-alert
              v-if="!publishedWorkflows.length"
              class="chat-no-workflows"
              type="info"
              :closable="false"
              show-icon
            >
              <template #title>
                {{ $t('modules.chatTest.noWorkflowsAlert') }}
                <RouterLink to="/flow">{{ $t('modules.chatTest.goPublish') }}</RouterLink>
              </template>
            </el-alert>

          <div class="chat-columns">
            <!-- 历史会话（置顶 / 重命名 / 导出 / 删除 / 清空） -->
            <ChatHistoryPanel
              v-model:search="historySearch"
              :histories="filteredSessions"
              :total="sessions.length"
              :active-id="conversationId"
              @select="selectHistory"
              @action="historyAction"
              @manage="manageHistories"
            />

            <!-- 对话主区 -->
            <section class="chat-main content-card">
              <div ref="messagesRef" class="conversation">
                <div v-if="!messages.length" class="chat-welcome">
                  <BrandMark />
                  <h3>{{ $t('modules.chatTest.welcomeTitle') }}</h3>
                  <p>{{ $t('modules.chatTest.welcomeDesc') }}</p>
                  <button type="button" @click="question = $t('modules.chatTest.suggestionRag')">
                    {{ $t('modules.chatTest.suggestionRag') }}
                    <Right />
                  </button>
                </div>

                <div v-else class="conversation-date">
                  {{ currentSessionDate }}
                </div>

                <div
                  v-for="(msg, idx) in messages"
                  :key="idx"
                  class="message-line"
                  :class="msg.role"
                >
                  <template v-if="msg.role === 'user'">
                    <div class="user-bubble">
                      {{ msg.text }}
                    </div>
                    <div class="user-avatar">
                      {{ $t('modules.chatTest.roleUser') }}
                    </div>
                  </template>

                  <template v-else>
                    <div class="assistant-avatar">
                      <BrandMark />
                    </div>
                    <div class="assistant-message">
                      <details
                        v-if="msg.evidence"
                        class="chat-evidence"
                        :open="msg.pending"
                      >
                        <summary class="chat-evidence__summary">
                          <span class="chat-evidence__title">{{ $t('modules.chatTest.evidenceTitle') }}</span>
                          <span v-if="msg.pending && msg.evidence.items.length" class="chat-evidence__meta">
                            {{ $t('modules.chatTest.evidenceGenerating', {
                              count: msg.evidence.stats.total,
                              sources: msg.evidence.stats.sources
                            }) }}
                          </span>
                          <span v-else-if="msg.evidence.items.length" class="chat-evidence__meta">
                            {{ $t('modules.chatTest.evidenceSummary', {
                              count: msg.evidence.stats.total,
                              sources: msg.evidence.stats.sources
                            }) }}
                          </span>
                          <span v-else class="chat-evidence__meta">
                            {{ $t('modules.chatTest.evidenceEmpty') }}<template v-if="boundKbLabels.length">
                              · {{ $t('modules.chatTest.evidenceEmptyWithKbs', { names: boundKbLabels.join('、') }) }}
                            </template>
                          </span>
                        </summary>
                        <div v-if="msg.evidence.items.length" class="chat-evidence__body">
                          <p v-if="msg.evidence.query" class="chat-evidence__query">
                            {{ $t('modules.chatTest.evidenceQueryLabel') }}{{ msg.evidence.query }}
                          </p>
                          <ol class="chat-evidence__list">
                            <li
                              v-for="item in msg.evidence.items"
                              :key="item.index"
                              class="chat-evidence__item"
                            >
                              <div class="chat-evidence__head">
                                <span class="chat-evidence__rank">#{{ item.index }}</span>
                                <span class="chat-evidence__kind">
                                  {{ item.kind === 'graph'
                                    ? $t('modules.chatTest.evidenceKindGraph')
                                    : $t('modules.chatTest.evidenceKindDocument') }}
                                </span>
                                <span v-if="item.kb" class="chat-evidence__kb">{{ kbLabel(item.kb) }}</span>
                                <span class="chat-evidence__source">
                                  {{ item.source || $t('modules.chatTest.evidenceSourceUnknown') }}<template v-if="item.chunkIndex">
                                    · {{ $t('modules.chatTest.evidenceChunkIndex', { index: item.chunkIndex }) }}
                                  </template>
                                </span>
                                <span
                                  v-if="formatEvidenceScore(item.score)"
                                  class="chat-evidence__score"
                                  :title="evidenceScoreHint"
                                >
                                  {{ $t('modules.chatTest.evidenceScoreLabel') }} {{ formatEvidenceScore(item.score) }}
                                </span>
                              </div>
                              <p v-if="item.text" class="chat-evidence__text">
                                {{ item.text }}<span v-if="item.truncated" class="chat-evidence__truncated">
                                  {{ $t('modules.chatTest.evidenceTruncated') }}
                                </span>
                              </p>
                            </li>
                          </ol>
                          <p
                            v-if="msg.evidence.stats.total > msg.evidence.items.length"
                            class="chat-evidence__stored"
                          >
                            {{ $t('modules.chatTest.evidenceStoredHint', {
                              total: msg.evidence.stats.total,
                              count: msg.evidence.items.length
                            }) }}
                          </p>
                        </div>
                      </details>

                      <div class="assistant-bubble" :class="{ 'assistant-bubble--error': msg.error }">
                        <!-- 判定顺序是**先内容、后等待**：流式期间 `pending` 一直是 true，
                           反过来写（pending 优先）会把渐长的正文一直挡在等待文案后面。 -->
                        <template v-if="msg.thinking || msg.text">
                          <div v-if="msg.thinking && msg.pending" class="chat-reasoning">
                            <div class="chat-reasoning__title">
                              {{ $t('modules.chatTest.reasoningLabel') }}
                            </div>
                            <pre class="chat-reasoning__body">{{ msg.thinking }}</pre>
                          </div>
                          <details v-else-if="msg.thinking" class="chat-reasoning">
                            <summary>{{ $t('modules.chatTest.reasoningLabel') }}</summary>
                            <pre class="chat-reasoning__body">{{ msg.thinking }}</pre>
                          </details>
                          <div
                            v-if="msg.html"
                            class="chat-markdown"
                            v-html="msg.html"
                          />
                          <div v-else-if="msg.text" class="chat-markdown-raw">
                            {{ msg.text }}
                          </div>
                        </template>
                        <span v-else-if="msg.pending" class="chat-pending">
                          {{ $t('modules.chatTest.thinking') }}
                        </span>
                        <span v-if="msg.stopped" class="chat-stopped">
                          {{ $t('modules.chatTest.stopped') }}
                        </span>
                      </div>

                      <div class="msg-meta">
                        <button type="button" @click="copyMessage(msg)">
                          <CopyDocument />
                          {{ $t('modules.chatTest.copyAnswer') }}
                        </button>
                        <button
                          type="button"
                          :class="{ voted: msg.vote === 1 }"
                          :aria-label="$t('modules.chatTest.voteUp')"
                          @click="toggleVote(msg, 1)"
                        >
                          <Pointer />
                        </button>
                        <button
                          type="button"
                          :class="{ voted: msg.vote === -1 }"
                          :aria-label="$t('modules.chatTest.voteDown')"
                          @click="toggleVote(msg, -1)"
                        >
                          <Pointer class="dislike" />
                        </button>
                        <span v-if="msg.evidence && msg.evidence.items.length" class="push">
                          <i />
                          {{ formatMs(msg.totalMs) }}
                          <span class="meta-divider">|</span>
                          {{ $t('modules.chatTest.docsUsed', { count: msg.evidence.stats.sources }) }}
                        </span>
                      </div>
                    </div>
                  </template>
                </div>
              </div>

              <footer class="composer">
                <textarea
                  v-model="question"
                  :placeholder="$t('modules.chatTest.inputPlaceholder')"
                  :aria-label="$t('modules.chatTest.inputPlaceholder')"
                  @keydown.enter.exact="onEnterKey"
                />
                <div class="composer-bottom">
                  <div class="composer-tools">
                    <el-tooltip :content="$t('modules.chatTest.attachmentNotConnected')" placement="top">
                      <button
                        type="button"
                        class="icon-button"
                        :aria-label="$t('modules.chatTest.addAttachment')"
                        @click="showNotConnected('attachmentNotConnected')"
                      >
                        <Paperclip />
                      </button>
                    </el-tooltip>
                    <el-popover placement="top-start" width="240" trigger="click">
                      <template #reference>
                        <button
                          type="button"
                          class="icon-button"
                          :aria-label="$t('modules.chatTest.chatSettings')"
                        >
                          <Setting />
                        </button>
                      </template>
                      <div class="chat-setting">
                        <span>{{ $t('modules.chatTest.citations') }}</span>
                        <el-switch :model-value="true" size="small" disabled />
                      </div>
                      <p class="chat-setting-note">
                        {{ $t('modules.chatTest.citationsNotConnected') }}
                      </p>
                    </el-popover>
                  </div>
                  <el-button
                    v-if="sending"
                    @click="stopGenerating"
                  >
                    {{ $t('modules.chatTest.stop') }}
                  </el-button>
                  <el-button
                    v-else
                    type="primary"
                    :disabled="!canSend"
                    @click="send"
                  >
                    <Position />
                    {{ $t('modules.chatTest.send') }}
                  </el-button>
                </div>
              </footer>
            </section>
          </div>
          </template>
        </div>

        <!-- 右侧：检索链路与效果（数据来自本轮真实检索依据） -->
        <aside class="trace right-panel">
          <div class="section-title">
            {{ $t('modules.chatTest.traceTitle') }}
            <el-button link type="primary" @click="traceDrawer = true">
              {{ $t('modules.chatTest.traceFullLink') }}
            </el-button>
          </div>
          <div class="trace-flow">
            <template v-for="(step, index) in traceSteps" :key="step.key">
              <div class="trace-step" :data-stage="step.key">
                <div :class="['tinted-icon', step.tone]">
                  <component :is="step.icon" />
                </div>
                <b>{{ step.name }}</b>
                <span>{{ step.ms }}</span>
              </div>
              <Right v-if="index < traceSteps.length - 1" class="trace-arrow" />
            </template>
          </div>
          <div class="trace-metrics">
            <!-- 分数量纲随重排模型而定（不是 0–1 的相似度）：指标卡给 2 位是摘要口径，
                 右边命中列表的 4 位是明细口径（与「检索监控」页一致）。用 title 把
                 「这是模型原始分」讲清楚，避免和文档库 0–1 的相似度混读。 -->
            <div v-for="metric in traceMetrics" :key="metric.name" :title="metric.hint || ''">
              <span :class="['tinted-icon', metric.tone]">
                <component :is="metric.icon" />
              </span>
              <b>{{ metric.value }}</b>
              <span class="trace-metric-label">{{ metric.name }}</span>
            </div>
          </div>
          <div class="hits-heading">
            {{ $t('modules.chatTest.hitsTitle') }}
            <el-tooltip :content="$t('modules.chatTest.hitsTooltip')">
              <InfoFilled />
            </el-tooltip>
          </div>
          <div v-if="!evidenceDocs.length" class="trace-empty">
            {{ $t('modules.chatTest.noHits') }}
          </div>
          <button
            v-for="(doc, index) in evidenceDocs"
            :key="`${doc.title}-${index}`"
            type="button"
            class="doc-hit"
            @click="selectedDoc = doc"
          >
            <span class="doc-index">{{ index + 1 }}</span>
            <span class="doc-hit-content">
              <span class="doc-hit-heading">
                <b>{{ doc.title }}</b>
                <strong :title="evidenceScoreHint">{{ doc.score }}</strong>
              </span>
              <span class="doc-file">
                <Document />
                {{ doc.file }}
              </span>
              <span class="doc-snippet">{{ doc.snippet }}</span>
            </span>
          </button>
        </aside>
      </div>

      <el-drawer v-model="traceDrawer" :title="$t('modules.chatTest.traceDrawerTitle')" size="420px">
        <el-timeline>
          <el-timeline-item
            v-for="step in traceSteps"
            :key="step.key"
            :timestamp="step.ms"
            color="#1677ff"
          >
            <b>{{ step.name }}</b>
            <p class="muted">
              {{ step.detail }}
            </p>
          </el-timeline-item>
        </el-timeline>
        <el-alert :title="$t('modules.chatTest.traceDemoHint')" type="info" :closable="false" />
      </el-drawer>

      <el-dialog
        :model-value="!!selectedDoc"
        :title="selectedDoc?.title"
        width="560px"
        @close="selectedDoc = null"
      >
        <p class="muted">
          {{ selectedDoc?.file }}
        </p>
        <p class="doc-detail">
          {{ selectedDoc?.snippet }}
        </p>
        <template #footer>
          <el-button @click="selectedDoc = null">
            {{ $t('modules.chatTest.docDetailClose') }}
          </el-button>
        </template>
      </el-dialog>

      <!-- 历史会话重命名 -->
      <StudioDialog
        v-model="renameOpen"
        dialog-class="chat-rename-dialog"
        :title="$t('modules.chatTest.renameTitle')"
        :subtitle="$t('modules.chatTest.renameSubtitle')"
        :icon="Edit"
        :hint="$t('modules.chatTest.renameHint')"
        width="480px"
        @opened="renameInput?.focus()"
      >
        <el-form class="studio-form chat-rename-form" label-position="top" @submit.prevent="saveHistoryName">
          <el-form-item :label="$t('modules.chatTest.sessionName')" :error="renameError">
            <el-input
              ref="renameInput"
              v-model="renameTitle"
              :aria-label="$t('modules.chatTest.sessionName')"
              maxlength="80"
              show-word-limit
              :placeholder="$t('modules.chatTest.sessionNamePlaceholder')"
              @input="renameError = ''"
            />
          </el-form-item>
        </el-form>
        <template #actions>
          <el-button @click="renameOpen = false">{{ $t('public.cancel') }}</el-button>
          <el-button type="primary" @click="saveHistoryName">{{ $t('modules.chatTest.saveName') }}</el-button>
        </template>
      </StudioDialog>
    </div>
  </AppPage>
</template>

<script lang="ts" setup>
/**
 * 对话测试页（路由 `/chat`，chunk `module.flow`）。
 *
 * 这一层只做视图编排与渲染：数据状态与业务逻辑都在同目录下的
 * `lib/*.ts`（零 Vue 依赖的纯函数，可单测）与 `composables/*.ts`（状态与副作用）里。
 */
import { computed, nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ChatLineSquare,
  CopyDocument,
  Pointer,
  Position,
  Right,
  InfoFilled,
  Document,
  Clock,
  Histogram,
  Coin,
  Paperclip,
  Setting,
  Edit,
  Search,
  Share
} from '@/shared/lib/icons'
import { SplitIcon, LayersIcon, SparkleIcon } from '@/shared/ui/icons'
import BrandMark from '@/shared/ui/BrandMark.vue'
import AppPage from '@/shared/ui/AppPage.vue'
import PageHeader from '@/shared/ui/reference/PageHeader.vue'
import AppEmpty from '@/shared/ui/AppEmpty.vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import TableRefreshButton from '@/shared/ui/TableRefreshButton.vue'
import ChatHistoryPanel from '@/features/chat/components/ChatHistoryPanel.vue'
import { copyText } from '@/shared/lib/clipboard'
import message from '@/shared/lib/message'
import { requestDeletion } from '@/shared/composables/deletion'
import { download } from '@/shared/lib/utils'
import { useChatSession } from '@/features/chat/composables/useChatSession'
import { useChatStream } from '@/features/chat/composables/useChatStream'
import { usePublishedWorkflows } from '@/features/chat/composables/usePublishedWorkflows'
import { useWorkflowBindingCheck } from '@/features/chat/composables/useWorkflowBindingCheck'
import { formatEvidenceScore } from '@/features/chat/lib/evidence'
import { formatMs, resolveRetrievalStages, resolveTraceTimings } from '@/features/chat/lib/trace'
import { normalizeKbIdentity } from '@/features/chat/lib/kb-bindings'

const { t } = useI18n()

// : 距底部多少像素以内算「贴着底」，流式自动滚动只在这个范围内跟随
const NEAR_BOTTOM_PX = 40
// 中文输入法组字期间按 Enter 是在「确认候选词」，部分浏览器此时给出的 keyCode
const IME_COMPOSING_KEYCODE = 229

// 已发布工作流下拉（含 publishType 过滤、空态/错误态、挂载即加载）
const { loadingWorkflows, loadError, publishedWorkflows, selectedWorkflowId, loadWorkflows } = usePublishedWorkflows()

// 当前工作流的「绑定库是否还活着」核对（只告警，不阻断提问）
const { missingKbNames, recheck: recheckKbBindings } = useWorkflowBindingCheck(selectedWorkflowId)

const selectedWorkflow = computed(() => publishedWorkflows.value.find(wf => wf.workFlowId === selectedWorkflowId.value))

// 当前工作流绑定的库（文档库 + 图谱库）；证据/零命中提示都复用
const boundKbs = computed(() => [
  ...(selectedWorkflow.value?.kbPkIds || []),
  ...(selectedWorkflow.value?.graphKbPkIds || [])
])

const boundKbLabels = computed(() => boundKbs.value
  .map(kb => kb.name)
  .filter((name): name is string => typeof name === 'string' && !!name))

// 证据里的 base（doc_<uuid> / graph_<uuid>）→ 创建时的可读库名
const kbLabelByIdentity = computed(() => {
  const labels = new Map<string, string>()
  for (const kb of boundKbs.value) {
    if (typeof kb.name !== 'string' || !kb.name) {
      continue
    }
    for (const field of ['tableName', 'dbTableName', 'assetId', 'kbaseId'] as const) {
      const identity = normalizeKbIdentity(kb[field])
      if (identity) {
        labels.set(identity, kb.name)
      }
    }
  }
  return labels
})

function kbLabel (base: string): string {
  const identity = normalizeKbIdentity(base)
  return (identity && kbLabelByIdentity.value.get(identity)) || base
}

// 已发布快照里只有检索基名（doc_<uuid>），告警里尽量换回创建时的库名
const missingKbLabels = computed(() => {
  const bound = boundKbs.value
  return missingKbNames.value.map(raw => {
    const identity = normalizeKbIdentity(raw)
    const hit = bound.find(kb => (
      normalizeKbIdentity(kb.assetId) === identity || normalizeKbIdentity(kb.tableName) === identity
    ))
    return hit?.name || raw
  })
})

// 刷新按钮：列表与绑定核对一起重跑（选中项不变时 watcher 不会触发）
async function refreshWorkflows (): Promise<void> {
  await loadWorkflows()
  await recheckKbBindings()
}

// 消息状态 + 多段历史（恢复/快照/节流落盘；订阅 selectedWorkflowId 切会话集合）
const {
  messages,
  conversationId,
  sessions,
  newConversation,
  selectConversation,
  deleteConversation,
  renameConversation,
  togglePin,
  clearAll,
  sessionMessages,
  exportSessions,
  flush
} = useChatSession(selectedWorkflowId)

function selectHistory (history: { conversationId: string }): void {
  selectConversation(history.conversationId)
}

function formatFullDate (savedAt: number): string {
  if (!savedAt) {
    return ''
  }
  const date = new Date(savedAt)
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/* ── 历史搜索（新 UX） ─────────────────────────────────────────── */
const historySearch = ref('')

const filteredSessions = computed(() => {
  const keyword = historySearch.value.trim().toLowerCase()
  if (!keyword) {
    return sessions.value
  }
  return sessions.value.filter(item => String(item.title || '').toLowerCase()
    .includes(keyword))
})

/* ── 历史会话操作：置顶 / 重命名 / 导出 / 删除 / 清空 ─────────── */
const renameOpen = ref(false)
const renameTarget = ref<any>(null)
const renameTitle = ref('')
const renameError = ref('')
const renameInput = ref<HTMLElement | null>(null)

function historyAction (command: string, history: any): void {
  if (command === 'pin') {
    togglePin(history.conversationId)
    return
  }
  if (command === 'rename') {
    renameTarget.value = history
    renameTitle.value = history.title || ''
    renameError.value = ''
    renameOpen.value = true
    return
  }
  if (command === 'export') {
    exportHistories([history])
    return
  }
  if (command === 'delete') {
    removeHistories([history])
  }
}

function saveHistoryName (): void {
  const title = renameTitle.value.trim()
  if (!title) {
    renameError.value = t('modules.chatTest.renameRequired')
    return
  }
  const target = renameTarget.value
  if (target && sessions.value.some(item => item.conversationId === target.conversationId)) {
    renameConversation(target.conversationId, title)
  } else {
    renameOpen.value = false
    return
  }
  renameOpen.value = false
  message.success(t('modules.chatTest.renameSuccess'))
}

function exportHistories (targets: any[]): void {
  if (!targets.length) {
    return
  }
  const content = targets.map(history => {
    const messagesOfHistory = sessionMessages(history.conversationId)
    const body = messagesOfHistory.map(item => (
      `## ${item.role === 'user' ? t('modules.chatTest.roleUser') : t('modules.chatTest.roleAssistant')}\n\n${item.text}`
    )).join('\n\n') || t('modules.chatTest.historyEmptyDesc')
    return `# ${history.title}\n\n${t('modules.chatTest.conversationDate')}：${formatFullDate(history.savedAt)}\n\n${body}`
  }).join('\n\n---\n\n')
  const name = targets.length === 1 ? targets[0].title : t('modules.chatTest.historyExportName')
  const safeName = String(name || 'chat').replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')
    .replace(/[. ]+$/g, '').slice(0, 80) || 'chat'
  download(content, `${safeName}.md`, 'text/markdown;charset=utf-8')
  message.success(t('modules.chatTest.exportSuccess'))
}

function manageHistories (command: string): void {
  if (command === 'export') {
    exportHistories(exportSessions())
    return
  }
  if (command === 'clear') {
    removeHistories(exportSessions(), true)
  }
}

async function removeHistories (targets: any[], all = false): Promise<void> {
  if (!targets.length) {
    return
  }
  const confirmed = await requestDeletion({
    resourceType: t('modules.chatTest.historyTitle'),
    title: all ? t('modules.chatTest.clearHistory') : t('modules.chatTest.deleteSession'),
    warning: all ? t('modules.chatTest.clearWarning') : t('modules.chatTest.deleteWarning'),
    description: t('modules.chatTest.deleteDescription'),
    items: targets.map(history => ({
      id: history.conversationId,
      name: history.title,
      meta: `${formatFullDate(history.savedAt)} · ${t('modules.chatTest.messageCount', { count: history.messageCount ?? sessionMessages(history.conversationId).length })}`,
      tag: history.pinned ? t('modules.chatTest.pinned') : ''
    })),
    detail: all
      ? t('modules.chatTest.clearDetail', { count: targets.length })
      : t('modules.chatTest.deleteDetailOther'),
    hint: t('modules.chatTest.deleteHint')
  })
  if (!confirmed) {
    return
  }
  if (all) {
    clearAll()
    message.success(t('modules.chatTest.clearSuccess'))
    return
  }
  targets.forEach(history => deleteConversation(history.conversationId))
  message.success(t('modules.chatTest.deleteSuccess'))
}

const currentSessionDate = computed(() => {
  const current = sessions.value.find(item => item.conversationId === conversationId.value)
  return formatFullDate(current?.savedAt || Date.now())
})

/* ── 右侧检索链路（真实数据） ───────────────────────────────────── */
function showNotConnected (key: string) {
  message.info(t(`modules.chatTest.${key}`))
}

const traceDrawer = ref(false)
const selectedDoc = ref<any>(null)

const latestAssistant = computed(() => {
  const list = messages.value
  for (let i = list.length - 1; i >= 0; i -= 1) {
    if (list[i].role === 'assistant') {
      return list[i]
    }
  }
  return null
})

const latestEvidence = computed(() => latestAssistant.value?.evidence || null)

// 阶段耗时：前三段来自服务端 evidence.timings，生成回答用客户端整段相位。
// 解析逻辑放在 lib/trace.ts，页面只负责格式化与渲染。
const stageTimings = computed(() => resolveTraceTimings(latestEvidence.value, latestAssistant.value))

// 命中片段分数字段的 tooltip：有重排时是重排模型量纲（LLM 1–10），
// 没启用重排时是检索器原始分（向量相似度通常 0–1），两者不能混着解释。
const evidenceScoreHint = computed(() => (
  stageTimings.value.rerankMs !== undefined
    ? t('modules.chatTest.evidenceScoreHint')
    : t('modules.chatTest.evidenceScoreHintNoRerank')
))

// 证据全部来自图谱库、但只有合计值时，也要显示「图谱检索」。
const graphEvidenceOnly = computed(() => {
  const items = latestEvidence.value?.items || []
  return items.length > 0 && items.every(item => item.kind === 'graph')
})

// 检索阶段按实际执行的检索器拆开展示：混合检索出现「向量检索 + 关键字检索」，
// 条件工作流只出现命中的那一路，图谱工作流出现「图谱检索」；只有合计值时按证据
// 类型回落。`data-stage` 仍用 retrieval，既有 E2E 钩子不变。
const traceSteps = computed(() => {
  const timings = stageTimings.value
  const steps = [
    { key: 'understanding', name: t('modules.chatTest.traceProblem'), ms: formatMs(timings.understandingMs), icon: Document, tone: 'blue', detail: t('modules.chatTest.traceProblemDetail') }
  ]
  const fallbackKey = graphEvidenceOnly.value ? 'graph' : 'vector'
  for (const stage of resolveRetrievalStages(timings, fallbackKey)) {
    if (stage.key === 'keyword') {
      steps.push({ key: 'keyword', name: t('modules.chatTest.traceKeyword'), ms: formatMs(stage.ms), icon: Search, tone: 'orange', detail: t('modules.chatTest.traceKeywordDetail') })
    } else if (stage.key === 'graph') {
      steps.push({ key: 'graph', name: t('modules.chatTest.traceGraph'), ms: formatMs(stage.ms), icon: Share, tone: 'purple', detail: t('modules.chatTest.traceGraphDetail') })
    } else {
      steps.push({ key: 'retrieval', name: t('modules.chatTest.traceVector'), ms: formatMs(stage.ms), icon: LayersIcon, tone: 'green', detail: t('modules.chatTest.traceVectorDetail') })
    }
  }
  steps.push(
    { key: 'rerank', name: t('modules.chatTest.traceRerank'), ms: formatMs(timings.rerankMs), icon: SplitIcon, tone: 'purple', detail: t('modules.chatTest.traceRerankDetail') },
    { key: 'generate', name: t('modules.chatTest.traceGenerate'), ms: formatMs(timings.generateMs), icon: SparkleIcon, tone: 'blue', detail: t('modules.chatTest.traceGenerateDetail') }
  )
  return steps
})

const traceMetrics = computed(() => {
  const reply = latestAssistant.value
  const evidence = latestEvidence.value
  const items = evidence?.items || []
  const topScore = items.reduce((max, item) => Math.max(max, Number(item.score) || 0), 0)
  return [
    { name: t('modules.chatTest.metricTotal'), value: formatMs(reply?.totalMs), icon: Clock, tone: 'blue' },
    { name: t('modules.chatTest.metricHits'), value: items.length ? String(items.length) : '—', icon: Document, tone: 'blue' },
    {
      name: t('modules.chatTest.metricTopScore'),
      value: topScore ? topScore.toFixed(2) : '—',
      icon: Histogram,
      tone: 'green',
      hint: t('modules.chatTest.metricTopScoreHint')
    },
    { name: t('modules.chatTest.metricSources'), value: evidence?.stats?.sources ? String(evidence.stats.sources) : '—', icon: Coin, tone: 'purple' }
  ]
})

const evidenceDocs = computed(() => {
  const evidence = latestEvidence.value
  if (!evidence) {
    return []
  }
  return evidence.items.map(item => ({
    title: item.label || item.source || item.kb || '—',
    file: [item.kb ? kbLabel(item.kb) : '', item.source].filter(Boolean).join(' / ') || '—',
    snippet: item.text || '',
    score: formatEvidenceScore(item.score)
  }))
})

/* ── 消息操作 ───────────────────────────────────────────────────── */
async function copyMessage (msg: any): Promise<void> {
  const ok = await copyText(msg.text || '')
  if (ok) {
    message.success(t('modules.chatTest.copied'))
  } else {
    message.error(t('modules.chatTest.copyFailed'))
  }
}

function toggleVote (msg: any, value: number): void {
  const next = msg.vote === value ? 0 : value
  msg.vote = next
  // 只有「投出去」才确认；再点一次是取消，静默（否则每点一下都弹，像在刷屏）。
  // 除了图标变蓝，还要给出可见反馈，否则在长回答里几乎看不见。
  if (next !== 0) {
    message.success(t('modules.chatTest.voteThanks'))
  }
}

const question = ref('')
const messagesRef = ref<HTMLElement | null>(null)

async function scrollToBottom (): Promise<void> {
  await nextTick()
  const el = messagesRef.value
  if (el) {
    el.scrollTop = el.scrollHeight
  }
}

/**
 * 流式期间的自动滚动。**只在用户本来就贴着底部时才跟**：
 * 每来一帧就把视口拽到底，等于让人没法往上翻已经生成的内容。
 */
function autoScroll (): void {
  const el = messagesRef.value
  if (!el) {
    return
  }
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
  if (nearBottom) {
    scrollToBottom()
  }
}

// 发送 / 流式收帧 / 停止生成 / 失败分类（DOM 相关的三件事以回调注入）
const { sending, send, stopGenerating } = useChatStream({
  workflowId: selectedWorkflowId,
  workflowName: computed(() => selectedWorkflow.value?.name || ''),
  conversationId,
  messages,
  question,
  scrollToBottom,
  autoScroll,
  flushSession: () => flush(selectedWorkflowId.value)
})

const canSend = computed(() => !!selectedWorkflowId.value && !!question.value.trim() && !sending.value)

/**
 * 中文输入法组字期间按 Enter 是在「确认候选词」，不是「发送」——
 * 不拦的话打完一个字就把半截问题发出去了。`isComposing` 是标准属性，
 * keyCode 229 是部分浏览器在组字期间给出的值。
 */
function onEnterKey (event: KeyboardEvent): void {
  if (event.isComposing || event.keyCode === IME_COMPOSING_KEYCODE) {
    return
  }
  event.preventDefault()
  send()
}
</script>

<!-- 样式外置到同目录的 chat-test.less：视图文件只留编排与渲染。
     `scoped` 由 vue-loader 加在外部文件上，作用域与内联时一致。 -->
<style lang="less" scoped src="./chat.less"></style>
