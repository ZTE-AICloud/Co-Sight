<!--
  统一空态 / 加载态 / 错误态。

    <AppEmpty state="empty" :description="$t('public.noData')" />
    <AppEmpty state="loading" :title="$t('public.loading')" />
    <AppEmpty state="error" :description="message" @retry="load" />

  约定：
    - 空态：没有数据，不一定是错误；
    - 加载态：首次进入、尚无任何内容时使用（表格内的局部刷新走表格自身的 loading）；
    - 错误态：取数失败，提供重试入口。
  默认按钮用 Default 而不是 Primary —— 页面主操作只允许一个 Primary Button。
-->
<template>
  <div
    class="app-empty"
    :class="[`app-empty--${state}`, { 'app-empty--compact': compact }]"
    :role="state === 'error' ? 'alert' : 'status'"
    :aria-busy="state === 'loading' ? 'true' : 'false'"
  >
    <div class="app-empty__visual" aria-hidden="true">
      <el-icon v-if="state === 'loading'" class="app-empty__spinner is-loading">
        <Loading />
      </el-icon>
      <el-icon v-else-if="state === 'error'" class="app-empty__icon app-empty__icon--error">
        <WarningFilled />
      </el-icon>
      <el-icon v-else class="app-empty__icon">
        <EmptyData />
      </el-icon>
    </div>

    <p v-if="resolvedTitle" class="app-empty__title">
      <slot name="title">{{ resolvedTitle }}</slot>
    </p>
    <p v-if="resolvedDescription" class="app-empty__description">
      <slot name="description">{{ resolvedDescription }}</slot>
    </p>

    <div v-if="$slots.default || canRetry" class="app-empty__actions">
      <slot />
      <el-button
        v-if="canRetry"
        :icon="Refresh"
        @click="$emit('retry')"
      >
        {{ retryText || $t('public.retry') }}
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { EmptyData, Loading, Refresh, WarningFilled } from '@/shared/lib/icons'
import { $t } from '@/app/i18n/i18n.js'

const props = defineProps({
  /** empty / loading / error */
  state: {
    type: String,
    default: 'empty',
    validator: value => ['empty', 'loading', 'error'].includes(value)
  },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  retryText: { type: String, default: '' },
  /** 紧凑模式：表格内空态使用 */
  compact: { type: Boolean, default: false }
})

defineEmits(['retry'])

const canRetry = computed(() => props.state === 'error')

const resolvedTitle = computed(() => {
  if (props.title) {
    return props.title
  }
  if (props.state === 'loading') {
    return $t('public.loading')
  }
  if (props.state === 'error') {
    return $t('public.loadFailed')
  }
  return props.description ? '' : $t('public.noData')
})

const resolvedDescription = computed(() => {
  if (props.description) {
    return props.description
  }
  if (props.state === 'error') {
    return $t('public.loadFailedTip')
  }
  return ''
})
</script>

<style scoped>
.app-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  min-height: 240px;
  padding: 32px 24px;
  text-align: center;
  color: var(--rs-text-2);
}

.app-empty--compact {
  min-height: 160px;
  padding: 24px 16px;
}

.app-empty__visual {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  margin-bottom: 4px;
  border-radius: var(--rs-radius);
  background: var(--rs-bg-soft);
  color: var(--rs-text-3);
}

.app-empty--compact .app-empty__visual {
  width: 40px;
  height: 40px;
}

.app-empty__icon {
  font-size: 24px;
}

.app-empty--compact .app-empty__icon {
  font-size: 20px;
}

.app-empty__icon--error {
  color: var(--rs-danger);
}

.app-empty__spinner {
  font-size: 22px;
  color: var(--rs-primary);
}

.app-empty__title {
  margin: 0;
  color: var(--rs-text);
  font-size: var(--rs-font-size-body);
  font-weight: 500;
  line-height: normal;
}

.app-empty__description {
  margin: 0;
  max-width: 520px;
  color: var(--rs-text-2);
  font-size: var(--rs-font-size-body);
  line-height: normal;
}

.app-empty__actions {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
</style>
