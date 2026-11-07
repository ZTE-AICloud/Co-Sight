<template>
  <el-dialog
    v-model="dialogVisible"
    :title="$t('modules.kbWorkspace.graphEditor.selectEntityType')"
    width="500px"
    :before-close="handleClose"
  >
    <div class="node-palette">
      <div class="node-grid">
        <div
          v-for="nodeType in nodeTypes"
          :key="nodeType.type"
          class="node-item"
          @click="handleSelectNode(nodeType.type)"
        >
          <div class="node-icon">
            <div class="circle-node" :style="{ backgroundColor: nodeType.color }">
              {{ nodeType.icon }}
            </div>
          </div>
          <div class="node-info">
            <div class="node-name">{{ nodeType.label }}</div>
            <div class="node-desc">{{ nodeType.description }}</div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <span>
        <el-button @click="handleClose">{{ $t('public.cancel') }}</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, getCurrentInstance } from 'vue'

const { proxy } = getCurrentInstance() as any

interface NodeType {
  type: string
  label: string
  icon: string
  color: string
  description: string
}

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits(['update:visible', 'add-node'])

// 节点类型定义（文案走 i18n，故用 computed —— 切语言时能跟着变）
const nodeTypes = computed<NodeType[]>(() => [
  {
    type: 'entity',
    label: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeEntity'),
    icon: '🔵',
    color: '#5F95FF',
    description: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeEntityDesc')
  },
  {
    type: 'fault',
    label: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeFault'),
    icon: '🔴',
    color: '#FF4D4F',
    description: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeFaultDesc')
  },
  {
    type: 'event',
    label: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeEvent'),
    icon: '🟡',
    color: '#FAAD14',
    description: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeEventDesc')
  },
  {
    type: 'resource',
    label: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeResource'),
    icon: '🟢',
    color: '#52C41A',
    description: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeResourceDesc')
  },
  {
    type: 'rootCause',
    label: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeRootCause'),
    icon: '🟣',
    color: '#722ED1',
    description: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeRootCauseDesc')
  },
  {
    type: 'plan',
    label: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypePlan'),
    icon: '🟠',
    color: '#FA8C16',
    description: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypePlanDesc')
  },
  {
    type: 'examItem',
    label: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeExamItem'),
    icon: '🔘',
    color: '#8C8C8C',
    description: proxy.$t('modules.kbWorkspace.graphEditor.nodeTypeExamItemDesc')
  }
])

// 计算属性
const dialogVisible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value)
})

// 事件处理
const handleSelectNode = (nodeType: string) => {
  emit('add-node', nodeType)
  dialogVisible.value = false
}

const handleClose = () => {
  dialogVisible.value = false
}
</script>

<style lang="less" scoped>
.node-palette {
  .node-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    max-height: 400px;
    overflow-y: auto;
  }

  .node-item {
    display: flex;
    align-items: center;
    padding: 16px;
    border: 1px solid var(--rs-border);
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.3s ease;

    &:hover {
      border-color: var(--rs-primary);
      background-color: var(--rs-bg-selected);
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(95, 149, 255, 0.15);
    }

    .node-icon {
      margin-right: 12px;
      flex-shrink: 0;

      .circle-node {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 20px;
        color: white;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
      }
    }

    .node-info {
      flex: 1;
      min-width: 0;

      .node-name {
        font-weight: 500;
        color: var(--rs-text);
        margin-bottom: 4px;
        font-size: 14px;
      }

      .node-desc {
        color: var(--rs-text-3);
        font-size: 12px;
        line-height: 1.4;
      }
    }
  }
}

// 滚动条样式
.node-grid::-webkit-scrollbar {
  width: 6px;
}

.node-grid::-webkit-scrollbar-track {
  background: var(--rs-bg-soft);
  border-radius: 3px;
}

.node-grid::-webkit-scrollbar-thumb {
  background: var(--rs-border);
  border-radius: 3px;
}

.node-grid::-webkit-scrollbar-thumb:hover {
  background: var(--rs-text-3);
}
</style> 