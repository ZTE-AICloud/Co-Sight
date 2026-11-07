<template>
  <div class="toolbar">
    <!-- 左侧：返回按钮和页面标题 -->
    <div class="toolbar-left">
      <el-button text @click="goBack" class="back-btn">
        <el-icon><ArrowLeft /></el-icon>
      </el-button>
      <div class="page-title">{{ displayTitle }}</div>
    </div>

    <!--
      中间：工具栏。

      Element Plus 没有 `<el-toolbar :tools>` 这个组件，
      而未注册元素渲染不出任何东西（按钮全在 tools prop 里，默认插槽是空的），所以整条工具栏
      是**空的**。这里按 tools 的契约就地实现：分隔符 '|'、图标按钮、以及带 popSlot 的
      弹层按钮（目前只有 delete 一个）；确认框内容直接内联。
    -->
    <div class="toolbar-center">
      <div class="editor-toolbar">
        <template v-for="(tool, index) in tools" :key="index">
          <span v-if="tool === '|'" class="editor-toolbar__divider" />
          <!-- 弹层按钮：不再套 el-tooltip —— tooltip 与 popover 会争同一个触发元素，
               这里用原生 title 给提示 -->
          <el-popover
            v-else-if="tool.popSlot"
            :ref="(el: any) => bindPopover(tool, el)"
            trigger="click"
            :width="240"
          >
            <template #reference>
              <button type="button" class="editor-toolbar__btn" :title="tool.tooltip">
                <component :is="tool.icon" />
              </button>
            </template>
            <!-- 删除确认弹窗（popSlot: 'delete' 的那个按钮弹它） -->
            <div class="popover-content">
              <p>{{ proxy.$t('modules.kb.confirmDeleteElements') }}</p>
              <div class="popover-actions">
                <el-button size="small" type="primary" @click="confirmDelete">{{ proxy.$t('public.confirm') }}</el-button>
                <el-button size="small" @click="closePopover">{{ proxy.$t('public.cancel') }}</el-button>
              </div>
            </div>
          </el-popover>
          <el-tooltip v-else :content="tool.tooltip" placement="top" :show-after="300">
            <button type="button" class="editor-toolbar__btn" @click="tool.callback()">
              <component :is="tool.icon" />
            </button>
          </el-tooltip>
        </template>
      </div>
    </div>

    <!-- 右侧保留空间 -->
    <div class="toolbar-right">
      <!-- 如果需要可以在这里添加其他按钮 -->
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, getCurrentInstance, h  } from 'vue'
import {
  ArrowLeft
} from '@/shared/lib/icons'
import ReturnIconUrl from '@/assets/return-16.svg'
import RecoveryIconUrl from '@/assets/recovery-16.svg'
import ExportIconUrl from '@/assets/export-16.svg'
import DeleteIconUrl from '@/assets/delete-16.svg'
import ZoomInIconUrl from '@/assets/zoom-in-16.svg'
import ZoomOutIconUrl from '@/assets/zoom-out-16.svg'
import FullScreenIconUrl from '@/assets/full-screen-16.svg'

const { proxy } = getCurrentInstance() as any

// 创建 SVG 图标组件 - 使用 img 标签渲染 SVG
const ReturnIconComponent = () => h('img', {
  src: ReturnIconUrl,
  style: 'width: 16px; height: 16px; display: inline-block;'
})
const RecoveryIconComponent = () => h('img', {
  src: RecoveryIconUrl,
  style: 'width: 16px; height: 16px; display: inline-block;'
})
const ExportIconComponent = () => h('img', {
  src: ExportIconUrl,
  style: 'width: 16px; height: 16px; display: inline-block;'
})
const DeleteIconComponent = () => h('img', {
  src: DeleteIconUrl,
  style: 'width: 16px; height: 16px; display: inline-block;'
})
const ZoomInIconComponent = () => h('img', {
  src: ZoomInIconUrl,
  style: 'width: 16px; height: 16px; display: inline-block;'
})
const ZoomOutIconComponent = () => h('img', {
  src: ZoomOutIconUrl,
  style: 'width: 16px; height: 16px; display: inline-block;'
})
const FullScreenIconComponent = () => h('img', {
  src: FullScreenIconUrl,
  style: 'width: 16px; height: 16px; display: inline-block;'
})

const emit = defineEmits([
  'undo', 'redo', 'delete',
  'zoom-in', 'zoom-out', 'fit-view', 'export-json', 'go-back'
])

const popover = ref()

// 添加props定义
const props = defineProps<{
  templateName?: string
}>()

// 计算显示的标题
const displayTitle = computed(() => {
  if (props.templateName && props.templateName.trim()) {
    return props.templateName
  }
  return proxy.$t('modules.kb.pleaseEnterTemplateNameInInfo')
})

// 工具栏配置
const tools = computed(() => [
  {
    icon: ReturnIconComponent,
    tooltip: proxy.$t('modules.kb.toolbarUndo'),
    callback: () => {
      emit('undo')
    }
  },
  {
    icon: RecoveryIconComponent,
    tooltip: proxy.$t('modules.kb.toolbarRedo'),
    callback: () => {
      emit('redo')
    }
  },
  '|', // 分隔符
  {
    icon: ExportIconComponent,
    tooltip: proxy.$t('modules.kb.toolbarExportJson'),
    callback: () => {
      emit('export-json')
    }
  },
  {
    icon: DeleteIconComponent,
    tooltip: proxy.$t('modules.kb.toolbarDelete'),
    popSlot: 'delete',
    callback: () => {
    }
  },
  '|', // 分隔符
  {
    icon: ZoomOutIconComponent,
    tooltip: proxy.$t('modules.kb.toolbarZoomIn'),
    callback: () => {
      emit('zoom-in')
    }
  },
  {
    icon: ZoomInIconComponent,
    tooltip: proxy.$t('modules.kb.toolbarZoomOut'),
    callback: () => {
      emit('zoom-out')
    }
  },
  {
    icon: FullScreenIconComponent,
    tooltip: proxy.$t('modules.kb.toolbarFitView'),
    callback: () => {
      emit('fit-view')
    }
  }
])

/**
 * 收集弹层按钮的 el-popover 实例（原 el-toolbar 的 `@popover-change` 语义）：
 * 父组件要靠它调 `.hide()` 关闭弹层，所以这里在 ref 就绪时把实例交出去。
 */
const bindPopover = (item, popoverRef) => {
  if (!popoverRef) {
    return
  }
  popover.value = popoverRef
}

const closePopover = () => {
  if (popover.value) {
    popover.value.hide()
  }
}

const confirmDelete = () => {
  emit('delete')
  closePopover()
}


const goBack = () => {
  // 通过 emit 通知父组件处理回退逻辑
  emit('go-back')
}
</script>

<style lang="less" scoped>
.toolbar {
  height: 50px;
  background: var(--rs-bg-card);
  border-bottom: 0px solid var(--rs-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 12px;

  .back-btn {
    padding: 8px;
    border-radius: 4px;

    &:hover {
      background-color: var(--rs-bg-hover);
    }
  }

  .page-title {
    font-size: 16px;
    font-weight: 500;
    color: var(--rs-text);
  }
}

.toolbar-center {
  display: flex;
  align-items: center;
  gap: 8px;
}

// 工具栏（就地实现，见模板注释）：图标按钮 + 分隔符
.editor-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;

  &__btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    border: none;
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
    transition: background-color 0.2s;

    &:hover {
      background-color: var(--el-color-primary-light-9);
    }
  }

  &__divider {
    width: 1px;
    height: 16px;
    margin: 0 8px;
    background-color: var(--el-color-info-light-4);
  }
}

/* .toolbar-right 由全局 styles/base.css 提供，不再复制。 */

// 弹窗内容样式
.popover-content {
  padding: 8px 0;

  p {
    margin: 0 0 12px 0;
    color: var(--rs-text-2);
    font-size: 14px;
  }
}

.popover-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

:deep(.el-dropdown-item) {
  font-size: 14px;

  &:hover {
    background-color: var(--rs-bg-soft);
  }
}
</style>
