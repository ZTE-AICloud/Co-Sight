<template>
  <section class="chat-history content-card" :aria-label="$t('modules.chatTest.historyTitle')">
    <div class="history-heading">
      <div class="history-heading-title">
        <h2 class="text-section-title">{{ $t('modules.chatTest.historyTitle') }}</h2>
        <span class="history-count text-caption">{{ total }}</span>
      </div>
      <el-dropdown trigger="click" placement="bottom-end" @command="$emit('manage', $event)">
        <button type="button" class="icon-button history-more" :aria-label="$t('modules.chatTest.historyManage')">
          <MoreFilled />
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="export" :disabled="!total">
              <Download />{{ $t('modules.chatTest.exportAllSessions') }}
            </el-dropdown-item>
            <el-dropdown-item class="danger-menu-item" command="clear" :disabled="!total" divided>
              <Delete />{{ $t('modules.chatTest.clearHistory') }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
    <el-input
      v-model="search"
      clearable
      :placeholder="$t('modules.chatTest.searchHistory')"
      :aria-label="$t('modules.chatTest.searchHistory')"
      :prefix-icon="Search"
    />
    <div v-if="histories.length" class="history-list" role="list" :aria-label="$t('modules.chatTest.historyList')">
      <div
        v-for="history in histories"
        :key="history.conversationId"
        :class="['history-item', { active: activeId === history.conversationId }]"
        role="listitem"
      >
        <button
          type="button"
          class="history-select"
          :aria-label="$t('modules.chatTest.openSession', { name: history.title })"
          :aria-pressed="activeId === history.conversationId"
          @click="$emit('select', history)"
        >
          <span class="history-name text-secondary" :title="history.title">{{ history.title }}</span>
          <span class="history-meta text-caption">
            <span v-if="history.pinned" class="history-pin"><Top />{{ $t('modules.chatTest.pinned') }}</span>
            <span class="history-date">{{ timeLabel(history.savedAt) }}</span>
          </span>
        </button>
        <el-dropdown
          class="history-actions"
          trigger="click"
          placement="bottom-end"
          @command="command => $emit('action', command, history)"
        >
          <button type="button" class="icon-button history-more" :aria-label="$t('modules.chatTest.sessionActions', { name: history.title })">
            <MoreFilled class="more-icon" />
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="pin">
                <Top />{{ history.pinned ? $t('modules.chatTest.unpinSession') : $t('modules.chatTest.pinSession') }}
              </el-dropdown-item>
              <el-dropdown-item command="rename"><Edit />{{ $t('modules.chatTest.renameSession') }}</el-dropdown-item>
              <el-dropdown-item command="export"><Download />{{ $t('modules.chatTest.exportSession') }}</el-dropdown-item>
              <el-dropdown-item command="delete" class="danger-menu-item" divided><Delete />{{ $t('modules.chatTest.deleteSession') }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>
    <div v-else class="history-empty">
      <ChatDotRound />
      <strong class="text-secondary">{{ total ? $t('modules.chatTest.noMatchingSession') : $t('modules.chatTest.historyEmpty') }}</strong>
      <p class="text-caption">{{ total ? $t('modules.chatTest.noMatchingSessionDesc') : $t('modules.chatTest.historyEmptyDesc') }}</p>
      <el-button v-if="search" link type="primary" @click="search = ''">{{ $t('modules.chatTest.clearSearch') }}</el-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { MoreFilled, Search, Download, Delete, Top, Edit, ChatDotRound } from '@/shared/lib/icons'

interface SessionSummary {
  conversationId: string
  savedAt: number
  title: string
  messageCount: number
  pinned: boolean
}

defineProps({
  histories: { type: Array as () => SessionSummary[], default: () => [] },
  total: { type: Number, default: 0 },
  activeId: { type: String, default: '' }
})
defineEmits(['select', 'action', 'manage'])

const search = defineModel<string>('search', { type: String, default: '' })

function timeLabel (savedAt: number): string {
  if (!savedAt) {
    return ''
  }
  const date = new Date(savedAt)
  const pad = (value: number): string => String(value).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
</script>

<style scoped>
.chat-history { display: flex; flex-direction: column; min-width: 0; min-height: 0; padding: 16px 10px; overflow: hidden; }
.history-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin: 0 4px 16px; }
.history-heading-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.history-heading h2 { margin: 0; color: var(--rs-text); }
.history-count { display: inline-flex; justify-content: center; align-items: center; min-width: 22px; height: 22px; padding: 0 6px; border-radius: 6px; background: var(--rs-bg-soft); color: var(--rs-text-3); font-variant-numeric: tabular-nums; }
.chat-history > .el-input { width: calc(100% - 8px); margin: 0 4px 12px; }
.chat-history :deep(.el-input__wrapper) { padding-left: 10px; }
.history-list { overflow-y: auto; padding: 1px 4px 4px; min-height: 0; scrollbar-width: thin; }
.history-item { position: relative; display: flex; align-items: center; gap: 2px; margin-top: 4px; border: 1px solid transparent; border-radius: 8px; transition: background .15s; }
.history-item:hover { background: var(--rs-bg-hover); }
.history-item.active { background: var(--rs-bg-selected); border-color: color-mix(in srgb, var(--rs-primary) 16%, var(--rs-border-soft)); }
.history-item.active::before { content: ''; position: absolute; left: -5px; top: 17px; bottom: 17px; width: 3px; border-radius: 2px; background: var(--rs-primary); }
.history-select { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 7px; min-height: 72px; padding: 12px 0 12px 10px; border: 0; border-radius: 7px; background: transparent; color: var(--rs-text); text-align: left; }
.history-name { display: block; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.history-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; color: var(--rs-text-3); }
.history-date { white-space: nowrap; font-size: var(--rs-font-size-caption); }
.history-pin { display: inline-flex; align-items: center; gap: 2px; color: var(--rs-primary); }
.history-pin svg { width: 11px; height: 11px; }
.history-actions { align-self: flex-start; margin: 10px 4px 0 0; flex-shrink: 0; }
.history-more { color: var(--rs-text-3); width: 26px; height: 28px; }
.history-more svg { width: 16px; height: 16px; }
.history-more:hover, .history-more[aria-expanded='true'] { color: var(--rs-primary); background: color-mix(in srgb, var(--rs-primary) 10%, var(--rs-bg-card)); }
.history-empty { display: flex; flex-direction: column; align-items: center; padding: 36px 8px; text-align: center; color: var(--rs-text-3); }
.history-empty > svg { width: 28px; height: 28px; margin-bottom: 12px; color: var(--rs-border); }
.history-empty strong { color: var(--rs-text-2); font-weight: 500; }
.history-empty p { margin: 6px 0 12px; }
</style>
