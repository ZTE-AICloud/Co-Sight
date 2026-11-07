<template>
  <section class="code-block">
    <header class="code-block__header">
      <span class="code-block__title">{{ title }}</span>
      <el-button text size="small" @click="copyHandle">
        {{ $t('modules.remoteAccess.copy') }}
      </el-button>
    </header>
    <pre class="code-block__pre"><code>{{ code }}</code></pre>
  </section>
</template>

<script setup>
import message from '@/shared/lib/message'
import { $t } from '@/app/i18n/i18n.js'
import { copyText } from '@/shared/lib/clipboard'

const props = defineProps({
  code: {
    type: String,
    default: ''
  },
  title: {
    type: String,
    default: ''
  }
})

async function copyHandle () {
  const ok = await copyText(props.code)
  if (ok) {
    message.success($t('modules.remoteAccess.copied'))
  } else {
    message.error($t('modules.remoteAccess.copyFailed'))
  }
}
</script>

<style scoped lang="less">
.code-block {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--rs-bg-soft);
  overflow: hidden;
}

.code-block__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 14px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--rs-bg-card);
}

.code-block__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--rs-text-2);
}

.code-block__pre {
  margin: 0;
  padding: 14px 16px;
  overflow: auto;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 13px;
  line-height: 1.7;
  color: var(--rs-text);
  white-space: pre;
}
</style>
