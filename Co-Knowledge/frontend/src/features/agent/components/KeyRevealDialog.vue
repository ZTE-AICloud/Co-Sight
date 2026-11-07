<template>
  <el-dialog
    v-model="dialogVisible"
    :title="$t('modules.remoteAccess.revealTitle')"
    width="620px"
    :append-to-body="true"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    @closed="clear"
  >
    <el-alert type="warning" :closable="false" show-icon>
      {{ $t('modules.remoteAccess.revealWarning') }}
    </el-alert>

    <div class="reveal-key">
      <div class="reveal-key__label">{{ $t('modules.remoteAccess.revealKeyLabel') }}</div>
      <code class="reveal-key__value">{{ plaintextKey }}</code>
      <el-button type="primary" plain size="small" @click="copyHandle">
        {{ copied ? $t('modules.remoteAccess.revealCopied') : $t('modules.remoteAccess.revealCopy') }}
      </el-button>
    </div>

    <dl v-if="keyInfo" class="reveal-meta">
      <div>
        <dt>{{ $t('modules.remoteAccess.columnName') }}</dt>
        <dd>{{ keyInfo.name }}</dd>
      </div>
      <div>
        <dt>{{ $t('modules.remoteAccess.columnPrefix') }}</dt>
        <dd><code>{{ keyInfo.keyPrefix }}</code></dd>
      </div>
      <div>
        <dt>{{ $t('modules.remoteAccess.columnExpiresAt') }}</dt>
        <dd>{{ formatDateTime(keyInfo.expiresAt) || $t('modules.remoteAccess.neverExpires') }}</dd>
      </div>
    </dl>

    <template #footer>
      <el-button type="primary" @click="dialogVisible = false">
        {{ $t('modules.remoteAccess.revealDone') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import message from '@/shared/lib/message'
import { $t } from '@/app/i18n/i18n.js'
import { copyText } from '@/shared/lib/clipboard'
import { formatDateTime } from '../lib/helpers'

const dialogVisible = ref(false)
const plaintextKey = ref('')
const keyInfo = ref(null)
const copied = ref(false)

/**
 * @param {{ key: object, plaintextKey: string }} result 创建接口的 `bo`
 */
function open (result) {
  plaintextKey.value = result?.plaintextKey || ''
  keyInfo.value = result?.key || null
  copied.value = false
  dialogVisible.value = true
}

function clear () {
  // 明文不留在内存/浏览器存储里：关闭即清空。
  plaintextKey.value = ''
  keyInfo.value = null
  copied.value = false
}

async function copyHandle () {
  const ok = await copyText(plaintextKey.value)
  if (ok) {
    copied.value = true
    message.success($t('modules.remoteAccess.revealCopied'))
  } else {
    message.error($t('modules.remoteAccess.copyFailed'))
  }
}

defineExpose({ open })
</script>

<style scoped lang="less">
.reveal-key {
  margin-top: 16px;
  padding: 14px 16px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--rs-bg-soft);
}

.reveal-key__label {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--rs-text-3);
}

.reveal-key__value {
  display: block;
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 6px;
  background: #111827;
  color: #f9fafb;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
  user-select: all;
}

.reveal-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 18px 0 0;

  div {
    min-width: 0;
  }

  dt {
    font-size: 11px;
    color: var(--rs-text-3);
  }

  dd {
    margin: 4px 0 0;
    overflow: hidden;
    font-size: 12px;
    color: var(--rs-text-2);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  code {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  }
}
</style>
