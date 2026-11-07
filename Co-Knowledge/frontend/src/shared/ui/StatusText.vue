<!--
  状态指示。

  Element Plus 没有 Status 组件 —— `<el-status>` 是未注册元素，只有默认插槽里的文字
  还渲染得出来，颜色/圆点/图标全丢。按调用点实际用到的四种形态补最小实现：

  | 调用点 | 形态 |
  |---|---|
  | `<el-status type="error" />`（无内容） | 只有圆点 |
  | `type="custom" :color="..."` | 指定颜色的文字 |
  | `type="custom" :icon="X" color="..."` | 指定颜色的图标 + 文字 |
  | `:type="info|warning|success"` | 语义色圆点 + 文字 |

  `#prefix` 插槽优先于内置圆点/图标（导入页用它塞了主题自带的 `plx-ico-*` 图标）。
-->
<template>
  <span class="status-text" :class="{ 'status-text--small': size === 'small' }" :style="colorStyle">
    <slot name="prefix">
      <el-icon v-if="icon" class="status-text__icon">
        <component :is="icon" />
      </el-icon>
      <span v-else-if="dotColor" class="status-text__dot" :style="{ backgroundColor: dotColor }" />
    </slot>
    <slot>{{ text }}</slot>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps({
  /** `custom` = 用 color 直接上色；其余取值按语义色处理（info / warning / success / error） */
  type: { type: String, default: 'custom' },
  /** 自定义颜色，用于 type="custom" */
  color: { type: String, default: '' },
  /** 自定义图标组件（Element Plus 图标） */
  icon: { type: [Object, Function], default: null },
  /** 文本（也可用默认插槽） */
  text: { type: String, default: '' },
  size: { type: String, default: '' }
})

const TYPE_COLORS: Record<string, string> = {
  info: 'var(--el-color-info)',
  warning: 'var(--el-color-warning)',
  success: 'var(--el-color-success)',
  error: 'var(--el-color-danger)',
  danger: 'var(--el-color-danger)'
}

/** 文字/图标颜色：显式 color 优先；语义 type 取对应色；都没有则不干预（跟随父级） */
const resolvedColor = computed(() => {
  if (props.color) {
    return props.color
  }
  return TYPE_COLORS[props.type] || ''
})

const colorStyle = computed(() => (resolvedColor.value ? { color: resolvedColor.value } : {}))

/**
 * 是否画圆点：只有语义 type（info/warning/success/error）才画 ——
 * `type="custom"` 的调用点要么自带图标、要么只用颜色标文字，不该多出一个点。
 */
const dotColor = computed(() => {
  if (props.icon) {
    return ''
  }
  return TYPE_COLORS[props.type] || ''
})
</script>

<style lang="less" scoped>
.status-text {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  line-height: 1.4;

  &--small {
    font-size: 12px;
  }

  &__icon {
    font-size: 14px;
  }

  &__dot {
    flex: none;
    width: 6px;
    height: 6px;
    border-radius: 50%;
  }
}
</style>
