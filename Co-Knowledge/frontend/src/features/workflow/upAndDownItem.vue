<template>
  <div class="up-down-item flex-box--align-center">
    <tableIcon
      :disabled="index === 0"
      icon-class="plx-ico-up-16 ai-button-icon--primary"
      :tips="aipVueInstance.$t('public.up')"
      @click="upHandle"
    />
    <tableIcon
      :disabled="index === lastIndex"
      icon-class="plx-ico-down-16 ai-button-icon--primary el-space-xs-l"
      :tips="aipVueInstance.$t('public.down')"
      @click="downHandle"
    />
    <div class="flex-1 el-space-sm-l">
      {{ inputVariable.label }}
    </div>
    <tableIcon
      v-show="isMode"
      icon-class="plx-ico-delete-16 ai-button-icon--primary el-space-md-l"
      :tips="aipVueInstance.$t('public.delete')"
      @click="deleteHandle"
    />
  </div>
</template>

<script setup lang="ts">
import TableIcon from '@/shared/ui/TableIcon.vue';
import { onMounted, ref, onBeforeUnmount } from 'vue';
import { InputVariable } from '@/shared/types/app'
import { EventBus } from '@/shared/events.js';
const aipVueInstance = window.aipVueInstance;
interface Props {
  inputVariable: InputVariable,
  index: number,
  lastIndex: number,
  // node通过props的方式传递的最新的是否处于编辑态信息
  isMode:boolean
}
const isEditMode = ref()
onMounted(() => {
  EventBus.on('isEditMode', (msg) => {
    isEditMode.value = msg;
  });
})
onBeforeUnmount(() => {
  EventBus.off('isEditMode');
})
withDefaults(defineProps<Props>(), {
  inputVariable: {
    key: 'text',
    label: 'INPUT',
    sourceNode: 'node_id_001'
  },
  index: 0,
  lastIndex: 0,
  isMode: false
})

const emit = defineEmits<{
  (e: 'upHandle'):void,
  (e: 'downHandle'):void,
  (e: 'deleteHandle'):void,
}>()

function upHandle () {
  emit('upHandle')
}
function downHandle () {
  emit('downHandle')
}
function deleteHandle () {
  emit('deleteHandle')
}

</script>

<style scoped lang="less">
.up-down-item {
  width: 100%;
  :deep(.plx-ico-delete-16) {
    display: none;
  }
  &:hover {
    :deep(.plx-ico-delete-16) {
      display: inline-block;
    }
  }
}
</style>
