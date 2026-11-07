<template>
  <div class="saas">
    <router-view />
  </div>
  <DeleteConfirmDialog v-model="deletion.open" v-bind="deletion.options" @confirm="settleDeletion(true)" />
</template>

<script setup lang="ts">
import { getCurrentInstance, watch } from 'vue';
import DeleteConfirmDialog from '@/shared/ui/DeleteConfirmDialog.vue'
import { deletion, settleDeletion } from '@/shared/composables/deletion'
const { proxy } = getCurrentInstance() as any;

watch(
  () => proxy.$route,
  () => {
    try {
      const allTooltips = document.querySelectorAll('.el-tooltip__popper')
      Array.from(allTooltips).forEach(item => document.body.removeChild(item))
    } catch (error) {
      // 路由切换后的浮层清理是尽力而为：元素可能已被组件自身移除，失败无需处理
    }
  }
)

// 弹窗被关闭（取消 / ESC / 点遮罩）时结算 Promise；路由切换时取消未完成的确认。
watch(() => deletion.open, value => {
  if (!value) {
    settleDeletion(false)
  }
}, { flush: 'post' })
watch(() => proxy.$route.fullPath, () => settleDeletion(false))
</script>

<style lang="less" scoped>
/*
 * 5173 migration: `.saas` is only the full-height app root. Typography, colors
 * and the page canvas come from the prototype body/.page rules; do not set a
 * 12px baseline or page background here.
 */
.saas {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow: hidden;
  height: 100%;
}
</style>
