<template>
  <StudioDialog
    v-model="open"
    dialog-class="delete-confirm-dialog"
    width="560px"
    :title="title || $t('public.deleteConfirm.title', { resourceType })"
    :subtitle="subtitle || $t('public.deleteConfirm.subtitle')"
    :icon="Delete"
    :hint="hint || $t('public.deleteConfirm.defaultHint')"
    @opened="focusInitial"
  >
    <div class="delete-confirm-content">
      <div class="delete-confirm-warning" role="note">
        <WarningFilled />
        <div>
          <strong class="text-body">{{ warning }}</strong>
          <p class="text-secondary">{{ description }}</p>
        </div>
      </div>

      <section class="delete-confirm-summary" :aria-label="$t('public.deleteConfirm.pending', { resourceType })">
        <div v-if="items.length > 1" class="delete-confirm-batch-heading text-secondary">
          <span>{{ $t('public.deleteConfirm.pending', { resourceType }) }}</span>
          <span class="tag-soft">{{ $t('public.deleteConfirm.batchCount', { count: items.length }) }}</span>
        </div>
        <ul class="delete-confirm-items" :class="{ 'is-batch': items.length > 1 }">
          <li v-for="(item, index) in items" :key="item.id ?? index" class="delete-confirm-identity">
            <span :class="['avatar-square', item.av || 'av-blue']">
              <component v-if="!item.letter" :is="resourceIcon" />
              <template v-else>{{ item.letter }}</template>
            </span>
            <div class="delete-confirm-name">
              <span v-if="items.length === 1" class="text-caption">{{ $t('public.deleteConfirm.pending', { resourceType }) }}</span>
              <h3 class="text-section-title">{{ item.name }}</h3>
              <code v-if="item.meta" class="text-caption">{{ item.meta }}</code>
            </div>
            <span v-if="item.tag" class="tag-soft blue delete-confirm-kind">{{ item.tag }}</span>
          </li>
        </ul>
        <div v-if="detail" class="delete-confirm-endpoint text-caption">
          <InfoFilled />
          <span>{{ detail }}</span>
        </div>
        <p v-if="note" class="delete-confirm-default text-caption">
          <InfoFilled />{{ note }}
        </p>
      </section>

      <DeleteVerification
        v-if="verification"
        ref="verificationRef"
        @update:verified="verified = $event"
        @submit="confirmDelete"
      />
    </div>
    <template #actions>
      <el-button ref="cancelButton" @click="open = false">{{ $t('public.cancel') }}</el-button>
      <el-button
        class="delete-confirm-submit"
        type="danger"
        :disabled="!items.length || (verification && !verified)"
        @click="confirmDelete"
      >
        <Delete />{{ confirmText || $t('public.delete') }}
      </el-button>
    </template>
  </StudioDialog>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
  Delete, WarningFilled, InfoFilled,
  Document, Share, Key, Connection, SetUp, Box
} from '@element-plus/icons-vue'
import StudioDialog from '@/shared/ui/StudioDialog.vue'
import DeleteVerification from '@/shared/ui/DeleteVerification.vue'
import { $t } from '@/app/i18n/i18n.js'

const open = defineModel({ type: Boolean, default: false })
const props = defineProps({
  resourceType: { type: String, default: () => $t('public.deleteConfirm.resource') },
  title: String,
  subtitle: String,
  warning: String,
  description: String,
  items: { type: Array, default: () => [] },
  detail: String,
  note: String,
  hint: String,
  verification: { type: Boolean, default: true },
  confirmText: String
})
const emit = defineEmits(['confirm'])
const verificationRef = ref()
const cancelButton = ref()
const verified = ref(false)

const resourceIcon = computed(() => ({
  [$t('public.deleteConfirm.resourceKb')]: Document,
  [$t('public.deleteConfirm.resourceGraphKb')]: Share,
  [$t('public.deleteConfirm.resourceKey')]: Key,
  [$t('public.deleteConfirm.resourceWorkflow')]: Connection,
  [$t('public.deleteConfirm.resourceNode')]: Connection,
  [$t('public.deleteConfirm.resourceEdge')]: Connection,
  [$t('public.deleteConfirm.resourceOperator')]: SetUp,
  [$t('public.deleteConfirm.resourceModel')]: Box
}[props.resourceType] || Document))

function focusInitial () {
  if (props.verification) {
    verificationRef.value?.focus()
  } else {
    cancelButton.value?.$el?.focus()
  }
}

watch([open, () => props.items], () => {
  verified.value = false
  if (open.value) {
    // 弹窗内容 destroy-on-close，重新打开时子组件会自生成新码；items 变化时显式重置。
    nextTick(() => verificationRef.value?.reset())
  }
}, { immediate: true })

function confirmDelete () {
  if (!open.value || !props.items.length || (props.verification && !verified.value)) {
    return
  }
  // 先关闭再通知调用方，避免重复提交。
  open.value = false
  emit('confirm')
}
</script>
